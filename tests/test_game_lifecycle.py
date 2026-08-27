"""Lifecycle regression tests for the graphical game coordinator."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from air_defense.entities import Aircraft, AntiAircraftGun, Pistol, SniperRifle
from air_defense.hud import GameHUD
from air_defense.main import AirDefenseGame
from air_defense.rules import LockOnTracker
from air_defense.scene import AirDefenseScene
from air_defense.state import (
    AircraftPhase,
    AircraftType,
    FailureReason,
    GamePhase,
    GameSession,
    SessionEvent,
)


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

    def test_lock_reticle_color_reaches_visible_segments(self) -> None:
        reticle = SimpleNamespace(
            color=None,
            children=[SimpleNamespace(color=None), SimpleNamespace(color=None)],
        )
        tint = (0.2, 1.0, 0.35, 1.0)

        GameHUD._set_reticle_color(reticle, tint)

        self.assertEqual(reticle.color, tint)
        self.assertEqual([child.color for child in reticle.children], [tint, tint])

    def test_game_over_keeps_status_card_root_for_final_snapshot(self) -> None:
        hud = GameHUD.__new__(GameHUD)
        hud.menu_root = SimpleNamespace(enabled=True)
        hud.gameplay_root = SimpleNamespace(enabled=False)
        hud.game_over_root = SimpleNamespace(enabled=False)
        hud.failure_text = SimpleNamespace(text="")
        hud.final_stats_text = SimpleNamespace(text="")
        stats = SimpleNamespace(
            failure_reason=None,
            survival_seconds=1.0,
            aircraft_destroyed=2,
            enemies_defeated=3,
        )

        hud.show_game_over(stats)

        self.assertTrue(hud.gameplay_root.enabled)
        self.assertTrue(hud.game_over_root.enabled)
        self.assertFalse(hud.menu_root.enabled)

    def test_scene_removal_forgets_aircraft_and_child_references(self) -> None:
        scene = AirDefenseScene.__new__(AirDefenseScene)
        aircraft = SimpleNamespace(parent=None, aircraft_id="aircraft-a")
        wing = SimpleNamespace(parent=aircraft)
        scene.aircraft_entity = aircraft
        scene.aircraft_entities = {"aircraft-a": aircraft}
        scene.crew_entities = {}
        scene.missile_entities = {}
        scene._dynamic_entities = [aircraft, wing]

        with patch("air_defense.scene.destroy") as destroy:
            scene.remove_aircraft("aircraft-a")

        self.assertEqual(scene._dynamic_entities, [])
        self.assertEqual(scene.aircraft_entities, {})
        self.assertIsNone(scene.aircraft_entity)
        destroy.assert_called_once_with(aircraft)


class WholeWaveLifecycleTests(unittest.TestCase):
    def _runtime_session(self) -> tuple[GameSession, tuple[str, ...]]:
        session = GameSession()
        session.start_new_game()
        ids = ("aircraft-wave-1", "aircraft-wave-2")
        session.initialize_wave_runtime(
            ids,
            {
                ids[0]: AircraftType.NORMAL,
                ids[1]: AircraftType.MANPOWER_SUPPORT,
            },
        )
        return session, ids

    def test_partial_destroy_stays_airstrike_and_duplicate_is_ignored(self) -> None:
        session, ids = self._runtime_session()

        self.assertTrue(session.mark_aircraft_destroyed(ids[0]))
        self.assertFalse(session.mark_aircraft_destroyed(ids[0]))
        self.assertEqual(session.phase, GamePhase.AIRSTRIKE)
        self.assertEqual(session.wave_runtime.remaining_aircraft_count, 1)
        self.assertEqual(session.stats.aircraft_destroyed, 1)

        self.assertEqual(
            session.transition(SessionEvent.AIRCRAFT_DESTROYED, aircraft_id=ids[1]),
            GamePhase.GROUND_COMBAT,
        )
        self.assertEqual(session.wave_runtime.remaining_aircraft_count, 0)
        self.assertEqual(session.active_encounter_id, "encounter:wave-1")

    def test_impact_marks_only_terminal_failure_and_freezes_progress(self) -> None:
        session, ids = self._runtime_session()

        self.assertEqual(
            session.transition(SessionEvent.BUILDING_IMPACT, aircraft_id=ids[1]),
            GamePhase.GAME_OVER,
        )
        self.assertEqual(
            session.wave_runtime.aircraft_statuses[ids[1]],
            AircraftPhase.IMPACTED,
        )
        snapshot = session.stats.snapshot()
        session.tick(10.0)
        self.assertEqual(session.stats.snapshot(), snapshot)
        self.assertEqual(session.stats.failure_reason, FailureReason.BUILDING_IMPACT)
        self.assertEqual(
            session.transition(SessionEvent.AIRCRAFT_DESTROYED, aircraft_id=ids[0]),
            GamePhase.GAME_OVER,
        )

    def test_weapon_boundary_reset_is_central_and_scope_close_preserves_cd(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.anti_aircraft = AntiAircraftGun(world_position=(0, 0, 0))
        game.sniper = SniperRifle(world_position=(0, 0, 0))
        game.pistol = Pistol(world_position=(0, 0, 0))
        game.anti_aircraft.fire_cooldown = 1.0
        game.sniper.fire_cooldown = 0.5
        game.pistol.fire_cooldown = 0.1
        game.sniper.toggle_scope()
        game.sniper.toggle_scope()
        self.assertEqual(game.sniper.fire_cooldown, 0.5)
        self.assertEqual(game.reset_weapon_cooldowns(), 3)
        self.assertEqual(
            (game.anti_aircraft.fire_cooldown, game.sniper.fire_cooldown, game.pistol.fire_cooldown),
            (0.0, 0.0, 0.0),
        )


if __name__ == "__main__":
    unittest.main()
