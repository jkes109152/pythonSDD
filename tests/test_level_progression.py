"""006 a-b 戰役順序與大於舊上限的純邏輯測試。"""

from __future__ import annotations

import unittest

from air_defense.progression import (
    AircraftToken,
    LevelKey,
    build_level_plan,
    campaign_levels,
    next_level,
    validate_level_key,
)


class LevelProgressionContractTests(unittest.TestCase):
    def test_campaign_order_and_final_stage_for_multiple_a_values(self) -> None:
        for maximum in (2, 3, 4, 5, 19):
            keys = campaign_levels(maximum)
            self.assertEqual(keys[0], LevelKey(1, 1))
            self.assertEqual(keys[-1], LevelKey(maximum, 2 * maximum + 1))
            self.assertEqual(len(keys), sum(a + 1 for a in range(1, maximum)) + 2 * maximum + 1)
            for key in keys:
                plan = build_level_plan(key, maximum)
                self.assertEqual(len(plan.roster), key.a)
                if key.a < maximum:
                    self.assertEqual(plan.boss_count, 0)
                    self.assertNotIn(AircraftToken.BOSS.value, plan.roster)

    def test_transitions_are_right_to_left_then_left_to_right(self) -> None:
        self.assertEqual(build_level_plan("4-1", 4).roster, ("普", "普", "普", "普"))
        self.assertEqual(build_level_plan("4-5", 4).roster, ("特", "特", "特", "特"))
        self.assertEqual(build_level_plan("4-6", 4).roster, ("魔", "特", "特", "特"))
        self.assertEqual(build_level_plan("4-9", 4).roster, ("魔", "魔", "魔", "魔"))

    def test_invalid_b_and_a_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_level_key("3-5", 4)
        with self.assertRaises(ValueError):
            validate_level_key("4-10", 4)
        with self.assertRaises(ValueError):
            validate_level_key("5-1", 4)

    def test_next_level_wraps_only_after_current_a_final_stage(self) -> None:
        self.assertEqual(next_level("1-2", 4), LevelKey(2, 1))
        self.assertEqual(next_level("4-8", 4), LevelKey(4, 9))
        self.assertEqual(next_level("4-9", 4), LevelKey(1, 1))


if __name__ == "__main__":
    unittest.main()
