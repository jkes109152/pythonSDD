"""Ursina scene adapter for the air-defense game.

The domain rules never depend on this module. This adapter owns only visual
entities, camera raycasts and translation between engine positions and domain
objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import radians, tan
from pathlib import Path
from typing import Iterable, Optional

from ursina import Entity, Vec3, camera, color, destroy, raycast, scene as ursina_scene, window
from ursina.prefabs.first_person_controller import FirstPersonController

from . import config
from .entities import (
    Aircraft,
    AutoDefenseTurret,
    CrewMember,
    GroundEncounter,
    GroundTracerEffect,
    GuidedMissile,
)
from .rules import (
    aircraft_profile,
    apply_aim_assist,
    clamp_screen_radius,
    is_inside_expanded_lock_frame,
    is_inside_lock_frame,
    lock_zone_radius,
    raycast_hit_matches_target,
)
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
    turret_positions: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True)
class AircraftScreenTarget:
    """Transient projection data shared by lock evaluation and the HUD."""

    visible: bool
    screen_position: tuple[float, float]
    hud_position: tuple[float, float]
    screen_radius: float
    distance_from_center: float
    in_lock_zone: bool = False
    aircraft_id: Optional[str] = None
    in_lock_frame: bool = False
    in_expanded_lock_frame: bool = False

    @property
    def target_id(self) -> Optional[str]:
        return self.aircraft_id


class AirDefenseScene:
    """Creates the long plain, collidable cover route and visual adapters."""

    def __init__(self) -> None:
        self.asset_root = Path(__file__).resolve().parents[1] / "assets" / "air_defense"
        self.world: Optional[WorldHandles] = None
        self._static_entities: list[Entity] = []
        self._dynamic_entities: list[Entity] = []
        self.player_controller: Optional[FirstPersonController] = None
        self.aircraft_entity: Optional[Entity] = None
        self.aircraft_entities: dict[str, Entity] = {}
        self.missile_entities: dict[str, Entity] = {}
        self.crew_entities: dict[str, Entity] = {}
        self._effects: list[tuple[Entity, float]] = []
        self.tracer_entities: dict[str, Entity] = {}
        self.tracer_effects: dict[str, GroundTracerEffect] = {}
        self.turret_entities: dict[str, Entity] = {}
        self.multi_lock_entities: dict[str, Entity] = {}
        self._last_aircraft_targets: dict[str, AircraftScreenTarget] = {}

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
            turret_positions=tuple(config.AUTO_DEFENSE_TURRET_POSITIONS),
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

    def set_scope_enabled(self, enabled: bool, *, anti_air: bool = False) -> None:
        """Bridge sniper or anti-air scope state to the actual camera FOV."""

        if not enabled:
            camera.fov = config.CAMERA_DEFAULT_FOV
        elif anti_air:
            camera.fov = config.AA_SCOPE_FOV
        else:
            camera.fov = config.CAMERA_SCOPE_FOV

    def viewport_size(self) -> tuple[float, float]:
        size = getattr(window, "size", None)
        if size is None:
            return float(config.WINDOW_WIDTH), float(config.WINDOW_HEIGHT)
        try:
            return max(1.0, float(size[0])), max(1.0, float(size[1]))
        except (TypeError, ValueError, IndexError):
            return float(config.WINDOW_WIDTH), float(config.WINDOW_HEIGHT)

    def clear_dynamic(self, *, clear_effects: bool = True) -> None:
        """Remove gameplay entities, optionally keeping short-lived effects."""

        aircraft_entities = getattr(self, "aircraft_entities", {})
        for entity in tuple(aircraft_entities.values()):
            destroy(entity)
        # A few legacy tests/controllers only populate the scalar view.
        if self.aircraft_entity is not None and self.aircraft_entity not in aircraft_entities.values():
            destroy(self.aircraft_entity)
        aircraft_entities.clear()
        self.aircraft_entity = None
        getattr(self, "_last_aircraft_targets", {}).clear()
        for entity in self.crew_entities.values():
            destroy(entity)
        self.crew_entities.clear()
        for entity in self.missile_entities.values():
            destroy(entity)
        self.missile_entities.clear()
        for entity in getattr(self, "turret_entities", {}).values():
            destroy(entity)
        getattr(self, "turret_entities", {}).clear()
        for entity in getattr(self, "multi_lock_entities", {}).values():
            destroy(entity)
        getattr(self, "multi_lock_entities", {}).clear()
        if clear_effects:
            for entity, _ in self._effects:
                destroy(entity)
            self._effects.clear()
        # Tracers are gameplay feedback, not retained explosion effects, so a
        # ground encounter/terminal cleanup always removes them.
        for entity in getattr(self, "tracer_entities", {}).values():
            destroy(entity)
        getattr(self, "tracer_entities", {}).clear()
        getattr(self, "tracer_effects", {}).clear()
        self._dynamic_entities.clear()

    def _forget_dynamic_entity_refs(self, root: Entity) -> None:
        """Forget a dynamic root and any tracked descendants before destroy."""

        remaining: list[Entity] = []
        for candidate in self._dynamic_entities:
            current: object | None = candidate
            visited: set[int] = set()
            belongs_to_root = False
            while current is not None and id(current) not in visited:
                visited.add(id(current))
                if current is root:
                    belongs_to_root = True
                    break
                current = getattr(current, "parent", None)
            if not belongs_to_root:
                remaining.append(candidate)
        self._dynamic_entities[:] = remaining

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
        target_position = Vec3(*aircraft_entity.world_position)
        origin = camera.world_position
        offset = target_position - origin
        distance = offset.length()
        if distance <= 1e-6 or offset.normalized().dot(camera.forward) <= 0.0:
            return False
        try:
            hit = raycast(
                origin,
                offset.normalized(),
                distance=distance + 0.25,
                traverse_target=ursina_scene,
                ignore=[self.player_controller],
            )
        except TypeError:
            hit = raycast(
                origin,
                offset.normalized(),
                distance=distance + 0.25,
                traverse_target=ursina_scene,
            )
        return raycast_hit_matches_target(hit, aircraft_entity)

    def project_aircraft_target(
        self,
        aircraft_entity: Optional[Entity] = None,
        *,
        lock_frame_size: float = config.AA_LOCK_FRAME_SIZE,
    ) -> Optional[AircraftScreenTarget]:
        """Project one target; the scalar wrapper remains for old callers."""

        entity = aircraft_entity if aircraft_entity is not None else self.aircraft_entity
        if entity is None or not entity.enabled:
            return None
        try:
            projected = entity.screen_position
            hud_position = (float(projected.x), float(projected.y))
            viewport_width, viewport_height = self.viewport_size()
            aspect = max(1e-6, float(getattr(camera, "aspect_ratio", viewport_width / viewport_height)))
            screen_position = (
                (hud_position[0] * 2.0 / aspect + 1.0) * viewport_width * 0.5,
                (hud_position[1] * 2.0 + 1.0) * viewport_height * 0.5,
            )
            visible = self.aircraft_is_visible(entity)
            center_x = viewport_width * 0.5
            center_y = viewport_height * 0.5
            distance_from_center = ((screen_position[0] - center_x) ** 2 + (screen_position[1] - center_y) ** 2) ** 0.5
            radius = self._projected_aircraft_radius(entity, viewport_width, viewport_height)
            in_lock_frame = visible and is_inside_lock_frame(
                screen_position,
                viewport_width,
                viewport_height,
                frame_size=max(0.0, float(lock_frame_size)),
            )
            target = AircraftScreenTarget(
                visible=visible,
                screen_position=screen_position,
                hud_position=hud_position,
                screen_radius=radius,
                distance_from_center=distance_from_center,
                in_lock_zone=in_lock_frame,
                aircraft_id=getattr(entity, "aircraft_id", None),
                in_lock_frame=in_lock_frame,
                in_expanded_lock_frame=visible and is_inside_expanded_lock_frame(
                    screen_position,
                    viewport_width,
                    viewport_height,
                    frame_size=max(0.0, float(lock_frame_size)),
                ),
            )
            target_id = target.aircraft_id
            if target_id is not None:
                self._last_aircraft_targets[target_id] = target
            return target
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            return None

    def project_aircraft_targets(
        self,
        aircraft_entities: Optional[dict[str, Entity]] = None,
        *,
        lock_frame_size: float = config.AA_LOCK_FRAME_SIZE,
    ) -> dict[str, AircraftScreenTarget]:
        """Project every keyed aircraft in stable ID order."""

        entities = aircraft_entities if aircraft_entities is not None else self.aircraft_entities
        projections: dict[str, AircraftScreenTarget] = {}
        for aircraft_id in sorted(entities):
            target = self.project_aircraft_target(
                entities[aircraft_id],
                lock_frame_size=lock_frame_size,
            )
            if target is not None:
                projections[aircraft_id] = target
            elif aircraft_id in self._last_aircraft_targets:
                # Preserve identity/last position during a transient screen
                # projection failure, but never claim that stale data is in
                # the current lock frame or visible.
                previous = self._last_aircraft_targets[aircraft_id]
                projections[aircraft_id] = AircraftScreenTarget(
                    visible=False,
                    screen_position=previous.screen_position,
                    hud_position=previous.hud_position,
                    screen_radius=previous.screen_radius,
                    distance_from_center=previous.distance_from_center,
                    in_lock_zone=False,
                    aircraft_id=aircraft_id,
                    in_lock_frame=False,
                    in_expanded_lock_frame=False,
                )
        return projections

    def _projected_aircraft_radius(
        self,
        entity: Entity,
        viewport_width: float,
        viewport_height: float,
    ) -> float:
        distance = max(0.01, (Vec3(*entity.world_position) - camera.world_position).length())
        world_radius = max(
            0.5,
            abs(float(getattr(entity, "scale_x", 1.0))),
            abs(float(getattr(entity, "scale_y", 1.0))),
            abs(float(getattr(entity, "scale_z", 1.0))),
        ) * 0.5
        fov = max(1.0, float(getattr(camera, "fov", config.CAMERA_DEFAULT_FOV)))
        ui_radius = world_radius / (distance * tan(radians(fov) * 0.5) * 2.0)
        # HUD scales are normalized to the viewport height, so cap them to a
        # readable range regardless of resolution or target distance.
        return clamp_screen_radius(ui_radius)

    def apply_aircraft_aim_assist(
        self,
        target: Optional[AircraftScreenTarget],
        delta_seconds: float,
    ) -> None:
        """Apply the small post-mouse correction to the active first-person camera."""

        if target is None or self.player_controller is None or not target.visible:
            return
        origin = camera.world_position
        target_entity = self.aircraft_entities.get(target.aircraft_id) if target.aircraft_id else self.aircraft_entity
        if target_entity is None:
            return
        target_direction = Vec3(*target_entity.world_position) - origin
        if target_direction.length() <= 1e-6:
            return
        viewport_width, viewport_height = self.viewport_size()
        corrected = apply_aim_assist(
            tuple(float(value) for value in camera.forward),
            tuple(float(value) for value in target_direction.normalized()),
            scope_enabled=True,
            target_visible=target.visible,
            target_screen_distance=target.distance_from_center,
            lock_zone_radius_pixels=lock_zone_radius(viewport_width, viewport_height),
            delta_seconds=delta_seconds,
            target_in_expanded_frame=target.in_expanded_lock_frame,
        )
        camera.look_in_direction(Vec3(*corrected))

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
        old_entity = self.aircraft_entities.pop(aircraft.id, None)
        if old_entity is not None:
            self._forget_dynamic_entity_refs(old_entity)
            if self.aircraft_entity is old_entity:
                self.aircraft_entity = None
            destroy(old_entity)
        entity = self.create_optional_model(
            "aircraft.glb",
            fallback_model="cube",
            position=aircraft.position,
            scale=scale,
            rotation=(12, 0, 0),
            color=_rgb(tint),
            collider="box",
        )
        entity.aircraft_id = aircraft.id
        entity.aircraft_type = aircraft.aircraft_type
        entity.aircraft_health = aircraft.health
        entity.aircraft_max_health = profile.max_health
        entity.look_in_direction(Vec3(*aircraft.forward))
        wing = Entity(
            parent=entity,
            model="cube",
            scale=(3.6, 0.08, 0.75) if aircraft.aircraft_type == AircraftType.ARMORED_BOSS else (3.0, 0.08, 0.65),
            y=0.02,
            color=_rgb((0.25, 0.28, 0.35)),
        )
        self.aircraft_entities[aircraft.id] = entity
        if self.aircraft_entity is None:
            self.aircraft_entity = entity
        self._dynamic_entities.extend((entity, wing))
        return entity

    def update_aircraft(self, aircraft: Aircraft) -> None:
        entity = self.aircraft_entities.get(aircraft.id)
        if entity is None and self.aircraft_entity is not None:
            entity = self.aircraft_entity
        if entity is None:
            return
        entity.position = aircraft.position
        entity.aircraft_health = aircraft.health
        entity.look_in_direction(Vec3(*aircraft.forward))

    def create_guided_missile(self, missile: GuidedMissile) -> Entity:
        """Create the yellow elongated cuboid used for one valid anti-air shot."""

        entity = Entity(
            model="cube",
            position=missile.position,
            scale=(config.GUIDED_MISSILE_WIDTH, config.GUIDED_MISSILE_HEIGHT, config.GUIDED_MISSILE_LENGTH),
            color=_rgb(config.YELLOW_RGB),
        )
        entity.missile_id = missile.id
        entity.target_aircraft_id = missile.target_aircraft_id
        entity.look_in_direction(Vec3(*missile.forward))
        self.missile_entities[missile.id] = entity
        self._dynamic_entities.append(entity)
        return entity

    def update_guided_missile(self, missile: GuidedMissile) -> None:
        entity = self.missile_entities.get(missile.id)
        if entity is None:
            return
        entity.position = missile.position
        entity.look_in_direction(Vec3(*missile.forward))

    def remove_guided_missile(self, missile_id: str, *, explode: bool = False) -> None:
        entity = self.missile_entities.pop(missile_id, None)
        if entity is None:
            return
        if explode:
            explosion = Entity(
                model="sphere",
                position=entity.position,
                scale=0.45,
                color=_rgb(config.YELLOW_RGB),
            )
            self._effects.append((explosion, config.GUIDED_MISSILE_EXPLOSION_SECONDS))
        self._forget_dynamic_entity_refs(entity)
        destroy(entity)

    def remove_aircraft(
        self,
        aircraft_id: Optional[str] = None,
        *,
        crash: bool = False,
    ) -> None:
        if aircraft_id is None:
            entity = self.aircraft_entity
            aircraft_id = getattr(entity, "aircraft_id", None) if entity is not None else None
        else:
            entity = self.aircraft_entities.get(aircraft_id)
        if entity is None:
            return
        if crash:
            explosion = Entity(
                model="sphere",
                position=entity.position,
                scale=1.0,
                color=_rgb((1.0, 0.38, 0.08)),
            )
            self._effects.append((explosion, 0.6))
        self._forget_dynamic_entity_refs(entity)
        destroy(entity)
        if aircraft_id is not None:
            self.aircraft_entities.pop(aircraft_id, None)
        if self.aircraft_entity is entity:
            self.aircraft_entity = next(iter(self.aircraft_entities.values()), None)

    def create_crew(self, encounter: GroundEncounter) -> None:
        self.create_crew_members(encounter.crew)

    def create_crew_members(self, members: Iterable[CrewMember]) -> None:
        """Create only missing crew colliders for an immediate drop batch."""

        if self.world is None:
            return
        for member in members:
            if member.id in self.crew_entities:
                entity = self.crew_entities[member.id]
                entity.enabled = member.alive
                if member.alive:
                    entity.position = Vec3(*member.position) + Vec3(0, 0.9, 0)
                continue
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
            self._forget_dynamic_entity_refs(entity)
            destroy(entity)

    def create_ground_tracer(
        self,
        tracer: GroundTracerEffect | str,
        start_position: Optional[tuple[float, float, float]] = None,
        target_position: Optional[tuple[float, float, float]] = None,
    ) -> Entity:
        """Create a yellow elongated visual for one ground attack event."""

        if isinstance(tracer, GroundTracerEffect):
            effect = tracer
        else:
            if start_position is None or target_position is None:
                raise ValueError("start_position and target_position are required")
            effect = GroundTracerEffect(
                id=str(tracer),
                start_position=start_position,
                target_position=target_position,
            )
        old_entity = self.tracer_entities.pop(effect.id, None)
        if old_entity is not None:
            self._forget_dynamic_entity_refs(old_entity)
            destroy(old_entity)
        entity = Entity(
            model="cube",
            color=_rgb(config.YELLOW_RGB),
        )
        entity.tracer_id = effect.id
        entity.tracer_visual_color = config.YELLOW_RGB
        self.tracer_effects[effect.id] = effect
        self.tracer_entities[effect.id] = entity
        self._dynamic_entities.append(entity)
        self._update_tracer_entity(effect, entity)
        return entity

    def update_ground_tracer(
        self,
        tracer: GroundTracerEffect,
        delta_seconds: float = 0.0,
    ) -> bool:
        """Advance and translate one tracer; return true when it is expired."""

        entity = self.tracer_entities.get(tracer.id)
        if entity is None:
            return True
        if delta_seconds > 0.0:
            tracer.advance(delta_seconds)
        if tracer.expired:
            self._remove_ground_tracer(tracer.id)
            return True
        self._update_tracer_entity(tracer, entity)
        return False

    def _update_tracer_entity(self, tracer: GroundTracerEffect, entity: Entity) -> None:
        head = Vec3(*tracer.head_position)
        tail = Vec3(*tracer.tail_position)
        segment = head - tail
        length = max(0.001, segment.length())
        entity.position = (head + tail) * 0.5
        entity.scale = (config.GROUND_TRACER_WIDTH, config.GROUND_TRACER_HEIGHT, length)
        if segment.length() > 1e-6:
            entity.look_in_direction(segment.normalized())

    def _remove_ground_tracer(self, tracer_id: str) -> None:
        entity = self.tracer_entities.pop(tracer_id, None)
        self.tracer_effects.pop(tracer_id, None)
        if entity is not None:
            self._forget_dynamic_entity_refs(entity)
            destroy(entity)

    def clear_ground_tracers(self) -> None:
        for tracer_id in tuple(self.tracer_entities):
            self._remove_ground_tracer(tracer_id)

    def create_auto_defense_turrets(
        self,
        turrets: Iterable[AutoDefenseTurret],
    ) -> dict[str, Entity]:
        """依固定座標建立目前小關的砲塔，最多六台。"""

        if self.world is None:
            return {}
        self.clear_auto_defense_turrets()
        fixed_positions = tuple(self.world.turret_positions) or tuple(
            config.AUTO_DEFENSE_TURRET_POSITIONS
        )
        for index, turret in enumerate(tuple(turrets)[: config.MAX_AUTO_DEFENSE_TURRETS]):
            if index >= len(fixed_positions):
                break
            position = fixed_positions[index]
            turret.position = tuple(position)
            entity = Entity(
                model="cube",
                position=Vec3(*position) + Vec3(0, 0.65, 0),
                scale=(1.1, 1.3, 1.1),
                color=_rgb((0.28, 0.42, 0.48)),
                collider="box",
            )
            entity.turret_id = turret.id
            entity.turret_position_id = index
            self.turret_entities[turret.id] = entity
            self._dynamic_entities.append(entity)
        return dict(self.turret_entities)

    # Compatibility aliases used by controller and headless scene fixtures.
    create_turrets = create_auto_defense_turrets

    def update_auto_defense_turrets(
        self,
        turrets: Iterable[AutoDefenseTurret],
    ) -> None:
        for turret in turrets:
            entity = self.turret_entities.get(turret.id)
            if entity is None:
                continue
            entity.enabled = bool(turret.enabled)
            entity.turret_target_id = turret.target_id

    update_turrets = update_auto_defense_turrets

    def clear_auto_defense_turrets(self) -> None:
        for turret_id, entity in tuple(self.turret_entities.items()):
            self._forget_dynamic_entity_refs(entity)
            destroy(entity)
            self.turret_entities.pop(turret_id, None)

    clear_turrets = clear_auto_defense_turrets

    def create_rpg_explosion(
        self,
        center: tuple[float, float, float],
        radius: float = config.RPG_EXPLOSION_RADIUS,
    ) -> Optional[Entity]:
        """建立短暫 RPG 爆炸效果；命中結算仍由純規則層負責。"""

        try:
            explosion = Entity(
                model="sphere",
                position=Vec3(*center),
                scale=max(0.1, float(radius) * 0.35),
                color=_rgb(config.ORANGE_RGB),
            )
        except Exception:
            return None
        self._effects.append((explosion, config.GUIDED_MISSILE_EXPLOSION_SECONDS))
        return explosion

    def update_multi_target_locks(
        self,
        target_positions: dict[str, tuple[float, float, float]],
    ) -> dict[str, Entity]:
        """顯示多目標鎖定投影的輕量標記。"""

        for target_id, entity in tuple(self.multi_lock_entities.items()):
            if target_id not in target_positions:
                self._forget_dynamic_entity_refs(entity)
                destroy(entity)
                self.multi_lock_entities.pop(target_id, None)
        for target_id, position in target_positions.items():
            entity = self.multi_lock_entities.get(str(target_id))
            if entity is None:
                entity = Entity(
                    model="sphere",
                    position=Vec3(*position),
                    scale=0.18,
                    color=_rgb(config.GREEN_RGB),
                )
                entity.lock_target_id = str(target_id)
                self.multi_lock_entities[str(target_id)] = entity
                self._dynamic_entities.append(entity)
            else:
                entity.position = Vec3(*position)
        return dict(self.multi_lock_entities)

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
        for tracer_id, tracer in tuple(self.tracer_effects.items()):
            self.update_ground_tracer(tracer, delta_seconds)


def distance_xz(first: Vec3, second: tuple[float, float, float] | Vec3) -> float:
    second_vec = second if isinstance(second, Vec3) else Vec3(*second)
    delta = first - second_vec
    return (delta.x * delta.x + delta.z * delta.z) ** 0.5
