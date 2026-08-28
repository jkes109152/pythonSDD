"""006 選檔後主選單流程的無視窗驗證。"""

from __future__ import annotations

import tempfile
import unittest

from air_defense.save_data import SaveProfile, SaveStore
from air_defense.state import GamePhase, GameSession


class MenuFlowTests(unittest.TestCase):
    def test_selecting_a_slot_never_starts_a_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(directory)
            store.save_slot(1, SaveProfile(coins=100))
            store.save_slot(2, SaveProfile(coins=200))
            session = GameSession(save_store=store, phase=GamePhase.SAVE_SELECT)
            result = session.select_save_slot(2)
            self.assertEqual(result.profile.coins, 200)
            self.assertEqual(session.phase, GamePhase.MAIN_MENU)
            self.assertIsNone(session.run_state)
            self.assertEqual(session.session_progress.selected_slot_id, 2)
            self.assertEqual(session.profile.coins, 200)

    def test_delete_from_save_select_keeps_other_slots_and_does_not_start_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SaveStore(directory)
            store.save_slot(1, SaveProfile(coins=100))
            store.save_slot(2, SaveProfile(coins=200))
            session = GameSession(save_store=store, phase=GamePhase.SAVE_SELECT)

            result = session.delete_save_slot(1)

            self.assertTrue(result.deleted)
            self.assertEqual(session.phase, GamePhase.SAVE_SELECT)
            self.assertIsNone(session.profile)
            self.assertIsNone(session.run_state)
            self.assertEqual(store.load_slot(1).status, "empty")
            self.assertEqual(store.load_slot(2).profile.coins, 200)

            session.phase = GamePhase.MAIN_MENU
            rejected = session.delete_save_slot(2)
            self.assertEqual(rejected.status, "rejected")
            self.assertEqual(store.load_slot(2).profile.coins, 200)


if __name__ == "__main__":
    unittest.main()
