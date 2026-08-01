from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

from c0.identity import IdentityStore
from c0.migration import STATUS_MIGRATED, Migrator
from c0.paths import RuntimeConfig


def worker_identity(identity_dir: str, worker: int, count: int) -> str:
    store = IdentityStore(Path(identity_dir))
    entries = [
        {"external": {"rut": f"{worker:02d}{index:08d}-1"}, "display_name": f"Worker {worker} {index}"}
        for index in range(count)
    ]
    store.ensure_many(entries)
    return identity_dir


def worker_migrate(workspace: str, private: str, state: str, section_code: str) -> str:
    runtime = RuntimeConfig(
        private_root=Path(private),
        state_root=Path(state),
        publications_root=Path(state) / "publications",
        temp_root=Path(state) / "tmp",
    )
    identity_store = IdentityStore(Path(state) / "identity")
    migrator = Migrator(Path(workspace), runtime, identity_store)
    plan = migrator.build_plan([section_code], dry_run=False)
    report = migrator.apply(plan)
    return ",".join(report.applied)


def _worker_entry(fn, args, queue) -> None:
    queue.put(fn(*args))


def _run_worker(fn, *args):
    # helper to spawn a process-safe worker returning its result
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    process = ctx.Process(target=_worker_entry, args=(fn, args, queue))
    process.start()
    process.join(120)
    if process.is_alive():
        process.terminate()
        raise AssertionError("concurrent worker timed out")
    return queue.get()


class ConcurrentIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.identity_dir = self.tmp / "state" / "identity"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_concurrent_ensure_many_no_lost_identities(self) -> None:
        workers = 4
        per_worker = 20
        processes = []
        for worker in range(workers):
            processes.append(_run_worker(worker_identity, str(self.identity_dir), worker, per_worker))
        self.assertEqual(len(processes), workers)
        final = IdentityStore(self.identity_dir)
        self.assertEqual(final.count(), workers * per_worker)
        self.assertEqual(final.integrity_issues(), [])


class ConcurrentMigrationTest(unittest.TestCase):
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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build_section(self, code: str, ruts: list[str]) -> None:
        section = self.workspace / "evaluations" / code
        section.mkdir(parents=True)
        (section / "config.json").write_text(json.dumps({"course": {"name": code}}), encoding="utf-8")
        students = [{"order": i, "rut": rut, "fullName": f"Student {i}"} for i, rut in enumerate(ruts)]
        (section / "students.json").write_text(json.dumps({"students": students}), encoding="utf-8")

    def test_concurrent_migration_of_different_sections_keeps_all_identities(self) -> None:
        self._build_section("CUR0001-001", ["11.111.111-1", "22.222.222-2"])
        self._build_section("CUR0001-002", ["33.333.333-3", "44.444.444-4", "55.555.555-5"])
        a = _run_worker(worker_migrate, str(self.workspace), str(self.private), str(self.state), "CUR0001-001")
        b = _run_worker(worker_migrate, str(self.workspace), str(self.private), str(self.state), "CUR0001-002")
        self.assertIn("CUR0001-001", a.split(","))
        self.assertIn("CUR0001-002", b.split(","))
        final = IdentityStore(self.state / "identity")
        self.assertEqual(final.count(), 5)
        self.assertEqual(final.integrity_issues(), [])

    def test_concurrent_same_section_migration_is_idempotent(self) -> None:
        self._build_section("CUR0001-001", ["11.111.111-1", "22.222.222-2"])
        results = [
            _run_worker(worker_migrate, str(self.workspace), str(self.private), str(self.state), "CUR0001-001")
            for _ in range(2)
        ]
        applied = sum(1 for result in results if "CUR0001-001" in result.split(","))
        self.assertGreaterEqual(applied, 1)
        self.assertLessEqual(applied, 2)
        plan = Migrator(self.workspace, self.runtime, IdentityStore(self.state / "identity")).build_plan(
            ["CUR0001-001"], dry_run=True
        )
        self.assertEqual(plan.sections[0].status, STATUS_MIGRATED)
        final = IdentityStore(self.state / "identity")
        self.assertEqual(final.count(), 2)


if __name__ == "__main__":
    unittest.main()
