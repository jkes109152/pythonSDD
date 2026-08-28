"""006 金幣、升級上限與重生經濟的純邏輯測試。"""

from __future__ import annotations

import unittest

from air_defense.progression import (
    UPGRADE_AUTO_DEFENSE,
    UPGRADE_AUTO_DEFENSE_CAPACITY,
    UPGRADE_AA_WHITEBOX,
    UPGRADE_MAX_HP,
    UPGRADE_MULTI_AA,
    UPGRADE_MULTI_AA_TARGETS,
    apply_rebirth,
    auto_defense_capacity,
    build_level_plan,
    calculate_rebirth_cost,
    calculate_reward,
    effective_whitebox_scale,
    multi_aa_target_count,
    price_for_upgrade,
    purchase_upgrade,
    upgrade_catalog,
)
from air_defense.entities import MultiAntiAircraftGun
from air_defense.save_data import SaveProfile


class EconomyContractTests(unittest.TestCase):
    def test_reward_formula_includes_boss_count_and_rebirth_multiplier(self) -> None:
        plan = build_level_plan("2-5", 2)
        expected = (100 + 25 * 2 + 10 * 4 + 150 * 2) * (1 + 0.5)
        self.assertEqual(calculate_reward(plan, 1), int(expected))

    def test_repeatable_price_and_cap_are_progression_driven(self) -> None:
        self.assertEqual(price_for_upgrade(UPGRADE_MAX_HP, 0), 250)
        self.assertEqual(price_for_upgrade(UPGRADE_MAX_HP, 1), 500)
        profile = SaveProfile(coins=100_000)
        for _ in range(profile.upgrade_caps[UPGRADE_MAX_HP]):
            profile = purchase_upgrade(profile, UPGRADE_MAX_HP)
        coins_before = profile.coins
        with self.assertRaises(ValueError):
            purchase_upgrade(profile, UPGRADE_MAX_HP)
        self.assertEqual(profile.coins, coins_before)

    def test_turret_hard_limit_remains_bounded_but_legacy_multi_target_upgrade_is_not_for_sale(self) -> None:
        profile = SaveProfile(coins=1_000_000)
        profile = purchase_upgrade(profile, UPGRADE_AUTO_DEFENSE)
        for _ in range(5):
            profile = purchase_upgrade(profile, UPGRADE_AUTO_DEFENSE_CAPACITY)
        self.assertEqual(auto_defense_capacity(profile), 6)
        with self.assertRaises(ValueError):
            purchase_upgrade(profile, UPGRADE_AUTO_DEFENSE_CAPACITY)

        profile = purchase_upgrade(profile, UPGRADE_MULTI_AA)
        self.assertNotIn(
            UPGRADE_MULTI_AA_TARGETS,
            {entry.upgrade_id for entry in upgrade_catalog(profile.config)},
        )
        with self.assertRaises(ValueError):
            purchase_upgrade(profile, UPGRADE_MULTI_AA_TARGETS)

    def test_whitebox_upgrade_is_the_shared_source_and_multi_frame_is_fixed_ratio(self) -> None:
        profile = SaveProfile(coins=100_000)
        self.assertEqual(price_for_upgrade(UPGRADE_AA_WHITEBOX, 0), 250)
        self.assertEqual(profile.upgrade_caps[UPGRADE_AA_WHITEBOX], 5)
        profile = purchase_upgrade(profile, UPGRADE_AA_WHITEBOX)
        self.assertAlmostEqual(effective_whitebox_scale(profile), 1.10)

        gun = MultiAntiAircraftGun(world_position=(0.0, 0.0, 0.0), target_capacity=2)
        self.assertEqual(len(gun.set_targets(tuple(f"aircraft-{i}" for i in range(12)))), 12)
        self.assertNotIn(
            UPGRADE_MULTI_AA_TARGETS,
            {entry.upgrade_id for entry in upgrade_catalog(profile.config)},
        )

    def test_rebirth_cost_and_apply_are_atomic(self) -> None:
        profile = SaveProfile(coins=calculate_rebirth_cost(2), rebirth_count=2)
        profile.rebirth_available = True
        reborn = apply_rebirth(profile)
        self.assertEqual(reborn.coins, 0)
        self.assertEqual(reborn.rebirth_count, 3)
        self.assertEqual(reborn.max_aircraft_count, 5)
        self.assertFalse(reborn.rebirth_available)
        self.assertEqual(profile.coins, calculate_rebirth_cost(2))


if __name__ == "__main__":
    unittest.main()
