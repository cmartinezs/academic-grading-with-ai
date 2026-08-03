"""C3 integration tests against a real approved C1 Publication Snapshot."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from c0.identity import IdentityStore
from email_delivery.approval import approve_plan
from email_delivery.errors import ExecuteBlockedError, LedgerError, PlanTamperedError
from email_delivery.executor import execute_plan
from email_delivery.ledger import EmailLedger
from email_delivery.lifecycle import verify_email_source_snapshot
from email_delivery.models import TransportConfig
from email_delivery.plan import prepare_plan, verify_plan_bundle
from email_delivery.transport.fake import FakeTransport
from publication import builder
from publication.clock import Clock

SECTION = "SEC-C3"
PUBLICATION = "pub_c3_auth"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _make_real_snapshot(base: Path):
    legacy = base / "legacy"
    roots = base / "roots"
    env = {
        "ACADGRAD_PRIVATE_ROOT": str(roots / "private"),
        "ACADGRAD_STATE_ROOT": str(roots / "state"),
        "ACADGRAD_PUBLICATIONS_ROOT": str(roots / "publications"),
        "ACADGRAD_TEMP_ROOT": str(roots / "temp"),
        "SOURCE_DATE_EPOCH": "1700000000",
    }

    _write(legacy / "manifest.json", {"course": {"id": SECTION}, "schemaVersion": 1})
    _write(
        legacy / "course/course.json",
        {
            "course": {"name": SECTION, "title": "C3 Integration"},
            "defaults": {
                "approvalThreshold": 60,
                "grading": {
                    "minGrade": 1,
                    "passingGrade": 4,
                    "maxGrade": 7,
                    "passingPercent": 60,
                },
                "presentationWeight": 100,
                "examWeight": 0,
            },
        },
    )
    _write(
        legacy / "course/students.json",
        {"items": [{"id": "11111111-1", "rut": "11111111-1", "name": "Synthetic Student"}]},
    )
    _write(
        legacy / "course/evaluations.json",
        {"items": [{"id": "ev1", "title": "EV1", "weight": 100, "type": "evaluacion", "forms": ["A"]}]},
    )
    _write(
        legacy / "course/results.json",
        {
            "items": [
                {
                    "studentId": "11111111-1",
                    "evaluationId": "ev1",
                    "form": "A",
                    "status": "Evaluada",
                    "score": 80.0,
                    "grade": 6.0,
                    "resultPath": "synthetic",
                    "finalFeedback": "Synthetic feedback",
                    "ies": [],
                }
            ]
        },
    )
    _write(legacy / "course/course-summary.json", {"students": 1, "evaluations": 1})

    identity_store = IdentityStore(roots / "state" / "identity")
    identity_store.ensure_many(
        [
            {
                "external": {"rut": "11111111-1"},
                "display_name": "Synthetic Student",
                "contact": {"email": "student@example.test"},
            }
        ]
    )

    context = builder.BuildContext.resolve(
        base,
        SECTION,
        publication_id=PUBLICATION,
        env=env,
        clock=Clock(env=env),
        legacy_source=legacy,
    )
    result = builder.build_draft(context)
    builder.review_draft(
        context,
        result.review_hash,
        "reviewer.synthetic",
        content_hash=result.content_hash,
    )
    snapshot_dir = builder.approve_draft(
        context,
        result.review_hash,
        "approver.synthetic",
        "approve",
        content_hash=result.content_hash,
    )

    template_path = base / "template.json"
    _write(
        template_path,
        {
            "schemaVersion": "1.0.0",
            "templateId": "result-notification",
            "templateVersion": "1",
            "intent": "result-notification",
            "subject": "Results {{sectionId}}",
            "textBody": "Hello {{displayName}}\n\n{{resultsBlock}}",
            "allowedPlaceholders": ["displayName", "sectionId", "resultsBlock"],
        },
    )
    sender_path = base / "sender.json"
    _write(
        sender_path,
        {
            "schemaVersion": "1.0.0",
            "senderProfileId": "default",
            "fromAddress": "noreply@example.test",
            "replyTo": "teacher@example.test",
        },
    )

    ledger = EmailLedger(roots / "state" / "email" / "email-ledger.sqlite3")
    verified = verify_email_source_snapshot(
        snapshot_dir,
        SECTION,
        PUBLICATION,
        context.ledger(),
    )
    plan = prepare_plan(
        section_id=SECTION,
        publication_id=PUBLICATION,
        snapshot_dir=snapshot_dir,
        snapshot_content_hash=verified.content_hash,
        snapshot_review_hash=verified.review_hash,
        snapshot_mode=verified.snapshot_mode,
        template_path=template_path,
        sender_profile_path=sender_path,
        identity_store=IdentityStore(roots / "state" / "identity"),
        private_root=roots / "private",
        temp_root=roots / "temp",
        lifecycle_ledger=context.ledger(),
        ledger=ledger,
    )
    plan_dir = roots / "private" / "email" / "plans" / SECTION / PUBLICATION / plan.plan_id
    ledger.register_plan(
        plan_id=plan.plan_id,
        section_id=plan.section_id,
        publication_id=plan.publication_id,
        snapshot_content_hash=plan.snapshot_content_hash,
        snapshot_review_hash=plan.snapshot_review_hash,
        snapshot_mode=plan.snapshot_mode,
        template_id=plan.template_id,
        template_version=plan.template_version,
        template_hash=plan.template_hash,
        intent=plan.intent,
        sender_profile_id=plan.sender_profile_id,
        from_address=plan.from_address,
        reply_to=plan.reply_to,
        preview_hash=plan.preview_hash,
        recipient_count=plan.recipient_count,
        plan_path=str(plan_dir),
    )
    return roots, context, snapshot_dir, plan, plan_dir, ledger


@pytest.fixture
def real_c3_fixture():
    base = Path(tempfile.mkdtemp(prefix="c3-real-snapshot-"))
    try:
        yield _make_real_snapshot(base)
    finally:
        for path in base.rglob("*"):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        try:
            os.chmod(base, 0o700)
        except OSError:
            pass
        shutil.rmtree(base, ignore_errors=True)


def _tamper_results(snapshot_dir: Path) -> None:
    path = snapshot_dir / "canonical" / "results.json"
    path.chmod(0o600)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["results"][0]["score"] = 81.0
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def test_real_c1_verifier_is_c3_authority(real_c3_fixture):
    _roots, context, snapshot_dir, plan, _plan_dir, _ledger = real_c3_fixture
    verified = verify_email_source_snapshot(
        snapshot_dir,
        SECTION,
        PUBLICATION,
        context.ledger(),
    )
    assert verified.content_hash == plan.snapshot_content_hash
    assert verified.review_hash == plan.snapshot_review_hash
    assert verified.snapshot_mode == plan.snapshot_mode


def test_snapshot_tamper_after_prepare_blocks_approval(real_c3_fixture):
    roots, context, snapshot_dir, plan, plan_dir, ledger = real_c3_fixture
    _tamper_results(snapshot_dir)

    with pytest.raises(PlanTamperedError):
        approve_plan(
            plan_id=plan.plan_id,
            preview_hash=plan.preview_hash,
            recipient_count=plan.recipient_count,
            actor="staff.synthetic",
            ledger=ledger,
            plan_dir=plan_dir,
            identity_store=IdentityStore(roots / "state" / "identity"),
            lifecycle_ledger=context.ledger(),
            publication_id=PUBLICATION,
            confirm_reviewed=True,
            snapshot_dir=snapshot_dir,
        )
    assert ledger.get_approval(plan.plan_id) is None


def test_snapshot_tamper_after_approval_blocks_execute(real_c3_fixture):
    roots, context, snapshot_dir, plan, plan_dir, ledger = real_c3_fixture
    identity_store = IdentityStore(roots / "state" / "identity")
    approve_plan(
        plan_id=plan.plan_id,
        preview_hash=plan.preview_hash,
        recipient_count=plan.recipient_count,
        actor="staff.synthetic",
        ledger=ledger,
        plan_dir=plan_dir,
        identity_store=identity_store,
        lifecycle_ledger=context.ledger(),
        publication_id=PUBLICATION,
        confirm_reviewed=True,
        snapshot_dir=snapshot_dir,
    )
    _tamper_results(snapshot_dir)
    transport = FakeTransport()

    with pytest.raises(ExecuteBlockedError):
        execute_plan(
            plan_id=plan.plan_id,
            preview_hash=plan.preview_hash,
            ledger=ledger,
            transport=transport,
            transport_config=TransportConfig(host="localhost", port=0, username=""),
            plan_dir=plan_dir,
            identity_store=identity_store,
            lifecycle_ledger=context.ledger(),
            publication_id=PUBLICATION,
            confirm_send=True,
            snapshot_dir=snapshot_dir,
            recovery_root=roots / "state" / "email" / "recovery",
        )
    assert transport.sent_count == 0


def test_recovery_marker_does_not_mutate_approved_plan(real_c3_fixture):
    roots, context, snapshot_dir, plan, plan_dir, ledger = real_c3_fixture
    identity_store = IdentityStore(roots / "state" / "identity")
    approve_plan(
        plan_id=plan.plan_id,
        preview_hash=plan.preview_hash,
        recipient_count=plan.recipient_count,
        actor="staff.synthetic",
        ledger=ledger,
        plan_dir=plan_dir,
        identity_store=identity_store,
        lifecycle_ledger=context.ledger(),
        publication_id=PUBLICATION,
        confirm_reviewed=True,
        snapshot_dir=snapshot_dir,
    )
    recovery_root = roots / "state" / "email" / "recovery"

    with patch.object(ledger, "complete_batch_run", side_effect=LedgerError("synthetic")):
        with pytest.raises(LedgerError):
            execute_plan(
                plan_id=plan.plan_id,
                preview_hash=plan.preview_hash,
                ledger=ledger,
                transport=FakeTransport(),
                transport_config=TransportConfig(host="localhost", port=0, username=""),
                plan_dir=plan_dir,
                identity_store=identity_store,
                lifecycle_ledger=context.ledger(),
                publication_id=PUBLICATION,
                confirm_send=True,
                snapshot_dir=snapshot_dir,
                recovery_root=recovery_root,
            )

    verify_plan_bundle(plan_dir)
    markers = list(recovery_root.glob("batch-*.json"))
    assert len(markers) == 1
    marker_text = markers[0].read_text(encoding="utf-8")
    assert "student@example.test" not in marker_text
    assert "Synthetic Student" not in marker_text
    assert str(plan_dir) not in marker_text
