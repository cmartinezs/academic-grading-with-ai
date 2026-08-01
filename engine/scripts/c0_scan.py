#!/usr/bin/env python3
"""c0-scan — PII and secret scanner.

Scans tracked files, staged files and/or explicit paths. Never prints sensitive
values in full; findings are masked. Exit codes: 2 on BLOCK findings, 1 when only
REVIEW findings exist and ``--strict`` is set, 0 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))

from c0.scanner import Scanner, SEVERITY_BLOCK, SEVERITY_REVIEW  # noqa: E402


def git_output(repo: Path, *args: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def tracked_files(repo: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for line in git_output(repo, "ls-files"):
        path = repo / line
        if path.is_file():
            files.append((line, path))
    return files


def staged_files(repo: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for line in git_output(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR"):
        path = repo / line
        if path.is_file():
            files.append((line, path))
    return files


def path_files(repo: Path, directory: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    skipped_dirs = {".git", "node_modules", "__pycache__"}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skipped_dirs for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        files.append((rel, path))
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="PII and secret scanner (C0.5).")
    parser.add_argument("--tracked", action="store_true", help="Scan files tracked by Git (default when no target given).")
    parser.add_argument("--staged", action="store_true", help="Scan files staged for commit.")
    parser.add_argument("--path", dest="paths", action="append", help="Scan a directory or file (repeatable).")
    parser.add_argument("--no-allowlist", action="store_true", help="Disable the allow-list.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero (1) on REVIEW findings too.")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    parser.add_argument("--workspace", help="Workspace root (defaults to repository root).")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve() if args.workspace else ROOT
    targets: list[tuple[str, Path]] = []

    if args.staged:
        targets.extend(staged_files(workspace))
    if args.paths:
        for raw in args.paths:
            path = Path(raw)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            if path.is_dir():
                targets.extend(path_files(workspace, path))
            elif path.is_file():
                rel = path.relative_to(workspace).as_posix() if path.is_relative_to(workspace) else path.as_posix()
                targets.append((rel, path))
    if args.tracked or (not args.staged and not args.paths):
        targets.extend(tracked_files(workspace))

    scanner = Scanner(allowlist=[] if args.no_allowlist else None)
    findings = scanner.scan_files(targets)

    block_count = sum(1 for finding in findings if finding.severity == SEVERITY_BLOCK)
    review_count = sum(1 for finding in findings if finding.severity == SEVERITY_REVIEW)

    if args.json:
        print(
            json.dumps(
                {
                    "workspace": str(workspace),
                    "scanned": len(targets),
                    "block": block_count,
                    "review": review_count,
                    "findings": [finding.to_dict() for finding in findings],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"# PII/secret scan")
        print(f"Workspace: {workspace}")
        print(f"Scanned: {len(targets)} files | BLOCK={block_count} REVIEW={review_count}")
        for finding in findings:
            detail = f" (masked: {finding.masked})" if finding.masked else ""
            print(f"[{finding.severity}] {finding.path} ({finding.rule}): {finding.message}{detail}")
        if block_count:
            print("Scan FAILED: BLOCK findings present.")
        elif review_count and args.strict:
            print("Scan FAILED: REVIEW findings present with --strict.")

    if block_count:
        return 2
    if review_count and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
