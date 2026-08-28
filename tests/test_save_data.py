"""006 五欄位 JSON 存檔與損壞資料恢復測試。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from air_defense.save_data import SCHEMA_VERSION, SaveProfile, SaveStore
from air_defense.progression import UPGRADE_MULTI_AA_TARGETS


class SaveDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SaveStore(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_five_slots_are_independent_and_empty_slots_are_safe(self) -> None:
        self.assertEqual([item.status for item in self.store.list_slots()], ["empty"] * 5)
        first = SaveProfile(coins=100)
        second = SaveProfile(coins=200, rebirth_count=1, max_aircraft_count=3)
        self.assertTrue(self.store.save_slot(1, first).success)
        self.assertTrue(self.store.save_slot(2, second).success)
        self.assertEqual(self.store.load_slot(1).profile.coins, 100)
        self.assertEqual(self.store.load_slot(2).profile.coins, 200)
        self.assertEqual(self.store.load_slot(3).status, "empty")

    def test_json_round_trip_has_schema_version_and_recent_level(self) -> None:
        profile = SaveProfile(coins=345, last_completed_a_b="19-39")
        self.assertTrue(self.store.save_slot(5, profile).success)
        raw = json.loads(self.store.slot_path(5).read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"], SCHEMA_VERSION)
        self.assertEqual(raw["last_completed_a_b"], "19-39")
        loaded = self.store.load_slot(5)
        self.assertEqual(loaded.status, "valid")
        self.assertEqual(loaded.profile.last_completed_a_b, "19-39")

    def test_stale_maximum_is_normalized_but_original_is_not_overwritten_on_load(self) -> None:
        profile = SaveProfile(coins=5, rebirth_count=2)
        self.assertTrue(self.store.save_slot(1, profile).success)
        path = self.store.slot_path(1)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["max_aircraft_count"] = 18
        path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = self.store.load_slot(1)
        self.assertEqual(loaded.status, "valid")
        self.assertEqual(loaded.profile.max_aircraft_count, 4)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["max_aircraft_count"], 18)

    def test_corrupt_save_is_replaced_in_memory_and_original_is_retained(self) -> None:
        path = self.store.slot_path(4)
        path.parent.mkdir(parents=True, exist_ok=True)
        original = '{"schema_version": 1, '
        path.write_text(original, encoding="utf-8")
        result = self.store.load_slot(4)
        self.assertEqual(result.status, "corrupt")
        self.assertTrue(result.warning)
        self.assertEqual(result.profile.coins, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_negative_or_over_cap_data_is_corrupt(self) -> None:
        profile = SaveProfile().to_dict()
        profile["coins"] = -1
        self.store.slot_path(1).parent.mkdir(parents=True, exist_ok=True)
        self.store.slot_path(1).write_text(json.dumps(profile), encoding="utf-8")
        self.assertTrue(self.store.load_slot(1).is_corrupt)
        profile["coins"] = 0
        profile["upgrade_levels"] = {"max_hp": 99}
        self.store.slot_path(2).write_text(json.dumps(profile), encoding="utf-8")
        self.assertTrue(self.store.load_slot(2).is_corrupt)

    def test_schema_one_legacy_multi_target_level_and_snapshot_round_trip(self) -> None:
        raw = SaveProfile(coins=12).to_dict()
        raw["upgrade_levels"][UPGRADE_MULTI_AA_TARGETS] = 99
        raw["upgrade_caps"][UPGRADE_MULTI_AA_TARGETS] = 123

        loaded = SaveProfile.from_dict(raw)

        self.assertEqual(loaded.upgrade_levels[UPGRADE_MULTI_AA_TARGETS], 99)
        self.assertEqual(loaded.upgrade_caps[UPGRADE_MULTI_AA_TARGETS], 123)
        self.assertEqual(
            SaveProfile.from_dict(loaded.to_dict()).upgrade_levels[UPGRADE_MULTI_AA_TARGETS],
            99,
        )
        self.assertEqual(
            SaveProfile.from_dict(loaded.to_dict()).upgrade_caps[UPGRADE_MULTI_AA_TARGETS],
            123,
        )

    def test_delete_slot_removes_only_the_requested_profile(self) -> None:
        for slot, coins in ((1, 111), (2, 222), (3, 333)):
            self.assertTrue(self.store.save_slot(slot, SaveProfile(coins=coins)).success)

        deleted = self.store.delete_slot(2)

        self.assertTrue(deleted.success)
        self.assertTrue(deleted.deleted)
        self.assertEqual(self.store.load_slot(2).status, "empty")
        self.assertEqual(self.store.load_slot(1).profile.coins, 111)
        self.assertEqual(self.store.load_slot(3).profile.coins, 333)
        repeated = self.store.delete_slot(2)
        self.assertFalse(repeated.success)
        self.assertTrue(repeated.is_empty)


if __name__ == "__main__":
    unittest.main()
