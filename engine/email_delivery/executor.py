"""Idempotent email executor for C3 email delivery.

Execute uses exclusively the approved plan. It never re-renders from source.
No auto-approval. No --force.
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from typing import Optional

from .approval import verify_approval
from .canonical import compute_identity_projection_hash, read_json
from .errors import (
    BatchTransportError,
    ExecuteBlockedError,
    ExecuteError,
    IdentityDriftError,
    LedgerError,
    NotApprovedError,
    RecipientTransportError,
    SnapshotTerminalError,
    TransportError,
)
from .ledger import EmailLedger
from .lifecycle import check_identity_drift, check_snapshot_sendable
from .masking import mask_email
from .models import DeliveryState, EmailPlan, Envelope, ExecuteOutcome, TransportReceipt
from .recipients import normalize_email
from .transport.base import EmailTransport
from .transport.fake import FakeTransport, FakeBehavior
from .transport.smtp import SMTPTransport, build_email_message

SNAPSHOT_TERMINAL_STATES = frozenset({"revoked", "corrected", "superseded"})


def execute_plan(
    plan_id: str,
    preview_hash: str,
    ledger: EmailLedger,
    transport: EmailTransport,
    transport_config,
    plan_dir: Path,
    identity_store=None,
    lifecycle_ledger=None,
    publication_id: Optional[str] = None,
    actor: str = "system",
    confirm_send: bool = False,
) -> ExecuteOutcome:
    if not confirm_send:
        raise ExecuteError("confirm_send is required for execution.")

    plan_path = plan_dir / "plan.json"
    if not plan_path.exists():
        raise ExecuteBlockedError(f"Plan not found: {plan_dir}")

    plan_dict = read_json(plan_path)
    if plan_dict.get("previewHash") != preview_hash:
        raise ExecuteBlockedError("previewHash mismatch.")

    try:
        verify_approval(plan_id, preview_hash, ledger)
    except NotApprovedError as exc:
        raise ExecuteBlockedError("Plan not approved.") from exc

    if lifecycle_ledger is not None and publication_id is not None:
        try:
            check_snapshot_sendable(lifecycle_ledger, publication_id)
        except SnapshotTerminalError as exc:
            raise ExecuteBlockedError("Snapshot not sendable.") from exc

    if identity_store is not None:
        drifts = check_identity_drift(plan_dict, identity_store)
        if drifts:
            raise IdentityDriftError(f"Identity drift detected: {'; '.join(drifts)}")

    try:
        transport.preflight(transport_config)
    except BatchTransportError as exc:
        raise ExecuteBlockedError(f"Transport preflight failed: {exc.sanitized_message}") from exc

    recipients = plan_dict.get("recipients", [])
    from_address = plan_dict.get("fromAddress", "")
    reply_to = plan_dict.get("replyTo")

    sent_count = 0
    failed_count = 0
    ambiguous_count = 0
    skipped_count = 0
    blocked_count = 0
    snapshot_terminal = False
    batch_transport_error = False

    transport_type = "fake" if isinstance(transport, FakeTransport) else "smtp"
    batch_run_id = ledger.start_batch_run(
        plan_id=plan_id,
        preview_hash=preview_hash,
        transport_type=transport_type,
        total_recipients=len(recipients),
        actor=actor,
    )

    try:
        for recipient in recipients:
            student_id = recipient["studentId"]
            idempotency_key = recipient["idempotencyKey"]
            masked_recipient = recipient["maskedRecipient"]
            identity_projection_hash = recipient["identityProjectionHash"]
            subject = recipient["subject"]
            text_body = recipient["textBody"]

            if snapshot_terminal or batch_transport_error:
                blocked_count += 1
                continue

            if lifecycle_ledger is not None and publication_id is not None:
                state = lifecycle_ledger.current_state(publication_id)
                if state in SNAPSHOT_TERMINAL_STATES:
                    snapshot_terminal = True
                    blocked_count += 1
                    continue

            try:
                action, delivery_id = ledger.acquire_for_execution(
                    plan_id=plan_id,
                    student_id=student_id,
                    idempotency_key=idempotency_key,
                    masked_recipient=masked_recipient,
                    identity_projection_hash=identity_projection_hash,
                    client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
                )
            except LedgerError:
                blocked_count += 1
                continue
            except Exception:
                blocked_count += 1
                continue

            if action == "sent":
                skipped_count += 1
                continue
            if action == "ambiguous":
                ambiguous_count += 1
                continue
            if action in ("failedPermanent", "sending", "paused", "failedTransient", "blocked"):
                blocked_count += 1
                continue
            if action not in ("reserved", "retryAuthorized"):
                blocked_count += 1
                continue

            try:
                ledger.transition_delivery(
                    delivery_id=delivery_id,
                    from_state=DeliveryState.RESERVED,
                    to_state=DeliveryState.SENDING,
                    client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
                )
            except Exception:
                blocked_count += 1
                continue

            envelope = Envelope(
                from_address=from_address,
                to_address=masked_recipient,
                reply_to=reply_to,
            )

            msg = build_email_message(
                from_address=from_address,
                to_address=masked_recipient,
                subject=subject,
                body=text_body,
                reply_to=reply_to,
                client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
            )

            try:
                receipt = transport.send(msg, envelope)
                if receipt.accepted:
                    ledger.transition_delivery(
                        delivery_id=delivery_id,
                        from_state=DeliveryState.SENDING,
                        to_state=DeliveryState.SENT,
                        transport_code=str(receipt.response_code),
                        provider_message_id=receipt.provider_message_id,
                        client_message_id=receipt.client_message_id,
                    )
                    sent_count += 1
                else:
                    ledger.transition_delivery(
                        delivery_id=delivery_id,
                        from_state=DeliveryState.SENDING,
                        to_state=DeliveryState.FAILED_PERMANENT,
                        transport_code=str(receipt.response_code),
                        error_class=receipt.response_class,
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
                        client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
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
                        client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
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
                        client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
                    )
                    failed_count += 1
            except BatchTransportError as exc:
                if exc.retryability == "transient":
                    ledger.transition_delivery(
                        delivery_id=delivery_id,
                        from_state=DeliveryState.SENDING,
                        to_state=DeliveryState.FAILED_TRANSIENT,
                        transport_code=exc.code,
                        error_class=type(exc).__name__,
                        delivery_certainty=exc.delivery_certainty,
                        client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
                    )
                else:
                    ledger.transition_delivery(
                        delivery_id=delivery_id,
                        from_state=DeliveryState.SENDING,
                        to_state=DeliveryState.FAILED_PERMANENT,
                        transport_code=exc.code,
                        error_class=type(exc).__name__,
                        delivery_certainty=exc.delivery_certainty,
                        client_message_id=f"<{idempotency_key[:24]}@academic-grading>",
                    )
                batch_transport_error = True
                break
            except LedgerError:
                blocked_count += 1
                break

    except Exception:
        blocked_count += 1

    if blocked_count > 0 and sent_count == 0 and ambiguous_count == 0 and failed_count == 0:
        outcome = ExecuteOutcome.BLOCKED
    elif snapshot_terminal and sent_count > 0:
        outcome = ExecuteOutcome.PARTIAL
    elif batch_transport_error:
        if sent_count > 0:
            outcome = ExecuteOutcome.PARTIAL
        else:
            outcome = ExecuteOutcome.BLOCKED
    elif blocked_count > 0 and ambiguous_count > 0:
        outcome = ExecuteOutcome.AMBIGUOUS
    elif ambiguous_count > 0:
        outcome = ExecuteOutcome.AMBIGUOUS
    elif blocked_count > 0 and sent_count > 0:
        outcome = ExecuteOutcome.PARTIAL
    elif failed_count > 0 and sent_count > 0:
        outcome = ExecuteOutcome.PARTIAL
    elif failed_count > 0 and sent_count == 0:
        outcome = ExecuteOutcome.PARTIAL
    elif blocked_count > 0:
        outcome = ExecuteOutcome.BLOCKED
    else:
        outcome = ExecuteOutcome.COMPLETE

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
    except LedgerError:
        pass

    return outcome
