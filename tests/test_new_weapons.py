"""006 RPG、多目標鎖定與固定砲塔的純規則測試。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from air_defense import config
from air_defense.entities import AutoDefenseTurret, CrewMember
from air_defense.rules import (
    MultiLockOnTracker,
    apply_rpg_explosion,
    is_valid_target,
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
        self.assertFalse(
            is_valid_target(
                WeaponKind.RPG,
                aircraft,
                distance=1.0,
                cooldown_remaining=0.0,
                ammo_remaining=1,
            )
        )

    def test_multi_lock_respects_capacity_and_tracks_each_target(self) -> None:
        tracker = MultiLockOnTracker(target_capacity=2, lock_duration=1.0, decay_duration=1.0)
        candidates = {
            "a": SimpleNamespace(id="a", visible=True, in_lock_frame=True),
            "b": SimpleNamespace(id="b", visible=True, in_lock_frame=True),
            "c": SimpleNamespace(id="c", visible=True, in_lock_frame=True),
        }
        tracker.set_targets(("a", "b", "c", "a"))
        self.assertEqual(tracker.target_ids, ("a", "b"))
        tracker.update(candidates, 1.0)
        self.assertEqual(tracker.ready_target_ids, ("a", "b"))
        self.assertEqual(tracker.mark_fired("volley-1"), ("a", "b"))

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
        self.assertEqual(turret.ammo_remaining, 19)
        self.assertEqual(turret.cooldown_remaining, 1.5)


if __name__ == "__main__":
    unittest.main()
