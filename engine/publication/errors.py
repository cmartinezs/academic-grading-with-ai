"""C1 exception hierarchy."""

from __future__ import annotations


class PublicationError(Exception):
    """Base error for the C1 publication package."""


class InvalidSectionIdError(PublicationError):
    """The section id is not a safe path segment."""


class InvalidPublicationIdError(PublicationError):
    """The publication id is not a valid opaque id."""


class StagingExistsError(PublicationError):
    """The staging directory for this publication already exists."""


class DestinationExistsError(PublicationError):
    """The destination snapshot already exists; refusing to overwrite."""


class SameFilesystemError(PublicationError):
    """Staging and destination are not on the same filesystem; rename cannot be atomic."""


class UnmappedStudentError(PublicationError):
    """A legacy student has no opaque identity assigned."""


class MissingLegacyExportError(PublicationError):
    """The legacy export data is missing or unreadable."""


class LegacyCourseMismatchError(PublicationError):
    """The legacy export does not correspond to the requested section."""


class GateError(PublicationError):
    """A gate failed (fail-closed). Carries a list of findings."""

    def __init__(self, gate: str, findings: list[str]):
        self.gate = gate
        self.findings = findings
        message = f"Gate {gate} failed ({len(findings)} finding(s))"
        super().__init__(message)
        self.details = findings


class ContentHashMismatchError(PublicationError):
    """The expected content hash does not match the computed one."""


class NotReviewedError(PublicationError):
    """Approval requires a prior review bound to the exact content hash."""


class ReviewRequiredError(PublicationError):
    """The publication must be reviewed before approval."""


class ConfirmationRequiredError(PublicationError):
    """An explicit confirmation is required for approval."""


class ImmutableSnapshotError(PublicationError):
    """An approved snapshot cannot be modified or rebuilt."""


class InvalidTransitionError(PublicationError):
    """The requested lifecycle transition is not allowed from the current state."""


class LedgerError(PublicationError):
    """The lifecycle ledger could not be read or written."""


class CompatibilityError(PublicationError):
    """Compatibility views cannot be generated from this snapshot."""


class SchemaError(PublicationError):
    """JSON Schema validation failed (fail-closed)."""
