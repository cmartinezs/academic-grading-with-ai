"""Email plan preparation for C3 email delivery.

Prepare never sends. It builds the deterministic plan from an approved snapshot,
identity store, template, and sender profile.
"""

from __future__ import annotations

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
    SnapshotNotApprovedError,
    SnapshotTerminalError,
)
from .masking import mask_email
from .models import EmailPlan, PlanRecipient, SnapshotMode
from .recipients import normalize_email
from .renderer import build_results_block, render
from .templates import load_template

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})


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
    operation_id: Optional[str] = None,
) -> EmailPlan:
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
        existing = read_json(existing_plan_path)
        existing_json = json.dumps(existing, sort_keys=True)
        new_json = json.dumps(plan.to_dict(), sort_keys=True)
        if existing_json == new_json:
            return plan
        raise PlanExistsError(f"A different plan already exists at {plan_dir}")

    staging_id = operation_id or plan_id
    staging_dir = temp_root / "email-plan-staging" / staging_id
    staging_dir.mkdir(parents=True, exist_ok=True)
    try:
        staging_dir.chmod(0o700)
    except OSError:
        pass

    plan_json_path = staging_dir / "plan.json"
    write_json(plan_json_path, plan.to_dict())

    previews_dir = staging_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = {"plan.json": {"sha256": sha256_file(plan_json_path)}}
    for recipient in recipients:
        preview_path = previews_dir / f"{recipient.student_id}.txt"
        preview_path.write_text(recipient.text_body, encoding="utf-8")
        preview_path.flush()
        os.fsync(preview_path.open("r").fileno()) if False else None
        rel = f"previews/{recipient.student_id}.txt"
        manifest_files[rel] = {"sha256": sha256_file(preview_path)}

    plan_dir.mkdir(parents=True, exist_ok=True)
    try:
        plan_dir.chmod(0o700)
    except OSError:
        pass

    for item in staging_dir.rglob("*"):
        if item.is_file():
            dest = plan_dir / item.relative_to(staging_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(item), str(dest))

    for f in plan_dir.rglob("*"):
        if f.is_file():
            try:
                os.chmod(str(f), 0o600)
            except OSError:
                pass

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
