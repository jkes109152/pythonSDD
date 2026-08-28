"""006 損壞存檔警告與五欄位隔離的無視窗 HUD 測試。"""

from __future__ import annotations

import unittest
import tempfile
from types import SimpleNamespace

from air_defense.hud import GameHUD
from air_defense.save_data import SaveProfile, SaveStore


class SaveRecoveryHudTests(unittest.TestCase):
    def _hud_stub(self) -> GameHUD:
        hud = GameHUD.__new__(GameHUD)
        hud.menu_profile_text = SimpleNamespace(text="")
        hud.shop_summary_text = SimpleNamespace(text="")
        hud.save_warning_text = SimpleNamespace(text="")
        hud.shop_result_text = SimpleNamespace(text="")
        hud.menu_rebirth_text = SimpleNamespace(text="")
        hud.rebirth_button = SimpleNamespace(enabled=True)
        hud.save_slot_buttons = [SimpleNamespace(text="") for _ in range(5)]
        return hud

    def test_corrupt_slot_warning_does_not_affect_other_slots(self) -> None:
        hud = self._hud_stub()
        with tempfile.TemporaryDirectory() as temporary_root:
            store = SaveStore(temporary_root)
            self.assertTrue(store.save_slot(2, SaveProfile(coins=222)).success)
            corrupt_path = store.slot_path(1)
            corrupt_path.parent.mkdir(parents=True, exist_ok=True)
            corrupt_path.write_text("{truncated", encoding="utf-8")

            results = store.list_slots()
            hud.update_profile_summary(
                results[0].profile,
                save_results=results,
                warning=results[0].warning,
                next_level="1-1",
            )

            self.assertTrue(results[0].is_corrupt)
            self.assertIn("原始檔案已保留", hud.save_warning_text.text)
            self.assertIn("損壞", hud.save_slot_buttons[0].text)
            self.assertIn("222 金幣", hud.save_slot_buttons[1].text)
            self.assertEqual(store.load_slot(2).profile.coins, 222)

    def test_delete_requires_confirmation_before_callback(self) -> None:
        hud = self._hud_stub()
        hud.save_delete_buttons = [
            SimpleNamespace(enabled=True, text="刪除") for _ in range(5)
        ]
        hud.save_confirm_delete_button = SimpleNamespace(
            enabled=False,
            text="確認刪除",
        )
        hud.save_cancel_delete_button = SimpleNamespace(enabled=False, text="取消")
        hud.pending_delete_slot = None
        calls: list[int] = []
        hud._delete_slot_callback = calls.append

        hud.request_delete_slot(2)

        self.assertEqual(hud.pending_delete_slot, 2)
        self.assertTrue(hud.save_confirm_delete_button.enabled)
        self.assertEqual(calls, [])

        hud.confirm_delete_slot()

        self.assertEqual(calls, [2])
        self.assertIsNone(hud.pending_delete_slot)
        self.assertFalse(hud.save_confirm_delete_button.enabled)


if __name__ == "__main__":
    unittest.main()
