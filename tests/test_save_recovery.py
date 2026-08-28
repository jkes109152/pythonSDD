"""006 損壞、未知版本與原子存檔恢復測試。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from air_defense.save_data import SaveProfile, SaveStore


class SaveRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SaveStore(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_unknown_version_and_invalid_history_keep_original_bytes(self) -> None:
        for slot, raw in (
            (1, {"schema_version": 99}),
            (2, {"schema_version": 1, "last_completed_a_b": "19-40"}),
        ):
            path = self.store.slot_path(slot)
            path.parent.mkdir(parents=True, exist_ok=True)
            original = json.dumps(raw, ensure_ascii=False)
            path.write_text(original, encoding="utf-8")
            result = self.store.load_slot(slot)
            self.assertTrue(result.is_corrupt)
            self.assertTrue(result.warning)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_one_corrupt_slot_does_not_change_the_other_four(self) -> None:
        for slot, coins in ((1, 11), (2, 22), (3, 33), (4, 44), (5, 55)):
            self.assertTrue(self.store.save_slot(slot, SaveProfile(coins=coins)).success)
        bad_path = self.store.slot_path(1)
        original = "{truncated"
        bad_path.write_text(original, encoding="utf-8")
        self.assertTrue(self.store.load_slot(1).is_corrupt)
        self.assertEqual(
            [self.store.load_slot(slot).profile.coins for slot in range(2, 6)],
            [22, 33, 44, 55],
        )

    def test_atomic_save_leaves_no_temporary_slot_files(self) -> None:
        self.assertTrue(self.store.save_slot(3, SaveProfile(coins=321)).success)
        self.assertEqual(self.store.load_slot(3).profile.coins, 321)
        self.assertEqual(tuple(self.store.root.glob(".slot-3-*.tmp")), ())


if __name__ == "__main__":
    unittest.main()
