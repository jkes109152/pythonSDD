"""Domain entities for the air-defense game.

These classes hold gameplay state and small object-local behaviors without
importing Ursina. The graphical scene translates them into visual entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import pi, sin
from typing import Optional

from . import config
from .state import (
    AircraftPhase,
    AircraftType,
    CrewBehaviorState,
    LockState,
    SquadRole,
    WeaponKind,
)


@dataclass
class Player:
    position: tuple[float, float, float] = config.DEFENSE_POINT_POSITION
    max_health: int = config.PLAYER_MAX_HEALTH
    health: int = config.PLAYER_MAX_HEALTH
    held_weapon: Optional[WeaponKind] = None
    aim_mode: str = "NONE"

    def take_damage(self, amount: int) -> bool:
        self.health = max(0, self.health - max(0, amount))
        return self.health == 0

    def pick_up(self, pickup: "WeaponPickup") -> bool:
        if self.held_weapon is not None or not pickup.available:
            return False
        self.held_weapon = pickup.kind
        pickup.available = False
        pickup.holder = "player"
        self.aim_mode = pickup.kind.value
        return True

    def drop_weapon(self, position: tuple[float, float, float]) -> Optional["WeaponPickup"]:
        if self.held_weapon is None:
            return None
        pickup = WeaponPickup(kind=self.held_weapon, world_position=position)
        self.held_weapon = None
        self.aim_mode = "NONE"
        return pickup


@dataclass
class WeaponPickup:
    kind: WeaponKind
    world_position: tuple[float, float, float]
    holder: Optional[str] = None
    available: bool = True

    def drop(self, position: tuple[float, float, float]) -> None:
        self.world_position = position
        self.holder = None
        self.available = True


@dataclass
class AntiAircraftGun(WeaponPickup):
    kind: WeaponKind = field(default=WeaponKind.ANTI_AIRCRAFT, init=False)
    lock_state: LockState = LockState.WHITE
    lock_elapsed: float = 0.0
    target_aircraft_id: Optional[str] = None
    fire_cooldown: float = 0.0

    def update_cooldown(self, delta_seconds: float) -> None:
        self.fire_cooldown = max(0.0, self.fire_cooldown - max(0.0, delta_seconds))

    def mark_fired(self) -> None:
        self.fire_cooldown = config.AA_FIRE_COOLDOWN_SECONDS
        self.lock_state = LockState.WHITE
        self.lock_elapsed = 0.0
        self.target_aircraft_id = None


@dataclass
class SniperRifle(WeaponPickup):
    kind: WeaponKind = field(default=WeaponKind.SNIPER, init=False)
    scope_enabled: bool = False
    fire_cooldown: float = 0.0
    last_hit: Optional[str] = None

    def toggle_scope(self) -> bool:
        self.scope_enabled = not self.scope_enabled
        return self.scope_enabled

    def update_cooldown(self, delta_seconds: float) -> None:
        self.fire_cooldown = max(0.0, self.fire_cooldown - max(0.0, delta_seconds))

    def mark_fired(self, crew_id: Optional[str]) -> None:
        self.fire_cooldown = config.SNIPER_FIRE_COOLDOWN_SECONDS
        self.last_hit = crew_id


@dataclass
class Pistol(WeaponPickup):
    kind: WeaponKind = field(default=WeaponKind.PISTOL, init=False)
    fire_cooldown: float = 0.0
    last_hit: Optional[str] = None

    def update_cooldown(self, delta_seconds: float) -> None:
        self.fire_cooldown = max(0.0, self.fire_cooldown - max(0.0, delta_seconds))

    def mark_fired(self, crew_id: Optional[str]) -> None:
        self.fire_cooldown = config.PISTOL_FIRE_COOLDOWN_SECONDS
        self.last_hit = crew_id


@dataclass
class TargetBuilding:
    id: str = "target-building"
    position: tuple[float, float, float] = config.BUILDING_POSITION
    collision_radius: float = 5.0
    is_protected: bool = True
    max_health: float = config.CITY_MAX_HEALTH
    health: float = config.CITY_MAX_HEALTH
    attack_zone_radius: float = config.CITY_ATTACK_RADIUS

    def take_damage(self, amount: float) -> bool:
        """Reduce city health and report only the first transition to zero."""

        if self.health <= 0.0 or amount <= 0.0:
            return False
        self.health = max(0.0, self.health - amount)
        return self.health == 0.0


@dataclass
class Aircraft:
    id: str
    target_building_id: str = "target-building"
    aircraft_type: AircraftType = AircraftType.NORMAL
    start_position: tuple[float, float, float] = config.AIRCRAFT_START_POSITION
    target_position: tuple[float, float, float] = config.AIRCRAFT_TARGET_POSITION
    flight_duration: float = config.AIRCRAFT_FLIGHT_DURATION_SECONDS
    path_progress: float = 0.0
    evasion_elapsed: float = 0.0
    evasion_amplitude: float = 0.0
    evasion_frequency: float = 0.0
    health: int = 0
    max_health: int = 0
    phase: AircraftPhase = AircraftPhase.APPROACHING
    crew_spawned: bool = False

    def __post_init__(self) -> None:
        self.aircraft_type = AircraftType(self.aircraft_type)
        profile = {
            AircraftType.NORMAL: (
                config.AIRCRAFT_NORMAL_FLIGHT_DURATION_SECONDS,
                config.AIRCRAFT_NORMAL_EVASION_AMPLITUDE,
                config.AIRCRAFT_NORMAL_EVASION_FREQUENCY,
                1,
            ),
            AircraftType.MANPOWER_SUPPORT: (
                config.AIRCRAFT_SUPPORT_FLIGHT_DURATION_SECONDS,
                config.AIRCRAFT_SUPPORT_EVASION_AMPLITUDE,
                config.AIRCRAFT_SUPPORT_EVASION_FREQUENCY,
                1,
            ),
            AircraftType.FAST: (
                config.AIRCRAFT_FAST_FLIGHT_DURATION_SECONDS,
                config.AIRCRAFT_FAST_EVASION_AMPLITUDE,
                config.AIRCRAFT_FAST_EVASION_FREQUENCY,
                1,
            ),
            AircraftType.ARMORED_BOSS: (
                config.AIRCRAFT_ARMORED_FLIGHT_DURATION_SECONDS,
                config.AIRCRAFT_ARMORED_EVASION_AMPLITUDE,
                config.AIRCRAFT_ARMORED_EVASION_FREQUENCY,
                config.ARMORED_AIRCRAFT_HEALTH,
            ),
        }[self.aircraft_type]
        if self.flight_duration == config.AIRCRAFT_FLIGHT_DURATION_SECONDS:
            self.flight_duration = profile[0]
        if self.evasion_amplitude <= 0.0:
            self.evasion_amplitude = profile[1]
        if self.evasion_frequency <= 0.0:
            self.evasion_frequency = profile[2]
        if self.max_health <= 0:
            self.max_health = profile[3]
        if self.health <= 0:
            self.health = self.max_health

    @property
    def position(self) -> tuple[float, float, float]:
        progress = max(0.0, min(1.0, self.path_progress))
        base_position = tuple(
            start + (target - start) * progress
            for start, target in zip(self.start_position, self.target_position)
        )
        lateral_offset = self.evasion_amplitude * sin(
            self.evasion_elapsed * self.evasion_frequency * 2.0 * pi
        )
        return (base_position[0] + lateral_offset, base_position[1], base_position[2])

    def advance(self, delta_seconds: float) -> None:
        if self.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
            return
        if self.flight_duration <= 0:
            self.path_progress = 1.0
        else:
            self.path_progress = min(
                1.0,
                self.path_progress + max(0.0, delta_seconds) / self.flight_duration,
            )
        self.evasion_elapsed += max(0.0, delta_seconds)

    def estimated_impact_seconds(self) -> float:
        return max(0.0, (1.0 - self.path_progress) * self.flight_duration)

    def mark_locked(self) -> None:
        if self.phase == AircraftPhase.APPROACHING:
            self.phase = AircraftPhase.LOCKED

    def take_damage(self, amount: int = 1) -> bool:
        """Apply one guarded anti-air hit and report destruction at zero HP."""

        if self.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED) or amount <= 0:
            return False
        self.health = max(0, self.health - amount)
        if self.health > 0:
            return False
        self.phase = AircraftPhase.DESTROYED
        self.crew_spawned = True
        return True

    def destroy(self) -> bool:
        if self.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
            return False
        # Keep the legacy method, but make it one valid anti-air hit so it
        # cannot bypass the armored Boss damage contract.
        return self.take_damage(1)

    def impact(self) -> bool:
        if self.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
            return False
        self.phase = AircraftPhase.IMPACTED
        return True


@dataclass
class CrewMember:
    id: str
    encounter_id: str
    cover_node: Optional[str]
    squad_role: SquadRole
    behavior_state: CrewBehaviorState = CrewBehaviorState.IN_COVER
    alive: bool = True
    attack_cooldown: float = config.CREW_ATTACK_COOLDOWN_SECONDS
    advance_elapsed: float = 0.0
    position: tuple[float, float, float] = config.CRASH_SITE_POSITION
    target_cover_node: Optional[str] = None
    route_index: int = 0
    move_speed: float = config.GROUND_MOVE_SPEED
    health: int = 1
    max_health: int = 1
    is_boss: bool = False
    at_city: bool = False
    city_attack_elapsed: float = 0.0

    def __post_init__(self) -> None:
        if self.is_boss:
            if self.max_health < config.GROUND_BOSS_HEALTH:
                self.max_health = config.GROUND_BOSS_HEALTH
            if self.alive and self.health <= 1:
                self.health = self.max_health
            if self.move_speed == config.GROUND_MOVE_SPEED:
                self.move_speed = config.GROUND_BOSS_MOVE_SPEED
        if self.target_cover_node is None:
            self.target_cover_node = self.cover_node
        self.max_health = max(1, self.max_health)
        self.health = max(0, min(self.max_health, self.health))
        if not self.alive:
            self.health = 0

    def take_hit(self) -> bool:
        return self.take_damage(1)

    def take_damage(self, amount: int = 1) -> bool:
        if not self.alive or amount <= 0:
            return False
        self.health = max(0, self.health - amount)
        if self.health > 0:
            return False
        self.alive = False
        self.behavior_state = CrewBehaviorState.IN_COVER
        self.at_city = False
        return True

    def update_attack_cooldown(self, delta_seconds: float) -> None:
        self.attack_cooldown = max(0.0, self.attack_cooldown - max(0.0, delta_seconds))

    def ready_to_attack(self) -> bool:
        return self.alive and self.attack_cooldown <= 0.0

    def mark_attacked(self) -> None:
        self.attack_cooldown = config.CREW_ATTACK_COOLDOWN_SECONDS

    def next_cover_node(self) -> str:
        current = self.cover_node or config.COVER_NODES[0]
        try:
            index = config.COVER_NODES.index(current)
        except ValueError:
            index = 0
        return config.COVER_NODES[(index + 1) % len(config.COVER_NODES)]


@dataclass
class GroundEncounter:
    aircraft_id: str
    crew: list[CrewMember]
    crew_count: int = 0
    cleared: bool = False
    aircraft_type: AircraftType = AircraftType.NORMAL
    boss_id: Optional[str] = None
    city_damage_accumulator: float = 0.0

    def __post_init__(self) -> None:
        self.crew_count = len(self.crew) if self.crew_count == 0 else self.crew_count
        self.aircraft_type = AircraftType(self.aircraft_type)
        if self.boss_id is None:
            boss = next((member for member in self.crew if member.is_boss), None)
            self.boss_id = boss.id if boss is not None else None
        self.refresh_cleared()

    @property
    def id(self) -> str:
        return f"encounter:{self.aircraft_id}"

    @property
    def alive_crew(self) -> list[CrewMember]:
        return [member for member in self.crew if member.alive]

    def find(self, crew_id: str) -> Optional[CrewMember]:
        return next((member for member in self.crew if member.id == crew_id), None)

    def refresh_cleared(self) -> bool:
        self.cleared = not self.alive_crew
        return self.cleared

    def add_reinforcement(self, *_: object) -> bool:
        return False
