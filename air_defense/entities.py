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
    AircraftType,
    CrewBehaviorState,
    LockState,
    SquadRole,
    WeaponKind,
)
from .rules import (
    desired_aircraft_heading,
    direction_to_yaw_pitch,
    normalize_vector,
    rotate_direction_towards,
    steer_forward,
    swept_segment_hits_sphere,
    vector_length,
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
    target_in_zone: bool = False
    fire_cooldown: float = 0.0

    def update_cooldown(self, delta_seconds: float) -> None:
        self.fire_cooldown = max(0.0, self.fire_cooldown - max(0.0, delta_seconds))

    def mark_fired(self) -> None:
        self.fire_cooldown = config.AA_FIRE_COOLDOWN_SECONDS
        self.lock_state = LockState.WHITE
        self.lock_elapsed = 0.0
        self.target_aircraft_id = None
        self.target_in_zone = False


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
    position: Optional[tuple[float, float, float]] = None
    forward: tuple[float, float, float] = (0.0, 0.0, 0.0)
    yaw: float = 0.0
    pitch: float = 0.0
    speed: float = 0.0
    max_yaw_rate: float = 0.0
    max_pitch_rate: float = 0.0
    flight_elapsed: float = 0.0
    evasion_phase: float = 0.0

    def __post_init__(self) -> None:
        self.aircraft_type = AircraftType(self.aircraft_type)
        from .rules import aircraft_profile

        profile = aircraft_profile(self.aircraft_type)
        if self.flight_duration == config.AIRCRAFT_FLIGHT_DURATION_SECONDS:
            self.flight_duration = profile.flight_duration
        if self.evasion_amplitude <= 0.0:
            self.evasion_amplitude = profile.evasion_amplitude
        if self.evasion_frequency <= 0.0:
            self.evasion_frequency = profile.evasion_frequency
        if self.max_health <= 0:
            self.max_health = profile.max_health
        if self.health <= 0:
            self.health = self.max_health
        if self.position is None:
            self.position = tuple(self.start_position)
        else:
            self.position = tuple(float(component) for component in self.position)
        if self.flight_elapsed <= 0.0 and self.path_progress > 0.0:
            self.flight_elapsed = self.path_progress * max(0.0, self.flight_duration)
        if self.forward == (0.0, 0.0, 0.0):
            self.forward = normalize_vector(
                tuple(target - start for start, target in zip(self.position, self.target_position))
            )
        else:
            self.forward = normalize_vector(self.forward)
        self.yaw, self.pitch = direction_to_yaw_pitch(self.forward)
        if self.speed <= 0.0:
            distance = vector_length(
                tuple(target - start for start, target in zip(self.start_position, self.target_position))
            )
            self.speed = distance / max(1e-6, self.flight_duration)
        if self.max_yaw_rate <= 0.0:
            self.max_yaw_rate = profile.max_yaw_rate
        if self.max_pitch_rate <= 0.0:
            self.max_pitch_rate = profile.max_pitch_rate

    def advance(self, delta_seconds: float) -> None:
        if self.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
            return
        delta_seconds = max(0.0, float(delta_seconds))
        if self.flight_duration <= 0:
            self.path_progress = 1.0
            self.position = tuple(self.target_position)
            return
        if delta_seconds <= 0.0:
            return

        self.flight_elapsed += delta_seconds
        self.evasion_elapsed = self.flight_elapsed
        self.evasion_phase = self.flight_elapsed
        desired_forward = desired_aircraft_heading(
            self.position,
            self.target_position,
            evasion_phase=self.evasion_phase,
            evasion_amplitude=self.evasion_amplitude,
            evasion_frequency=self.evasion_frequency,
        )
        self.forward = steer_forward(
            self.forward,
            desired_forward,
            max_yaw_degrees=self.max_yaw_rate * delta_seconds,
            max_pitch_degrees=self.max_pitch_rate * delta_seconds,
        )
        self.yaw, self.pitch = direction_to_yaw_pitch(self.forward)
        distance = self.speed * delta_seconds
        self.position = tuple(
            self.position[index] + self.forward[index] * distance
            for index in range(3)
        )
        self.path_progress = min(1.0, self.flight_elapsed / self.flight_duration)

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


@dataclass(frozen=True)
class MissileStep:
    """Result of one guided missile simulation step."""

    position: tuple[float, float, float]
    hit: bool = False
    expired: bool = False
    previous_position: Optional[tuple[float, float, float]] = None


@dataclass
class GuidedMissile:
    """Engine-independent target-bound missile with swept collision."""

    id: str
    target_aircraft_id: str
    position: tuple[float, float, float]
    forward: tuple[float, float, float] = (0.0, 0.0, 1.0)
    speed: float = config.GUIDED_MISSILE_SPEED
    turn_rate: float = config.GUIDED_MISSILE_TURN_RATE_DEGREES
    hit_radius: float = config.GUIDED_MISSILE_HIT_RADIUS
    lifetime_remaining: float = config.GUIDED_MISSILE_LIFETIME_SECONDS
    consumed: bool = False
    damage_applied: bool = False

    def __post_init__(self) -> None:
        self.position = tuple(float(component) for component in self.position)
        normalized = normalize_vector(self.forward)
        self.forward = normalized if normalized != (0.0, 0.0, 0.0) else (0.0, 0.0, 1.0)
        self.speed = max(0.0, float(self.speed))
        self.turn_rate = max(0.0, float(self.turn_rate))
        self.hit_radius = max(0.0, float(self.hit_radius))
        self.lifetime_remaining = max(0.0, float(self.lifetime_remaining))

    def advance(
        self,
        delta_seconds: float,
        target_position: tuple[float, float, float],
    ) -> MissileStep:
        previous_position = self.position
        target_position = tuple(float(component) for component in target_position)
        if self.consumed:
            return MissileStep(
                self.position,
                hit=False,
                expired=True,
                previous_position=previous_position,
            )

        # A target already touching the missile wins over lifetime expiry.
        if vector_length(
            tuple(target - current for target, current in zip(target_position, self.position))
        ) <= self.hit_radius + 1e-9:
            self.consumed = True
            return MissileStep(
                self.position,
                hit=True,
                expired=False,
                previous_position=previous_position,
            )

        delta_seconds = max(0.0, float(delta_seconds))
        desired_forward = normalize_vector(
            tuple(target - current for target, current in zip(target_position, self.position))
        )
        self.forward = rotate_direction_towards(
            self.forward,
            desired_forward,
            self.turn_rate * delta_seconds,
        )
        proposed_position = tuple(
            self.position[index] + self.forward[index] * self.speed * delta_seconds
            for index in range(3)
        )
        hit = swept_segment_hits_sphere(
            previous_position,
            proposed_position,
            target_position,
            self.hit_radius,
        )
        self.position = proposed_position
        self.lifetime_remaining = max(0.0, self.lifetime_remaining - delta_seconds)
        expired = not hit and self.lifetime_remaining <= 0.0
        if hit or expired:
            self.consumed = True
        return MissileStep(
            self.position,
            hit=hit,
            expired=expired,
            previous_position=previous_position,
        )


@dataclass
class GroundTracerEffect:
    """Short-lived ground-fire visual; it never owns gameplay damage."""

    id: str
    start_position: tuple[float, float, float]
    target_position: tuple[float, float, float]
    remaining_seconds: float = config.GROUND_TRACER_LIFETIME_SECONDS
    lifetime_seconds: float = config.GROUND_TRACER_LIFETIME_SECONDS
    travel_progress: float = 0.0
    tail_length: float = config.GROUND_TRACER_TAIL_LENGTH
    visual_color: tuple[float, float, float] = config.YELLOW_RGB
    expired: bool = False

    def __post_init__(self) -> None:
        self.start_position = tuple(float(value) for value in self.start_position)
        self.target_position = tuple(float(value) for value in self.target_position)
        self.lifetime_seconds = max(1e-6, float(self.lifetime_seconds))
        self.remaining_seconds = max(
            0.0,
            min(self.lifetime_seconds, float(self.remaining_seconds)),
        )
        self.travel_progress = max(0.0, min(1.0, float(self.travel_progress)))
        self.tail_length = max(0.0, float(self.tail_length))
        self.visual_color = tuple(float(value) for value in self.visual_color)  # type: ignore[assignment]
        self.expired = self.remaining_seconds <= 0.0

    @property
    def head_position(self) -> tuple[float, float, float]:
        return tuple(
            self.start_position[index]
            + (self.target_position[index] - self.start_position[index]) * self.travel_progress
            for index in range(3)
        )

    @property
    def tail_position(self) -> tuple[float, float, float]:
        head = self.head_position
        direction = normalize_vector(
            tuple(
                self.target_position[index] - self.start_position[index]
                for index in range(3)
            )
        )
        return tuple(
            head[index] - direction[index] * self.tail_length
            for index in range(3)
        )

    def advance(self, delta_seconds: float) -> bool:
        """Advance the visual head linearly and return whether it expired."""

        if self.expired:
            return True
        delta_seconds = max(0.0, float(delta_seconds))
        elapsed = self.lifetime_seconds - self.remaining_seconds
        elapsed = min(self.lifetime_seconds, elapsed + delta_seconds)
        self.remaining_seconds = max(0.0, self.lifetime_seconds - elapsed)
        self.travel_progress = min(1.0, elapsed / self.lifetime_seconds)
        self.expired = self.travel_progress >= 1.0 or self.remaining_seconds <= 0.0
        return self.expired


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
    attack_sequence: int = 0

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
        self.attack_sequence += 1

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
    source_aircraft_ids: tuple[str, ...] = ()
    group_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.crew_count = len(self.crew) if self.crew_count == 0 else self.crew_count
        self.aircraft_type = AircraftType(self.aircraft_type)
        if not self.source_aircraft_ids:
            self.source_aircraft_ids = (self.aircraft_id,)
        else:
            self.source_aircraft_ids = tuple(str(item) for item in self.source_aircraft_ids)
        if self.group_id is not None:
            self.group_id = str(self.group_id)
        if self.boss_id is None:
            boss = next((member for member in self.crew if member.is_boss), None)
            self.boss_id = boss.id if boss is not None else None
        self.refresh_cleared()

    @property
    def id(self) -> str:
        return f"encounter:{self.group_id or self.aircraft_id}"

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
