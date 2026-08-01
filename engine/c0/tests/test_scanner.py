from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from c0.scanner import (
    SEVERITY_BLOCK,
    SEVERITY_REVIEW,
    InvalidAllowlistError,
    Scanner,
    glob_match,
    load_allowlist,
)
from c0.util import mask_path


def assemble(*parts: str) -> str:
    """Join string fragments so the assembled value only exists at runtime."""
    return "".join(parts)


def secret_value() -> str:
    return assemble("SuperSecret", "Value123")


def password_line() -> str:
    return assemble("password = ", chr(34), secret_value(), chr(34), "\n")


def env_line() -> str:
    return assemble("PASSWORD", "=", "x", "\n")


def env_example_line() -> str:
    return assemble("PASSWORD", "=", "changeme", "\n")


def private_key_block() -> str:
    return assemble("-----BEGIN ", "PRIVATE KEY-----")


def aws_key() -> str:
    return assemble("AKIA", "ABCDEFGHIJKLMNOP")


def github_token() -> str:
    return assemble("ghp_", "123456789012345678901234567890123456789012")


def mystery_email() -> str:
    return assemble("someone@", "mysterydomain", ".example")


def leak_file_content() -> str:
    return assemble("PASSWORD", "=", "SuperSecret", "Value123", "\n")


def run_scan(args: list[str], cwd: Path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "c0_scan.py"
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def git(args: list[str], cwd: Path):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)


class ScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def scan_content(self, content: str, rel_path: str = "scan-target/file.txt", allowlist=None) -> list:
        scanner = Scanner(allowlist=allowlist)
        return scanner.scan_bytes(rel_path, content.encode("utf-8"))

    def test_secret_assignment_detected(self) -> None:
        findings = self.scan_content(password_line())
        blocked = [f for f in findings if f.rule == "secret-assignment" and f.severity == SEVERITY_BLOCK]
        self.assertEqual(len(blocked), 1)

    def test_private_key_detected(self) -> None:
        findings = self.scan_content(private_key_block() + "\nAAAA\n" + private_key_block() + "\n")
        self.assertTrue(any(f.rule == "private-key-block" for f in findings))

    def test_common_tokens_detected(self) -> None:
        findings = self.scan_content(assemble("token = ", aws_key(), "\n"))
        self.assertTrue(any(f.rule == "aws-access-key" for f in findings))
        findings = self.scan_content(assemble("key=", github_token(), "\n"))
        self.assertTrue(any(f.rule == "github-token" for f in findings))

    def test_email_detected_is_block(self) -> None:
        findings = self.scan_content(assemble("contact: ", mystery_email(), "\n"))
        emails = [f for f in findings if f.rule == "email"]
        self.assertEqual(len(emails), 1)
        self.assertEqual(emails[0].severity, SEVERITY_BLOCK)

    def test_email_in_reserved_domain_not_flagged(self) -> None:
        findings = self.scan_content("student.one@example.test person@example.com\n")
        emails = [f for f in findings if f.rule == "email"]
        self.assertEqual(emails, [])

    def test_chilean_rut_detected(self) -> None:
        findings = self.scan_content("rut: 12.345.678-9\n")
        ruts = [f for f in findings if f.rule == "chilean-rut"]
        self.assertEqual(len(ruts), 1)
        self.assertEqual(ruts[0].severity, SEVERITY_BLOCK)

    def test_masking(self) -> None:
        findings = self.scan_content(password_line())
        masked = [f for f in findings if f.rule == "secret-assignment"][0].masked
        self.assertIsNotNone(masked)
        self.assertNotIn(secret_value(), masked or "")
        self.assertIn("***", masked or "")

    def test_allowlist_suppresses_fixture_dir(self) -> None:
        scanner = Scanner()
        targets = []
        for path in sorted((self.fixtures / "pii").glob("*")):
            if path.is_file():
                rel = "engine/c0/fixtures/synthetic/" + path.relative_to(self.fixtures).as_posix()
                targets.append((rel, path))
        findings = scanner.scan_files(targets)
        blocked = [f for f in findings if f.severity == SEVERITY_BLOCK]
        self.assertEqual(blocked, [])

    def test_without_allowlist_fixture_content_triggers(self) -> None:
        scanner = Scanner(allowlist=[])
        path = self.fixtures / "pii" / "sample-ruts.txt"
        rel = "unlisted/pii/sample-ruts.txt"
        findings = scanner.scan_file(rel, path)
        self.assertTrue(any(f.rule == "chilean-rut" for f in findings))

    def test_env_file_detected(self) -> None:
        scanner = Scanner()
        path = self.tmp / ".env"
        path.write_text(env_line(), encoding="utf-8")
        findings = scanner.scan_file(".env", path)
        self.assertTrue(any(f.rule == "env-file" for f in findings))

    def test_env_example_not_detected(self) -> None:
        scanner = Scanner()
        path = self.tmp / ".env.example"
        path.write_text(env_example_line(), encoding="utf-8")
        findings = scanner.scan_file(".env.example", path)
        self.assertFalse(any(f.rule == "env-file" for f in findings))

    def test_binary_content_emits_review(self) -> None:
        content = ("plain\n" + password_line()) * 200
        content = content + "\x00" + content
        findings = self.scan_content(content)
        self.assertFalse(any(f.rule == "secret-assignment" for f in findings))
        self.assertTrue(
            any(f.rule == "uninspected-binary" and f.severity == SEVERITY_REVIEW for f in findings)
        )

    def test_large_content_emits_review(self) -> None:
        secret_line = password_line()
        content = secret_line * 120000  # well above the 2 MiB content limit
        self.assertGreater(len(content.encode("utf-8")), 2 * 1024 * 1024)
        findings = self.scan_content(content)
        self.assertFalse(any(f.rule == "secret-assignment" for f in findings))
        self.assertTrue(
            any(f.rule == "uninspected-large" and f.severity == SEVERITY_REVIEW for f in findings)
        )

    def test_high_confidence_rule_not_allowlistable(self) -> None:
        allowlist = [{"path": "**/.env", "rules": ["env-file", "secret-assignment"]}]
        scanner = Scanner(allowlist=allowlist)
        findings = scanner.scan_blob("config/.env", env_line().encode("utf-8"))
        self.assertTrue(any(f.rule == "env-file" for f in findings), "env-file must stay active")
        findings = scanner.scan_bytes("x/token.txt", github_token().encode("utf-8"))
        self.assertTrue(any(f.rule == "github-token" for f in findings), "tokens cannot be allow-listed")

    def test_wildcard_allowlist_ignored(self) -> None:
        scanner = Scanner(allowlist=[{"path": "**", "rules": ["*"]}])
        content = password_line().encode("utf-8")
        findings = scanner.scan_bytes("x/secret.txt", content)
        self.assertTrue(any(f.severity == SEVERITY_BLOCK for f in findings))

    def test_allowlist_rejects_wildcard_rule(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write('{"entries": [{"path": "x/**", "rules": ["*"]}]}')
            path = Path(handle.name)
        try:
            with self.assertRaises(InvalidAllowlistError):
                load_allowlist(path)
        finally:
            path.unlink()

    def test_allowlist_rejects_high_confidence_rule(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write('{"entries": [{"path": "x/**", "rules": ["github-token"]}]}')
            path = Path(handle.name)
        try:
            with self.assertRaises(InvalidAllowlistError):
                load_allowlist(path)
        finally:
            path.unlink()

    def test_path_rules(self) -> None:
        scanner = Scanner()
        for rel in (
            "evaluations/CUR0001-001/EV1/form-A/submissions/x.zip",
            "evaluations/CUR0001-001/EV1/form-A/results/11.111.111-1.md",
            "evaluations/CUR0001-001/students.json",
            "runtime/state/email-ledger/ledger.json",
            "exports/email/preview/out.html",
        ):
            findings = scanner.scan_path(rel, Path(rel))
            self.assertTrue(any(f.severity == SEVERITY_BLOCK for f in findings), f"no block for {rel}")

    def test_path_pii_masked(self) -> None:
        masked = mask_path("evaluations/CUR0001-001/students/11.111.111-1/entregas/x.psc")
        self.assertNotIn("11.111.111-1", masked)
        masked_email = mask_path("exports/students/someone@mysterydomain.example.md")
        self.assertNotIn("someone@mysterydomain.example", masked_email)

    def test_glob_match(self) -> None:
        self.assertTrue(glob_match("engine/c0/fixtures/synthetic/**", "engine/c0/fixtures/synthetic/pii/sample.env"))
        self.assertTrue(glob_match("**/students.json", "evaluations/x/students.json"))
        self.assertTrue(glob_match("onboarding/**", "onboarding/data/01-roster/students.csv"))
        self.assertFalse(glob_match("engine/c0/fixtures/synthetic/**", "evaluations/x/students.json"))
        self.assertFalse(glob_match("docs/**", "evaluations/x/students.json"))


class StagedScanTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(["init", "-q", "-b", "main"], self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, content: str) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_staged_secret_blocks_even_with_clean_worktree(self) -> None:
        self.write("notes/data.txt", leak_file_content())
        git(["add", "-A"], self.repo)
        self.write("notes/data.txt", "# cleaned up, secret removed\n")

        staged = run_scan(["--staged", "--workspace", str(self.repo)], self.repo)
        self.assertEqual(staged.returncode, 2, staged.stdout + staged.stderr)
        self.assertIn("BLOCK=1", staged.stdout)

        worktree = run_scan(["--path", "notes/data.txt", "--workspace", str(self.repo)], self.repo)
        self.assertEqual(worktree.returncode, 0, worktree.stdout + worktree.stderr)
        self.assertIn("BLOCK=0", worktree.stdout)

    def test_staged_blob_respects_allowlist(self) -> None:
        self.write("engine/c0/fixtures/synthetic/pii/sample-ruts.txt", "12.345.678-9\n")
        git(["add", "-A"], self.repo)
        staged = run_scan(["--staged", "--workspace", str(self.repo)], self.repo)
        self.assertEqual(staged.returncode, 0, staged.stdout + staged.stderr)
        self.assertIn("BLOCK=0", staged.stdout)


if __name__ == "__main__":
    unittest.main()
