from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from c0.status import FAIL, PASS, WARN, run_security_checks


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def git(args, cwd: Path):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


class StatusTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir(parents=True)
        self.private = self.tmp / "runtime-data" / "private"
        self.state = self.tmp / "runtime-data" / "state"
        git(["init", "-q"], self.workspace)
        env = {
            "ACADGRAD_PRIVATE_ROOT": str(self.private),
            "ACADGRAD_STATE_ROOT": str(self.state),
            "ACADGRAD_PUBLICATIONS_ROOT": str(self.tmp / "runtime-data" / "publications"),
            "ACADGRAD_TEMP_ROOT": str(self.tmp / "runtime-data" / "tmp"),
        }
        self.env = env

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def report(self):
        return run_security_checks(self.workspace, env=self.env)

    def test_pass_state_for_empty_workspace(self) -> None:
        self.private.mkdir(parents=True, exist_ok=True)
        self.private.chmod(0o700)
        self.state.mkdir(parents=True, exist_ok=True)
        self.state.chmod(0o700)
        write(self.workspace / "README.md", "# workspace\n")
        git(["add", "-A"], self.workspace)
        report = self.report()
        self.assertEqual(report.worst_state(), PASS)

    def test_fail_on_unsafe_private_root(self) -> None:
        env = dict(self.env)
        env["ACADGRAD_PRIVATE_ROOT"] = str(self.workspace / "private-data")
        report = run_security_checks(self.workspace, env=env)
        self.assertEqual(report.worst_state(), FAIL)
        self.assertTrue(any(f.check == "config-resolution" for f in report.findings))

    def test_fail_on_versioned_secret(self) -> None:
        write(self.workspace / "leak.env", "PASSWORD=SuperSecretValue123\n")
        git(["add", "-A"], self.workspace)
        report = self.report()
        self.assertEqual(report.worst_state(), FAIL)
        self.assertTrue(any(f.check == "versionable-private-data" for f in report.findings))

    def test_warn_on_private_root_missing(self) -> None:
        report = self.report()
        self.assertTrue(any(f.check == "private-root" and f.state == WARN for f in report.findings))

    def test_warn_on_pending_migration(self) -> None:
        section = self.workspace / "evaluations" / "CUR0001-001"
        write(section / "config.json", json.dumps({"course": {"name": "CUR0001-001"}}))
        write(
            section / "students.json",
            json.dumps({"students": [{"rut": "11.111.111-1", "fullName": "Fictional"}]}),
        )
        write(section / "EV1" / "form-A" / "submissions" / "x" / "work.psc", "Algoritmo\n")
        git(["add", "-A"], self.workspace)
        report = self.report()
        self.assertTrue(any(f.check == "pending-migration" and f.state == WARN for f in report.findings))

    def test_warn_on_permissions(self) -> None:
        self.private.mkdir(parents=True, exist_ok=True)
        self.private.chmod(0o755)
        report = self.report()
        self.assertTrue(any(f.check == "permissions" and f.state == WARN for f in report.findings))

    def test_status_is_read_only(self) -> None:
        before = {path for path in self.workspace.rglob("*") if path.is_file()}
        self.report()
        after = {path for path in self.workspace.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_fail_finds_state(self) -> None:
        env = dict(self.env)
        env["ACADGRAD_PRIVATE_ROOT"] = str(self.workspace / "unsafe")
        report = run_security_checks(self.workspace, env=env)
        self.assertEqual(report.worst_state(), FAIL)


if __name__ == "__main__":
    unittest.main()
