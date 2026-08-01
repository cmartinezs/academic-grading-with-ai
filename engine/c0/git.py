"""Git helpers for workspace scanning."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

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


def blob_content(repo: Path, rel_path: str) -> Optional[bytes]:
    """Return the exact blob stored in the Git index for ``rel_path``.

    Reads from the index (``:<path>``), not from the working tree, so a staged file
    is scanned with the content that will actually be committed.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", ":" + rel_path],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def is_git_repo(repo: Path) -> bool:
    result = run_git_result(repo, "rev-parse", "--is-inside-work-tree")
    return result is not None and result.returncode == 0
