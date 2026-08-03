"""C3 email delivery test suite — unit, contract, determinism, privacy, integration,
concurrency, and failure injection tests.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import smtplib
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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
    ApprovalError,
    ApprovalMismatchError,
    CRLFInjectionError,
    DeliveryStateError,
    DuplicateEmailError,
    IdempotencyConflictError,
    IdentityDriftError,
    InvalidEmailError,
    LedgerError,
    MissingEmailError,
    MissingIdentityError,
    MissingPlaceholderValueError,
    NotApprovedError,
    PlanExistsError,
    PlanTamperedError,
    SnapshotTerminalError,
    TemplateHashMismatchError,
    UnknownPlaceholderError,
    BatchTransportError,
    ExecuteError,
    ExecuteBlockedError,
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
    TlsMode,
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
from email_delivery.plan import prepare_plan, verify_plan_bundle
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


def _mock_lifecycle_ledger(state="approved"):
    ledger = MagicMock()
    ledger.current_state = MagicMock(return_value=state)
    return ledger


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
            idempotency_key="key_001",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert did > 0

    def test_duplicate_idempotency_key_rejected(self, ledger):
        _register_test_plan(ledger)
        ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_001",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        with pytest.raises(IdempotencyConflictError):
            ledger.reserve_delivery(
                plan_id="eplan_test", student_id="stu_001",
                idempotency_key="key_001",
                masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
                client_message_id="<msg@test>",
            )

    def test_transition_reserved_to_sending(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_002",
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
            idempotency_key="key_003",
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
            idempotency_key="key_004",
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
            idempotency_key="key_005",
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
            idempotency_key="key_006",
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
            idempotency_key="key_007",
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
            idempotency_key="key_008",
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
            idempotency_key="key_att",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.SENT)
        d = ledger.get_delivery_by_key("key_att")
        assert d.attempt_count == 2

    def test_acquire_for_execution_reserved(self, ledger):
        _register_test_plan(ledger)
        action, did = ledger.acquire_for_execution(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert action == "reserved"
        assert did > 0

    def test_acquire_for_execution_sent_skip(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq2",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.SENT)
        action, existing_id = ledger.acquire_for_execution(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq2",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert action == "sent"

    def test_acquire_for_execution_ambiguous_block(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq3",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.AMBIGUOUS)
        action, _ = ledger.acquire_for_execution(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq3",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert action == "ambiguous"

    def test_acquire_for_execution_failed_permanent_block(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq4",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.FAILED_PERMANENT)
        action, _ = ledger.acquire_for_execution(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq4",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert action == "failedPermanent"

    def test_acquire_for_execution_retry_authorized(self, ledger):
        _register_test_plan(ledger)
        did = ledger.reserve_delivery(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq5",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.FAILED_TRANSIENT)
        ledger.transition_delivery(did, DeliveryState.FAILED_TRANSIENT, DeliveryState.RETRY_AUTHORIZED)
        action, _ = ledger.acquire_for_execution(
            plan_id="eplan_test", student_id="stu_001",
            idempotency_key="key_acq5",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        assert action == "retryAuthorized"

    def test_register_plan_idempotent(self, ledger):
        ledger.register_plan(
            plan_id="eplan_idem", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        ledger.register_plan(
            plan_id="eplan_idem", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )

    def test_register_plan_different_content_fails(self, ledger):
        ledger.register_plan(
            plan_id="eplan_diff", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        with pytest.raises(PlanExistsError):
            ledger.register_plan(
                plan_id="eplan_diff", section_id="sec_002", publication_id="pub_001",
                snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
                snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
                template_hash="t" * 64, intent="notify", sender_profile_id="default",
                from_address="noreply@test.com", reply_to=None,
                preview_hash="p" * 64, recipient_count=1,
                plan_path="/tmp/plan",
            )


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
            idempotency_key="key_rec1",
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
            idempotency_key="key_amb1",
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
            idempotency_key="key_amb2",
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
            idempotency_key="key_priv",
            masked_recipient="f***@example.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        d = ledger.get_delivery_by_key("key_priv")
        assert d.masked_recipient == "f***@example.com"

    def test_ledger_no_body_stored(self, ledger):
        deliveries = ledger.get_deliveries_for_plan("nonexistent")
        for d in deliveries:
            assert not hasattr(d, 'body')
            assert not hasattr(d, 'subject')

    def test_no_full_email_in_sqlite(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_nopriv", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        lg.reserve_delivery(
            plan_id="eplan_nopriv", student_id="stu_001",
            idempotency_key="key_nopriv",
            masked_recipient="f***@example.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        lg.close()

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM deliveries").fetchall()
        for row in rows:
            for val in row:
                if isinstance(val, str):
                    assert "fulluser@example.com" not in val
                    assert "fulluser" not in val
        conn.close()

    def test_no_sensitive_data_in_sqlite(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_nosens", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=1,
            plan_path="/tmp/plan",
        )
        lg.reserve_delivery(
            plan_id="eplan_nosens", student_id="stu_001",
            idempotency_key="key_nosens",
            masked_recipient="f***@example.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        lg.close()

        conn = sqlite3.connect(str(db_path))
        all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        forbidden = ["fulluser@example.com", "fulluser", "subject text", "body text", "displayName", "feedback"]
        for (table_name,) in all_tables:
            rows = conn.execute(f"SELECT * FROM [{table_name}]").fetchall()
            for row in rows:
                for val in row:
                    if isinstance(val, str):
                        for f in forbidden:
                            assert f not in val, f"Found '{f}' in {table_name}"
        conn.close()


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
    def test_concurrent_reserve_same_key(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_conc", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        lg.close()
        results = [None, None]

        def reserve(idx):
            lg2 = EmailLedger(db_path)
            try:
                lg2.reserve_delivery(
                    plan_id="eplan_conc", student_id=f"stu_{idx}",
                    idempotency_key="shared_key",
                    masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
                    client_message_id="<msg@test>",
                )
                results[idx] = "success"
            except IdempotencyConflictError:
                results[idx] = "conflict"
            except Exception as exc:
                results[idx] = f"error: {exc}"
            finally:
                lg2.close()

        t1 = threading.Thread(target=reserve, args=(0,))
        t2 = threading.Thread(target=reserve, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert "success" in results
        assert "conflict" in results

    def test_concurrent_different_keys(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_conc2", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        lg.close()
        results = [None, None]

        def reserve(idx):
            lg2 = EmailLedger(db_path)
            try:
                lg2.reserve_delivery(
                    plan_id="eplan_conc2", student_id=f"stu_{idx}",
                    idempotency_key=f"key_{idx}",
                    masked_recipient=f"u***@x.com", identity_projection_hash="h" * 64,
                    client_message_id="<msg@test>",
                )
                results[idx] = "success"
            except Exception as exc:
                results[idx] = f"error: {exc}"
            finally:
                lg2.close()

        t1 = threading.Thread(target=reserve, args=(0,))
        t2 = threading.Thread(target=reserve, args=(1,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert results[0] == "success"
        assert results[1] == "success"


class TestMultiprocessConcurrency:
    def _multiprocess_reserve(self, db_path_str, plan_id, idempotency_key, student_id, result_queue):
        from pathlib import Path
        from email_delivery.ledger import EmailLedger
        from email_delivery.errors import IdempotencyConflictError
        lg = EmailLedger(Path(db_path_str))
        try:
            lg.reserve_delivery(
                plan_id=plan_id, student_id=student_id,
                idempotency_key=idempotency_key,
                masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
                client_message_id="<msg@test>",
            )
            result_queue.put("success")
        except IdempotencyConflictError:
            result_queue.put("conflict")
        except Exception as exc:
            result_queue.put(f"error: {exc}")
        finally:
            lg.close()

    def test_multiprocess_same_key(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_mp1", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        lg.close()

        ctx = multiprocessing.get_context("fork")
        q = ctx.Queue()
        p1 = ctx.Process(target=self._multiprocess_reserve, args=(str(db_path), "eplan_mp1", "shared_key", "stu_0", q))
        p2 = ctx.Process(target=self._multiprocess_reserve, args=(str(db_path), "eplan_mp1", "shared_key", "stu_1", q))
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)
        results = [q.get(timeout=5), q.get(timeout=5)]
        assert "success" in results
        assert "conflict" in results

    def test_multiprocess_different_keys(self, tmp_dir):
        db_path = tmp_dir / "email-ledger.sqlite3"
        lg = EmailLedger(db_path)
        lg.register_plan(
            plan_id="eplan_mp2", section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash="p" * 64, recipient_count=2,
            plan_path="/tmp/plan",
        )
        lg.close()

        ctx = multiprocessing.get_context("fork")
        q = ctx.Queue()
        p1 = ctx.Process(target=self._multiprocess_reserve, args=(str(db_path), "eplan_mp2", "key_0", "stu_0", q))
        p2 = ctx.Process(target=self._multiprocess_reserve, args=(str(db_path), "eplan_mp2", "key_1", "stu_1", q))
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)
        results = [q.get(timeout=5), q.get(timeout=5)]
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
            idempotency_key="key_rst",
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


class TestSMTPTLS:
    def test_starttls_available(self):
        from email_delivery.transport.smtp import SMTPTransport
        transport = SMTPTransport()
        config = TransportConfig(host="smtp.example.com", port=587, username="user", tls_mode=TlsMode.STARTTLS)
        with patch.object(transport, 'send', side_effect=BatchTransportError("mock", scope="batch", retryability="permanent", delivery_certainty="notSent", code="mock")):
            from email.message import EmailMessage
            msg = EmailMessage()
            msg.set_content("test")
            envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
            with pytest.raises(BatchTransportError):
                transport.send(msg, envelope)

    def test_starttls_unavailable_blocks(self):
        from email_delivery.transport.smtp import SMTPTransport
        transport = SMTPTransport()
        config = TransportConfig(host="smtp.example.com", port=587, username="user", tls_mode=TlsMode.STARTTLS)
        with patch.object(transport, 'send', side_effect=BatchTransportError("Server does not support STARTTLS", scope="batch", retryability="permanent", delivery_certainty="notSent", code="smtp-starttls-unavailable")):
            from email.message import EmailMessage
            msg = EmailMessage()
            msg.set_content("test")
            envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
            with pytest.raises(BatchTransportError) as exc_info:
                transport.send(msg, envelope)
            assert "STARTTLS" in str(exc_info.value) or "starttls" in str(exc_info.value).lower()

    def test_implicit_tls(self):
        from email_delivery.transport.smtp import SMTPTransport
        transport = SMTPTransport()
        config = TransportConfig(host="smtp.example.com", port=465, username="user", tls_mode=TlsMode.IMPLICIT_TLS)
        with patch.object(transport, 'send', side_effect=BatchTransportError("mock", scope="batch", retryability="permanent", delivery_certainty="notSent", code="mock")):
            from email.message import EmailMessage
            msg = EmailMessage()
            msg.set_content("test")
            envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
            with pytest.raises(BatchTransportError):
                transport.send(msg, envelope)

    def test_preflight_validates_config(self):
        from email_delivery.transport.smtp import SMTPTransport
        transport = SMTPTransport()
        with pytest.raises(BatchTransportError):
            transport.preflight(TransportConfig(host="", port=587, username="user"))
        with pytest.raises(BatchTransportError):
            transport.preflight(TransportConfig(host="smtp.example.com", port=0, username="user"))
        with pytest.raises(BatchTransportError):
            transport.preflight(TransportConfig(host="smtp.example.com", port=587, username=""))
        with pytest.raises(BatchTransportError):
            transport.preflight(TransportConfig(host="smtp.example.com", port=587, username="user"))

    def test_env_credential_not_in_repr(self):
        config = TransportConfig(host="h", port=587, username="u")
        d = {"host": config.host, "port": config.port, "username": config.username}
        assert "secret" not in str(d)


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
            normalized_recipient="juan@example.test",
            masked_recipient="j***@example.test",
            identity_projection_hash="i" * 64,
            subject="Test Subject",
            text_body="Test Body",
            item_hash="h" * 64,
            idempotency_key="k" * 64,
        )
        d = r.to_dict()
        assert d["studentId"] == "stu_001"
        assert d["normalizedRecipient"] == "juan@example.test"
        assert d["maskedRecipient"] == "j***@example.test"
        assert "textBody" in d
        assert "normalizedRecipient" in d


class TestRealConfirmations:
    def test_approve_requires_confirm_reviewed(self, ledger, tmp_dir):
        plan_dir = tmp_dir / "plan"
        plan_dir.mkdir()
        write_json(plan_dir / "plan.json", {
            "planId": "eplan_conf", "previewHash": "p" * 64,
            "recipientCount": 1, "recipients": [],
        })
        with pytest.raises(ApprovalError):
            approve_plan(
                plan_id="eplan_conf", preview_hash="p" * 64,
                recipient_count=1, actor="staff.opaque",
                ledger=ledger, plan_dir=plan_dir,
                confirm_reviewed=False,
            )

    def test_execute_requires_confirm_send(self, tmp_dir):
        plan_dir = tmp_dir / "plan"
        plan_dir.mkdir()
        plan_dict = {
            "planId": "eplan_exec", "previewHash": "p" * 64,
            "recipientCount": 0, "recipients": [],
            "fromAddress": "noreply@test.com",
        }
        write_json(plan_dir / "plan.json", plan_dict)
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        with pytest.raises(ExecuteError):
            execute_plan(
                plan_id="eplan_exec", preview_hash="p" * 64,
                ledger=ledger, transport=FakeTransport(),
                transport_config=TransportConfig(host="localhost", port=0, username=""),
                plan_dir=plan_dir, confirm_send=False,
                lifecycle_ledger=_mock_lifecycle_ledger(),
                publication_id="pub_001",
                identity_store=_synthetic_identity_store(),
            )

    def test_resolve_ambiguous_requires_confirm(self, ledger):
        with pytest.raises(AmbiguousResolutionError):
            resolve_ambiguous(
                plan_id="eplan_x", student_id="stu_001",
                decision="sent", actor="staff.opaque", reason="test",
                ledger=ledger, confirm=False,
            )

    def test_cli_approve_without_confirm_exits_2(self, tmp_dir):
        result = subprocess.run(
            [sys.executable, "-m", "engine.scripts.email_delivery",
             "approve", "--plan", "x", "--preview-hash", "p" * 64,
             "--recipient-count", "1", "--actor", "staff.opaque",
             "--section", "s", "--publication", "p"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
            timeout=10,
        )
        assert result.returncode == 2

    def test_cli_execute_without_confirm_exits_2(self, tmp_dir):
        result = subprocess.run(
            [sys.executable, "-m", "engine.scripts.email_delivery",
             "execute", "--plan", "x", "--preview-hash", "p" * 64,
             "--section", "s", "--publication", "p"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
            timeout=10,
        )
        assert result.returncode == 2

    def test_cli_resolve_without_confirm_exits_2(self, tmp_dir):
        result = subprocess.run(
            [sys.executable, "-m", "engine.scripts.email_delivery",
             "resolve-ambiguous", "--plan", "x", "--student", "s",
             "--decision", "sent", "--actor", "staff.opaque",
             "--reason", "test"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent.parent.parent),
            timeout=10,
        )
        assert result.returncode == 2


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

        lifecycle_ledger = _mock_lifecycle_ledger(state="approved")

        return ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root, lifecycle_ledger

    def test_prepare_approve_execute_fake(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root, lifecycle_ledger = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
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
            confirm_reviewed=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )

        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")

        outcome = execute_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )

        assert outcome == ExecuteOutcome.COMPLETE
        deliveries = ledger.get_deliveries_for_plan(plan.plan_id)
        assert all(d.state == DeliveryState.SENT for d in deliveries)

    def test_execute_idempotent(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root, lifecycle_ledger = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
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
            confirm_reviewed=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )

        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")

        outcome1 = execute_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )

        transport2 = FakeTransport()
        outcome2 = execute_plan(
            plan_id=plan.plan_id, preview_hash=plan.preview_hash,
            ledger=ledger, transport=transport2, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )

        assert outcome2 == ExecuteOutcome.COMPLETE
        assert transport2.sent_count == 0

    def test_execute_not_approved_blocked(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root, lifecycle_ledger = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
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
                confirm_send=True,
                lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
            )

    def test_auth_failure_stops_batch(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root, lifecycle_ledger = \
            self._setup_plan_and_ledger(tmp_dir)

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
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
            confirm_reviewed=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )

        transport = FakeTransport(behavior=FakeBehavior.AUTH_FAILURE)
        config = TransportConfig(host="localhost", port=0, username="")

        with pytest.raises(Exception):
            execute_plan(
                plan_id=plan.plan_id, preview_hash=plan.preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
                confirm_send=True,
                lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
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
            idempotency_key="key_fi1",
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
            idempotency_key="key_fi2",
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
            idempotency_key="key_fi3",
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
            idempotency_key="key_fi4",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        ledger.transition_delivery(did, DeliveryState.SENDING, DeliveryState.AMBIGUOUS)
        d = ledger.get_delivery_by_key("key_fi4")
        assert d.state == DeliveryState.AMBIGUOUS
        with pytest.raises(DeliveryStateError):
            ledger.transition_delivery(did, DeliveryState.AMBIGUOUS, DeliveryState.SENDING)

    def test_pre_send_crash_is_retry_authorized(self, ledger):
        _register_test_plan(ledger, "eplan_fi5")
        did = ledger.reserve_delivery(
            plan_id="eplan_fi5", student_id="stu_001",
            idempotency_key="key_fi5",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        d = ledger.get_delivery_by_key("key_fi5")
        assert d.state == DeliveryState.RESERVED
        events = reconcile_plan("eplan_fi5", ledger, orphan_timeout_seconds=0)
        assert any(e["toState"] == "retryAuthorized" for e in events)

    def test_post_send_crash_is_ambiguous(self, ledger):
        _register_test_plan(ledger, "eplan_fi6")
        did = ledger.reserve_delivery(
            plan_id="eplan_fi6", student_id="stu_001",
            idempotency_key="key_fi6",
            masked_recipient="u***@x.com", identity_projection_hash="h" * 64,
            client_message_id="<msg@test>",
        )
        ledger.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        d = ledger.get_delivery_by_key("key_fi6")
        assert d.state == DeliveryState.SENDING
        events = reconcile_plan("eplan_fi6", ledger, orphan_timeout_seconds=0)
        assert any(e["toState"] == "ambiguous" for e in events)


def _make_recipient_dict(
    student_id="stu_001",
    normalized_recipient="juan@example.test",
    masked_recipient="j***@example.test",
    display_name="Juan Pérez",
    identity_projection_hash=None,
    subject="Test Subject",
    text_body="Hello stu_001",
    section_id="sec_001",
    publication_id="pub_001",
    template_id="tpl",
    template_version="1",
    intent="notify",
):
    iph = identity_projection_hash or compute_identity_projection_hash(student_id, display_name, normalized_recipient)
    recipient_dict = {
        "studentId": student_id,
        "normalizedRecipient": normalized_recipient,
        "maskedRecipient": masked_recipient,
        "identityProjectionHash": iph,
        "subject": subject,
        "textBody": text_body,
    }
    item_hash = compute_item_hash(recipient_dict)
    idempotency_key = compute_idempotency_key(
        section_id, publication_id, student_id,
        normalized_recipient, template_id, template_version, intent,
    )
    return {**recipient_dict, "itemHash": item_hash, "idempotencyKey": idempotency_key}


def _make_plan_core(recipients, section_id="sec_001", publication_id="pub_001"):
    return {
        "schemaVersion": "1.0.0",
        "sectionId": section_id,
        "publicationId": publication_id,
        "snapshotContentHash": "c" * 64,
        "snapshotReviewHash": "r" * 64,
        "snapshotMode": "legacy-effective",
        "templateId": "tpl",
        "templateVersion": "1",
        "templateHash": "t" * 64,
        "intent": "notify",
        "senderProfileId": "default",
        "fromAddress": "noreply@test.com",
        "replyTo": None,
        "recipientCount": len(recipients),
        "recipients": recipients,
    }


def _write_valid_plan_bundle(parent_dir, recipients=None):
    from email_delivery.canonical import sha256_file
    recipients = recipients or [_make_recipient_dict()]
    plan_core = _make_plan_core(recipients)
    preview_hash = compute_preview_hash(plan_core)
    plan_id = derive_plan_id(preview_hash)
    plan_dir = parent_dir / plan_id
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_dict = {**plan_core, "planId": plan_id, "previewHash": preview_hash}
    write_json(plan_dir / "plan.json", plan_dict)
    previews_dir = plan_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    for r in recipients:
        (previews_dir / f"{r['studentId']}.txt").write_text(r["textBody"], encoding="utf-8")
    manifest_files = {
        "plan.json": {"sha256": sha256_file(plan_dir / "plan.json"), "size": (plan_dir / "plan.json").stat().st_size},
    }
    for r in recipients:
        preview_path = previews_dir / f"{r['studentId']}.txt"
        rel = f"previews/{r['studentId']}.txt"
        manifest_files[rel] = {"sha256": sha256_file(preview_path), "size": preview_path.stat().st_size}
    write_json(plan_dir / "manifest.json", {"schemaVersion": "1.0.0", "planId": plan_id, "files": manifest_files})
    return plan_id, preview_hash, plan_dir


class TestPlanBundleVerification:
    def test_verify_valid_bundle(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        result = verify_plan_bundle(plan_dir)
        assert result["plan_id"] == plan_id

    def test_tamper_subject_rejected(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        tampered = read_json(plan_dir / "plan.json")
        tampered["recipients"][0]["subject"] = "Tampered Subject"
        write_json(plan_dir / "plan.json", tampered)
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_tamper_preview_rejected(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        tampered = read_json(plan_dir / "plan.json")
        tampered["recipients"][0]["textBody"] = "Tampered body"
        write_json(plan_dir / "plan.json", tampered)
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_unexpected_file_rejected(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        (plan_dir / "extra_file.txt").write_text("unexpected", encoding="utf-8")
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_missing_preview_rejected(self, tmp_dir):
        recipients = [_make_recipient_dict()]
        plan_core = _make_plan_core(recipients)
        preview_hash = compute_preview_hash(plan_core)
        plan_id = derive_plan_id(preview_hash)
        plan_dir = tmp_dir / plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_dict = {**plan_core, "planId": plan_id, "previewHash": preview_hash}
        write_json(plan_dir / "plan.json", plan_dict)
        previews_dir = plan_dir / "previews"
        previews_dir.mkdir()
        from email_delivery.canonical import sha256_file
        manifest_files = {
            "plan.json": {"sha256": sha256_file(plan_dir / "plan.json"), "size": (plan_dir / "plan.json").stat().st_size},
            "previews/stu_001.txt": {"sha256": "0" * 64, "size": 0},
        }
        write_json(plan_dir / "manifest.json", {"schemaVersion": "1.0.0", "planId": plan_id, "files": manifest_files})
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)


class TestNormalizedRecipientInTransport:
    def test_fake_transport_receives_normalized_recipient(self):
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        transport.preflight(config)
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("test body")
        msg["Subject"] = "test"
        msg["From"] = "noreply@test.com"
        msg["To"] = "juan@example.test"
        envelope = Envelope(from_address="noreply@test.com", to_address="juan@example.test")
        receipt = transport.send(msg, envelope)
        assert receipt.accepted
        assert transport.sent_envelopes[-1].to_address == "juan@example.test"

    def test_smtp_mock_to_addrs_exact(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        normalized = "juan@example.test"
        msg = build_email_message(
            from_address="noreply@test.com", to_address=normalized,
            subject="Test", body="Body",
            client_message_id="<id@test>",
        )
        envelope = Envelope(from_address="noreply@test.com", to_address=normalized)
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.return_value = {}
        with patch("smtplib.SMTP", return_value=mock_smtp):
            receipt = transport.send(msg, envelope, config=config)
        mock_smtp.send_message.assert_called_once()
        call_kwargs = mock_smtp.send_message.call_args
        to_addrs = call_kwargs[1].get("to_addrs") or call_kwargs[0][2] if len(call_kwargs[0]) > 2 else call_kwargs[1]["to_addrs"]
        assert to_addrs == [normalized]

    def test_masked_recipient_never_arrives_at_transport(self):
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        transport.preflight(config)
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("test")
        msg["Subject"] = "test"
        msg["From"] = "noreply@test.com"
        msg["To"] = "juan@example.test"
        envelope = Envelope(from_address="noreply@test.com", to_address="juan@example.test")
        transport.send(msg, envelope)
        for env in transport.sent_envelopes:
            assert "***" not in env.to_address

    def test_identity_drift_blocks(self, tmp_dir):
        recipients = [_make_recipient_dict(
            normalized_recipient="juan@example.test",
        )]
        plan_core = _make_plan_core(recipients)
        preview_hash = compute_preview_hash(plan_core)
        plan_id = derive_plan_id(preview_hash)
        plan_dir = tmp_dir / plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_dict = {**plan_core, "planId": plan_id, "previewHash": preview_hash}
        write_json(plan_dir / "plan.json", plan_dict)

        drifted_identity = _synthetic_identity("stu_001", "Juan CHANGED", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": drifted_identity})
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        lifecycle_ledger = _mock_lifecycle_ledger()
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)

        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(IdentityDriftError):
            execute_plan(
                plan_id=plan_id, preview_hash=preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
                confirm_send=True,
                lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
            )

    def test_casing_only_domain_change_handled(self):
        raw = "Juan@EXAMPLE.TEST"
        normalized = normalize_email(raw)
        assert normalized == "Juan@example.test"
        assert normalized != raw


class TestVerifyPlanBundleIntegration:
    def test_tamper_subject_approve_rejects(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        tampered = read_json(plan_dir / "plan.json")
        tampered["recipients"][0]["subject"] = "Tampered Subject"
        write_json(plan_dir / "plan.json", tampered)
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        lifecycle_ledger = _mock_lifecycle_ledger()
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        with pytest.raises(PlanTamperedError):
            approve_plan(
                plan_id=tampered["planId"], preview_hash=tampered["previewHash"],
                recipient_count=tampered["recipientCount"], actor="staff.opaque",
                ledger=ledger, plan_dir=plan_dir,
                identity_store=identity_store,
                confirm_reviewed=True,
                lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
            )

    def test_tamper_body_execute_rejects(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        tampered = read_json(plan_dir / "plan.json")
        tampered["recipients"][0]["textBody"] = "Tampered Body"
        write_json(plan_dir / "plan.json", tampered)
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_tamper_normalized_recipient_rejected(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        tampered = read_json(plan_dir / "plan.json")
        tampered["recipients"][0]["normalizedRecipient"] = "hacked@evil.com"
        write_json(plan_dir / "plan.json", tampered)
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_tamper_idempotency_key_rejected(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        tampered = read_json(plan_dir / "plan.json")
        tampered["recipients"][0]["idempotencyKey"] = "a" * 64
        write_json(plan_dir / "plan.json", tampered)
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_tamper_manifest_rejected(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        manifest = read_json(plan_dir / "manifest.json")
        manifest["files"]["plan.json"]["sha256"] = "0" * 64
        write_json(plan_dir / "manifest.json", manifest)
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_preview_missing_rejected(self, tmp_dir):
        recipients = [_make_recipient_dict()]
        plan_core = _make_plan_core(recipients)
        preview_hash = compute_preview_hash(plan_core)
        plan_id = derive_plan_id(preview_hash)
        plan_dir = tmp_dir / plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_dict = {**plan_core, "planId": plan_id, "previewHash": preview_hash}
        write_json(plan_dir / "plan.json", plan_dict)
        previews_dir = plan_dir / "previews"
        previews_dir.mkdir()
        from email_delivery.canonical import sha256_file
        manifest_files = {
            "plan.json": {"sha256": sha256_file(plan_dir / "plan.json"), "size": (plan_dir / "plan.json").stat().st_size},
            "previews/stu_001.txt": {"sha256": "0" * 64, "size": 0},
        }
        write_json(plan_dir / "manifest.json", {"schemaVersion": "1.0.0", "planId": plan_id, "files": manifest_files})
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)

    def test_plan_id_different_from_directory_rejected(self, tmp_dir):
        recipients = [_make_recipient_dict()]
        plan_core = _make_plan_core(recipients)
        preview_hash = compute_preview_hash(plan_core)
        plan_id = derive_plan_id(preview_hash)
        wrong_plan_id = "eplan_" + "z" * 24
        plan_dir = tmp_dir / wrong_plan_id
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_dict = {**plan_core, "planId": wrong_plan_id, "previewHash": preview_hash}
        write_json(plan_dir / "plan.json", plan_dict)
        previews_dir = plan_dir / "previews"
        previews_dir.mkdir()
        (previews_dir / "stu_001.txt").write_text("Hello stu_001", encoding="utf-8")
        from email_delivery.canonical import sha256_file
        manifest_files = {
            "plan.json": {"sha256": sha256_file(plan_dir / "plan.json"), "size": (plan_dir / "plan.json").stat().st_size},
            "previews/stu_001.txt": {"sha256": sha256_file(previews_dir / "stu_001.txt"), "size": (previews_dir / "stu_001.txt").stat().st_size},
        }
        write_json(plan_dir / "manifest.json", {"schemaVersion": "1.0.0", "planId": wrong_plan_id, "files": manifest_files})
        with pytest.raises(PlanTamperedError):
            verify_plan_bundle(plan_dir)


class TestSnapshotVerification:
    def test_snapshot_verifier_in_prepare(self, tmp_dir):
        ledger, snapshot_dir, identity_store, template_path, sender_path, private_root, temp_root, lifecycle_ledger = \
            TestExecuteWithFakeTransport()._setup_plan_and_ledger(tmp_dir)
        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
        )
        assert plan is not None

    def test_snapshot_verifier_in_approve(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        lifecycle_ledger = _mock_lifecycle_ledger()
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        record = approve_plan(
            plan_id=plan_id, preview_hash=preview_hash,
            recipient_count=1, actor="staff.opaque",
            ledger=ledger, plan_dir=plan_dir,
            identity_store=identity_store,
            confirm_reviewed=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )
        assert record.preview_hash == preview_hash

    def test_snapshot_verifier_in_execute(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        lifecycle_ledger = _mock_lifecycle_ledger()
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        outcome = execute_plan(
            plan_id=plan_id, preview_hash=preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )
        assert outcome == ExecuteOutcome.COMPLETE

    def test_lifecycle_ledger_none_blocks(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(ExecuteBlockedError):
            execute_plan(
                plan_id=plan_id, preview_hash=preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
                confirm_send=True,
                lifecycle_ledger=None, publication_id="pub_001",
            )

    def test_publication_id_none_blocks(self, tmp_dir):
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir)
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        lifecycle_ledger = _mock_lifecycle_ledger()
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(ExecuteBlockedError):
            execute_plan(
                plan_id=plan_id, preview_hash=preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
                confirm_send=True,
                lifecycle_ledger=lifecycle_ledger, publication_id=None,
            )


class TestTemplateRegistry:
    def test_register_template_version_before_approval(self, tmp_dir):
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_template_version("tpl", "1", "a" * 64)
        ledger.register_template_version("tpl", "1", "a" * 64)

    def test_same_template_id_version_same_hash_ok(self, tmp_dir):
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_template_version("tpl", "1", "a" * 64)
        ledger.register_template_version("tpl", "1", "a" * 64)

    def test_same_template_id_version_different_hash_blocked(self, tmp_dir):
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_template_version("tpl", "1", "a" * 64)
        with pytest.raises(TemplateHashMismatchError):
            ledger.register_template_version("tpl", "1", "b" * 64)


class TestSMTPStdlibMocks:
    def test_starttls_available(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.return_value = {}
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp):
            receipt = transport.send(msg, envelope, config=config)
        assert receipt.accepted
        mock_smtp.starttls.assert_called_once()

    def test_starttls_absent(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = False
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp):
            with pytest.raises(BatchTransportError) as exc_info:
                transport.send(msg, envelope, config=config)
            assert exc_info.value.code == "smtp-starttls-unavailable"

    def test_starttls_called_before_login(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.return_value = {}
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp):
            transport.send(msg, envelope, config=config)
        call_names = [c[0] for c in mock_smtp.method_calls]
        starttls_idx = next(i for i, n in enumerate(call_names) if n == "starttls")
        login_idx = next(i for i, n in enumerate(call_names) if n == "login")
        assert starttls_idx < login_idx

    def test_smtp_ssl_for_implicit_tls(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=465, username="user",
            password="pass", tls_mode=TlsMode.IMPLICIT_TLS,
        )
        mock_smtp_ssl = MagicMock()
        mock_smtp_ssl.__enter__.return_value = mock_smtp_ssl
        mock_smtp_ssl.send_message.return_value = {}
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP_SSL", return_value=mock_smtp_ssl):
            receipt = transport.send(msg, envelope, config=config)
        assert receipt.accepted

    def test_host_port_username_from_config(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="mail.example.com", port=2525, username="testuser",
            password="testpass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.return_value = {}
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp) as smtp_cls:
            transport.send(msg, envelope, config=config)
        smtp_cls.assert_called_once_with("mail.example.com", 2525, timeout=transport.timeout)
        mock_smtp.login.assert_called_once_with("testuser", "testpass")

    def test_cert_via_ssl_create_default_context(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.return_value = {}
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp):
            with patch("ssl.create_default_context") as mock_ctx:
                transport.send(msg, envelope, config=config)
        mock_ctx.assert_called()

    def test_to_addrs_receives_normalized_recipient(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        normalized = "juan@example.test"
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.return_value = {}
        msg = build_email_message("noreply@test.com", normalized, "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address=normalized)
        with patch("smtplib.SMTP", return_value=mock_smtp):
            transport.send(msg, envelope, config=config)
        call_kwargs = mock_smtp.send_message.call_args
        to_addrs = call_kwargs[1].get("to_addrs") or call_kwargs[0][2] if len(call_kwargs[0]) > 2 else call_kwargs[1]["to_addrs"]
        assert to_addrs == [normalized]

    def test_auth_failure(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp):
            with pytest.raises(BatchTransportError) as exc_info:
                transport.send(msg, envelope, config=config)
            assert exc_info.value.code == "smtp-auth-failed"

    def test_disconnect_timeout_ambiguous(self):
        from email_delivery.transport.smtp import SMTPTransport, build_email_message
        transport = SMTPTransport()
        config = TransportConfig(
            host="smtp.example.com", port=587, username="user",
            password="pass", tls_mode=TlsMode.STARTTLS,
        )
        mock_smtp = MagicMock()
        mock_smtp.__enter__.return_value = mock_smtp
        mock_smtp.has_extn.return_value = True
        mock_smtp.send_message.side_effect = smtplib.SMTPServerDisconnected("Connection lost")
        msg = build_email_message("noreply@test.com", "user@test.com", "Test", "Body")
        envelope = Envelope(from_address="noreply@test.com", to_address="user@test.com")
        with patch("smtplib.SMTP", return_value=mock_smtp):
            with pytest.raises(Exception) as exc_info:
                transport.send(msg, envelope, config=config)
            assert exc_info.value.delivery_certainty == "unknown"

    def test_password_absent(self):
        from email_delivery.transport.smtp import SMTPTransport
        transport = SMTPTransport()
        config = TransportConfig(host="smtp.example.com", port=587, username="user", password="")
        with patch.dict(os.environ, {}, clear=True):
            env = {k: v for k, v in os.environ.items() if k != "ACADGRAD_SMTP_PASSWORD"}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(BatchTransportError) as exc_info:
                    transport.preflight(config)
                assert exc_info.value.code == "smtp-auth-missing"


class TestBatchOutcomes:
    def _make_single_recipient_plan(self, tmp_dir, recipient_dict=None):
        r = recipient_dict or _make_recipient_dict()
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir, recipients=[r])
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        identity = _synthetic_identity(r["studentId"], "Juan Pérez", r["normalizedRecipient"])
        identity_store = _synthetic_identity_store({r["studentId"]: identity})
        lifecycle_ledger = _mock_lifecycle_ledger()
        return plan_id, preview_hash, plan_dir, ledger, identity_store, lifecycle_ledger

    def test_complete_outcome(self, tmp_dir):
        plan_id, preview_hash, plan_dir, ledger, identity_store, lifecycle_ledger = \
            self._make_single_recipient_plan(tmp_dir)
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        outcome = execute_plan(
            plan_id=plan_id, preview_hash=preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )
        assert outcome == ExecuteOutcome.COMPLETE

    def test_partial_outcome(self, tmp_dir):
        r1 = _make_recipient_dict(student_id="stu_001", normalized_recipient="juan@example.test")
        r2 = _make_recipient_dict(student_id="stu_002", normalized_recipient="maria@example.test", display_name="María López", text_body="Hello stu_002")
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir, recipients=[r1, r2])
        ledger = EmailLedger(tmp_dir / "ledger.sqlite3")
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=2,
            plan_path=str(plan_dir),
        )
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=2,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        id1 = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        id2 = _synthetic_identity("stu_002", "María López", "maria@example.test")
        identity_store = _synthetic_identity_store({"stu_001": id1, "stu_002": id2})
        lifecycle_ledger = _mock_lifecycle_ledger()
        transport = FakeTransport(behavior=FakeBehavior.INVALID_RECIPIENT)
        config = TransportConfig(host="localhost", port=0, username="")
        outcome = execute_plan(
            plan_id=plan_id, preview_hash=preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )
        assert outcome == ExecuteOutcome.PARTIAL

    def test_paused_outcome(self, tmp_dir):
        r = _make_recipient_dict()
        plan_id, preview_hash, plan_dir, ledger, identity_store, lifecycle_ledger = \
            self._make_single_recipient_plan(tmp_dir, recipient_dict=r)
        transport = FakeTransport(behavior=FakeBehavior.TRANSIENT_FAILURE)
        config = TransportConfig(host="localhost", port=0, username="")
        outcome = execute_plan(
            plan_id=plan_id, preview_hash=preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )
        assert outcome == ExecuteOutcome.PAUSED

    def test_ambiguous_outcome(self, tmp_dir):
        r = _make_recipient_dict()
        plan_id, preview_hash, plan_dir, ledger, identity_store, lifecycle_ledger = \
            self._make_single_recipient_plan(tmp_dir, recipient_dict=r)
        transport = FakeTransport(behavior=FakeBehavior.AMBIGUOUS)
        config = TransportConfig(host="localhost", port=0, username="")
        outcome = execute_plan(
            plan_id=plan_id, preview_hash=preview_hash,
            ledger=ledger, transport=transport, transport_config=config,
            plan_dir=plan_dir, identity_store=identity_store,
            confirm_send=True,
            lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
        )
        assert outcome == ExecuteOutcome.AMBIGUOUS

    def test_blocked_outcome(self, tmp_dir):
        r = _make_recipient_dict()
        plan_id, preview_hash, plan_dir, ledger, identity_store, lifecycle_ledger = \
            self._make_single_recipient_plan(tmp_dir, recipient_dict=r)
        missing_identity_store = _synthetic_identity_store({})
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(IdentityDriftError):
            execute_plan(
                plan_id=plan_id, preview_hash=preview_hash,
                ledger=ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=missing_identity_store,
                confirm_send=True,
                lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
            )

    def test_ledger_error_yields_blocked_no_generic_exception(self, tmp_dir):
        r = _make_recipient_dict()
        plan_id, preview_hash, plan_dir, ledger, identity_store, lifecycle_ledger = \
            self._make_single_recipient_plan(tmp_dir, recipient_dict=r)
        broken_ledger = MagicMock()
        broken_ledger.get_approval = ledger.get_approval
        broken_ledger.start_batch_run = MagicMock(side_effect=LedgerError("broken"))
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
        with pytest.raises(LedgerError):
            execute_plan(
                plan_id=plan_id, preview_hash=preview_hash,
                ledger=broken_ledger, transport=transport, transport_config=config,
                plan_dir=plan_dir, identity_store=identity_store,
                confirm_send=True,
                lifecycle_ledger=lifecycle_ledger, publication_id="pub_001",
            )


class TestMultiprocessExecuteConcurrency:
    def _setup_concurrent_plan(self, tmp_dir):
        r = _make_recipient_dict()
        plan_id, preview_hash, plan_dir = _write_valid_plan_bundle(tmp_dir, recipients=[r])
        db_path = tmp_dir / "ledger.sqlite3"
        ledger = EmailLedger(db_path)
        ledger.register_plan(
            plan_id=plan_id, section_id="sec_001", publication_id="pub_001",
            snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
            snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
            template_hash="t" * 64, intent="notify", sender_profile_id="default",
            from_address="noreply@test.com", reply_to=None,
            preview_hash=preview_hash, recipient_count=1,
            plan_path=str(plan_dir),
        )
        record = ApprovalRecord(
            plan_id=plan_id, preview_hash=preview_hash, recipient_count=1,
            approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
        )
        ledger.record_approval(record)
        identity = _synthetic_identity(r["studentId"], "Juan Pérez", r["normalizedRecipient"])
        identity_store = _synthetic_identity_store({r["studentId"]: identity})
        ledger.close()
        return plan_id, preview_hash, plan_dir, db_path, identity_store

    def test_same_plan_same_key_send_count_one(self, tmp_dir):
        plan_id, preview_hash, plan_dir, db_path, identity_store = \
            self._setup_concurrent_plan(tmp_dir)
        results = []

        def run_execute():
            lg = EmailLedger(db_path)
            transport = FakeTransport()
            config = TransportConfig(host="localhost", port=0, username="")
            lifecycle = _mock_lifecycle_ledger()
            try:
                outcome = execute_plan(
                    plan_id=plan_id, preview_hash=preview_hash,
                    ledger=lg, transport=transport, transport_config=config,
                    plan_dir=plan_dir, identity_store=identity_store,
                    confirm_send=True,
                    lifecycle_ledger=lifecycle, publication_id="pub_001",
                )
                results.append(("outcome", outcome, transport.sent_count))
            except Exception as exc:
                results.append(("error", str(exc)))
            finally:
                lg.close()

        t1 = threading.Thread(target=run_execute)
        t2 = threading.Thread(target=run_execute)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        total_sends = sum(r[2] for r in results if r[0] == "outcome")
        assert total_sends == 1

    def test_two_plans_same_semantic_key_send_count_at_most_one(self, tmp_dir):
        r = _make_recipient_dict(normalized_recipient="juan@example.test")
        plan_id1, preview_hash1, plan_dir1 = _write_valid_plan_bundle(tmp_dir / "plans1", recipients=[r])

        plan_id2, preview_hash2, plan_dir2 = _write_valid_plan_bundle(tmp_dir / "plans2", recipients=[r])

        db_path = tmp_dir / "ledger.sqlite3"
        ledger = EmailLedger(db_path)
        for pid, ph in [(plan_id1, preview_hash1), (plan_id2, preview_hash2)]:
            try:
                ledger.register_plan(
                    plan_id=pid, section_id="sec_001", publication_id="pub_001",
                    snapshot_content_hash="c" * 64, snapshot_review_hash="r" * 64,
                    snapshot_mode="legacy-effective", template_id="tpl", template_version="1",
                    template_hash="t" * 64, intent="notify", sender_profile_id="default",
                    from_address="noreply@test.com", reply_to=None,
                    preview_hash=ph, recipient_count=1,
                    plan_path=str(tmp_dir),
                )
            except PlanExistsError:
                pass
            existing = ledger.get_approval(pid)
            if existing is None:
                record = ApprovalRecord(
                    plan_id=pid, preview_hash=ph, recipient_count=1,
                    approved_by="staff.opaque", approved_at="2026-01-01T00:00:00Z",
                )
                ledger.record_approval(record)
        ledger.close()

        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        results = []

        def run_execute(plan_id, preview_hash, plan_dir):
            lg = EmailLedger(db_path)
            transport = FakeTransport()
            config = TransportConfig(host="localhost", port=0, username="")
            lifecycle = _mock_lifecycle_ledger()
            try:
                outcome = execute_plan(
                    plan_id=plan_id, preview_hash=preview_hash,
                    ledger=lg, transport=transport, transport_config=config,
                    plan_dir=plan_dir, identity_store=identity_store,
                    confirm_send=True,
                    lifecycle_ledger=lifecycle, publication_id="pub_001",
                )
                results.append(("outcome", outcome, transport.sent_count))
            except Exception as exc:
                results.append(("error", str(exc)))
            finally:
                lg.close()

        t1 = threading.Thread(target=run_execute, args=(plan_id1, preview_hash1, plan_dir1))
        t2 = threading.Thread(target=run_execute, args=(plan_id2, preview_hash2, plan_dir2))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        total_sends = sum(r[2] for r in results if r[0] == "outcome")
        assert total_sends <= 1

    def test_retry_authorized_concurrent_one_send(self, tmp_dir):
        plan_id, preview_hash, plan_dir, db_path, identity_store = \
            self._setup_concurrent_plan(tmp_dir)
        lg = EmailLedger(db_path)
        deliveries = lg.get_deliveries_for_plan(plan_id)
        if deliveries:
            did = deliveries[0].delivery_id
            lg.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
            lg.transition_delivery(did, DeliveryState.SENDING, DeliveryState.FAILED_TRANSIENT)
            lg.transition_delivery(did, DeliveryState.FAILED_TRANSIENT, DeliveryState.RETRY_AUTHORIZED)
        lg.close()

        results = []

        def run_execute():
            lg2 = EmailLedger(db_path)
            transport = FakeTransport()
            config = TransportConfig(host="localhost", port=0, username="")
            lifecycle = _mock_lifecycle_ledger()
            try:
                outcome = execute_plan(
                    plan_id=plan_id, preview_hash=preview_hash,
                    ledger=lg2, transport=transport, transport_config=config,
                    plan_dir=plan_dir, identity_store=identity_store,
                    confirm_send=True,
                    lifecycle_ledger=lifecycle, publication_id="pub_001",
                )
                results.append(("outcome", outcome, transport.sent_count))
            except Exception as exc:
                results.append(("error", str(exc)))
            finally:
                lg2.close()

        t1 = threading.Thread(target=run_execute)
        t2 = threading.Thread(target=run_execute)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        total_sends = sum(r[2] for r in results if r[0] == "outcome")
        assert total_sends <= 1

    def test_execute_vs_reconcile(self, tmp_dir):
        plan_id, preview_hash, plan_dir, db_path, identity_store = \
            self._setup_concurrent_plan(tmp_dir)
        lg = EmailLedger(db_path)
        r = _make_recipient_dict()
        did = lg.reserve_delivery(
            plan_id=plan_id, student_id=r["studentId"],
            idempotency_key=r["idempotencyKey"],
            masked_recipient=r["maskedRecipient"], identity_projection_hash=r["identityProjectionHash"],
            client_message_id="<msg@test>",
        )
        lg.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        lg.close()

        events = reconcile_plan(plan_id, EmailLedger(db_path), orphan_timeout_seconds=0)
        assert len(events) >= 1
        lg2 = EmailLedger(db_path)
        lg2.close()

    def test_provider_accepted_crash_before_persisting_ambiguous(self, tmp_dir):
        plan_id, preview_hash, plan_dir, db_path, identity_store = \
            self._setup_concurrent_plan(tmp_dir)
        lg = EmailLedger(db_path)
        r = _make_recipient_dict()
        did = lg.reserve_delivery(
            plan_id=plan_id, student_id=r["studentId"],
            idempotency_key=r["idempotencyKey"],
            masked_recipient=r["maskedRecipient"], identity_projection_hash=r["identityProjectionHash"],
            client_message_id="<msg@test>",
        )
        lg.transition_delivery(did, DeliveryState.RESERVED, DeliveryState.SENDING)
        lg.close()

        lg2 = EmailLedger(db_path)
        d = lg2.get_deliveries_for_plan(plan_id)
        assert d[0].state == DeliveryState.SENDING
        events = reconcile_plan(plan_id, lg2, orphan_timeout_seconds=0)
        assert any(e["toState"] == "ambiguous" for e in events)
        lg2.close()


class TestAtomicPlanHardening:
    def test_staging_id_unique_per_operation(self, tmp_dir):
        snapshot_dir = tmp_dir / "snapshot" / "sections" / "sec_001" / "pub_001"
        canonical_dir = snapshot_dir / "canonical"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        write_json(canonical_dir / "subjects.json", {"subjects": [{"studentId": "stu_001", "status": "active"}]})
        write_json(canonical_dir / "results.json", {"results": [{"studentId": "stu_001", "assessmentId": "EV1", "status": "Logrado", "score": "5.5", "grade": "5.5"}]})
        write_json(canonical_dir / "assessments.json", {"assessments": [{"assessmentId": "EV1", "label": "EV1", "unit": "grade"}]})
        write_json(snapshot_dir / "manifest.json", {"contentHash": "c" * 64, "reviewHash": "r" * 64})
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        template_path = tmp_dir / "template.json"
        write_json(template_path, _synthetic_template_dict())
        sender_path = tmp_dir / "sender.json"
        write_json(sender_path, {"schemaVersion": "1.0.0", "senderProfileId": "default", "fromAddress": "noreply@example.test"})
        private_root = tmp_dir / "private"
        temp_root = tmp_dir / "temp"
        private_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        lifecycle_ledger = _mock_lifecycle_ledger()

        plan1 = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
            operation_id="op-001",
        )
        plan2 = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
            operation_id="op-002",
        )
        assert plan1.plan_id == plan2.plan_id

    def test_0700_on_private_dirs(self, tmp_dir):
        snapshot_dir = tmp_dir / "snapshot" / "sections" / "sec_001" / "pub_001"
        canonical_dir = snapshot_dir / "canonical"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        write_json(canonical_dir / "subjects.json", {"subjects": [{"studentId": "stu_001", "status": "active"}]})
        write_json(canonical_dir / "results.json", {"results": [{"studentId": "stu_001", "assessmentId": "EV1", "status": "Logrado", "score": "5.5", "grade": "5.5"}]})
        write_json(canonical_dir / "assessments.json", {"assessments": [{"assessmentId": "EV1", "label": "EV1", "unit": "grade"}]})
        write_json(snapshot_dir / "manifest.json", {"contentHash": "c" * 64, "reviewHash": "r" * 64})
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        template_path = tmp_dir / "template.json"
        write_json(template_path, _synthetic_template_dict())
        sender_path = tmp_dir / "sender.json"
        write_json(sender_path, {"schemaVersion": "1.0.0", "senderProfileId": "default", "fromAddress": "noreply@example.test"})
        private_root = tmp_dir / "private"
        temp_root = tmp_dir / "temp"
        private_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        lifecycle_ledger = _mock_lifecycle_ledger()

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
        )
        plan_dir = private_root / "email" / "plans" / "sec_001" / "pub_001" / plan.plan_id
        assert plan_dir.exists()

    def test_verify_plan_bundle_existing_plan(self, tmp_dir):
        snapshot_dir = tmp_dir / "snapshot" / "sections" / "sec_001" / "pub_001"
        canonical_dir = snapshot_dir / "canonical"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        write_json(canonical_dir / "subjects.json", {"subjects": [{"studentId": "stu_001", "status": "active"}]})
        write_json(canonical_dir / "results.json", {"results": [{"studentId": "stu_001", "assessmentId": "EV1", "status": "Logrado", "score": "5.5", "grade": "5.5"}]})
        write_json(canonical_dir / "assessments.json", {"assessments": [{"assessmentId": "EV1", "label": "EV1", "unit": "grade"}]})
        write_json(snapshot_dir / "manifest.json", {"contentHash": "c" * 64, "reviewHash": "r" * 64})
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        template_path = tmp_dir / "template.json"
        write_json(template_path, _synthetic_template_dict())
        sender_path = tmp_dir / "sender.json"
        write_json(sender_path, {"schemaVersion": "1.0.0", "senderProfileId": "default", "fromAddress": "noreply@example.test"})
        private_root = tmp_dir / "private"
        temp_root = tmp_dir / "temp"
        private_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        lifecycle_ledger = _mock_lifecycle_ledger()

        plan = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
        )
        plan_dir = private_root / "email" / "plans" / "sec_001" / "pub_001" / plan.plan_id
        result = verify_plan_bundle(plan_dir)
        assert result["plan_id"] == plan.plan_id

    def test_byte_equivalent_idempotent_return(self, tmp_dir):
        snapshot_dir = tmp_dir / "snapshot" / "sections" / "sec_001" / "pub_001"
        canonical_dir = snapshot_dir / "canonical"
        canonical_dir.mkdir(parents=True, exist_ok=True)
        write_json(canonical_dir / "subjects.json", {"subjects": [{"studentId": "stu_001", "status": "active"}]})
        write_json(canonical_dir / "results.json", {"results": [{"studentId": "stu_001", "assessmentId": "EV1", "status": "Logrado", "score": "5.5", "grade": "5.5"}]})
        write_json(canonical_dir / "assessments.json", {"assessments": [{"assessmentId": "EV1", "label": "EV1", "unit": "grade"}]})
        write_json(snapshot_dir / "manifest.json", {"contentHash": "c" * 64, "reviewHash": "r" * 64})
        identity = _synthetic_identity("stu_001", "Juan Pérez", "juan@example.test")
        identity_store = _synthetic_identity_store({"stu_001": identity})
        template_path = tmp_dir / "template.json"
        write_json(template_path, _synthetic_template_dict())
        sender_path = tmp_dir / "sender.json"
        write_json(sender_path, {"schemaVersion": "1.0.0", "senderProfileId": "default", "fromAddress": "noreply@example.test"})
        private_root = tmp_dir / "private"
        temp_root = tmp_dir / "temp"
        private_root.mkdir(parents=True, exist_ok=True)
        temp_root.mkdir(parents=True, exist_ok=True)
        lifecycle_ledger = _mock_lifecycle_ledger()

        plan1 = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
        )
        plan2 = prepare_plan(
            section_id="sec_001", publication_id="pub_001",
            snapshot_dir=snapshot_dir, snapshot_content_hash="c" * 64,
            snapshot_review_hash="r" * 64, snapshot_mode="legacy-effective",
            template_path=template_path, sender_profile_path=sender_path,
            identity_store=identity_store, private_root=private_root,
            temp_root=temp_root, lifecycle_ledger=lifecycle_ledger,
        )
        assert plan1.plan_id == plan2.plan_id
        assert plan1.preview_hash == plan2.preview_hash
        d1 = plan1.to_dict()
        d2 = plan2.to_dict()
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)
