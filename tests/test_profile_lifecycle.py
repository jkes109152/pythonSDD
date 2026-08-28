"""006 Profile／RunState 生命週期與冪等結算測試。"""

from __future__ import annotations

import tempfile
import unittest

from air_defense.save_data import SaveStore
from air_defense import config
from air_defense.state import GamePhase, GameSession


class ProfileLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SaveStore(self.temp_dir.name)
        self.session = GameSession(save_store=self.store)
        self.session.select_save_slot(1)
        self.session.profile.coins = 10_000

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_slot_selection_enters_menu_and_start_restores_effective_max_hp(self) -> None:
        self.assertEqual(self.session.phase, GamePhase.MAIN_MENU)
        self.assertIsNone(self.session.run_state)
        run = self.session.start_sublevel()
        self.assertEqual(str(run.level), "1-1")
        self.assertEqual(run.current_hp, 100.0)
        self.session.take_damage(30)
        self.assertLess(self.session.health, 100)
        self.session.return_to_profile_menu()
        self.assertEqual(self.session.phase, GamePhase.MAIN_MENU)
        self.assertIsNone(self.session.run_state)
        restarted = self.session.start_sublevel()
        self.assertEqual(restarted.current_hp, 100.0)

    def test_profile_rpg_runtime_uses_pistol_range(self) -> None:
        run = self.session.start_sublevel()

        self.assertEqual(run.weapon_runtime["RPG"].range, config.PISTOL_MAX_RANGE)

    def test_complete_is_idempotent_after_runstate_clear_and_persists_history(self) -> None:
        run = self.session.start_sublevel()
        settlement = self.session.complete_sublevel_once(run.attempt_id)
        self.assertIsNotNone(settlement)
        assert settlement is not None
        self.assertEqual(self.session.profile.coins, settlement.awarded_coins + 10_000)
        self.assertIsNone(self.session.run_state)
        duplicate = self.session.complete_sublevel_once(run.attempt_id)
        self.assertIs(duplicate, settlement)
        self.assertEqual(self.session.profile.coins, settlement.awarded_coins + 10_000)
        loaded = self.store.load_slot(1).profile
        self.assertEqual(loaded.last_completed_a_b, "1-1")

    def test_death_resets_transient_state_without_losing_profile(self) -> None:
        run = self.session.start_sublevel()
        self.session.run_state.weapon_runtime[next(iter(self.session.run_state.weapon_runtime))].ammo_remaining = 0
        self.session.take_damage(10_000)
        self.assertEqual(self.session.phase, GamePhase.MAIN_MENU)
        self.assertIsNone(self.session.run_state)
        self.assertEqual(self.session.profile.rebirth_available, True)
        self.assertEqual(self.session.session_progress.next_play_level.a, 1)
        self.assertEqual(self.session.session_progress.next_play_level.b, 1)
        self.assertEqual(self.store.load_slot(1).profile.rebirth_available, True)

    def test_purchase_operation_id_only_changes_profile_once(self) -> None:
        first = self.session.purchase_upgrade_once("buy-1", "max_hp")
        second = self.session.purchase_upgrade_once("buy-1", "max_hp")
        self.assertTrue(first.success)
        self.assertIs(second, first)
        self.assertEqual(self.session.profile.upgrade_levels["max_hp"], 1)
        self.assertEqual(self.session.profile.coins, 10_000 - 250)

    def test_normal_completion_advances_in_memory_but_new_load_starts_at_one_one(self) -> None:
        run = self.session.start_sublevel()
        self.session.complete_sublevel_once(run.attempt_id)
        self.assertEqual(str(self.session.session_progress.next_play_level), "1-2")
        next_run = self.session.start_sublevel()
        self.assertEqual(str(next_run.level), "1-2")
        self.session.complete_sublevel_once(next_run.attempt_id)
        self.session.select_save_slot(1)
        self.assertEqual(str(self.session.session_progress.next_play_level), "1-1")

    def test_high_rebirth_count_can_start_a_level_above_legacy_limits(self) -> None:
        self.session.profile.rebirth_count = 17
        self.session.profile.max_aircraft_count = 19
        self.session.session_progress.next_play_level = (19, 39)
        run = self.session.start_sublevel()
        self.assertEqual(run.level.a, 19)
        self.assertEqual(run.level.b, 39)
        self.assertEqual(run.level_plan.boss_count, 19)

    def test_new_run_rebuilds_hp_city_weapons_turrets_and_regen(self) -> None:
        run = self.session.start_sublevel()
        self.session.take_damage(20)
        run.city_health = 1
        self.session.return_to_profile_menu()
        restarted = self.session.start_sublevel()
        self.assertEqual(restarted.current_hp, restarted.effective_max_hp)
        self.assertEqual(restarted.city_health, restarted.max_city_health)
        self.assertIsNot(restarted, run)
        self.assertIsNotNone(restarted.regen)
        self.assertEqual(restarted.weapon_runtime["RPG"].ammo_remaining, 0)
        self.assertEqual(restarted.turrets, [])


if __name__ == "__main__":
    unittest.main()
