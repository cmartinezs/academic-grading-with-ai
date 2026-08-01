#!/usr/bin/env python3
"""publication-snapshot — C1 CLI (build/verify/review/approve/status/transition/compatibility).

Exit codes:
    0 success
    1 usage / invalid state (e.g. illegal transition, missing staging)
    2 gate failure (schema, hash, identity, privacy) — fail-closed
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from publication import builder, compat  # noqa: E402
from publication.clock import Clock  # noqa: E402
from publication.errors import (  # noqa: E402
    CompatibilityError,
    ConfirmationRequiredError,
    ContentHashMismatchError,
    DestinationExistsError,
    GateError,
    InvalidTransitionError,
    LedgerError,
    LegacyCourseMismatchError,
    MissingLegacyExportError,
    NotReviewedError,
    PublicationError,
    SameFilesystemError,
    StagingExistsError,
    UnmappedStudentError,
)
from publication.ids import validate_publication_id  # noqa: E402
from publication.legacy import load_legacy_export  # noqa: E402


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


GATE_EXCEPTIONS = (
    GateError,
    ContentHashMismatchError,
    UnmappedStudentError,
)
STATE_EXCEPTIONS = (
    NotReviewedError,
    InvalidTransitionError,
    ConfirmationRequiredError,
    StagingExistsError,
    DestinationExistsError,
    SameFilesystemError,
    MissingLegacyExportError,
    LegacyCourseMismatchError,
    LedgerError,
    CompatibilityError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(description="C1 publication snapshot and lifecycle (v0.1.0).")
    parser.add_argument("--workspace", help="Workspace root (defaults to repository root).")
    parser.add_argument("--section", required=True, help="Section code (e.g. FP2111-S1).")
    parser.add_argument("--publication", help="Opaque publicationId (auto-generated on build).")

    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build a draft snapshot in staging.")
    p_build.add_argument("--dry-run", action="store_true", help="Compute the content hash without writing anything.")
    p_build.add_argument("--legacy-source", help="Override the legacy export directory.")

    p_verify = sub.add_parser("verify", help="Verify a snapshot (staging or approved).")
    p_verify.add_argument(
        "--target", choices=["staging", "approved"], default="staging",
        help="Which snapshot to verify (default: staging).",
    )

    p_review = sub.add_parser("review", help="Review a draft bound to an exact content hash.")
    p_review.add_argument("--content-hash", required=True, help="Exact contentHash to review.")
    p_review.add_argument("--reviewer", required=True, help="Audit id of the reviewer (not an email).")
    p_review.add_argument("--dry-run", action="store_true", help="Validate the review without writing.")

    p_approve = sub.add_parser("approve", help="Approve a reviewed draft and promote it atomically.")
    p_approve.add_argument("--content-hash", required=True, help="Exact contentHash to approve.")
    p_approve.add_argument("--approver", required=True, help="Audit id of the approver (not an email).")
    p_approve.add_argument("--confirm", choices=["approve"], help="Explicit confirmation required.")

    p_transition = sub.add_parser("transition", help="Append a lifecycle event to the ledger.")
    p_transition.add_argument("--event", choices=["published", "superseded", "corrected", "revoked"], required=True)
    p_transition.add_argument("--actor", help="Audit id performing the transition.")
    p_transition.add_argument("--receipt", help="Receipt reference (required for published).")
    p_transition.add_argument("--by-publication", help="Referenced approved publication (required for superseded/corrected).")
    p_transition.add_argument("--reason", help="Optional reason recorded in the ledger.")
    p_transition.add_argument("--confirm", choices=["approve"], help="Explicit confirmation required for terminal events.")

    p_compat = sub.add_parser("compatibility", help="Generate compatibility views from an approved snapshot.")
    p_compat.add_argument("--update-legacy-aliases", action="store_true", help="Also write legacy aliases (course/*, evaluations, grades).")

    sub.add_parser("status", help="Show the lifecycle state and published snapshots for the section.")

    p_discard = sub.add_parser("discard", help="Remove the staging draft for this publication.")
    p_discard.add_argument("--publication", help="PublicationId whose staging is discarded (defaults to current).")

    return parser


def make_context(args, publication_id=None):
    workspace = Path(args.workspace).resolve() if args.workspace else ROOT
    env = dict(os.environ)
    return builder.BuildContext.resolve(
        workspace,
        args.section,
        publication_id=publication_id or args.publication,
        env=env,
        clock=Clock(env=env),
        legacy_source=Path(args.legacy_source) if getattr(args, "legacy_source", None) else None,
    )


def cmd_build(args) -> int:
    ctx = make_context(args)
    result = builder.build_draft(ctx, dry_run=args.dry_run)
    print(f"Section: {result.section_id}")
    print(f"Publication: {result.publication_id}")
    print(f"ContentHash: {result.content_hash}")
    print(f"Staging: {result.staging_dir}")
    print(f"Files: {result.file_count}")
    if result.dry_run:
        print("Dry run: nothing written.")
    else:
        print("Status: draft (staging). Review before approval.")
    return 0


def cmd_verify(args) -> int:
    ctx = make_context(args)
    report = builder.verify(ctx, target=args.target)
    print(f"Verify target: {args.target} ({report.root})")
    for finding in report.findings:
        print(f"[{finding.gate}] {finding.message}")
    print(f"Result: {report.summary()}")
    return 0 if report.passed() else 2


def cmd_review(args) -> int:
    ctx = make_context(args)
    builder.review_draft(ctx, args.content_hash, args.reviewer, dry_run=args.dry_run)
    print(f"Reviewed {ctx.publication_id} bound to {args.content_hash} by {args.reviewer}.")
    return 0


def cmd_approve(args) -> int:
    ctx = make_context(args)
    dest = builder.approve_draft(ctx, args.content_hash, args.approver, args.confirm or "")
    print(f"Approved {ctx.publication_id}.")
    print(f"Snapshot: {dest}")
    return 0


def cmd_transition(args) -> int:
    ctx = make_context(args)
    if args.publication is None:
        print("transition requires --publication.", file=sys.stderr)
        return 1
    validate_publication_id(args.publication)
    if args.event in ("superseded", "corrected", "revoked") and args.confirm != "approve":
        raise ConfirmationRequiredError("Terminal lifecycle transitions require --confirm approve.")
    if args.event == "published" and not args.receipt:
        raise ConfirmationRequiredError("published requires --receipt.")
    if args.event in ("superseded", "corrected") and not args.by_publication:
        raise ConfirmationRequiredError(f"{args.event} requires --by-publication.")
    ledger = ctx.ledger()
    event = ledger.append(
        args.event,
        args.publication,
        actor=args.actor,
        receipt=args.receipt,
        by_publication_id=args.by_publication,
        reason=args.reason,
        is_approved=lambda pid: builder.approved_snapshot_exists(ctx, pid)
        and builder.is_approved_snapshot(ctx, pid),
    )
    print(f"Event #{event['seq']}: {event['event']} for {event['publicationId']}.")
    return 0


def cmd_compatibility(args) -> int:
    ctx = make_context(args)
    written = compat.generate(ctx, update_legacy_aliases=args.update_legacy_aliases)
    print(f"Compatibility views for {ctx.publication_id}:")
    for rel in written:
        print(f"  {rel}")
    return 0


def cmd_status(args) -> int:
    ctx = make_context(args)
    ledger = ctx.ledger()
    events = ledger.read_events()
    print(f"Section: {ctx.section_id}")
    if not events:
        print("No lifecycle events recorded.")
    for event in events:
        print(f"  #{event['seq']} {event['event']} {event['publicationId']} "
              f"at={event['at']} actor={event.get('actor', '-')}")
    destinations = ctx.sections_root() / ctx.section_id
    if destinations.is_dir():
        pubs = sorted(p.name for p in destinations.iterdir() if p.is_dir())
        print(f"Approved snapshots: {', '.join(pubs) if pubs else '(none)'}")
    else:
        print("Approved snapshots: (none)")
    return 0


def cmd_discard(args) -> int:
    if args.publication:
        ctx = make_context(args, publication_id=args.publication)
    else:
        ctx = make_context(args)
    removed = builder.discard_staging(ctx)
    print(f"Discarded staging for {ctx.publication_id}: {removed}")
    return 0


COMMANDS = {
    "build": cmd_build,
    "verify": cmd_verify,
    "review": cmd_review,
    "approve": cmd_approve,
    "transition": cmd_transition,
    "compatibility": cmd_compatibility,
    "status": cmd_status,
    "discard": cmd_discard,
}


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except GATE_EXCEPTIONS as exc:
        print(f"Gate failed (fail-closed): {exc}", file=sys.stderr)
        if getattr(exc, "details", None):
            for detail in exc.details:
                print(f"  - {detail}", file=sys.stderr)
        return 2
    except STATE_EXCEPTIONS as exc:
        print(f"Invalid state: {exc}", file=sys.stderr)
        return 1
    except PublicationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
