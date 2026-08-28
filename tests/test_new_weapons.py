"""006 RPG、多目標鎖定與固定砲塔的純規則測試。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from air_defense import config
from air_defense.entities import (
    AutoDefenseTurret,
    CrewMember,
    MultiAntiAircraftGun,
    RPGProjectileEffect,
)
from air_defense.rules import (
    MultiLockOnTracker,
    apply_rpg_explosion,
    auto_defense_damage_for_target,
    can_auto_defense_target,
    is_valid_target,
    resolve_rpg_targets,
    select_turret_target,
)
from air_defense.state import CrewBehaviorState, SquadRole, WeaponKind


def _crew(
    identifier: str,
    position: tuple[float, float, float],
    *,
    descending: bool = False,
    boss: bool = False,
) -> CrewMember:
    return CrewMember(
        id=identifier,
        encounter_id="encounter-1",
        cover_node="cover-north",
        squad_role=SquadRole.COVER_SHOOTER,
        position=position,
        behavior_state=(CrewBehaviorState.DESCENDING if descending else CrewBehaviorState.IN_COVER),
        is_boss=boss,
    )


class NewWeaponRuleTests(unittest.TestCase):
    def test_rpg_projectile_is_green_rectangular_and_expires(self) -> None:
        projectile = RPGProjectileEffect(
            id="rpg-projectile-1",
            start_position=(0.0, 1.0, 0.0),
            target_position=(4.0, 1.0, 0.0),
        )

        self.assertEqual(projectile.visual_color, config.GREEN_RGB)
        self.assertGreater(projectile.length, projectile.width)
        self.assertGreater(projectile.length, projectile.height)
        self.assertEqual(projectile.travel_progress, 0.0)
        self.assertFalse(projectile.advance(projectile.lifetime_seconds / 2.0))
        self.assertGreater(projectile.travel_progress, 0.0)
        self.assertTrue(projectile.advance(projectile.lifetime_seconds))
        self.assertTrue(projectile.expired)

    def test_auto_defense_normal_enemy_needs_three_one_damage_hits(self) -> None:
        normal = _crew("normal-auto-defense", (0.0, 0.0, 0.0))
        normal.health = 3
        normal.max_health = 3

        for hit_number in range(2):
            self.assertEqual(
                auto_defense_damage_for_target(normal, 1),
                1,
                msg=f"hit {hit_number + 1}",
            )
            self.assertFalse(normal.take_damage(1))
        self.assertTrue(normal.take_damage(auto_defense_damage_for_target(normal, 1)))
        self.assertFalse(normal.alive)

    def test_auto_defense_can_hit_boss_only_until_half_health(self) -> None:
        boss = _crew("boss-auto-defense", (0.0, 0.0, 0.0), boss=True)

        for _ in range(config.GROUND_BOSS_HEALTH // 2):
            self.assertTrue(can_auto_defense_target(boss))
            damage = auto_defense_damage_for_target(boss, 1)
            self.assertEqual(damage, 1)
            self.assertFalse(boss.take_damage(damage))

        self.assertEqual(boss.health, config.GROUND_BOSS_HEALTH // 2)
        self.assertFalse(can_auto_defense_target(boss))
        self.assertEqual(auto_defense_damage_for_target(boss, 1), 0)

    def test_auto_defense_range_is_short_and_inclusive(self) -> None:
        inside = _crew("inside-range", (0.0, 0.0, config.AUTO_DEFENSE_MAX_RANGE))
        outside = _crew("outside-range", (0.0, 0.0, config.AUTO_DEFENSE_MAX_RANGE + 0.001))

        self.assertIs(
            select_turret_target(
                (0.0, 0.0, 0.0),
                (inside,),
                max_range=config.AUTO_DEFENSE_MAX_RANGE,
            ),
            inside,
        )
        self.assertIsNone(
            select_turret_target(
                (0.0, 0.0, 0.0),
                (outside,),
                max_range=config.AUTO_DEFENSE_MAX_RANGE,
            )
        )

    def test_auto_defense_default_cd_matches_player_pistol_cd(self) -> None:
        self.assertEqual(
            config.AUTO_DEFENSE_FIRE_COOLDOWN_SECONDS,
            config.PISTOL_FIRE_COOLDOWN_SECONDS,
        )

    def test_rpg_hits_each_enemy_once_inside_radius(self) -> None:
        close = _crew("close", (1.0, 0.0, 0.0))
        second = _crew("second", (5.0, 0.0, 0.0))
        far = _crew("far", (7.0, 0.0, 0.0))
        enemies = (close, second, close, far)
        hit_ids = apply_rpg_explosion((0.0, 0.0, 0.0), enemies, radius=6.0, damage=1)
        self.assertEqual(hit_ids, ("close", "second"))
        self.assertFalse(close.alive)
        self.assertFalse(second.alive)
        self.assertTrue(far.alive)

    def test_rpg_duplicate_collision_callback_is_ignored_for_same_explosion(self) -> None:
        target = _crew("target", (1.0, 0.0, 0.0))
        registry: set[str] = set()
        first = apply_rpg_explosion(
            (0.0, 0.0, 0.0),
            (target,),
            radius=6.0,
            damage=1,
            explosion_id="explosion-1",
            hit_registry=registry,
        )
        second = apply_rpg_explosion(
            (0.0, 0.0, 0.0),
            (target,),
            radius=6.0,
            damage=1,
            explosion_id="explosion-1",
            hit_registry=registry,
        )
        self.assertEqual(first, ("target",))
        self.assertEqual(second, ())

    def test_rpg_explosion_never_hits_aircraft(self) -> None:
        ground = _crew("ground", (1.0, 0.0, 0.0))
        aircraft_damage_calls: list[int] = []
        aircraft = SimpleNamespace(
            id="aircraft",
            aircraft_type="NORMAL",
            phase="APPROACHING",
            health=1,
            position=(1.0, 0.0, 0.0),
            take_damage=lambda amount: aircraft_damage_calls.append(amount),
        )
        hit_ids = apply_rpg_explosion(
            (0.0, 0.0, 0.0),
            (ground, aircraft),
            radius=6.0,
            damage=1,
        )
        self.assertEqual(hit_ids, ("ground",))
        self.assertFalse(ground.alive)
        self.assertEqual(aircraft_damage_calls, [])

    def test_rpg_cannot_select_aircraft_as_explosion_center(self) -> None:
        aircraft = SimpleNamespace(
            id="aircraft",
            aircraft_type="NORMAL",
            phase="APPROACHING",
            health=1,
            position=(1.0, 0.0, 0.0),
        )

    def test_rpg_center_snapshot_contains_only_ground_targets(self) -> None:
        ground = _crew("ground-center", (0.0, 0.0, 0.0))
        aircraft = SimpleNamespace(
            id="aircraft-center",
            aircraft_type="NORMAL",
            phase="APPROACHING",
            health=1,
            position=(0.0, 0.0, 0.0),
        )
        snapshot = resolve_rpg_targets((0.0, 0.0, 0.0), (ground, aircraft), radius=6.0)
        self.assertEqual(tuple(target.id for target in snapshot), (ground.id,))
        self.assertFalse(
            is_valid_target(
                WeaponKind.RPG,
                aircraft,
                distance=1.0,
                cooldown_remaining=0.0,
                ammo_remaining=1,
            )
        )

    def test_multi_lock_ignores_legacy_capacity_and_tracks_all_targets(self) -> None:
        tracker = MultiLockOnTracker(target_capacity=2, lock_duration=1.0, decay_duration=1.0)
        candidates = {
            "a": SimpleNamespace(id="a", visible=True, in_lock_frame=True),
            "b": SimpleNamespace(id="b", visible=True, in_lock_frame=True),
            "c": SimpleNamespace(id="c", visible=True, in_lock_frame=True),
        }
        tracker.set_targets(("a", "b", "c", "a"))
        self.assertEqual(tracker.target_ids, ("a", "b", "c"))
        tracker.update(candidates, 1.0)
        self.assertEqual(tracker.ready_target_ids, ("a", "b", "c"))
        self.assertEqual(tracker.mark_fired("volley-1"), ("a", "b", "c"))

    def test_multi_lock_dynamic_set_keeps_independent_progress_for_ten_plus_targets(self) -> None:
        tracker = MultiLockOnTracker(target_capacity=2, lock_duration=1.0, decay_duration=1.0)
        candidates = {
            f"aircraft-{index:02d}": SimpleNamespace(
                id=f"aircraft-{index:02d}",
                visible=True,
                in_lock_frame=True,
            )
            for index in range(12)
        }
        tracker.update(candidates, 0.5)
        self.assertEqual(len(tracker.target_ids), 12)
        self.assertEqual(set(tracker.lock_progress), set(candidates))

        leaving = candidates["aircraft-00"]
        leaving.in_lock_frame = False
        tracker.update(candidates, 0.25)
        self.assertAlmostEqual(tracker.lock_progress["aircraft-00"], 0.25)
        self.assertAlmostEqual(tracker.lock_progress["aircraft-01"], 0.75)

        candidates["aircraft-01"].visible = False
        tracker.update(candidates, 0.0)
        self.assertNotIn("aircraft-01", tracker.target_ids)

    def test_multi_lock_empty_or_partial_set_is_never_fireable(self) -> None:
        tracker = MultiLockOnTracker(target_capacity=6, lock_duration=1.0)
        self.assertFalse(tracker.all_targets_ready)
        self.assertEqual(tracker.fireable_targets(), ())
        tracker.update(
            {
                "ready": SimpleNamespace(id="ready", visible=True, in_lock_frame=True),
                "partial": SimpleNamespace(id="partial", visible=True, in_lock_frame=True),
            },
            1.0,
        )
        tracker.trackers["partial"].lock_elapsed = 0.25
        tracker.update(
            {
                "ready": SimpleNamespace(id="ready", visible=True, in_lock_frame=True),
                "partial": SimpleNamespace(id="partial", visible=True, in_lock_frame=True),
            },
            0.0,
        )
        self.assertFalse(tracker.all_targets_ready)
        self.assertEqual(tracker.fireable_targets(), ())

    def test_multi_aircraft_gun_does_not_truncate_legacy_capacity(self) -> None:
        gun = MultiAntiAircraftGun(world_position=(0.0, 0.0, 0.0), target_capacity=2)
        target_ids = tuple(f"aircraft-{index}" for index in range(10))
        self.assertEqual(gun.set_targets(target_ids), target_ids)

    def test_turret_only_selects_landed_non_boss_minion(self) -> None:
        descending = _crew("descending", (1.0, 0.0, 0.0), descending=True)
        boss = _crew("boss", (2.0, 0.0, 0.0), boss=True)
        landed = _crew("landed", (3.0, 0.0, 0.0))
        self.assertIs(select_turret_target((0.0, 0.0, 0.0), (descending, boss, landed)), landed)
        turret = AutoDefenseTurret(
            id="turret-1",
            position=config.AUTO_DEFENSE_TURRET_POSITIONS[0],
            ammo_remaining=20,
        )
        turret.assign_target(landed.id)
        self.assertTrue(turret.can_fire)
        self.assertTrue(turret.mark_fired())
        self.assertIsNone(turret.ammo_remaining)
        self.assertEqual(turret.cooldown_remaining, config.PISTOL_FIRE_COOLDOWN_SECONDS)

    def test_auto_defense_ignores_legacy_finite_ammo_values(self) -> None:
        turret = AutoDefenseTurret(
            id="turret-unlimited",
            position=(0.0, 0.0, 0.0),
            ammo_remaining=0,
            cooldown_seconds=0.0,
        )
        turret.assign_target("landed-target")

        self.assertTrue(turret.can_fire)
        self.assertTrue(turret.mark_fired())
        self.assertTrue(turret.can_fire)
        self.assertIsNone(turret.ammo_remaining)


if __name__ == "__main__":
    unittest.main()
