"""Centralized resolution of runtime data roots (C0.1).

Separates four zones:

- private data (roster, submissions, evidence, results);
- operational state (identity, locks, migrations, diagnostics);
- publication artifacts (reserved for C1, not implemented);
- temporary build data.

All roots are absolute paths. A root located inside a Git worktree must be fully
ignored by Git; otherwise resolution fails closed with ``UnsafeDataRootError``.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_DIR_NAME = "academic-grading-with-ai"
RUNTIME_CONFIG_FILENAME = "runtime.json"

ENV_PRIVATE_ROOT = "ACADGRAD_PRIVATE_ROOT"
ENV_STATE_ROOT = "ACADGRAD_STATE_ROOT"
ENV_PUBLICATIONS_ROOT = "ACADGRAD_PUBLICATIONS_ROOT"
ENV_TEMP_ROOT = "ACADGRAD_TEMP_ROOT"
ENV_RUNTIME_CONFIG = "ACADGRAD_RUNTIME_CONFIG"

ZONES = (
    ("private", ENV_PRIVATE_ROOT, "private"),
    ("state", ENV_STATE_ROOT, "state"),
    ("publications", ENV_PUBLICATIONS_ROOT, "publications"),
    ("temp", ENV_TEMP_ROOT, "tmp"),
)


class RuntimeConfigError(Exception):
    """Base error for runtime data configuration problems."""


class UnsafeDataRootError(RuntimeConfigError):
    """A configured data root is inside a version-controlled area and is not safely ignored."""


class InvalidRuntimeConfigError(RuntimeConfigError):
    """The runtime configuration file is malformed."""


class ZoneClassification(Enum):
    SAFE_OUTSIDE_REPO = "outside-repo"
    SAFE_IGNORED = "ignored"
    UNSAFE_TRACKED = "tracked"
    UNSAFE_NOT_IGNORED = "not-ignored"
    UNSAFE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuntimeConfig:
    private_root: Path
    state_root: Path
    publications_root: Path
    temp_root: Path
    source: str = "default"

    def as_dict(self) -> dict[str, str]:
        return {
            "privateRoot": str(self.private_root),
            "stateRoot": str(self.state_root),
            "publicationsRoot": str(self.publications_root),
            "tempRoot": str(self.temp_root),
            "source": self.source,
        }

    def ensure_dirs(self) -> None:
        """Create the configured roots with restrictive permissions (not read-only)."""
        for root in (self.private_root, self.state_root, self.publications_root, self.temp_root):
            root.mkdir(parents=True, exist_ok=True)
            try:
                root.chmod(0o700)
            except OSError:
                pass
        (self.state_root / "identity").mkdir(parents=True, exist_ok=True)
        (self.state_root / "locks").mkdir(parents=True, exist_ok=True)
        (self.state_root / "migrations").mkdir(parents=True, exist_ok=True)
        (self.state_root / "diagnostics").mkdir(parents=True, exist_ok=True)


def run_git_result(repo_root: Path, *args: str) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_repo_root(path: Path) -> Optional[Path]:
    result = run_git_result(path, "rev-parse", "--show-toplevel")
    if result is None or result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root).resolve() if root else None


def git_worktree_present(path: Path) -> bool:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return True
    return False


def classify_zone(path: Path, workspace_root: Path) -> ZoneClassification:
    """Classify whether ``path`` is a safe location for private data."""
    path = Path(path).expanduser().resolve()
    repo = git_repo_root(workspace_root)
    if repo is None:
        if git_worktree_present(workspace_root):
            return ZoneClassification.UNSAFE_UNKNOWN
        return ZoneClassification.SAFE_OUTSIDE_REPO
    try:
        path.relative_to(repo)
    except ValueError:
        return ZoneClassification.SAFE_OUTSIDE_REPO

    if path.exists():
        result = run_git_result(repo, "ls-files", "--", str(path))
        if result is not None and result.stdout.strip():
            return ZoneClassification.UNSAFE_TRACKED

    check = run_git_result(repo, "check-ignore", "-q", "--", str(path))
    if check is None:
        return ZoneClassification.UNSAFE_UNKNOWN
    if check.returncode == 0:
        return ZoneClassification.SAFE_IGNORED
    return ZoneClassification.UNSAFE_NOT_IGNORED


def default_data_base(env: Mapping[str, str]) -> Path:
    xdg = (env.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        base = Path(xdg).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return base / DEFAULT_DIR_NAME


def load_runtime_config(workspace_root: Path, env: Mapping[str, str]) -> dict:
    explicit = (env.get(ENV_RUNTIME_CONFIG) or "").strip()
    config_path = Path(explicit).expanduser() if explicit else Path(workspace_root) / RUNTIME_CONFIG_FILENAME
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise InvalidRuntimeConfigError(f"Invalid runtime config file: {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidRuntimeConfigError(f"Runtime config file must be a JSON object: {config_path}")
    return payload


def _resolve_zone(
    name: str,
    env_var: str,
    default_subdir: str,
    workspace_root: Path,
    env: Mapping[str, str],
    config: dict,
) -> tuple[Path, str]:
    candidate: Optional[str] = None
    source = "default"
    if (env.get(env_var) or "").strip():
        candidate = env.get(env_var)
        source = "env"
    elif (config.get(name) or "").strip():
        candidate = str(config.get(name))
        source = "config-file"

    if candidate is None:
        candidate = str(default_data_base(env) / default_subdir)

    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = Path(workspace_root) / path
    return path.resolve(), source


def resolve_runtime_roots(
    workspace_root: Path,
    env: Optional[Mapping[str, str]] = None,
) -> RuntimeConfig:
    """Resolve and validate the four runtime data roots (fail-closed)."""
    env = dict(os.environ) if env is None else dict(env)
    workspace_root = Path(workspace_root).resolve()
    config = load_runtime_config(workspace_root, env)

    resolved: dict[str, Path] = {}
    sources: list[str] = []
    for name, env_var, default_subdir in ZONES:
        path, source = _resolve_zone(name, env_var, default_subdir, workspace_root, env, config)
        resolved[name] = path
        sources.append(source)

    for name, path in resolved.items():
        classification = classify_zone(path, workspace_root)
        if classification in (
            ZoneClassification.UNSAFE_TRACKED,
            ZoneClassification.UNSAFE_NOT_IGNORED,
            ZoneClassification.UNSAFE_UNKNOWN,
        ):
            raise UnsafeDataRootError(_unsafe_message(name, path, classification))

    source = "config-file" if "config-file" in sources else ("env" if "env" in sources else "default")
    return RuntimeConfig(
        private_root=resolved["private"],
        state_root=resolved["state"],
        publications_root=resolved["publications"],
        temp_root=resolved["temp"],
        source=source,
    )


def _unsafe_message(name: str, path: Path, classification: ZoneClassification) -> str:
    reason = {
        ZoneClassification.UNSAFE_TRACKED: "contains files tracked by Git",
        ZoneClassification.UNSAFE_NOT_IGNORED: "is inside a Git worktree and is not fully ignored",
        ZoneClassification.UNSAFE_UNKNOWN: "cannot be verified as ignored by Git",
    }[classification]
    return (
        f"Unsafe data root for zone '{name}': {path} {reason}. "
        f"Move it outside the repository or configure a Git-ignored location."
    )
