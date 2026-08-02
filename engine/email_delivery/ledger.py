"""Durable SQLite email ledger for C3 email delivery."""

from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import DeliveryStateError, IdempotencyConflictError, LedgerError
from .models import ApprovalRecord, BatchRunSummary, DeliveryRecord, DeliveryState

BUSY_TIMEOUT_MS = 5000

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plans (
    planId              TEXT PRIMARY KEY,
    sectionId           TEXT NOT NULL,
    publicationId       TEXT NOT NULL,
    snapshotContentHash TEXT NOT NULL,
    snapshotReviewHash  TEXT NOT NULL,
    snapshotMode        TEXT NOT NULL,
    templateId          TEXT NOT NULL,
    templateVersion     TEXT NOT NULL,
    templateHash        TEXT NOT NULL,
    intent              TEXT NOT NULL,
    senderProfileId     TEXT NOT NULL,
    fromAddress         TEXT NOT NULL,
    replyTo             TEXT,
    previewHash         TEXT NOT NULL,
    recipientCount      INTEGER NOT NULL,
    planPath            TEXT NOT NULL,
    createdAt           TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    CHECK (recipientCount > 0)
);

CREATE TABLE IF NOT EXISTS approvals (
    approvalId      INTEGER PRIMARY KEY AUTOINCREMENT,
    planId          TEXT NOT NULL REFERENCES plans(planId),
    previewHash     TEXT NOT NULL,
    recipientCount  INTEGER NOT NULL,
    approvedBy      TEXT NOT NULL,
    approvedAt      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'approved',
    UNIQUE(planId, previewHash)
);

CREATE TABLE IF NOT EXISTS deliveries (
    deliveryId          INTEGER PRIMARY KEY AUTOINCREMENT,
    planId              TEXT NOT NULL REFERENCES plans(planId),
    studentId           TEXT NOT NULL,
    idempotencyKey      TEXT NOT NULL UNIQUE,
    normalizedRecipient TEXT NOT NULL,
    maskedRecipient     TEXT NOT NULL,
    identityProjectionHash TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'reserved',
    attemptCount        INTEGER NOT NULL DEFAULT 0,
    lastAttemptAt       TEXT,
    providerMessageId   TEXT,
    clientMessageId     TEXT NOT NULL,
    createdAt           TEXT NOT NULL,
    updatedAt           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    attemptId       INTEGER PRIMARY KEY AUTOINCREMENT,
    deliveryId      INTEGER NOT NULL REFERENCES deliveries(deliveryId),
    attemptNumber   INTEGER NOT NULL,
    stateBefore     TEXT NOT NULL,
    stateAfter      TEXT NOT NULL,
    transportCode   TEXT,
    errorClass      TEXT,
    deliveryCertainty TEXT,
    providerMessageId TEXT,
    clientMessageId TEXT,
    attemptedAt     TEXT NOT NULL,
    UNIQUE(deliveryId, attemptNumber)
);

CREATE TABLE IF NOT EXISTS template_versions (
    templateId      TEXT NOT NULL,
    templateVersion TEXT NOT NULL,
    templateHash    TEXT NOT NULL,
    firstSeenAt     TEXT NOT NULL,
    PRIMARY KEY (templateId, templateVersion)
);

CREATE TABLE IF NOT EXISTS reconciliation_events (
    eventId         INTEGER PRIMARY KEY AUTOINCREMENT,
    planId          TEXT NOT NULL,
    deliveryId      INTEGER REFERENCES deliveries(deliveryId),
    studentId       TEXT,
    idempotencyKey  TEXT,
    fromState       TEXT NOT NULL,
    toState         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    actor           TEXT NOT NULL,
    reconciledAt    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_runs (
    batchRunId      INTEGER PRIMARY KEY AUTOINCREMENT,
    planId          TEXT NOT NULL REFERENCES plans(planId),
    previewHash     TEXT NOT NULL,
    transportType   TEXT NOT NULL,
    startedAt       TEXT NOT NULL,
    completedAt     TEXT,
    totalRecipients INTEGER NOT NULL,
    sentCount       INTEGER NOT NULL DEFAULT 0,
    failedCount     INTEGER NOT NULL DEFAULT 0,
    ambiguousCount  INTEGER NOT NULL DEFAULT 0,
    skippedCount    INTEGER NOT NULL DEFAULT 0,
    outcome         TEXT,
    actor           TEXT NOT NULL
);
"""

LEDGER_VERSION_KEY = "c3_email_ledger_version"
LEDGER_VERSION = "1.0.0"


class EmailLedger:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db_path.parent.chmod(0o700)
        except OSError:
            pass
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        try:
            os.chmod(str(self.db_path), 0o600)
        except OSError:
            pass
        self._conn = conn
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._connect()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self._connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def register_plan(self, plan_id: str, section_id: str, publication_id: str,
                      snapshot_content_hash: str, snapshot_review_hash: str,
                      snapshot_mode: str, template_id: str, template_version: str,
                      template_hash: str, intent: str, sender_profile_id: str,
                      from_address: str, reply_to: Optional[str],
                      preview_hash: str, recipient_count: int,
                      plan_path: str) -> None:
        now = self._now()
        with self.conn:
            self.conn.execute(
                """INSERT OR IGNORE INTO plans
                   (planId, sectionId, publicationId, snapshotContentHash, snapshotReviewHash,
                    snapshotMode, templateId, templateVersion, templateHash, intent,
                    senderProfileId, fromAddress, replyTo, previewHash, recipientCount,
                    planPath, createdAt, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (plan_id, section_id, publication_id, snapshot_content_hash, snapshot_review_hash,
                 snapshot_mode, template_id, template_version, template_hash, intent,
                 sender_profile_id, from_address, reply_to, preview_hash, recipient_count,
                 plan_path, now, "active")
            )

    def record_approval(self, record: ApprovalRecord) -> None:
        with self.conn:
            self.conn.execute(
                """INSERT INTO approvals (planId, previewHash, recipientCount, approvedBy, approvedAt, status)
                   VALUES (?,?,?,?,?,?)""",
                (record.plan_id, record.preview_hash, record.recipient_count,
                 record.approved_by, record.approved_at, record.status)
            )

    def get_approval(self, plan_id: str) -> Optional[ApprovalRecord]:
        row = self.conn.execute(
            "SELECT planId, previewHash, recipientCount, approvedBy, approvedAt, status FROM approvals WHERE planId = ?",
            (plan_id,)
        ).fetchone()
        if row is None:
            return None
        return ApprovalRecord(
            plan_id=row[0], preview_hash=row[1], recipient_count=row[2],
            approved_by=row[3], approved_at=row[4], status=row[5]
        )

    def reserve_delivery(self, plan_id: str, student_id: str,
                         idempotency_key: str, normalized_recipient: str,
                         masked_recipient: str, identity_projection_hash: str,
                         client_message_id: str) -> int:
        now = self._now()
        try:
            with self.conn:
                cursor = self.conn.execute(
                    """INSERT INTO deliveries
                       (planId, studentId, idempotencyKey, normalizedRecipient, maskedRecipient,
                        identityProjectionHash, state, attemptCount, clientMessageId, createdAt, updatedAt)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (plan_id, student_id, idempotency_key, normalized_recipient, masked_recipient,
                     identity_projection_hash, "reserved", 0, client_message_id, now, now)
                )
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise IdempotencyConflictError(
                f"Duplicate idempotencyKey: {idempotency_key}"
            ) from exc

    def get_delivery_by_key(self, idempotency_key: str) -> Optional[DeliveryRecord]:
        row = self.conn.execute(
            """SELECT deliveryId, planId, studentId, idempotencyKey, normalizedRecipient,
                      maskedRecipient, identityProjectionHash, state, attemptCount,
                      lastAttemptAt, providerMessageId, clientMessageId, createdAt, updatedAt
               FROM deliveries WHERE idempotencyKey = ?""",
            (idempotency_key,)
        ).fetchone()
        if row is None:
            return None
        return DeliveryRecord(
            delivery_id=row[0], plan_id=row[1], student_id=row[2],
            idempotency_key=row[3], normalized_recipient=row[4],
            masked_recipient=row[5], identity_projection_hash=row[6],
            state=DeliveryState(row[7]), attempt_count=row[8],
            last_attempt_at=row[9], provider_message_id=row[10],
            client_message_id=row[11], created_at=row[12], updated_at=row[13]
        )

    def transition_delivery(self, delivery_id: int, from_state: DeliveryState,
                            to_state: DeliveryState, transport_code: Optional[str] = None,
                            error_class: Optional[str] = None,
                            delivery_certainty: Optional[str] = None,
                            provider_message_id: Optional[str] = None,
                            client_message_id: Optional[str] = None) -> None:
        now = self._now()
        with self.conn:
            result = self.conn.execute(
                "UPDATE deliveries SET state = ?, updatedAt = ? WHERE deliveryId = ? AND state = ?",
                (to_state.value, now, delivery_id, from_state.value)
            )
            if result.rowcount == 0:
                raise DeliveryStateError(
                    f"Cannot transition delivery {delivery_id} from {from_state.value} to {to_state.value}"
                )
            attempt_number = self.conn.execute(
                "SELECT COALESCE(MAX(attemptNumber), 0) + 1 FROM delivery_attempts WHERE deliveryId = ?",
                (delivery_id,)
            ).fetchone()[0]
            self.conn.execute(
                """INSERT INTO delivery_attempts
                   (deliveryId, attemptNumber, stateBefore, stateAfter, transportCode,
                    errorClass, deliveryCertainty, providerMessageId, clientMessageId, attemptedAt)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (delivery_id, attempt_number, from_state.value, to_state.value,
                 transport_code, error_class, delivery_certainty,
                 provider_message_id, client_message_id, now)
            )
            self.conn.execute(
                "UPDATE deliveries SET attemptCount = ?, lastAttemptAt = ? WHERE deliveryId = ?",
                (attempt_number, now, delivery_id)
            )

    def get_deliveries_for_plan(self, plan_id: str) -> list[DeliveryRecord]:
        rows = self.conn.execute(
            """SELECT deliveryId, planId, studentId, idempotencyKey, normalizedRecipient,
                      maskedRecipient, identityProjectionHash, state, attemptCount,
                      lastAttemptAt, providerMessageId, clientMessageId, createdAt, updatedAt
               FROM deliveries WHERE planId = ? ORDER BY studentId""",
            (plan_id,)
        ).fetchall()
        return [
            DeliveryRecord(
                delivery_id=r[0], plan_id=r[1], student_id=r[2],
                idempotency_key=r[3], normalized_recipient=r[4],
                masked_recipient=r[5], identity_projection_hash=r[6],
                state=DeliveryState(r[7]), attempt_count=r[8],
                last_attempt_at=r[9], provider_message_id=r[10],
                client_message_id=r[11], created_at=r[12], updated_at=r[13]
            )
            for r in rows
        ]

    def register_template_version(self, template_id: str, template_version: str,
                                  template_hash: str) -> None:
        from .errors import TemplateHashMismatchError
        now = self._now()
        with self.conn:
            existing = self.conn.execute(
                "SELECT templateHash FROM template_versions WHERE templateId = ? AND templateVersion = ?",
                (template_id, template_version)
            ).fetchone()
            if existing is not None:
                if existing[0] != template_hash:
                    raise TemplateHashMismatchError(
                        f"templateId/version {template_id}/{template_version} already registered with hash {existing[0]}"
                    )
                return
            self.conn.execute(
                "INSERT INTO template_versions (templateId, templateVersion, templateHash, firstSeenAt) VALUES (?,?,?,?)",
                (template_id, template_version, template_hash, now)
            )

    def start_batch_run(self, plan_id: str, preview_hash: str,
                        transport_type: str, total_recipients: int,
                        actor: str) -> int:
        now = self._now()
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO batch_runs
                   (planId, previewHash, transportType, startedAt, totalRecipients, actor)
                   VALUES (?,?,?,?,?,?)""",
                (plan_id, preview_hash, transport_type, now, total_recipients, actor)
            )
            return cursor.lastrowid

    def complete_batch_run(self, batch_run_id: int, sent_count: int,
                          failed_count: int, ambiguous_count: int,
                          skipped_count: int, outcome: str) -> None:
        now = self._now()
        with self.conn:
            self.conn.execute(
                """UPDATE batch_runs SET completedAt = ?, sentCount = ?, failedCount = ?,
                   ambiguousCount = ?, skippedCount = ?, outcome = ? WHERE batchRunId = ?""",
                (now, sent_count, failed_count, ambiguous_count, skipped_count, outcome, batch_run_id)
            )

    def record_reconciliation(self, plan_id: str, delivery_id: Optional[int],
                              student_id: Optional[str], idempotency_key: Optional[str],
                              from_state: str, to_state: str, reason: str,
                              actor: str) -> None:
        now = self._now()
        with self.conn:
            self.conn.execute(
                """INSERT INTO reconciliation_events
                   (planId, deliveryId, studentId, idempotencyKey, fromState, toState, reason, actor, reconciledAt)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (plan_id, delivery_id, student_id, idempotency_key,
                 from_state, to_state, reason, actor, now)
            )

    def integrity_check(self) -> list[str]:
        issues = []
        try:
            result = self.conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                issues.append(f"SQLite integrity: {result[0]}")
        except Exception as exc:
            issues.append(f"SQLite integrity check failed: {exc}")
        try:
            rows = self.conn.execute(
                "SELECT deliveryId, state FROM deliveries WHERE state NOT IN (?,?,?,?,?,?,?,?,?)",
                (s.value for s in DeliveryState)
            ).fetchall()
            for row in rows:
                issues.append(f"Invalid state for delivery {row[0]}: {row[1]}")
        except Exception:
            pass
        return issues

    def get_batch_runs(self, plan_id: str) -> list[BatchRunSummary]:
        rows = self.conn.execute(
            """SELECT batchRunId, planId, previewHash, transportType, startedAt, completedAt,
                      totalRecipients, sentCount, failedCount, ambiguousCount, skippedCount, outcome, actor
               FROM batch_runs WHERE planId = ? ORDER BY batchRunId""",
            (plan_id,)
        ).fetchall()
        return [
            BatchRunSummary(
                batch_run_id=r[0], plan_id=r[1], preview_hash=r[2],
                transport_type=r[3], started_at=r[4], completed_at=r[5],
                total_recipients=r[6], sent_count=r[7], failed_count=r[8],
                ambiguous_count=r[9], skipped_count=r[10], outcome=r[11], actor=r[12]
            )
            for r in rows
        ]

    def backup(self, backup_path: Path) -> None:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            backup_path.parent.chmod(0o700)
        except OSError:
            pass
        dest = sqlite3.connect(str(backup_path))
        try:
            self.conn.backup(dest)
        finally:
            dest.close()
        try:
            os.chmod(str(backup_path), 0o600)
        except OSError:
            pass
