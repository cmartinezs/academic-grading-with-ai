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
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "engine"))


def _resolve_roots():
    from c0.paths import resolve_runtime_roots

    return resolve_runtime_roots(WORKSPACE_ROOT)


def _get_ledger(roots):
    from email_delivery.ledger import EmailLedger

    return EmailLedger(roots.state_root / "email" / "email-ledger.sqlite3")


def _get_identity_store(roots):
    from c0.identity import IdentityStore

    return IdentityStore(roots.state_root / "identity")


def _get_lifecycle_ledger(roots, section_id):
    from publication.lifecycle import LifecycleLedger

    return LifecycleLedger(roots.state_root, section_id)


def _snapshot_dir(roots, section_id: str, publication_id: str) -> Path:
    return roots.publications_root / "sections" / section_id / publication_id


def cmd_prepare(args):
    from email_delivery.lifecycle import verify_email_source_snapshot
    from email_delivery.plan import prepare_plan

    roots = _resolve_roots()
    identity_store = _get_identity_store(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    ledger = _get_ledger(roots)

    try:
        verified_snapshot = verify_email_source_snapshot(
            snapshot_dir=snapshot_dir,
            section_id=args.section,
            publication_id=args.publication,
            lifecycle_ledger=lifecycle_ledger,
        )
        plan = prepare_plan(
            section_id=args.section,
            publication_id=args.publication,
            snapshot_dir=snapshot_dir,
            snapshot_content_hash=verified_snapshot.content_hash,
            snapshot_review_hash=verified_snapshot.review_hash,
            snapshot_mode=verified_snapshot.snapshot_mode,
            template_path=Path(args.template),
            sender_profile_path=Path(args.sender_profile),
            identity_store=identity_store,
            private_root=roots.private_root,
            temp_root=roots.temp_root,
            lifecycle_ledger=lifecycle_ledger,
            ledger=ledger,
        )
        plan_dir = (
            roots.private_root
            / "email"
            / "plans"
            / args.section
            / args.publication
            / plan.plan_id
        )
        ledger.register_plan(
            plan_id=plan.plan_id,
            section_id=plan.section_id,
            publication_id=plan.publication_id,
            snapshot_content_hash=plan.snapshot_content_hash,
            snapshot_review_hash=plan.snapshot_review_hash,
            snapshot_mode=plan.snapshot_mode,
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
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
        ledger.close()

    print(
        json.dumps(
            {
                "planId": plan.plan_id,
                "previewHash": plan.preview_hash,
                "recipientCount": plan.recipient_count,
                "snapshotMode": plan.snapshot_mode,
            },
            indent=2,
        )
    )


def cmd_inspect(args):
    from email_delivery.executor import inspect_plan

    roots = _resolve_roots()
    plan_dir = (
        roots.private_root
        / "email"
        / "plans"
        / args.section
        / args.publication
        / args.plan
    )
    try:
        verified = inspect_plan(plan_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)

    plan = verified.plan_dict
    print(
        json.dumps(
            {
                "planId": verified.plan_id,
                "previewHash": verified.preview_hash,
                "recipientCount": verified.recipient_count,
                "recipients": [
                    {
                        "studentId": recipient["studentId"],
                        "maskedRecipient": recipient["maskedRecipient"],
                    }
                    for recipient in plan.get("recipients", [])
                ],
            },
            indent=2,
        )
    )


def cmd_approve(args):
    from email_delivery.approval import approve_plan

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    identity_store = _get_identity_store(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    plan_dir = (
        roots.private_root
        / "email"
        / "plans"
        / args.section
        / args.publication
        / args.plan
    )

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
            confirm_reviewed=args.confirm_reviewed,
            snapshot_dir=snapshot_dir,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
        ledger.close()

    print(json.dumps(record.to_dict(), indent=2))


def cmd_execute(args):
    from email_delivery.executor import execute_plan
    from email_delivery.models import TlsMode, TransportConfig
    from email_delivery.transport.fake import FakeTransport
    from email_delivery.transport.smtp import SMTPTransport

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    identity_store = _get_identity_store(roots)
    lifecycle_ledger = _get_lifecycle_ledger(roots, args.section)
    snapshot_dir = _snapshot_dir(roots, args.section, args.publication)
    plan_dir = (
        roots.private_root
        / "email"
        / "plans"
        / args.section
        / args.publication
        / args.plan
    )

    if args.transport == "fake":
        transport = FakeTransport()
        config = TransportConfig(host="localhost", port=0, username="")
    else:
        transport = SMTPTransport()
        tls_value = os.environ.get("ACADGRAD_SMTP_TLS_MODE", "starttls")
        if tls_value not in ("starttls", "implicitTls"):
            print("Error: invalid ACADGRAD_SMTP_TLS_MODE", file=sys.stderr)
            ledger.close()
            sys.exit(2)
        config = TransportConfig(
            host=os.environ.get("ACADGRAD_SMTP_HOST", ""),
            port=int(os.environ.get("ACADGRAD_SMTP_PORT", "0")),
            username=os.environ.get("ACADGRAD_SMTP_USERNAME", ""),
            password=os.environ.get("ACADGRAD_SMTP_PASSWORD", ""),
            tls_mode=TlsMode(tls_value),
            timeout=float(os.environ.get("ACADGRAD_SMTP_TIMEOUT", "30")),
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
            confirm_send=args.confirm_send,
            snapshot_dir=snapshot_dir,
            recovery_root=roots.state_root / "email" / "recovery",
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
        ledger.close()

    print(json.dumps({"outcome": outcome.value}, indent=2))
    if outcome.value != "COMPLETE":
        sys.exit(3)


def cmd_status(args):
    from email_delivery.reconciliation import get_plan_status

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    try:
        status = get_plan_status(args.plan, ledger)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
        ledger.close()
    print(json.dumps(status, indent=2))


def cmd_reconcile(args):
    from email_delivery.reconciliation import reconcile_plan

    roots = _resolve_roots()
    ledger = _get_ledger(roots)
    try:
        events = reconcile_plan(
            args.plan, ledger, actor=args.actor or "system.reconcile"
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
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
            confirm=args.confirm,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    finally:
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
    print(json.dumps({"integrity": "OK"}, indent=2))


def cmd_test(args):
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(WORKSPACE_ROOT / "engine" / "email_delivery" / "tests"),
            "-v",
            "--tb=short",
        ],
        capture_output=False,
    )
    sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        prog="email-delivery", description="C3 email delivery workflow"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    command = sub.add_parser("prepare")
    command.add_argument("--section", required=True)
    command.add_argument("--publication", required=True)
    command.add_argument("--template", required=True)
    command.add_argument("--sender-profile", required=True)

    command = sub.add_parser("inspect")
    command.add_argument("--section", required=True)
    command.add_argument("--publication", required=True)
    command.add_argument("--plan", required=True)

    command = sub.add_parser("approve")
    command.add_argument("--plan", required=True)
    command.add_argument("--preview-hash", required=True)
    command.add_argument("--recipient-count", type=int, required=True)
    command.add_argument("--actor", required=True)
    command.add_argument("--section", required=True)
    command.add_argument("--publication", required=True)
    command.add_argument("--confirm-reviewed", action="store_true")

    command = sub.add_parser("execute")
    command.add_argument("--plan", required=True)
    command.add_argument("--preview-hash", required=True)
    command.add_argument("--section", required=True)
    command.add_argument("--publication", required=True)
    command.add_argument("--actor", default="system")
    command.add_argument("--transport", default="fake", choices=["fake", "smtp"])
    command.add_argument("--confirm-send", action="store_true")

    command = sub.add_parser("status")
    command.add_argument("--plan", required=True)

    command = sub.add_parser("reconcile")
    command.add_argument("--plan", required=True)
    command.add_argument("--actor", default="system.reconcile")

    command = sub.add_parser("resolve-ambiguous")
    command.add_argument("--plan", required=True)
    command.add_argument("--student", required=True)
    command.add_argument("--decision", required=True, choices=["sent", "not-sent"])
    command.add_argument("--actor", required=True)
    command.add_argument("--reason", required=True)
    command.add_argument("--confirm", action="store_true")

    sub.add_parser("ledger-check")
    sub.add_parser("test")

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
