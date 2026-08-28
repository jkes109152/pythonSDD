"""006 純進度規則測試；不建立 Ursina 視窗。"""

from __future__ import annotations

import importlib
import sys
import unittest

from air_defense.progression import (
    AircraftToken,
    LevelKey,
    ProgressionConfig,
    apply_damage,
    build_level_plan,
    calculate_rebirth_cost,
    calculate_reward,
    create_regen_state,
    effective_max_hp,
    purchase_upgrade,
    tick_regeneration,
    UPGRADE_MAX_HP,
)
from air_defense.save_data import SaveProfile


class LevelProgressionTests(unittest.TestCase):
    def test_all_supported_a_values_use_a_b_rules_without_fixed_limits(self) -> None:
        for maximum in (2, 3, 4, 5, 19):
            for a in range(1, maximum + 1):
                last_b = a + 1 if a < maximum else 2 * a + 1
                for b in range(1, last_b + 1):
                    plan = build_level_plan(LevelKey(a, b), maximum)
                    self.assertEqual(str(plan.key), f"{a}-{b}")
                    self.assertEqual(len(plan.roster), a)
                    if a < maximum:
                        self.assertEqual(plan.boss_count, 0)
                    elif b <= maximum + 1:
                        self.assertEqual(plan.boss_count, 0)

    def test_deterministic_direction_is_normal_right_to_special_and_boss_left(self) -> None:
        self.assertEqual(
            build_level_plan("4-4", 4).roster,
            ("普", "特", "特", "特"),
        )
        self.assertEqual(
            build_level_plan("4-7", 4).roster,
            ("魔", "魔", "特", "特"),
        )
        self.assertEqual(build_level_plan("4-9", 4).roster, ("魔",) * 4)

    def test_maximum_is_derived_from_rebirth_and_never_18_or_4(self) -> None:
        config = ProgressionConfig()
        self.assertEqual(config.maximum_aircraft_count(0), 2)
        self.assertEqual(config.maximum_aircraft_count(5), 7)
        self.assertEqual(config.maximum_aircraft_count(17), 19)


class EconomyAndRecoveryTests(unittest.TestCase):
    def test_upgrade_purchase_is_atomic_and_rebirth_increases_caps(self) -> None:
        profile = SaveProfile(coins=10_000)
        purchased = purchase_upgrade(profile, UPGRADE_MAX_HP)
        self.assertEqual(profile.coins, 10_000)
        self.assertEqual(purchased.coins, 9_750)
        self.assertEqual(effective_max_hp(purchased), 110)
        purchased.rebirth_available = True
        from air_defense.progression import apply_rebirth

        reborn = apply_rebirth(purchased)
        self.assertEqual(reborn.rebirth_count, 1)
        self.assertEqual(reborn.max_aircraft_count, 3)
        self.assertEqual(reborn.upgrade_caps[UPGRADE_MAX_HP], 6)

    def test_regeneration_waits_is_limited_and_damage_uses_armor(self) -> None:
        profile = SaveProfile(coins=10_000)
        profile = purchase_upgrade(profile, "armor")
        regen = create_regen_state(100)
        hp = apply_damage(100, 10, 100, regen, now=0.0, profile=profile)
        self.assertEqual(hp, 91.0)
        self.assertEqual(tick_regeneration(regen, hp, 100, 4.0, now=4.0), hp)
        recovered = tick_regeneration(regen, hp, 100, 2.0, now=6.0)
        self.assertEqual(recovered, 93.0)
        self.assertLessEqual(recovered - hp, 2.0)

    def test_reward_includes_boss_and_rebirth_multiplier(self) -> None:
        regular = build_level_plan("2-1", 2)
        boss = build_level_plan("2-5", 2)
        self.assertGreater(calculate_reward(boss, 0), calculate_reward(regular, 0))
        self.assertGreater(calculate_reward(regular, 1), calculate_reward(regular, 0))


if __name__ == "__main__":
    unittest.main()
