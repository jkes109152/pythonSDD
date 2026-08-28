"""006 跨戰鬥階段武器切換與合法目標檢查。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from air_defense.rules import inventory_selection_allowed, is_valid_target
from air_defense.state import AircraftPhase, AircraftType, GamePhase, WeaponKind


class WeaponSystemTests(unittest.TestCase):
    def test_all_slots_can_switch_in_all_combat_phases(self) -> None:
        for phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT):
            for weapon in WeaponKind:
                self.assertTrue(inventory_selection_allowed(phase, weapon))

    def test_target_categories_still_gate_fire(self) -> None:
        aircraft = SimpleNamespace(
            id="plane-1",
            aircraft_type=AircraftType.NORMAL,
            phase=AircraftPhase.APPROACHING,
            health=1,
            position=(0.0, 0.0, 10.0),
        )
        ground = SimpleNamespace(id="crew-1", alive=True, health=1, position=(0.0, 0.0, 5.0))
        self.assertTrue(is_valid_target(WeaponKind.ANTI_AIRCRAFT, aircraft, distance=10.0))
        self.assertFalse(is_valid_target(WeaponKind.ANTI_AIRCRAFT, ground, distance=5.0))
        self.assertTrue(is_valid_target(WeaponKind.SNIPER, ground, distance=5.0))
        self.assertFalse(is_valid_target(WeaponKind.SNIPER, aircraft, distance=5.0))
        self.assertFalse(is_valid_target(WeaponKind.PISTOL, ground, distance=13.0))
        self.assertFalse(is_valid_target(WeaponKind.RPG, aircraft, distance=10.0))
        self.assertTrue(is_valid_target(WeaponKind.RPG, ground, distance=5.0))
        self.assertFalse(is_valid_target(WeaponKind.RPG, ground, cooldown_remaining=0.1))
        self.assertFalse(is_valid_target(WeaponKind.RPG, ground, ammo_remaining=0))


if __name__ == "__main__":
    unittest.main()
