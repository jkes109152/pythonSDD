"""006 E/G 輸入契約的無效果測試。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from air_defense.main import AirDefenseGame
from air_defense.state import GamePhase


class InputContractTests(unittest.TestCase):
    def test_legacy_e_and_g_handlers_are_no_ops(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        self.assertIsNone(game._interact())
        self.assertIsNone(game._drop_weapon())

    def test_save_select_mouse_click_routes_to_slot_selection(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        selected: list[int] = []
        game.session = SimpleNamespace(phase=GamePhase.SAVE_SELECT)
        game.hud = SimpleNamespace(
            save_slot_buttons=[
                SimpleNamespace(hovered=False),
                SimpleNamespace(hovered=True),
                SimpleNamespace(hovered=False),
                SimpleNamespace(hovered=False),
                SimpleNamespace(hovered=False),
            ],
            save_delete_buttons=[SimpleNamespace(hovered=False) for _ in range(5)],
            save_confirm_delete_button=SimpleNamespace(hovered=False),
            save_cancel_delete_button=SimpleNamespace(hovered=False),
        )
        game.select_save_slot = selected.append
        game.input("left mouse down")
        self.assertEqual(selected, [2])

    def test_save_select_mouse_click_routes_to_delete_confirmation(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        requested: list[int] = []
        game.session = SimpleNamespace(phase=GamePhase.SAVE_SELECT)
        game.hud = SimpleNamespace(
            save_slot_buttons=[SimpleNamespace(hovered=False) for _ in range(5)],
            save_delete_buttons=[
                SimpleNamespace(hovered=False),
                SimpleNamespace(hovered=True),
                SimpleNamespace(hovered=False),
                SimpleNamespace(hovered=False),
                SimpleNamespace(hovered=False),
            ],
            save_confirm_delete_button=SimpleNamespace(hovered=False),
            save_cancel_delete_button=SimpleNamespace(hovered=False),
            request_delete_slot=requested.append,
        )
        game.input("left mouse down")
        self.assertEqual(requested, [2])


if __name__ == "__main__":
    unittest.main()
