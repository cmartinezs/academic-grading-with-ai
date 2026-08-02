#!/usr/bin/env python3
"""C3 email delivery CLI.

Subcommands: prepare, inspect, approve, execute, status, reconcile,
resolve-ambiguous, ledger-check, test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(WORKSPACE_ROOT / "engine"))


def _resolve_roots():
    from c0.paths import resolve_runtime_roots
    return resolve_runtime_roots(WORKSPACE_ROOT)


def _get_ledger(roots):
    from email_delivery.ledger import EmailLedger
    db_path = roots.state_root / "email" / "email-ledger.sqlite3"
    return EmailLedger(db_path)


def _get_identity_store(roots):
    from c0.identity import IdentityStore
    return IdentityStore(roots.state_root / "identity")


def _get_lifecycle_ledger(roots, section_id):
    from publication.lifecycle import LifecycleLedger
    return LifecycleLedger(roots.state_root, section_id)


def cmd_prepare(args):
    from email_delivery.plan import prepare_plan
    from email_delivery.canonical import read_json, sha256_file

    roots = _resolve_roots()
    identity_store = _get_identity_store(roots)

    snapshot_dir = roots.publications_root / "sections" / args.section / args.publication
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: snapshot manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(2)

    manifest = read_json(manifest_path)
    content_hash = manifest.get("contentHash", "")
    review_hash = manifest.get("reviewHash", "")

    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)

    try:
        plan = prepare_plan(
            section_id=args.section,
            publication_id=args.publication,
            snapshot_dir=snapshot_dir,
            snapshot_content_hash=content_hash,
            snapshot_review_hash=review_hash,
            snapshot_mode=args.mode,
            template_path=Path(args.template),
            sender_profile_path=Path(args.sender_profile),
            identity_store=identity_store,
            private_root=roots.private_root,
            temp_root=roots.temp_root,
            lifecycle_ledger=lifecycle_ledger,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    ledger = _get_ledger(roots)
    plan_dir = roots.private_root / "email" / "plans" / args.section / args.publication / plan.plan_id
    try:
        ledger.register_plan(
            plan_id=plan.plan_id,
            section_id=args.section,
            publication_id=args.publication,
            snapshot_content_hash=content_hash,
            snapshot_review_hash=review_hash,
            snapshot_mode=args.mode,
            template_id=plan.template_id,
            template_version=plan.template_version,
            template_hash=plan.template_hash,
            intent=plan.intent,
            sender_profile_id=plan.sender_profile_id,
            from_address=plan.from_address,
            reply_to=plan.reply_to,
            preview_hash=plan.preview_hash,
            recipient_count=plan.recipient_count,
            plan_path=str(plan_dir),
        )
    except Exception:
        pass
    finally:
        ledger.close()

    print(json.dumps({
        "planId": plan.plan_id,
        "previewHash": plan.preview_hash,
        "recipientCount": plan.recipient_count,
    }, indent=2))


def cmd_inspect(args):
    roots = _resolve_roots()
    plan_dir = roots.private_root / "email" / "plans" / args.section / args.publication / args.plan
    plan_path = plan_dir / "plan.json"
    if not plan_path.exists():
        print(f"Error: plan not found at {plan_path}", file=sys.stderr)
        sys.exit(2)

    from email_delivery.canonical import read_json
    plan = read_json(plan_path)

    output = {
        "planId": plan.get("planId"),
        "previewHash": plan.get("previewHash"),
        "recipientCount": plan.get("recipientCount"),
        "recipients": [
            {
                "studentId": r.get("studentId"),
                "maskedRecipient": r.get("maskedRecipient"),
            }
            for r in plan.get("recipients", [])
        ],
    }
    print(json.dumps(output, indent=2))


def cmd_approve(args):
    from email_delivery.approval import approve_plan

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    identity_store = _get_identity_store(roots)
    plan_dir = roots.private_root / "email" / "plans" / args.section / args.publication / args.plan

    try:
        lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    except Exception:
        lifecycle_ledger = None

    try:
        record = approve_plan(
            plan_id=args.plan,
            preview_hash=args.preview_hash,
            recipient_count=args.recipient_count,
            actor=args.actor,
            ledger=ledger,
            plan_dir=plan_dir,
            identity_store=identity_store,
            lifecycle_ledger=lifecycle_ledger,
            publication_id=args.publication,
            confirm_reviewed=True,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        ledger.close()
        sys.exit(2)

    ledger.close()
    print(json.dumps(record.to_dict(), indent=2))


def cmd_execute(args):
    from email_delivery.executor import execute_plan
    from email_delivery.transport.fake import FakeTransport, FakeBehavior
    from email_delivery.transport.smtp import SMTPTransport
    from email_delivery.models import TransportConfig

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    identity_store = _get_identity_store(roots)
    plan_dir = roots.private_root / "email" / "plans" / args.section / args.publication / args.plan

    try:
        lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    except Exception:
        lifecycle_ledger = None

    if args.transport == "fake":
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
    else:
        transport = SMTPTransport()
        config = TransportConfig(
            host=os.environ.get("ACADGRAD_SMTP_HOST", "localhost"),
            port=int(os.environ.get("ACADGRAD_SMTP_PORT", "587")),
            username=os.environ.get("ACADGRAD_SMTP_USERNAME", ""),
        )

    try:
        outcome = execute_plan(
            plan_id=args.plan,
            preview_hash=args.preview_hash,
            ledger=ledger,
            transport=transport,
            transport_config=config,
            plan_dir=plan_dir,
            identity_store=identity_store,
            lifecycle_ledger=lifecycle_ledger,
            publication_id=args.publication,
            actor=args.actor or "system",
            confirm_send=True,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        ledger.close()
        sys.exit(2)

    ledger.close()
    print(json.dumps({"outcome": outcome.value}, indent=2))


def cmd_status(args):
    from email_delivery.reconciliation import get_plan_status

    roots = _resolve_roots()
    ledger = _get_ledger(roots)

    try:
        status = get_plan_status(args.plan, ledger)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        ledger.close()
        sys.exit(2)

    ledger.close()
    print(json.dumps(status, indent=2))


def cmd_reconcile(args):
    from email_delivery.reconciliation import reconcile_plan

    roots = _resolve_roots()
    ledger = _get_ledger(roots)

    try:
        events = reconcile_plan(args.plan, ledger, actor=args.actor or "system.reconcile")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        ledger.close()
        sys.exit(2)

    ledger.close()
    print(json.dumps({"reconciliationEvents": events}, indent=2))


def cmd_resolve_ambiguous(args):
    from email_delivery.reconciliation import resolve_ambiguous

    roots = _resolve_roots()
    ledger = _get_ledger(roots)

    try:
        result = resolve_ambiguous(
            plan_id=args.plan,
            student_id=args.student,
            decision=args.decision,
            actor=args.actor,
            reason=args.reason,
            ledger=ledger,
            confirm=True,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        ledger.close()
        sys.exit(2)

    ledger.close()
    print(json.dumps(result, indent=2))


def cmd_ledger_check(args):
    roots = _resolve_roots()
    ledger = _get_ledger(roots)

    issues = ledger.integrity_check()
    ledger.close()

    if issues:
        print(json.dumps({"integrity": "FAIL", "issues": issues}, indent=2))
        sys.exit(3)
    else:
        print(json.dumps({"integrity": "OK"}, indent=2))


def cmd_test(args):
    import subprocess
    test_dir = WORKSPACE_ROOT / "engine" / "email_delivery" / "tests"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-v", "--tb=short"],
        capture_output=False,
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(prog="email-delivery", description="C3 email delivery workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--template", required=True)
    p.add_argument("--sender-profile", required=True)
    p.add_argument("--mode", default="legacy-effective", choices=["legacy-effective", "grade-policy-effective"])

    p = sub.add_parser("inspect")
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--plan", required=True)

    p = sub.add_parser("approve")
    p.add_argument("--plan", required=True)
    p.add_argument("--preview-hash", required=True)
    p.add_argument("--recipient-count", type=int, required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--confirm-reviewed", action="store_true")

    p = sub.add_parser("execute")
    p.add_argument("--plan", required=True)
    p.add_argument("--preview-hash", required=True)
    p.add_argument("--section", required=True)
    p.add_argument("--publication", required=True)
    p.add_argument("--actor", default="system")
    p.add_argument("--transport", default="fake", choices=["fake", "smtp"])
    p.add_argument("--confirm-send", action="store_true")

    p = sub.add_parser("status")
    p.add_argument("--plan", required=True)

    p = sub.add_parser("reconcile")
    p.add_argument("--plan", required=True)
    p.add_argument("--actor", default="system.reconcile")

    p = sub.add_parser("resolve-ambiguous")
    p.add_argument("--plan", required=True)
    p.add_argument("--student", required=True)
    p.add_argument("--decision", required=True, choices=["sent", "not-sent"])
    p.add_argument("--actor", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--confirm", action="store_true")

    p = sub.add_parser("ledger-check")

    p = sub.add_parser("test")

    args = parser.parse_args()

    handlers = {
        "prepare": cmd_prepare,
        "inspect": cmd_inspect,
        "approve": cmd_approve,
        "execute": cmd_execute,
        "status": cmd_status,
        "reconcile": cmd_reconcile,
        "resolve-ambiguous": cmd_resolve_ambiguous,
        "ledger-check": cmd_ledger_check,
        "test": cmd_test,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()
