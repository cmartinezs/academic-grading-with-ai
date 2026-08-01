from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from c0.identity import IdentityStore
from c0.locking import FileLock, LockTimeoutError
from c0.migration import (
    MIGRATION_NOTES_FILENAME,
    MANIFEST_FILENAME,
    Migrator,
    STATUS_MIGRATED,
    STATUS_PARTIAL,
    STATUS_ROLLED_BACK,
    detect_sections,
)
from c0.paths import RuntimeConfig


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def build_legacy_section(workspace: Path, code: str = "CUR0001-001") -> Path:
    section = workspace / "evaluations" / code
    write(
        section / "config.json",
        json.dumps({"course": {"name": code, "title": "Synthetic course"}}),
    )
    roster = [
        {
            "order": 1,
            "rut": "11.111.111-1",
            "names": "Fictional",
            "lastName": "Student",
            "fullName": "Fictional Student",
        },
        {
            "order": 2,
            "rut": "22.222.222-2",
            "names": "Another",
            "lastName": "Student",
            "fullName": "Another Student",
        },
    ]
    write(section / "students.json", json.dumps({"students": roster}, indent=2))
    write(section / "EV1" / "students.json", json.dumps({"students": roster}, indent=2))
    write(section / "EV1" / "assignments.json", json.dumps({"assignments": []}))
    write(section / "EV1" / "form-A" / "submissions" / "31001001" / "work.psc", "Algoritmo prueba\n")
    write(section / "EV1" / "form-A" / "results" / "11.111.111-1.md", "# Resultado\nNota: 6.0\n")
    write(section / "EV1" / "form-A" / "results" / "22.222.222-2.md", "# Resultado\nNota: 5.0\n")
    write(section / "grades.json", json.dumps({"grades": []}))
    return section


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.workspace = self.tmp / "workspace"
        self.private = self.tmp / "runtime-data" / "private"
        self.state = self.tmp / "runtime-data" / "state"
        self.runtime = RuntimeConfig(
            private_root=self.private,
            state_root=self.state,
            publications_root=self.tmp / "runtime-data" / "publications",
            temp_root=self.tmp / "runtime-data" / "tmp",
        )
        self.identity_dir = self.state / "identity"
        self.identity_store = IdentityStore(self.identity_dir)
        self.migrator = Migrator(self.workspace, self.runtime, self.identity_store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_detects_sections(self) -> None:
        build_legacy_section(self.workspace)
        codes = [path.name for path in detect_sections(self.workspace)]
        self.assertIn("CUR0001-001", codes)

    def test_dry_run_plan_does_not_write(self) -> None:
        build_legacy_section(self.workspace)
        plan = self.migrator.build_plan()
        self.assertTrue(plan.dry_run)
        self.assertEqual(plan.sections[0].status, "pending")
        self.assertGreater(len(plan.sections[0].items), 0)
        self.assertFalse(self.private.exists())
        self.assertFalse(self.identity_dir.exists())

    def test_apply_migrates_and_keeps_origin(self) -> None:
        section = build_legacy_section(self.workspace)
        plan = self.migrator.build_plan(dry_run=False)
        report = self.migrator.apply(plan)
        self.assertEqual(report.applied, ["CUR0001-001"])

        origin_roster = section / "students.json"
        self.assertTrue(origin_roster.exists(), "origin must not be deleted")

        private_roster = self.private / "sections" / "CUR0001-001" / "roster" / "students.json"
        self.assertTrue(private_roster.exists())
        payload = json.loads(private_roster.read_text(encoding="utf-8"))
        self.assertTrue(all(row.get("studentId", "").startswith("stu_") for row in payload["students"]))
        self.assertEqual(payload["students"][0]["externalIdentifiers"]["rut"], "11.111.111-1")

        results = list((self.private / "sections" / "CUR0001-001" / "results").rglob("*.md"))
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.stem.startswith("stu_") for result in results))

        submissions = list((self.private / "sections" / "CUR0001-001" / "submissions").rglob("*"))
        self.assertTrue(any(path.name == "work.psc" for path in submissions))

    def test_apply_is_idempotent(self) -> None:
        build_legacy_section(self.workspace)
        first = self.migrator.apply(self.migrator.build_plan(dry_run=False))
        self.assertEqual(first.applied, ["CUR0001-001"])
        second = self.migrator.apply(self.migrator.build_plan(dry_run=False))
        self.assertEqual(second.applied, [])
        self.assertEqual(second.skipped, ["CUR0001-001"])
        self.assertEqual(self.identity_store.count(), 2)

    def test_partial_migration_detected(self) -> None:
        section = build_legacy_section(self.workspace)
        self.migrator.apply(self.migrator.build_plan(dry_run=False))
        target = self.private / "sections" / "CUR0001-001" / "results" / "form-A"
        result = next(target.glob("*.md"))
        result.unlink()
        plan = self.migrator.build_plan()
        self.assertEqual(plan.sections[0].status, STATUS_PARTIAL)
        # re-apply completes it
        report = self.migrator.apply(plan)
        self.assertEqual(report.applied, ["CUR0001-001"])
        self.assertTrue(result.exists())

    def test_rollback_removes_copied_files(self) -> None:
        section = build_legacy_section(self.workspace)
        self.migrator.apply(self.migrator.build_plan(dry_run=False))
        report = self.migrator.rollback("CUR0001-001")
        self.assertEqual(report.errors, [])
        self.assertGreater(len(report.removed), 0)
        self.assertTrue((section / "students.json").exists())  # origin kept
        self.assertFalse((self.private / "sections" / "CUR0001-001" / "roster" / "students.json").exists())
        ledger = json.loads((self.state / "migrations" / "CUR0001-001.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["status"], STATUS_ROLLED_BACK)
        plan = self.migrator.build_plan()
        self.assertEqual(plan.sections[0].status, STATUS_ROLLED_BACK)

    def test_rollback_resists_modified_targets(self) -> None:
        build_legacy_section(self.workspace)
        self.migrator.apply(self.migrator.build_plan(dry_run=False))
        target = self.private / "sections" / "CUR0001-001" / "results" / "form-A"
        result = next(target.glob("*.md"))
        write(result, "# tampered\n")
        report = self.migrator.rollback("CUR0001-001")
        self.assertTrue(any("modified" in error for error in report.errors))
        self.assertTrue(result.exists())

    def test_ledger_has_no_pii(self) -> None:
        build_legacy_section(self.workspace)
        self.migrator.apply(self.migrator.build_plan(dry_run=False))
        ledger_text = (self.state / "migrations" / "CUR0001-001.json").read_text(encoding="utf-8")
        self.assertNotIn("11.111.111", ledger_text)
        self.assertNotIn("Fictional", ledger_text)
        self.assertIn("status", ledger_text)

    def test_migration_notes_created(self) -> None:
        build_legacy_section(self.workspace)
        self.migrator.apply(self.migrator.build_plan(dry_run=False))
        notes = self.private / "sections" / "CUR0001-001" / MIGRATION_NOTES_FILENAME
        self.assertTrue(notes.exists())
        self.assertIn("were NOT deleted", notes.read_text(encoding="utf-8"))

    def test_manifest_present(self) -> None:
        build_legacy_section(self.workspace)
        self.migrator.apply(self.migrator.build_plan(dry_run=False))
        manifest = self.private / "sections" / "CUR0001-001" / MANIFEST_FILENAME
        self.assertTrue(manifest.exists())
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(payload["sectionCode"], "CUR0001-001")


class LockingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.lock_path = self.tmp / "locks" / "migrate-x.lock"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_lock_acquire_release(self) -> None:
        with FileLock(self.lock_path):
            self.assertTrue(self.lock_path.exists())
        self.assertFalse(self.lock_path.exists())

    def test_second_lock_times_out(self) -> None:
        with FileLock(self.lock_path, timeout=1.0):
            with self.assertRaises(LockTimeoutError):
                with FileLock(self.lock_path, timeout=0.2, poll_interval=0.05):
                    pass


if __name__ == "__main__":
    unittest.main()
