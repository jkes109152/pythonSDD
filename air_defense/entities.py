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
class RPGWeapon(WeaponPickup):
    """本局 RPG；彈藥與冷卻在每個小關重新建立。"""

    kind: WeaponKind = field(default=WeaponKind.RPG, init=False)
    ammo_remaining: int = 3
    fire_cooldown: float = 0.0
    explosion_radius: float = 6.0
    damage: int = 35
    last_explosion_id: Optional[str] = None
    explosion_hit_ids: set[str] = field(default_factory=set, repr=False)

    def update_cooldown(self, delta_seconds: float) -> None:
        self.fire_cooldown = max(0.0, self.fire_cooldown - max(0.0, float(delta_seconds)))

    def can_fire(self) -> bool:
        return self.ammo_remaining > 0 and self.fire_cooldown <= 0.0

    def mark_fired(self, explosion_id: Optional[str] = None) -> bool:
        if not self.can_fire():
            return False
        self.ammo_remaining -= 1
        self.fire_cooldown = config.RPG_FIRE_COOLDOWN_SECONDS
        self.last_explosion_id = (
            str(explosion_id) if explosion_id is not None else None
        )
        self.explosion_hit_ids.clear()
        return True


RPG = RPGWeapon
RPGLauncher = RPGWeapon


@dataclass
class MultiAntiAircraftGun(AntiAircraftGun):
    """多目標防空炮的場景資料；鎖定進度由規則層追蹤器管理。"""

    kind: WeaponKind = field(default=WeaponKind.MULTI_ANTI_AIRCRAFT, init=False)
    target_aircraft_ids: list[str] = field(default_factory=list)
    target_capacity: int = 2
    volley_id: Optional[str] = None

    def set_targets(self, target_ids: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        """Store the current target IDs without consulting legacy capacity."""

        self.target_aircraft_ids = []
        for target_id in target_ids:
            value = str(target_id)
            if value not in self.target_aircraft_ids:
                self.target_aircraft_ids.append(value)
        return tuple(self.target_aircraft_ids)

    def mark_fired(self, volley_id: Optional[str] = None) -> None:
        self.fire_cooldown = config.AA_FIRE_COOLDOWN_SECONDS
        self.volley_id = str(volley_id) if volley_id is not None else None
        self.target_aircraft_ids.clear()
        self.lock_state = LockState.WHITE
        self.lock_elapsed = 0.0


# Public name used by the progression specification and by scene adapters.
MultiTargetAntiAircraftGun = MultiAntiAircraftGun


@dataclass
class AutoDefenseTurret:
    """固定位置、無限彈藥的陸地自動防禦系統。"""

    id: str
    position: tuple[float, float, float]
    enabled: bool = True
    target_id: Optional[str] = None
    # Retained as a compatibility field for older callers/save snapshots.  The
    # current land-defense rules deliberately do not use a finite ammo pool.
    ammo_remaining: Optional[int] = None
    cooldown_remaining: float = 0.0
    damage: int = config.AUTO_DEFENSE_DAMAGE
    cooldown_seconds: float = config.AUTO_DEFENSE_FIRE_COOLDOWN_SECONDS
    shot_sequence: int = 0

    def __post_init__(self) -> None:
        self.id = str(self.id)
        self.position = tuple(float(value) for value in self.position)
        # Do not let a legacy ammo value turn the current turret into a finite
        # resource.  Keeping the field as ``None`` makes the unlimited policy
        # explicit to adapters that still inspect it.
        self.ammo_remaining = None
        self.cooldown_remaining = max(0.0, float(self.cooldown_remaining))
        self.damage = max(0, int(self.damage))
        self.cooldown_seconds = max(0.0, float(self.cooldown_seconds))
        self.shot_sequence = max(0, int(self.shot_sequence))

    @property
    def can_fire(self) -> bool:
        return bool(
            self.enabled
            and self.target_id is not None
            and self.cooldown_remaining <= 0.0
        )

    def update(self, delta_seconds: float) -> None:
        self.cooldown_remaining = max(
            0.0, self.cooldown_remaining - max(0.0, float(delta_seconds))
        )

    def assign_target(self, target_id: Optional[str]) -> None:
        self.target_id = str(target_id) if target_id is not None else None

    def release_target(self) -> None:
        self.target_id = None

    def mark_fired(self) -> bool:
        if not self.can_fire:
            return False
        self.cooldown_remaining = self.cooldown_seconds
        self.shot_sequence += 1
        return True


LandAutoDefenseSystem = AutoDefenseTurret
AutoDefenseTurretState = AutoDefenseTurret


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
class RPGProjectileEffect:
    """Short-lived green cuboid feedback for one valid RPG shot.

    This object deliberately owns no collision or damage.  RPG damage is
    resolved once by ``apply_rpg_explosion``; the scene adapter only animates
    this effect from the player's view toward the already selected center.
    """

    id: str
    start_position: tuple[float, float, float]
    target_position: tuple[float, float, float]
    remaining_seconds: float = config.RPG_PROJECTILE_LIFETIME_SECONDS
    lifetime_seconds: float = config.RPG_PROJECTILE_LIFETIME_SECONDS
    travel_progress: float = 0.0
    length: float = config.RPG_PROJECTILE_LENGTH
    width: float = config.RPG_PROJECTILE_WIDTH
    height: float = config.RPG_PROJECTILE_HEIGHT
    visual_color: tuple[float, float, float] = config.GREEN_RGB
    expired: bool = False

    def __post_init__(self) -> None:
        self.id = str(self.id)
        self.start_position = tuple(float(value) for value in self.start_position)
        self.target_position = tuple(float(value) for value in self.target_position)
        self.lifetime_seconds = max(1e-6, float(self.lifetime_seconds))
        self.remaining_seconds = max(
            0.0,
            min(self.lifetime_seconds, float(self.remaining_seconds)),
        )
        self.travel_progress = max(0.0, min(1.0, float(self.travel_progress)))
        self.length = max(0.001, float(self.length))
        self.width = max(0.001, float(self.width))
        self.height = max(0.001, float(self.height))
        self.visual_color = tuple(float(value) for value in self.visual_color)  # type: ignore[assignment]
        self.expired = bool(self.expired or self.remaining_seconds <= 0.0)

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
        return tuple(head[index] - direction[index] * self.length for index in range(3))

    def advance(self, delta_seconds: float) -> bool:
        """Advance the visual projectile and report whether it expired."""

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
class BatchProgress:
    """Mutable source-scoped counters owned by one ground encounter."""

    source_aircraft_id: str
    spawned_count: int = 0
    alive_count: int = 0
    cleared_count: int = 0

    def __post_init__(self) -> None:
        self.source_aircraft_id = str(self.source_aircraft_id)
        self.spawned_count = max(0, int(self.spawned_count))
        self.alive_count = max(0, int(self.alive_count))
        self.cleared_count = max(0, int(self.cleared_count))
        if self.spawned_count != self.alive_count + self.cleared_count:
            raise ValueError("spawned_count must equal alive_count + cleared_count")


class BatchProgressLedger(dict[str, BatchProgress]):
    """Dictionary view that also supports the documented lookup call syntax."""

    def __call__(self, source_aircraft_id: str) -> Optional[BatchProgress]:
        return self.get(str(source_aircraft_id))


@dataclass
class CrewMember:
    id: str
    encounter_id: str
    cover_node: Optional[str]
    squad_role: SquadRole
    source_aircraft_id: str = ""
    behavior_state: CrewBehaviorState = CrewBehaviorState.IN_COVER
    alive: bool = True
    attack_cooldown: float = config.CREW_ATTACK_COOLDOWN_SECONDS
    advance_elapsed: float = 0.0
    position: tuple[float, float, float] = config.CRASH_SITE_POSITION
    target_cover_node: Optional[str] = None
    route_index: int = 0
    move_speed: float = config.GROUND_MOVE_SPEED
    # Keep the low-level constructor's legacy one-hit default.  New gameplay
    # encounters explicitly use GROUND_MINION_HEALTH through EncounterFactory.
    health: int = 1
    max_health: int = 1
    is_boss: bool = False
    at_city: bool = False
    city_attack_elapsed: float = 0.0
    attack_sequence: int = 0
    descent_start_position: tuple[float, float, float] = config.CRASH_SITE_POSITION
    landing_position: tuple[float, float, float] = config.CRASH_SITE_POSITION
    descent_elapsed: float = 0.0
    descent_duration: float = config.CREW_DESCENT_DURATION_SECONDS
    descent_offset: tuple[float, float] = (0.0, 0.0)

    def __post_init__(self) -> None:
        self.id = str(self.id)
        self.encounter_id = str(self.encounter_id)
        self.source_aircraft_id = str(self.source_aircraft_id)
        self.position = tuple(float(value) for value in self.position)
        self.descent_start_position = tuple(
            float(value) for value in self.descent_start_position
        )
        self.landing_position = tuple(float(value) for value in self.landing_position)
        self.descent_duration = max(1e-6, float(self.descent_duration))
        self.descent_elapsed = max(0.0, float(self.descent_elapsed))
        self.descent_offset = (
            float(self.descent_offset[0]),
            float(self.descent_offset[1]),
        )
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

    def begin_descent(
        self,
        start_position: tuple[float, float, float],
        landing_position: tuple[float, float, float],
        duration: float = config.CREW_DESCENT_DURATION_SECONDS,
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> bool:
        """Start one guarded descent; dead members can never be revived."""

        if not self.alive:
            return False
        self.descent_start_position = tuple(float(value) for value in start_position)
        self.landing_position = tuple(float(value) for value in landing_position)
        self.position = self.descent_start_position
        self.descent_duration = max(1e-6, float(duration))
        self.descent_elapsed = 0.0
        self.descent_offset = (float(offset[0]), float(offset[1]))
        self.behavior_state = CrewBehaviorState.DESCENDING
        self.at_city = False
        self.attack_cooldown = config.CREW_ATTACK_COOLDOWN_SECONDS
        return True

    def advance_descent(self, delta_seconds: float) -> bool:
        """Linearly advance and report only the first transition to landed."""

        if not self.alive or self.behavior_state != CrewBehaviorState.DESCENDING:
            return False
        self.descent_elapsed = min(
            self.descent_duration,
            self.descent_elapsed + max(0.0, float(delta_seconds)),
        )
        progress = min(1.0, self.descent_elapsed / self.descent_duration)
        self.position = tuple(
            self.descent_start_position[index]
            + (self.landing_position[index] - self.descent_start_position[index]) * progress
            for index in range(3)
        )
        if progress < 1.0:
            return False
        self.position = self.landing_position
        self.behavior_state = CrewBehaviorState.IN_COVER
        return True

    def update_attack_cooldown(self, delta_seconds: float) -> None:
        self.attack_cooldown = max(0.0, self.attack_cooldown - max(0.0, delta_seconds))

    def ready_to_attack(self) -> bool:
        return (
            self.alive
            and self.behavior_state != CrewBehaviorState.DESCENDING
            and self.attack_cooldown <= 0.0
        )

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
    batch_progress: BatchProgressLedger = field(default_factory=BatchProgressLedger)
    _cleared_member_ids: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self.aircraft_id = str(self.aircraft_id)
        self.crew = list(self.crew)
        member_ids = [str(member.id) for member in self.crew]
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("crew IDs must be unique within an encounter")
        self.crew_count = len(self.crew)
        self.aircraft_type = AircraftType(self.aircraft_type)
        if not self.source_aircraft_ids:
            inferred_sources = tuple(
                dict.fromkeys(
                    member.source_aircraft_id
                    for member in self.crew
                    if member.source_aircraft_id
                )
            )
            self.source_aircraft_ids = inferred_sources or (
                (self.aircraft_id,) if self.crew else ()
            )
        else:
            self.source_aircraft_ids = tuple(str(item) for item in self.source_aircraft_ids)
        if len(set(self.source_aircraft_ids)) != len(self.source_aircraft_ids):
            raise ValueError("source aircraft IDs must be unique")
        if self.group_id is not None:
            self.group_id = str(self.group_id)
        if self.boss_id is None:
            boss = next((member for member in self.crew if member.is_boss), None)
            self.boss_id = boss.id if boss is not None else None
        if self.boss_id is not None:
            self.boss_id = str(self.boss_id)

        supplied_progress = BatchProgressLedger(self.batch_progress)
        self.batch_progress = BatchProgressLedger()
        for key, progress in supplied_progress.items():
            source_id = str(key)
            if source_id != progress.source_aircraft_id:
                raise ValueError("batch progress key must match source aircraft ID")
            if source_id not in self.source_aircraft_ids:
                raise ValueError("batch progress source must be registered")
            self.batch_progress[source_id] = progress

        observed_progress: BatchProgressLedger = BatchProgressLedger()
        if not self.crew and self.source_aircraft_ids:
            for source_id in self.source_aircraft_ids:
                observed_progress[source_id] = BatchProgress(source_id)
        for member in self.crew:
            if not member.source_aircraft_id:
                if len(self.source_aircraft_ids) == 1:
                    member.source_aircraft_id = self.source_aircraft_ids[0]
                else:
                    raise ValueError("crew member source aircraft ID is required")
            if member.source_aircraft_id not in self.source_aircraft_ids:
                raise ValueError("crew member source aircraft ID must be registered")
            if member.encounter_id != self.id:
                raise ValueError("crew member encounter ID must match aggregate")
            progress = observed_progress.setdefault(
                member.source_aircraft_id,
                BatchProgress(member.source_aircraft_id),
            )
            progress.spawned_count += 1
            if member.alive:
                progress.alive_count += 1
            else:
                progress.cleared_count += 1
                self._cleared_member_ids.add(member.id)

        for source_id, observed in observed_progress.items():
            supplied = self.batch_progress.get(source_id)
            if supplied is None:
                self.batch_progress[source_id] = observed
                continue
            if (
                supplied.spawned_count,
                supplied.alive_count,
                supplied.cleared_count,
            ) != (
                observed.spawned_count,
                observed.alive_count,
                observed.cleared_count,
            ):
                raise ValueError("batch progress counters do not match crew")
        for progress in self.batch_progress.values():
            if progress.spawned_count != progress.alive_count + progress.cleared_count:
                raise ValueError("invalid batch progress counters")
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

    def add_reinforcement(
        self,
        members: list[CrewMember] | tuple[CrewMember, ...],
        source_aircraft_id: str,
    ) -> bool:
        """Append one non-empty source batch without disturbing existing members."""

        source_aircraft_id = str(source_aircraft_id)
        batch = tuple(members)
        if not batch or source_aircraft_id in self.source_aircraft_ids:
            return False
        existing_ids = {member.id for member in self.crew}
        batch_ids = [member.id for member in batch]
        if len(set(batch_ids)) != len(batch_ids) or existing_ids.intersection(batch_ids):
            return False
        if any(
            member.encounter_id != self.id
            or member.source_aircraft_id != source_aircraft_id
            for member in batch
        ):
            return False
        self.crew.extend(batch)
        self.crew_count = len(self.crew)
        self.source_aircraft_ids = self.source_aircraft_ids + (source_aircraft_id,)
        progress = BatchProgress(
            source_aircraft_id=source_aircraft_id,
            spawned_count=len(batch),
            alive_count=sum(1 for member in batch if member.alive),
            cleared_count=sum(1 for member in batch if not member.alive),
        )
        self.batch_progress[source_aircraft_id] = progress
        self._cleared_member_ids.update(member.id for member in batch if not member.alive)
        if self.boss_id is None:
            boss = next((member for member in batch if member.is_boss), None)
            if boss is not None:
                self.boss_id = boss.id
        self.refresh_cleared()
        return True

    def record_crew_cleared(self, member_id: str) -> bool:
        """Count one already-dead crew member once in its source batch."""

        member = self.find(member_id)
        if member is None or member.alive or member.id in self._cleared_member_ids:
            return False
        progress = self.batch_progress.get(member.source_aircraft_id)
        if progress is None:
            return False
        self._cleared_member_ids.add(member.id)
        progress.alive_count = max(0, progress.alive_count - 1)
        progress.cleared_count += 1
        self.refresh_cleared()
        return True
