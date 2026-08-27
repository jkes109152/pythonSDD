"""Engine-independent state, enums and guarded session transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import PLAYER_MAX_HEALTH


class GamePhase(str, Enum):
    MAIN_MENU = "MAIN_MENU"
    AIRSTRIKE = "AIRSTRIKE"
    GROUND_COMBAT = "GROUND_COMBAT"
    GAME_OVER = "GAME_OVER"


class LockState(str, Enum):
    WHITE = "WHITE"
    RED_TRACKING = "RED_TRACKING"
    GREEN_READY = "GREEN_READY"


class FailureReason(str, Enum):
    BUILDING_IMPACT = "BUILDING_IMPACT"
    PLAYER_DEAD = "PLAYER_DEAD"


class WeaponKind(str, Enum):
    ANTI_AIRCRAFT = "ANTI_AIRCRAFT"
    SNIPER = "SNIPER"


class AircraftPhase(str, Enum):
    APPROACHING = "APPROACHING"
    LOCKED = "LOCKED"
    DESTROYED = "DESTROYED"
    IMPACTED = "IMPACTED"


class SquadRole(str, Enum):
    COVER_SHOOTER = "COVER_SHOOTER"
    ADVANCE_SHOOTER = "ADVANCE_SHOOTER"


class CrewBehaviorState(str, Enum):
    IN_COVER = "IN_COVER"
    ADVANCING = "ADVANCING"
    RELOCATING = "RELOCATING"


class SessionEvent(str, Enum):
    START_GAME = "START_GAME"
    AIRCRAFT_DESTROYED = "AIRCRAFT_DESTROYED"
    BUILDING_IMPACT = "BUILDING_IMPACT"
    CREW_CLEARED = "CREW_CLEARED"
    PLAYER_DIED = "PLAYER_DIED"
    RETURN_TO_MENU = "RETURN_TO_MENU"


@dataclass
class SessionStats:
    """Counters whose updates are protected from repeated engine callbacks."""

    survival_seconds: float = 0.0
    aircraft_destroyed: int = 0
    enemies_defeated: int = 0
    failure_reason: Optional[FailureReason] = None
    _recorded_events: set[str] = field(default_factory=set, repr=False)

    def record_once(self, event_id: str, event_type: str) -> bool:
        if event_id in self._recorded_events:
            return False
        self._recorded_events.add(event_id)
        if event_type == "aircraft_destroyed":
            self.aircraft_destroyed += 1
        elif event_type == "enemy_defeated":
            self.enemies_defeated += 1
        elif event_type == "building_impact":
            self.failure_reason = FailureReason.BUILDING_IMPACT
        elif event_type == "player_dead":
            self.failure_reason = FailureReason.PLAYER_DEAD
        return True

    def tick(self, delta_seconds: float) -> None:
        self.survival_seconds += max(0.0, delta_seconds)

    def snapshot(self) -> dict[str, object]:
        return {
            "survival_seconds": self.survival_seconds,
            "aircraft_destroyed": self.aircraft_destroyed,
            "enemies_defeated": self.enemies_defeated,
            "failure_reason": self.failure_reason,
        }

    def reset(self) -> None:
        self.survival_seconds = 0.0
        self.aircraft_destroyed = 0
        self.enemies_defeated = 0
        self.failure_reason = None
        self._recorded_events.clear()


@dataclass
class GameSession:
    """Small explicit state machine for one endless game session."""

    phase: GamePhase = GamePhase.MAIN_MENU
    health: int = PLAYER_MAX_HEALTH
    max_health: int = PLAYER_MAX_HEALTH
    held_weapon: Optional[WeaponKind] = None
    lock_state: LockState = LockState.WHITE
    lock_elapsed: float = 0.0
    active_aircraft_id: Optional[str] = None
    active_encounter_id: Optional[str] = None
    aircraft_sequence: int = 0
    stats: SessionStats = field(default_factory=SessionStats)
    _processed_events: set[str] = field(default_factory=set, repr=False)

    def start_new_game(self) -> GamePhase:
        self.phase = GamePhase.AIRSTRIKE
        self.health = self.max_health
        self.held_weapon = None
        self.lock_state = LockState.WHITE
        self.lock_elapsed = 0.0
        self.active_encounter_id = None
        self.aircraft_sequence = 1
        self.active_aircraft_id = self._aircraft_id(self.aircraft_sequence)
        self.stats.reset()
        self._processed_events.clear()
        return self.phase

    def transition(
        self,
        event: SessionEvent | str,
        *,
        event_id: Optional[str] = None,
        aircraft_id: Optional[str] = None,
        encounter_id: Optional[str] = None,
    ) -> GamePhase:
        event = SessionEvent(event)
        if event == SessionEvent.START_GAME:
            if self.phase == GamePhase.MAIN_MENU:
                return self.start_new_game()
            return self.phase

        if event == SessionEvent.RETURN_TO_MENU:
            if self.phase == GamePhase.GAME_OVER:
                self._reset_to_menu()
            return self.phase

        if self.phase == GamePhase.GAME_OVER:
            return self.phase

        if event == SessionEvent.AIRCRAFT_DESTROYED:
            if self.phase != GamePhase.AIRSTRIKE:
                return self.phase
            if (
                aircraft_id is not None
                and self.active_aircraft_id is not None
                and aircraft_id != self.active_aircraft_id
            ):
                return self.phase
            target_id = aircraft_id or self.active_aircraft_id or "unknown-aircraft"
            key = event_id or f"aircraft-destroyed:{target_id}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.stats.record_once(key, "aircraft_destroyed")
            self.active_encounter_id = f"encounter:{target_id}"
            self.lock_state = LockState.WHITE
            self.lock_elapsed = 0.0
            self.phase = GamePhase.GROUND_COMBAT
            return self.phase

        if event == SessionEvent.BUILDING_IMPACT:
            if self.phase != GamePhase.AIRSTRIKE:
                return self.phase
            if (
                aircraft_id is not None
                and self.active_aircraft_id is not None
                and aircraft_id != self.active_aircraft_id
            ):
                return self.phase
            key = event_id or f"building-impact:{self.active_aircraft_id or 'unknown-aircraft'}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.stats.record_once(key, "building_impact")
            self.phase = GamePhase.GAME_OVER
            return self.phase

        if event == SessionEvent.CREW_CLEARED:
            if self.phase != GamePhase.GROUND_COMBAT:
                return self.phase
            if (
                encounter_id is not None
                and self.active_encounter_id is not None
                and encounter_id != self.active_encounter_id
            ):
                return self.phase
            current_id = encounter_id or self.active_encounter_id or "unknown-encounter"
            key = event_id or f"crew-cleared:{current_id}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.active_encounter_id = None
            self.aircraft_sequence += 1
            self.active_aircraft_id = self._aircraft_id(self.aircraft_sequence)
            self.phase = GamePhase.AIRSTRIKE
            return self.phase

        if event == SessionEvent.PLAYER_DIED:
            if self.phase not in (GamePhase.AIRSTRIKE, GamePhase.GROUND_COMBAT):
                return self.phase
            key = event_id or "player-died"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.health = 0
            self.stats.record_once(key, "player_dead")
            self.phase = GamePhase.GAME_OVER
            return self.phase

        return self.phase

    def take_damage(self, amount: int) -> bool:
        if self.phase not in (GamePhase.AIRSTRIKE, GamePhase.GROUND_COMBAT):
            return False
        self.health = max(0, self.health - max(0, amount))
        if self.health == 0:
            self.transition(SessionEvent.PLAYER_DIED)
            return True
        return False

    def tick(self, delta_seconds: float) -> None:
        if self.phase in (GamePhase.AIRSTRIKE, GamePhase.GROUND_COMBAT):
            self.stats.tick(delta_seconds)

    def can_use_anti_air(self) -> bool:
        return self.phase == GamePhase.AIRSTRIKE and self.held_weapon == WeaponKind.ANTI_AIRCRAFT

    def _reset_to_menu(self) -> None:
        self.phase = GamePhase.MAIN_MENU
        self.health = self.max_health
        self.held_weapon = None
        self.lock_state = LockState.WHITE
        self.lock_elapsed = 0.0
        self.active_aircraft_id = None
        self.active_encounter_id = None
        self.aircraft_sequence = 0
        self.stats.reset()
        self._processed_events.clear()

    @staticmethod
    def _aircraft_id(sequence: int) -> str:
        return f"aircraft-{sequence:03d}"
