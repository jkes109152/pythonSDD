"""Lifecycle regression tests for the graphical game coordinator."""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ursina import Vec3

from air_defense.entities import (
    Aircraft,
    AntiAircraftGun,
    GroundEncounter,
    Pistol,
    RPGWeapon,
    SniperRifle,
)
from air_defense.hud import GameHUD
from air_defense.main import AirDefenseGame
from air_defense.rules import LockOnTracker
from air_defense.rules import EncounterFactory, WaveDirector
from air_defense.scene import AirDefenseScene
from air_defense.save_data import SaveStore
from air_defense.state import (
    AircraftPhase,
    AircraftType,
    FailureReason,
    GamePhase,
    GameSession,
    SessionEvent,
    WeaponKind,
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
        self.assertIsNone(session.active_encounter_id)

    def test_runstate_ground_encounter_repairs_stale_controller_cache(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        authoritative = GroundEncounter(
            aircraft_id="wave-1",
            crew=[],
            group_id="wave-1",
        )
        stale = GroundEncounter(
            aircraft_id="wave-old",
            crew=[],
            group_id="wave-old",
        )
        game.session = SimpleNamespace(
            run_state=SimpleNamespace(ground_encounter=authoritative),
        )
        game.encounter = stale

        selected = game._current_ground_encounter()

        self.assertIs(selected, authoritative)
        self.assertIs(game.encounter, authoritative)

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


class AircraftEnemyDescentLifecycleTests(unittest.TestCase):
    def _drop_game(
        self,
        aircraft_types: tuple[AircraftType, ...],
        *,
        wave_number: int = 1,
    ) -> AirDefenseGame:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        plan = WaveDirector().plan_wave(wave_number, aircraft_count=len(aircraft_types), cap=len(aircraft_types))
        game.session.start_new_game(plan)
        ids = tuple(f"drop-aircraft-{index + 1}" for index in range(len(aircraft_types)))
        game.session.initialize_wave_runtime(ids, dict(zip(ids, aircraft_types)))
        game.aircrafts = {
            aircraft_id: Aircraft(
                id=aircraft_id,
                aircraft_type=aircraft_type,
                position=(float(index * 8), 24.0 + index, 50.0 + index),
            )
            for index, (aircraft_id, aircraft_type) in enumerate(zip(ids, aircraft_types))
        }
        game.aircraft = game.aircrafts[ids[0]]
        game.encounter = None
        game.encounter_factory = EncounterFactory(minimum=2, maximum=2)
        game.lock_tracker = LockOnTracker()
        game.anti_aircraft = None
        game.sniper = None
        game.pistol = None
        game.active_missiles = {}
        game._missile_sequence = 0
        game._aircraft_screen_target = None
        game._aircraft_screen_targets = {}
        game._tracer_event_ids = set()
        game.scene = Mock(world=None)
        game.scene.create_crew_members = Mock()
        game.scene.remove_aircraft = Mock()
        game.scene.set_scope_enabled = Mock()
        game.scene.set_gameplay_enabled = Mock()
        game.scene.clear_ground_tracers = Mock()
        game.wave_director = WaveDirector()
        game.hud = Mock()
        game._game_over_presented = False
        game._game_over_snapshot = None
        game._victory_presented = False
        return game

    def test_destroyed_aircraft_immediately_creates_one_source_batch_at_saved_position(self) -> None:
        game = self._drop_game((AircraftType.MANPOWER_SUPPORT, AircraftType.NORMAL))
        aircraft = game.aircrafts["drop-aircraft-1"]
        aircraft.take_damage()
        hit_position = aircraft.position

        game._on_aircraft_destroyed(aircraft.id)

        self.assertEqual(game.session.phase, GamePhase.HYBRID_COMBAT)
        self.assertIsNotNone(game.encounter)
        assert game.encounter is not None
        self.assertEqual(game.encounter.source_aircraft_ids, (aircraft.id,))
        self.assertEqual(len(game.encounter.crew), 6)
        self.assertEqual(game.encounter.crew[0].descent_start_position, hit_position)
        self.assertTrue(any(member.descent_start_position != hit_position for member in game.encounter.crew[1:]))
        self.assertEqual(game.scene.create_crew_members.call_count, 1)
        self.assertEqual(len(game.aircrafts), 1)

        game._on_aircraft_destroyed(aircraft.id)
        self.assertEqual(len(game.encounter.crew), 6)
        self.assertEqual(game.session.stats.aircraft_destroyed, 1)

    def test_empty_fast_drop_does_not_create_an_encounter_or_hybrid_phase(self) -> None:
        game = self._drop_game((AircraftType.FAST, AircraftType.NORMAL))
        aircraft = game.aircrafts["drop-aircraft-1"]
        aircraft.take_damage()

        game._on_aircraft_destroyed(aircraft.id)

        self.assertIsNone(game.encounter)
        self.assertEqual(game.session.phase, GamePhase.AIRSTRIKE)
        self.assertEqual(game.session.wave_runtime.drop_spawned_aircraft_ids, {aircraft.id})

    def test_descending_kill_is_removed_and_counted_once(self) -> None:
        game = self._drop_game((AircraftType.MANPOWER_SUPPORT,))
        aircraft = game.aircrafts["drop-aircraft-1"]
        aircraft.take_damage()
        game._on_aircraft_destroyed(aircraft.id)
        assert game.encounter is not None
        member_id = game.encounter.crew[0].id

        self.assertTrue(game.encounter.crew[0].take_damage())
        self.assertTrue(game.encounter.record_crew_cleared(member_id))
        self.assertFalse(game.encounter.record_crew_cleared(member_id))
        self.assertEqual(game.encounter.batch_progress(aircraft.id).cleared_count, 1)

    def test_multiple_source_batches_run_independently_until_both_aircraft_and_crew_clear(self) -> None:
        game = self._drop_game((AircraftType.MANPOWER_SUPPORT, AircraftType.MANPOWER_SUPPORT))
        first, second = tuple(game.aircrafts.values())
        first.take_damage()
        game._on_aircraft_destroyed(first.id)
        self.assertEqual(game.session.phase, GamePhase.HYBRID_COMBAT)
        second.take_damage()
        game._on_aircraft_destroyed(second.id)
        self.assertEqual(game.session.phase, GamePhase.GROUND_COMBAT)
        assert game.encounter is not None
        self.assertEqual(set(game.encounter.source_aircraft_ids), {first.id, second.id})
        self.assertEqual(game.encounter.batch_progress(first.id).alive_count, 6)
        self.assertEqual(game.encounter.batch_progress(second.id).alive_count, 6)

        for member in game.encounter.crew[:6]:
            member.take_damage()
            game.encounter.record_crew_cleared(member.id)
        game._complete_encounter()
        self.assertEqual(game.session.wave.wave_number, 1)
        self.assertEqual(game.session.phase, GamePhase.GROUND_COMBAT)

        for member in game.encounter.crew[6:]:
            member.take_damage()
            game.encounter.record_crew_cleared(member.id)
        game._complete_encounter()
        self.assertEqual(game.session.wave.wave_number, 2)
        self.assertEqual(game.session.phase, GamePhase.AIRSTRIKE)

    def test_wave_18_empty_drop_enters_victory_without_spawning_wave_19(self) -> None:
        game = self._drop_game((AircraftType.FAST,), wave_number=18)
        aircraft = game.aircrafts["drop-aircraft-1"]
        aircraft.take_damage()

        game._on_aircraft_destroyed(aircraft.id)

        self.assertEqual(game.session.phase, GamePhase.VICTORY)
        self.assertEqual(game.session.wave.wave_number, 18)
        game._on_aircraft_destroyed(aircraft.id)
        self.assertEqual(game.session.wave.wave_number, 18)
        game.input("enter")
        self.assertEqual(game.session.phase, GamePhase.MAIN_MENU)

    def test_hybrid_aircraft_impact_precedes_ground_updates_and_freezes_run(self) -> None:
        game = self._drop_game((AircraftType.MANPOWER_SUPPORT, AircraftType.MANPOWER_SUPPORT))
        first, second = tuple(game.aircrafts.values())
        first.take_damage()
        game._on_aircraft_destroyed(first.id)
        self.assertEqual(game.session.phase, GamePhase.HYBRID_COMBAT)

        game._on_aircraft_impacted(second.id)

        self.assertEqual(game.session.phase, GamePhase.GAME_OVER)
        self.assertIsNone(game.encounter)
        self.assertEqual(game.aircrafts, {})
        game._on_aircraft_impacted(second.id)
        self.assertEqual(game.session.stats.failure_reason, FailureReason.BUILDING_IMPACT)


class WeaponFireGuardTests(unittest.TestCase):
    def test_sniper_does_not_consume_cooldown_without_a_target(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.phase = GamePhase.HYBRID_COMBAT
        game.session.held_weapon = WeaponKind.SNIPER
        game.session.active_encounter_id = "encounter:wave-1"
        game.encounter = SimpleNamespace(id="encounter:wave-1")
        game.sniper = SniperRifle(world_position=(0.0, 0.0, 0.0))
        game.scene = Mock()
        game.scene.crew_under_center.return_value = None
        game.scene.crew_entities = {}

        game._fire_sniper()

        self.assertEqual(game.sniper.fire_cooldown, 0.0)


class RpgCompletionLifecycleTests(unittest.TestCase):
    def test_rpg_clearing_last_ground_batch_settles_the_sublevel(self) -> None:
        """RPG 的多目標擊倒必須走與其他武器相同的通關結算邊界。"""

        with TemporaryDirectory() as temporary_directory:
            store = SaveStore(temporary_directory)
            session = GameSession(save_store=store)
            session.select_save_slot(1)
            assert session.profile is not None
            session.profile.unlocked_weapons.append(WeaponKind.RPG.value)
            run = session.start_sublevel(level_key="1-1")
            aircraft_id = next(iter(run.aircrafts))
            aircraft_type = run.aircrafts[aircraft_id]["aircraft_type"]

            factory = EncounterFactory(minimum=2, maximum=2)
            batch = factory.create_drop_batch(
                aircraft_id,
                aircraft_type,
                "encounter:wave-1",
                (0.0, 0.0, 0.0),
                random_source=SimpleNamespace(randint=lambda lower, upper: lower),
            )
            encounter = GroundEncounter(
                aircraft_id="wave-1",
                group_id="wave-1",
                crew=list(batch),
                source_aircraft_ids=(aircraft_id,),
            )
            session.mark_aircraft_destroyed(aircraft_id)
            session.transition(
                SessionEvent.DROP_STARTED,
                event_id=f"drop-started:1:{aircraft_id}",
                aircraft_id=aircraft_id,
                encounter_id=encounter.id,
            )
            run.ground_encounter = encounter

            game = AirDefenseGame.__new__(AirDefenseGame)
            game.session = session
            game.encounter = None
            game.aircraft = None
            game.aircrafts = {}
            game.encounter_factory = factory
            game.lock_tracker = LockOnTracker()
            game.multi_lock_tracker = SimpleNamespace(reset=lambda: None)
            game.anti_aircraft = AntiAircraftGun(world_position=(0.0, 0.0, 0.0))
            game.sniper = SniperRifle(world_position=(0.0, 0.0, 0.0))
            game.pistol = Pistol(world_position=(0.0, 0.0, 0.0))
            game.rpg = RPGWeapon(
                world_position=(0.0, 0.0, 0.0),
                ammo_remaining=1,
                damage=1,
            )
            game.multi_anti_aircraft = None
            game.turrets = []
            game.active_missiles = {}
            game._rpg_explosion_sequence = 0
            game._aircraft_screen_target = None
            game._aircraft_screen_targets = {}
            game._tracer_event_ids = set()
            game._hit_feedback_seconds = 0.0
            game.scene = Mock(world=None)
            game.scene.player_position.return_value = Vec3(0.0, 0.0, 0.0)
            game.scene.crew_under_center.return_value = batch[0].id
            game.hud = Mock()
            session.held_weapon = WeaponKind.RPG

            game._fire_rpg()

            self.assertEqual(
                session.phase,
                GamePhase.MAIN_MENU,
                msg=(
                    f"phase={session.phase}, alive={encounter.alive_crew}, "
                    f"cleared={encounter.cleared}, runtime={session.wave_runtime}"
                ),
            )
            self.assertIsNone(session.run_state)
            self.assertEqual(session.profile.last_completed_a_b, "1-1")
            self.assertGreater(session.profile.coins, 0)
            self.assertEqual(game.rpg.ammo_remaining, 0)
            self.assertEqual(game.scene.remove_crew_member.call_count, len(batch))


if __name__ == "__main__":
    unittest.main()
