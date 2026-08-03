"""Email plan preparation for C3 email delivery.

Prepare never sends. It builds a deterministic private plan from a verified,
approved Publication Snapshot, the private identity store, a versioned template,
and a sender profile.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from .canonical import (
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
    SchemaValidationError,
    SnapshotNotApprovedError,
    TemplateHashMismatchError,
)
from .masking import mask_email
from .models import EmailPlan, PlanRecipient, VerifiedEmailPlan
from .recipients import normalize_email
from .renderer import build_results_block, render
from .templates import load_template


MANIFEST_SCHEMA_V1 = {
    "type": "object",
    "required": ["schemaVersion", "planId", "files"],
    "additionalProperties": False,
    "properties": {
        "schemaVersion": {"const": "1.0.0"},
        "planId": {"type": "string", "pattern": "^eplan_[0-9a-f]{24}$"},
        "files": {
            "type": "object",
            "minProperties": 2,
            "additionalProperties": False,
            "patternProperties": {
                "^(plan\\.json|previews/[A-Za-z0-9._-]+\\.txt)$": {
                    "type": "object",
                    "required": ["sha256", "size"],
                    "additionalProperties": False,
                    "properties": {
                        "sha256": {
                            "type": "string",
                            "pattern": "^[0-9a-f]{64}$",
                        },
                        "size": {"type": "integer", "minimum": 0},
                    },
                }
            },
        },
    },
}


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_plan(
    section_id: str,
    publication_id: str,
    snapshot_dir: Path,
    snapshot_content_hash: Optional[str],
    snapshot_review_hash: Optional[str],
    snapshot_mode: Optional[str],
    template_path: Path,
    sender_profile_path: Path,
    identity_store,
    private_root: Path,
    temp_root: Path,
    lifecycle_ledger=None,
    ledger=None,
    operation_id: Optional[str] = None,
) -> EmailPlan:
    """Prepare and atomically promote a private, immutable email plan bundle.

    The three snapshot_* arguments are retained as compatibility assertions for
    existing callers.  The verified snapshot is always authoritative.
    """
    del temp_root  # staging intentionally lives below private_root for atomic rename

    from .lifecycle import verify_email_source_snapshot

    verified_snapshot = verify_email_source_snapshot(
        snapshot_dir=Path(snapshot_dir),
        section_id=section_id,
        publication_id=publication_id,
        lifecycle_ledger=lifecycle_ledger,
    )

    if snapshot_content_hash and verified_snapshot.content_hash != snapshot_content_hash:
        raise PlanTamperedError("Provided snapshot contentHash does not match verified snapshot.")
    if snapshot_review_hash and verified_snapshot.review_hash != snapshot_review_hash:
        raise PlanTamperedError("Provided snapshot reviewHash does not match verified snapshot.")
    if snapshot_mode and verified_snapshot.snapshot_mode != snapshot_mode:
        raise SnapshotNotApprovedError(
            "Provided snapshotMode does not match canonical/policy.json."
        )

    effective_content_hash = verified_snapshot.content_hash
    effective_review_hash = verified_snapshot.review_hash
    effective_mode = verified_snapshot.snapshot_mode

    template = load_template(Path(template_path))
    template_hash = compute_template_hash(template.to_dict())

    # Template identity is an operational invariant.  Check it before any
    # destination directory is promoted.
    if ledger is not None:
        try:
            ledger.register_template_version(
                template_id=template.template_id,
                template_version=template.template_version,
                template_hash=template_hash,
            )
        except TemplateHashMismatchError as exc:
            raise PlanExistsError(
                "Template id/version is already registered with different content."
            ) from exc

    sender_profile = read_json(Path(sender_profile_path))
    from_address = normalize_email(sender_profile["fromAddress"])
    reply_to = None
    if sender_profile.get("replyTo"):
        reply_to = normalize_email(sender_profile["replyTo"])

    subjects_data = _load_subjects(Path(snapshot_dir))
    results_data = _load_results(Path(snapshot_dir))
    outcomes_data = _load_outcomes(Path(snapshot_dir))
    assessments_data = _load_assessments(Path(snapshot_dir))

    recipients = _build_recipients(
        section_id=section_id,
        publication_id=publication_id,
        subjects_data=subjects_data,
        results_data=results_data,
        outcomes_data=outcomes_data,
        assessments_data=assessments_data,
        snapshot_mode=effective_mode,
        template=template,
        identity_store=identity_store,
    )

    plan_core = _build_plan_core(
        section_id=section_id,
        publication_id=publication_id,
        snapshot_content_hash=effective_content_hash,
        snapshot_review_hash=effective_review_hash,
        snapshot_mode=effective_mode,
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
        snapshot_content_hash=effective_content_hash,
        snapshot_review_hash=effective_review_hash,
        snapshot_mode=effective_mode,
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

    plan_dir = (
        Path(private_root)
        / "email"
        / "plans"
        / section_id
        / publication_id
        / plan_id
    )
    if plan_dir.exists():
        try:
            verified_existing = verify_plan_bundle(plan_dir)
        except (PlanTamperedError, SchemaValidationError) as exc:
            raise PlanExistsError("Existing plan bundle fails verification.") from exc
        if verified_existing.plan_dict == plan.to_dict():
            return plan
        raise PlanExistsError("A different plan already exists for this planId.")

    staging_id = operation_id or f"{plan_id}-{uuid.uuid4().hex[:12]}"
    staging_base = plan_dir.parent / ".staging"
    staging_dir = staging_base / staging_id
    if staging_dir.exists():
        raise PlanExistsError("Email plan staging operation already exists.")

    staging_dir.mkdir(parents=True, exist_ok=False)
    for parent in (
        staging_dir,
        staging_base,
        staging_base.parent,
        staging_base.parent.parent,
    ):
        try:
            parent.chmod(0o700)
        except OSError:
            pass

    try:
        plan_json_path = staging_dir / "plan.json"
        write_json(plan_json_path, plan.to_dict())

        previews_dir = staging_dir / "previews"
        previews_dir.mkdir(parents=True, exist_ok=False)
        try:
            previews_dir.chmod(0o700)
        except OSError:
            pass

        manifest_files = {
            "plan.json": {
                "sha256": sha256_file(plan_json_path),
                "size": plan_json_path.stat().st_size,
            }
        }
        for recipient in recipients:
            preview_path = previews_dir / f"{recipient.student_id}.txt"
            preview_path.write_text(recipient.text_body, encoding="utf-8")
            rel = f"previews/{recipient.student_id}.txt"
            manifest_files[rel] = {
                "sha256": sha256_file(preview_path),
                "size": preview_path.stat().st_size,
            }

        manifest = {
            "schemaVersion": "1.0.0",
            "planId": plan_id,
            "files": manifest_files,
        }
        write_json(staging_dir / "manifest.json", manifest)

        for file_path in staging_dir.rglob("*"):
            if file_path.is_file():
                try:
                    file_path.chmod(0o600)
                except OSError:
                    pass
                fd = os.open(str(file_path), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)

        _fsync_dir(previews_dir)
        _fsync_dir(staging_dir)
        _fsync_dir(staging_dir.parent)

        # Verify the exact staged bytes before the single atomic promotion.
        # The verifier binds directory basename to planId, so use a temporary
        # planId-shaped alias within staging for this pre-promotion check.
        _verify_staged_bundle(staging_dir, plan_id)

        os.rename(str(staging_dir), str(plan_dir))
        _fsync_dir(plan_dir.parent)
    except Exception:
        if staging_dir.exists():
            import shutil

            shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return plan


def _verify_staged_bundle(staging_dir: Path, plan_id: str) -> None:
    """Verify staging content without weakening the final dirname binding."""
    plan_dict = read_json(staging_dir / "plan.json")
    manifest = read_json(staging_dir / "manifest.json")
    if plan_dict.get("planId") != plan_id or manifest.get("planId") != plan_id:
        raise PlanTamperedError("Staged planId mismatch.")
    manifest_files = manifest.get("files", {})
    for logical_name, entry in manifest_files.items():
        path = staging_dir / logical_name
        if not path.is_file():
            raise PlanTamperedError(f"Staged file missing: {logical_name}")
        if sha256_file(path) != entry.get("sha256"):
            raise PlanTamperedError(f"Staged hash mismatch: {logical_name}")
        if path.stat().st_size != entry.get("size"):
            raise PlanTamperedError(f"Staged size mismatch: {logical_name}")


def _load_subjects(snapshot_dir: Path) -> list[dict]:
    path = snapshot_dir / "canonical" / "subjects.json"
    if not path.exists():
        return []
    return read_json(path).get("subjects", [])


def _load_results(snapshot_dir: Path) -> dict:
    path = snapshot_dir / "canonical" / "results.json"
    return read_json(path) if path.exists() else {}


def _load_outcomes(snapshot_dir: Path) -> dict:
    path = snapshot_dir / "canonical" / "outcomes.json"
    return read_json(path) if path.exists() else {}


def _load_assessments(snapshot_dir: Path) -> list[dict]:
    path = snapshot_dir / "canonical" / "assessments.json"
    if not path.exists():
        return []
    return read_json(path).get("assessments", [])


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
    results_by_student: dict[str, list[dict]] = {}
    for result in results_data.get("results", []):
        student_id = result.get("studentId")
        if student_id:
            results_by_student.setdefault(student_id, []).append(result)

    outcomes_by_student = {
        outcome.get("subjectId"): outcome
        for outcome in outcomes_data.get("outcomes", [])
        if outcome.get("subjectId")
    }

    seen_emails: dict[str, str] = {}
    recipients: list[PlanRecipient] = []
    for subject in sorted(subjects_data, key=lambda item: item.get("studentId", "")):
        student_id = subject.get("studentId")
        if not student_id:
            continue

        identity = identity_store.resolve(student_id)
        if identity is None:
            raise MissingIdentityError(
                f"studentId {student_id} not found in IdentityStore."
            )
        email_raw = (identity.contact or {}).get("email")
        if not email_raw:
            raise MissingEmailError(
                f"studentId {student_id} has no email in IdentityStore."
            )

        normalized = normalize_email(email_raw)
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
        rendered_subject, rendered_body = render(
            template,
            {
                "displayName": display_name,
                "sectionId": section_id,
                "publicationId": publication_id,
                "resultsBlock": build_results_block(view),
            },
        )

        recipient_core = {
            "studentId": student_id,
            "normalizedRecipient": normalized,
            "maskedRecipient": mask_email(normalized),
            "identityProjectionHash": identity_projection_hash,
            "subject": rendered_subject,
            "textBody": rendered_body,
        }
        recipients.append(
            PlanRecipient(
                student_id=student_id,
                normalized_recipient=normalized,
                masked_recipient=recipient_core["maskedRecipient"],
                identity_projection_hash=identity_projection_hash,
                subject=rendered_subject,
                text_body=rendered_body,
                item_hash=compute_item_hash(recipient_core),
                idempotency_key=compute_idempotency_key(
                    section_id=section_id,
                    publication_id=publication_id,
                    student_id=student_id,
                    normalized_recipient=normalized,
                    template_id=template.template_id,
                    template_version=template.template_version,
                    intent=template.intent,
                ),
            )
        )
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
    assessments: list[dict] = []
    if snapshot_mode == "grade-policy-effective" and student_outcome:
        assessments.append(
            {
                "assessmentId": "final-outcome",
                "assessmentLabel": "Resultado Final",
                "status": student_outcome.get("status"),
                "value": student_outcome.get("value"),
                "unit": student_outcome.get("unit"),
                "resultState": student_outcome.get("resultState"),
                "finalizable": student_outcome.get("finalizable"),
            }
        )
    for result in sorted(
        student_results, key=lambda item: item.get("assessmentId", "")
    ):
        assessment_id = result.get("assessmentId", "")
        metadata = assessment_map.get(assessment_id, {})
        assessments.append(
            {
                "assessmentId": assessment_id,
                "assessmentLabel": metadata.get("label", assessment_id),
                "status": result.get("status"),
                "score": result.get("score"),
                "scoreUnit": metadata.get("unit", ""),
                "grade": result.get("grade"),
            }
        )
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
        "recipients": [recipient.to_dict() for recipient in recipients],
    }


def verify_plan_bundle(plan_dir: Path) -> VerifiedEmailPlan:
    """Fail-closed verification of the complete private plan bundle."""
    try:
        import jsonschema
    except ImportError as exc:
        raise SchemaValidationError(
            "jsonschema runtime dependency is required for plan verification."
        ) from exc

    from .schemas import PLAN_SCHEMA_V1

    plan_dir = Path(plan_dir)
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
        jsonschema.validate(plan_dict, PLAN_SCHEMA_V1)
        jsonschema.validate(manifest, MANIFEST_SCHEMA_V1)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(
            f"Email bundle schema validation failed: {exc.message}"
        ) from exc

    plan_id = plan_dict["planId"]
    preview_hash = plan_dict["previewHash"]
    recipients = plan_dict["recipients"]
    recipient_count = plan_dict["recipientCount"]

    if manifest["planId"] != plan_id:
        raise PlanTamperedError("Manifest planId does not match plan.json.")
    if plan_dir.name != plan_id:
        raise PlanTamperedError("Plan directory basename does not match planId.")

    manifest_files = manifest["files"]
    if "plan.json" not in manifest_files:
        raise PlanTamperedError("Manifest does not declare plan.json.")
    for logical_name, entry in manifest_files.items():
        file_path = plan_dir / logical_name
        try:
            file_path.relative_to(plan_dir)
        except ValueError as exc:
            raise PlanTamperedError("Manifest path escapes plan directory.") from exc
        if not file_path.is_file():
            raise PlanTamperedError(f"Manifest file missing: {logical_name}")
        if sha256_file(file_path) != entry["sha256"]:
            raise PlanTamperedError(f"SHA256 mismatch for {logical_name}")
        if file_path.stat().st_size != entry["size"]:
            raise PlanTamperedError(f"Size mismatch for {logical_name}")

    student_ids = [recipient["studentId"] for recipient in recipients]
    if student_ids != sorted(student_ids):
        raise PlanTamperedError("Recipients are not sorted by studentId.")
    if len(student_ids) != len(set(student_ids)):
        raise PlanTamperedError("Duplicate studentId in plan.")
    if len(recipients) != recipient_count:
        raise PlanTamperedError("recipientCount mismatch.")

    for recipient in recipients:
        student_id = recipient["studentId"]
        recipient_core = {
            key: value
            for key, value in recipient.items()
            if key not in ("itemHash", "idempotencyKey")
        }
        if compute_item_hash(recipient_core) != recipient["itemHash"]:
            raise PlanTamperedError(f"itemHash mismatch for {student_id}")
        expected_key = compute_idempotency_key(
            section_id=plan_dict["sectionId"],
            publication_id=plan_dict["publicationId"],
            student_id=student_id,
            normalized_recipient=recipient["normalizedRecipient"],
            template_id=plan_dict["templateId"],
            template_version=plan_dict["templateVersion"],
            intent=plan_dict["intent"],
        )
        if expected_key != recipient["idempotencyKey"]:
            raise PlanTamperedError(f"idempotencyKey mismatch for {student_id}")

        preview_file = previews_dir / f"{student_id}.txt"
        if not preview_file.is_file():
            raise PlanTamperedError(f"Preview missing for {student_id}")
        if preview_file.read_text(encoding="utf-8") != recipient["textBody"]:
            raise PlanTamperedError(f"Preview content mismatch for {student_id}")

    plan_core = {
        key: value
        for key, value in plan_dict.items()
        if key not in ("previewHash", "planId")
    }
    recomputed_preview_hash = compute_preview_hash(plan_core)
    if recomputed_preview_hash != preview_hash:
        raise PlanTamperedError("previewHash mismatch.")
    if derive_plan_id(recomputed_preview_hash) != plan_id:
        raise PlanTamperedError("planId mismatch.")

    actual_files = {
        path.relative_to(plan_dir).as_posix()
        for path in plan_dir.rglob("*")
        if path.is_file()
    }
    expected_files = set(manifest_files) | {"manifest.json"}
    if actual_files != expected_files:
        raise PlanTamperedError("Plan bundle contains missing or unexpected files.")

    return VerifiedEmailPlan(
        plan_id=plan_id,
        preview_hash=preview_hash,
        recipient_count=recipient_count,
        plan_dict=plan_dict,
        manifest=manifest,
    )
