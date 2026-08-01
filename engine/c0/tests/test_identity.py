from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from c0.identity import (
    STUDENT_ID_PREFIX,
    IdentityConflictError,
    IdentityIntegrityError,
    IdentityStore,
    StudentIdentity,
    generate_student_id,
)


class IdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.identity_dir = self.tmp / "state" / "identity"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generate_opaque_id(self) -> None:
        sid = generate_student_id()
        self.assertTrue(sid.startswith(STUDENT_ID_PREFIX))
        self.assertGreater(len(sid), len(STUDENT_ID_PREFIX) + 20)

    def test_not_derived_from_pii(self) -> None:
        pii = "12.345.678-9"
        a = generate_student_id()
        b = generate_student_id()
        self.assertNotEqual(a, b)
        self.assertNotIn("12345678", a)
        self.assertNotIn(pii, a)

    def test_collision_safe(self) -> None:
        taken = {"stu_" + "0" * 32}
        self.assertNotIn(generate_student_id(taken), taken)

    def test_ensure_is_stable(self) -> None:
        store = IdentityStore(self.identity_dir)
        sid_a = store.ensure(external={"rut": "11.111.111-1"}, display_name="Fictional User")
        sid_b = store.ensure(external={"rut": "11.111.111-1"}, display_name="Fictional User")
        self.assertEqual(sid_a, sid_b)
        self.assertEqual(store.count(), 1)

    def test_ensure_persists_across_stores(self) -> None:
        first = IdentityStore(self.identity_dir)
        sid = first.ensure(external={"rut": "22.222.222-2"}, display_name="Synthetic Name")
        second = IdentityStore(self.identity_dir)
        self.assertEqual(second.resolve_by_external("rut", "22.222.222-2"), sid)
        self.assertEqual(second.resolve(sid).display_name, "Synthetic Name")

    def test_ensure_merges_extra_identifiers(self) -> None:
        store = IdentityStore(self.identity_dir)
        sid = store.ensure(external={"rut": "33.333.333-3"})
        again = store.ensure(external={"rut": "33.333.333-3", "email": "person@example.test"})
        self.assertEqual(sid, again)
        record = store.resolve(sid)
        self.assertEqual(record.external_identifiers["email"], "person@example.test")

    def test_conflicting_external_identity_raises(self) -> None:
        store = IdentityStore(self.identity_dir)
        store.ensure(external={"rut": "44.444.444-4"}, display_name="One")
        store.ensure(external={"email": "first@example.test"}, display_name="Two")
        # Bringing both identifiers together resolves to two different opaque ids.
        with self.assertRaises(IdentityConflictError):
            store.ensure(external={"rut": "44.444.444-4", "email": "first@example.test"})

    def test_ensure_merges_updates_reverse_lookup(self) -> None:
        store = IdentityStore(self.identity_dir)
        sid = store.ensure(external={"rut": "33.333.333-3"})
        store.ensure(external={"rut": "33.333.333-3", "email": "person@example.test"})
        self.assertEqual(store.resolve_by_external("email", "person@example.test"), sid)

    def test_ensure_many_detects_duplicates_in_batch(self) -> None:
        store = IdentityStore(self.identity_dir)
        entries = [
            {"external": {"rut": "11.111.111-1"}, "display_name": "One"},
            {"external": {"rut": "11.111.111-1"}, "display_name": "One duplicate row"},
        ]
        with self.assertRaises(IdentityConflictError):
            store.ensure_many(entries)

    def test_ensure_many_is_atomic_and_stable(self) -> None:
        store = IdentityStore(self.identity_dir)
        entries = [
            {"external": {"rut": "11.111.111-1"}, "display_name": "One"},
            {"external": {"rut": "22.222.222-2"}, "display_name": "Two"},
        ]
        first = store.ensure_many(entries)
        second = store.ensure_many(entries)
        self.assertEqual(first, second)
        self.assertEqual(store.count(), 2)
        reloaded = IdentityStore(self.identity_dir)
        self.assertEqual(reloaded.count(), 2)
        self.assertEqual(reloaded.resolve_by_external("rut", "22.222.222-2"), second[1])

    def test_ensure_many_dry_run_does_not_persist(self) -> None:
        store = IdentityStore(self.identity_dir)
        entries = [
            {"external": {"rut": "11.111.111-1"}, "display_name": "One"},
            {"external": {"rut": "22.222.222-2"}, "display_name": "Two"},
        ]
        store.ensure_many(entries, dry_run=True)
        reloaded = IdentityStore(self.identity_dir)
        self.assertEqual(reloaded.count(), 0)

    def test_corrupted_store_reports_issue_without_raising(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        (self.identity_dir / "identity.json").write_text("{not valid json", encoding="utf-8")
        store = IdentityStore(self.identity_dir)
        self.assertTrue(store.integrity_issues())
        self.assertEqual(store.count(), 0)

    def test_modification_refused_on_corrupted_store(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        (self.identity_dir / "identity.json").write_text("{not valid json", encoding="utf-8")
        store = IdentityStore(self.identity_dir)
        with self.assertRaises(IdentityIntegrityError):
            store.ensure(external={"rut": "11.111.111-1"})

    def test_dry_run_does_not_persist(self) -> None:
        store = IdentityStore(self.identity_dir)
        sid = store.ensure(external={"rut": "66.666.666-6"}, dry_run=True)
        self.assertTrue(sid.startswith(STUDENT_ID_PREFIX))
        reloaded = IdentityStore(self.identity_dir)
        self.assertEqual(reloaded.count(), 0)

    def test_integrity_detects_duplicate_student_id(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        (self.identity_dir / "identity.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "records": [
                        {"studentId": "stu_aaa", "externalIdentifiers": {"rut": "11.111.111-1"}},
                        {"studentId": "stu_aaa", "externalIdentifiers": {"rut": "22.222.222-2"}},
                    ],
                }
            ),
            encoding="utf-8",
        )
        store = IdentityStore(self.identity_dir)
        self.assertTrue(any("duplicate studentId" in issue for issue in store.integrity_issues()))

    def test_integrity_detects_external_conflict(self) -> None:
        self.identity_dir.mkdir(parents=True, exist_ok=True)
        (self.identity_dir / "identity.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "records": [
                        {"studentId": "stu_aaa", "externalIdentifiers": {"rut": "11.111.111-1"}},
                        {"studentId": "stu_bbb", "externalIdentifiers": {"rut": "11.111.111-1"}},
                    ],
                }
            ),
            encoding="utf-8",
        )
        store = IdentityStore(self.identity_dir)
        self.assertTrue(any("bound to multiple student ids" in issue for issue in store.integrity_issues()))

    def test_store_file_has_restrictive_permissions(self) -> None:
        store = IdentityStore(self.identity_dir)
        store.ensure(external={"rut": "77.777.777-7"})
        mode = (self.identity_dir / "identity.json").stat().st_mode & 0o777
        self.assertLessEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
