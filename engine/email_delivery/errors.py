"""C3 email delivery error hierarchy."""


class EmailDeliveryError(Exception):
    """Base error for email delivery."""


class ExecuteError(EmailDeliveryError):
    """Execute workflow error."""


class ExecuteBlockedError(ExecuteError):
    """Execute blocked by gate, approval, tamper, identity, or lifecycle."""


class PlanError(EmailDeliveryError):
    """Plan construction or validation error."""


class PlanExistsError(PlanError):
    """A different plan already exists under the same planId."""


class PlanTamperedError(PlanError, ExecuteBlockedError):
    """Plan or source snapshot no longer matches its approved hashes.

    This is both a plan-validation error and an execute-blocking gate so direct
    domain callers cannot accidentally treat source tampering as operationally
    recoverable execution.
    """


class PlanRevokedError(PlanError):
    """Plan is revoked and cannot be used."""


class ApprovalError(EmailDeliveryError):
    """Approval workflow error."""


class ApprovalMismatchError(ApprovalError):
    """previewHash or recipientCount does not match the plan."""


class AlreadyApprovedError(ApprovalError):
    """Plan already approved with the same previewHash."""


class NotApprovedError(ApprovalError):
    """Plan has not been approved."""


class SnapshotError(EmailDeliveryError):
    """Snapshot state error."""


class SnapshotNotApprovedError(SnapshotError):
    """Snapshot is not in approved state."""


class SnapshotTerminalError(SnapshotError):
    """Snapshot is in a terminal state (revoked/corrected/superseded)."""


class IdentityDriftError(EmailDeliveryError):
    """Identity projection has drifted since plan creation."""


class RecipientError(EmailDeliveryError):
    """Recipient validation error."""


class DuplicateEmailError(RecipientError):
    """Two studentIds resolve to the same normalized email."""


class MissingIdentityError(RecipientError):
    """studentId not found in IdentityStore."""


class MissingEmailError(RecipientError):
    """studentId has no email in IdentityStore."""


class InvalidEmailError(RecipientError):
    """Email address is invalid."""


class TemplateError(EmailDeliveryError):
    """Template validation or rendering error."""


class UnknownPlaceholderError(TemplateError):
    """Placeholder not in allowedPlaceholders."""


class MissingPlaceholderValueError(TemplateError):
    """Placeholder value not provided."""


class TemplateHashMismatchError(TemplateError):
    """templateId/version registered with a different hash."""


class CRLFInjectionError(TemplateError):
    """CR or LF detected in subject or header."""


class LedgerError(EmailDeliveryError):
    """Ledger operation error."""


class DeliveryStateError(LedgerError):
    """Invalid state transition."""


class IdempotencyConflictError(LedgerError):
    """Concurrent reservation of the same idempotency key."""


class TransportError(EmailDeliveryError):
    """Transport-level error."""

    def __init__(
        self,
        message: str,
        scope: str,
        retryability: str,
        delivery_certainty: str,
        code: str,
    ):
        super().__init__(message)
        self.scope = scope
        self.retryability = retryability
        self.delivery_certainty = delivery_certainty
        self.code = code

    @property
    def sanitized_message(self) -> str:
        return str(self.args[0]) if self.args else ""


class BatchTransportError(TransportError):
    """Batch-scoped transport error (auth, config, rate limit)."""


class RecipientTransportError(TransportError):
    """Recipient-scoped transport error (invalid, refused, timeout)."""


class ReconcileError(EmailDeliveryError):
    """Reconciliation error."""


class AmbiguousResolutionError(EmailDeliveryError):
    """Ambiguous resolution error."""


class SchemaValidationError(EmailDeliveryError):
    """Schema validation error."""
