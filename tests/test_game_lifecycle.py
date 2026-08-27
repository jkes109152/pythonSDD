"""Lifecycle regression tests for the graphical game coordinator."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from air_defense.entities import Aircraft
from air_defense.main import AirDefenseGame
from air_defense.rules import LockOnTracker
from air_defense.scene import AirDefenseScene
from air_defense.state import AircraftType, GamePhase, GameSession, SessionEvent


class TerminalGuidanceResetTests(unittest.TestCase):
    def test_present_game_over_clears_tracker_and_projected_target(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.set_anti_air_scope(True)
        game.lock_tracker = LockOnTracker(scope_enabled=True)
        game.lock_tracker.update(True, 3.0)
        game.anti_aircraft = None
        game.active_missiles = {}
        game._missile_sequence = 4
        game._aircraft_screen_target = object()
        game._game_over_presented = False
        game.scene = Mock()
        game.hud = Mock()
        game.session.phase = GamePhase.GAME_OVER

        game._present_game_over()

        self.assertFalse(game.lock_tracker.scope_enabled)
        self.assertEqual(game.lock_tracker.progress, 0.0)
        self.assertIsNone(game._aircraft_screen_target)
        self.assertFalse(game.session.anti_air_scope_enabled)
        self.assertEqual(game.session.lock_elapsed, 0.0)

    def test_aircraft_destruction_transition_clears_tracker_before_ground_combat(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.set_anti_air_scope(True)
        game.lock_tracker = LockOnTracker(scope_enabled=True)
        game.lock_tracker.update(True, 3.0)
        game.aircraft = Aircraft(
            id=game.session.active_aircraft_id or "aircraft-001",
            aircraft_type=AircraftType.NORMAL,
        )
        game.anti_aircraft = None
        game.active_missiles = {}
        game._missile_sequence = 4
        game._aircraft_screen_target = object()
        game.scene = Mock(world=None)
        game.encounter_factory = Mock()
        game.encounter_factory.create_for_aircraft.return_value = SimpleNamespace(cleared=False)

        game._on_aircraft_destroyed()

        self.assertEqual(game.session.phase, GamePhase.GROUND_COMBAT)
        self.assertFalse(game.lock_tracker.scope_enabled)
        self.assertEqual(game.lock_tracker.progress, 0.0)
        self.assertIsNone(game._aircraft_screen_target)

    def test_encounter_transition_does_not_clear_recent_explosion_effects(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        aircraft_id = game.session.active_aircraft_id or "aircraft-001"
        game.session.transition(SessionEvent.AIRCRAFT_DESTROYED, aircraft_id=aircraft_id)
        game.encounter = SimpleNamespace(id=f"encounter:{aircraft_id}")
        game.scene = Mock(world=None)
        game.aircraft = None
        game.anti_aircraft = None
        game.sniper = None
        game.active_missiles = {}
        game._missile_sequence = 1
        game.lock_tracker = LockOnTracker(scope_enabled=True)
        game._aircraft_screen_target = None
        game.wave_director = Mock()
        game._spawn_current_aircraft = Mock()

        game._complete_encounter()

        game.scene.clear_dynamic.assert_called_once_with(clear_effects=False)

    def test_scene_can_clear_entities_while_preserving_short_lived_effects(self) -> None:
        scene = AirDefenseScene.__new__(AirDefenseScene)
        effect = Mock()
        scene.aircraft_entity = None
        scene.crew_entities = {}
        scene.missile_entities = {}
        scene._effects = [(effect, 0.45)]
        scene._dynamic_entities = []

        with patch("air_defense.scene.destroy") as destroy:
            scene.clear_dynamic(clear_effects=False)
            self.assertEqual(scene._effects, [(effect, 0.45)])
            destroy.assert_not_called()

            scene.clear_dynamic()
            destroy.assert_called_once_with(effect)
            self.assertEqual(scene._effects, [])


if __name__ == "__main__":
    unittest.main()
