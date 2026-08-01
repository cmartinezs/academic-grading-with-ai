from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from c0.scanner import (
    SEVERITY_BLOCK,
    SEVERITY_REVIEW,
    Scanner,
    glob_match,
)


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
        findings = self.scan_content('password = "SuperSecretValue123"')
        blocked = [f for f in findings if f.rule == "secret-assignment" and f.severity == SEVERITY_BLOCK]
        self.assertEqual(len(blocked), 1)

    def test_private_key_detected(self) -> None:
        findings = self.scan_content("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----")
        self.assertTrue(any(f.rule == "private-key-block" for f in findings))

    def test_common_tokens_detected(self) -> None:
        findings = self.scan_content("token = AKIAABCDEFGHIJKLMNOP\n")
        self.assertTrue(any(f.rule == "aws-access-key" for f in findings))
        findings = self.scan_content("key=ghp_123456789012345678901234567890123456789012\n")
        self.assertTrue(any(f.rule == "github-token" for f in findings))

    def test_email_detected_outside_reserved_domains(self) -> None:
        findings = self.scan_content("contact: someone@mysterydomain.example\n")
        emails = [f for f in findings if f.rule == "email" and f.severity == SEVERITY_REVIEW]
        self.assertEqual(len(emails), 1)

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
        findings = self.scan_content('password = "SuperSecretValue123"')
        masked = [f for f in findings if f.rule == "secret-assignment"][0].masked
        self.assertIsNotNone(masked)
        self.assertNotIn("SuperSecretValue123", masked or "")
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
        path.write_text("PASSWORD=x\n", encoding="utf-8")
        findings = scanner.scan_file(".env", path)
        self.assertTrue(any(f.rule == "env-file" for f in findings))

    def test_env_example_not_detected(self) -> None:
        scanner = Scanner()
        path = self.tmp / ".env.example"
        path.write_text("PASSWORD=changeme\n", encoding="utf-8")
        findings = scanner.scan_file(".env.example", path)
        self.assertFalse(any(f.rule == "env-file" for f in findings))

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

    def test_glob_match(self) -> None:
        self.assertTrue(glob_match("engine/c0/fixtures/synthetic/**", "engine/c0/fixtures/synthetic/pii/sample.env"))
        self.assertTrue(glob_match("**/students.json", "evaluations/x/students.json"))
        self.assertTrue(glob_match("onboarding/**", "onboarding/data/01-roster/students.csv"))
        self.assertFalse(glob_match("engine/c0/fixtures/synthetic/**", "evaluations/x/students.json"))
        self.assertFalse(glob_match("docs/**", "evaluations/x/students.json"))


if __name__ == "__main__":
    unittest.main()
