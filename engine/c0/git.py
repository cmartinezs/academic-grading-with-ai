"""Git helpers for workspace scanning."""

from __future__ import annotations

from pathlib import Path

from c0.paths import run_git_result


def tracked_files(repo: Path) -> list[Path]:
    result = run_git_result(repo, "ls-files")
    if result is None:
        return []
    return [repo / line for line in result.stdout.splitlines() if line.strip()]


def staged_files(repo: Path) -> list[Path]:
    result = run_git_result(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR")
    if result is None:
        return []
    return [repo / line for line in result.stdout.splitlines() if line.strip()]


def is_git_repo(repo: Path) -> bool:
    result = run_git_result(repo, "rev-parse", "--is-inside-work-tree")
    return result is not None and result.returncode == 0
