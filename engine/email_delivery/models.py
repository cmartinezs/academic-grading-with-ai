"""C3 email delivery domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DeliveryState(Enum):
    RESERVED = "reserved"
    SENDING = "sending"
    SENT = "sent"
    FAILED_TRANSIENT = "failedTransient"
    FAILED_PERMANENT = "failedPermanent"
    AMBIGUOUS = "ambiguous"
    PAUSED = "paused"
    RETRY_AUTHORIZED = "retryAuthorized"


TERMINAL_STATES = frozenset({DeliveryState.SENT, DeliveryState.FAILED_PERMANENT})

VALID_TRANSITIONS: dict[DeliveryState, frozenset[DeliveryState]] = {
    DeliveryState.RESERVED: frozenset({
        DeliveryState.SENDING,
        DeliveryState.RETRY_AUTHORIZED,
    }),
    DeliveryState.SENDING: frozenset({
        DeliveryState.SENT,
        DeliveryState.FAILED_TRANSIENT,
        DeliveryState.FAILED_PERMANENT,
        DeliveryState.AMBIGUOUS,
    }),
    DeliveryState.FAILED_TRANSIENT: frozenset({
        DeliveryState.RETRY_AUTHORIZED,
    }),
    DeliveryState.RETRY_AUTHORIZED: frozenset({
        DeliveryState.RESERVED,
    }),
    DeliveryState.AMBIGUOUS: frozenset({
        DeliveryState.SENT,
        DeliveryState.RETRY_AUTHORIZED,
    }),
    DeliveryState.SENT: frozenset(),
    DeliveryState.FAILED_PERMANENT: frozenset(),
    DeliveryState.PAUSED: frozenset({
        DeliveryState.RESERVED,
    }),
}


class SnapshotMode(Enum):
    LEGACY_EFFECTIVE = "legacy-effective"
    GRADE_POLICY_EFFECTIVE = "grade-policy-effective"


class ExecuteOutcome(Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    PAUSED = "PAUSED"
    AMBIGUOUS = "AMBIGUOUS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class TemplateDocument:
    schema_version: str
    template_id: str
    template_version: str
    intent: str
    subject: str
    text_body: str
    allowed_placeholders: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "templateId": self.template_id,
            "templateVersion": self.template_version,
            "intent": self.intent,
            "subject": self.subject,
            "textBody": self.text_body,
            "allowedPlaceholders": list(self.allowed_placeholders),
        }


@dataclass(frozen=True)
class SenderProfile:
    schema_version: str
    sender_profile_id: str
    from_address: str
    reply_to: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "schemaVersion": self.schema_version,
            "senderProfileId": self.sender_profile_id,
            "fromAddress": self.from_address,
        }
        if self.reply_to is not None:
            d["replyTo"] = self.reply_to
        return d


@dataclass(frozen=True)
class StudentEmailView:
    schema_version: str
    student_id: str
    section_id: str
    publication_id: str
    snapshot_mode: str
    assessments: tuple[dict, ...]

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "studentId": self.student_id,
            "sectionId": self.section_id,
            "publicationId": self.publication_id,
            "snapshotMode": self.snapshot_mode,
            "assessments": list(self.assessments),
        }


@dataclass(frozen=True)
class PlanRecipient:
    student_id: str
    normalized_recipient: str
    masked_recipient: str
    identity_projection_hash: str
    subject: str
    text_body: str
    item_hash: str
    idempotency_key: str

    def to_dict(self) -> dict:
        return {
            "studentId": self.student_id,
            "normalizedRecipient": self.normalized_recipient,
            "maskedRecipient": self.masked_recipient,
            "identityProjectionHash": self.identity_projection_hash,
            "subject": self.subject,
            "textBody": self.text_body,
            "itemHash": self.item_hash,
            "idempotencyKey": self.idempotency_key,
        }


@dataclass(frozen=True)
class EmailPlan:
    schema_version: str
    plan_id: str
    section_id: str
    publication_id: str
    snapshot_content_hash: str
    snapshot_review_hash: str
    snapshot_mode: str
    template_id: str
    template_version: str
    template_hash: str
    intent: str
    sender_profile_id: str
    from_address: str
    reply_to: Optional[str]
    recipient_count: int
    recipients: tuple[PlanRecipient, ...]
    preview_hash: str

    def to_dict(self) -> dict:
        return {
            "schemaVersion": self.schema_version,
            "planId": self.plan_id,
            "sectionId": self.section_id,
            "publicationId": self.publication_id,
            "snapshotContentHash": self.snapshot_content_hash,
            "snapshotReviewHash": self.snapshot_review_hash,
            "snapshotMode": self.snapshot_mode,
            "templateId": self.template_id,
            "templateVersion": self.template_version,
            "templateHash": self.template_hash,
            "intent": self.intent,
            "senderProfileId": self.sender_profile_id,
            "fromAddress": self.from_address,
            "replyTo": self.reply_to,
            "recipientCount": self.recipient_count,
            "recipients": [r.to_dict() for r in self.recipients],
            "previewHash": self.preview_hash,
        }

    def core_dict(self) -> dict:
        d = self.to_dict()
        d.pop("previewHash", None)
        return d


@dataclass(frozen=True)
class ApprovalRecord:
    plan_id: str
    preview_hash: str
    recipient_count: int
    approved_by: str
    approved_at: str
    status: str = "approved"

    def to_dict(self) -> dict:
        return {
            "planId": self.plan_id,
            "previewHash": self.preview_hash,
            "recipientCount": self.recipient_count,
            "approvedBy": self.approved_by,
            "approvedAt": self.approved_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class TransportReceipt:
    accepted: bool
    provider_message_id: Optional[str]
    client_message_id: str
    response_code: int
    response_class: str


@dataclass(frozen=True)
class Envelope:
    from_address: str
    to_address: str
    reply_to: Optional[str] = None


class TlsMode(Enum):
    STARTTLS = "starttls"
    IMPLICIT_TLS = "implicitTls"


@dataclass(frozen=True)
class TransportConfig:
    host: str
    port: int
    username: str
    password: str = ""
    tls_mode: TlsMode = TlsMode.STARTTLS
    use_tls: bool = True
    timeout: float = 30.0

    def __repr__(self) -> str:
        return f"TransportConfig(host={self.host!r}, port={self.port!r}, username={self.username!r}, tls_mode={self.tls_mode!r}, use_tls={self.use_tls!r}, timeout={self.timeout!r})"


@dataclass
class DeliveryRecord:
    delivery_id: int
    plan_id: str
    student_id: str
    idempotency_key: str
    masked_recipient: str
    identity_projection_hash: str
    state: DeliveryState
    attempt_count: int
    last_attempt_at: Optional[str]
    provider_message_id: Optional[str]
    client_message_id: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BatchRunSummary:
    batch_run_id: int
    plan_id: str
    preview_hash: str
    transport_type: str
    started_at: str
    completed_at: Optional[str]
    total_recipients: int
    sent_count: int
    failed_count: int
    ambiguous_count: int
    skipped_count: int
    outcome: Optional[str]
    actor: str


@dataclass(frozen=True)
class VerifiedEmailPlan:
    plan_id: str
    preview_hash: str
    recipient_count: int
    plan_dict: dict
    manifest: dict
