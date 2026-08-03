"""Durable SQLite portal ledger for C4.

Each operation opens its own connection with proper pragmas, performs its
transaction, and closes the connection (WAL, no shared connection across
threads). Capability keys, capability URLs, payloads, and PII never touch the
ledger.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import (
    IdempotencyConflictError,
    LedgerError,
    StateTransitionError,
)

BUSY_TIMEOUT_MS = 5000

PREPARED = "prepared"
APPROVED = "approved"
PUBLISHING = "publishing"
PUBLISHED = "published"
PARTIAL = "partial"
BLOCKED = "blocked"
REVOKED = "revoked"
PURGED = "purged"

ALLOWED_TRANSITIONS = {
    PREPARED: frozenset({APPROVED, BLOCKED}),
    APPROVED: frozenset({PUBLISHING, BLOCKED}),
    PUBLISHING: frozenset({PUBLISHED, PARTIAL}),
    PARTIAL: frozenset({PUBLISHING, BLOCKED}),
    PUBLISHED: frozenset({REVOKED}),
    REVOKED: frozenset({PURGED}),
    BLOCKED: frozenset(),
    PURGED: frozenset(),
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS releases (
    releaseId           TEXT PRIMARY KEY,
    releaseHash         TEXT NOT NULL,
    releaseIntentHash   TEXT NOT NULL,
    sectionId           TEXT NOT NULL,
    publicationId       TEXT NOT NULL,
    snapshotMode        TEXT NOT NULL,
    portalMode          TEXT NOT NULL,
    portalAppVersion    TEXT NOT NULL,
    hostingProfileId    TEXT NOT NULL,
    objectCount         INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'prepared',
    createdAt           TEXT NOT NULL,
    updatedAt           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    approvalId      INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    releaseHash     TEXT NOT NULL,
    objectCount     INTEGER NOT NULL,
    approvedBy      TEXT NOT NULL,
    approvedAt      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'approved',
    UNIQUE(releaseId, releaseHash)
);

CREATE TABLE IF NOT EXISTS publish_runs (
    runId           INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    idempotencyKey  TEXT NOT NULL UNIQUE,
    hostingProfileId TEXT NOT NULL,
    publisherType   TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'publishing',
    startedAt       TEXT NOT NULL,
    completedAt     TEXT,
    receiptId       TEXT
);

CREATE TABLE IF NOT EXISTS published_objects (
    objectId        TEXT NOT NULL,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    projectionHash  TEXT NOT NULL,
    artifactHash    TEXT NOT NULL,
    deployedAt      TEXT NOT NULL,
    PRIMARY KEY (releaseId, objectId)
);

CREATE TABLE IF NOT EXISTS receipts (
    receiptId       TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    payload         TEXT NOT NULL,
    createdAt       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lifecycle_events (
    eventId         INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL REFERENCES releases(releaseId),
    event           TEXT NOT NULL,
    actor           TEXT NOT NULL,
    reason          TEXT,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconciliation_events (
    eventId         INTEGER PRIMARY KEY AUTOINCREMENT,
    releaseId       TEXT NOT NULL,
    finding         TEXT NOT NULL,
    action          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hosting_profiles (
    profileId       TEXT PRIMARY KEY,
    profileHash     TEXT NOT NULL,
    mode            TEXT NOT NULL,
    profileJson     TEXT NOT NULL,
    firstSeenAt     TEXT NOT NULL
);
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class PortalLedger:
    def __init__(self, db_path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db_path.parent.chmod(0o700)
        except OSError:
            pass
        conn = sqlite3.connect(str(self.db_path), timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        return conn

    def init(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    def close(self) -> None:
        """No-op for compatibility: connections are per-operation (WAL)."""

    def _row(self, conn, sql, params=()) -> Optional[sqlite3.Row]:
        cur = conn.execute(sql, params)
        return cur.fetchone()

    # ----- releases ------------------------------------------------------

    def record_release(
        self,
        release_id: str,
        release_hash: str,
        release_intent_hash: str,
        section_id: str,
        publication_id: str,
        snapshot_mode: str,
        portal_mode: str,
        portal_app_version: str,
        hosting_profile_id: str,
        object_count: int,
        now: Optional[str] = None,
    ) -> None:
        now = now or utc_now_iso()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO releases (
                    releaseId, releaseHash, releaseIntentHash, sectionId,
                    publicationId, snapshotMode, portalMode, portalAppVersion,
                    hostingProfileId, objectCount, status, createdAt, updatedAt
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                """,
                (
                    release_id, release_hash, release_intent_hash, section_id,
                    publication_id, snapshot_mode, portal_mode, portal_app_version,
                    hosting_profile_id, object_count, now, now,
                ),
            )
            conn.execute(
                "INSERT INTO lifecycle_events (releaseId, event, actor, at) VALUES (?, ?, ?, ?)",
                (release_id, "prepared", "system", now),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise LedgerError(f"Release already recorded: {release_id}") from exc
        finally:
            conn.close()

    def get_release(self, release_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = self._row(
                conn,
                "SELECT * FROM releases WHERE releaseId = ?",
                (release_id,),
            )
            return dict(row) if row else None
        finally:
            conn.close()

    def current_status(self, release_id: str) -> Optional[str]:
        conn = self._connect()
        try:
            row = self._row(
                conn,
                "SELECT status FROM releases WHERE releaseId = ?",
                (release_id,),
            )
            return row["status"] if row else None
        finally:
            conn.close()

    def transition(
        self,
        release_id: str,
        from_state: str,
        to_state: str,
        event: str,
        actor: str,
        reason: Optional[str] = None,
        now: Optional[str] = None,
    ) -> None:
        if to_state not in ALLOWED_TRANSITIONS.get(from_state, frozenset()):
            raise StateTransitionError(
                f"Transition {from_state} -> {to_state} is not allowed for release {release_id}."
            )
        now = now or utc_now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE releases SET status = ?, updatedAt = ? WHERE releaseId = ? AND status = ?",
                (to_state, now, release_id, from_state),
            )
            if cur.rowcount != 1:
                conn.rollback()
                row = self._row(conn, "SELECT status FROM releases WHERE releaseId = ?", (release_id,))
                actual = row["status"] if row else "unknown"
                raise StateTransitionError(
                    f"Cannot transition {release_id} from {from_state}: current state is {actual}."
                )
            conn.execute(
                "INSERT INTO lifecycle_events (releaseId, event, actor, reason, at) VALUES (?, ?, ?, ?, ?)",
                (release_id, event, actor, reason, now),
            )
            conn.commit()
        finally:
            conn.close()

    # ----- approvals -----------------------------------------------------

    def get_approval(self, release_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = self._row(
                conn,
                "SELECT * FROM approvals WHERE releaseId = ? ORDER BY approvalId DESC",
                (release_id,),
            )
            return dict(row) if row else None
        finally:
            conn.close()

    def record_approval(self, record) -> None:
        release = self.get_release(record.release_id)
        if release is None:
            raise LedgerError(f"Release not recorded: {record.release_id}")
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO approvals (releaseId, releaseHash, objectCount, approvedBy, approvedAt)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.release_id,
                    record.release_hash,
                    record.object_count,
                    record.approved_by,
                    record.approved_at,
                ),
            )
            cur = conn.execute(
                "UPDATE releases SET status = ?, updatedAt = ? WHERE releaseId = ? AND status = ?",
                (APPROVED, record.approved_at, record.release_id, PREPARED),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise StateTransitionError(
                    f"Release {record.release_id} is not in {PREPARED} state; cannot approve."
                )
            conn.execute(
                "INSERT INTO lifecycle_events (releaseId, event, actor, at) VALUES (?, ?, ?, ?)",
                (record.release_id, "approved", record.approved_by, record.approved_at),
            )
            conn.commit()
        finally:
            conn.close()

    # ----- publish -------------------------------------------------------

    def begin_publish(
        self,
        release_id: str,
        idempotency_key: str,
        hosting_profile_id: str,
        publisher_type: str,
        now: Optional[str] = None,
    ) -> int:
        now = now or utc_now_iso()
        release = self.get_release(release_id)
        if release is None:
            raise LedgerError(f"Release not recorded: {release_id}")
        conn = self._connect()
        try:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO publish_runs (
                        releaseId, idempotencyKey, hostingProfileId, publisherType,
                        state, startedAt
                    ) VALUES (?, ?, ?, ?, 'publishing', ?)
                    """,
                    (release_id, idempotency_key, hosting_profile_id, publisher_type, now),
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise IdempotencyConflictError(
                    f"idempotency key already claimed: {idempotency_key}"
                ) from exc
            run_id = cur.lastrowid
            cur = conn.execute(
                "UPDATE releases SET status = ?, updatedAt = ? WHERE releaseId = ? AND status = ?",
                (PUBLISHING, now, release_id, APPROVED),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise StateTransitionError(
                    f"Release {release_id} is not in {APPROVED} state; cannot publish."
                )
            conn.execute(
                "INSERT INTO lifecycle_events (releaseId, event, actor, at) VALUES (?, ?, ?, ?)",
                (release_id, "publishing", "system", now),
            )
            conn.commit()
            return run_id
        finally:
            conn.close()

    def get_publish_run(self, run_id: int) -> Optional[dict]:
        conn = self._connect()
        try:
            row = self._row(conn, "SELECT * FROM publish_runs WHERE runId = ?", (run_id,))
            return dict(row) if row else None
        finally:
            conn.close()

    def latest_publish_run(self, release_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = self._row(
                conn,
                "SELECT * FROM publish_runs WHERE releaseId = ? ORDER BY runId DESC",
                (release_id,),
            )
            return dict(row) if row else None
        finally:
            conn.close()

    def list_publish_runs(self, release_id: str) -> list:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM publish_runs WHERE releaseId = ? ORDER BY runId ASC",
                (release_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def complete_publish(
        self,
        run_id: int,
        release_id: str,
        deployed_objects: list,
        receipt_id: str,
        now: Optional[str] = None,
    ) -> None:
        now = now or utc_now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE publish_runs SET state = 'published', completedAt = ?, receiptId = ? "
                "WHERE runId = ? AND state IN ('publishing', 'partial')",
                (now, receipt_id, run_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise StateTransitionError(f"Publish run {run_id} is not in publishing/partial state.")
            for obj in deployed_objects:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO published_objects (
                        objectId, releaseId, projectionHash, artifactHash, deployedAt
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (obj["objectId"], release_id, obj["projectionHash"], obj["artifactHash"], now),
                )
            cur = conn.execute(
                "UPDATE releases SET status = ?, updatedAt = ? WHERE releaseId = ? AND status = ?",
                (PUBLISHED, now, release_id, PUBLISHING),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise StateTransitionError(
                    f"Release {release_id} is not in publishing state."
                )
            conn.execute(
                "INSERT INTO lifecycle_events (releaseId, event, actor, at) VALUES (?, ?, ?, ?)",
                (release_id, "published", "system", now),
            )
            conn.commit()
        finally:
            conn.close()

    def fail_publish(self, run_id: int, release_id: str, now: Optional[str] = None) -> None:
        now = now or utc_now_iso()
        conn = self._connect()
        try:
            cur = conn.execute(
                "UPDATE publish_runs SET state = 'partial', completedAt = ? "
                "WHERE runId = ? AND state = 'publishing'",
                (now, run_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise StateTransitionError(f"Publish run {run_id} is not in publishing state.")
            cur = conn.execute(
                "UPDATE releases SET status = ?, updatedAt = ? WHERE releaseId = ? AND status = ?",
                (PARTIAL, now, release_id, PUBLISHING),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise StateTransitionError(f"Release {release_id} is not in publishing state.")
            conn.execute(
                "INSERT INTO lifecycle_events (releaseId, event, actor, at) VALUES (?, ?, ?, ?)",
                (release_id, "partial", "system", now),
            )
            conn.commit()
        finally:
            conn.close()

    # ----- receipts ------------------------------------------------------

    def record_receipt(self, receipt: dict) -> None:
        import json as _json

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO receipts (receiptId, type, releaseId, payload, createdAt) VALUES (?, ?, ?, ?, ?)",
                (receipt["receiptId"], receipt["type"], receipt["releaseId"],
                 _json.dumps(receipt), receipt.get("createdAt") or utc_now_iso()),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise LedgerError(f"Receipt already recorded: {receipt['receiptId']}") from exc
        finally:
            conn.close()

    def get_receipt(self, receipt_id: str) -> Optional[dict]:
        conn = self._connect()
        try:
            row = self._row(conn, "SELECT payload FROM receipts WHERE receiptId = ?", (receipt_id,))
            if row is None:
                return None
            import json

            return json.loads(row["payload"])
        finally:
            conn.close()

    # ----- hosting profiles ----------------------------------------------

    def register_hosting_profile(self, profile) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO hosting_profiles (profileId, profileHash, mode, profileJson, firstSeenAt)
                VALUES (?, ?, ?, ?, ?)
                """,
                (profile.profile_id, profile.profile_hash, profile.mode,
                 str(profile.to_dict()), utc_now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    # ----- reconciliation / events ---------------------------------------

    def record_reconciliation_event(self, release_id: str, finding: str, action: str, actor: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO reconciliation_events (releaseId, finding, action, actor, at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (release_id, finding, action, actor, utc_now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def lifecycle_events(self, release_id: str) -> list:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM lifecycle_events WHERE releaseId = ? ORDER BY eventId",
                (release_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ----- integrity -----------------------------------------------------

    def integrity_check(self) -> list:
        conn = self._connect()
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            return [row[0] for row in rows]
        finally:
            conn.close()

    def foreign_key_check(self) -> list:
        conn = self._connect()
        try:
            rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            return [dict(zip(("table", "rowid", "parent", "fkid"), row)) for row in rows]
        finally:
            conn.close()
