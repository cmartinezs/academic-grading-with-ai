"""Snapshot builder: staging, review, approval and atomic promotion (C1).

Build flow:
    build draft (staging) -> verify -> review (exact contentHash)
    -> approve (exact contentHash + confirmation) -> atomic promotion
    -> immutable snapshot

Failures never leave a partial snapshot under the publications root. Staging
lives under the temp root and is recoverable; the operator discards it with the
``discard`` command.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from c0.identity import IdentityStore
from c0.paths import RuntimeConfig, ZoneClassification, classify_zone, resolve_runtime_roots

from .adapter import ADAPTER_NAME, ADAPTER_VERSION, LegacyAdapter
from .clock import Clock
from .errors import (
    ConfirmationRequiredError,
    ContentHashMismatchError,
    DestinationExistsError,
    GateError,
    ImmutableSnapshotError,
    NotReviewedError,
    PublicationError,
    ReviewHashMismatchError,
    SameFilesystemError,
    StagingExistsError,
)
from .hashing import content_file_entries, content_hash_from_payloads, expected_file_meta, review_hash
from .ids import generate_publication_id, validate_publication_id, validate_section_id
from .jsonutil import (
    compute_content_hash,
    is_content_file,
    read_json,
    sha256_file,
    write_json,
)
from .legacy import load_legacy_export, require_course_matches
from .lifecycle import LifecycleLedger
from .locking import publication_lock
from .schemas import SCHEMA_VERSION
from .verify import VerifyReport, verify_snapshot

STAGING_REL = "publication-staging"
SECTIONS_REL = "sections"


@dataclass
class BuildContext:
    workspace_root: Path
    runtime: RuntimeConfig
    section_id: str
    publication_id: str
    clock: Clock = field(default_factory=Clock)
    legacy_source: Optional[Path] = None
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def resolve(
        cls,
        workspace_root,
        section_id: str,
        publication_id: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        clock: Optional[Clock] = None,
        legacy_source: Optional[Path] = None,
    ) -> "BuildContext":
        env = dict(os.environ) if env is None else dict(env)
        runtime = resolve_runtime_roots(Path(workspace_root), env=env)
        runtime.ensure_dirs()
        validate_section_id(section_id)
        if publication_id is None:
            publication_id = generate_publication_id()
        validate_publication_id(publication_id)
        return cls(
            workspace_root=Path(workspace_root),
            runtime=runtime,
            section_id=section_id,
            publication_id=publication_id,
            clock=clock or Clock(env=env),
            legacy_source=Path(legacy_source) if legacy_source else None,
            env=env,
        )

    # -- paths ----------------------------------------------------------------

    def staging_root(self) -> Path:
        return self.runtime.temp_root / STAGING_REL

    def staging_dir(self) -> Path:
        return self.staging_root() / self.section_id / self.publication_id

    def sections_root(self) -> Path:
        return self.runtime.publications_root / SECTIONS_REL

    def destination_dir(self) -> Path:
        return self.sections_root() / self.section_id / self.publication_id

    def ledger(self) -> LifecycleLedger:
        return LifecycleLedger(self.runtime.state_root, self.section_id, clock=self.clock)

    def identity_store(self) -> IdentityStore:
        return IdentityStore(self.runtime.state_root / "identity")

    def legacy_export_dir(self) -> Path:
        if self.legacy_source is not None:
            return self.legacy_source
        return Path(self.workspace_root) / "exports" / "publication-input"


# ---------------------------------------------------------------------------
# G0 — C0 boundary gate
# ---------------------------------------------------------------------------


def check_roots(ctx: BuildContext) -> None:
    findings: list[str] = []
    workspace = ctx.workspace_root.resolve()
    for name, path in (
        ("private-root", ctx.runtime.private_root),
        ("state-root", ctx.runtime.state_root),
        ("publications-root", ctx.runtime.publications_root),
        ("temp-root", ctx.runtime.temp_root),
    ):
        classification = classify_zone(path, workspace)
        if classification in (
            ZoneClassification.UNSAFE_TRACKED,
            ZoneClassification.UNSAFE_NOT_IGNORED,
            ZoneClassification.UNSAFE_UNKNOWN,
        ):
            findings.append(f"{name}: unsafe data root ({classification.value}).")
    if findings:
        raise GateError("G0-boundary", findings)

    identity = ctx.identity_store()
    issues = identity.integrity_issues()
    if issues:
        raise GateError("G0-boundary", [f"identity store integrity: {len(issues)} issue(s)."])


# ---------------------------------------------------------------------------
# Staging / atomic promotion
# ---------------------------------------------------------------------------


def _nearest_existing(path: Path) -> Path:
    current = Path(path)
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def check_same_filesystem(left: Path, right: Path) -> None:
    try:
        left_dev = os.stat(_nearest_existing(left)).st_dev
        right_dev = os.stat(_nearest_existing(right)).st_dev
    except OSError as exc:
        raise SameFilesystemError(f"Cannot stat roots for atomic rename: {exc}") from exc
    if left_dev != right_dev:
        raise SameFilesystemError(
            f"Staging root ({left}) and publications root ({right}) are on different "
            "filesystems; atomic rename is not possible. Configure ACADGRAD_TEMP_ROOT on "
            "the same filesystem as ACADGRAD_PUBLICATIONS_ROOT."
        )


def check_filesystem_precondition(ctx: BuildContext) -> None:
    check_same_filesystem(ctx.staging_root(), ctx.sections_root())


def _fsync_tree(root: Path) -> None:
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            fd = os.open(os.path.join(dirpath, name), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        dir_fd = os.open(dirpath, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _make_read_only(root: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o400)
        os.chmod(dirpath, 0o500)


def promote(ctx: BuildContext) -> Path:
    """Atomically promote a fully-verified staging snapshot to the publications root."""
    staging = ctx.staging_dir()
    dest = ctx.destination_dir()
    if not staging.is_dir():
        raise PublicationError(f"Staging does not exist: {staging}")
    if dest.exists():
        raise DestinationExistsError(f"Destination already exists: {dest}")
    check_same_filesystem(staging.parent, dest.parent)

    dest.parent.mkdir(parents=True, exist_ok=True)
    _fsync_tree(staging)
    os.rename(staging, dest)
    try:
        parent_fd = os.open(dest.parent, os.O_RDONLY)
    except OSError:
        parent_fd = None
    try:
        if parent_fd is not None:
            os.fsync(parent_fd)
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    _make_read_only(dest)
    return dest


def discard_staging(ctx: BuildContext) -> bool:
    with publication_lock(ctx.runtime.state_root, ctx.section_id, ctx.publication_id):
        staging = ctx.staging_dir()
        if not staging.exists():
            return False
        shutil.rmtree(staging)
        return True


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _manifest_files_entries(root: Path) -> dict[str, dict]:
    entries = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rel = path.relative_to(root).as_posix()
        classification, audience = expected_file_meta(rel) or (None, None)
        entries[rel] = {
            "classification": classification,
            "audience": audience,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return entries


def _manifest_files_entries_dry(payloads: dict[str, dict]) -> dict[str, dict]:
    from .jsonutil import encode, sha256_bytes

    entries = {}
    for rel, payload in sorted(payloads.items()):
        classification, audience = expected_file_meta(rel) or (None, None)
        entries[rel] = {
            "classification": classification,
            "audience": audience,
            "size": None,
            "sha256": sha256_bytes(encode(payload)),
        }
    return entries


def _content_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if is_content_file(rel):
            hashes[rel] = sha256_file(path)
    return hashes


def _roster_names(ctx: BuildContext) -> set[str]:
    """Legacy roster full names, used to detect identity leaking into free text."""
    try:
        legacy = load_legacy_export(ctx.legacy_export_dir())
    except PublicationError:
        return set()
    names = set()
    for student in legacy.students:
        name = student.get("name") or student.get("studentName")
        if name:
            names.add(str(name))
    return names


def _manifest_core(ctx: BuildContext, supersedes: Optional[str], corrects: Optional[str]) -> dict:
    """Immutable manifest core that a reviewer signs via the review hash."""
    return {
        "sectionId": ctx.section_id,
        "publicationId": ctx.publication_id,
        "supersedesPublicationId": supersedes,
        "correctsPublicationId": corrects,
        "engineVersion": ADAPTER_VERSION,
        "adapterVersion": ADAPTER_VERSION,
        "policySnapshotVersion": SCHEMA_VERSION,
    }


def _compute_review_hash(
    content_hash: str, core: dict, files: dict[str, dict]
) -> str:
    return review_hash(content_hash, core, content_file_entries(files))


def _write_manifest(root: Path, ctx: BuildContext, status: str, extra: Optional[dict] = None) -> str:
    manifest = read_json(root / "manifest.json")
    manifest["status"] = status
    manifest["files"] = _manifest_files_entries(root)
    if extra:
        manifest.update(extra)
    write_json(root / "manifest.json", manifest)
    return str(root / "manifest.json")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


@dataclass
class BuildResult:
    section_id: str
    publication_id: str
    content_hash: str
    review_hash: str
    staging_dir: Path
    file_count: int
    dry_run: bool = False


def compute_plan_payloads(ctx: BuildContext) -> tuple[LegacyAdapter, dict[str, dict], dict[str, dict]]:
    """G0–G3 + adapter; returns adapter, canonical and provenance payloads (no writes)."""
    check_roots(ctx)
    legacy = load_legacy_export(ctx.legacy_export_dir())
    require_course_matches(legacy, ctx.section_id)

    applied_migrations: list[str] = []
    migration_ledger = ctx.runtime.state_root / "migrations" / f"{ctx.section_id}-migration.json"
    if migration_ledger.exists():
        applied_migrations.append(f"c0-migration-{ctx.section_id}")

    store = ctx.identity_store()
    adapter = LegacyAdapter(
        legacy,
        ctx.section_id,
        resolve_student_id=lambda rut: store.resolve_by_external("rut", str(rut)),
        clock=ctx.clock,
        applied_migrations=applied_migrations,
    )
    mapping = adapter.build_mapping()
    canonical = adapter.build_canonical()
    provenance = adapter.build_provenance(mapping)
    return adapter, canonical, provenance


def build_draft(
    ctx: BuildContext,
    dry_run: bool = False,
    supersedes_publication_id: Optional[str] = None,
    corrects_publication_id: Optional[str] = None,
) -> BuildResult:
    """Build a draft snapshot in staging. Never promotes. Prints contentHash.

    Runs under the per-(section, publication) lock so concurrent operations on
    the same publication cannot interleave writes to staging.
    """
    with publication_lock(ctx.runtime.state_root, ctx.section_id, ctx.publication_id):
        return _build_draft_locked(ctx, dry_run, supersedes_publication_id, corrects_publication_id)


def _build_draft_locked(
    ctx: BuildContext,
    dry_run: bool = False,
    supersedes_publication_id: Optional[str] = None,
    corrects_publication_id: Optional[str] = None,
) -> BuildResult:
    if ctx.destination_dir().exists():
        raise ImmutableSnapshotError(
            f"An approved snapshot already exists for {ctx.publication_id}; "
            "approved snapshots are immutable and cannot be rebuilt."
        )
    if supersedes_publication_id and corrects_publication_id:
        raise GateError(
            "build-refs",
            ["supersedesPublicationId and correctsPublicationId are mutually exclusive."],
        )
    for ref, label in (
        (supersedes_publication_id, "supersedes"),
        (corrects_publication_id, "corrects"),
    ):
        if ref is None:
            continue
        if ref == ctx.publication_id:
            raise GateError("build-refs", ["A publication cannot reference itself."])
        if not approved_snapshot_exists(ctx, ref) or not is_approved_snapshot(ctx, ref):
            raise GateError(
                "build-refs",
                [f"{label} references publication {ref!r} which is not approved."],
            )

    adapter, canonical, provenance = compute_plan_payloads(ctx)
    check_filesystem_precondition(ctx)

    staging = ctx.staging_dir()
    if not dry_run and staging.exists():
        raise StagingExistsError(
            f"Staging already exists: {staging}. Use 'discard' to remove it or a new publicationId."
        )

    def payload_hash(payload) -> str:
        from .jsonutil import encode, sha256_bytes

        return sha256_bytes(encode(payload))

    core = _manifest_core(ctx, supersedes_publication_id, corrects_publication_id)
    payloads = {**canonical, **provenance}
    if dry_run:
        hashes = {rel: payload_hash(payload) for rel, payload in payloads.items()}
        content_hash = compute_content_hash(hashes)
        file_entries = content_file_entries(_manifest_files_entries_dry(payloads))
        review_hash = _compute_review_hash(content_hash, core, file_entries)
        return BuildResult(
            section_id=ctx.section_id,
            publication_id=ctx.publication_id,
            content_hash=content_hash,
            review_hash=review_hash,
            staging_dir=staging,
            file_count=len(payloads) + 1,
            dry_run=True,
        )

    staging.mkdir(parents=True, exist_ok=True)
    for rel, payload in payloads.items():
        path = staging / rel
        write_json(path, payload)

    content_hash = compute_content_hash(_content_hashes(staging))
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "sectionId": ctx.section_id,
        "publicationId": ctx.publication_id,
        "status": "draft",
        "supersedesPublicationId": supersedes_publication_id,
        "correctsPublicationId": corrects_publication_id,
        "contentHash": content_hash,
        "reviewHash": None,
        "engineVersion": ADAPTER_VERSION,
        "adapterVersion": ADAPTER_VERSION,
        "policySnapshotVersion": SCHEMA_VERSION,
        "builtAt": ctx.clock.iso(),
        "createdAt": ctx.clock.iso(),
        "approvedAt": None,
        "approvedBy": None,
        "files": {},
    }
    write_json(staging / "manifest.json", manifest)
    _write_manifest(staging, ctx, "draft")
    manifest_on_disk = read_json(staging / "manifest.json")
    review_hash = _compute_review_hash(
        content_hash, core, manifest_on_disk["files"]
    )
    manifest_on_disk["reviewHash"] = review_hash
    write_json(staging / "manifest.json", manifest_on_disk)

    report = verify_snapshot(staging, ctx.section_id, ctx.publication_id, known_names=_roster_names(ctx))
    if not report.passed():
        raise GateError("build-verify", [f.message for f in report.findings])

    ctx.ledger().append("created", ctx.publication_id, actor="system")

    return BuildResult(
        section_id=ctx.section_id,
        publication_id=ctx.publication_id,
        content_hash=content_hash,
        review_hash=review_hash,
        staging_dir=staging,
        file_count=len(payloads) + 1,
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def verify(ctx: BuildContext, target: str = "staging") -> VerifyReport:
    """Read-only verification of a staging draft or an approved snapshot."""
    if target == "staging":
        root = ctx.staging_dir()
    elif target == "approved":
        root = ctx.destination_dir()
    else:
        raise PublicationError(f"Unknown verify target: {target!r}")
    if not root.is_dir():
        raise PublicationError(f"Snapshot does not exist for verification: {root}")
    return verify_snapshot(root, ctx.section_id, ctx.publication_id, immutable=(target == "approved"))


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def review_draft(
    ctx: BuildContext,
    review_hash_value: str,
    reviewer: str,
    content_hash: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    """Write a review bound to the exact review hash. Never promotes."""
    with publication_lock(ctx.runtime.state_root, ctx.section_id, ctx.publication_id):
        return _review_draft_locked(ctx, review_hash_value, reviewer, content_hash=content_hash, dry_run=dry_run)


def _review_draft_locked(
    ctx: BuildContext,
    review_hash_value: str,
    reviewer: str,
    content_hash: Optional[str] = None,
    dry_run: bool = False,
) -> str:
    if not reviewer or "@" in reviewer:
        raise PublicationError("reviewer must be a non-email audit id.")
    staging = ctx.staging_dir()
    if not staging.is_dir():
        raise PublicationError(f"Staging does not exist: {staging}")
    current_content, current_review = _current_hashes(staging, ctx)
    if content_hash is not None and current_content != content_hash:
        raise ContentHashMismatchError(
            f"Expected contentHash {content_hash} does not match current {current_content}; "
            "review rejected (content changed)."
        )
    if current_review != review_hash_value:
        raise ReviewHashMismatchError(
            f"Expected reviewHash {review_hash_value} does not match current {current_review}; "
            "review rejected (manifest core or file classification changed)."
        )

    review = {
        "schemaVersion": SCHEMA_VERSION,
        "publicationId": ctx.publication_id,
        "contentHash": current_content,
        "reviewHash": review_hash_value,
        "reviewedBy": reviewer,
        "reviewedAt": ctx.clock.iso(),
        "status": "reviewed",
    }
    if not dry_run:
        write_json(staging / "approvals" / "review.json", review)
        _write_manifest(staging, ctx, "reviewed")
        report = verify_snapshot(staging, ctx.section_id, ctx.publication_id, known_names=_roster_names(ctx))
        if not report.passed():
            raise GateError("review-verify", [f.message for f in report.findings])
        ctx.ledger().append("reviewed", ctx.publication_id, actor=reviewer)
    return review_hash_value


def _current_hashes(staging: Path, ctx: BuildContext) -> tuple[str, str]:
    """Content and review hash of the current staging state.

    The review hash is derived from the *declared* manifest core so that
    tampering with engineVersion/adapterVersion/lineage is detected.
    """
    content_hash = compute_content_hash(_content_hashes(staging))
    manifest = read_json(staging / "manifest.json")
    core = {
        "sectionId": manifest.get("sectionId"),
        "publicationId": manifest.get("publicationId"),
        "supersedesPublicationId": manifest.get("supersedesPublicationId"),
        "correctsPublicationId": manifest.get("correctsPublicationId"),
        "engineVersion": manifest.get("engineVersion"),
        "adapterVersion": manifest.get("adapterVersion"),
        "policySnapshotVersion": manifest.get("policySnapshotVersion"),
    }
    review = _compute_review_hash(content_hash, core, manifest["files"])
    return content_hash, review


# ---------------------------------------------------------------------------
# Approval + promotion
# ---------------------------------------------------------------------------


def approve_draft(
    ctx: BuildContext,
    review_hash_value: str,
    approver: str,
    confirmation: str,
    content_hash: Optional[str] = None,
) -> Path:
    """Approve an exact-review-hash reviewed draft, finalize the manifest and promote atomically."""
    with publication_lock(ctx.runtime.state_root, ctx.section_id, ctx.publication_id):
        return _approve_draft_locked(ctx, review_hash_value, approver, confirmation, content_hash=content_hash)


def _approve_draft_locked(
    ctx: BuildContext,
    review_hash_value: str,
    approver: str,
    confirmation: str,
    content_hash: Optional[str] = None,
) -> Path:
    if not approver or "@" in approver:
        raise PublicationError("approver must be a non-email audit id.")
    if confirmation != "approve":
        raise ConfirmationRequiredError("Approval requires explicit confirmation ('--confirm approve').")

    staging = ctx.staging_dir()
    if not staging.is_dir():
        raise PublicationError(f"Staging does not exist: {staging}")

    current_content, current_review = _current_hashes(staging, ctx)
    if content_hash is not None and current_content != content_hash:
        raise ContentHashMismatchError(
            f"Expected contentHash {content_hash} does not match current {current_content}; approval rejected."
        )
    if current_review != review_hash_value:
        raise ReviewHashMismatchError(
            f"Expected reviewHash {review_hash_value} does not match current {current_review}; approval rejected."
        )

    review_path = staging / "approvals" / "review.json"
    if not review_path.is_file():
        raise NotReviewedError("Approval requires a prior review bound to the exact review hash.")
    review = read_json(review_path)
    if review.get("reviewHash") != review_hash_value:
        raise NotReviewedError("Review is not bound to the current review hash; re-review required.")
    if review.get("contentHash") != current_content:
        raise NotReviewedError("Review is not bound to the current content hash; re-review required.")
    if review.get("publicationId") != ctx.publication_id:
        raise NotReviewedError("Review references a different publication; re-review required.")

    approval = {
        "schemaVersion": SCHEMA_VERSION,
        "publicationId": ctx.publication_id,
        "contentHash": current_content,
        "reviewHash": review_hash_value,
        "approvedBy": approver,
        "approvedAt": ctx.clock.iso(),
        "confirmation": confirmation,
        "status": "approved",
    }
    write_json(staging / "approvals" / "publication-approval.json", approval)
    _write_manifest(
        staging,
        ctx,
        "approved",
        {"approvedAt": approval["approvedAt"], "approvedBy": approver},
    )

    report = verify_snapshot(staging, ctx.section_id, ctx.publication_id, known_names=_roster_names(ctx))
    if not report.passed():
        raise GateError("approve-verify", [f.message for f in report.findings])

    dest = promote(ctx)

    final = verify_snapshot(dest, ctx.section_id, ctx.publication_id, immutable=True)
    if not final.passed():
        raise GateError("promote-verify", [f.message for f in final.findings])

    ctx.ledger().append("approved", ctx.publication_id, actor=approver)
    return dest


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def approved_snapshot_exists(ctx: BuildContext, publication_id: str) -> bool:
    return (ctx.sections_root() / ctx.section_id / publication_id).is_dir()


def is_approved_snapshot(ctx: BuildContext, publication_id: str) -> bool:
    dest = ctx.sections_root() / ctx.section_id / publication_id
    if not dest.is_dir():
        return False
    manifest = read_json(dest / "manifest.json")
    return manifest.get("status") == "approved"
