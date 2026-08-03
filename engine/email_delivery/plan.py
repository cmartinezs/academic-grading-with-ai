"""Email plan preparation for C3 email delivery.

Prepare never sends. It builds the deterministic plan from an approved snapshot,
identity store, template, and sender profile.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .canonical import (
    compute_hash,
    compute_identity_projection_hash,
    compute_idempotency_key,
    compute_item_hash,
    compute_preview_hash,
    compute_template_hash,
    derive_plan_id,
    read_json,
    sha256_file,
    write_json,
)
from .errors import (
    DuplicateEmailError,
    MissingEmailError,
    MissingIdentityError,
    PlanExistsError,
    PlanTamperedError,
    SnapshotNotApprovedError,
    SnapshotTerminalError,
)
from .masking import mask_email
from .models import EmailPlan, PlanRecipient, SnapshotMode
from .recipients import normalize_email
from .renderer import build_results_block, render
from .templates import load_template

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_plan(
    section_id: str,
    publication_id: str,
    snapshot_dir: Path,
    snapshot_content_hash: str,
    snapshot_review_hash: str,
    snapshot_mode: str,
    template_path: Path,
    sender_profile_path: Path,
    identity_store,
    private_root: Path,
    temp_root: Path,
    lifecycle_ledger=None,
    ledger=None,
    operation_id: Optional[str] = None,
) -> EmailPlan:
    from .lifecycle import verify_email_source_snapshot, derive_snapshot_mode

    verified_snapshot = verify_email_source_snapshot(
        snapshot_dir=snapshot_dir,
        section_id=section_id,
        publication_id=publication_id,
        lifecycle_ledger=lifecycle_ledger,
    )

    derived_mode = derive_snapshot_mode(snapshot_dir)
    if derived_mode != snapshot_mode:
        raise SnapshotNotApprovedError(
            f"snapshotMode argument {snapshot_mode!r} does not match canonical/policy.json mode {derived_mode!r}"
        )

    if verified_snapshot.content_hash != snapshot_content_hash:
        raise PlanTamperedError(
            f"snapshot contentHash mismatch: verified {verified_snapshot.content_hash} vs provided {snapshot_content_hash}"
        )
    if verified_snapshot.review_hash != snapshot_review_hash:
        raise PlanTamperedError(
            f"snapshot reviewHash mismatch: verified {verified_snapshot.review_hash} vs provided {snapshot_review_hash}"
        )

    if lifecycle_ledger is not None:
        state = lifecycle_ledger.current_state(publication_id)
        if state in SNAPSHOT_TERMINAL_STATES:
            raise SnapshotTerminalError(f"Snapshot is in terminal state: {state}")
        if state != "approved":
            raise SnapshotNotApprovedError(f"Snapshot state is {state}, expected approved.")

    template = load_template(template_path)
    template_dict = template.to_dict()
    template_hash = compute_template_hash(template_dict)

    sender_profile = read_json(sender_profile_path)
    from_address = normalize_email(sender_profile["fromAddress"])
    reply_to = None
    if sender_profile.get("replyTo"):
        reply_to = normalize_email(sender_profile["replyTo"])

    subjects_data = _load_subjects(snapshot_dir)
    results_data = _load_results(snapshot_dir)
    outcomes_data = _load_outcomes(snapshot_dir)
    assessments_data = _load_assessments(snapshot_dir)

    recipients = _build_recipients(
        section_id=section_id,
        publication_id=publication_id,
        subjects_data=subjects_data,
        results_data=results_data,
        outcomes_data=outcomes_data,
        assessments_data=assessments_data,
        snapshot_mode=snapshot_mode,
        template=template,
        identity_store=identity_store,
    )

    plan_core = _build_plan_core(
        section_id=section_id,
        publication_id=publication_id,
        snapshot_content_hash=snapshot_content_hash,
        snapshot_review_hash=snapshot_review_hash,
        snapshot_mode=snapshot_mode,
        template=template,
        template_hash=template_hash,
        sender_profile_id=sender_profile.get("senderProfileId", "default"),
        from_address=from_address,
        reply_to=reply_to,
        recipients=recipients,
    )

    preview_hash = compute_preview_hash(plan_core)
    plan_id = derive_plan_id(preview_hash)

    plan = EmailPlan(
        schema_version="1.0.0",
        plan_id=plan_id,
        section_id=section_id,
        publication_id=publication_id,
        snapshot_content_hash=snapshot_content_hash,
        snapshot_review_hash=snapshot_review_hash,
        snapshot_mode=snapshot_mode,
        template_id=template.template_id,
        template_version=template.template_version,
        template_hash=template_hash,
        intent=template.intent,
        sender_profile_id=sender_profile.get("senderProfileId", "default"),
        from_address=from_address,
        reply_to=reply_to,
        recipient_count=len(recipients),
        recipients=tuple(recipients),
        preview_hash=preview_hash,
    )

    plan_dir = private_root / "email" / "plans" / section_id / publication_id / plan_id
    existing_plan_path = plan_dir / "plan.json"
    if existing_plan_path.exists():
        try:
            verify_plan_bundle(plan_dir)
        except PlanTamperedError:
            raise PlanExistsError(f"Existing plan at {plan_dir} fails bundle verification")
        existing = read_json(existing_plan_path)
        existing_json = json.dumps(existing, sort_keys=True)
        new_json = json.dumps(plan.to_dict(), sort_keys=True)
        if existing_json == new_json:
            return plan
        raise PlanExistsError(f"A different plan already exists at {plan_dir}")

    import uuid as _uuid
    staging_id = operation_id or f"{plan_id}-{_uuid.uuid4().hex[:12]}"
    staging_base = private_root / "email" / "plans" / section_id / publication_id / ".staging"
    staging_dir = staging_base / staging_id
    if staging_dir.exists():
        import shutil
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        staging_dir.chmod(0o700)
    except OSError:
        pass
    for parent in [staging_dir, staging_base, staging_base.parent, staging_base.parent.parent]:
        try:
            parent.chmod(0o700)
        except OSError:
            pass

    plan_json_path = staging_dir / "plan.json"
    write_json(plan_json_path, plan.to_dict())

    previews_dir = staging_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    try:
        previews_dir.chmod(0o700)
    except OSError:
        pass
    manifest_files = {"plan.json": {"sha256": sha256_file(plan_json_path), "size": plan_json_path.stat().st_size}}
    for recipient in recipients:
        preview_path = previews_dir / f"{recipient.student_id}.txt"
        preview_path.write_text(recipient.text_body, encoding="utf-8")
        rel = f"previews/{recipient.student_id}.txt"
        manifest_files[rel] = {"sha256": sha256_file(preview_path), "size": preview_path.stat().st_size}

    manifest = {
        "schemaVersion": "1.0.0",
        "planId": plan_id,
        "files": manifest_files,
    }
    manifest_path = staging_dir / "manifest.json"
    write_json(manifest_path, manifest)

    for f in staging_dir.rglob("*"):
        if f.is_file():
            try:
                os.chmod(str(f), 0o600)
            except OSError:
                pass

    for f in staging_dir.rglob("*"):
        if f.is_file():
            fd = os.open(str(f), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    _fsync_dir(staging_dir)
    if previews_dir.exists():
        _fsync_dir(previews_dir)
    _fsync_dir(staging_dir.parent)

    os.rename(str(staging_dir), str(plan_dir))
    _fsync_dir(plan_dir.parent)

    if ledger is not None:
        try:
            ledger.register_template_version(
                template_id=template.template_id,
                template_version=template.template_version,
                template_hash=template_hash,
            )
        except TemplateHashMismatchError:
            raise PlanExistsError(
                f"Template {template.template_id}/{template.template_version} already registered with different hash"
            )

    return plan


def _load_subjects(snapshot_dir: Path) -> list[dict]:
    path = snapshot_dir / "canonical" / "subjects.json"
    if not path.exists():
        return []
    data = read_json(path)
    return data.get("subjects", [])


def _load_results(snapshot_dir: Path) -> dict:
    path = snapshot_dir / "canonical" / "results.json"
    if not path.exists():
        return {}
    return read_json(path)


def _load_outcomes(snapshot_dir: Path) -> dict:
    path = snapshot_dir / "canonical" / "outcomes.json"
    if not path.exists():
        return {}
    return read_json(path)


def _load_assessments(snapshot_dir: Path) -> list[dict]:
    path = snapshot_dir / "canonical" / "assessments.json"
    if not path.exists():
        return []
    data = read_json(path)
    return data.get("assessments", [])


def _build_recipients(
    section_id: str,
    publication_id: str,
    subjects_data: list[dict],
    results_data: dict,
    outcomes_data: dict,
    assessments_data: list[dict],
    snapshot_mode: str,
    template,
    identity_store,
) -> list[PlanRecipient]:
    assessment_map = {a.get("assessmentId"): a for a in assessments_data}
    results_by_student = {}
    for r in results_data.get("results", []):
        sid = r.get("studentId")
        if sid:
            results_by_student.setdefault(sid, []).append(r)

    outcomes_by_student = {}
    for o in outcomes_data.get("outcomes", []):
        sid = o.get("subjectId")
        if sid:
            outcomes_by_student[sid] = o

    seen_emails: dict[str, str] = {}
    recipients: list[PlanRecipient] = []

    for subject in sorted(subjects_data, key=lambda s: s.get("studentId", "")):
        student_id = subject.get("studentId")
        if not student_id:
            continue

        identity = identity_store.resolve(student_id)
        if identity is None:
            raise MissingIdentityError(f"studentId {student_id} not found in IdentityStore.")

        email_raw = (identity.contact or {}).get("email")
        if not email_raw:
            raise MissingEmailError(f"studentId {student_id} has no email in IdentityStore.")

        normalized = normalize_email(email_raw)
        masked = mask_email(normalized)

        if normalized in seen_emails:
            raise DuplicateEmailError(
                f"studentId {student_id} and {seen_emails[normalized]} resolve to same email."
            )
        seen_emails[normalized] = student_id

        display_name = identity.display_name or ""
        identity_projection_hash = compute_identity_projection_hash(
            student_id, display_name, normalized
        )

        view = _build_student_email_view(
            student_id=student_id,
            section_id=section_id,
            publication_id=publication_id,
            snapshot_mode=snapshot_mode,
            student_results=results_by_student.get(student_id, []),
            student_outcome=outcomes_by_student.get(student_id),
            assessment_map=assessment_map,
        )

        results_block = build_results_block(view)
        values = {
            "displayName": display_name,
            "sectionId": section_id,
            "publicationId": publication_id,
            "resultsBlock": results_block,
        }

        rendered_subject, rendered_body = render(template, values)

        recipient_dict = {
            "studentId": student_id,
            "normalizedRecipient": normalized,
            "maskedRecipient": masked,
            "identityProjectionHash": identity_projection_hash,
            "subject": rendered_subject,
            "textBody": rendered_body,
        }

        item_hash = compute_item_hash(recipient_dict)
        idempotency_key = compute_idempotency_key(
            section_id=section_id,
            publication_id=publication_id,
            student_id=student_id,
            normalized_recipient=normalized,
            template_id=template.template_id,
            template_version=template.template_version,
            intent=template.intent,
        )

        recipients.append(PlanRecipient(
            student_id=student_id,
            normalized_recipient=normalized,
            masked_recipient=masked,
            identity_projection_hash=identity_projection_hash,
            subject=rendered_subject,
            text_body=rendered_body,
            item_hash=item_hash,
            idempotency_key=idempotency_key,
        ))

    return recipients


def _build_student_email_view(
    student_id: str,
    section_id: str,
    publication_id: str,
    snapshot_mode: str,
    student_results: list[dict],
    student_outcome: Optional[dict],
    assessment_map: dict,
) -> dict:
    assessments = []
    if snapshot_mode == "grade-policy-effective" and student_outcome:
        assessments.append({
            "assessmentId": "final-outcome",
            "assessmentLabel": "Resultado Final",
            "status": student_outcome.get("status"),
            "value": student_outcome.get("value"),
            "unit": student_outcome.get("unit"),
            "resultState": student_outcome.get("resultState"),
            "finalizable": student_outcome.get("finalizable"),
        })

    for r in sorted(student_results, key=lambda x: x.get("assessmentId", "")):
        aid = r.get("assessmentId", "")
        a_meta = assessment_map.get(aid, {})
        entry = {
            "assessmentId": aid,
            "assessmentLabel": a_meta.get("label", aid),
            "status": r.get("status"),
            "score": r.get("score"),
            "scoreUnit": a_meta.get("unit", ""),
            "grade": r.get("grade"),
        }
        assessments.append(entry)

    return {
        "schemaVersion": "1.0.0",
        "studentId": student_id,
        "sectionId": section_id,
        "publicationId": publication_id,
        "snapshotMode": snapshot_mode,
        "assessments": assessments,
    }


def _build_plan_core(
    section_id: str,
    publication_id: str,
    snapshot_content_hash: str,
    snapshot_review_hash: str,
    snapshot_mode: str,
    template,
    template_hash: str,
    sender_profile_id: str,
    from_address: str,
    reply_to: Optional[str],
    recipients: list[PlanRecipient],
) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "sectionId": section_id,
        "publicationId": publication_id,
        "snapshotContentHash": snapshot_content_hash,
        "snapshotReviewHash": snapshot_review_hash,
        "snapshotMode": snapshot_mode,
        "templateId": template.template_id,
        "templateVersion": template.template_version,
        "templateHash": template_hash,
        "intent": template.intent,
        "senderProfileId": sender_profile_id,
        "fromAddress": from_address,
        "replyTo": reply_to,
        "recipientCount": len(recipients),
        "recipients": [r.to_dict() for r in recipients],
    }


def verify_plan_bundle(plan_dir: Path) -> 'VerifiedEmailPlan':
    """Verify plan bundle integrity.

    Returns VerifiedEmailPlan on success.
    Raises PlanTamperedError on any mismatch.
    """
    from .errors import PlanTamperedError, SchemaValidationError
    from .models import VerifiedEmailPlan
    from .schemas import PLAN_SCHEMA_V1

    plan_path = plan_dir / "plan.json"
    manifest_path = plan_dir / "manifest.json"
    previews_dir = plan_dir / "previews"

    if not plan_path.exists():
        raise PlanTamperedError("plan.json missing from bundle")
    if not manifest_path.exists():
        raise PlanTamperedError("manifest.json missing from bundle")

    plan_dict = read_json(plan_path)
    manifest = read_json(manifest_path)

    try:
        import jsonschema
        jsonschema.validate(plan_dict, PLAN_SCHEMA_V1)
    except ImportError:
        pass
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(f"Plan JSON Schema validation failed: {exc.message}") from exc

    MANIFEST_SCHEMA = {
        "type": "object",
        "required": ["schemaVersion", "planId", "files"],
        "additionalProperties": False,
        "properties": {
            "schemaVersion": {"type": "string"},
            "planId": {"type": "string"},
            "files": {
                "type": "object",
                "additionalProperties": False,
                "patternProperties": {
                    "^.*$": {
                        "type": "object",
                        "required": ["sha256", "size"],
                        "additionalProperties": False,
                        "properties": {
                            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            "size": {"type": "integer", "minimum": 0},
                        },
                    },
                },
            },
        },
    }
    try:
        import jsonschema
        jsonschema.validate(manifest, MANIFEST_SCHEMA)
    except ImportError:
        pass
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(f"Manifest JSON Schema validation failed: {exc.message}") from exc

    plan_id = plan_dict.get("planId", "")
    preview_hash = plan_dict.get("previewHash", "")
    recipient_count = plan_dict.get("recipientCount", 0)
    recipients = plan_dict.get("recipients", [])

    manifest_plan_id = manifest.get("planId", "")
    if manifest_plan_id != plan_id:
        raise PlanTamperedError(f"manifest planId {manifest_plan_id} does not match plan planId {plan_id}")

    expected_dirname = plan_dir.name
    if expected_dirname != plan_id:
        raise PlanTamperedError(f"directory basename {expected_dirname} does not match planId {plan_id}")

    manifest_files = manifest.get("files", {})

    for logical_name, entry in manifest_files.items():
        file_path = plan_dir / logical_name
        if not file_path.exists():
            raise PlanTamperedError(f"Manifest file missing: {logical_name}")
        actual_sha256 = sha256_file(file_path)
        expected_sha256 = entry.get("sha256", "")
        if actual_sha256 != expected_sha256:
            raise PlanTamperedError(f"SHA256 mismatch for {logical_name}")
        actual_size = file_path.stat().st_size
        expected_size = entry.get("size")
        if expected_size is not None and actual_size != expected_size:
            raise PlanTamperedError(f"Size mismatch for {logical_name}")

    for recipient in recipients:
        student_id = recipient.get("studentId", "")
        stored_item_hash = recipient.get("itemHash", "")
        recipient_check = {k: v for k, v in recipient.items() if k not in ("itemHash", "idempotencyKey")}
        recomputed_item_hash = compute_item_hash(recipient_check)
        if recomputed_item_hash != stored_item_hash:
            raise PlanTamperedError(f"itemHash mismatch for {student_id}")

        stored_idempotency_key = recipient.get("idempotencyKey", "")
        normalized_recipient = recipient.get("normalizedRecipient", "")
        recomputed_key = compute_idempotency_key(
            section_id=plan_dict.get("sectionId", ""),
            publication_id=plan_dict.get("publicationId", ""),
            student_id=student_id,
            normalized_recipient=normalized_recipient,
            template_id=plan_dict.get("templateId", ""),
            template_version=plan_dict.get("templateVersion", ""),
            intent=plan_dict.get("intent", ""),
        )
        if recomputed_key != stored_idempotency_key:
            raise PlanTamperedError(f"idempotencyKey mismatch for {student_id}")

    plan_core = {k: v for k, v in plan_dict.items() if k not in ("previewHash", "planId")}
    recomputed_preview_hash = compute_preview_hash(plan_core)
    if recomputed_preview_hash != preview_hash:
        raise PlanTamperedError("previewHash mismatch")

    recomputed_plan_id = derive_plan_id(recomputed_preview_hash)
    if recomputed_plan_id != plan_id:
        raise PlanTamperedError("planId mismatch")

    if len(recipients) != recipient_count:
        raise PlanTamperedError("recipientCount mismatch")

    student_ids = [r.get("studentId", "") for r in recipients]
    if student_ids != sorted(student_ids):
        raise PlanTamperedError("recipients not sorted by studentId")

    seen_student_ids = set()
    for recipient in recipients:
        sid = recipient.get("studentId", "")
        if sid in seen_student_ids:
            raise PlanTamperedError(f"Duplicate studentId {sid}")
        seen_student_ids.add(sid)

    for recipient in recipients:
        student_id = recipient.get("studentId", "")
        preview_file = previews_dir / f"{student_id}.txt"
        if not preview_file.exists():
            raise PlanTamperedError(f"Preview missing for {student_id}")
        expected_body = recipient.get("textBody", "")
        actual_body = preview_file.read_text(encoding="utf-8")
        if actual_body != expected_body:
            raise PlanTamperedError(f"Preview content mismatch for {student_id}")

    all_files = set()
    for f in plan_dir.rglob("*"):
        if f.is_file():
            rel = str(f.relative_to(plan_dir))
            all_files.add(rel)
    expected_files = set(manifest_files.keys()) | {"manifest.json"}
    if all_files != expected_files:
        extra = all_files - expected_files
        if extra:
            raise PlanTamperedError(f"Unexpected files in bundle: {extra}")
        missing = expected_files - all_files
        if missing:
            raise PlanTamperedError(f"Missing files in bundle: {missing}")

    return VerifiedEmailPlan(
        plan_id=plan_id,
        preview_hash=preview_hash,
        recipient_count=recipient_count,
        plan_dict=plan_dict,
        manifest=manifest,
    )
