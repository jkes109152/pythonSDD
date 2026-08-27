"""Ursina scene adapter for the air-defense game.

The domain rules never depend on this module. This adapter owns only visual
entities, camera raycasts and translation between engine positions and domain
objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from ursina import Entity, Vec3, camera, color, destroy, raycast, scene as ursina_scene
from ursina.prefabs.first_person_controller import FirstPersonController

from . import config
from .entities import Aircraft, GroundEncounter
from .rules import aircraft_profile
from .state import AircraftType


def _rgb(values: tuple[float, float, float]):
    return color.rgb(*values)


@dataclass
class WorldHandles:
    ground: Entity
    target_building: Entity
    crash_site: Entity
    weapon_rack: Entity
    anti_aircraft_pickup: Entity
    sniper_pickup: Entity
    cover_nodes: dict[str, Entity]
    obstacles: tuple[Entity, ...] = ()


class AirDefenseScene:
    """Creates the long plain, collidable cover route and visual adapters."""

    def __init__(self) -> None:
        self.asset_root = Path(__file__).resolve().parents[1] / "assets" / "air_defense"
        self.world: Optional[WorldHandles] = None
        self._static_entities: list[Entity] = []
        self._dynamic_entities: list[Entity] = []
        self.player_controller: Optional[FirstPersonController] = None
        self.aircraft_entity: Optional[Entity] = None
        self.crew_entities: dict[str, Entity] = {}
        self._effects: list[tuple[Entity, float]] = []

    def create_optional_model(
        self,
        asset_name: str,
        *,
        fallback_model: str = "cube",
        **kwargs: object,
    ) -> Entity:
        """Create a visual from an optional local asset or procedural fallback."""

        candidate = (self.asset_root / asset_name).resolve()
        asset_root = self.asset_root.resolve()
        use_asset = asset_root in candidate.parents and candidate.is_file()
        model = str(candidate) if use_asset else fallback_model
        try:
            return Entity(model=model, **kwargs)
        except Exception:
            if model == fallback_model:
                raise
            return Entity(model=fallback_model, **kwargs)

    def build_world(self) -> WorldHandles:
        self.clear_world()

        ground = Entity(
            model="plane",
            position=config.GROUND_CENTER,
            scale=(config.MAP_WIDTH, 1, config.MAP_LENGTH),
            color=_rgb((0.28, 0.38, 0.25)),
            collider="box",
        )
        self._static_entities.append(ground)

        road = Entity(
            model="cube",
            position=(0, 0.015, 8),
            scale=(config.MAP_WIDTH, 0.03, 5),
            color=_rgb((0.16, 0.17, 0.19)),
        )
        crossroad = Entity(
            model="cube",
            position=(0, 0.02, -2),
            scale=(5, 0.035, config.MAP_LENGTH),
            color=_rgb((0.16, 0.17, 0.19)),
        )
        self._static_entities.extend((road, crossroad))

        target_position = config.BUILDING_POSITION
        target_building = Entity(
            model="cube",
            position=target_position,
            scale=(10, 12, 9),
            color=_rgb((0.45, 0.55, 0.68)),
            collider="box",
        )
        roof = Entity(
            model="cube",
            parent=target_building,
            y=0.52,
            scale=(1.03, 0.04, 1.03),
            color=_rgb((0.12, 0.14, 0.18)),
        )
        self._static_entities.extend((target_building, roof))

        crash_site = Entity(
            model="cube",
            position=config.CRASH_SITE_POSITION,
            scale=(4.0, 0.08, 4.0),
            color=_rgb((0.28, 0.16, 0.12)),
        )
        self._static_entities.append(crash_site)

        obstacles: list[Entity] = []
        for position, scale, tint in config.OBSTACLE_LAYOUT:
            obstacle = Entity(
                model="cube",
                position=position,
                scale=scale,
                color=_rgb(tint),
                collider="box",
            )
            obstacle.obstacle_id = f"obstacle-{len(obstacles) + 1:02d}"
            obstacles.append(obstacle)
        self._static_entities.extend(obstacles)

        rack_position = config.WEAPON_RACK_POSITION
        weapon_rack = Entity(
            model="cube",
            position=rack_position,
            scale=(2.2, 2.0, 0.7),
            color=_rgb((0.3, 0.22, 0.14)),
            collider="box",
        )
        rack_sign = Entity(
            model="cube",
            parent=weapon_rack,
            y=0.4,
            z=-0.51,
            scale=(0.75, 0.35, 0.03),
            color=_rgb((0.9, 0.75, 0.2)),
        )
        self._static_entities.extend((weapon_rack, rack_sign))

        aa_x, aa_y, aa_z = config.DEFENSE_POINT_POSITION
        anti_aircraft_pickup = Entity(
            model="cube",
            position=(aa_x, aa_y + 0.45, aa_z),
            scale=(1.5, 0.45, 0.55),
            rotation=(0, 20, 8),
            color=_rgb((0.22, 0.26, 0.3)),
            collider="box",
        )
        anti_aircraft_pickup.interaction_kind = "anti_aircraft"
        sniper_pickup = Entity(
            model="cube",
            position=(rack_position[0], rack_position[1] + 0.9, rack_position[2] - 0.65),
            scale=(1.25, 0.16, 0.16),
            rotation=(0, 0, 15),
            color=_rgb((0.14, 0.15, 0.17)),
            collider="box",
        )
        sniper_pickup.interaction_kind = "sniper"
        sniper_pickup.enabled = False
        self._static_entities.extend((anti_aircraft_pickup, sniper_pickup))

        cover_nodes: dict[str, Entity] = {}
        for node_id, route_position in config.COVER_NODE_POSITIONS.items():
            position = (route_position[0], 0.8, route_position[2])
            node = Entity(
                model="cube",
                position=position,
                scale=(2.8, 1.6, 1.2),
                color=_rgb((0.34, 0.34, 0.38)),
                collider="box",
            )
            node.cover_node_id = node_id
            cover_nodes[node_id] = node
            self._static_entities.append(node)

        self.world = WorldHandles(
            ground=ground,
            target_building=target_building,
            crash_site=crash_site,
            weapon_rack=weapon_rack,
            anti_aircraft_pickup=anti_aircraft_pickup,
            sniper_pickup=sniper_pickup,
            cover_nodes=cover_nodes,
            obstacles=tuple(obstacles),
        )
        self._create_player()
        return self.world

    def _create_player(self) -> None:
        if self.player_controller is not None:
            destroy(self.player_controller)
        self.player_controller = FirstPersonController(
            position=config.DEFENSE_POINT_POSITION,
            speed=config.PLAYER_SPEED,
            gravity=config.PLAYER_GRAVITY,
            jump_height=config.PLAYER_JUMP_HEIGHT,
        )
        # Use the game's HUD reticle instead of the controller's pink cursor.
        self.player_controller.cursor.visible = False
        self.player_controller.enabled = True

    def set_gameplay_enabled(self, enabled: bool) -> None:
        if self.player_controller is not None:
            self.player_controller.enabled = enabled
            self.player_controller.cursor.visible = False

    def set_scope_enabled(self, enabled: bool) -> None:
        """Bridge the sniper scope state to the actual camera field of view."""

        camera.fov = config.CAMERA_SCOPE_FOV if enabled else config.CAMERA_DEFAULT_FOV

    def clear_dynamic(self) -> None:
        if self.aircraft_entity is not None:
            destroy(self.aircraft_entity)
            self.aircraft_entity = None
        for entity in self.crew_entities.values():
            destroy(entity)
        self.crew_entities.clear()
        for entity, _ in self._effects:
            destroy(entity)
        self._effects.clear()
        self._dynamic_entities.clear()

    def clear_world(self) -> None:
        self.clear_dynamic()
        self.set_scope_enabled(False)
        if self.player_controller is not None:
            destroy(self.player_controller)
            self.player_controller = None
        for entity in self._static_entities:
            destroy(entity)
        self._static_entities.clear()
        self.world = None

    def player_position(self) -> Vec3:
        if self.player_controller is None:
            return Vec3(0, 0, 0)
        return self.player_controller.world_position

    def is_near(self, position: tuple[float, float, float], radius: float = 3.2) -> bool:
        return distance_xz(self.player_position(), position) <= radius

    def interactable_under_center(
        self,
        max_distance: float = 5.0,
        *,
        preferred_kind: Optional[str] = None,
    ) -> Optional[Entity]:
        if self.world is None:
            return None
        if preferred_kind == "anti_aircraft":
            interactables = [self.world.anti_aircraft_pickup]
        elif preferred_kind == "sniper":
            interactables = [self.world.sniper_pickup, self.world.weapon_rack]
        else:
            interactables = [
                self.world.anti_aircraft_pickup,
                self.world.sniper_pickup,
                self.world.weapon_rack,
            ]
        hit = self.center_raycast(max_distance, ignore=[self.player_controller])
        if hit is not None:
            current = hit
            while current is not None:
                if current in interactables:
                    return current
                current = getattr(current, "parent", None)
        for entity in interactables:
            if entity.enabled and self.is_near(entity.world_position, 2.8):
                return entity
        return None

    def center_raycast(
        self,
        max_distance: float = 200.0,
        *,
        ignore: Optional[Iterable[Entity]] = None,
    ) -> Optional[Entity]:
        ignored = [entity for entity in (ignore or []) if entity is not None]
        try:
            hit = raycast(
                camera.world_position,
                camera.forward,
                distance=max_distance,
                traverse_target=ursina_scene,
                ignore=ignored,
            )
        except TypeError:
            hit = raycast(
                camera.world_position,
                camera.forward,
                distance=max_distance,
                traverse_target=ursina_scene,
            )
        return hit.entity if hit.hit else None

    def aircraft_is_visible(self, aircraft_entity: Optional[Entity]) -> bool:
        if aircraft_entity is None or not aircraft_entity.enabled:
            return False
        hit = self.center_raycast(250.0, ignore=[self.player_controller])
        if hit is None:
            return False
        current = hit
        while current is not None:
            same_aircraft = (
                current is aircraft_entity
                or getattr(current, "aircraft_id", None)
                == getattr(aircraft_entity, "aircraft_id", None)
            )
            if same_aircraft:
                return True
            current = getattr(current, "parent", None)
        return False

    def crew_under_center(self, max_distance: float = 150.0) -> Optional[str]:
        hit = self.center_raycast(max_distance, ignore=[self.player_controller])
        current = hit
        while current is not None:
            crew_id = getattr(current, "crew_id", None)
            if crew_id:
                return crew_id
            current = getattr(current, "parent", None)
        return None

    def create_aircraft(self, aircraft: Aircraft) -> Entity:
        profile = aircraft_profile(aircraft.aircraft_type)
        tint = {
            AircraftType.NORMAL: (0.82, 0.25, 0.18),
            AircraftType.MANPOWER_SUPPORT: (0.86, 0.55, 0.14),
            AircraftType.FAST: (0.28, 0.62, 0.92),
            AircraftType.ARMORED_BOSS: (0.62, 0.18, 0.68),
        }[aircraft.aircraft_type]
        scale = (1.9, 0.6, 3.2) if aircraft.aircraft_type == AircraftType.ARMORED_BOSS else (1.6, 0.45, 2.8)
        self.aircraft_entity = self.create_optional_model(
            "aircraft.glb",
            fallback_model="cube",
            position=aircraft.position,
            scale=scale,
            rotation=(12, 0, 0),
            color=_rgb(tint),
            collider="box",
        )
        self.aircraft_entity.aircraft_id = aircraft.id
        self.aircraft_entity.aircraft_type = aircraft.aircraft_type
        self.aircraft_entity.aircraft_health = aircraft.health
        self.aircraft_entity.aircraft_max_health = profile.max_health
        wing = Entity(
            parent=self.aircraft_entity,
            model="cube",
            scale=(3.6, 0.08, 0.75) if aircraft.aircraft_type == AircraftType.ARMORED_BOSS else (3.0, 0.08, 0.65),
            y=0.02,
            color=_rgb((0.25, 0.28, 0.35)),
        )
        self._dynamic_entities.extend((self.aircraft_entity, wing))
        return self.aircraft_entity

    def update_aircraft(self, aircraft: Aircraft) -> None:
        if self.aircraft_entity is None:
            return
        self.aircraft_entity.position = aircraft.position
        self.aircraft_entity.aircraft_health = aircraft.health
        self.aircraft_entity.look_at(Vec3(*config.AIRCRAFT_TARGET_POSITION))

    def remove_aircraft(self, *, crash: bool = False) -> None:
        if self.aircraft_entity is None:
            return
        if crash:
            explosion = Entity(
                model="sphere",
                position=self.aircraft_entity.position,
                scale=1.0,
                color=_rgb((1.0, 0.38, 0.08)),
            )
            self._effects.append((explosion, 0.6))
        destroy(self.aircraft_entity)
        self.aircraft_entity = None

    def create_crew(self, encounter: GroundEncounter) -> None:
        if self.world is None:
            return
        for member in encounter.crew:
            tint = (0.55, 0.12, 0.7) if member.is_boss else (0.72, 0.18, 0.16)
            entity = self.create_optional_model(
                "crew.glb",
                fallback_model="cube",
                position=Vec3(*member.position) + Vec3(0, 0.9, 0),
                scale=(0.9, 2.4, 0.9) if member.is_boss else (0.65, 1.8, 0.65),
                color=_rgb(tint),
                collider="box",
            )
            entity.crew_id = member.id
            entity.is_boss = member.is_boss
            head = Entity(
                parent=entity,
                model="sphere",
                y=0.62,
                scale=0.45,
                color=_rgb((0.92, 0.7, 0.5)),
            )
            self.crew_entities[member.id] = entity
            self._dynamic_entities.extend((entity, head))

    def update_crew(self, encounter: GroundEncounter) -> None:
        if self.world is None:
            return
        for member in encounter.crew:
            entity = self.crew_entities.get(member.id)
            if entity is None:
                continue
            entity.enabled = member.alive
            if member.alive:
                entity.position = Vec3(*member.position) + Vec3(0, 0.9, 0)

    def remove_crew_member(self, crew_id: str) -> None:
        entity = self.crew_entities.pop(crew_id, None)
        if entity is not None:
            destroy(entity)

    def move_weapon_pickup(
        self,
        kind: str,
        position: tuple[float, float, float],
        *,
        enabled: bool = True,
    ) -> None:
        if self.world is None:
            return
        entity = (
            self.world.anti_aircraft_pickup
            if kind == "anti_aircraft"
            else self.world.sniper_pickup
        )
        entity.position = position
        entity.enabled = enabled

    def tick_effects(self, delta_seconds: float) -> None:
        remaining: list[tuple[Entity, float]] = []
        for entity, lifetime in self._effects:
            lifetime -= max(0.0, delta_seconds)
            entity.scale += Vec3(delta_seconds * 3, delta_seconds * 3, delta_seconds * 3)
            if lifetime <= 0:
                destroy(entity)
            else:
                remaining.append((entity, lifetime))
        self._effects = remaining


def distance_xz(first: Vec3, second: tuple[float, float, float] | Vec3) -> float:
    second_vec = second if isinstance(second, Vec3) else Vec3(*second)
    delta = first - second_vec
    return (delta.x * delta.x + delta.z * delta.z) ** 0.5
