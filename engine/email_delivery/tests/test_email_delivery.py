"""C3 email delivery test suite — unit, contract, determinism, privacy, integration,
concurrency, and failure injection tests.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from email_delivery.canonical import (
    compute_hash,
    compute_identity_projection_hash,
    compute_idempotency_key,
    compute_item_hash,
    compute_preview_hash,
    compute_template_hash,
    derive_plan_id,
    sha256_bytes,
    sha256_text,
    write_json,
    read_json,
)
from email_delivery.errors import (
    AmbiguousResolutionError,
    ApprovalMismatchError,
    CRLFInjectionError,
    DeliveryStateError,
    DuplicateEmailError,
    IdempotencyConflictError,
    IdentityDriftError,
    InvalidEmailError,
    MissingEmailError,
    MissingIdentityError,
    MissingPlaceholderValueError,
    NotApprovedError,
    PlanExistsError,
    SnapshotTerminalError,
    TemplateHashMismatchError,
    UnknownPlaceholderError,
)
from email_delivery.ledger import EmailLedger
from email_delivery.masking import mask_email, mask_name, mask_subject
from email_delivery.models import (
    ApprovalRecord,
    DeliveryState,
    EmailPlan,
    Envelope,
    ExecuteOutcome,
    PlanRecipient,
    SenderProfile,
    StudentEmailView,
    TemplateDocument,
    TransportConfig,
    TransportReceipt,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
)
from email_delivery.recipients import (
    normalize_email,
    normalize_unicode_nfc,
    normalize_line_endings,
    check_crlf_injection,
    is_valid_email,
)
from email_delivery.renderer import render, build_results_block
from email_delivery.reconciliation import (
    reconcile_plan,
    resolve_ambiguous,
    get_plan_status,
)
from email_delivery.templates import (
    load_template_from_dict,
    compute_template_document_hash,
    extract_placeholders,
)
from email_delivery.transport.fake import FakeTransport, FakeBehavior
from email_delivery.plan import prepare_plan
from email_delivery.approval import approve_plan
from email_delivery.executor import execute_plan


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def ledger(tmp_dir):
    db_path = tmp_dir / "email-ledger.sqlite3"
    lg = EmailLedger(db_path)
    yield lg
    lg.close()


def _register_test_plan(ledger, plan_id="eplan_test"):
    ledger.register_plan(
        plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
        snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
        snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
        template_hash="t" * 64, intent="notify", sender_profile_id="default",
        from_address="noreply@test.com", reply_to=None,
        preview_hash="p" * 64, recipient_count=1,
        plan_path="/tmp/plan",
    )


def _synthetic_template_dict():
    return {
        "schemaVersion": "1.0.0",
        "templateId": "result-notification",
        "templateVersion": "1",
        "intent": "result-notification",
        "subject": "Resultados {{sectionId}} — {{publicationId}}",
        "textBody": "Estimado/a {{displayName}},\n\n{{resultsBlock}}\n\nAtentamente",
        "allowedPlaceholders": ["displayName", "sectionId", "publicationId", "resultsBlock"],
    }


def _synthetic_template():
    return load_template_from_dict(_synthetic_template_dict())


def _synthetic_identity(student_id="stu_abc123", display_name="Juan Pérez", email="juan@example.test"):
    identity = MagicMock()
    identity.student_id = student_id
    identity.display_name = display_name
    identity.contact = {"email": email}
    identity.external_identifiers = {}
    return identity


def _synthetic_identity_store(identities=None):
    store = MagicMock()
    identities = identities or {}
    store.resolve = MagicMock(side_effect=lambda sid: identities.get(sid))
    store.all = MagicMock(return_value=list(identities.values()))
    return store


class TestEmailNormalization:
    def test_basic_normalization(self):
        assert normalize_email("user@example.com") == "user@example.com"

    def test_trim_whitespace(self):
        assert normalize_email("  user@example.com  ") == "user@example.com"

    def test_domain_lowercase(self):
        assert normalize_email("user@EXAMPLE.COM") == "user@example.com"

    def test_local_part_preserved(self):
        assert normalize_email("User@example.com") == "User@example.com"

    def test_reject_cr(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("user\r@example.com")

    def test_reject_lf(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("user\n@example.com")

    def test_reject_display_name(self):
        with pytest.raises(InvalidEmailError):
            normalize_email('"Name" <user@example.com>')

    def test_reject_cc_indicator(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("user@example.com,other@example.com")

    def test_reject_bcc_indicator(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("user@example.com;other@example.com")

    def test_reject_empty(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("")

    def test_reject_no_at(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("userexample.com")

    def test_reject_empty_local(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("@example.com")

    def test_reject_empty_domain(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("user@")

    def test_reject_angle_brackets(self):
        with pytest.raises(InvalidEmailError):
            normalize_email("<user@example.com>")

    def test_idna_domain(self):
        result = normalize_email("user@exämple.com")
        assert "xn--" in result or "exmple" in result.lower()

    def test_is_valid_email(self):
        assert is_valid_email("user@example.com")
        assert not is_valid_email("invalid")


class TestMasking:
    def test_mask_email_basic(self):
        assert mask_email("user@example.com") == "u***@example.com"

    def test_mask_email_single_char(self):
        assert mask_email("a@example.com") == "*@example.com"

    def test_mask_email_no_at(self):
        assert mask_email("invalid") == "***"

    def test_mask_name(self):
        assert mask_name("Juan Pérez") == "J*** P***"

    def test_mask_name_single(self):
        assert mask_name("Juan") == "J***"

    def test_mask_name_empty(self):
        assert mask_name("") == ""

    def test_mask_subject(self):
        result = mask_subject("Resultados sección A — pub_001")
        assert "***" in result


class TestUnicodeNormalization:
    def test_nfc(self):
        assert normalize_unicode_nfc("e\u0301") == normalize_unicode_nfc("é")

    def test_line_endings_crlf(self):
        assert normalize_line_endings("a\r\nb") == "a\nb"

    def test_line_endings_cr(self):
        assert normalize_line_endings("a\rb") == "a\nb"

    def test_crlf_injection_detect(self):
        with pytest.raises(CRLFInjectionError):
            check_crlf_injection("subject\r\ninjection")

    def test_crlf_injection_lf(self):
        with pytest.raises(CRLFInjectionError):
            check_crlf_injection("subject\ninjection")


class TestTemplateSchema:
    def test_valid_template(self):
        t = _synthetic_template()
        assert t.template_id == "result-notification"
        assert t.template_version == "1"

    def test_unknown_placeholder_rejected(self):
        d = _synthetic_template_dict()
        d["subject"] = "{{unknownPlaceholder}}"
        with pytest.raises(UnknownPlaceholderError):
            load_template_from_dict(d)

    def test_missing_allowed_placeholders(self):
        d = _synthetic_template_dict()
        d["allowedPlaceholders"] = ["displayName"]
        with pytest.raises(UnknownPlaceholderError):
            load_template_from_dict(d)

    def test_crlf_in_subject_rejected(self):
        d = _synthetic_template_dict()
        d["subject"] = "line1\r\nline2"
        with pytest.raises(CRLFInjectionError):
            load_template_from_dict(d)


class TestRenderer:
    def test_basic_render(self):
        t = _synthetic_template()
        subject, body = render(t, {
            "displayName": "Juan Pérez",
            "sectionId": "sec_001",
            "publicationId": "pub_001",
            "resultsBlock": "EV1: 5.5 (Logrado)",
        })
        assert "Juan Pérez" in body
        assert "sec_001" in subject
        assert "pub_001" in subject

    def test_missing_placeholder_value(self):
        t = _synthetic_template()
        with pytest.raises(MissingPlaceholderValueError):
            render(t, {
                "displayName": "Juan",
                "sectionId": "sec_001",
                "publicationId": "pub_001",
            })

    def test_deterministic_render(self):
        t = _synthetic_template()
        values = {
            "displayName": "Juan Pérez",
            "sectionId": "sec_001",
            "publicationId": "pub_001",
            "resultsBlock": "EV1: 5.5",
        }
        s1, b1 = render(t, values)
        s2, b2 = render(t, values)
        assert s1 == s2
        assert b1 == b2

    def test_results_block_legacy(self):
        view = {
            "assessments": [
                {"assessmentId": "EV1", "assessmentLabel": "Evaluación 1", "status": "Logrado", "score": "5.5", "grade": "5.5"},
                {"assessmentId": "EV2", "assessmentLabel": "Evaluación 2", "status": "No Logrado", "score": "3.0", "grade": "3.0"},
            ]
        }
        block = build_results_block(view)
        assert "Evaluación 1" in block
        assert "5.5" in block
        assert "Evaluación 2" in block

    def test_results_block_c2_outcome(self):
        view = {
            "assessments": [
                {"assessmentId": "final-outcome", "assessmentLabel": "Resultado Final", "value": "5.38", "unit": "grade", "status": "finalized"},
            ]
        }
        block = build_results_block(view)
        assert "5.38" in block


class TestHashing:
    def test_item_hash_deterministic(self):
        d = {"studentId": "stu_001", "subject": "test"}
        assert compute_item_hash(d) == compute_item_hash(d)

    def test_preview_hash_deterministic(self):
        d = {"sectionId": "sec_001", "recipients": []}
        assert compute_preview_hash(d) == compute_preview_hash(d)

    def test_idempotency_key_deterministic(self):
        k1 = compute_idempotency_key("sec", "pub", "stu", "e@x.com", "tpl", "1", "notify")
        k2 = compute_idempotency_key("sec", "pub", "stu", "e@x.com", "tpl", "1", "notify")
        assert k1 == k2

    def test_idempotency_key_changes_with_component(self):
        k1 = compute_idempotency_key("sec", "pub", "stu", "e@x.com", "tpl", "1", "notify")
        k2 = compute_idempotency_key("sec", "pub", "stu", "e@x.com", "tpl", "2", "notify")
        assert k1 != k2

    def test_identity_projection_hash(self):
        h1 = compute_identity_projection_hash("stu_001", "Juan", "juan@test.com")
        h2 = compute_identity_projection_hash("stu_001", "Juan", "juan@test.com")
        assert h1 == h2
        h3 = compute_identity_projection_hash("stu_001", "Pedro", "juan@test.com")
        assert h1 != h3

    def test_plan_id_derivation(self):
        preview = "a" * 64
        plan_id = derive_plan_id(preview)
        assert plan_id.startswith("eplan_")
        assert len(plan_id) == 6 + 24

    def test_template_hash(self):
        d = _synthetic_template_dict()
        h1 = compute_template_hash(d)
        h2 = compute_template_hash(d)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_content_different_hash(self):
        h1 = compute_hash({"a": 1})
        h2 = compute_hash({"a": 2})
        assert h1 != h2


class TestLedgerStateMachine:
    def test_reserve_delivery(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_001", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert did > 0

    def test_duplicate_idempotency_key_rejected(self, ledger):
        _register_test_plan(ledger)
        ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_001", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        with pytest.raises(IdempotencyConflictError):
            ledger.reserve_delivery(
                plan_id="eplan_test", student_id="stu_001",
                idempotency_key="key_001", normalized_recipient="u@x.com",
                masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
                client_message_id="<msg@test>",
            )

    def test_transition_reserved_to_sending(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_002", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        d = ledger.get_delivery_by_key("key_002")
        assert d.state == DeliveryState.SENDING

    def test_transition_sending_to_sent(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_003", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.SENT)
        d = ledger.get_delivery_by_key("key_003")
        assert d.state == DeliveryState.SENT

    def test_sent_is_terminal(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_004", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.SENT)
        with pytest.raises(DeliveryStateError):
            ledger.transition_delivery(did, DeliveryState.SENT, DeliveryState.SENDING)

    def test_failed_permanent_is_terminal(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_005", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.FAILED_PERMANENT)
        with pytest.raises(DeliveryStateError):
            ledger.transition_delivery(did, DeliveryState.FAILED_PERMANENT, DeliveryState.RESERVED)

    def test_sending_to_ambiguous(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_006", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.AMBIGUOUS)
        d = ledger.get_delivery_by_key("key_006")
        assert d.state == DeliveryState.AMBIGUOUS

    def test_failed_transient_to_retry_authorized(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_007", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.FAILED_TRANSIENT)
        ledger.transition_delivery(did, DeliveryState.FAILED_TRANSIENT, DeliveryState.RETRY_AUTHORIZED)
        d = ledger.get_delivery_by_key("key_007")
        assert d.state == DeliveryState.RETRY_AUTHORIZED

    def test_invalid_transition_rejected(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_008", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        with pytest.raises(DeliveryStateError):
            ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENT)

    def test_approval_recorded(self, ledger):
        ledger.register_plan(
            plan_id="eplan_test", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        record = ApprovalRecord(
            plan_id="eplan_test", preview_hash="p" * 64, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        result = ledger.get_approval("eplan_test")
        assert result is not None
        assert result.preview_hash == "p" * 64

    def test_template_version_registration(self, ledger):
        ledger.register_template_version("tpl", "1", "a" * 64)
        ledger.register_template_version("tpl", "1", "a" * 64)
        with pytest.raises(TemplateHashMismatchError):
            ledger.register_template_version("tpl", "1", "b" * 64)

    def test_integrity_check(self, ledger):
        issues = ledger.integrity_check()
        assert issues == []

    def test_batch_run(self, ledger):
        ledger.register_plan(
            plan_id="eplan_br", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        brid = ledger.start_batch_run("eplan_br", "p" * 64, "fake", 2, "system")
        ledger.complete_batch_run(brid, 2, 0, 0, 0, "COMPLETE")
        runs = ledger.get_batch_runs("eplan_br")
        assert len(runs) == 1
        assert runs[0].outcome == "COMPLETE"

    def test_delivery_attempts_recorded(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_att", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.SENT)
        d = ledger.get_delivery_by_key("key_att")
        assert d.attempt_count == 2


class TestReconciliation:
    def test_reconcile_orphan_reserved(self, ledger):
        ledger.register_plan(
            plan_id="eplan_rec", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_rec", student_id="stu_001",
            idempotency_key="key_rec1", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        events = reconcile_plan("eplan_rec", ledger, orphan_timeout_seconds=0)
        assert len(events) >= 1
        assert events[0]["toState"] == "retryAuthorized"

    def test_resolve_ambiguous_sent(self, ledger):
        ledger.register_plan(
            plan_id="eplan_amb", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_amb", student_id="stu_001",
            idempotency_key="key_amb1", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.AMBIGUOUS)

        result = resolve_ambiguous(
            plan_id="eplan_amb", student_id="stu_001",
            decision="sent", actor="staff.opaque", reason="provider confirmed",
            ledger=ledger, confirm=True,
        )
        assert result["newState"] == "sent"

    def test_resolve_ambiguous_not_sent(self, ledger):
        ledger.register_plan(
            plan_id="eplan_amb2", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_amb2", student_id="stu_001",
            idempotency_key="key_amb2", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.AMBIGUOUS)

        result = resolve_ambiguous(
            plan_id="eplan_amb2", student_id="stu_001",
            decision="not-sent", actor="staff.opaque", reason="bounce confirmed",
            ledger=ledger, confirm=True,
        )
        assert result["newState"] == "retryAuthorized"

    def test_resolve_ambiguous_requires_confirm(self, ledger):
        with pytest.raises(AmbiguousResolutionError):
            resolve_ambiguous(
                plan_id="eplan_x", student_id="stu_001",
                decision="sent", actor="staff.opaque", reason="test",
                ledger=ledger, confirm=False,
            )

    def test_resolve_ambiguous_invalid_decision(self, ledger):
        with pytest.raises(AmbiguousResolutionError):
            resolve_ambiguous(
                plan_id="eplan_x", student_id="stu_001",
                decision="maybe", actor="staff.opaque", reason="test",
                ledger=ledger, confirm=True,
            )


class TestDeterminism:
    def test_same_inputs_same_preview_hash(self):
        core1 = {"sectionId": "sec_001", "recipients": [{"studentId": "stu_001"}]}
        core2 = {"sectionId": "sec_001", "recipients": [{"studentId": "stu_001"}]}
        assert compute_preview_hash(core1) == compute_preview_hash(core2)

    def test_subject_order_no_effect_on_hash(self):
        core1 = {"sectionId": "sec", "recipients": [{"studentId": "a"}, {"studentId": "b"}]}
        core2 = {"sectionId": "sec", "recipients": [{"studentId": "a"}, {"studentId": "b"}]}
        assert compute_preview_hash(core1) == compute_preview_hash(core2)

    def test_different_recipient_different_hash(self):
        core1 = {"sectionId": "sec", "recipients": [{"studentId": "a"}]}
        core2 = {"sectionId": "sec", "recipients": [{"studentId": "b"}]}
        assert compute_preview_hash(core1) != compute_preview_hash(core2)

    def test_clock_not_in_core(self):
        core = {"sectionId": "sec", "recipients": []}
        h1 = compute_preview_hash(core)
        time.sleep(0.01)
        h2 = compute_preview_hash(core)
        assert h1 == h2


class TestPrivacy:
    def test_mask_email_no_full_email(self):
        masked = mask_email("longuser@example.com")
        assert "longuser" not in masked
        assert "***" in masked

    def test_mask_name_no_full_name(self):
        masked = mask_name("Juan Pérez")
        assert "Juan" not in masked
        assert "Pérez" not in masked

    def test_ledger_stores_masked_recipient(self, ledger):
        ledger.register_plan(
            plan_id="eplan_priv", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_priv", student_id="stu_001",
            idempotency_key="key_priv", normalized_recipient="fulluser@example.com",
            masked_recipient="f***@example.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        d = ledger.get_delivery_by_key("key_priv")
        assert d.masked_recipient == "f***@example.com"
        assert d.normalized_recipient == "fulluser@example.com"

    def test_ledger_no_body_stored(self, ledger):
        deliveries = ledger.get_deliveries_for_plan("nonexistent")
        for d in deliveries:
            assert not hasattr(d, 'body')
            assert not hasattr(d, 'subject')


class TestFakeTransport:
    def test_success(self):
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        transport.preflight(config)
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("test body")
        msg["Subject"] = "test"
        msg["From"] = "noreply@test.com"
        msg["To"] = "user@test.com"
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        receipt = transport.send(msg, envelope)
        assert receipt.accepted
        assert receipt.response_code == 250

    def test_auth_failure(self):
        transport = FakeTransport(behavior=FakeBehavior.AUTH_FAILURE)
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(Exception):
            transport.preflight(config)

    def test_invalid_recipient(self):
        transport = FakeTransport(behavior=FakeBehavior.INVALID_RECIPIENT)
        config = TransportConfig(host="localhost", port=0, username="")
        transport.preflight(config)
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("test")
        msg["Subject"] = "test"
        envelope = Envelope(from_address="noreply@test.com", to_address="bad@test.com")
        with pytest.raises(Exception) as exc_info:
            transport.send(msg, envelope)
        assert exc_info.value.retryability == "permanent"

    def test_transient_failure(self):
        transport = FakeTransport(behavior=FakeBehavior.TRANSIENT_FAILURE)
        config = TransportConfig(host="localhost", port=0, username="")
        transport.preflight(config)
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("test")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with pytest.raises(Exception) as exc_info:
            transport.send(msg, envelope)
        assert exc_info.value.retryability == "transient"
        assert exc_info.value.delivery_certainty == "notSent"

    def test_ambiguous(self):
        transport = FakeTransport(behavior=FakeBehavior.AMBIGUOUS)
        config = TransportConfig(host="localhost", port=0, username="")
        transport.preflight(config)
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("test")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with pytest.raises(Exception) as exc_info:
            transport.send(msg, envelope)
        assert exc_info.value.delivery_certainty == "unknown"


class TestConcurrency:
    def test_concurrent_reserve_same_key(self, ledger):
        ledger.register_plan(
            plan_id="eplan_conc", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        results = [None, None]

        def reserve(idx):
            try:
                ledger.reserve_delivery(
                    plan_id="eplan_conc", student_id=f"stu_{idx}",
                    idempotency_key="shared_key", normalized_recipient="u@x.com",
                    masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
                    client_message_id="<msg@test>",
                )
                results[idx] = "success"
            except IdempotencyConflictError:
                results[idx] = "conflict"

        t1 = threading.Thread(target=reserve, args=(0,))
        t2 = threading.Thread(target=reserve, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert "success" in results
        assert "conflict" in results

    def test_concurrent_different_keys(self, ledger):
        ledger.register_plan(
            plan_id="eplan_conc2", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        results = [None, None]

        def reserve(idx):
            try:
                ledger.reserve_delivery(
                    plan_id="eplan_conc2", student_id=f"stu_{idx}",
                    idempotency_key=f"key_{idx}", normalized_recipient=f"u{idx}@x.com",
                    masked_recipient=f"u***@x.com", identity_projection_hash="h" * 64,
                    client_message_id="<msg@test>",
                )
                results[idx] = "success"
            except Exception as exc:
                results[idx] = f"error: {exc}"

        t1 = threading.Thread(target=reserve, args=(0,))
        t2 = threading.Thread(target=reserve, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert results[0] == "success"
        assert results[1] == "success"


class TestLedgerBackup:
    def test_backup_and_restore(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        backup_path = tmp_dir / "backups" / "ledger-backup.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_bk", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        lg.backup(backup_path)
        assert backup_path.exists()
        lg.close()

        lg2 = EmailLedger(backup_path)
        approval = lg2.get_approval("eplan_bk")
        lg2.close()


class TestLedgerRestart:
    def test_sent_preserved_after_restart(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg1 = EmailLedger(db_path)
        lg1.register_plan(
            plan_id="eplan_rst", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = lg1.reserve_delivery(
            plan_id="eplan_rst", student_id="stu_001",
            idempotency_key="key_rst", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        lg1.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        lg1.transition_delivery(did, DeliveryState.SENDING, DeliveryState.SENT)
        lg1.close()

        lg2 = EmailLedger(db_path)
        d = lg2.get_delivery_by_key("key_rst")
        assert d.state == DeliveryState.SENT
        lg2.close()


class TestSMTPErrorClassification:
    def test_auth_error_is_batch_permanent(self):
        from email_delivery.transport.smtp import SMTPTransport
        from email_delivery.errors import BatchTransportError
        transport = SMTPTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(BatchTransportError) as exc_info:
            transport.preflight(config)
        assert exc_info.value.scope == "batch"
        assert exc_info.value.retryability == "permanent"


class TestSchemaValidation:
    def test_template_schema_valid(self):
        from email_delivery.schemas import TEMPLATE_SCHEMA_V1
        try:
            import jsonschema
            jsonschema.validate(_synthetic_template_dict(), TEMPLATE_SCHEMA_V1)
        except ImportError:
            pytest.skip("jsonschema not available")

    def test_plan_schema_structure(self):
        from email_delivery.schemas import PLAN_SCHEMA_V1
        assert PLAN_SCHEMA_V1["type"] == "object"
        assert "planId" in PLAN_SCHEMA_V1["properties"]

    def test_approval_schema_structure(self):
        from email_delivery.schemas import APPROVAL_SCHEMA_V1
        assert APPROVAL_SCHEMA_V1["type"] == "object"
        assert "previewHash" in APPROVAL_SCHEMA_V1["properties"]


class TestStudentEmailView:
    def test_legacy_view(self):
        view = StudentEmailView(
            schema_version="1.0.0",
            student_id="stu_001",
            section_id="sec_001",
            publication_id="pub_001",
            snapshot_mode="legacy-effective",
            assessments=(
                {"assessmentId": "EV1", "assessmentLabel": "EV1", "status": "Logrado", "score": "5.5", "grade": "5.5"},
            ),
        )
        d = view.to_dict()
        assert d["schemaVersion"] == "1.0.0"
        assert d["snapshotMode"] == "legacy-effective"
        assert len(d["assessments"]) == 1

    def test_c2_view(self):
        view = StudentEmailView(
            schema_version="1.0.0",
            student_id="stu_001",
            section_id="sec_001",
            publication_id="pub_001",
            snapshot_mode="grade-policy-effective",
            assessments=(
                {"assessmentId": "final-outcome", "value": "5.38", "unit": "grade", "status": "finalized", "resultState": "finalized", "finalizable": True},
            ),
        )
        d = view.to_dict()
        assert d["snapshotMode"] == "grade-policy-effective"


class TestPlanRecipient:
    def test_recipient_dict(self):
        r = PlanRecipient(
            student_id="stu_001",
            normalized_recipient="user@example.test",
            masked_recipient="u***@example.test",
            identity_projection_hash="i" * 64,
            subject="Test Subject",
            text_body="Test Body",
            item_hash="h" * 64,
            idempotency_key="k" * 64,
        )
        d = r.to_dict()
        assert d["studentId"] == "stu_001"
        assert d["maskedRecipient"] == "u***@example.test"
        assert "textBody" in d


class TestExecuteWithFakeTransport:
    def _setup_plan_and_ledger(self, tmp_dir):
        from email_delivery.ledger import EmailLedger
        from email_delivery.plan import prepare_plan

        db_path = tmp_dir / "ledger.sqlite3"
        ledger = EmailLedger(db_path)

        snapshot_dir = tmp_dir / "snapshot" / "sections" / "sec_001" / "pub_001"
        canonical_dir = snapshot_dir / "canonical"
        canonical_dir.mkdir(parents=True, exist_ok=True)

        subjects = {"subjects": [
            {"studentId": "stu_001", "status": "active"},
            {"studentId": "stu_002", "status": "active"},
        ]}
        write_json(canonical_dir / "subjects.json", subjects)

        results = {"results": [
            {"studentId": "stu_001", "assessmentId": "EV1", "status": "Logrado", "score": "5.5", "grade": "5.5"},
            {"studentId": "stu_002", "assessmentId": "EV1", "status": "No Logrado", "score": "3.0", "grade": "3.0"},
        ]}
        write_json(canonical_dir / "results.json", results)

        assessments = {"assessments": [
            {"assessmentId": "EV1", "label": "Evaluación 1", "unit": "grade"},
        ]}
        write_json(canonical_dir / "assessments.json", assessments)

        manifest = {"contentHash": "c" * 64, "reviewHash": "r" * 64}
        write_json(snapshot_dir / "manifest.json", manifest)

        identities = {
            "stu_001": _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test"),
            "stu_002": _synthetic_identity("stu_002", "María López", "maria@example.test"),
        }
        identity_store = _synthetic_identity_store(identities)

        template_path = tmp_dir / "template.json"
        write_json(template_path, _synthetic_template_dict())

        sender_path = tmp_dir / "sender.json"
        write_json(sender_path, {
            "schemaVersion": "1.0.0",
            "senderProfileId": "staff-default",
            "fromAddress": "noreply@example.test",
            "replyTo": "docente@example.test",
        })

        private_root = tmp_dir / "private"
        temp_root = tmp_dir / "temp"
        private_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)

        return ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root

    def test_prepare_approve_execute_fake(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root,
        )

        plan_dir = private_root / "email" / "plans" / "sec_001" / "pub_001" / plan.plan_id
        ledger.register_plan(
            plan_id=plan.plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id=plan.template_id,
            template_version=plan.template_version, template_hash=plan.template_hash,
            intent=plan.intent, sender_profile_id=plan.sender_profile_id,
            from_address=plan.from_address, reply_to=plan.reply_to,
            preview_hash=plan.preview_hash, recipient_count=plan.recipient_count,
            plan_path=str(plan_dir),
        )

        record = approve_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            recipient_count=plan.recipient_count, actor="staff.opaque",
            ledger=ledger, plan_dir=plan_dir, identity_store=identity_store,
        )

        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")

        outcome = execute_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
        )

        assert outcome == ExecuteOutcome.COMPLETE
        deliveries = ledger.get_deliveries_for_plan(plan.plan_id)
        assert all(d.state == DeliveryState.SENT for d in deliveries)

    def test_execute_idempotent(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root,
        )

        plan_dir = private_root / "email" / "plans" / "sec_001" / "pub_001" / plan.plan_id
        ledger.register_plan(
            plan_id=plan.plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id=plan.template_id,
            template_version=plan.template_version, template_hash=plan.template_hash,
            intent=plan.intent, sender_profile_id=plan.sender_profile_id,
            from_address=plan.from_address, reply_to=plan.reply_to,
            preview_hash=plan.preview_hash, recipient_count=plan.recipient_count,
            plan_path=str(plan_dir),
        )

        approve_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            recipient_count=plan.recipient_count, actor="staff.opaque",
            ledger=ledger, plan_dir=plan_dir, identity_store=identity_store,
        )

        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")

        outcome1 = execute_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
        )

        transport2 = FakeTransport()
        outcome2 = execute_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            ledger=ledger, transport=transport2, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
        )

        assert outcome2 == ExecuteOutcome.COMPLETE
        assert transport2.sent_count == 0

    def test_execute_not_approved_blocked(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root,
        )

        plan_dir = private_root / "email" / "plans" / "sec_001" / "pub_001" / plan.plan_id
        ledger.register_plan(
            plan_id=plan.plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id=plan.template_id,
            template_version=plan.template_version, template_hash=plan.template_hash,
            intent=plan.intent, sender_profile_id=plan.sender_profile_id,
            from_address=plan.from_address, reply_to=plan.reply_to,
            preview_hash=plan.preview_hash, recipient_count=plan.recipient_count,
            plan_path=str(plan_dir),
        )

        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")

        with pytest.raises(Exception):
            execute_plan(
                plan_id=plan.plan_id, preview_hash=plan.preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
            )

    def test_auth_failure_stops_batch(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root,
        )

        plan_dir = private_root / "email" / "plans" / "sec_001" / "pub_001" / plan.plan_id
        ledger.register_plan(
            plan_id=plan.plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id=plan.template_id,
            template_version=plan.template_version, template_hash=plan.template_hash,
            intent=plan.intent, sender_profile_id=plan.sender_profile_id,
            from_address=plan.from_address, reply_to=plan.reply_to,
            preview_hash=plan.preview_hash, recipient_count=plan.recipient_count,
            plan_path=str(plan_dir),
        )

        approve_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            recipient_count=plan.recipient_count, actor="staff.opaque",
            ledger=ledger, plan_dir=plan_dir, identity_store=identity_store,
        )

        transport = FakeTransport(behavior=FakeBehavior.AUTH_FAILURE)
        config = TransportConfig(host="localhost", port=0, username="")

        with pytest.raises(Exception):
            execute_plan(
                plan_id=plan.plan_id, preview_hash=plan.preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
            )


class TestFailureInjection:
    def test_crash_after_reserved(self, ledger):
        ledger.register_plan(
            plan_id="eplan_fi1", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_fi1", student_id="stu_001",
            idempotency_key="key_fi1", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        events = reconcile_plan("eplan_fi1", ledger, orphan_timeout_seconds=0)
        assert len(events) >= 1
        assert events[0]["toState"] == "retryAuthorized"

    def test_crash_after_sending(self, ledger):
        ledger.register_plan(
            plan_id="eplan_fi2", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_fi2", student_id="stu_001",
            idempotency_key="key_fi2", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        events = reconcile_plan("eplan_fi2", ledger, orphan_timeout_seconds=0)
        assert len(events) >= 1
        assert events[0]["toState"] == "ambiguous"

    def test_permanent_failure_no_auto_retry(self, ledger):
        _register_test_plan(ledger, "eplan_fi3")
        ledger.register_plan(
            plan_id="eplan_fi3", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_fi3", student_id="stu_001",
            idempotency_key="key_fi3", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.FAILED_PERMANENT)
        d = ledger.get_delivery_by_key("key_fi3")
        assert d.state == DeliveryState.FAILED_PERMANENT
        with pytest.raises(DeliveryStateError):
            ledger.transition_delivery(did, DeliveryState.FAILED_PERMANENT, DeliveryState.RESERVED)

    def test_ambiguous_no_auto_retry(self, ledger):
        _register_test_plan(ledger, "eplan_fi4")
        ledger.register_plan(
            plan_id="eplan_fi4", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        did = ledger.reserve_delivery(
            plan_id="eplan_fi4", student_id="stu_001",
            idempotency_key="key_fi4", normalized_recipient="u@x.com",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.AMBIGUOUS)
        d = ledger.get_delivery_by_key("key_fi4")
        assert d.state == DeliveryState.AMBIGUOUS
        with pytest.raises(DeliveryStateError):
            ledger.transition_delivery(did, DeliveryState.AMBIGUOUS, DeliveryState.SENDING)
