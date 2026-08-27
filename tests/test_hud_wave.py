"""Pure acceptance fixtures for the 004 HUD and whole-wave feature.

This module intentionally imports only the engine-independent domain layer.
The graphical adapter is covered by the lifecycle/smoke tests instead.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from air_defense import config
from air_defense.hud import GameHUD
from air_defense.entities import (
    AntiAircraftGun,
    GroundTracerEffect,
    Pistol,
    SniperRifle,
)
from air_defense.rules import (
    EncounterFactory,
    LockOnTracker,
    WaveDirector,
    build_city_status_view,
    build_player_status_view,
    build_wave_status_view,
    is_inside_expanded_lock_frame,
    is_inside_lock_frame,
    inventory_selection_allowed,
    lock_frame_bounds,
    reset_weapon_cooldowns,
    reticle_position_for_progress,
    select_lock_target,
    weapon_cooldown_view,
)
from air_defense.state import (
    AircraftPhase,
    AircraftType,
    GamePhase,
    LockState,
    WeaponKind,
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


class HudWaveFixtureTests(unittest.TestCase):
    def test_pure_fixture_modules_do_not_import_ursina(self) -> None:
        import air_defense.entities as entities_module
        import air_defense.rules as rules_module

        self.assertNotIn("ursina", entities_module.__dict__)
        self.assertNotIn("ursina", rules_module.__dict__)

    def test_player_and_city_views_clamp_independently(self) -> None:
        player = build_player_status_view(-5, 100)
        city = build_city_status_view(140, 100)

        self.assertEqual((player.health, player.max_health), (0, 100))
        self.assertEqual(player.health_ratio, 0.0)
        self.assertEqual((city.city_health, city.max_city_health), (100.0, 100.0))
        self.assertEqual(city.health_ratio, 1.0)
        self.assertNotEqual(player.icon_color, city.icon_color)

    def test_wave_fixture_has_ordered_dots_and_clamped_layout(self) -> None:
        plan = WaveDirector().plan_wave(6, aircraft_count=6, cap=6)
        ids = tuple(f"aircraft-006-{index + 1:02d}" for index in range(plan.aircraft_count))
        runtime = WaveRuntime(
            plan.to_progress(),
            ids,
            aircraft_types=dict(zip(ids, plan.roster)),
        )
        runtime.mark_destroyed(ids[1])
        view = build_wave_status_view(runtime, active_target_id=ids[0], viewport_width=320)

        self.assertEqual(view.aircraft_total, 6)
        self.assertEqual(view.aircraft_alive, 5)
        self.assertAlmostEqual(view.aircraft_ratio, 5 / 6)
        self.assertEqual(tuple(dot.aircraft_id for dot in view.dots), ids)
        self.assertTrue(view.dots[0].alive)
        self.assertTrue(view.dots[1].terminal)
        self.assertGreaterEqual(view.layout_rows, 2)
        self.assertEqual(view.selected_aircraft_type, plan.roster[0])

    def test_wave_view_lists_distinct_aircraft_types_in_roster_order(self) -> None:
        plan = WavePlan(
            1,
            4,
            6,
            True,
            (
                AircraftType.FAST,
                AircraftType.NORMAL,
                AircraftType.ARMORED_BOSS,
                AircraftType.MANPOWER_SUPPORT,
            ),
        )
        ids = tuple(f"aircraft-type-{index}" for index in range(4))
        view = build_wave_status_view(WaveRuntime(plan.to_progress(), ids))

        self.assertEqual(
            view.aircraft_type_labels,
            ("快速", "普通", "Boss", "人力支援"),
        )

    def test_lock_frame_is_rectangular_inclusive_and_reticle_is_constrained(self) -> None:
        width, height = 1000.0, 600.0
        bounds = lock_frame_bounds(width, height)
        left, bottom, right, top = bounds
        self.assertAlmostEqual(right - left, height * config.AA_LOCK_FRAME_SIZE)
        self.assertTrue(is_inside_lock_frame((left, bottom), width, height))
        self.assertTrue(is_inside_lock_frame((right, top), width, height))
        self.assertFalse(is_inside_lock_frame((right + 0.01, top), width, height))
        self.assertTrue(is_inside_expanded_lock_frame((right + 1.0, height / 2), width, height))

        center = (width / 2, height / 2)
        target = (width * 2, -height)
        self.assertEqual(
            reticle_position_for_progress(center, bounds, target, 0.0),
            center,
        )
        self.assertEqual(
            reticle_position_for_progress(center, bounds, target, 1.0),
            (right, bottom),
        )

    def test_target_selection_is_sticky_then_uses_distance_and_id_tiebreak(self) -> None:
        candidates = [
            SimpleNamespace(aircraft_id="b", visible=True, in_lock_frame=True, distance_from_center=4.0),
            SimpleNamespace(aircraft_id="a", visible=True, in_lock_frame=True, distance_from_center=4.0),
            SimpleNamespace(aircraft_id="outside", visible=True, in_lock_frame=False, distance_from_center=0.0),
        ]
        self.assertEqual(select_lock_target(candidates).aircraft_id, "a")
        self.assertEqual(select_lock_target(candidates, current_target_id="b").aircraft_id, "b")
        self.assertIsNone(select_lock_target([], current_target_id="missing"))

    def test_lock_tracker_keeps_target_during_buffer_and_requires_frame_for_fire(self) -> None:
        tracker = LockOnTracker(scope_enabled=True)
        tracker.set_target("aircraft-a")
        self.assertEqual(
            tracker.update(target_visible=True, target_in_frame=True, delta_seconds=3.0),
            LockState.GREEN_READY,
        )
        self.assertTrue(tracker.fireable)
        self.assertEqual(
            tracker.update(target_visible=True, target_in_frame=False, delta_seconds=0.25),
            LockState.RED_TRACKING,
        )
        self.assertAlmostEqual(tracker.progress, 2 / 3)
        self.assertFalse(tracker.fireable)
        tracker.update(target_visible=True, target_in_frame=False, delta_seconds=0.50)
        self.assertEqual(tracker.progress, 0.0)
        self.assertIsNone(tracker.target_aircraft_id)

    def test_weapon_views_are_independent_and_resettable(self) -> None:
        aa = AntiAircraftGun(world_position=(0, 0, 0))
        sniper = SniperRifle(world_position=(0, 0, 0))
        pistol = Pistol(world_position=(0, 0, 0))
        aa.fire_cooldown = config.AA_FIRE_COOLDOWN_SECONDS / 2
        sniper.fire_cooldown = config.SNIPER_FIRE_COOLDOWN_SECONDS
        views = {
            kind: weapon_cooldown_view(kind, {"aa": aa, "sniper": sniper, "pistol": pistol})
            for kind in ("aa", "sniper", "pistol")
        }
        self.assertAlmostEqual(views["aa"].fill_ratio, 0.5)
        self.assertEqual(views["sniper"].fill_ratio, 0.0)
        self.assertTrue(views["pistol"].ready)
        reset_weapon_cooldowns(aa, sniper, pistol)
        self.assertEqual((aa.fire_cooldown, sniper.fire_cooldown, pistol.fire_cooldown), (0.0, 0.0, 0.0))

    def test_weapon_cooldown_view_caps_remaining_at_configured_duration(self) -> None:
        aa = AntiAircraftGun(world_position=(0, 0, 0))
        aa.fire_cooldown = config.AA_FIRE_COOLDOWN_SECONDS * 4.0

        view = weapon_cooldown_view("aa", {"aa": aa})

        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.remaining_seconds, config.AA_FIRE_COOLDOWN_SECONDS)
        self.assertEqual(view.fill_ratio, 0.0)
        self.assertFalse(view.ready)

    def test_scope_view_is_procedural_and_circular(self) -> None:
        from air_defense.rules import sniper_scope_view

        view = sniper_scope_view(True)
        self.assertTrue(view.enabled)
        self.assertTrue(view.circular_mask)
        self.assertTrue(view.crosshair)
        self.assertTrue(view.center_dot)
        self.assertFalse(view.checkerboard)
        self.assertEqual(view.fov, config.CAMERA_SCOPE_FOV)
        self.assertFalse(sniper_scope_view(False).enabled)

    def test_tracer_fixture_moves_head_linearly_and_expires(self) -> None:
        tracer = GroundTracerEffect(
            id="tracer-1",
            start_position=(0.0, 1.0, 0.0),
            target_position=(10.0, 1.0, 0.0),
        )
        self.assertEqual(tracer.lifetime_seconds, config.GROUND_TRACER_LIFETIME_SECONDS)
        tracer.advance(tracer.lifetime_seconds / 2)
        self.assertAlmostEqual(tracer.travel_progress, 0.5)
        self.assertAlmostEqual(tracer.head_position[0], 5.0)
        self.assertLess(tracer.tail_position[0], tracer.head_position[0])
        self.assertTrue(tracer.advance(tracer.lifetime_seconds / 2))
        self.assertTrue(tracer.expired)
        self.assertEqual(tracer.visual_color, config.YELLOW_RGB)


class AggregateWaveFixtureTests(unittest.TestCase):
    def test_wave_runtime_and_aggregate_factory_preserve_source_order(self) -> None:
        ids = ("a-1", "a-2", "a-3", "a-4")
        types = {
            ids[0]: AircraftType.NORMAL,
            ids[1]: AircraftType.MANPOWER_SUPPORT,
            ids[2]: AircraftType.FAST,
            ids[3]: AircraftType.ARMORED_BOSS,
        }
        plan = WaveDirector().plan_wave(1, aircraft_count=len(ids), cap=6)
        runtime = WaveRuntime(plan.to_progress(), ids, aircraft_types=types)
        self.assertFalse(runtime.all_aircraft_destroyed)
        self.assertTrue(runtime.mark_destroyed(ids[0]))
        self.assertFalse(runtime.mark_destroyed(ids[0]))
        self.assertEqual(runtime.remaining_aircraft_count, 3)
        self.assertTrue(runtime.mark_impacted(ids[1]))
        self.assertFalse(runtime.all_aircraft_destroyed)
        random_source = FixedRandom(2)
        encounter = EncounterFactory().create_for_wave(3, ids, types, random_source)
        self.assertEqual(encounter.id, "encounter:wave-3")
        self.assertEqual(encounter.source_aircraft_ids, ids)
        self.assertEqual(len(encounter.crew), 2 + config.MANPOWER_SUPPORT_CREW + 0 + 1)
        self.assertEqual(len(random_source.calls), 1)
        self.assertTrue(all(member.id.startswith(tuple(f"{source}-" for source in ids)) for member in encounter.crew))


class VictoryHudFixtureTests(unittest.TestCase):
    def test_victory_presentation_is_frozen_and_has_return_action(self) -> None:
        hud = GameHUD.__new__(GameHUD)
        hud.menu_root = SimpleNamespace(enabled=True)
        hud.gameplay_root = SimpleNamespace(enabled=False)
        hud.game_over_root = SimpleNamespace(enabled=False)
        hud.victory_root = SimpleNamespace(enabled=False)
        hud.victory_text = SimpleNamespace(text="")
        hud.victory_stats_text = SimpleNamespace(text="")
        stats = SimpleNamespace(
            survival_seconds=18.0,
            aircraft_destroyed=12,
            enemies_defeated=24,
        )

        hud.show_victory(stats)

        self.assertFalse(hud.menu_root.enabled)
        self.assertTrue(hud.gameplay_root.enabled)
        self.assertTrue(hud.victory_root.enabled)
        self.assertIn("你贏了", hud.victory_text.text)
        self.assertIn("擊落飛機 12", hud.victory_stats_text.text)

    def test_hybrid_inventory_has_no_descent_progress_contract(self) -> None:
        self.assertTrue(all(
            inventory_selection_allowed(GamePhase.HYBRID_COMBAT, weapon)
            for weapon in WeaponKind
        ))

    def test_hybrid_reticle_selects_the_requested_weapon_family(self) -> None:
        hud = GameHUD.__new__(GameHUD)
        hud.lock_frame = SimpleNamespace(enabled=False)
        hud.lock_label = SimpleNamespace(enabled=False)
        hud.lock_reticle = SimpleNamespace(enabled=False)
        hud.sniper_crosshair = SimpleNamespace(enabled=False)
        hud.pistol_reticle = SimpleNamespace(enabled=False)
        hud.scope_overlay = SimpleNamespace(enabled=False)

        hud.update_reticle(WeaponKind.SNIPER, GamePhase.HYBRID_COMBAT)
        self.assertTrue(hud.sniper_crosshair.enabled)
        self.assertFalse(hud.pistol_reticle.enabled)
        self.assertFalse(hud.lock_frame.enabled)

        hud.update_reticle(WeaponKind.ANTI_AIRCRAFT, GamePhase.HYBRID_COMBAT, anti_air_scope_enabled=True)
        self.assertTrue(hud.lock_frame.enabled)
        self.assertTrue(hud.lock_label.enabled)
        self.assertFalse(hud.sniper_crosshair.enabled)


if __name__ == "__main__":
    unittest.main()
