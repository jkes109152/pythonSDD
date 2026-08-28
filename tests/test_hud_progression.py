"""006 HUD 永久進度文字的無視窗測試。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from air_defense.hud import GameHUD
from air_defense.progression import ProgressionConfig, UPGRADE_ARMOR
from air_defense.save_data import SaveProfile


class HudProgressionTests(unittest.TestCase):
    def _hud_stub(self) -> GameHUD:
        hud = GameHUD.__new__(GameHUD)
        hud.menu_profile_text = SimpleNamespace(text="")
        hud.shop_summary_text = SimpleNamespace(text="")
        hud.save_warning_text = SimpleNamespace(text="")
        hud.shop_result_text = SimpleNamespace(text="")
        hud.shop_upgrade_buttons = [SimpleNamespace(text="") for _ in range(11)]
        return hud

    def test_profile_summary_contains_slot_progress_and_next_level(self) -> None:
        hud = self._hud_stub()
        hud.update_profile_summary(
            SaveProfile(coins=123, rebirth_count=2, last_completed_a_b="4-9"),
            next_level="1-1",
        )
        self.assertIn("金幣 123", hud.menu_profile_text.text)
        self.assertIn("重生 2", hud.menu_profile_text.text)
        self.assertIn("A 4", hud.menu_profile_text.text)
        self.assertIn("最近完成 4-9", hud.menu_profile_text.text)
        self.assertIn("下一關 1-1", hud.menu_profile_text.text)

    def test_shop_buttons_list_all_upgrade_entries(self) -> None:
        hud = self._hud_stub()
        hud.update_shop_details(SaveProfile())
        button_text = "\n".join(button.text for button in hud.shop_upgrade_buttons)
        self.assertIn("最大 HP", button_text)
        self.assertIn("RPG", button_text)
        self.assertIn("多目標鎖定數量", button_text)

    def test_shop_item_uses_compact_number_level_cap_and_price_format(self) -> None:
        hud = self._hud_stub()
        config = ProgressionConfig(armor_upgrade_price=110)
        profile = SaveProfile(
            rebirth_count=1,
            max_aircraft_count=3,
            upgrade_levels={UPGRADE_ARMOR: 1},
            config=config,
        )

        hud.update_shop_details(profile)

        self.assertEqual(hud.shop_upgrade_buttons[1].text, "2鎧甲(1/4)220元")


if __name__ == "__main__":
    unittest.main()
