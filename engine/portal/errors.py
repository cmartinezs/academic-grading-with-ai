"""C4 portal error hierarchy.

All portal failures are typed and fail-closed. None of the messages expose
capabilities, payloads, or student PII.
"""


class PortalError(Exception):
    """Base error for the C4 portal."""


class UsageError(PortalError):
    """CLI usage or configuration error (exit code 1)."""


class ValidationError(PortalError):
    """Schema, semantic, security, or approval gate failure (exit code 2)."""


class SchemaValidationError(ValidationError):
    """A contract failed JSON Schema validation."""


class SnapshotVerificationError(ValidationError):
    """The source Publication Snapshot failed the canonical C1 verifier."""


class SnapshotNotApprovedError(ValidationError):
    """The snapshot manifest is not in approved state."""


class SnapshotTerminalError(ValidationError):
    """The snapshot is in a terminal state (revoked/corrected/superseded)."""


class SnapshotModeError(ValidationError):
    """canonical/policy.json mode is missing or invalid."""


class HostingProfileError(ValidationError):
    """The hosting profile is invalid or fails its mode requirements."""


class PreflightError(HostingProfileError):
    """A publisher preflight check failed closed."""


class IdentityDriftError(ValidationError):
    """Identity projection drifted since release preparation."""


class BundleError(ValidationError):
    """Release bundle is missing, incomplete, or does not verify."""


class BundleTamperedError(BundleError):
    """A byte of the approved bundle changed after preparation."""


class ApprovalError(ValidationError):
    """Approval workflow error."""


class ApprovalMismatchError(ApprovalError):
    """releaseHash or objectCount does not match the release."""


class NotApprovedError(ApprovalError):
    """The release has not been approved."""


class AlreadyApprovedError(ApprovalError):
    """The release is already approved with the same releaseHash."""


class ActorError(ValidationError):
    """Actor identifier is empty, an email, or unsanitized."""


class CapabilityError(ValidationError):
    """Capability or object identifier validation error."""


class LedgerError(PortalError):
    """Ledger operation error."""


class StateTransitionError(LedgerError):
    """Invalid release state transition."""


class IdempotencyConflictError(LedgerError):
    """Concurrent acquisition of the same idempotency key."""


class PublisherError(PortalError):
    """Publisher operation error."""


class PublisherUnavailableError(PublisherError):
    """No publisher supports the requested hosting profile / publisher type."""


class OperationalError(PortalError):
    """Partial, blocked, or inconsistent operational state (exit code 3)."""


class ReconciliationError(OperationalError):
    """Reconciliation found inconsistent state."""
