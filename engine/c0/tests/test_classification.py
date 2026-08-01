from __future__ import annotations

import unittest

from c0.classification import DataClass, classify, is_versionable, reason_for


class ClassificationTest(unittest.TestCase):
    def test_versionable_classes(self) -> None:
        self.assertTrue(is_versionable(DataClass.PUBLIC))
        self.assertTrue(is_versionable(DataClass.INTERNAL))
        self.assertFalse(is_versionable(DataClass.CONFIDENTIAL))
        self.assertFalse(is_versionable(DataClass.RESTRICTED))

    def test_known_kinds(self) -> None:
        self.assertEqual(classify("source-code"), DataClass.PUBLIC)
        self.assertEqual(classify("synthetic-fixtures"), DataClass.INTERNAL)
        self.assertEqual(classify("roster"), DataClass.RESTRICTED)
        self.assertEqual(classify("submissions"), DataClass.RESTRICTED)
        self.assertEqual(classify("smtp-api-secrets"), DataClass.RESTRICTED)

    def test_unknown_kind_is_conservative(self) -> None:
        self.assertEqual(classify("totally-unknown"), DataClass.CONFIDENTIAL)
        self.assertFalse(is_versionable(classify("totally-unknown")))

    def test_reason_for_known_and_unknown(self) -> None:
        self.assertTrue(reason_for("roster"))
        self.assertTrue(reason_for("mystery"))


if __name__ == "__main__":
    unittest.main()
