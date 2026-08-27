"""Pure gameplay rules used by the graphical adapter and unit tests."""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import acos, asin, atan2, ceil, cos, degrees, hypot, pi, radians, sin, sqrt
from typing import TYPE_CHECKING, Optional, Protocol

from . import config
from .config import (
    AIRSTRIKE_WARNING_LEAD_SECONDS,
    CREW_ADVANCE_INTERVAL_SECONDS,
    ENCOUNTER_MAX_CREW,
    ENCOUNTER_MIN_CREW,
    AA_AIM_ASSIST_MAX_DEGREES_PER_SECOND,
    AA_AIM_ASSIST_ZONE_MULTIPLIER,
    AA_LOCK_DECAY_SECONDS,
    AA_LOCK_ZONE_DIAMETER_RATIO,
    LOCK_DURATION_SECONDS,
    LOCK_FLASH_HALF_PERIOD_SECONDS,
)
from .state import (
    CrewBehaviorState,
    AircraftPhase,
    AircraftType,
    GamePhase,
    GameSession,
    LockState,
    SessionEvent,
    SquadRole,
    WavePlan,
    WaveProgress,
    WeaponKind,
)

if TYPE_CHECKING:
    from .entities import GroundEncounter


class RandomSource(Protocol):
    def randint(self, minimum: int, maximum: int) -> int: ...


class LockOnTracker:
    """Accumulates an in-zone target while the anti-air scope is open."""

    def __init__(
        self,
        lock_duration: float = LOCK_DURATION_SECONDS,
        decay_duration: float = AA_LOCK_DECAY_SECONDS,
        *,
        scope_enabled: bool = False,
    ) -> None:
        self.lock_duration = max(1e-6, float(lock_duration))
        self.decay_duration = max(1e-6, float(decay_duration))
        self.lock_elapsed = 0.0
        self.state = LockState.WHITE
        self.target_in_zone = False
        self.scope_enabled = bool(scope_enabled)

    @property
    def progress(self) -> float:
        """Return the clamped UI progress value in the inclusive [0, 1] range."""

        return max(0.0, min(1.0, self.lock_elapsed / self.lock_duration))

    def set_scope_enabled(self, enabled: bool) -> None:
        """Open/close the anti-air scope and apply its immediate-close reset rule."""

        enabled = bool(enabled)
        if not enabled:
            self.scope_enabled = False
            self.reset()
            return
        if not self.scope_enabled:
            self.reset()
        self.scope_enabled = True

    def update(self, target_in_zone: bool, delta_seconds: float) -> LockState:
        if not self.scope_enabled:
            self.reset()
            return self.state

        delta_seconds = max(0.0, float(delta_seconds))
        self.target_in_zone = bool(target_in_zone)
        if self.target_in_zone:
            self.lock_elapsed = min(self.lock_duration, self.lock_elapsed + delta_seconds)
        else:
            decay_rate = self.lock_duration / self.decay_duration
            self.lock_elapsed = max(0.0, self.lock_elapsed - delta_seconds * decay_rate)

        if self.lock_elapsed <= 0.0:
            self.lock_elapsed = 0.0
            self.state = LockState.WHITE
        elif self.lock_elapsed >= self.lock_duration and self.target_in_zone:
            self.lock_elapsed = self.lock_duration
            self.state = LockState.GREEN_READY
        else:
            self.state = LockState.RED_TRACKING
        return self.state

    def reset(self) -> None:
        self.lock_elapsed = 0.0
        self.state = LockState.WHITE
        self.target_in_zone = False

    def flash_visible(self, half_period: float = LOCK_FLASH_HALF_PERIOD_SECONDS) -> bool:
        if self.state != LockState.RED_TRACKING or half_period <= 0:
            return self.state == LockState.RED_TRACKING
        return int(self.lock_elapsed / half_period) % 2 == 0


Vector3 = tuple[float, float, float]
Vector2 = tuple[float, float]


def vector_length(vector: Vector3) -> float:
    return sqrt(sum(float(component) ** 2 for component in vector))


def normalize_vector(vector: Vector3) -> Vector3:
    """Normalize a vector; an explicit zero vector remains zero."""

    length = vector_length(vector)
    if length <= 1e-9:
        return (0.0, 0.0, 0.0)
    return tuple(float(component) / length for component in vector)  # type: ignore[return-value]


def _dot(first: Vector3, second: Vector3) -> float:
    return sum(left * right for left, right in zip(first, second))


def _cross(first: Vector3, second: Vector3) -> Vector3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def wrap_angle_degrees(angle: float) -> float:
    """Wrap an angle to [-180, 180), including the 180-degree boundary."""

    wrapped = (float(angle) + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def clamp_angle_delta(target_angle: float, current_angle: float, maximum_delta: float) -> float:
    """Move an angle toward a target by no more than maximum_delta degrees."""

    maximum_delta = max(0.0, float(maximum_delta))
    difference = wrap_angle_degrees(target_angle - current_angle)
    return current_angle + _clamp(difference, -maximum_delta, maximum_delta)


def direction_to_yaw_pitch(direction: Vector3) -> tuple[float, float]:
    normalized = normalize_vector(direction)
    if normalized == (0.0, 0.0, 0.0):
        return 0.0, 0.0
    yaw = degrees(atan2(normalized[0], normalized[2]))
    pitch = degrees(asin(_clamp(normalized[1], -1.0, 1.0)))
    return yaw, pitch


def yaw_pitch_to_direction(yaw: float, pitch: float) -> Vector3:
    yaw_radians = radians(yaw)
    pitch_radians = radians(_clamp(pitch, -89.999, 89.999))
    return normalize_vector(
        (
            sin(yaw_radians) * cos(pitch_radians),
            sin(pitch_radians),
            cos(yaw_radians) * cos(pitch_radians),
        )
    )


def steer_forward(
    current_forward: Vector3,
    desired_forward: Vector3,
    *,
    max_yaw_degrees: float,
    max_pitch_degrees: float,
) -> Vector3:
    """Turn a heading with independent bounded yaw and pitch deltas."""

    current = normalize_vector(current_forward)
    desired = normalize_vector(desired_forward)
    if desired == (0.0, 0.0, 0.0):
        return current
    if current == (0.0, 0.0, 0.0):
        return desired
    current_yaw, current_pitch = direction_to_yaw_pitch(current)
    desired_yaw, desired_pitch = direction_to_yaw_pitch(desired)
    return yaw_pitch_to_direction(
        clamp_angle_delta(desired_yaw, current_yaw, max_yaw_degrees),
        clamp_angle_delta(desired_pitch, current_pitch, max_pitch_degrees),
    )


def rotate_direction_towards(
    current_direction: Vector3,
    target_direction: Vector3,
    maximum_angle_degrees: float,
) -> Vector3:
    """Rotate a direction by a bounded total angular amount."""

    current = normalize_vector(current_direction)
    target = normalize_vector(target_direction)
    if target == (0.0, 0.0, 0.0):
        return current
    if current == (0.0, 0.0, 0.0):
        return target
    maximum_angle = max(0.0, float(maximum_angle_degrees))
    cosine = _clamp(_dot(current, target), -1.0, 1.0)
    angle = acos(cosine)
    if angle <= radians(maximum_angle) + 1e-9:
        return target
    if angle <= 1e-9:
        return current
    axis = _cross(current, target)
    axis_length = vector_length(axis)
    if axis_length <= 1e-9:
        axis = _cross(current, (0.0, 1.0, 0.0))
        if vector_length(axis) <= 1e-9:
            axis = _cross(current, (1.0, 0.0, 0.0))
        axis = normalize_vector(axis)
        angle_to_apply = min(angle, radians(maximum_angle))
        # Rodrigues rotation around the perpendicular axis.
        cosine_step = cos(angle_to_apply)
        sine_step = sin(angle_to_apply)
        rotated = tuple(
            current[index] * cosine_step
            + _cross(axis, current)[index] * sine_step
            for index in range(3)
        )
        return normalize_vector(rotated)  # type: ignore[arg-type]

    axis = normalize_vector(axis)
    angle_to_apply = min(angle, radians(maximum_angle))
    cosine_step = cos(angle_to_apply)
    sine_step = sin(angle_to_apply)
    cross_term = _cross(axis, current)
    rotated = tuple(
        current[index] * cosine_step + cross_term[index] * sine_step
        for index in range(3)
    )
    return normalize_vector(rotated)  # type: ignore[arg-type]


def desired_aircraft_heading(
    position: Vector3,
    target_position: Vector3,
    *,
    evasion_phase: float,
    evasion_amplitude: float,
    evasion_frequency: float,
) -> Vector3:
    """Return a forward heading that bends toward a deterministic evasion wave."""

    base = normalize_vector(tuple(target - current for current, target in zip(position, target_position)))
    if base == (0.0, 0.0, 0.0):
        return base
    world_up = (0.0, 1.0, 0.0)
    lateral = normalize_vector(_cross(world_up, base))
    if lateral == (0.0, 0.0, 0.0):
        lateral = normalize_vector(_cross((1.0, 0.0, 0.0), base))
    vertical = normalize_vector(_cross(base, lateral))
    phase = evasion_phase * evasion_frequency * 2.0 * pi
    offset = tuple(
        lateral[index] * sin(phase) + vertical[index] * 0.35 * cos(phase)
        for index in range(3)
    )
    distance = max(1.0, vector_length(tuple(target - current for current, target in zip(position, target_position))))
    bend = max(0.0, float(evasion_amplitude)) / max(1.0, distance * 0.35)
    return normalize_vector(tuple(base[index] + offset[index] * bend for index in range(3)))


def lock_zone_radius(
    viewport_width: float,
    viewport_height: float,
    diameter_ratio: float = AA_LOCK_ZONE_DIAMETER_RATIO,
) -> float:
    """Return the hidden lock-circle radius in viewport pixels."""

    width = max(0.0, float(viewport_width))
    height = max(0.0, float(viewport_height))
    ratio = max(0.0, float(diameter_ratio))
    return min(width, height) * ratio * 0.5


def screen_distance_from_center(
    screen_position: Vector2,
    viewport_width: float,
    viewport_height: float,
) -> float:
    """Measure an absolute pixel position from the viewport center."""

    width = float(viewport_width)
    height = float(viewport_height)
    if width <= 0.0 or height <= 0.0:
        return float("inf")
    return hypot(float(screen_position[0]) - width * 0.5, float(screen_position[1]) - height * 0.5)


def is_inside_lock_zone(
    screen_position: Vector2,
    viewport_width: float,
    viewport_height: float,
    diameter_ratio: float = AA_LOCK_ZONE_DIAMETER_RATIO,
) -> bool:
    radius = lock_zone_radius(viewport_width, viewport_height, diameter_ratio)
    return screen_distance_from_center(screen_position, viewport_width, viewport_height) <= radius + 1e-6


def raycast_hit_matches_target(hit_result: object, target: object) -> bool:
    """Resolve an engine raycast wrapper and match its entity parent chain."""

    if hit_result is None or target is None or not bool(getattr(hit_result, "hit", False)):
        return False
    target_id = getattr(target, "aircraft_id", None)
    current = getattr(hit_result, "entity", None)
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if current is target:
            return True
        if target_id is not None and getattr(current, "aircraft_id", None) == target_id:
            return True
        current = getattr(current, "parent", None)
    return False


def clamp_screen_radius(radius: float, *, minimum: float = 0.008, maximum: float = 0.2) -> float:
    """Keep a projected target radius readable and finite for the HUD."""

    return _clamp(float(radius), max(0.0, minimum), max(max(0.0, minimum), maximum))


def tracking_ring_radius(
    acquisition_radius: float,
    target_radius: float,
    progress: float,
    *,
    padding: float = 0.0,
) -> float:
    """Interpolate the tracking ring from the acquisition circle to the target."""

    start = max(0.0, float(acquisition_radius))
    end = max(0.0, float(target_radius) + float(padding))
    amount = _clamp(float(progress), 0.0, 1.0)
    return start + (end - start) * amount


def apply_aim_assist(
    current_direction: Vector3,
    target_direction: Vector3,
    *,
    scope_enabled: bool,
    target_visible: bool,
    target_screen_distance: float,
    lock_zone_radius_pixels: float,
    delta_seconds: float,
    activation_multiplier: float = AA_AIM_ASSIST_ZONE_MULTIPLIER,
    maximum_degrees_per_second: float = AA_AIM_ASSIST_MAX_DEGREES_PER_SECOND,
) -> Vector3:
    """Apply small scope-only attraction after player mouse rotation."""

    current = normalize_vector(current_direction)
    if not scope_enabled or not target_visible:
        return current
    activation_radius = max(0.0, float(lock_zone_radius_pixels)) * max(0.0, float(activation_multiplier))
    if float(target_screen_distance) > activation_radius + 1e-6:
        return current
    maximum_degrees = max(0.0, float(maximum_degrees_per_second)) * max(0.0, float(delta_seconds))
    return rotate_direction_towards(current, target_direction, maximum_degrees)


def distance_point_to_segment(
    point: Vector3,
    segment_start: Vector3,
    segment_end: Vector3,
) -> float:
    """Return the shortest distance from a point to a finite 3D segment."""

    segment = tuple(end - start for start, end in zip(segment_start, segment_end))
    length_squared = _dot(segment, segment)
    if length_squared <= 1e-12:
        return vector_length(tuple(value - start for value, start in zip(point, segment_start)))
    offset = tuple(value - start for value, start in zip(point, segment_start))
    amount = _clamp(_dot(offset, segment) / length_squared, 0.0, 1.0)
    closest = tuple(segment_start[index] + segment[index] * amount for index in range(3))
    return vector_length(tuple(value - candidate for value, candidate in zip(point, closest)))


def swept_segment_hits_sphere(
    segment_start: Vector3,
    segment_end: Vector3,
    sphere_center: Vector3,
    sphere_radius: float,
) -> bool:
    """Test a swept missile segment against the target's current hit sphere."""

    radius = max(0.0, sphere_radius)
    start_inside = vector_length(
        tuple(start - center for start, center in zip(segment_start, sphere_center))
    ) <= radius + 1e-9
    return start_inside or distance_point_to_segment(
        sphere_center,
        segment_start,
        segment_end,
    ) <= radius + 1e-9


def warning_active(
    estimated_impact_seconds: Optional[float],
    lead_seconds: float = AIRSTRIKE_WARNING_LEAD_SECONDS,
) -> bool:
    """Return whether the aircraft warning must be shown."""

    return estimated_impact_seconds is not None and estimated_impact_seconds <= lead_seconds


def lock_status_label(state: LockState) -> str:
    """Return the text paired with each reticle color state."""

    return {
        LockState.WHITE: "未鎖定",
        LockState.RED_TRACKING: "鎖定中",
        LockState.GREEN_READY: "可發射",
    }[state]


def inventory_selection_allowed(
    phase: GamePhase,
    requested_weapon: WeaponKind,
) -> bool:
    """Return whether an inventory slot is usable in the current phase."""

    return (
        phase == GamePhase.AIRSTRIKE
        and requested_weapon == WeaponKind.ANTI_AIRCRAFT
    ) or (
        phase == GamePhase.GROUND_COMBAT
        and requested_weapon in (WeaponKind.SNIPER, WeaponKind.PISTOL)
    )


def cooldown_ready(cooldown_remaining: float) -> bool:
    return cooldown_remaining <= 0.0


def tick_cooldown(cooldown_remaining: float, delta_seconds: float) -> float:
    return max(0.0, cooldown_remaining - max(0.0, delta_seconds))


def can_fire_anti_air(
    lock_state: LockState,
    cooldown_remaining: float,
    held_weapon: Optional[WeaponKind] = WeaponKind.ANTI_AIRCRAFT,
    target_in_zone: bool = False,
) -> bool:
    return (
        held_weapon == WeaponKind.ANTI_AIRCRAFT
        and lock_state == LockState.GREEN_READY
        and cooldown_ready(cooldown_remaining)
        and bool(target_in_zone)
    )


def apply_guided_missile_damage(
    aircraft: object,
    missile: object,
    step: object,
    *,
    active_aircraft_id: Optional[str],
    damage: int = 1,
) -> bool:
    """Apply one collision-time hit after validating target identity and phase."""

    if not bool(getattr(step, "hit", False)):
        return False
    if bool(getattr(missile, "damage_applied", False)):
        return False
    aircraft_id = getattr(aircraft, "id", None)
    target_id = getattr(missile, "target_aircraft_id", None)
    if active_aircraft_id is None or aircraft_id != active_aircraft_id or target_id != active_aircraft_id:
        return False
    if getattr(aircraft, "phase", None) in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
        return False
    take_damage = getattr(aircraft, "take_damage", None)
    if take_damage is None or damage <= 0:
        return False
    setattr(missile, "damage_applied", True)
    return bool(take_damage(damage))


def can_fire_sniper(
    cooldown_remaining: float,
    held_weapon: Optional[WeaponKind] = WeaponKind.SNIPER,
    target_distance: Optional[float] = None,
) -> bool:
    return (
        held_weapon == WeaponKind.SNIPER
        and cooldown_ready(cooldown_remaining)
        and (target_distance is None or 0.0 <= target_distance <= config.SNIPER_MAX_RANGE)
    )


def can_fire_pistol(
    cooldown_remaining: float,
    target_distance: Optional[float],
    held_weapon: Optional[WeaponKind] = WeaponKind.PISTOL,
) -> bool:
    """Gate a pistol shot by phase-selected weapon, cooldown and short range."""

    return (
        held_weapon == WeaponKind.PISTOL
        and cooldown_ready(cooldown_remaining)
        and target_distance is not None
        and 0.0 <= target_distance <= config.PISTOL_MAX_RANGE
    )


def try_pickup_weapon(
    current_weapon: Optional[WeaponKind],
    requested_weapon: WeaponKind,
    *,
    in_range: bool,
    available: bool = True,
) -> tuple[bool, Optional[WeaponKind]]:
    if not in_range or not available or current_weapon is not None:
        return False, current_weapon
    return True, requested_weapon


def drop_weapon(current_weapon: Optional[WeaponKind]) -> tuple[bool, Optional[WeaponKind]]:
    if current_weapon is None:
        return False, None
    return True, None


def apply_enemy_hit(session: GameSession, damage: int) -> bool:
    """Apply one enemy hit; return True only when this hit caused death."""

    return session.take_damage(damage)


def resolve_session_event(
    session: GameSession,
    event: SessionEvent | str,
    *,
    event_id: Optional[str] = None,
    aircraft_id: Optional[str] = None,
    encounter_id: Optional[str] = None,
) -> GamePhase:
    return session.transition(
        event,
        event_id=event_id,
        aircraft_id=aircraft_id,
        encounter_id=encounter_id,
    )


@dataclass(frozen=True)
class AircraftProfile:
    aircraft_type: AircraftType
    max_health: int
    flight_duration: float
    evasion_amplitude: float
    evasion_frequency: float
    max_yaw_rate: float = 0.0
    max_pitch_rate: float = 0.0


def aircraft_profile(aircraft_type: AircraftType) -> AircraftProfile:
    """Return the centralized movement and health profile for an aircraft."""

    aircraft_type = AircraftType(aircraft_type)
    profiles = {
        AircraftType.NORMAL: AircraftProfile(
            aircraft_type,
            1,
            config.AIRCRAFT_NORMAL_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_NORMAL_EVASION_AMPLITUDE,
            config.AIRCRAFT_NORMAL_EVASION_FREQUENCY,
            config.AIRCRAFT_NORMAL_MAX_YAW_RATE_DEGREES,
            config.AIRCRAFT_NORMAL_MAX_PITCH_RATE_DEGREES,
        ),
        AircraftType.MANPOWER_SUPPORT: AircraftProfile(
            aircraft_type,
            1,
            config.AIRCRAFT_SUPPORT_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_SUPPORT_EVASION_AMPLITUDE,
            config.AIRCRAFT_SUPPORT_EVASION_FREQUENCY,
            config.AIRCRAFT_SUPPORT_MAX_YAW_RATE_DEGREES,
            config.AIRCRAFT_SUPPORT_MAX_PITCH_RATE_DEGREES,
        ),
        AircraftType.FAST: AircraftProfile(
            aircraft_type,
            1,
            config.AIRCRAFT_FAST_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_FAST_EVASION_AMPLITUDE,
            config.AIRCRAFT_FAST_EVASION_FREQUENCY,
            config.AIRCRAFT_FAST_MAX_YAW_RATE_DEGREES,
            config.AIRCRAFT_FAST_MAX_PITCH_RATE_DEGREES,
        ),
        AircraftType.ARMORED_BOSS: AircraftProfile(
            aircraft_type,
            config.ARMORED_AIRCRAFT_HEALTH,
            config.AIRCRAFT_ARMORED_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_ARMORED_EVASION_AMPLITUDE,
            config.AIRCRAFT_ARMORED_EVASION_FREQUENCY,
            config.AIRCRAFT_ARMORED_MAX_YAW_RATE_DEGREES,
            config.AIRCRAFT_ARMORED_MAX_PITCH_RATE_DEGREES,
        ),
    }
    return profiles[aircraft_type]


class WaveDirector:
    """Build deterministic rosters and preserve the increasing-count rule."""

    _REGULAR_TYPES = (
        AircraftType.NORMAL,
        AircraftType.MANPOWER_SUPPORT,
        AircraftType.FAST,
    )

    def __init__(
        self,
        initial_aircraft_count: int = 2,
        initial_cap: int = 6,
        cap_increment: int = 2,
    ) -> None:
        self.initial_aircraft_count = max(1, initial_aircraft_count)
        self.initial_cap = max(self.initial_aircraft_count, initial_cap)
        self.cap_increment = max(1, cap_increment)

    def aircraft_count_for_wave(self, wave_number: int) -> int:
        return self.initial_aircraft_count + max(0, wave_number - 1)

    def cap_for_count(self, aircraft_count: int) -> int:
        aircraft_count = max(1, aircraft_count)
        if aircraft_count <= self.initial_cap:
            return self.initial_cap
        bands = ceil((aircraft_count - self.initial_cap) / self.cap_increment)
        return self.initial_cap + bands * self.cap_increment

    def plan_wave(
        self,
        wave_number: int,
        aircraft_count: Optional[int] = None,
        cap: Optional[int] = None,
    ) -> WavePlan:
        wave_number = max(1, int(wave_number))
        count = aircraft_count or self.aircraft_count_for_wave(wave_number)
        count = max(1, int(count))
        aircraft_cap = max(1, int(cap)) if cap is not None else self.cap_for_count(count)
        is_boss_wave = wave_number % 10 == 0
        roster = tuple(
            AircraftType.ARMORED_BOSS
            if is_boss_wave and index == 0
            else self._REGULAR_TYPES[(wave_number + index - 1) % len(self._REGULAR_TYPES)]
            for index in range(count)
        )
        return WavePlan(
            wave_number=wave_number,
            aircraft_count=count,
            aircraft_cap=aircraft_cap,
            is_boss_wave=is_boss_wave,
            roster=roster,
        )

    def next_progress(self, progress: WaveProgress) -> WaveProgress:
        if not progress.is_last_aircraft:
            return WaveProgress(
                wave_number=progress.wave_number,
                aircraft_index=progress.aircraft_index + 1,
                aircraft_count=progress.aircraft_count,
                aircraft_cap=progress.aircraft_cap,
                is_boss_wave=progress.is_boss_wave,
                roster=progress.roster,
            )
        return self.plan_wave(progress.wave_number + 1).to_progress()


class EncounterFactory:
    """Creates one deterministic, finite crew group for one aircraft."""

    def __init__(
        self,
        minimum: int = ENCOUNTER_MIN_CREW,
        maximum: int = ENCOUNTER_MAX_CREW,
    ) -> None:
        self.minimum = minimum
        self.maximum = maximum

    def create_for_aircraft(
        self,
        aircraft_id: str,
        aircraft_type: AircraftType = AircraftType.NORMAL,
        random_source: Optional[RandomSource] = None,
    ) -> GroundEncounter:
        from .entities import CrewMember, GroundEncounter

        # Preserve the old two-argument form where the second argument was a
        # random source, while making the aircraft type explicit for new waves.
        if not isinstance(aircraft_type, AircraftType):
            if random_source is None and hasattr(aircraft_type, "randint"):
                random_source = aircraft_type  # type: ignore[assignment]
            aircraft_type = AircraftType.NORMAL
        source = random_source if random_source is not None else random
        if aircraft_type == AircraftType.NORMAL:
            minimum = max(0, min(ENCOUNTER_MAX_CREW, self.minimum))
            maximum = max(minimum, min(ENCOUNTER_MAX_CREW, self.maximum))
            count = source.randint(minimum, maximum)
        elif aircraft_type == AircraftType.MANPOWER_SUPPORT:
            count = config.MANPOWER_SUPPORT_CREW
        elif aircraft_type == AircraftType.FAST:
            count = 0
        else:
            count = 1

        route_nodes = config.COVER_NODES
        members = []
        for index in range(count):
            current_node = route_nodes[index % len(route_nodes)]
            target_node = (
                route_nodes[(index + 1) % len(route_nodes)]
                if index % 2
                else current_node
            )
            is_boss = aircraft_type == AircraftType.ARMORED_BOSS
            role = (
                SquadRole.COVER_SHOOTER
                if index % 2 == 0
                else SquadRole.ADVANCE_SHOOTER
            )
            members.append(
                CrewMember(
                    id=f"{aircraft_id}-crew-{index + 1}",
                    encounter_id=f"encounter:{aircraft_id}",
                    cover_node=current_node,
                    squad_role=role,
                    behavior_state=CrewBehaviorState.IN_COVER,
                    position=config.CRASH_SITE_POSITION,
                    target_cover_node=target_node,
                    route_index=index % len(route_nodes),
                    move_speed=(
                        config.GROUND_BOSS_MOVE_SPEED
                        if is_boss
                        else config.GROUND_MOVE_SPEED
                    ),
                    health=config.GROUND_BOSS_HEALTH if is_boss else 1,
                    max_health=config.GROUND_BOSS_HEALTH if is_boss else 1,
                    is_boss=is_boss,
                )
            )
        return GroundEncounter(
            aircraft_id=aircraft_id,
            crew=members,
            crew_count=count,
            aircraft_type=aircraft_type,
            boss_id=members[0].id if aircraft_type == AircraftType.ARMORED_BOSS and members else None,
        )


def advance_crew_behavior(
    encounter: GroundEncounter,
    delta_seconds: float,
    interval_seconds: float = CREW_ADVANCE_INTERVAL_SECONDS,
    route_positions: Optional[object] = None,
    city_position: Optional[tuple[float, float, float]] = None,
) -> None:
    """Move living crew toward cover nodes and then the city without teleporting."""

    routes = _normalise_route_positions(route_positions)
    if not routes:
        return
    route_ids = tuple(routes)
    city = city_position if city_position is not None else config.CITY_ATTACK_POINT
    delta_seconds = max(0.0, delta_seconds)
    interval_seconds = max(0.0, interval_seconds)

    for member in encounter.crew:
        if not member.alive:
            continue

        # Keep the explicit state sequence used by the old encounter tests.
        # Zero-delta calls are also useful to advance a visual state machine
        # without moving a member in a headless test.
        if delta_seconds <= 0.0 and member.behavior_state == CrewBehaviorState.ADVANCING:
            member.behavior_state = CrewBehaviorState.RELOCATING
            continue
        if delta_seconds <= 0.0 and member.behavior_state == CrewBehaviorState.RELOCATING:
            member.behavior_state = CrewBehaviorState.IN_COVER
            continue

        if member.at_city:
            member.behavior_state = CrewBehaviorState.IN_COVER
            continue

        member.advance_elapsed += delta_seconds
        target_id = member.target_cover_node
        if target_id is not None and target_id not in routes:
            # A stale/malformed route must still let the member continue to
            # the city rather than failing when route_ids.index() is called.
            member.target_cover_node = None
            target_id = None
        target = city if target_id is None else routes.get(target_id, city)
        member.position = _move_towards(
            member.position,
            target,
            member.move_speed * delta_seconds,
        )
        reached = _distance(member.position, target) <= 1e-6

        if target_id is None:
            if reached:
                member.position = city
                member.at_city = True
                member.behavior_state = CrewBehaviorState.IN_COVER
            continue

        if not reached:
            # An advance shooter announces its next cover assignment at the
            # interval, but its position keeps moving toward that node.
            if (
                member.squad_role == SquadRole.ADVANCE_SHOOTER
                and member.advance_elapsed >= interval_seconds
                and member.cover_node != target_id
            ):
                member.cover_node = target_id
                member.route_index = route_ids.index(target_id)
                member.advance_elapsed = 0.0
                member.behavior_state = CrewBehaviorState.ADVANCING
            elif member.behavior_state != CrewBehaviorState.ADVANCING:
                member.behavior_state = CrewBehaviorState.IN_COVER
            continue

        member.position = target
        member.cover_node = target_id
        member.route_index = route_ids.index(target_id)
        if member.advance_elapsed < interval_seconds:
            member.behavior_state = CrewBehaviorState.IN_COVER
            continue
        member.advance_elapsed = 0.0
        next_id = _next_route_node(target_id, route_ids)
        member.target_cover_node = next_id
        member.behavior_state = CrewBehaviorState.ADVANCING if next_id else CrewBehaviorState.IN_COVER


def defeat_crew_member(
    encounter: GroundEncounter,
    crew_id: str,
    session: Optional[GameSession] = None,
) -> bool:
    """Apply one valid firearm hit and count the defeat only once."""

    return damage_crew_member(encounter, crew_id, 1, session)


def damage_crew_member(
    encounter: GroundEncounter,
    crew_id: str,
    damage: int = 1,
    session: Optional[GameSession] = None,
) -> bool:
    """Apply guarded firearm damage and return true only when the target dies."""

    if session is not None and (
        session.phase != GamePhase.GROUND_COMBAT
        or session.active_encounter_id != encounter.id
    ):
        return False
    member = encounter.find(crew_id)
    if member is None or not member.alive:
        return False
    defeated = member.take_damage(damage)
    if defeated and session is not None:
        session.stats.record_once(f"enemy-defeated:{crew_id}", "enemy_defeated")
    encounter.refresh_cleared()
    return defeated


def apply_city_damage(
    encounter: GroundEncounter,
    building: object,
    delta_seconds: float,
) -> bool:
    """Apply damage from every living crew member inside the city zone."""

    if encounter.cleared or delta_seconds <= 0.0:
        return False
    position = getattr(building, "position", config.BUILDING_POSITION)
    radius = float(getattr(building, "attack_zone_radius", config.CITY_ATTACK_RADIUS))
    attackers = []
    for member in encounter.crew:
        if not member.alive:
            continue
        if (
            member.at_city
            or _distance(member.position, config.CITY_ATTACK_POINT) <= 1e-6
            or _distance_xz(member.position, position) <= radius
        ):
            member.at_city = True
            member.city_attack_elapsed += max(0.0, delta_seconds)
            attackers.append(member)
    if not attackers:
        return False
    amount = len(attackers) * config.CITY_DAMAGE_PER_SECOND * max(0.0, delta_seconds)
    encounter.city_damage_accumulator += amount
    take_damage = getattr(building, "take_damage", None)
    if take_damage is None:
        return False
    return bool(take_damage(amount))


def _normalise_route_positions(route_positions: Optional[object]) -> dict[str, tuple[float, float, float]]:
    if route_positions is None:
        return dict(config.COVER_NODE_POSITIONS)
    if isinstance(route_positions, dict):
        return {str(key): tuple(value) for key, value in route_positions.items()}
    return {
        str(index): tuple(value)
        for index, value in enumerate(route_positions)  # type: ignore[arg-type]
    }


def _next_route_node(current: str, route_ids: tuple[str, ...]) -> Optional[str]:
    try:
        index = route_ids.index(current)
    except ValueError:
        return route_ids[0] if route_ids else None
    return route_ids[index + 1] if index + 1 < len(route_ids) else None


def _distance(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sqrt(sum((left - right) ** 2 for left, right in zip(first, second)))


def _distance_xz(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return sqrt((first[0] - second[0]) ** 2 + (first[2] - second[2]) ** 2)


def _move_towards(
    current: tuple[float, float, float],
    target: tuple[float, float, float],
    max_distance: float,
) -> tuple[float, float, float]:
    distance = _distance(current, target)
    if distance <= max(0.0, max_distance) or distance <= 1e-9:
        return tuple(target)
    ratio = max(0.0, max_distance) / distance
    return tuple(
        current[index] + (target[index] - current[index]) * ratio
        for index in range(3)
    )


def add_reinforcement(encounter: GroundEncounter, *_: object) -> bool:
    """The feature explicitly has no ground reinforcement path."""

    return False


@dataclass(frozen=True)
class AirstrikeOutcome:
    success: bool
    reason: str


def resolve_aircraft_outcome(
    session: GameSession,
    *,
    aircraft_id: str,
    outcome: str,
) -> AirstrikeOutcome:
    """Resolve destroy/impact races in first-event order via the session guard."""

    if outcome == "destroyed":
        before = session.phase
        session.transition(
            SessionEvent.AIRCRAFT_DESTROYED,
            aircraft_id=aircraft_id,
        )
        return AirstrikeOutcome(
            session.phase == GamePhase.GROUND_COMBAT,
            "aircraft_destroyed" if before == GamePhase.AIRSTRIKE else "ignored",
        )
    if outcome == "building_impact":
        before = session.phase
        session.transition(SessionEvent.BUILDING_IMPACT, aircraft_id=aircraft_id)
        return AirstrikeOutcome(
            session.phase == GamePhase.GAME_OVER,
            "building_impact" if before == GamePhase.AIRSTRIKE else "ignored",
        )
    raise ValueError(f"Unknown aircraft outcome: {outcome}")
