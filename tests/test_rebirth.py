"""006 明確重生資格、費用與冪等操作測試。"""

from __future__ import annotations

import tempfile
import unittest

from air_defense.progression import (
    UPGRADE_MAX_HP,
    calculate_rebirth_cost,
    derive_upgrade_caps,
)
from air_defense.save_data import SaveStore
from air_defense.state import GamePhase, GameSession


class RebirthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SaveStore(self.temp_dir.name)
        self.session = GameSession(save_store=self.store)
        self.session.select_save_slot(1)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_death_opens_rebirth_and_success_clears_coins_without_auto_start(self) -> None:
        self.session.profile.coins = calculate_rebirth_cost(0)
        self.session.start_sublevel()
        self.session.take_damage(10_000)
        self.assertTrue(self.session.profile.rebirth_available)
        result = self.session.apply_rebirth_once("rebirth-1")
        self.assertTrue(result.success)
        self.assertEqual(result.profile.coins, 0)
        self.assertEqual(result.profile.rebirth_count, 1)
        self.assertEqual(result.profile.max_aircraft_count, 3)
        self.assertEqual(self.session.phase, GamePhase.MAIN_MENU)
        self.assertIsNone(self.session.run_state)
        duplicate = self.session.apply_rebirth_once("rebirth-1")
        self.assertIs(duplicate, result)
        self.assertEqual(self.session.profile.rebirth_count, 1)

    def test_rebirth_is_rejected_during_battle(self) -> None:
        self.session.profile.coins = calculate_rebirth_cost(0)
        self.session.profile.rebirth_available = True
        self.session.start_sublevel()
        result = self.session.apply_rebirth_once("battle-rebirth")
        self.assertFalse(result.success)
        self.assertEqual(self.session.profile.rebirth_count, 0)
        self.assertEqual(self.session.phase, GamePhase.AIRSTRIKE)

    def test_final_sublevel_opens_rebirth_and_resets_next_level(self) -> None:
        self.session.profile.coins = 10_000
        self.session.session_progress.next_play_level = (2, 5)
        run = self.session.start_sublevel()
        settlement = self.session.complete_sublevel_once(run.attempt_id)
        self.assertIsNotNone(settlement)
        self.assertTrue(self.session.profile.rebirth_available)
        self.assertEqual(str(self.session.session_progress.next_play_level), "1-1")


if __name__ == "__main__":
    unittest.main()
