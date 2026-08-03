#!/usr/bin/env python3
"""C4 secure student portal CLI.

Subcommands: prepare, inspect, approve, publish, verify, status, reconcile,
revoke, purge, ledger-check, test.

Exit codes: 0 success, 1 usage/config, 2 validation/security/approval gate,
3 partial/blocked/operational. No --force, --auto-approve, --plaintext, or
--short-code exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "engine"))


def _usage_error(message: str):
    from portal.errors import UsageError

    return UsageError(message)


def _resolve_roots():
    from c0.paths import resolve_runtime_roots

    return resolve_runtime_roots(WORKSPACE_ROOT)


def _get_ledger(roots):
    from portal.ledger import PortalLedger

    ledger = PortalLedger(roots.state_root / "portal" / "portal-ledger.sqlite3")
    return ledger


def _get_identity_store(roots):
    from c0.identity import IdentityStore

    return IdentityStore(roots.state_root / "identity")


def _get_lifecycle_ledger(roots, section_id):
    from publication.lifecycle import LifecycleLedger

    return LifecycleLedger(roots.state_root, section_id)


def _snapshot_dir(roots, section_id: str, publication_id: str) -> Path:
    return roots.publications_root / "sections" / section_id / publication_id


def _plan_dir(roots, section_id: str, publication_id: str, release_id: str) -> Path:
    return roots.private_root / "portal" / "plans" / section_id / publication_id / release_id


def _load_profile(path: Path):
    from portal.models import HostingProfile

    import json as _json

    data = _json.loads(Path(path).read_text(encoding="utf-8"))
    return HostingProfile(
        profile_id=data["profileId"],
        mode=data["mode"],
        base_url=data["baseUrl"],
        tls_required=data["tlsRequired"],
        directory_listing_disabled=data["directoryListingDisabled"],
        header_policy=data["headerPolicy"],
        cache_policy=data["cachePolicy"],
        supports_atomic_promotion=data["supportsAtomicPromotion"],
        supports_delete=data["supportsDelete"],
        supports_purge=data["supportsPurge"],
        authorization_model=data.get("authorizationModel"),
    )


def _emit(result: dict, exit_code: int = 0) -> None:
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(exit_code)


def cmd_prepare(args):
    from portal.lifecycle import prepare

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    ledger.init()
    identity_store = _get_identity_store(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    profile = _load_profile(args.profile)
    try:
        result = prepare(
            roots=roots,
            section_id=args.section,
            publication_id=args.publication,
            snapshot_dir=snapshot_dir,
            hosting_profile=profile,
            portal_mode=profile.mode,
            identity_store=identity_store,
            lifecycle_ledger=lifecycle_ledger,
            ledger=ledger,
        )
        ledger.register_hosting_profile(profile)
    finally:
        ledger.close()
    _emit(result)


def cmd_inspect(args):
    from portal.approval import _verify_bundle

    roots = _resolve_roots()
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        plan = _verify_bundle(plan_dir)
    finally:
        pass
    _emit(
        {
            "releaseId": plan["releaseId"],
            "releaseHash": plan["releaseHash"],
            "sectionId": plan["sectionId"],
            "publicationId": plan["publicationId"],
            "snapshotMode": plan["snapshot"]["mode"],
            "portalMode": plan["portalMode"],
            "hostingProfileId": plan["hostingProfileId"],
            "objectCount": plan["objectCount"],
            "objects": [
                {"studentId": obj["studentId"], "objectId": obj["objectId"]}
                for obj in plan["objects"]
            ],
        }
    )


def cmd_approve(args):
    from portal.lifecycle import approve

    if not args.confirm_reviewed:
        raise _usage_error("--confirm-reviewed is required to approve a release.")
    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    identity_store = _get_identity_store(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        result = approve(
            release_id=args.release,
            plan_dir=plan_dir,
            actor=args.actor,
            ledger=ledger,
            identity_store=identity_store,
            lifecycle_ledger=lifecycle_ledger,
            publication_id=args.publication,
            snapshot_dir=snapshot_dir,
            confirm_reviewed=args.confirm_reviewed,
        )
    finally:
        ledger.close()
    _emit(result)


def cmd_publish(args):
    from portal.lifecycle import publish

    if not args.confirm_publish:
        raise _usage_error("--confirm-publish is required to publish a release.")
    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    identity_store = _get_identity_store(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        result = publish(
            release_id=args.release,
            plan_dir=plan_dir,
            publisher_type=args.publisher,
            ledger=ledger,
            receipts_dir=roots.state_root / "portal" / "receipts",
            deployments_root=roots.state_root / "portal" / "deployments",
            identity_store=identity_store,
            lifecycle_ledger=lifecycle_ledger,
            publication_id=args.publication,
            snapshot_dir=snapshot_dir,
            confirm_publish=args.confirm_publish,
        )
    finally:
        ledger.close()
    _emit(result)


def cmd_verify(args):
    from portal.approval import _verify_bundle, verify_approval
    from portal.snapshot import verify_source_snapshot

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        plan = _verify_bundle(plan_dir)
        record = verify_approval(args.release, plan["releaseHash"], ledger)
        snapshot = verify_source_snapshot(
            snapshot_dir, args.section, args.publication, lifecycle_ledger
        )
    finally:
        ledger.close()
    _emit(
        {
            "releaseId": args.release,
            "releaseHash": plan["releaseHash"],
            "bundleVerified": True,
            "approved": True,
            "approvedBy": record.approved_by,
            "approvedAt": record.approved_at,
            "snapshotMode": snapshot.snapshot_mode,
            "snapshotState": snapshot.lifecycle_state,
        }
    )


def cmd_status(args):
    from portal.lifecycle import status

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    try:
        result = status(ledger, args.release)
    finally:
        ledger.close()
    _emit(result)


def cmd_reconcile(args):
    from portal.reconciliation import reconcile_release

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        result = reconcile_release(
            release_id=args.release,
            plan_dir=plan_dir,
            ledger=ledger,
            receipts_dir=roots.state_root / "portal" / "receipts",
            deployments_root=roots.state_root / "portal" / "deployments",
            actor=args.actor,
        )
    finally:
        ledger.close()
    _emit(result, exit_code=0 if result["status"] in ("published",) else 3)


def cmd_revoke(args):
    from portal.lifecycle import revoke

    if not args.confirm_revoke:
        raise _usage_error("--confirm-revoke is required to revoke a release.")
    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        result = revoke(
            release_id=args.release,
            plan_dir=plan_dir,
            ledger=ledger,
            receipts_dir=roots.state_root / "portal" / "receipts",
            deployments_root=roots.state_root / "portal" / "deployments",
            actor=args.actor,
            reason=args.reason,
            confirm_revoke=args.confirm_revoke,
        )
    finally:
        ledger.close()
    _emit(result)


def cmd_purge(args):
    from portal.lifecycle import purge

    if not args.confirm_purge:
        raise _usage_error("--confirm-purge is required to purge a release.")
    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    plan_dir = _plan_dir(roots, args.section, args.publication, args.release)
    try:
        result = purge(
            release_id=args.release,
            plan_dir=plan_dir,
            ledger=ledger,
            receipts_dir=roots.state_root / "portal" / "receipts",
            deployments_root=roots.state_root / "portal" / "deployments",
            actor=args.actor,
            confirm_purge=args.confirm_purge,
        )
    finally:
        ledger.close()
    _emit(result)


def cmd_ledger_check(args):
    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    try:
        ledger.init()
        integrity = ledger.integrity_check()
        fk = ledger.foreign_key_check()
    finally:
        ledger.close()
    if integrity != ["ok"] or fk:
        _emit({"integrity": "FAIL", "issues": integrity, "foreignKeyIssues": fk}, exit_code=3)
    _emit({"integrity": "OK"})


def cmd_test(args):
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        print("Error: node is required for the static app interop tests.", file=sys.stderr)
        sys.exit(1)
    static_tests = WORKSPACE_ROOT / "engine" / "portal" / "static" / "tests"
    node_result = subprocess.run(
        [node, "--test", str(static_tests / "app.interop.test.js")],
        capture_output=False,
    )
    if node_result.returncode != 0:
        sys.exit(node_result.returncode)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(WORKSPACE_ROOT / "engine" / "portal" / "tests"),
            "-q",
            "--tb=short",
        ],
        capture_output=False,
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(prog="portal", description="C4 secure student portal")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--profile", required=True, help="path to a PortalHostingProfile JSON")

    p = sub.add_parser("inspect")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)

    p = sub.add_parser("approve")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--confirm-reviewed", action="store_true")

    p = sub.add_parser("publish")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--publisher", required=True, choices=["local-static", "fake-authenticated"])
    p.add_argument("--confirm-publish", action="store_true")

    p = sub.add_parser("verify")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)

    p = sub.add_parser("status")
    p.add_argument("--release", required=True)

    p = sub.add_parser("reconcile")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--actor", default="system.reconcile")

    p = sub.add_parser("revoke")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--reason")
    p.add_argument("--confirm-revoke", action="store_true")

    p = sub.add_parser("purge")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--confirm-purge", action="store_true")

    sub.add_parser("ledger-check")
    sub.add_parser("test")

    args = parser.parse_args()
    handlers = {
        "prepare": cmd_prepare,
        "inspect": cmd_inspect,
        "approve": cmd_approve,
        "publish": cmd_publish,
        "verify": cmd_verify,
        "status": cmd_status,
        "reconcile": cmd_reconcile,
        "revoke": cmd_revoke,
        "purge": cmd_purge,
        "ledger-check": cmd_ledger_check,
        "test": cmd_test,
    }
    try:
        handlers[args.command](args)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(3)
    except Exception as exc:
        _print_error_and_exit(exc)


def _print_error_and_exit(exc: Exception) -> None:
    from portal.errors import LedgerError, OperationalError, PublisherError, UsageError, ValidationError

    code = 3
    if isinstance(exc, UsageError):
        code = 1
    elif isinstance(exc, ValidationError):
        code = 2
    elif isinstance(exc, (OperationalError, LedgerError, PublisherError)):
        code = 3
    print(f"Error: {exc}", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
