"""Pure gameplay rules used by the graphical adapter and unit tests."""

from __future__ import annotations

import random
from dataclasses import dataclass
from math import ceil, sqrt
from typing import TYPE_CHECKING, Optional, Protocol

from . import config
from .config import (
    AIRSTRIKE_WARNING_LEAD_SECONDS,
    CREW_ADVANCE_INTERVAL_SECONDS,
    ENCOUNTER_MAX_CREW,
    ENCOUNTER_MIN_CREW,
    LOCK_DURATION_SECONDS,
    LOCK_FLASH_HALF_PERIOD_SECONDS,
)
from .state import (
    CrewBehaviorState,
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
    """Accumulates only uninterrupted visible target time."""

    def __init__(self, lock_duration: float = LOCK_DURATION_SECONDS) -> None:
        self.lock_duration = lock_duration
        self.lock_elapsed = 0.0
        self.state = LockState.WHITE

    def update(self, target_visible: bool, delta_seconds: float) -> LockState:
        if not target_visible:
            self.reset()
            return self.state
        self.lock_elapsed = min(
            self.lock_duration,
            self.lock_elapsed + max(0.0, delta_seconds),
        )
        self.state = (
            LockState.GREEN_READY
            if self.lock_elapsed >= self.lock_duration
            else LockState.RED_TRACKING
        )
        return self.state

    def reset(self) -> None:
        self.lock_elapsed = 0.0
        self.state = LockState.WHITE

    def flash_visible(self, half_period: float = LOCK_FLASH_HALF_PERIOD_SECONDS) -> bool:
        if self.state != LockState.RED_TRACKING or half_period <= 0:
            return self.state == LockState.RED_TRACKING
        return int(self.lock_elapsed / half_period) % 2 == 0


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
) -> bool:
    return (
        held_weapon == WeaponKind.ANTI_AIRCRAFT
        and lock_state == LockState.GREEN_READY
        and cooldown_ready(cooldown_remaining)
    )


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
        ),
        AircraftType.MANPOWER_SUPPORT: AircraftProfile(
            aircraft_type,
            1,
            config.AIRCRAFT_SUPPORT_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_SUPPORT_EVASION_AMPLITUDE,
            config.AIRCRAFT_SUPPORT_EVASION_FREQUENCY,
        ),
        AircraftType.FAST: AircraftProfile(
            aircraft_type,
            1,
            config.AIRCRAFT_FAST_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_FAST_EVASION_AMPLITUDE,
            config.AIRCRAFT_FAST_EVASION_FREQUENCY,
        ),
        AircraftType.ARMORED_BOSS: AircraftProfile(
            aircraft_type,
            config.ARMORED_AIRCRAFT_HEALTH,
            config.AIRCRAFT_ARMORED_FLIGHT_DURATION_SECONDS,
            config.AIRCRAFT_ARMORED_EVASION_AMPLITUDE,
            config.AIRCRAFT_ARMORED_EVASION_FREQUENCY,
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
