"""Focused engine-free tests for the 003 airstrike guidance feature."""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from air_defense import config
from air_defense.entities import Aircraft, GuidedMissile, MissileStep
from air_defense.rules import (
    LockOnTracker,
    MissileVolley,
    apply_aim_assist,
    can_fire_anti_air,
    clamp_screen_radius,
    direction_to_yaw_pitch,
    is_inside_lock_zone,
    is_inside_expanded_lock_frame,
    is_inside_lock_frame,
    lock_frame_bounds,
    lock_zone_radius,
    normalize_vector,
    raycast_hit_matches_target,
    screen_distance_from_center,
    select_lock_target,
    steer_forward,
    swept_segment_hits_sphere,
    tracking_ring_radius,
    vector_length,
)
from air_defense.state import AircraftType, LockState


class GuidanceFixtures:
    """Stable values shared by the deterministic lock/flight/missile tests."""

    start_position = (0.0, 32.0, 210.0)
    target_position = (0.0, 10.0, -60.0)
    time_step = 0.1

    @classmethod
    def aircraft(cls, *, aircraft_id: str = "fixture-aircraft") -> Aircraft:
        return Aircraft(
            id=aircraft_id,
            aircraft_type=AircraftType.NORMAL,
            start_position=cls.start_position,
            target_position=cls.target_position,
        )


class GuidanceFixtureTests(unittest.TestCase):
    def test_fixture_is_deterministic_and_far_enough_for_airstrike(self) -> None:
        aircraft = GuidanceFixtures.aircraft()
        distance = math.sqrt(
            sum(
                (left - right) ** 2
                for left, right in zip(
                    GuidanceFixtures.start_position,
                    GuidanceFixtures.target_position,
                )
            )
        )

        self.assertEqual(aircraft.position, GuidanceFixtures.start_position)
        self.assertEqual(GuidanceFixtures.time_step, 0.1)
        self.assertGreater(distance, config.AIRCRAFT_FAR_SPAWN_MIN_DISTANCE)


class LockScopeRuleTests(unittest.TestCase):
    def test_scope_is_required_and_closing_scope_resets_immediately(self) -> None:
        tracker = LockOnTracker()

        self.assertEqual(tracker.update(True, 1.0), LockState.WHITE)
        self.assertEqual(tracker.progress, 0.0)

        tracker.set_scope_enabled(True)
        self.assertEqual(tracker.update(True, 1.0), LockState.RED_TRACKING)
        self.assertAlmostEqual(tracker.progress, 1.0 / 3.0, places=6)

        tracker.set_scope_enabled(False)
        self.assertEqual(tracker.state, LockState.WHITE)
        self.assertEqual(tracker.progress, 0.0)
        self.assertFalse(tracker.target_in_zone)

    def test_lock_zone_uses_short_side_radius_and_inclusive_boundary(self) -> None:
        width, height = 1000.0, 600.0
        radius = lock_zone_radius(width, height)

        self.assertAlmostEqual(radius, height * config.AA_LOCK_ZONE_DIAMETER_RATIO / 2.0)
        self.assertTrue(is_inside_lock_zone((width / 2.0, height / 2.0), width, height))
        self.assertTrue(is_inside_lock_zone((width / 2.0 + radius, height / 2.0), width, height))
        self.assertFalse(is_inside_lock_zone((width / 2.0 + radius + 0.01, height / 2.0), width, height))
        self.assertAlmostEqual(
            screen_distance_from_center((width / 2.0 + 3.0, height / 2.0 + 4.0), width, height),
            5.0,
        )

    def test_visible_in_zone_accumulates_to_green_ready(self) -> None:
        tracker = LockOnTracker()
        tracker.set_scope_enabled(True)

        self.assertEqual(tracker.update(False, 1.0), LockState.WHITE)
        self.assertEqual(tracker.update(True, 2.99), LockState.RED_TRACKING)
        self.assertAlmostEqual(tracker.progress, 2.99 / 3.0, places=6)
        self.assertEqual(tracker.update(True, 0.01), LockState.GREEN_READY)
        self.assertEqual(tracker.progress, 1.0)
        self.assertTrue(tracker.target_in_zone)


class LockGeometryTests(unittest.TestCase):
    def test_target_radius_is_clamped_and_ring_shrinks_to_target(self) -> None:
        self.assertEqual(clamp_screen_radius(-1.0), 0.008)
        self.assertEqual(clamp_screen_radius(10.0), 0.2)

        self.assertAlmostEqual(tracking_ring_radius(50.0, 10.0, 0.0, padding=2.0), 50.0)
        self.assertAlmostEqual(tracking_ring_radius(50.0, 10.0, 0.5, padding=2.0), 31.0)
        self.assertAlmostEqual(tracking_ring_radius(50.0, 10.0, 1.0, padding=2.0), 12.0)
        self.assertAlmostEqual(tracking_ring_radius(50.0, 10.0, 2.0, padding=2.0), 12.0)

    def test_raycast_visibility_starts_from_hit_entity_and_follows_parent(self) -> None:
        aircraft = SimpleNamespace(aircraft_id="aircraft-001", parent=None)
        wing = SimpleNamespace(parent=aircraft)
        hit = SimpleNamespace(hit=True, entity=wing)
        blocker = SimpleNamespace(parent=None)

        self.assertTrue(raycast_hit_matches_target(hit, aircraft))
        self.assertFalse(
            raycast_hit_matches_target(
                SimpleNamespace(hit=True, entity=blocker),
                aircraft,
            )
        )
        self.assertFalse(raycast_hit_matches_target(SimpleNamespace(hit=False, entity=wing), aircraft))

    def test_rectangular_frame_selection_and_clamped_reticle(self) -> None:
        width, height = 1280.0, 720.0
        left, bottom, right, top = lock_frame_bounds(width, height)
        self.assertTrue(is_inside_lock_frame((left, top), width, height))
        self.assertFalse(is_inside_lock_frame((left - 0.1, top), width, height))
        self.assertTrue(is_inside_expanded_lock_frame((right + 1.0, height / 2), width, height))
        candidates = [
            SimpleNamespace(aircraft_id="late", visible=True, in_lock_frame=True, distance_from_center=6.0),
            SimpleNamespace(aircraft_id="early", visible=True, in_lock_frame=True, distance_from_center=3.0),
        ]
        self.assertEqual(select_lock_target(candidates).aircraft_id, "early")
        out_of_frame = SimpleNamespace(
            aircraft_id="early", visible=True, in_lock_frame=False, distance_from_center=100.0
        )
        self.assertEqual(
            select_lock_target([out_of_frame], "early", lock_progress=0.2).aircraft_id,
            "early",
        )


class LockDecayRuleTests(unittest.TestCase):
    def test_partial_decay_preserves_progress_and_reentry_resumes(self) -> None:
        tracker = LockOnTracker()
        tracker.set_scope_enabled(True)
        tracker.update(True, 3.0)

        self.assertEqual(tracker.state, LockState.GREEN_READY)
        self.assertEqual(tracker.update(False, 0.25), LockState.RED_TRACKING)
        self.assertAlmostEqual(tracker.progress, 2.0 / 3.0, places=6)
        self.assertFalse(tracker.target_in_zone)

        tracker.update(True, 0.25)
        self.assertAlmostEqual(tracker.progress, 3.0 / 4.0, places=6)
        self.assertEqual(tracker.state, LockState.RED_TRACKING)

    def test_decay_expires_at_three_quarters_of_a_second(self) -> None:
        tracker = LockOnTracker()
        tracker.set_scope_enabled(True)
        tracker.update(True, 3.0)

        tracker.update(False, 0.75)
        self.assertEqual(tracker.progress, 0.0)
        self.assertEqual(tracker.state, LockState.WHITE)
        self.assertFalse(tracker.target_in_zone)

    def test_green_progress_is_not_fireable_while_target_is_outside(self) -> None:
        tracker = LockOnTracker()
        tracker.set_scope_enabled(True)
        tracker.update(True, 3.0)
        tracker.update(False, 0.1)

        self.assertGreater(tracker.progress, 0.0)
        self.assertEqual(tracker.state, LockState.RED_TRACKING)
        self.assertFalse(
            can_fire_anti_air(
                tracker.state,
                0.0,
                target_in_zone=tracker.target_in_zone,
            )
        )
        self.assertFalse(can_fire_anti_air(LockState.GREEN_READY, 0.0))

    def test_target_switch_resets_progress_but_reentry_keeps_sticky_target(self) -> None:
        tracker = LockOnTracker(scope_enabled=True)
        tracker.set_target("aircraft-a")
        tracker.update(target_visible=True, target_in_frame=True, delta_seconds=1.5)
        tracker.update(target_visible=True, target_in_frame=False, delta_seconds=0.25)
        self.assertEqual(tracker.target_aircraft_id, "aircraft-a")
        tracker.set_target("aircraft-b")
        self.assertEqual(tracker.progress, 0.0)
        self.assertEqual(tracker.state, LockState.WHITE)


class AircraftFlightRuleTests(unittest.TestCase):
    def test_aircraft_moves_only_along_current_forward_with_speed_limit(self) -> None:
        aircraft = GuidanceFixtures.aircraft()
        previous = aircraft.position

        aircraft.advance(GuidanceFixtures.time_step)
        displacement = tuple(
            aircraft.position[index] - previous[index]
            for index in range(3)
        )

        self.assertLessEqual(vector_length(displacement), aircraft.speed * GuidanceFixtures.time_step + 1e-9)
        self.assertAlmostEqual(vector_length(aircraft.forward), 1.0, places=6)
        expected = tuple(aircraft.forward[index] * vector_length(displacement) for index in range(3))
        for actual, expected_component in zip(displacement, expected):
            self.assertAlmostEqual(actual, expected_component, places=6)
        self.assertGreaterEqual(sum(actual * direction for actual, direction in zip(displacement, aircraft.forward)), -1e-9)

    def test_aircraft_yaw_and_pitch_turn_rates_are_bounded(self) -> None:
        aircraft = Aircraft(
            id="turn-limited",
            start_position=(0.0, 0.0, 0.0),
            target_position=(100.0, 100.0, 0.0),
            forward=(0.0, 0.0, 1.0),
            speed=20.0,
            max_yaw_rate=10.0,
            max_pitch_rate=8.0,
        )
        aircraft.advance(0.1)
        yaw, pitch = direction_to_yaw_pitch(aircraft.forward)

        self.assertLessEqual(abs(yaw), 1.0 + 1e-6)
        self.assertLessEqual(abs(pitch), 0.8 + 1e-6)
        self.assertGreaterEqual(vector_length(aircraft.position), 0.0)

    def test_aircraft_evasion_changes_heading_without_sideways_teleport(self) -> None:
        aircraft = GuidanceFixtures.aircraft()
        headings = []
        positions = [aircraft.position]
        for _ in range(12):
            aircraft.advance(GuidanceFixtures.time_step)
            headings.append(aircraft.forward)
            positions.append(aircraft.position)

        self.assertGreater(len({tuple(round(value, 5) for value in heading) for heading in headings}), 1)
        for previous, current in zip(positions, positions[1:]):
            displacement = tuple(current[index] - previous[index] for index in range(3))
            self.assertLessEqual(vector_length(displacement), aircraft.speed * GuidanceFixtures.time_step + 1e-6)
            self.assertGreaterEqual(sum(displacement[index] * headings[max(0, positions.index(current) - 1)][index] for index in range(3)), -1e-6)

    def test_tuned_evasion_produces_visible_wide_turns(self) -> None:
        normal = Aircraft(id="normal-evasion", aircraft_type=AircraftType.NORMAL)
        fast = Aircraft(id="fast-evasion", aircraft_type=AircraftType.FAST)
        traces: dict[AircraftType, list[float]] = {
            AircraftType.NORMAL: [],
            AircraftType.FAST: [],
        }

        for _ in range(100):
            normal.advance(GuidanceFixtures.time_step)
            fast.advance(GuidanceFixtures.time_step)
            traces[AircraftType.NORMAL].append(normal.position[0])
            traces[AircraftType.FAST].append(fast.position[0])

        normal_span = max(traces[AircraftType.NORMAL]) - min(traces[AircraftType.NORMAL])
        fast_span = max(traces[AircraftType.FAST]) - min(traces[AircraftType.FAST])
        self.assertGreater(normal_span, 2.0)
        self.assertGreater(fast_span, 4.0)
        self.assertGreater(fast_span, normal_span)

    def test_second_stage_evasion_has_gameplay_scale_turns(self) -> None:
        aircraft_by_type = {
            aircraft_type: Aircraft(
                id=f"{aircraft_type.value.lower()}-second-stage-evasion",
                aircraft_type=aircraft_type,
            )
            for aircraft_type in AircraftType
        }
        traces = {aircraft_type: [] for aircraft_type in aircraft_by_type}

        for _ in range(100):
            for aircraft_type, aircraft in aircraft_by_type.items():
                aircraft.advance(GuidanceFixtures.time_step)
                traces[aircraft_type].append(aircraft.position[0])

        spans = {
            aircraft_type: max(samples) - min(samples)
            for aircraft_type, samples in traces.items()
        }
        self.assertGreater(spans[AircraftType.NORMAL], 4.0)
        self.assertGreater(spans[AircraftType.MANPOWER_SUPPORT], 2.5)
        self.assertGreater(spans[AircraftType.FAST], 7.0)
        self.assertGreater(spans[AircraftType.ARMORED_BOSS], 2.4)
        self.assertGreater(spans[AircraftType.FAST], spans[AircraftType.NORMAL])


class AimAssistRuleTests(unittest.TestCase):
    def test_aim_assist_is_scope_only_and_has_inclusive_1_5x_boundary(self) -> None:
        current = normalize_vector((0.0, 0.0, 1.0))
        target = normalize_vector((math.sin(math.radians(10.0)), 0.0, math.cos(math.radians(10.0))))

        corrected = apply_aim_assist(
            current,
            target,
            scope_enabled=True,
            target_visible=True,
            target_screen_distance=75.0,
            lock_zone_radius_pixels=50.0,
            delta_seconds=1.0,
        )
        yaw, _ = direction_to_yaw_pitch(corrected)
        self.assertAlmostEqual(yaw, 3.0, places=5)

        self.assertEqual(
            apply_aim_assist(
                current,
                target,
                scope_enabled=True,
                target_visible=True,
                target_screen_distance=75.01,
                lock_zone_radius_pixels=50.0,
                delta_seconds=1.0,
            ),
            current,
        )
        self.assertEqual(
            apply_aim_assist(
                current,
                target,
                scope_enabled=False,
                target_visible=True,
                target_screen_distance=0.0,
                lock_zone_radius_pixels=50.0,
                delta_seconds=1.0,
            ),
            current,
        )
        self.assertEqual(
            apply_aim_assist(
                current,
                target,
                scope_enabled=True,
                target_visible=False,
                target_screen_distance=0.0,
                lock_zone_radius_pixels=50.0,
                delta_seconds=1.0,
            ),
            current,
        )

    def test_aim_assist_cap_scales_with_delta_seconds(self) -> None:
        corrected = apply_aim_assist(
            (0.0, 0.0, 1.0),
            normalize_vector((math.sin(math.radians(30.0)), 0.0, math.cos(math.radians(30.0)))),
            scope_enabled=True,
            target_visible=True,
            target_screen_distance=0.0,
            lock_zone_radius_pixels=1.0,
            delta_seconds=0.25,
        )
        yaw, _ = direction_to_yaw_pitch(corrected)
        self.assertAlmostEqual(yaw, 0.75, places=5)


class GuidedMissileRuleTests(unittest.TestCase):
    def test_missile_volley_is_immutable_and_keeps_target_pairs(self) -> None:
        volley = MissileVolley(
            volley_id="volley-001",
            target_ids=(f"aircraft-{index}" for index in range(10)),
            missile_ids=tuple((f"aircraft-{index}", f"missile-{index}") for index in range(10)),
        )
        self.assertEqual(len(volley.target_ids), 10)
        self.assertEqual(volley.missile_ids[0], ("aircraft-0", "missile-0"))
        with self.assertRaises(FrozenInstanceError):
            volley.cooldown_applied = True

    def test_missile_moves_forward_and_turns_with_a_rate_limit(self) -> None:
        missile = GuidedMissile(
            id="missile-turn",
            target_aircraft_id="aircraft-1",
            position=(0.0, 0.0, 0.0),
            forward=(0.0, 0.0, 1.0),
            speed=10.0,
            turn_rate=90.0,
            hit_radius=0.1,
        )

        step = missile.advance(0.1, (10.0, 0.0, 0.0))
        self.assertIsInstance(step, MissileStep)
        self.assertLessEqual(vector_length(tuple(step.position[index] for index in range(3))), 1.0 + 1e-6)
        self.assertAlmostEqual(vector_length(missile.forward), 1.0, places=6)
        yaw, _ = direction_to_yaw_pitch(missile.forward)
        self.assertLessEqual(abs(yaw), 9.0 + 1e-6)

    def test_swept_collision_catches_high_speed_tunneling(self) -> None:
        missile = GuidedMissile(
            id="missile-fast",
            target_aircraft_id="aircraft-1",
            position=(0.0, 0.0, 0.0),
            forward=(1.0, 0.0, 0.0),
            speed=100.0,
            turn_rate=0.0,
            hit_radius=1.0,
            lifetime_remaining=5.0,
        )

        step = missile.advance(0.1, (5.0, 0.0, 0.0))
        self.assertTrue(step.hit)
        self.assertFalse(step.expired)
        self.assertTrue(missile.consumed)
        self.assertTrue(swept_segment_hits_sphere((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (5.0, 0.0, 0.0), 1.0))

    def test_hit_wins_over_expiry_and_consumption_blocks_duplicate_hits(self) -> None:
        missile = GuidedMissile(
            id="missile-last-frame",
            target_aircraft_id="aircraft-1",
            position=(0.0, 0.0, 0.0),
            forward=(1.0, 0.0, 0.0),
            speed=100.0,
            turn_rate=0.0,
            hit_radius=0.5,
            lifetime_remaining=0.01,
        )

        first = missile.advance(0.1, (5.0, 0.0, 0.0))
        second = missile.advance(0.1, (6.0, 0.0, 0.0))
        self.assertTrue(first.hit)
        self.assertFalse(first.expired)
        self.assertFalse(second.hit)
        self.assertTrue(second.expired)

    def test_missile_expires_without_contact(self) -> None:
        missile = GuidedMissile(
            id="missile-expire",
            target_aircraft_id="aircraft-1",
            position=(0.0, 0.0, 0.0),
            forward=(0.0, 0.0, 1.0),
            speed=1.0,
            lifetime_remaining=0.1,
        )

        step = missile.advance(0.1, (100.0, 100.0, 100.0))
        self.assertFalse(step.hit)
        self.assertTrue(step.expired)
        self.assertTrue(missile.consumed)

    def test_missile_tracks_updated_target_positions_and_ids_are_isolated(self) -> None:
        first = GuidedMissile(
            id="missile-a",
            target_aircraft_id="aircraft-a",
            position=(0.0, 0.0, 0.0),
            forward=(1.0, 0.0, 0.0),
            speed=20.0,
            turn_rate=360.0,
            hit_radius=0.75,
        )
        second = GuidedMissile(
            id="missile-b",
            target_aircraft_id="aircraft-b",
            position=(0.0, 0.0, 0.0),
            forward=(1.0, 0.0, 0.0),
            speed=20.0,
            turn_rate=360.0,
            hit_radius=0.75,
        )

        first_step = first.advance(0.1, (8.0, 1.0, 0.0))
        second_step = second.advance(0.1, (8.0, -1.0, 0.0))
        self.assertEqual(first.target_aircraft_id, "aircraft-a")
        self.assertEqual(second.target_aircraft_id, "aircraft-b")
        self.assertNotEqual(first_step.position, second_step.position)
        self.assertFalse(first.consumed)
        self.assertFalse(second.consumed)


if __name__ == "__main__":
    unittest.main()
