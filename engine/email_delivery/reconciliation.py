"""Reconciliation and recovery for C3 email delivery.

Reconcile transforms orphan `sending` → `ambiguous` and `reserved` → `retryAuthorized`.
Resolve-ambiguous requires human decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import AmbiguousResolutionError, DeliveryStateError
from .ledger import EmailLedger
from .models import DeliveryState, DeliveryRecord

ORPHAN_SENDING_TIMEOUT_SECONDS = 300


def reconcile_plan(
    plan_id: str,
    ledger: EmailLedger,
    actor: str = "system.reconcile",
    orphan_timeout_seconds: int = ORPHAN_SENDING_TIMEOUT_SECONDS,
) -> list[dict]:
    deliveries = ledger.get_deliveries_for_plan(plan_id)
    events = []
    now = datetime.now(timezone.utc)

    for delivery in deliveries:
        if delivery.state == DeliveryState.SENDING:
            if delivery.last_attempt_at:
                try:
                    last = datetime.fromisoformat(delivery.last_attempt_at)
                    elapsed = (now - last).total_seconds()
                except (ValueError, TypeError):
                    elapsed = orphan_timeout_seconds + 1
            else:
                elapsed = orphan_timeout_seconds + 1

            if elapsed >= orphan_timeout_seconds:
                try:
                    ledger.transition_delivery(
                        delivery_id=delivery.delivery_id,
                        from_state=DeliveryState.SENDING,
                        to_state=DeliveryState.AMBIGUOUS,
                        transport_code="reconcile-orphan",
                        error_class="OrphanSending",
                        delivery_certainty="unknown",
                    )
                    ledger.record_reconciliation(
                        plan_id=plan_id,
                        delivery_id=delivery.delivery_id,
                        student_id=delivery.student_id,
                        idempotency_key=delivery.idempotency_key,
                        from_state="sending",
                        to_state="ambiguous",
                        reason="orphan-sending",
                        actor=actor,
                    )
                    events.append({
                        "deliveryId": delivery.delivery_id,
                        "studentId": delivery.student_id,
                        "fromState": "sending",
                        "toState": "ambiguous",
                        "reason": "orphan-sending",
                    })
                except DeliveryStateError:
                    pass

        elif delivery.state == DeliveryState.RESERVED:
            if delivery.last_attempt_at:
                try:
                    last = datetime.fromisoformat(delivery.last_attempt_at)
                    elapsed = (now - last).total_seconds()
                except (ValueError, TypeError):
                    elapsed = orphan_timeout_seconds + 1
            else:
                elapsed = orphan_timeout_seconds + 1

            if elapsed >= orphan_timeout_seconds:
                try:
                    ledger.transition_delivery(
                        delivery_id=delivery.delivery_id,
                        from_state=DeliveryState.RESERVED,
                        to_state=DeliveryState.RETRY_AUTHORIZED,
                        transport_code="reconcile-orphan",
                        error_class="OrphanReserved",
                    )
                    ledger.record_reconciliation(
                        plan_id=plan_id,
                        delivery_id=delivery.delivery_id,
                        student_id=delivery.student_id,
                        idempotency_key=delivery.idempotency_key,
                        from_state="reserved",
                        to_state="retryAuthorized",
                        reason="orphan-reserved",
                        actor=actor,
                    )
                    events.append({
                        "deliveryId": delivery.delivery_id,
                        "studentId": delivery.student_id,
                        "fromState": "reserved",
                        "toState": "retryAuthorized",
                        "reason": "orphan-reserved",
                    })
                except DeliveryStateError:
                    pass

    return events


def resolve_ambiguous(
    plan_id: str,
    student_id: str,
    decision: str,
    actor: str,
    reason: str,
    ledger: EmailLedger,
    confirm: bool = False,
) -> dict:
    if not confirm:
        raise AmbiguousResolutionError("Confirmation required for ambiguous resolution.")
    if decision not in ("sent", "not-sent"):
        raise AmbiguousResolutionError(f"Invalid decision: {decision!r}. Must be 'sent' or 'not-sent'.")
    if not actor or not actor.strip():
        raise AmbiguousResolutionError("actor is required.")
    if "@" in actor:
        raise AmbiguousResolutionError("actor must be a non-email audit id.")

    deliveries = ledger.get_deliveries_for_plan(plan_id)
    target = None
    for d in deliveries:
        if d.student_id == student_id and d.state == DeliveryState.AMBIGUOUS:
            target = d
            break

    if target is None:
        raise AmbiguousResolutionError(
            f"No ambiguous delivery found for studentId {student_id} in plan {plan_id}."
        )

    if decision == "sent":
        ledger.transition_delivery(
            delivery_id=target.delivery_id,
            from_state=DeliveryState.AMBIGUOUS,
            to_state=DeliveryState.SENT,
            transport_code="manual-resolve",
            error_class="AmbiguousResolution",
            delivery_certainty="delivered",
        )
    else:
        ledger.transition_delivery(
            delivery_id=target.delivery_id,
            from_state=DeliveryState.AMBIGUOUS,
            to_state=DeliveryState.RETRY_AUTHORIZED,
            transport_code="manual-resolve",
            error_class="AmbiguousResolution",
            delivery_certainty="notSent",
        )

    ledger.record_reconciliation(
        plan_id=plan_id,
        delivery_id=target.delivery_id,
        student_id=student_id,
        idempotency_key=target.idempotency_key,
        from_state="ambiguous",
        to_state="sent" if decision == "sent" else "retryAuthorized",
        reason=reason,
        actor=actor,
    )

    return {
        "deliveryId": target.delivery_id,
        "studentId": student_id,
        "decision": decision,
        "newState": "sent" if decision == "sent" else "retryAuthorized",
    }


def get_plan_status(plan_id: str, ledger: EmailLedger) -> dict:
    deliveries = ledger.get_deliveries_for_plan(plan_id)
    batch_runs = ledger.get_batch_runs(plan_id)

    state_counts = {}
    for d in deliveries:
        state_counts[d.state.value] = state_counts.get(d.state.value, 0) + 1

    return {
        "planId": plan_id,
        "totalDeliveries": len(deliveries),
        "stateCounts": state_counts,
        "batchRuns": len(batch_runs),
        "deliveries": [
            {
                "studentId": d.student_id,
                "maskedRecipient": d.masked_recipient,
                "state": d.state.value,
                "attemptCount": d.attempt_count,
            }
            for d in deliveries
        ],
    }
