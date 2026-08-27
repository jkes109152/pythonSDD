"""Deterministic tests for the engine-independent game rules."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from air_defense import config
from air_defense.entities import AntiAircraftGun, Player, SniperRifle
from air_defense.rules import (
    EncounterFactory,
    LockOnTracker,
    add_reinforcement,
    advance_crew_behavior,
    can_fire_anti_air,
    can_fire_sniper,
    defeat_crew_member,
    drop_weapon,
    inventory_selection_allowed,
    lock_status_label,
    resolve_aircraft_outcome,
    try_pickup_weapon,
    warning_active,
)
from air_defense.state import (
    CrewBehaviorState,
    FailureReason,
    GamePhase,
    GameSession,
    LockState,
    SessionEvent,
    SessionStats,
    WeaponKind,
)


class FixedRandom:
    def __init__(self, value: int) -> None:
        self.value = value

    def randint(self, minimum: int, maximum: int) -> int:
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
                SessionEvent.BUILDING_IMPACT,
                aircraft_id=first_aircraft,
            ),
            GamePhase.AIRSTRIKE,
        )


class LockAndWeaponRuleTests(unittest.TestCase):
    def test_lock_tracker_resets_when_target_is_lost(self) -> None:
        tracker = LockOnTracker(lock_duration=3.0)

        self.assertEqual(tracker.update(True, 1.0), LockState.RED_TRACKING)
        self.assertEqual(tracker.update(False, 0.01), LockState.WHITE)
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
        tracker = LockOnTracker(lock_duration=3.0)

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
        tracker = LockOnTracker()
        tracker.update(True, 2.0)
        self.assertEqual(tracker.update(False, 0.0), LockState.WHITE)
        self.assertEqual(tracker.lock_elapsed, 0.0)

        self.assertTrue(warning_active(8.0))
        self.assertFalse(warning_active(8.01))
        self.assertFalse(warning_active(None))
        self.assertFalse(can_fire_anti_air(LockState.RED_TRACKING, 0.0))
        self.assertTrue(can_fire_anti_air(LockState.GREEN_READY, 0.0))
        self.assertFalse(can_fire_anti_air(LockState.GREEN_READY, 0.01))
        self.assertFalse(
            can_fire_anti_air(
                LockState.GREEN_READY,
                0.0,
                WeaponKind.SNIPER,
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


class GroundEncounterRuleTests(unittest.TestCase):
    def test_factory_assigns_one_finite_group_with_roles_and_cover(self) -> None:
        encounter = EncounterFactory().create_for_aircraft(
            "aircraft-007",
            random_source=FixedRandom(5),
        )

        self.assertEqual(encounter.crew_count, 5)
        self.assertEqual(len(encounter.crew), 5)
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
            can_fire_anti_air(LockState.GREEN_READY, 0.0, session.held_weapon)
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


if __name__ == "__main__":
    unittest.main()
