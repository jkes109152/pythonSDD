"""Deterministic tests for the engine-independent game rules."""

from __future__ import annotations

import unittest
from math import dist
from pathlib import Path
from unittest.mock import patch

from air_defense import config
from air_defense.entities import (
    Aircraft,
    AntiAircraftGun,
    BatchProgress,
    CrewMember,
    GuidedMissile,
    GroundEncounter,
    MissileStep,
    Player,
    SniperRifle,
    TargetBuilding,
)
from air_defense.rules import (
    EncounterFactory,
    LockOnTracker,
    add_reinforcement,
    aircraft_profile,
    advance_crew_behavior,
    apply_guided_missile_damage,
    can_fire_anti_air,
    can_fire_pistol,
    can_fire_sniper,
    damage_crew_member,
    defeat_crew_member,
    drop_weapon,
    inventory_selection_allowed,
    normalize_aircraft_token,
    lock_status_label,
    apply_city_damage,
    resolve_aircraft_outcome,
    try_pickup_weapon,
    WaveDirector,
    warning_active,
)
from air_defense.state import (
    AircraftType,
    CrewBehaviorState,
    FailureReason,
    GamePhase,
    GameSession,
    LockState,
    SessionEvent,
    SessionStats,
    SquadRole,
    WeaponKind,
    WaveProgress,
    WavePlan,
    WaveRuntime,
)


class FixedRandom:
    def __init__(self, value: int) -> None:
        self.value = value
        self.calls: list[tuple[int, int]] = []

    def randint(self, minimum: int, maximum: int) -> int:
        self.calls.append((minimum, maximum))
        return max(minimum, min(maximum, self.value))


class SessionStateTests(unittest.TestCase):
    def test_new_session_starts_clean(self) -> None:
        session = GameSession()

        self.assertEqual(session.phase, GamePhase.MAIN_MENU)
        self.assertEqual(session.health, session.max_health)
        self.assertIsNone(session.held_weapon)
        self.assertEqual(session.stats.aircraft_destroyed, 0)
        self.assertEqual(session.stats.enemies_defeated, 0)

    def test_legal_and_illegal_transitions_are_guarded(self) -> None:
        session = GameSession()

        self.assertEqual(session.transition(SessionEvent.AIRCRAFT_DESTROYED), GamePhase.MAIN_MENU)
        self.assertEqual(session.transition(SessionEvent.START_GAME), GamePhase.AIRSTRIKE)
        self.assertEqual(
            session.transition(SessionEvent.AIRCRAFT_DESTROYED),
            GamePhase.GROUND_COMBAT,
        )
        self.assertEqual(
            session.transition(SessionEvent.AIRCRAFT_DESTROYED),
            GamePhase.GROUND_COMBAT,
        )
        self.assertEqual(session.stats.aircraft_destroyed, 1)

    def test_crew_clear_starts_next_aircraft_and_return_resets(self) -> None:
        session = GameSession()
        session.start_new_game()
        first_aircraft = session.active_aircraft_id
        session.transition(SessionEvent.AIRCRAFT_DESTROYED)

        self.assertEqual(session.transition(SessionEvent.CREW_CLEARED), GamePhase.AIRSTRIKE)
        self.assertNotEqual(session.active_aircraft_id, first_aircraft)
        session.stats.aircraft_destroyed = 3
        session.health = 20
        session.transition(SessionEvent.BUILDING_IMPACT)
        self.assertEqual(session.phase, GamePhase.GAME_OVER)
        self.assertEqual(session.stats.failure_reason, FailureReason.BUILDING_IMPACT)
        self.assertEqual(session.transition(SessionEvent.RETURN_TO_MENU), GamePhase.MAIN_MENU)
        self.assertEqual(session.health, session.max_health)
        self.assertEqual(session.stats.aircraft_destroyed, 0)
        self.assertIsNone(session.active_aircraft_id)

    def test_city_failure_is_terminal_and_reset_clears_wave_state(self) -> None:
        session = GameSession()
        session.start_new_game()
        session.transition(SessionEvent.AIRCRAFT_DESTROYED)

        self.assertTrue(session.take_city_damage(config.CITY_MAX_HEALTH))
        self.assertEqual(session.phase, GamePhase.GAME_OVER)
        self.assertEqual(session.stats.failure_reason, FailureReason.CITY_DESTROYED)
        self.assertEqual(session.city_health, 0.0)
        session.transition(SessionEvent.RETURN_TO_MENU)
        self.assertEqual(session.phase, GamePhase.MAIN_MENU)
        self.assertEqual(session.wave.wave_number, 1)
        self.assertEqual(session.city_health, config.CITY_MAX_HEALTH)

    def test_stale_aircraft_and_encounter_events_are_ignored(self) -> None:
        session = GameSession()
        session.start_new_game()
        first_aircraft = session.active_aircraft_id

        self.assertEqual(
            session.transition(
                SessionEvent.AIRCRAFT_DESTROYED,
                aircraft_id="aircraft-stale",
            ),
            GamePhase.AIRSTRIKE,
        )
        self.assertEqual(
            session.transition(
                SessionEvent.BUILDING_IMPACT,
                aircraft_id="aircraft-stale",
            ),
            GamePhase.AIRSTRIKE,
        )

        self.assertEqual(
            session.transition(
                SessionEvent.AIRCRAFT_DESTROYED,
                aircraft_id=first_aircraft,
            ),
            GamePhase.GROUND_COMBAT,
        )
        first_encounter = session.active_encounter_id
        self.assertEqual(
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id="encounter:stale",
            ),
            GamePhase.GROUND_COMBAT,
        )
        self.assertEqual(session.active_encounter_id, first_encounter)

        self.assertEqual(
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id=first_encounter,
            ),
            GamePhase.AIRSTRIKE,
        )
        self.assertEqual(
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id=first_encounter,
            ),
            GamePhase.AIRSTRIKE,
        )
        self.assertEqual(
            session.transition(
                SessionEvent.BUILDING_IMPACT,
                aircraft_id=first_aircraft,
            ),
            GamePhase.AIRSTRIKE,
        )


class LockAndWeaponRuleTests(unittest.TestCase):
    def test_lock_tracker_decays_when_target_is_lost(self) -> None:
        tracker = LockOnTracker(lock_duration=3.0, scope_enabled=True)

        self.assertEqual(tracker.update(True, 1.0), LockState.RED_TRACKING)
        self.assertEqual(tracker.update(False, 0.01), LockState.RED_TRACKING)
        self.assertAlmostEqual(tracker.lock_elapsed, 0.96, places=6)
        self.assertEqual(tracker.update(False, 0.75), LockState.WHITE)
        self.assertEqual(tracker.lock_elapsed, 0.0)

    def test_one_weapon_at_a_time(self) -> None:
        picked, weapon = try_pickup_weapon(
            None,
            WeaponKind.ANTI_AIRCRAFT,
            in_range=True,
        )
        self.assertTrue(picked)
        self.assertEqual(weapon, WeaponKind.ANTI_AIRCRAFT)

        picked_again, same_weapon = try_pickup_weapon(
            weapon,
            WeaponKind.SNIPER,
            in_range=True,
        )
        self.assertFalse(picked_again)
        self.assertEqual(same_weapon, WeaponKind.ANTI_AIRCRAFT)
        dropped, empty = drop_weapon(weapon)
        self.assertTrue(dropped)
        self.assertIsNone(empty)

    def test_lock_flash_period_and_exact_ready_threshold(self) -> None:
        tracker = LockOnTracker(lock_duration=3.0, scope_enabled=True)

        self.assertEqual(tracker.update(True, 0.11), LockState.RED_TRACKING)
        self.assertTrue(tracker.flash_visible(0.12))
        tracker.update(True, 0.02)
        self.assertFalse(tracker.flash_visible(0.12))

        tracker.reset()
        self.assertEqual(tracker.update(True, 2.99), LockState.RED_TRACKING)
        self.assertEqual(tracker.lock_elapsed, 2.99)
        self.assertEqual(tracker.update(True, 0.01), LockState.GREEN_READY)
        self.assertEqual(tracker.lock_elapsed, 3.0)
        self.assertEqual(lock_status_label(LockState.WHITE), "未鎖定")
        self.assertEqual(lock_status_label(LockState.RED_TRACKING), "鎖定中")
        self.assertEqual(lock_status_label(LockState.GREEN_READY), "可發射")

    def test_lock_loss_warning_and_fire_gates(self) -> None:
        tracker = LockOnTracker(scope_enabled=True)
        tracker.update(True, 2.0)
        self.assertEqual(tracker.update(False, 0.0), LockState.RED_TRACKING)
        self.assertEqual(tracker.lock_elapsed, 2.0)
        self.assertEqual(tracker.update(False, 0.75), LockState.WHITE)
        self.assertEqual(tracker.lock_elapsed, 0.0)

        self.assertTrue(warning_active(8.0))
        self.assertFalse(warning_active(8.01))
        self.assertFalse(warning_active(None))
        self.assertFalse(can_fire_anti_air(LockState.RED_TRACKING, 0.0))
        self.assertTrue(can_fire_anti_air(LockState.GREEN_READY, 0.0, target_in_zone=True))
        self.assertFalse(can_fire_anti_air(LockState.GREEN_READY, 0.01, target_in_zone=True))
        self.assertFalse(
            can_fire_anti_air(
                LockState.GREEN_READY,
                0.0,
                WeaponKind.SNIPER,
                False,
            )
        )
        self.assertTrue(can_fire_sniper(0.0, WeaponKind.SNIPER))
        self.assertFalse(can_fire_sniper(0.01, WeaponKind.SNIPER))

    def test_inventory_slots_are_direct_and_phase_limited(self) -> None:
        self.assertTrue(
            inventory_selection_allowed(
                GamePhase.AIRSTRIKE,
                WeaponKind.ANTI_AIRCRAFT,
            )
        )
        self.assertTrue(
            inventory_selection_allowed(
                GamePhase.GROUND_COMBAT,
                WeaponKind.SNIPER,
            )
        )
        self.assertFalse(
            inventory_selection_allowed(
                GamePhase.AIRSTRIKE,
                WeaponKind.SNIPER,
            )
        )
        self.assertFalse(
            inventory_selection_allowed(
                GamePhase.GROUND_COMBAT,
                WeaponKind.ANTI_AIRCRAFT,
            )
        )
        self.assertTrue(
            inventory_selection_allowed(
                GamePhase.GROUND_COMBAT,
                WeaponKind.PISTOL,
            )
        )
        self.assertFalse(
            inventory_selection_allowed(
                GamePhase.AIRSTRIKE,
                WeaponKind.PISTOL,
            )
        )


class GroundEncounterRuleTests(unittest.TestCase):
    def test_factory_assigns_one_finite_group_with_roles_and_cover(self) -> None:
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-007",
            random_source=FixedRandom(5),
        )

        self.assertEqual(encounter.crew_count, 3)
        self.assertEqual(len(encounter.crew), 3)
        self.assertEqual(
            {member.encounter_id for member in encounter.crew},
            {encounter.id},
        )
        self.assertTrue(
            all(member.cover_node in config.COVER_NODES for member in encounter.crew)
        )
        self.assertEqual(
            {member.squad_role.value for member in encounter.crew},
            {"COVER_SHOOTER", "ADVANCE_SHOOTER"},
        )
        self.assertFalse(encounter.cleared)
        self.assertFalse(add_reinforcement(encounter))

    def test_advance_shooter_moves_only_after_two_seconds(self) -> None:
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-008",
            random_source=FixedRandom(2),
        )
        cover_shooter, advance_shooter = encounter.crew
        original_cover = cover_shooter.cover_node
        original_advance_cover = advance_shooter.cover_node

        advance_crew_behavior(encounter, config.CREW_ADVANCE_INTERVAL_SECONDS - 0.01)
        self.assertEqual(cover_shooter.cover_node, original_cover)
        self.assertEqual(advance_shooter.cover_node, original_advance_cover)
        self.assertEqual(advance_shooter.behavior_state.value, "IN_COVER")

        advance_crew_behavior(encounter, 0.01)
        self.assertNotEqual(advance_shooter.cover_node, original_advance_cover)
        self.assertEqual(advance_shooter.behavior_state, CrewBehaviorState.ADVANCING)
        advance_crew_behavior(encounter, 0.0)
        self.assertEqual(advance_shooter.behavior_state, CrewBehaviorState.RELOCATING)
        advance_crew_behavior(encounter, 0.0)
        self.assertEqual(advance_shooter.behavior_state, CrewBehaviorState.IN_COVER)
        self.assertEqual(cover_shooter.behavior_state.value, "IN_COVER")

    def test_manual_weapon_transfer_scope_hit_and_health_failure(self) -> None:
        player = Player()
        anti_aircraft = AntiAircraftGun(world_position=(0.0, 0.0, 0.0))
        sniper = SniperRifle(world_position=(1.0, 0.0, 0.0))

        self.assertTrue(player.pick_up(anti_aircraft))
        self.assertFalse(player.pick_up(sniper))
        dropped = player.drop_weapon((2.0, 0.0, 0.0))
        self.assertIsNotNone(dropped)
        self.assertEqual(dropped.kind, WeaponKind.ANTI_AIRCRAFT)
        self.assertTrue(player.pick_up(sniper))
        self.assertTrue(sniper.toggle_scope())
        self.assertTrue(sniper.scope_enabled)

        session = GameSession()
        session.start_new_game()
        session.transition(SessionEvent.AIRCRAFT_DESTROYED)
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-001",
            random_source=FixedRandom(2),
        )
        target = encounter.crew[0]
        self.assertTrue(defeat_crew_member(encounter, target.id, session))
        self.assertFalse(target.alive)
        self.assertFalse(defeat_crew_member(encounter, target.id, session))
        self.assertEqual(session.stats.enemies_defeated, 1)
        self.assertTrue(can_fire_sniper(0.0, WeaponKind.SNIPER))
        sniper.mark_fired(target.id)
        self.assertFalse(can_fire_sniper(sniper.fire_cooldown, WeaponKind.SNIPER))

        self.assertTrue(session.take_damage(session.health))
        self.assertEqual(session.phase, GamePhase.GAME_OVER)
        self.assertEqual(session.stats.failure_reason, FailureReason.PLAYER_DEAD)

    def test_stale_or_terminal_crew_damage_is_ignored(self) -> None:
        session = GameSession()
        session.start_new_game()
        session.transition(SessionEvent.AIRCRAFT_DESTROYED)
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-current",
            AircraftType.MANPOWER_SUPPORT,
        )
        target = encounter.crew[0]

        self.assertFalse(damage_crew_member(encounter, target.id, 1, session))
        self.assertTrue(target.alive)

        session.active_encounter_id = encounter.id
        self.assertTrue(damage_crew_member(encounter, target.id, 1, session))
        self.assertEqual(session.stats.enemies_defeated, 1)

        replacement = EncounterFactory().create_for_aircraft(
            "aircraft-replacement",
            AircraftType.MANPOWER_SUPPORT,
        )
        replacement_target = replacement.crew[0]
        session.transition(SessionEvent.PLAYER_DIED)
        self.assertFalse(
            damage_crew_member(replacement, replacement_target.id, 1, session)
        )
        self.assertTrue(replacement_target.alive)


class StatisticsTests(unittest.TestCase):
    def test_record_once_prevents_duplicate_updates(self) -> None:
        stats = SessionStats()

        self.assertTrue(stats.record_once("aircraft-1", "aircraft_destroyed"))
        self.assertFalse(stats.record_once("aircraft-1", "aircraft_destroyed"))
        self.assertEqual(stats.aircraft_destroyed, 1)

    def test_aircraft_outcome_is_first_event_wins(self) -> None:
        session = GameSession()
        session.start_new_game()
        first = resolve_aircraft_outcome(
            session,
            aircraft_id="aircraft-001",
            outcome="destroyed",
        )
        second = resolve_aircraft_outcome(
            session,
            aircraft_id="aircraft-001",
            outcome="building_impact",
        )
        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertEqual(session.phase, GamePhase.GROUND_COMBAT)
        self.assertEqual(session.stats.aircraft_destroyed, 1)

        impact_session = GameSession()
        impact_session.start_new_game()
        impact = resolve_aircraft_outcome(
            impact_session,
            aircraft_id="aircraft-001",
            outcome="building_impact",
        )
        ignored_destroy = resolve_aircraft_outcome(
            impact_session,
            aircraft_id="aircraft-001",
            outcome="destroyed",
        )
        self.assertTrue(impact.success)
        self.assertFalse(ignored_destroy.success)
        self.assertEqual(
            impact_session.stats.failure_reason,
            FailureReason.BUILDING_IMPACT,
        )

    def test_cycle_restriction_duplicate_events_and_clean_reset(self) -> None:
        session = GameSession()
        session.start_new_game()
        session.held_weapon = WeaponKind.SNIPER
        self.assertFalse(session.can_use_anti_air())
        self.assertFalse(
            can_fire_anti_air(
                LockState.GREEN_READY,
                0.0,
                session.held_weapon,
                target_in_zone=True,
            )
        )
        session.transition(SessionEvent.AIRCRAFT_DESTROYED)
        current_encounter = session.active_encounter_id
        self.assertEqual(
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id=current_encounter,
            ),
            GamePhase.AIRSTRIKE,
        )
        next_aircraft = session.active_aircraft_id
        self.assertEqual(
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id=current_encounter,
            ),
            GamePhase.AIRSTRIKE,
        )
        self.assertEqual(session.active_aircraft_id, next_aircraft)

        session.stats.record_once("aircraft-002", "aircraft_destroyed")
        session.transition(SessionEvent.BUILDING_IMPACT, aircraft_id=next_aircraft)
        session.transition(SessionEvent.PLAYER_DIED)
        self.assertEqual(session.stats.failure_reason, FailureReason.BUILDING_IMPACT)
        session.transition(SessionEvent.RETURN_TO_MENU)
        self.assertEqual(session.phase, GamePhase.MAIN_MENU)
        self.assertEqual(session.health, session.max_health)
        self.assertIsNone(session.held_weapon)
        self.assertEqual(session.stats.aircraft_destroyed, 0)
        self.assertEqual(session.stats.enemies_defeated, 0)

    def test_five_complete_cycles_and_frozen_failure_stats(self) -> None:
        session = GameSession()
        session.start_new_game()

        for cycle in range(5):
            aircraft_id = session.active_aircraft_id
            self.assertEqual(session.phase, GamePhase.AIRSTRIKE)
            session.transition(
                SessionEvent.AIRCRAFT_DESTROYED,
                aircraft_id=aircraft_id,
            )
            encounter = EncounterFactory().create_for_aircraft(
                aircraft_id or f"aircraft-{cycle + 1:03d}",
                random_source=FixedRandom(2),
            )
            for member in encounter.crew:
                self.assertTrue(defeat_crew_member(encounter, member.id, session))
            self.assertTrue(encounter.cleared)
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id=encounter.id,
            )

        self.assertEqual(session.phase, GamePhase.AIRSTRIKE)
        self.assertEqual(session.stats.aircraft_destroyed, 5)
        self.assertEqual(session.stats.enemies_defeated, 10)
        session.tick(1.0)
        session.transition(SessionEvent.BUILDING_IMPACT)
        frozen_snapshot = session.stats.snapshot()
        session.tick(5.0)
        self.assertEqual(session.stats.snapshot(), frozen_snapshot)
        self.assertEqual(session.stats.failure_reason, FailureReason.BUILDING_IMPACT)

    def test_domain_modules_are_asset_free(self) -> None:
        """The deterministic layer can be imported without starting Ursina."""

        import air_defense.entities as entities_module
        import air_defense.rules as rules_module

        self.assertNotIn("ursina", entities_module.__dict__)
        self.assertNotIn("ursina", rules_module.__dict__)

    def test_missing_optional_model_uses_procedural_fallback(self) -> None:
        from air_defense.scene import AirDefenseScene

        scene = AirDefenseScene.__new__(AirDefenseScene)
        scene.asset_root = Path("assets/air_defense").resolve()
        with patch("air_defense.scene.Entity", return_value=object()) as entity_factory:
            scene.create_optional_model(
                "missing-aircraft.glb",
                fallback_model="cube",
                position=(0, 0, 0),
            )

        self.assertEqual(entity_factory.call_args.kwargs["model"], "cube")


class AircraftTypeRuleTests(unittest.TestCase):
    def test_aircraft_profiles_have_type_specific_health_speed_and_evasion(self) -> None:
        normal = aircraft_profile(AircraftType.NORMAL)
        support = aircraft_profile(AircraftType.MANPOWER_SUPPORT)
        fast = aircraft_profile(AircraftType.FAST)
        armored = aircraft_profile(AircraftType.ARMORED_BOSS)

        self.assertEqual(normal.max_health, 1)
        self.assertEqual(support.max_health, 1)
        self.assertEqual(fast.max_health, 1)
        self.assertEqual(armored.max_health, config.ARMORED_AIRCRAFT_HEALTH)
        self.assertLess(support.flight_duration, 100.0)
        self.assertLess(fast.flight_duration, normal.flight_duration)
        self.assertGreater(fast.evasion_amplitude, normal.evasion_amplitude)

    def test_aircraft_spawns_far_and_evasion_is_continuous(self) -> None:
        aircraft = Aircraft(
            id="aircraft-far",
            aircraft_type=AircraftType.NORMAL,
        )
        self.assertGreater(
            dist(aircraft.start_position, aircraft.target_position),
            config.AIRCRAFT_FAR_SPAWN_MIN_DISTANCE,
        )
        start = aircraft.position
        aircraft.advance(0.5)
        middle = aircraft.position
        self.assertNotEqual(start, middle)
        self.assertLessEqual(
            dist(start, middle),
            dist(aircraft.start_position, aircraft.target_position) + 10.0,
        )

    def test_armored_aircraft_requires_five_valid_hits(self) -> None:
        aircraft = Aircraft(
            id="aircraft-armored",
            aircraft_type=AircraftType.ARMORED_BOSS,
        )
        for _ in range(config.ARMORED_AIRCRAFT_HEALTH - 1):
            self.assertFalse(aircraft.take_damage(1))
        self.assertTrue(aircraft.take_damage(1))
        self.assertEqual(aircraft.health, 0)

        legacy_aircraft = Aircraft(
            id="aircraft-armored-legacy",
            aircraft_type=AircraftType.ARMORED_BOSS,
        )
        for _ in range(config.ARMORED_AIRCRAFT_HEALTH - 1):
            self.assertFalse(legacy_aircraft.destroy())
        self.assertTrue(legacy_aircraft.destroy())

    def test_wave_progress_uses_requested_count_without_explicit_roster(self) -> None:
        progress = WaveProgress(aircraft_count=5)

        self.assertEqual(progress.aircraft_count, 5)
        self.assertEqual(len(progress.roster), 5)


class WaveRuleTests(unittest.TestCase):
    def test_progress_advances_one_aircraft_then_builds_next_wave(self) -> None:
        director = WaveDirector()
        first = director.plan_wave(1).to_progress()
        second_aircraft = director.next_progress(first)
        next_wave = director.next_progress(second_aircraft)

        self.assertEqual(second_aircraft.wave_number, 1)
        self.assertEqual(second_aircraft.aircraft_index, 1)
        self.assertEqual(next_wave.wave_number, 2)
        self.assertEqual(next_wave.aircraft_count, 2)
        self.assertEqual(next_wave.aircraft_index, 0)

    def test_session_completes_same_wave_before_creating_the_next_wave(self) -> None:
        director = WaveDirector()
        session = GameSession()
        session.start_new_game(director.plan_wave(1))

        session.transition(
            SessionEvent.AIRCRAFT_DESTROYED,
            aircraft_id=session.active_aircraft_id,
        )
        first_encounter = session.active_encounter_id
        session.transition(SessionEvent.CREW_CLEARED, encounter_id=first_encounter)
        self.assertEqual(session.wave.wave_number, 1)
        self.assertEqual(session.wave.aircraft_index, 1)

        session.transition(
            SessionEvent.AIRCRAFT_DESTROYED,
            aircraft_id=session.active_aircraft_id,
        )
        second_encounter = session.active_encounter_id
        session.transition(SessionEvent.CREW_CLEARED, encounter_id=second_encounter)
        self.assertEqual(session.wave.wave_number, 2)
        self.assertEqual(session.wave.aircraft_index, 0)
        self.assertEqual(session.wave.aircraft_count, 3)

    def test_wave_counts_caps_and_boss_rosters(self) -> None:
        director = WaveDirector()
        plans = [director.plan_wave(number) for number in range(1, 11)]

        self.assertEqual(
            [plan.aircraft_count for plan in plans[:9]],
            [2, 2, 2, 2, 3, 3, 3, 3, 3],
        )
        self.assertEqual([plans[index].aircraft_cap for index in (4, 6, 8)], [6, 6, 6])
        self.assertTrue(any(plan.is_boss_wave for plan in plans[:9]))
        boss_plan = plans[8]
        self.assertTrue(boss_plan.is_boss_wave)
        self.assertEqual(
            boss_plan.roster.count(AircraftType.ARMORED_BOSS),
            1,
        )
        self.assertGreater(boss_plan.aircraft_count, 1)

    def test_type_specific_encounter_counts_and_empty_encounters(self) -> None:
        factory = EncounterFactory()
        normal = factory.create_for_aircraft(
            "aircraft-normal",
            AircraftType.NORMAL,
            random_source=FixedRandom(0),
        )
        support = factory.create_for_aircraft(
            "aircraft-support",
            AircraftType.MANPOWER_SUPPORT,
            random_source=FixedRandom(0),
        )
        fast = factory.create_for_aircraft("aircraft-fast", AircraftType.FAST)
        boss = factory.create_for_aircraft("aircraft-boss", AircraftType.ARMORED_BOSS)

        self.assertEqual(normal.crew_count, 0)
        self.assertTrue(normal.cleared)
        self.assertEqual(support.crew_count, 6)
        self.assertEqual(fast.crew_count, 0)
        self.assertTrue(fast.cleared)
        self.assertEqual(boss.crew_count, 1)
        self.assertTrue(boss.crew[0].is_boss)
        self.assertEqual(boss.crew[0].max_health, config.GROUND_BOSS_HEALTH)

        string_typed = factory.create_for_aircraft(
            "aircraft-string-type",
            "MANPOWER_SUPPORT",
        )
        self.assertEqual(len(string_typed.crew), config.MANPOWER_SUPPORT_CREW)

    def test_encounter_factory_honors_custom_normal_crew_bounds(self) -> None:
        source = FixedRandom(0)

        encounter = EncounterFactory(minimum=2, maximum=2).create_for_aircraft(
            "aircraft-custom-count",
            AircraftType.NORMAL,
            random_source=source,
        )

        self.assertEqual(source.calls, [(2, 2)])
        self.assertEqual(encounter.crew_count, 2)

    def test_aggregate_wave_factory_uses_one_random_draw_per_normal_source(self) -> None:
        ids = ("wave-a", "wave-b", "wave-c")
        types = {
            ids[0]: AircraftType.NORMAL,
            ids[1]: AircraftType.MANPOWER_SUPPORT,
            ids[2]: AircraftType.FAST,
        }
        runtime = WaveRuntime(
            WaveDirector().plan_wave(4, aircraft_count=3, cap=6).to_progress(),
            ids,
            aircraft_types=types,
        )
        self.assertTrue(runtime.mark_destroyed(ids[0]))
        self.assertFalse(runtime.mark_destroyed(ids[0]))
        source = FixedRandom(2)
        encounter = EncounterFactory().create_for_wave(4, ids, types, source)
        self.assertEqual(encounter.id, "encounter:wave-4")
        self.assertEqual(encounter.source_aircraft_ids, ids)
        self.assertEqual(len(source.calls), 1)
        self.assertEqual(len(encounter.crew), 2 + config.MANPOWER_SUPPORT_CREW)
        self.assertTrue(all(member.encounter_id == encounter.id for member in encounter.crew))


class AircraftEnemyDescentRuleTests(unittest.TestCase):
    def test_drop_and_clear_guards_reject_stale_or_illegal_events(self) -> None:
        director = WaveDirector()
        plan = director.plan_wave(1, aircraft_count=1, cap=1)
        session = GameSession()
        session.start_new_game(plan)
        aircraft_id = "guarded-aircraft"
        runtime = session.initialize_wave_runtime((aircraft_id,), {aircraft_id: plan.roster[0]})

        self.assertFalse(runtime.mark_drop_spawned(aircraft_id))
        self.assertTrue(session.mark_aircraft_destroyed(aircraft_id))
        self.assertEqual(
            session.transition(
                SessionEvent.WAVE_CLEARED,
                ground_cleared=True,
            ),
            GamePhase.AIRSTRIKE,
        )
        self.assertEqual(
            session.transition(
                SessionEvent.WAVE_CLEARED,
                encounter_id="encounter:stale",
            ),
            GamePhase.AIRSTRIKE,
        )
        self.assertEqual(session.wave.wave_number, 1)
        self.assertTrue(runtime.mark_drop_spawned(aircraft_id))

        menu = GameSession(
            phase=GamePhase.MAIN_MENU,
            wave=plan.to_progress(),
        )
        menu.wave.wave_number = 18
        menu_runtime = menu.initialize_wave_runtime(
            ("menu-aircraft",),
            {"menu-aircraft": plan.roster[0]},
        )
        self.assertTrue(menu_runtime.mark_destroyed("menu-aircraft"))
        self.assertEqual(menu.transition(SessionEvent.VICTORY), GamePhase.MAIN_MENU)

        legacy_final = GameSession()
        legacy_final_plan = director.plan_wave(18, aircraft_count=1, cap=1)
        legacy_final.start_new_game(legacy_final_plan)
        self.assertEqual(
            legacy_final.transition(SessionEvent.VICTORY, ground_cleared=True),
            GamePhase.AIRSTRIKE,
        )

    def test_drop_and_wave_clear_events_are_keyed_and_final_is_idempotent(self) -> None:
        director = WaveDirector()
        session = GameSession()
        plan = director.plan_wave(1, aircraft_count=2, cap=2)
        session.start_new_game(plan)
        ids = ("event-aircraft-1", "event-aircraft-2")
        session.initialize_wave_runtime(ids, dict(zip(ids, plan.roster)))

        self.assertTrue(session.mark_aircraft_destroyed(ids[0]))
        self.assertEqual(
            session.transition(
                SessionEvent.DROP_STARTED,
                event_id="drop-event-1",
                aircraft_id=ids[0],
                encounter_id="encounter:wave-1",
            ),
            GamePhase.HYBRID_COMBAT,
        )
        self.assertEqual(session.wave_runtime.drop_spawned_aircraft_ids, {ids[0]})
        self.assertEqual(
            session.transition(
                SessionEvent.DROP_STARTED,
                event_id="drop-event-1",
                aircraft_id=ids[0],
                encounter_id="encounter:wave-1",
            ),
            GamePhase.HYBRID_COMBAT,
        )
        self.assertEqual(
            session.transition(SessionEvent.AIRCRAFT_DESTROYED, aircraft_id=ids[1]),
            GamePhase.GROUND_COMBAT,
        )

        final = GameSession()
        final_plan = director.plan_wave(18, aircraft_count=1, cap=1)
        final.start_new_game(final_plan)
        final_id = ("final-aircraft",)
        final.initialize_wave_runtime(final_id, {final_id[0]: final_plan.roster[0]})
        self.assertTrue(final.mark_aircraft_destroyed(final_id[0]))
        self.assertTrue(final.wave_runtime.mark_drop_spawned(final_id[0]))
        self.assertEqual(
            final.transition(
                SessionEvent.WAVE_CLEARED,
                event_id="wave-cleared:18",
            ),
            GamePhase.VICTORY,
        )
        self.assertEqual(
            final.transition(
                SessionEvent.WAVE_CLEARED,
                event_id="wave-cleared:18",
            ),
            GamePhase.VICTORY,
        )
        self.assertEqual(final.transition(SessionEvent.RETURN_TO_MENU), GamePhase.MAIN_MENU)

    def test_keyed_crew_cleared_compatibility_event_cannot_bypass_aggregate_clear(self) -> None:
        session = GameSession()
        plan = WaveDirector().plan_wave(1, aircraft_count=1, cap=1)
        session.start_new_game(plan)
        aircraft_id = "keyed-aircraft"
        session.initialize_wave_runtime((aircraft_id,), {aircraft_id: plan.roster[0]})
        session.mark_aircraft_destroyed(aircraft_id)
        session.transition(
            SessionEvent.DROP_STARTED,
            aircraft_id=aircraft_id,
            encounter_id="encounter:wave-1",
        )
        self.assertEqual(
            session.transition(
                SessionEvent.CREW_CLEARED,
                encounter_id="encounter:wave-1",
            ),
            GamePhase.GROUND_COMBAT,
        )

    def test_fixed_campaign_roster_and_special_rotation_are_exact(self) -> None:
        director = WaveDirector()
        expected = (
            (AircraftType.NORMAL, AircraftType.NORMAL),
            (AircraftType.NORMAL, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.FAST, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.ARMORED_BOSS, AircraftType.FAST),
            (AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.NORMAL),
            (AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.NORMAL, AircraftType.FAST, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.FAST, AircraftType.MANPOWER_SUPPORT, AircraftType.FAST),
            (AircraftType.ARMORED_BOSS, AircraftType.MANPOWER_SUPPORT, AircraftType.FAST),
            (AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.NORMAL),
            (AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.NORMAL, AircraftType.NORMAL, AircraftType.FAST, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.NORMAL, AircraftType.FAST, AircraftType.MANPOWER_SUPPORT, AircraftType.FAST),
            (AircraftType.MANPOWER_SUPPORT, AircraftType.FAST, AircraftType.MANPOWER_SUPPORT, AircraftType.FAST),
            (AircraftType.ARMORED_BOSS, AircraftType.MANPOWER_SUPPORT, AircraftType.FAST, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.ARMORED_BOSS, AircraftType.ARMORED_BOSS, AircraftType.FAST, AircraftType.MANPOWER_SUPPORT),
            (AircraftType.ARMORED_BOSS, AircraftType.ARMORED_BOSS, AircraftType.ARMORED_BOSS, AircraftType.FAST),
            (AircraftType.ARMORED_BOSS, AircraftType.ARMORED_BOSS, AircraftType.ARMORED_BOSS, AircraftType.ARMORED_BOSS),
        )

        self.assertEqual(tuple(director.plan_wave(number).roster for number in range(1, 19)), expected)
        self.assertEqual(normalize_aircraft_token("摩"), "魔")
        self.assertEqual(normalize_aircraft_token("魔"), "魔")
        with self.assertRaises(ValueError):
            director.plan_wave(19)

    def test_wave_plan_cap_is_structurally_validated_and_synthetic_override_is_explicit(self) -> None:
        with self.assertRaises(ValueError):
            WavePlan(1, 2, 1, False, (AircraftType.NORMAL, AircraftType.NORMAL))

        fixture = WaveDirector().plan_wave(6, aircraft_count=6, cap=6)
        self.assertEqual((fixture.aircraft_count, fixture.aircraft_cap), (6, 6))
        self.assertEqual(len(fixture.roster), fixture.aircraft_count)

    def test_crew_descent_interpolates_clamps_and_lands_once(self) -> None:
        member = CrewMember(
            id="drop-crew-1",
            encounter_id="encounter:wave-1",
            source_aircraft_id="aircraft-drop",
            cover_node=config.COVER_NODES[0],
            squad_role=SquadRole.COVER_SHOOTER,
        )
        start = (20.0, 30.0, -4.0)
        landing = (21.0, config.GROUND_LEVEL_Y, -3.0)

        self.assertTrue(member.begin_descent(start, landing, config.CREW_DESCENT_DURATION_SECONDS, (1.0, 1.0)))
        self.assertEqual(member.behavior_state, CrewBehaviorState.DESCENDING)
        self.assertEqual(member.position, start)
        self.assertFalse(member.advance_descent(-3.0))
        self.assertFalse(member.advance_descent(config.CREW_DESCENT_DURATION_SECONDS / 2.0))
        self.assertEqual(member.position, (20.5, 15.0, -3.5))
        self.assertTrue(member.advance_descent(config.CREW_DESCENT_DURATION_SECONDS))
        self.assertEqual(member.position, landing)
        self.assertEqual(member.behavior_state, CrewBehaviorState.IN_COVER)
        self.assertFalse(member.advance_descent(1.0))

    def test_drop_batch_preserves_source_composition_and_deterministic_spread(self) -> None:
        factory = EncounterFactory()
        batch = factory.create_drop_batch(
            "aircraft-support",
            AircraftType.MANPOWER_SUPPORT,
            "encounter:wave-1",
            (10.0, 25.0, 40.0),
        )

        self.assertEqual(len(batch), config.MANPOWER_SUPPORT_CREW)
        self.assertTrue(all(member.source_aircraft_id == "aircraft-support" for member in batch))
        self.assertTrue(all(member.behavior_state == CrewBehaviorState.DESCENDING for member in batch))
        self.assertTrue(all(member.descent_start_position[1] == 25.0 for member in batch))
        self.assertTrue(all(member.landing_position[1] == config.GROUND_LEVEL_Y for member in batch))
        self.assertLessEqual(
            max((member.descent_offset[0] ** 2 + member.descent_offset[1] ** 2) ** 0.5 for member in batch),
            config.CREW_DESCENT_MAX_SPREAD_RADIUS,
        )

    def test_aggregate_batches_keep_independent_progress_and_count_death_once(self) -> None:
        factory = EncounterFactory()
        encounter = GroundEncounter(
            aircraft_id="wave-1",
            group_id="wave-1",
            crew=[],
        )
        first = factory.create_drop_batch(
            "aircraft-a",
            AircraftType.MANPOWER_SUPPORT,
            encounter.id,
            (0.0, 20.0, 30.0),
        )
        second = factory.create_drop_batch(
            "aircraft-b",
            AircraftType.ARMORED_BOSS,
            encounter.id,
            (4.0, 22.0, 34.0),
        )
        self.assertTrue(encounter.add_reinforcement(first, "aircraft-a"))
        self.assertTrue(encounter.add_reinforcement(second, "aircraft-b"))
        self.assertFalse(encounter.add_reinforcement(second, "aircraft-b"))
        self.assertEqual(encounter.batch_progress("aircraft-a"), BatchProgress("aircraft-a", 6, 6, 0))

        defeated = first[0]
        self.assertTrue(defeated.take_damage())
        self.assertTrue(encounter.record_crew_cleared(defeated.id))
        self.assertFalse(encounter.record_crew_cleared(defeated.id))
        self.assertEqual(encounter.batch_progress("aircraft-a").cleared_count, 1)
        self.assertEqual(encounter.batch_progress("aircraft-a").alive_count, 5)
        self.assertEqual(encounter.batch_progress("aircraft-b").alive_count, 1)

    def test_aggregate_constructor_does_not_double_count_supplied_progress(self) -> None:
        factory = EncounterFactory()
        members = list(
            factory.create_drop_batch(
                "aircraft-a",
                AircraftType.MANPOWER_SUPPORT,
                "encounter:wave-1",
                (0.0, 20.0, 30.0),
            )
        )
        self.assertTrue(members[0].take_damage())

        encounter = GroundEncounter(
            aircraft_id="wave-1",
            group_id="wave-1",
            crew=members,
            source_aircraft_ids=("aircraft-a",),
            batch_progress={
                "aircraft-a": BatchProgress("aircraft-a", 6, 5, 1),
            },
        )

        progress = encounter.batch_progress("aircraft-a")
        self.assertIsNotNone(progress)
        assert progress is not None
        self.assertEqual(
            (progress.spawned_count, progress.alive_count, progress.cleared_count),
            (6, 5, 1),
        )

    def test_descending_members_are_targetable_but_not_ground_ai_or_city_damage(self) -> None:
        factory = EncounterFactory()
        encounter = GroundEncounter(aircraft_id="wave-1", group_id="wave-1", crew=[])
        batch = factory.create_drop_batch(
            "aircraft-support",
            AircraftType.MANPOWER_SUPPORT,
            encounter.id,
            (0.0, 25.0, 30.0),
        )
        encounter.add_reinforcement(batch, "aircraft-support")
        member = batch[0]
        before_position = member.position
        member.attack_cooldown = 0.0
        building = TargetBuilding()
        advance_crew_behavior(encounter, 1.0)
        self.assertEqual(member.position, before_position)
        self.assertFalse(member.ready_to_attack())
        self.assertFalse(apply_city_damage(encounter, building, 1.0))
        self.assertEqual(building.health, config.CITY_MAX_HEALTH)

        session = GameSession()
        session.start_new_game(WaveDirector().plan_wave(1, aircraft_count=1, cap=2))
        session.phase = GamePhase.HYBRID_COMBAT
        session.active_encounter_id = encounter.id
        self.assertTrue(damage_crew_member(encounter, member.id, 1, session))
        self.assertEqual(session.stats.enemies_defeated, 1)
        self.assertFalse(encounter.record_crew_cleared(member.id))

    def test_hybrid_allows_all_three_weapon_slots(self) -> None:
        for weapon in WeaponKind:
            self.assertTrue(inventory_selection_allowed(GamePhase.HYBRID_COMBAT, weapon))

    def test_hybrid_city_damage_compatibility_api_remains_active(self) -> None:
        session = GameSession()
        session.start_new_game(WaveDirector().plan_wave(1, aircraft_count=1, cap=1))
        session.phase = GamePhase.HYBRID_COMBAT

        self.assertTrue(session.take_city_damage(session.city_health))
        self.assertEqual(session.phase, GamePhase.GAME_OVER)


class ExpandedGroundRuleTests(unittest.TestCase):
    def test_direct_boss_entity_defaults_to_boss_profile(self) -> None:
        boss = CrewMember(
            id="boss-direct",
            encounter_id="encounter:boss-direct",
            cover_node=config.COVER_NODES[0],
            squad_role=SquadRole.COVER_SHOOTER,
            is_boss=True,
        )

        self.assertEqual(boss.health, config.GROUND_BOSS_HEALTH)
        self.assertEqual(boss.max_health, config.GROUND_BOSS_HEALTH)
        self.assertEqual(boss.move_speed, config.GROUND_BOSS_MOVE_SPEED)

    def test_ground_enemy_moves_with_speed_limit_instead_of_teleporting(self) -> None:
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-walk",
            AircraftType.MANPOWER_SUPPORT,
            random_source=FixedRandom(6),
        )
        member = encounter.crew[0]
        start = member.position
        target = config.COVER_NODE_POSITIONS[member.target_cover_node]
        delta = 0.1

        advance_crew_behavior(encounter, delta)

        self.assertNotEqual(member.position, target)
        self.assertLessEqual(
            dist(start, member.position),
            member.move_speed * delta + 1e-6,
        )

    def test_pistol_is_short_range_and_fast_cooldown(self) -> None:
        self.assertTrue(can_fire_pistol(0.0, target_distance=11.9))
        self.assertFalse(can_fire_pistol(0.0, target_distance=12.1))
        self.assertFalse(can_fire_pistol(config.PISTOL_FIRE_COOLDOWN_SECONDS, target_distance=1.0))

    def test_city_damage_and_ground_boss_need_repeated_hits(self) -> None:
        building = TargetBuilding()
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-city",
            AircraftType.ARMORED_BOSS,
        )
        boss = encounter.crew[0]
        boss.position = config.CITY_ATTACK_POINT
        boss.at_city = True

        apply_city_damage(encounter, building, 1.0)
        self.assertEqual(building.health, config.CITY_MAX_HEALTH - config.CITY_DAMAGE_PER_SECOND)

        for _ in range(config.GROUND_BOSS_HEALTH - 1):
            self.assertFalse(damage_crew_member(encounter, boss.id, 1))
        self.assertTrue(damage_crew_member(encounter, boss.id, 1))
        self.assertTrue(encounter.cleared)

    def test_ground_enemy_can_reach_city_by_continuous_route_steps(self) -> None:
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-route",
            AircraftType.MANPOWER_SUPPORT,
            random_source=FixedRandom(6),
        )
        member = encounter.crew[0]
        previous = member.position
        for _ in range(1000):
            advance_crew_behavior(encounter, 0.1)
            self.assertLessEqual(
                dist(previous, member.position),
                member.move_speed * 0.1 + 1e-6,
            )
            previous = member.position
            if member.at_city:
                break
        self.assertTrue(member.at_city)
        self.assertEqual(member.position, config.CITY_ATTACK_POINT)


class GuidedMissileIntegrationRuleTests(unittest.TestCase):
    def test_damage_is_delayed_until_collision(self) -> None:
        aircraft = Aircraft(id="aircraft-delayed")
        missile = GuidedMissile(
            id="missile-delayed",
            target_aircraft_id=aircraft.id,
            position=(aircraft.position[0], aircraft.position[1], aircraft.position[2] + 10.0),
            forward=(0.0, 0.0, -1.0),
            speed=100.0,
            turn_rate=0.0,
        )

        self.assertEqual(aircraft.health, aircraft.max_health)
        step = missile.advance(0.1, aircraft.position)
        self.assertIsInstance(step, MissileStep)
        self.assertTrue(step.hit)
        self.assertTrue(apply_guided_missile_damage(aircraft, missile, step, active_aircraft_id=aircraft.id))
        self.assertEqual(aircraft.health, 0)

    def test_armored_aircraft_takes_exactly_five_collision_hits(self) -> None:
        aircraft = Aircraft(id="aircraft-armored-missiles", aircraft_type=AircraftType.ARMORED_BOSS)

        for hit_number in range(1, config.ARMORED_AIRCRAFT_HEALTH + 1):
            missile = GuidedMissile(
                id=f"missile-armored-{hit_number}",
                target_aircraft_id=aircraft.id,
                position=aircraft.position,
            )
            step = missile.advance(0.0, aircraft.position)
            destroyed = apply_guided_missile_damage(
                aircraft,
                missile,
                step,
                active_aircraft_id=aircraft.id,
            )
            self.assertEqual(aircraft.health, config.ARMORED_AIRCRAFT_HEALTH - hit_number)
            self.assertEqual(destroyed, hit_number == config.ARMORED_AIRCRAFT_HEALTH)

    def test_simultaneous_contacts_are_ordered_and_terminal_state_blocks_second_hit(self) -> None:
        aircraft = Aircraft(id="aircraft-simultaneous")
        missiles = [
            GuidedMissile(
                id=f"missile-simultaneous-{index}",
                target_aircraft_id=aircraft.id,
                position=aircraft.position,
            )
            for index in (1, 2)
        ]
        steps = [missile.advance(0.0, aircraft.position) for missile in missiles]

        self.assertTrue(apply_guided_missile_damage(aircraft, missiles[0], steps[0], active_aircraft_id=aircraft.id))
        self.assertFalse(apply_guided_missile_damage(aircraft, missiles[1], steps[1], active_aircraft_id=aircraft.id))
        self.assertEqual(aircraft.health, 0)

    def test_impact_and_stale_target_cannot_receive_late_missile_damage(self) -> None:
        impacted = Aircraft(id="aircraft-impacted")
        impacted.impact()
        impact_missile = GuidedMissile(
            id="missile-impact",
            target_aircraft_id=impacted.id,
            position=impacted.position,
        )
        impact_step = impact_missile.advance(0.0, impacted.position)
        self.assertFalse(
            apply_guided_missile_damage(
                impacted,
                impact_missile,
                impact_step,
                active_aircraft_id=impacted.id,
            )
        )

        current = Aircraft(id="aircraft-current")
        stale = GuidedMissile(
            id="missile-stale",
            target_aircraft_id="aircraft-old",
            position=current.position,
        )
        stale_step = stale.advance(0.0, current.position)
        self.assertFalse(
            apply_guided_missile_damage(
                current,
                stale,
                stale_step,
                active_aircraft_id=current.id,
            )
        )


if __name__ == "__main__":
    unittest.main()
