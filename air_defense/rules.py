"""Pure gameplay rules used by the graphical adapter and unit tests."""

from __future__ import annotations

import random
from dataclasses import dataclass
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
    GamePhase,
    GameSession,
    LockState,
    SessionEvent,
    SquadRole,
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
        and requested_weapon == WeaponKind.SNIPER
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
) -> bool:
    return held_weapon == WeaponKind.SNIPER and cooldown_ready(cooldown_remaining)


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
        random_source: Optional[RandomSource] = None,
    ) -> GroundEncounter:
        from .entities import CrewMember, GroundEncounter

        source = random_source or random
        count = source.randint(self.minimum, self.maximum)
        members = []
        for index in range(count):
            role = (
                SquadRole.COVER_SHOOTER
                if index % 2 == 0
                else SquadRole.ADVANCE_SHOOTER
            )
            members.append(
                CrewMember(
                    id=f"{aircraft_id}-crew-{index + 1}",
                    encounter_id=f"encounter:{aircraft_id}",
                    cover_node=config.COVER_NODES[index % len(config.COVER_NODES)],
                    squad_role=role,
                    behavior_state=CrewBehaviorState.IN_COVER,
                )
            )
        return GroundEncounter(
            aircraft_id=aircraft_id,
            crew=members,
            crew_count=count,
        )


def advance_crew_behavior(
    encounter: GroundEncounter,
    delta_seconds: float,
    interval_seconds: float = CREW_ADVANCE_INTERVAL_SECONDS,
) -> None:
    """Advance only the predefined squad route; cover shooters hold position."""

    for member in encounter.crew:
        if not member.alive:
            continue
        if member.squad_role == SquadRole.COVER_SHOOTER:
            member.behavior_state = CrewBehaviorState.IN_COVER
            continue
        if member.behavior_state == CrewBehaviorState.ADVANCING:
            member.behavior_state = CrewBehaviorState.RELOCATING
            continue
        if member.behavior_state == CrewBehaviorState.RELOCATING:
            member.behavior_state = CrewBehaviorState.IN_COVER
            continue
        member.advance_elapsed += max(0.0, delta_seconds)
        if member.advance_elapsed < interval_seconds:
            member.behavior_state = CrewBehaviorState.IN_COVER
            continue
        member.advance_elapsed = 0.0
        member.cover_node = member.next_cover_node()
        member.behavior_state = CrewBehaviorState.ADVANCING


def defeat_crew_member(
    encounter: GroundEncounter,
    crew_id: str,
    session: Optional[GameSession] = None,
) -> bool:
    """Apply one valid sniper hit and count it once."""

    member = encounter.find(crew_id)
    if member is None or not member.alive:
        return False
    member.alive = False
    member.behavior_state = CrewBehaviorState.IN_COVER
    if session is not None:
        session.stats.record_once(f"enemy-defeated:{crew_id}", "enemy_defeated")
    encounter.refresh_cleared()
    return True


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
