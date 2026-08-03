"""Idempotent email executor for C3 email delivery.

Execute uses exclusively the approved and verified private plan. It never
re-renders from source, never auto-approves, and never provides a force path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .approval import verify_approval
from .canonical import compute_identity_projection_hash
from .errors import (
    BatchTransportError,
    ExecuteBlockedError,
    ExecuteError,
    IdentityDriftError,
    LedgerError,
    NotApprovedError,
    PlanTamperedError,
    RecipientTransportError,
    SchemaValidationError,
    TemplateHashMismatchError,
)
from .ledger import EmailLedger
from .models import DeliveryState, Envelope, ExecuteOutcome
from .plan import verify_plan_bundle
from .recipients import normalize_email
from .transport.fake import FakeTransport
from .transport.smtp import build_email_message

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})


def execute_plan(
    plan_id: str,
    preview_hash: str,
    ledger: EmailLedger,
    transport,
    transport_config,
    plan_dir: Path,
    identity_store=None,
    lifecycle_ledger=None,
    publication_id: Optional[str] = None,
    actor: str = "system",
    confirm_send: bool = False,
    snapshot_dir: Optional[Path] = None,
    recovery_root: Optional[Path] = None,
) -> ExecuteOutcome:
    if not confirm_send:
        raise ExecuteError("confirm_send is required for execution.")
    if not Path(plan_dir).exists():
        raise ExecuteBlockedError("Plan not found.")
    if identity_store is None:
        raise ExecuteBlockedError("identity_store is required for execution.")
    if lifecycle_ledger is None or publication_id is None:
        raise ExecuteBlockedError(
            "lifecycle_ledger and publication_id are required for execution."
        )
    if snapshot_dir is None:
        raise ExecuteBlockedError("snapshot_dir is required for execution.")

    try:
        verified_plan = verify_plan_bundle(Path(plan_dir))
    except (PlanTamperedError, SchemaValidationError) as exc:
        raise ExecuteBlockedError("Plan bundle verification failed.") from exc

    if verified_plan.plan_id != plan_id:
        raise ExecuteBlockedError("planId mismatch.")
    if verified_plan.preview_hash != preview_hash:
        raise ExecuteBlockedError("previewHash mismatch.")

    plan_dict = verified_plan.plan_dict
    if publication_id != plan_dict["publicationId"]:
        raise ExecuteBlockedError("publicationId does not match plan.")

    from .lifecycle import check_identity_drift, verify_email_source_snapshot

    verified_snapshot = verify_email_source_snapshot(
        snapshot_dir=Path(snapshot_dir),
        section_id=plan_dict["sectionId"],
        publication_id=plan_dict["publicationId"],
        lifecycle_ledger=lifecycle_ledger,
    )
    _assert_snapshot_binding(plan_dict, verified_snapshot)

    try:
        ledger.register_template_version(
            plan_dict["templateId"],
            plan_dict["templateVersion"],
            plan_dict["templateHash"],
        )
    except TemplateHashMismatchError as exc:
        raise ExecuteBlockedError("Template registry mismatch.") from exc

    try:
        verify_approval(plan_id, preview_hash, ledger)
    except NotApprovedError as exc:
        raise ExecuteBlockedError("Plan not approved.") from exc

    drifts = check_identity_drift(plan_dict, identity_store)
    if drifts:
        raise IdentityDriftError("Identity drift detected for one or more subjects.")

    try:
        transport.preflight(transport_config)
    except BatchTransportError as exc:
        raise ExecuteBlockedError(
            f"Transport preflight failed: {exc.sanitized_message}"
        ) from exc

    recipients = plan_dict.get("recipients", [])
    from_address = plan_dict.get("fromAddress", "")
    reply_to = plan_dict.get("replyTo")

    sent_count = 0
    failed_count = 0
    ambiguous_count = 0
    skipped_count = 0
    blocked_count = 0
    paused_count = 0
    snapshot_terminal = False
    batch_operational_error = False

    transport_type = "fake" if isinstance(transport, FakeTransport) else "smtp"
    batch_run_id = ledger.start_batch_run(
        plan_id=plan_id,
        preview_hash=preview_hash,
        transport_type=transport_type,
        total_recipients=len(recipients),
        actor=actor,
    )

    for recipient in recipients:
        student_id = recipient["studentId"]
        idempotency_key = recipient["idempotencyKey"]
        normalized_recipient = recipient["normalizedRecipient"]
        masked_recipient = recipient["maskedRecipient"]
        identity_projection_hash = recipient["identityProjectionHash"]

        identity = identity_store.resolve(student_id)
        if identity is None:
            blocked_count += 1
            continue
        email_raw = (identity.contact or {}).get("email")
        if not email_raw:
            blocked_count += 1
            continue
        try:
            current_normalized = normalize_email(email_raw)
        except Exception:
            blocked_count += 1
            continue
        if current_normalized != normalized_recipient:
            blocked_count += 1
            continue
        current_hash = compute_identity_projection_hash(
            student_id,
            identity.display_name or "",
            current_normalized,
        )
        if current_hash != identity_projection_hash:
            blocked_count += 1
            continue

        state = lifecycle_ledger.current_state(publication_id)
        if state in SNAPSHOT_TERMINAL_STATES:
            snapshot_terminal = True
            blocked_count += 1
            break
        if state != "approved":
            blocked_count += 1
            snapshot_terminal = True
            break

        try:
            action, delivery_id = ledger.acquire_for_execution(
                plan_id=plan_id,
                student_id=student_id,
                idempotency_key=idempotency_key,
                masked_recipient=masked_recipient,
                identity_projection_hash=identity_projection_hash,
                client_message_id=_client_message_id(idempotency_key),
            )
        except LedgerError:
            batch_operational_error = True
            break

        if action == "sent":
            skipped_count += 1
            continue
        if action == "ambiguous":
            ambiguous_count += 1
            continue
        if action == "paused":
            paused_count += 1
            blocked_count += 1
            continue
        if action in {
            "failedPermanent",
            "sending",
            "failedTransient",
            "blocked",
        }:
            blocked_count += 1
            continue
        if action not in {"reserved", "retryAuthorized"}:
            blocked_count += 1
            continue

        try:
            ledger.transition_delivery(
                delivery_id=delivery_id,
                from_state=DeliveryState.RESERVED,
                to_state=DeliveryState.SENDING,
                client_message_id=_client_message_id(idempotency_key),
            )
        except LedgerError:
            batch_operational_error = True
            break

        envelope = Envelope(
            from_address=from_address,
            to_address=normalized_recipient,
            reply_to=reply_to,
        )
        message = build_email_message(
            from_address=from_address,
            to_address=normalized_recipient,
            subject=recipient["subject"],
            body=recipient["textBody"],
            reply_to=reply_to,
            client_message_id=_client_message_id(idempotency_key),
        )

        try:
            receipt = transport.send(message, envelope, transport_config)
            if receipt.accepted:
                try:
                    ledger.transition_delivery(
                        delivery_id=delivery_id,
                        from_state=DeliveryState.SENDING,
                        to_state=DeliveryState.SENT,
                        transport_code=str(receipt.response_code),
                        provider_message_id=receipt.provider_message_id,
                        client_message_id=receipt.client_message_id,
                    )
                    sent_count += 1
                except LedgerError:
                    # Provider accepted the message but durable persistence failed.
                    # Leave the row in sending so reconciliation converts it to
                    # ambiguous. Never retry automatically.
                    ambiguous_count += 1
                    batch_operational_error = True
                    break
            else:
                ledger.transition_delivery(
                    delivery_id=delivery_id,
                    from_state=DeliveryState.SENDING,
                    to_state=DeliveryState.FAILED_PERMANENT,
                    transport_code=str(receipt.response_code),
                    error_class=receipt.response_class,
                    delivery_certainty="notSent",
                )
                failed_count += 1
        except RecipientTransportError as exc:
            if exc.delivery_certainty == "unknown":
                ledger.transition_delivery(
                    delivery_id=delivery_id,
                    from_state=DeliveryState.SENDING,
                    to_state=DeliveryState.AMBIGUOUS,
                    transport_code=exc.code,
                    error_class=type(exc).__name__,
                    delivery_certainty="unknown",
                    client_message_id=_client_message_id(idempotency_key),
                )
                ambiguous_count += 1
            elif exc.retryability == "permanent":
                ledger.transition_delivery(
                    delivery_id=delivery_id,
                    from_state=DeliveryState.SENDING,
                    to_state=DeliveryState.FAILED_PERMANENT,
                    transport_code=exc.code,
                    error_class=type(exc).__name__,
                    delivery_certainty="notSent",
                    client_message_id=_client_message_id(idempotency_key),
                )
                failed_count += 1
            else:
                ledger.transition_delivery(
                    delivery_id=delivery_id,
                    from_state=DeliveryState.SENDING,
                    to_state=DeliveryState.FAILED_TRANSIENT,
                    transport_code=exc.code,
                    error_class=type(exc).__name__,
                    delivery_certainty="notSent",
                    client_message_id=_client_message_id(idempotency_key),
                )
                failed_count += 1
                paused_count += 1
        except BatchTransportError as exc:
            target_state = (
                DeliveryState.FAILED_TRANSIENT
                if exc.retryability == "transient"
                else DeliveryState.FAILED_PERMANENT
            )
            ledger.transition_delivery(
                delivery_id=delivery_id,
                from_state=DeliveryState.SENDING,
                to_state=target_state,
                transport_code=exc.code,
                error_class=type(exc).__name__,
                delivery_certainty=exc.delivery_certainty,
                client_message_id=_client_message_id(idempotency_key),
            )
            if exc.retryability == "transient":
                paused_count += 1
            else:
                failed_count += 1
            batch_operational_error = True
            break
        except LedgerError:
            ambiguous_count += 1
            batch_operational_error = True
            break

    outcome = _derive_outcome(
        sent_count=sent_count,
        failed_count=failed_count,
        ambiguous_count=ambiguous_count,
        blocked_count=blocked_count,
        paused_count=paused_count,
        snapshot_terminal=snapshot_terminal,
        batch_operational_error=batch_operational_error,
    )

    try:
        ledger.complete_batch_run(
            batch_run_id=batch_run_id,
            sent_count=sent_count,
            failed_count=failed_count,
            ambiguous_count=ambiguous_count,
            skipped_count=skipped_count,
            outcome=outcome.value,
            blocked_count=blocked_count,
        )
    except LedgerError as exc:
        _write_recovery_marker(
            recovery_root=(
                Path(recovery_root)
                if recovery_root is not None
                else Path(ledger.db_path).parent / "recovery"
            ),
            batch_run_id=batch_run_id,
            plan_id=plan_id,
            preview_hash=preview_hash,
            sent_count=sent_count,
            failed_count=failed_count,
            ambiguous_count=ambiguous_count,
            skipped_count=skipped_count,
            blocked_count=blocked_count,
            outcome=outcome,
            error=exc,
        )
        raise

    return outcome


def _assert_snapshot_binding(plan_dict: dict, verified_snapshot) -> None:
    checks = (
        (verified_snapshot.content_hash, plan_dict.get("snapshotContentHash")),
        (verified_snapshot.review_hash, plan_dict.get("snapshotReviewHash")),
        (verified_snapshot.section_id, plan_dict.get("sectionId")),
        (verified_snapshot.publication_id, plan_dict.get("publicationId")),
        (verified_snapshot.snapshot_mode, plan_dict.get("snapshotMode")),
    )
    if any(actual != expected for actual, expected in checks):
        raise ExecuteBlockedError(
            "Publication Snapshot no longer matches approved email plan."
        )


def _client_message_id(idempotency_key: str) -> str:
    return f"<{idempotency_key[:24]}@academic-grading>"


def _derive_outcome(
    *,
    sent_count: int,
    failed_count: int,
    ambiguous_count: int,
    blocked_count: int,
    paused_count: int,
    snapshot_terminal: bool,
    batch_operational_error: bool,
) -> ExecuteOutcome:
    if ambiguous_count > 0:
        return ExecuteOutcome.AMBIGUOUS
    if paused_count > 0 and sent_count == 0:
        return ExecuteOutcome.PAUSED
    if snapshot_terminal:
        return ExecuteOutcome.PARTIAL if sent_count > 0 else ExecuteOutcome.BLOCKED
    if batch_operational_error:
        return ExecuteOutcome.PARTIAL if sent_count > 0 else ExecuteOutcome.BLOCKED
    if failed_count > 0:
        return ExecuteOutcome.PARTIAL
    if blocked_count > 0:
        return ExecuteOutcome.PARTIAL if sent_count > 0 else ExecuteOutcome.BLOCKED
    return ExecuteOutcome.COMPLETE


def _write_recovery_marker(
    *,
    recovery_root: Path,
    batch_run_id: int,
    plan_id: str,
    preview_hash: str,
    sent_count: int,
    failed_count: int,
    ambiguous_count: int,
    skipped_count: int,
    blocked_count: int,
    outcome: ExecuteOutcome,
    error: Exception,
) -> None:
    recovery_root.mkdir(parents=True, exist_ok=True)
    try:
        recovery_root.chmod(0o700)
    except OSError:
        pass
    marker = recovery_root / f"batch-{batch_run_id}.json"
    payload = {
        "schemaVersion": "1.0.0",
        "batchRunId": batch_run_id,
        "planId": plan_id,
        "previewHash": preview_hash,
        "sentCount": sent_count,
        "failedCount": failed_count,
        "ambiguousCount": ambiguous_count,
        "skippedCount": skipped_count,
        "blockedCount": blocked_count,
        "outcome": outcome.value,
        "errorClass": type(error).__name__,
        "errorCode": "ledger-complete-failed",
    }
    temp = marker.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    os.replace(temp, marker)
    try:
        marker.chmod(0o600)
    except OSError:
        pass


def inspect_plan(plan_dir: Path):
    return verify_plan_bundle(plan_dir)
