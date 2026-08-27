"""Domain entities for the air-defense game.

These classes hold gameplay state and small object-local behaviors without
importing Ursina. The graphical scene translates them into visual entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import config
from .state import (
    AircraftPhase,
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
class TargetBuilding:
    id: str = "target-building"
    position: tuple[float, float, float] = config.BUILDING_POSITION
    collision_radius: float = 5.0
    is_protected: bool = True


@dataclass
class Aircraft:
    id: str
    target_building_id: str = "target-building"
    start_position: tuple[float, float, float] = config.AIRCRAFT_START_POSITION
    target_position: tuple[float, float, float] = config.AIRCRAFT_TARGET_POSITION
    flight_duration: float = config.AIRCRAFT_FLIGHT_DURATION_SECONDS
    path_progress: float = 0.0
    phase: AircraftPhase = AircraftPhase.APPROACHING
    crew_spawned: bool = False

    @property
    def position(self) -> tuple[float, float, float]:
        progress = max(0.0, min(1.0, self.path_progress))
        return tuple(
            start + (target - start) * progress
            for start, target in zip(self.start_position, self.target_position)
        )

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

    def estimated_impact_seconds(self) -> float:
        return max(0.0, (1.0 - self.path_progress) * self.flight_duration)

    def mark_locked(self) -> None:
        if self.phase == AircraftPhase.APPROACHING:
            self.phase = AircraftPhase.LOCKED

    def destroy(self) -> bool:
        if self.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
            return False
        self.phase = AircraftPhase.DESTROYED
        self.crew_spawned = True
        return True

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

    def take_hit(self) -> bool:
        if not self.alive:
            return False
        self.alive = False
        self.behavior_state = CrewBehaviorState.IN_COVER
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

    def __post_init__(self) -> None:
        self.crew_count = len(self.crew) if self.crew_count == 0 else self.crew_count
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
