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
    AutoDefenseTurret,
    CrewMember,
    GroundTracerEffect,
    GroundEncounter,
    MultiAntiAircraftGun,
    Player,
    Pistol,
    RPGProjectileEffect,
    RPGWeapon,
    SniperRifle,
)
from air_defense.hud import GameHUD
from air_defense.main import AirDefenseGame
from air_defense.rules import LockOnTracker, MultiLockOnTracker
from air_defense.rules import EncounterFactory, WaveDirector
from air_defense.scene import AirDefenseScene
from air_defense.save_data import SaveProfile, SaveStore
from air_defense.progression import UPGRADE_AA_WHITEBOX, effective_whitebox_scale, purchase_upgrade
from air_defense import config
from air_defense.state import (
    AntiAirGuiMode,
    AircraftPhase,
    AircraftType,
    CrewBehaviorState,
    FailureReason,
    GamePhase,
    GameSession,
    LockState,
    SessionEvent,
    SquadRole,
    WeaponKind,
)


class AntiAirSettingsTests(unittest.TestCase):
    def test_settings_mode_is_runtime_only_and_can_return_to_menu(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = SimpleNamespace(phase=GamePhase.MAIN_MENU)
        game.hud = Mock()
        game.anti_air_gui_mode = AntiAirGuiMode.NEW
        game._settings_open = False

        game.open_settings()
        self.assertTrue(game._settings_open)
        game.hud.show_settings.assert_called_once_with(AntiAirGuiMode.NEW)

        game.set_anti_air_gui_mode("LEGACY")
        self.assertEqual(game.anti_air_gui_mode, AntiAirGuiMode.LEGACY)
        game.hud.update_settings_mode.assert_called_once_with(AntiAirGuiMode.LEGACY)

        game.close_settings()
        self.assertFalse(game._settings_open)
        game.hud.show_main_menu.assert_called_once_with()

    def test_invalid_settings_mode_does_not_change_selected_mode(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = SimpleNamespace(phase=GamePhase.MAIN_MENU)
        game.hud = Mock()
        game.anti_air_gui_mode = AntiAirGuiMode.LEGACY
        game._settings_open = False

        game.set_anti_air_gui_mode("not-a-mode")

        self.assertEqual(game.anti_air_gui_mode, AntiAirGuiMode.LEGACY)


class TerminalGuidanceResetTests(unittest.TestCase):
    def test_hud_transient_weapon_reset_hides_all_feedback_widgets(self) -> None:
        hud = GameHUD.__new__(GameHUD)
        hud.lock_frame = SimpleNamespace(enabled=True, children=[])
        hud.lock_ring = SimpleNamespace(enabled=True)
        hud.lock_reticle = SimpleNamespace(enabled=True)
        hud.sniper_crosshair = SimpleNamespace(enabled=True)
        hud.pistol_reticle = SimpleNamespace(enabled=True)
        hud.rpg_reticle = SimpleNamespace(enabled=True)
        hud.scope_overlay = SimpleNamespace(enabled=True)
        hud.lock_label = SimpleNamespace(enabled=True)
        hud.lock_percent_text = SimpleNamespace(enabled=True, text="鎖定 100%")
        hud.lock_bar_background = SimpleNamespace(enabled=True)
        hud.lock_bar_fill = SimpleNamespace(enabled=True, scale_x=1.0)
        hud.cooldown_bar_background = SimpleNamespace(enabled=True)
        hud.cooldown_bar_fill = SimpleNamespace(enabled=True, scale_x=1.0)
        hud.cooldown_text = SimpleNamespace(enabled=True, text="AA 1.0s")

        hud.clear_transient_weapon_ui()

        self.assertFalse(hud.lock_frame.enabled)
        for widget_name in (
            "lock_ring",
            "lock_reticle",
            "sniper_crosshair",
            "pistol_reticle",
            "rpg_reticle",
            "scope_overlay",
            "lock_label",
            "lock_percent_text",
            "lock_bar_background",
            "lock_bar_fill",
            "cooldown_bar_background",
            "cooldown_bar_fill",
            "cooldown_text",
        ):
            self.assertFalse(getattr(hud, widget_name).enabled, widget_name)
        self.assertEqual(hud.lock_bar_fill.scale_x, 0.0)
        self.assertEqual(hud.cooldown_bar_fill.scale_x, 0.0)
        self.assertEqual(hud.cooldown_text.text, "")

    def test_guidance_reset_clears_hud_but_keeps_in_flight_missiles(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.lock_tracker = LockOnTracker(scope_enabled=True)
        game.multi_lock_tracker = SimpleNamespace(reset=Mock())
        game.anti_aircraft = None
        game.multi_anti_aircraft = None
        game.scene = Mock()
        game.hud = Mock()
        missile = object()
        game.active_missiles = {"missile-001": missile}

        game._reset_airstrike_guidance(clear_missiles=False)

        game.hud.clear_transient_weapon_ui.assert_called_once_with()
        self.assertEqual(game.active_missiles, {"missile-001": missile})

    def test_guidance_cleanup_matrix_resets_multi_lock_without_canceling_flight(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.phase = GamePhase.AIRSTRIKE
        game.session.held_weapon = WeaponKind.MULTI_ANTI_AIRCRAFT
        game.session.set_anti_air_scope(True)
        game.lock_tracker = LockOnTracker(scope_enabled=True)
        game.multi_lock_tracker = MultiLockOnTracker(scope_enabled=True)
        game.multi_lock_tracker.set_targets(("aircraft-live",))
        game.anti_aircraft = AntiAircraftGun(world_position=(0, 0, 0))
        game.multi_anti_aircraft = MultiAntiAircraftGun(world_position=(0, 0, 0))
        game.multi_anti_aircraft.set_targets(("aircraft-live",))
        game.scene = Mock()
        game.hud = Mock()
        in_flight = object()
        game.active_missiles = {"missile-live": in_flight}
        game.active_volleys = {"volley-live": object()}

        game._reset_airstrike_guidance(clear_missiles=False)

        self.assertEqual(game.multi_lock_tracker.target_ids, ())
        self.assertEqual(game.multi_anti_aircraft.target_aircraft_ids, [])
        self.assertEqual(game.active_missiles, {"missile-live": in_flight})
        self.assertEqual(set(game.active_volleys), {"volley-live"})
        game.hud.clear_transient_weapon_ui.assert_called_once_with()

    def test_profile_weapon_switch_resets_both_lock_families(self) -> None:
        profile = SaveProfile(
            unlocked_weapons=[
                WeaponKind.ANTI_AIRCRAFT.value,
                WeaponKind.MULTI_ANTI_AIRCRAFT.value,
            ]
        )
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession(profile=profile)
        game.session.phase = GamePhase.AIRSTRIKE
        game.session.held_weapon = WeaponKind.MULTI_ANTI_AIRCRAFT
        game.player = Player(held_weapon=WeaponKind.MULTI_ANTI_AIRCRAFT)
        game.lock_tracker = LockOnTracker(scope_enabled=True)
        game.multi_lock_tracker = MultiLockOnTracker(scope_enabled=True)
        game.multi_lock_tracker.set_targets(("aircraft-switch",))
        game.anti_aircraft = AntiAircraftGun(world_position=(0, 0, 0))
        game.multi_anti_aircraft = MultiAntiAircraftGun(world_position=(0, 0, 0))
        game.scene = Mock()
        game.hud = Mock()
        game.active_missiles = {"missile-switch": object()}
        game.active_volleys = {"volley-switch": object()}

        game._select_weapon(WeaponKind.ANTI_AIRCRAFT)

        self.assertEqual(game.session.held_weapon, WeaponKind.ANTI_AIRCRAFT)
        self.assertEqual(game.multi_lock_tracker.target_ids, ())
        self.assertEqual(game.active_missiles.keys(), {"missile-switch"})
        game.hud.clear_transient_weapon_ui.assert_called_once_with()

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

    def test_scene_clear_dynamic_removes_rpg_projectiles_and_effect_state(self) -> None:
        scene = AirDefenseScene.__new__(AirDefenseScene)
        projectile = Mock()
        scene.aircraft_entity = None
        scene.aircraft_entities = {}
        scene.crew_entities = {}
        scene.missile_entities = {}
        scene.rpg_projectile_entities = {"rpg-projectile-1": projectile}
        scene.rpg_projectile_effects = {"rpg-projectile-1": Mock()}
        scene.turret_entities = {}
        scene.multi_lock_entities = {}
        scene.tracer_entities = {}
        scene.tracer_effects = {}
        scene._effects = []
        scene._dynamic_entities = []

        with patch("air_defense.scene.destroy") as destroy:
            scene.clear_dynamic()

        destroy.assert_called_once_with(projectile)
        self.assertEqual(scene.rpg_projectile_entities, {})
        self.assertEqual(scene.rpg_projectile_effects, {})

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

        self.assertTrue(game.encounter.crew[0].take_damage(config.GROUND_MINION_HEALTH))
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
            member.take_damage(config.GROUND_MINION_HEALTH)
            game.encounter.record_crew_cleared(member.id)
        game._complete_encounter()
        self.assertEqual(game.session.wave.wave_number, 1)
        self.assertEqual(game.session.phase, GamePhase.GROUND_COMBAT)

        for member in game.encounter.crew[6:]:
            member.take_damage(config.GROUND_MINION_HEALTH)
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
    def test_rpg_out_of_range_does_not_consume_ammo_or_cooldown(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.phase = GamePhase.GROUND_COMBAT
        game.session.held_weapon = WeaponKind.RPG
        target = SimpleNamespace(
            id="crew-too-far",
            alive=True,
            health=1,
            position=(20.0, 0.0, 0.0),
            take_damage=Mock(),
        )
        game.encounter = SimpleNamespace(find=lambda target_id: target if target_id == target.id else None)
        game._current_ground_encounter = lambda: game.encounter
        game.rpg = RPGWeapon(world_position=(0.0, 0.0, 0.0), ammo_remaining=2, damage=35)
        game._rpg_explosion_sequence = 0
        game.scene = Mock()
        game.scene.player_position.return_value = Vec3(0.0, 0.0, 0.0)
        game.scene.crew_under_center.return_value = target.id
        ammo_before = game.rpg.ammo_remaining

        game._fire_rpg()

        self.assertEqual(game.rpg.ammo_remaining, ammo_before)
        self.assertEqual(game.rpg.fire_cooldown, 0.0)
        target.take_damage.assert_not_called()

    def test_rpg_fire_creates_one_green_projectile_without_duplicate_damage(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.phase = GamePhase.GROUND_COMBAT
        game.session.held_weapon = WeaponKind.RPG
        target = SimpleNamespace(
            id="crew-rpg-visual",
            alive=True,
            health=1,
            position=(4.0, 0.0, 0.0),
            take_damage=Mock(),
        )
        encounter = SimpleNamespace(
            id="encounter:rpg-visual",
            crew=[target],
            refresh_cleared=Mock(),
            find=lambda target_id: target if target_id == target.id else None,
        )
        game.session.active_encounter_id = encounter.id
        game.encounter = encounter
        game._current_ground_encounter = lambda: encounter
        game.aircrafts = {}
        game.rpg = RPGWeapon(
            world_position=(0.0, 0.0, 0.0),
            ammo_remaining=1,
            damage=1,
        )
        game.scene = Mock(world=None)
        game.scene.player_position.return_value = Vec3(0.0, 1.0, 0.0)
        game.scene.crew_under_center.return_value = target.id
        game.hud = Mock()
        game._rpg_explosion_sequence = 0
        game._hit_feedback_seconds = 0.0
        game._try_complete_encounter = Mock(return_value=False)

        with patch(
            "air_defense.main.camera",
            SimpleNamespace(
                world_position=Vec3(0.0, 1.0, 0.0),
                forward=Vec3(0.0, 0.0, 1.0),
            ),
        ):
            game._fire_rpg()

        game.scene.create_rpg_projectile.assert_called_once()
        projectile = game.scene.create_rpg_projectile.call_args.args[0]
        self.assertIsInstance(projectile, RPGProjectileEffect)
        self.assertEqual(projectile.visual_color, config.GREEN_RGB)
        self.assertGreater(projectile.length, projectile.width)
        target.take_damage.assert_called_once_with(1)
        game.scene.create_rpg_explosion.assert_called_once()


class AutoDefenseLifecycleTests(unittest.TestCase):
    def test_auto_defense_fire_creates_enemy_style_tracer_and_needs_three_shots(self) -> None:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.phase = GamePhase.GROUND_COMBAT
        member = CrewMember(
            id="crew-auto-visual",
            encounter_id="encounter:auto-visual",
            cover_node=config.COVER_NODES[0],
            squad_role=SquadRole.COVER_SHOOTER,
            position=(0.0, 0.0, 0.0),
            behavior_state=CrewBehaviorState.IN_COVER,
            health=3,
            max_health=3,
        )
        encounter = GroundEncounter(
            aircraft_id="auto-visual",
            group_id="auto-visual",
            crew=[member],
            source_aircraft_ids=("aircraft-auto-visual",),
        )
        game.session.active_encounter_id = encounter.id
        turret = AutoDefenseTurret(
            id="turret-visual",
            position=(0.0, 0.0, 0.0),
            damage=1,
            cooldown_seconds=config.PISTOL_FIRE_COOLDOWN_SECONDS,
        )
        game.turrets = [turret]
        game.scene = Mock()
        game._tracer_event_ids = set()

        for shot_number in range(3):
            if shot_number:
                turret.update(config.PISTOL_FIRE_COOLDOWN_SECONDS)
            game._update_auto_defense_turrets(encounter)

        self.assertEqual(member.health, 0)
        self.assertFalse(member.alive)
        self.assertEqual(game.scene.create_ground_tracer.call_count, 3)
        first_tracer = game.scene.create_ground_tracer.call_args_list[0].args[0]
        self.assertIsInstance(first_tracer, GroundTracerEffect)
        self.assertEqual(first_tracer.visual_color, config.YELLOW_RGB)
        self.assertEqual(first_tracer.start_position, turret.position)
        self.assertEqual(first_tracer.target_position, member.position)
        game.scene.remove_crew_member.assert_called_once_with(member.id)

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
                damage=35,
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


class MultiAntiAircraftLifecycleTests(unittest.TestCase):
    def _game_with_ready_targets(self, count: int = 3) -> AirDefenseGame:
        game = AirDefenseGame.__new__(AirDefenseGame)
        game.session = GameSession()
        game.session.start_new_game()
        game.session.phase = GamePhase.AIRSTRIKE
        game.session.held_weapon = WeaponKind.MULTI_ANTI_AIRCRAFT
        game.session.set_anti_air_scope(True)
        ids = tuple(f"aircraft-volley-{index}" for index in range(count))
        game.aircrafts = {
            target_id: Aircraft(
                id=target_id,
                aircraft_type=AircraftType.NORMAL,
                position=(float(index), 10.0, 10.0 + index),
            )
            for index, target_id in enumerate(ids)
        }
        game.aircraft = next(iter(game.aircrafts.values()))
        game.multi_anti_aircraft = MultiAntiAircraftGun(world_position=(0, 0, 0))
        game.multi_lock_tracker = MultiLockOnTracker(lock_duration=1.0)
        game.multi_lock_tracker.update(
            {
                target_id: SimpleNamespace(
                    id=target_id,
                    visible=True,
                    in_lock_frame=True,
                )
                for target_id in ids
            },
            1.0,
        )
        game._aircraft_screen_targets = {
            target_id: SimpleNamespace(
                aircraft_id=target_id,
                visible=True,
                in_lock_frame=True,
                eligible=True,
                screen_position=(0.0, 0.0),
                hud_position=(0.0, 0.0),
            )
            for target_id in ids
        }
        game.scene = Mock()
        game.scene.player_position.return_value = Vec3(0.0, 0.0, 0.0)
        game.scene.create_guided_missile = Mock()
        game.scene.remove_guided_missile = Mock()
        game.active_missiles = {}
        game._missile_sequence = 0
        game.hud = Mock()
        game.lock_tracker = LockOnTracker()
        game.anti_aircraft = None
        game._hit_feedback_seconds = 0.0
        return game

    def test_multi_fire_creates_one_guided_missile_per_target_without_direct_damage(self) -> None:
        game = self._game_with_ready_targets(10)
        health_before = {target_id: target.health for target_id, target in game.aircrafts.items()}

        with patch(
            "air_defense.main.camera",
            SimpleNamespace(world_position=Vec3(0.0, 1.0, 0.0), forward=Vec3(0.0, 0.0, 1.0)),
        ):
            game._fire_multi_anti_aircraft()

        self.assertEqual(len(game.active_missiles), 10)
        self.assertEqual(
            {missile.target_aircraft_id for missile in game.active_missiles.values()},
            set(game.aircrafts),
        )
        self.assertEqual(
            {target_id: target.health for target_id, target in game.aircrafts.items()},
            health_before,
        )
        self.assertGreater(game.multi_anti_aircraft.fire_cooldown, 0.0)
        self.assertEqual(len(game.active_volleys), 1)

        game.active_missiles.clear()
        game._prune_active_volleys()
        self.assertEqual(game.active_volleys, {})

    def test_multi_fire_rejects_partial_lock_without_cooldown_or_missile(self) -> None:
        game = self._game_with_ready_targets(3)
        partial_id = game.multi_lock_tracker.target_ids[0]
        game.multi_lock_tracker.trackers[partial_id].lock_elapsed = 0.2
        game.multi_lock_tracker.trackers[partial_id].state = LockState.RED_TRACKING

        with patch(
            "air_defense.main.camera",
            SimpleNamespace(world_position=Vec3(0.0, 1.0, 0.0), forward=Vec3(0.0, 0.0, 1.0)),
        ):
            game._fire_multi_anti_aircraft()

        self.assertEqual(game.active_missiles, {})
        self.assertEqual(game.multi_anti_aircraft.fire_cooldown, 0.0)


class WhiteboxUpgradeLifecycleTests(unittest.TestCase):
    def test_whitebox_upgrade_survives_save_reload_and_preserves_multi_ratio(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            store = SaveStore(temporary_directory)
            upgraded = purchase_upgrade(
                SaveProfile(coins=10_000),
                UPGRADE_AA_WHITEBOX,
            )
            self.assertTrue(store.save_slot(1, upgraded).success)
            loaded = store.load_slot(1).profile

            scale = effective_whitebox_scale(loaded)
            ordinary_size = config.AA_LOCK_FRAME_SIZE * scale
            multi_size = ordinary_size * config.AA_MULTI_LOCK_FRAME_MULTIPLIER

            self.assertAlmostEqual(scale, 1.10)
            self.assertAlmostEqual(multi_size / ordinary_size, 2.0)
            self.assertNotEqual(ordinary_size, config.AA_LOCK_FRAME_SIZE)


if __name__ == "__main__":
    unittest.main()
