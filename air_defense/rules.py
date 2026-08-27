"""Pure gameplay rules used by the graphical adapter and unit tests."""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import acos, asin, atan2, ceil, cos, degrees, hypot, pi, radians, sin, sqrt
from typing import TYPE_CHECKING, Mapping, Optional, Protocol, Sequence

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
    WaveRuntime,
    WeaponKind,
)

if TYPE_CHECKING:
    from .entities import GroundEncounter


class RandomSource(Protocol):
    def randint(self, minimum: int, maximum: int) -> int: ...


class LockOnTracker:
    """Accumulates one sticky, visible target while the anti-air scope is open."""

    def __init__(
        self,
        lock_duration: float = LOCK_DURATION_SECONDS,
        decay_duration: float = AA_LOCK_DECAY_SECONDS,
        *,
        scope_enabled: bool = False,
        target_aircraft_id: Optional[str] = None,
    ) -> None:
        self.lock_duration = max(1e-6, float(lock_duration))
        self.decay_duration = max(1e-6, float(decay_duration))
        self.lock_elapsed = 0.0
        self.state = LockState.WHITE
        self.target_aircraft_id = target_aircraft_id
        self.target_visible = False
        self.target_in_frame = False
        self.scope_enabled = bool(scope_enabled)
        self.completion_flash_remaining = 0.0

    @property
    def target_in_zone(self) -> bool:
        """Legacy alias for the original circular lock-zone boolean."""

        return self.target_in_frame

    @target_in_zone.setter
    def target_in_zone(self, value: bool) -> None:
        self.target_in_frame = bool(value)

    @property
    def fireable(self) -> bool:
        return bool(
            self.scope_enabled
            and self.state == LockState.GREEN_READY
            and self.target_aircraft_id is not None
            and self.target_visible
            and self.target_in_frame
        )

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

    def set_target(self, target_aircraft_id: Optional[str]) -> None:
        target_aircraft_id = (
            str(target_aircraft_id) if target_aircraft_id is not None else None
        )
        if target_aircraft_id != self.target_aircraft_id and self.lock_elapsed > 0.0:
            self.lock_elapsed = 0.0
            self.state = LockState.WHITE
        self.target_aircraft_id = target_aircraft_id

    def update(
        self,
        target_in_zone: bool = False,
        delta_seconds: float = 0.0,
        *legacy_args: object,
        target_visible: Optional[bool] = None,
        target_in_frame: Optional[bool] = None,
        target_aircraft_id: Optional[str] = None,
    ) -> LockState:
        """Update visibility/frame membership with a linear decay buffer.

        The two-argument form remains compatible with the original tests. A
        three-positional form is also accepted as ``visible, in_frame, dt``
        for small headless integrations.
        """

        if legacy_args:
            if len(legacy_args) != 1:
                raise TypeError("update accepts at most one legacy delta argument")
            target_visible = bool(target_in_zone)
            target_in_frame = bool(delta_seconds)
            delta_seconds = float(legacy_args[0])
        if target_aircraft_id is not None:
            self.set_target(target_aircraft_id)
        if not self.scope_enabled:
            self.reset()
            return self.state

        delta_seconds = max(0.0, float(delta_seconds))
        self.target_visible = (
            bool(target_in_zone) if target_visible is None else bool(target_visible)
        )
        self.target_in_frame = (
            bool(target_in_zone) if target_in_frame is None else bool(target_in_frame)
        )
        eligible = self.target_visible and self.target_in_frame
        self.completion_flash_remaining = max(
            0.0,
            self.completion_flash_remaining - delta_seconds,
        )
        if eligible:
            self.lock_elapsed = min(self.lock_duration, self.lock_elapsed + delta_seconds)
        else:
            decay_rate = self.lock_duration / self.decay_duration
            self.lock_elapsed = max(0.0, self.lock_elapsed - delta_seconds * decay_rate)

        if self.lock_elapsed <= 0.0:
            self.lock_elapsed = 0.0
            self.state = LockState.WHITE
            if not eligible:
                self.target_aircraft_id = None
        elif self.lock_elapsed >= self.lock_duration and eligible:
            self.lock_elapsed = self.lock_duration
            if self.state != LockState.GREEN_READY:
                self.completion_flash_remaining = LOCK_FLASH_HALF_PERIOD_SECONDS
            self.state = LockState.GREEN_READY
        else:
            self.state = LockState.RED_TRACKING
        return self.state

    def reset(self) -> None:
        self.lock_elapsed = 0.0
        self.state = LockState.WHITE
        self.target_visible = False
        self.target_in_frame = False
        self.target_aircraft_id = None
        self.completion_flash_remaining = 0.0

    def flash_visible(self, half_period: float = LOCK_FLASH_HALF_PERIOD_SECONDS) -> bool:
        if self.completion_flash_remaining > 0.0:
            return True
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


def clamp_ratio(value: float, *, denominator: float = 1.0) -> float:
    """Clamp a ratio safely, including a zero/negative denominator."""

    denominator = float(denominator)
    if denominator <= 0.0:
        return 0.0
    return _clamp(float(value) / denominator, 0.0, 1.0)


def lock_frame_bounds(
    viewport_width: float,
    viewport_height: float,
    frame_size: float = config.AA_LOCK_FRAME_SIZE,
) -> tuple[float, float, float, float]:
    """Return inclusive ``left, bottom, right, top`` pixel bounds."""

    width = max(0.0, float(viewport_width))
    height = max(0.0, float(viewport_height))
    half_size = min(width, height) * max(0.0, float(frame_size)) * 0.5
    center = (width * 0.5, height * 0.5)
    return (
        center[0] - half_size,
        center[1] - half_size,
        center[0] + half_size,
        center[1] + half_size,
    )


def _position_in_bounds(
    screen_position: Vector2,
    bounds: tuple[float, float, float, float],
) -> bool:
    left, bottom, right, top = bounds
    return (
        left - 1e-6 <= float(screen_position[0]) <= right + 1e-6
        and bottom - 1e-6 <= float(screen_position[1]) <= top + 1e-6
    )


def is_inside_lock_frame(
    screen_position: Vector2,
    viewport_width: float,
    viewport_height: float,
    frame_size: float = config.AA_LOCK_FRAME_SIZE,
) -> bool:
    return _position_in_bounds(
        screen_position,
        lock_frame_bounds(viewport_width, viewport_height, frame_size),
    )


def is_inside_expanded_lock_frame(
    screen_position: Vector2,
    viewport_width: float,
    viewport_height: float,
    frame_size: float = config.AA_LOCK_FRAME_SIZE,
    multiplier: float = AA_AIM_ASSIST_ZONE_MULTIPLIER,
) -> bool:
    return is_inside_lock_frame(
        screen_position,
        viewport_width,
        viewport_height,
        max(0.0, float(frame_size)) * max(0.0, float(multiplier)),
    )


def _candidate_id(candidate: object) -> Optional[str]:
    value = getattr(candidate, "aircraft_id", None)
    if value is None:
        value = getattr(candidate, "id", None)
    return str(value) if value is not None else None


def _candidate_in_frame(candidate: object) -> bool:
    value = getattr(candidate, "in_lock_frame", None)
    if value is None:
        value = getattr(candidate, "in_lock_zone", False)
    return bool(value)


def select_lock_target(
    candidates: Sequence[object],
    current_target_id: Optional[str] = None,
    *,
    lock_progress: float = 0.0,
) -> Optional[object]:
    """Choose a visible in-frame candidate while retaining a valid sticky ID."""

    eligible = [
        candidate
        for candidate in candidates
        if bool(getattr(candidate, "visible", False)) and _candidate_in_frame(candidate)
        and _candidate_id(candidate) is not None
    ]
    if current_target_id is not None:
        sticky = next(
            (
                candidate
                for candidate in candidates
                if bool(getattr(candidate, "visible", False))
                if _candidate_id(candidate) == str(current_target_id)
                and (_candidate_in_frame(candidate) or float(lock_progress) > 0.0)
            ),
            None,
        )
        if sticky is not None:
            return sticky
    return min(
        eligible,
        key=lambda candidate: (
            float(getattr(candidate, "distance_from_center", float("inf"))),
            _candidate_id(candidate) or "",
        ),
        default=None,
    )


def reticle_position_for_progress(
    frame_center: Vector2,
    frame_bounds: tuple[float, float, float, float],
    target_position: Optional[Vector2],
    progress: float,
) -> Vector2:
    """Interpolate the small reticle toward a target clamped inside the frame."""

    if target_position is None:
        return (float(frame_center[0]), float(frame_center[1]))
    left, bottom, right, top = frame_bounds
    target = (
        _clamp(float(target_position[0]), left, right),
        _clamp(float(target_position[1]), bottom, top),
    )
    amount = _clamp(float(progress), 0.0, 1.0)
    return (
        float(frame_center[0]) + (target[0] - float(frame_center[0])) * amount,
        float(frame_center[1]) + (target[1] - float(frame_center[1])) * amount,
    )


@dataclass(frozen=True)
class PlayerStatusView:
    health: int
    max_health: int
    health_ratio: float
    icon_color: tuple[float, float, float]
    bar_color: tuple[float, float, float]


@dataclass(frozen=True)
class CityStatusView:
    city_health: float
    max_city_health: float
    health_ratio: float
    percent: int
    icon_color: tuple[float, float, float]
    bar_color: tuple[float, float, float]


@dataclass(frozen=True)
class WaveDotView:
    aircraft_id: str
    aircraft_type: AircraftType
    phase: AircraftPhase
    alive: bool
    terminal: bool
    color: tuple[float, float, float]


@dataclass(frozen=True)
class WaveStatusView:
    wave_number: int
    aircraft_total: int
    aircraft_alive: int
    aircraft_ratio: float
    aircraft_percent: int
    dots: tuple[WaveDotView, ...]
    selected_aircraft_type: Optional[AircraftType]
    selected_aircraft_id: Optional[str]
    selected_type_label: str
    layout_rows: int
    dots_per_row: int
    dot_size: float
    aircraft_type_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class WeaponCooldownView:
    weapon: WeaponKind
    remaining_seconds: float
    duration_seconds: float
    fill_ratio: float
    ready: bool
    visible: bool
    color: tuple[float, float, float]


@dataclass(frozen=True)
class SniperScopeView:
    enabled: bool
    fov: float
    circular_mask: bool
    crosshair: bool
    center_dot: bool
    checkerboard: bool


def build_player_status_view(health: int, max_health: int) -> PlayerStatusView:
    maximum = max(1, int(max_health))
    current = int(round(_clamp(float(health), 0.0, float(maximum))))
    return PlayerStatusView(
        health=current,
        max_health=maximum,
        health_ratio=clamp_ratio(current, denominator=maximum),
        icon_color=config.RED_RGB,
        bar_color=config.RED_RGB,
    )


def build_city_status_view(city_health: float, max_city_health: float) -> CityStatusView:
    maximum = max(1.0, float(max_city_health))
    current = _clamp(float(city_health), 0.0, maximum)
    return CityStatusView(
        city_health=current,
        max_city_health=maximum,
        health_ratio=clamp_ratio(current, denominator=maximum),
        percent=int(round(clamp_ratio(current, denominator=maximum) * 100.0)),
        icon_color=config.BLUE_RGB,
        bar_color=config.BLUE_RGB,
    )


def build_wave_status_view(
    runtime: Optional[WaveRuntime],
    *,
    active_target_id: Optional[str] = None,
    viewport_width: float = config.WINDOW_WIDTH,
) -> WaveStatusView:
    if runtime is None:
        return WaveStatusView(
            wave_number=1,
            aircraft_total=0,
            aircraft_alive=0,
            aircraft_ratio=0.0,
            aircraft_percent=0,
            dots=(),
            selected_aircraft_type=None,
            selected_aircraft_id=None,
            selected_type_label="未選定",
            layout_rows=0,
            dots_per_row=0,
            dot_size=config.HUD_WAVE_DOT_SIZE,
        )
    dots = tuple(
        WaveDotView(
            aircraft_id=aircraft_id,
            aircraft_type=runtime.aircraft_types[aircraft_id],
            phase=runtime.aircraft_statuses[aircraft_id],
            alive=runtime.aircraft_statuses[aircraft_id]
            in (AircraftPhase.APPROACHING, AircraftPhase.LOCKED),
            terminal=runtime.aircraft_statuses[aircraft_id]
            in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED),
            color=(
                config.BLUE_RGB
                if runtime.aircraft_statuses[aircraft_id]
                in (AircraftPhase.APPROACHING, AircraftPhase.LOCKED)
                else config.GRAY_RGB
            ),
        )
        for aircraft_id in runtime.aircraft_ids
    )
    selected_id = active_target_id or runtime.active_target_id
    if selected_id not in runtime.aircraft_ids:
        selected_id = None
    selected_type = runtime.aircraft_types[selected_id] if selected_id is not None else None
    type_labels = {
        AircraftType.NORMAL: "普通",
        AircraftType.MANPOWER_SUPPORT: "人力支援",
        AircraftType.FAST: "快速",
        AircraftType.ARMORED_BOSS: "Boss",
    }
    aircraft_type_labels = tuple(
        dict.fromkeys(type_labels.get(dot.aircraft_type, "未分類") for dot in dots)
    )
    total = len(dots)
    width_capacity = max(1, int(float(viewport_width) / 64.0))
    dots_per_row = max(
        1,
        min(config.HUD_WAVE_DOTS_PER_ROW, width_capacity),
    )
    rows = ceil(total / dots_per_row) if total else 0
    dot_size = (
        config.HUD_WAVE_DOT_MIN_SIZE
        if total > config.HUD_WAVE_DOTS_PER_ROW
        else config.HUD_WAVE_DOT_SIZE
    )
    return WaveStatusView(
        wave_number=runtime.wave.wave_number,
        aircraft_total=total,
        aircraft_alive=runtime.remaining_aircraft_count,
        aircraft_ratio=runtime.alive_ratio,
        aircraft_percent=int(round(runtime.alive_ratio * 100.0)),
        dots=dots,
        selected_aircraft_type=selected_type,
        selected_aircraft_id=selected_id,
        selected_type_label=type_labels.get(selected_type, "未選定"),
        layout_rows=rows,
        dots_per_row=dots_per_row,
        dot_size=dot_size,
        aircraft_type_labels=aircraft_type_labels,
    )


def _weapon_lookup(weapons: Mapping[object, object]) -> dict[WeaponKind, object]:
    result: dict[WeaponKind, object] = {}
    aliases = {
        "aa": WeaponKind.ANTI_AIRCRAFT,
        "anti_aircraft": WeaponKind.ANTI_AIRCRAFT,
        "sniper": WeaponKind.SNIPER,
        "pistol": WeaponKind.PISTOL,
    }
    for key, value in weapons.items():
        kind = key if isinstance(key, WeaponKind) else aliases.get(str(key))
        if kind is not None:
            result[kind] = value
    return result


def weapon_cooldown_view(
    weapon: Optional[WeaponKind | str],
    weapons: Mapping[object, object],
    *,
    gameplay: bool = True,
) -> Optional[WeaponCooldownView]:
    if weapon is None or not gameplay:
        return None
    aliases = {
        "aa": WeaponKind.ANTI_AIRCRAFT,
        "anti_aircraft": WeaponKind.ANTI_AIRCRAFT,
        "sniper": WeaponKind.SNIPER,
        "pistol": WeaponKind.PISTOL,
    }
    kind = weapon if isinstance(weapon, WeaponKind) else aliases.get(str(weapon))
    if kind is None:
        return None
    source = _weapon_lookup(weapons).get(kind)
    if source is None:
        return None
    durations = {
        WeaponKind.ANTI_AIRCRAFT: config.AA_FIRE_COOLDOWN_SECONDS,
        WeaponKind.SNIPER: config.SNIPER_FIRE_COOLDOWN_SECONDS,
        WeaponKind.PISTOL: config.PISTOL_FIRE_COOLDOWN_SECONDS,
    }
    duration = max(1e-6, float(durations[kind]))
    remaining = min(
        duration,
        max(0.0, float(getattr(source, "fire_cooldown", 0.0))),
    )
    ratio = clamp_ratio(duration - min(duration, remaining), denominator=duration)
    return WeaponCooldownView(
        weapon=kind,
        remaining_seconds=remaining,
        duration_seconds=duration,
        fill_ratio=ratio,
        ready=remaining <= 0.0,
        visible=True,
        color=config.GREEN_RGB if remaining <= 0.0 else config.YELLOW_RGB,
    )


def reset_weapon_cooldowns(*weapon_objects: object) -> int:
    """Reset each weapon object once and return the number changed."""

    if len(weapon_objects) == 1 and isinstance(weapon_objects[0], Mapping):
        weapon_objects = tuple(weapon_objects[0].values())
    changed = 0
    seen: set[int] = set()
    for weapon in weapon_objects:
        if weapon is None or id(weapon) in seen or not hasattr(weapon, "fire_cooldown"):
            continue
        seen.add(id(weapon))
        if float(getattr(weapon, "fire_cooldown", 0.0)) != 0.0:
            changed += 1
        setattr(weapon, "fire_cooldown", 0.0)
    return changed


def sniper_scope_view(enabled: bool) -> SniperScopeView:
    return SniperScopeView(
        enabled=bool(enabled),
        fov=config.CAMERA_SCOPE_FOV,
        circular_mask=True,
        crosshair=True,
        center_dot=True,
        checkerboard=False,
    )


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
    target_in_expanded_frame: Optional[bool] = None,
) -> Vector3:
    """Apply small scope-only attraction after player mouse rotation."""

    current = normalize_vector(current_direction)
    if not scope_enabled or not target_visible:
        return current
    activation_radius = max(0.0, float(lock_zone_radius_pixels)) * max(0.0, float(activation_multiplier))
    in_activation_zone = (
        bool(target_in_expanded_frame)
        if target_in_expanded_frame is not None
        else float(target_screen_distance) <= activation_radius + 1e-6
    )
    if not in_activation_zone:
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
        phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
        and requested_weapon == WeaponKind.ANTI_AIRCRAFT
    ) or (
        phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
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
    *,
    target_aircraft_id: Optional[str] = None,
    target_visible: Optional[bool] = None,
    target_in_frame: Optional[bool] = None,
    scope_enabled: Optional[bool] = None,
) -> bool:
    in_frame = bool(target_in_zone if target_in_frame is None else target_in_frame)
    visible = bool(in_frame if target_visible is None else target_visible)
    return (
        held_weapon == WeaponKind.ANTI_AIRCRAFT
        and lock_state == LockState.GREEN_READY
        and cooldown_ready(cooldown_remaining)
        and in_frame
        and visible
        and (scope_enabled is not False)
        and (target_aircraft_id is None or bool(target_aircraft_id))
    )


def apply_guided_missile_damage(
    aircraft: object,
    missile: object,
    step: object,
    *,
    active_aircraft_id: Optional[str] = None,
    expected_aircraft_id: Optional[str] = None,
    target_id: Optional[str] = None,
    damage: int = 1,
) -> bool:
    """Apply one collision-time hit after validating target identity and phase."""

    if not bool(getattr(step, "hit", False)):
        return False
    if bool(getattr(missile, "damage_applied", False)):
        return False
    aircraft_id = getattr(aircraft, "id", None)
    missile_target_id = getattr(missile, "target_aircraft_id", None)
    expected_target_id = (
        expected_aircraft_id
        if expected_aircraft_id is not None
        else target_id if target_id is not None else active_aircraft_id
    )
    if (
        expected_target_id is None
        or aircraft_id != expected_target_id
        or missile_target_id != expected_target_id
    ):
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
    wave_plan: Optional[WavePlan] = None,
    ground_cleared: Optional[bool] = None,
) -> GamePhase:
    return session.transition(
        event,
        event_id=event_id,
        aircraft_id=aircraft_id,
        encounter_id=encounter_id,
        wave_plan=wave_plan,
        ground_cleared=ground_cleared,
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


def normalize_aircraft_token(token: str) -> str:
    """Normalize the user-facing special-aircraft alias to the canonical token."""

    normalized = str(token).strip()
    if normalized == "摩":
        normalized = "魔"
    if normalized not in {"普", "特", "魔"}:
        raise ValueError(f"Unknown aircraft token: {token}")
    return normalized


class WaveDirector:
    """Build the finite, deterministic campaign roster."""

    _REGULAR_TYPES = (
        AircraftType.NORMAL,
        AircraftType.MANPOWER_SUPPORT,
        AircraftType.FAST,
    )
    _CAMPAIGN_TOKENS = (
        ("普", "普"),
        ("普", "特"),
        ("特", "特"),
        ("魔", "特"),
        ("普", "普", "普"),
        ("普", "普", "特"),
        ("普", "特", "特"),
        ("特", "特", "特"),
        ("魔", "特", "特"),
        ("普", "普", "普", "普"),
        ("普", "普", "普", "特"),
        ("普", "普", "特", "特"),
        ("普", "特", "特", "特"),
        ("特", "特", "特", "特"),
        ("魔", "特", "特", "特"),
        ("魔", "魔", "特", "特"),
        ("魔", "魔", "魔", "特"),
        ("魔", "魔", "魔", "魔"),
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
        wave_number = int(wave_number)
        if not 1 <= wave_number <= len(self._CAMPAIGN_TOKENS):
            raise ValueError("wave_number must be between 1 and 18")
        return len(self._CAMPAIGN_TOKENS[wave_number - 1])

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
        wave_number = int(wave_number)
        if not 1 <= wave_number <= len(self._CAMPAIGN_TOKENS):
            raise ValueError("wave_number must be between 1 and 18")
        has_synthetic_override = aircraft_count is not None or cap is not None
        if has_synthetic_override:
            count = (
                self.aircraft_count_for_wave(wave_number)
                if aircraft_count is None
                else int(aircraft_count)
            )
            if count < 1:
                raise ValueError("aircraft_count must be positive")
            if cap is not None and int(cap) < count:
                raise ValueError("cap must be at least aircraft_count")
            aircraft_cap = self.cap_for_count(count) if cap is None else int(cap)
            roster = tuple(
                self._REGULAR_TYPES[index % len(self._REGULAR_TYPES)]
                for index in range(count)
            )
        else:
            roster = self._campaign_roster(wave_number)
            count = len(roster)
            aircraft_cap = self.cap_for_count(count)
        is_boss_wave = AircraftType.ARMORED_BOSS in roster
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
        if progress.wave_number >= len(self._CAMPAIGN_TOKENS):
            raise ValueError("wave 18 has no successor")
        return self.plan_wave(progress.wave_number + 1).to_progress()

    def is_final_wave(self, wave_number: int) -> bool:
        return int(wave_number) == len(self._CAMPAIGN_TOKENS)

    @classmethod
    def _campaign_roster(cls, wave_number: int) -> tuple[AircraftType, ...]:
        special_ordinal = 0
        for index, raw_roster in enumerate(cls._CAMPAIGN_TOKENS, start=1):
            resolved: list[AircraftType] = []
            for raw_token in raw_roster:
                token = normalize_aircraft_token(raw_token)
                if token == "普":
                    resolved.append(AircraftType.NORMAL)
                elif token == "魔":
                    resolved.append(AircraftType.ARMORED_BOSS)
                elif token == "特":
                    special_ordinal += 1
                    resolved.append(
                        AircraftType.MANPOWER_SUPPORT
                        if special_ordinal % 2 == 1
                        else AircraftType.FAST
                    )
                else:  # pragma: no cover - normalize guards the table itself
                    raise ValueError(f"Unknown campaign token: {raw_token}")
            if index == wave_number:
                return tuple(resolved)
        raise ValueError("wave_number must be between 1 and 18")


class EncounterFactory:
    """Creates deterministic finite crew groups for aircraft or a full wave."""

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
            else:
                aircraft_type = AircraftType(aircraft_type)
        source = random_source if random_source is not None else random
        encounter_id = f"encounter:{aircraft_id}"
        count = self._crew_count(aircraft_type, source)
        members = self._create_source_crew(
            aircraft_id,
            aircraft_type,
            count,
            encounter_id,
        )
        return GroundEncounter(
            aircraft_id=aircraft_id,
            crew=members,
            crew_count=count,
            aircraft_type=aircraft_type,
            boss_id=members[0].id if aircraft_type == AircraftType.ARMORED_BOSS and members else None,
            source_aircraft_ids=(aircraft_id,),
        )

    def create_drop_batch(
        self,
        aircraft_id: str,
        aircraft_type: AircraftType,
        encounter_id: str,
        hit_position: tuple[float, float, float],
        random_source: Optional[RandomSource] = None,
    ) -> tuple[object, ...]:
        """Create one immediately visible source batch in descent state."""

        aircraft_id = str(aircraft_id)
        encounter_id = str(encounter_id)
        aircraft_type = AircraftType(aircraft_type)
        source = random_source if random_source is not None else random
        count = self._crew_count(aircraft_type, source)
        members = self._create_source_crew(
            aircraft_id,
            aircraft_type,
            count,
            encounter_id,
        )
        hit = tuple(float(value) for value in hit_position)
        for index, member in enumerate(members):
            offset = config.CREW_DESCENT_SPREAD_OFFSETS[
                index % len(config.CREW_DESCENT_SPREAD_OFFSETS)
            ]
            start = (hit[0] + offset[0], hit[1], hit[2] + offset[1])
            landing = (start[0], config.GROUND_LEVEL_Y, start[2])
            member.begin_descent(
                start,
                landing,
                config.CREW_DESCENT_DURATION_SECONDS,
                offset,
            )
        return tuple(members)

    def create_for_wave(
        self,
        wave_number: int,
        aircraft_ids: Sequence[str],
        aircraft_types: Mapping[str, AircraftType],
        random_source: Optional[RandomSource] = None,
    ) -> GroundEncounter:
        """Merge all source aircraft into one ``encounter:wave-N`` group."""

        from .entities import GroundEncounter

        ids = tuple(str(aircraft_id) for aircraft_id in aircraft_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("aircraft_ids must be a non-empty unique sequence")
        if set(aircraft_types) != set(ids):
            raise ValueError("aircraft_types keys must match aircraft_ids")
        wave_number = max(1, int(wave_number))
        source = random_source if random_source is not None else random
        group_id = f"wave-{wave_number}"
        encounter_id = f"encounter:{group_id}"
        members = []
        for aircraft_id in ids:
            aircraft_type = AircraftType(aircraft_types[aircraft_id])
            # NORMAL consumes exactly one random draw per source. Fixed-size
            # types never call randint, which makes wave fixtures reproducible.
            count = self._crew_count(aircraft_type, source)
            members.extend(
                self._create_source_crew(
                    aircraft_id,
                    aircraft_type,
                    count,
                    encounter_id,
                )
            )
        boss = next((member for member in members if member.is_boss), None)
        aggregate_type = (
            AircraftType.ARMORED_BOSS
            if boss is not None
            else AircraftType.NORMAL
        )
        return GroundEncounter(
            aircraft_id=group_id,
            crew=members,
            crew_count=len(members),
            aircraft_type=aggregate_type,
            boss_id=boss.id if boss is not None else None,
            source_aircraft_ids=ids,
            group_id=group_id,
        )

    def _crew_count(self, aircraft_type: AircraftType, source: RandomSource) -> int:
        aircraft_type = AircraftType(aircraft_type)
        if aircraft_type == AircraftType.NORMAL:
            minimum = max(0, min(ENCOUNTER_MAX_CREW, int(self.minimum)))
            maximum = max(minimum, min(ENCOUNTER_MAX_CREW, int(self.maximum)))
            return int(source.randint(minimum, maximum))
        if aircraft_type == AircraftType.MANPOWER_SUPPORT:
            return config.MANPOWER_SUPPORT_CREW
        if aircraft_type == AircraftType.FAST:
            return 0
        return 1

    @staticmethod
    def _create_source_crew(
        aircraft_id: str,
        aircraft_type: AircraftType,
        count: int,
        encounter_id: str,
    ) -> list[object]:
        from .entities import CrewMember

        route_nodes = config.COVER_NODES
        members: list[CrewMember] = []
        for index in range(max(0, int(count))):
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
                    encounter_id=encounter_id,
                    cover_node=current_node,
                    squad_role=role,
                    source_aircraft_id=aircraft_id,
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
        return members


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
        if not member.alive or member.behavior_state == CrewBehaviorState.DESCENDING:
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
        session.phase not in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
        or session.active_encounter_id != encounter.id
    ):
        return False
    member = encounter.find(crew_id)
    if member is None or not member.alive:
        return False
    defeated = member.take_damage(damage)
    if defeated and session is not None:
        session.stats.record_once(f"enemy-defeated:{crew_id}", "enemy_defeated")
    if defeated:
        encounter.record_crew_cleared(crew_id)
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
        if not member.alive or member.behavior_state == CrewBehaviorState.DESCENDING:
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


def add_reinforcement(
    encounter: GroundEncounter,
    members: Optional[Sequence[object]] = None,
    source_aircraft_id: Optional[str] = None,
) -> bool:
    """Compatibility wrapper for the aggregate encounter operation."""

    if members is None or source_aircraft_id is None:
        return False
    return encounter.add_reinforcement(list(members), source_aircraft_id)  # type: ignore[arg-type]


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
            session.phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT),
            "aircraft_destroyed"
            if before in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
            else "ignored",
        )
    if outcome == "building_impact":
        before = session.phase
        session.transition(SessionEvent.BUILDING_IMPACT, aircraft_id=aircraft_id)
        return AirstrikeOutcome(
            session.phase == GamePhase.GAME_OVER,
            "building_impact"
            if before in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
            else "ignored",
        )
    raise ValueError(f"Unknown aircraft outcome: {outcome}")
