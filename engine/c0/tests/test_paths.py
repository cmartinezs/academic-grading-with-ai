from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from c0.paths import (
    ENV_PRIVATE_ROOT,
    ENV_STATE_ROOT,
    InvalidRuntimeConfigError,
    UnsafeDataRootError,
    ZoneClassification,
    classify_zone,
    default_data_base,
    resolve_runtime_roots,
)


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


def make_git_repo(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    result = git(["init", "-q"], directory)
    if result.returncode != 0:
        raise RuntimeError(f"git init failed: {result.stderr}")
    return directory


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class PathResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_default_base_uses_xdg_data_home(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        xdg = self.tmp / "xdg"
        env = {"XDG_DATA_HOME": str(xdg)}
        cfg = resolve_runtime_roots(workspace, env=env)
        expected = (xdg / "academic-grading-with-ai").resolve()
        self.assertEqual(cfg.private_root, expected / "private")
        self.assertEqual(cfg.state_root, expected / "state")
        self.assertEqual(cfg.publications_root, expected / "publications")
        self.assertEqual(cfg.temp_root, expected / "tmp")
        self.assertEqual(cfg.source, "default")

    def test_default_data_base_falls_back_to_home(self) -> None:
        base = default_data_base({"XDG_DATA_HOME": ""})
        self.assertTrue(str(base).startswith(str(Path.home())))

    def test_private_root_outside_repo_is_safe(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        outside = self.tmp / "outside-data" / "private"
        env = {ENV_PRIVATE_ROOT: str(outside)}
        cfg = resolve_runtime_roots(workspace, env=env)
        self.assertEqual(cfg.private_root, outside.resolve())
        self.assertEqual(cfg.source, "env")

    def test_unsafe_private_root_inside_repo_fails_closed(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        unsafe = workspace / "private-data"
        env = {ENV_PRIVATE_ROOT: str(unsafe)}
        with self.assertRaises(UnsafeDataRootError):
            resolve_runtime_roots(workspace, env=env)

    def test_fallback_local_ignored_is_safe(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        write(workspace / ".gitignore", "runtime/\n")
        private = workspace / "runtime" / "private"
        env = {ENV_PRIVATE_ROOT: str(private)}
        cfg = resolve_runtime_roots(workspace, env=env)
        self.assertEqual(cfg.private_root, private.resolve())

    def test_tracked_zone_is_unsafe_even_if_ignored(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        write(workspace / ".gitignore", "runtime/\n")
        tracked = write(workspace / "runtime" / "private" / "tracked.txt", "x")
        git(["add", "-f", str(tracked)], workspace)
        env = {ENV_PRIVATE_ROOT: str(tracked.parent)}
        with self.assertRaises(UnsafeDataRootError):
            resolve_runtime_roots(workspace, env=env)

    def test_paths_with_spaces_and_unicode(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        outside = self.tmp / "dir with spaces-ñó" / "priv ado"
        env = {ENV_PRIVATE_ROOT: str(outside)}
        cfg = resolve_runtime_roots(workspace, env=env)
        self.assertEqual(cfg.private_root, outside.resolve())

    def test_relative_root_resolves_under_workspace(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        write(workspace / ".gitignore", "runtime/\n")
        env = {ENV_PRIVATE_ROOT: "runtime/private"}
        cfg = resolve_runtime_roots(workspace, env=env)
        self.assertEqual(cfg.private_root, (workspace / "runtime" / "private").resolve())

    def test_config_file_roots(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        outside = self.tmp / "cfg-data"
        write(
            workspace / "runtime.json",
            '{"private": "%s/private", "state": "%s/state"}\n' % (outside, outside),
        )
        cfg = resolve_runtime_roots(workspace, env={})
        self.assertEqual(cfg.private_root, (outside / "private").resolve())
        self.assertEqual(cfg.state_root, (outside / "state").resolve())
        self.assertEqual(cfg.source, "config-file")

    def test_env_overrides_config_file(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        outside = self.tmp / "cfg-data"
        write(workspace / "runtime.json", '{"private": "%s/private"}\n' % outside)
        env_override = self.tmp / "env-data"
        cfg = resolve_runtime_roots(workspace, env={ENV_PRIVATE_ROOT: str(env_override)})
        self.assertEqual(cfg.private_root, env_override.resolve())

    def test_invalid_config_file_fails(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        write(workspace / "runtime.json", "{not json")
        with self.assertRaises(Exception):
            resolve_runtime_roots(workspace, env={})

    def test_classify_zone_outside_repo(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        outside = self.tmp / "outside-data"
        self.assertEqual(classify_zone(outside, workspace), ZoneClassification.SAFE_OUTSIDE_REPO)

    def test_classify_zone_ignored(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        write(workspace / ".gitignore", "runtime/\n")
        self.assertEqual(
            classify_zone(workspace / "runtime" / "private", workspace),
            ZoneClassification.SAFE_IGNORED,
        )

    def test_classify_zone_not_ignored(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        self.assertEqual(
            classify_zone(workspace / "nope" / "private", workspace),
            ZoneClassification.UNSAFE_NOT_IGNORED,
        )

    def test_classify_zone_tracked(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        tracked = write(workspace / "nope" / "private" / "x.txt", "x")
        git(["add", "-f", str(tracked)], workspace)
        self.assertEqual(
            classify_zone(workspace / "nope" / "private", workspace),
            ZoneClassification.UNSAFE_TRACKED,
        )

    def test_root_inside_second_git_repo_is_unsafe(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        other = make_git_repo(self.tmp / "other-repo")
        write(other / "README.md", "# other\n")
        git(["add", "-A"], other)
        env = {ENV_PRIVATE_ROOT: str(other / "private-data")}
        with self.assertRaises(UnsafeDataRootError):
            resolve_runtime_roots(workspace, env=env)

    def test_second_repo_ignored_root_is_safe(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        other = make_git_repo(self.tmp / "other-repo")
        write(other / ".gitignore", "private-data/\n")
        env = {ENV_PRIVATE_ROOT: str(other / "private-data")}
        cfg = resolve_runtime_roots(workspace, env=env)
        self.assertEqual(cfg.private_root, (other / "private-data").resolve())

    def test_second_repo_tracked_root_is_unsafe(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        other = make_git_repo(self.tmp / "other-repo")
        write(other / ".gitignore", "private-data/\n")
        tracked = write(other / "private-data" / "x.txt", "x")
        git(["add", "-f", str(tracked)], other)
        env = {ENV_PRIVATE_ROOT: str(other / "private-data")}
        with self.assertRaises(UnsafeDataRootError):
            resolve_runtime_roots(workspace, env=env)

    def test_equal_roots_rejected(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        env = {
            ENV_PRIVATE_ROOT: str(self.tmp / "data"),
            ENV_STATE_ROOT: str(self.tmp / "data"),
        }
        with self.assertRaises(InvalidRuntimeConfigError):
            resolve_runtime_roots(workspace, env=env)

    def test_nested_roots_rejected(self) -> None:
        workspace = make_git_repo(self.tmp / "workspace")
        env = {
            ENV_PRIVATE_ROOT: str(self.tmp / "data"),
            ENV_STATE_ROOT: str(self.tmp / "data" / "state"),
        }
        with self.assertRaises(InvalidRuntimeConfigError):
            resolve_runtime_roots(workspace, env=env)


if __name__ == "__main__":
    unittest.main()
