"""Engine-independent state, enums and guarded session transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import CITY_MAX_HEALTH, PLAYER_MAX_HEALTH


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
    CITY_DESTROYED = "CITY_DESTROYED"


class WeaponKind(str, Enum):
    ANTI_AIRCRAFT = "ANTI_AIRCRAFT"
    SNIPER = "SNIPER"
    PISTOL = "PISTOL"


class AircraftType(str, Enum):
    NORMAL = "NORMAL"
    MANPOWER_SUPPORT = "MANPOWER_SUPPORT"
    FAST = "FAST"
    ARMORED_BOSS = "ARMORED_BOSS"


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
    CITY_DESTROYED = "CITY_DESTROYED"
    RETURN_TO_MENU = "RETURN_TO_MENU"


@dataclass
class WaveProgress:
    """Mutable progress for one roster; the director owns roster creation."""

    wave_number: int = 1
    aircraft_index: int = 0
    aircraft_count: int = 2
    aircraft_cap: int = 6
    is_boss_wave: bool = False
    roster: tuple[AircraftType, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.wave_number = max(1, int(self.wave_number))
        self.aircraft_cap = max(1, int(self.aircraft_cap))
        requested_count = max(1, int(self.aircraft_count))
        if not self.roster:
            self.roster = tuple(AircraftType.NORMAL for _ in range(requested_count))
        self.roster = tuple(AircraftType(item) for item in self.roster)
        self.aircraft_count = len(self.roster)
        self.aircraft_index = max(0, min(int(self.aircraft_index), self.aircraft_count - 1))
        self.is_boss_wave = bool(self.is_boss_wave)

    @property
    def active_aircraft_type(self) -> AircraftType:
        return self.roster[self.aircraft_index]

    @property
    def is_last_aircraft(self) -> bool:
        return self.aircraft_index >= self.aircraft_count - 1

    def advance_aircraft(self) -> bool:
        """Move to the next roster slot and report whether one exists."""

        if self.is_last_aircraft:
            return False
        self.aircraft_index += 1
        return True


@dataclass(frozen=True)
class WavePlan:
    """Immutable roster returned by the deterministic wave director."""

    wave_number: int
    aircraft_count: int
    aircraft_cap: int
    is_boss_wave: bool
    roster: tuple[AircraftType, ...]

    def __post_init__(self) -> None:
        if self.wave_number < 1:
            raise ValueError("wave_number must be positive")
        if self.aircraft_count < 1:
            raise ValueError("aircraft_count must be positive")
        if len(self.roster) != self.aircraft_count:
            raise ValueError("roster length must match aircraft_count")

    def to_progress(self) -> WaveProgress:
        return WaveProgress(
            wave_number=self.wave_number,
            aircraft_index=0,
            aircraft_count=self.aircraft_count,
            aircraft_cap=self.aircraft_cap,
            is_boss_wave=self.is_boss_wave,
            roster=self.roster,
        )


@dataclass
class WaveRuntime:
    """Authoritative per-aircraft state for one simultaneous wave.

    ``Aircraft`` owns movement and health transitions.  This ledger is the
    controller-owned, ordered snapshot used by HUD aggregation and wave
    transitions, so a single destroyed aircraft cannot accidentally advance
    the whole wave.
    """

    wave: WaveProgress
    aircraft_ids: tuple[str, ...]
    aircraft_statuses: dict[str, AircraftPhase] = field(default_factory=dict)
    aircraft_types: dict[str, AircraftType] = field(default_factory=dict)
    active_target_id: Optional[str] = None
    ground_encounter_id: Optional[str] = None

    def __post_init__(self) -> None:
        self.aircraft_ids = tuple(str(aircraft_id) for aircraft_id in self.aircraft_ids)
        if not self.aircraft_ids:
            raise ValueError("aircraft_ids must not be empty")
        if len(set(self.aircraft_ids)) != len(self.aircraft_ids):
            raise ValueError("aircraft_ids must be unique")
        if len(self.aircraft_ids) != self.wave.aircraft_count:
            raise ValueError("aircraft_ids length must match wave aircraft_count")

        default_types = dict(zip(self.aircraft_ids, self.wave.roster))
        if not self.aircraft_types:
            self.aircraft_types = default_types
        else:
            self.aircraft_types = {
                str(aircraft_id): AircraftType(aircraft_type)
                for aircraft_id, aircraft_type in self.aircraft_types.items()
            }
        if set(self.aircraft_types) != set(self.aircraft_ids):
            raise ValueError("aircraft_types keys must match aircraft_ids")

        if not self.aircraft_statuses:
            self.aircraft_statuses = {
                aircraft_id: AircraftPhase.APPROACHING
                for aircraft_id in self.aircraft_ids
            }
        else:
            self.aircraft_statuses = {
                str(aircraft_id): AircraftPhase(phase)
                for aircraft_id, phase in self.aircraft_statuses.items()
            }
        if set(self.aircraft_statuses) != set(self.aircraft_ids):
            raise ValueError("aircraft_statuses keys must match aircraft_ids")
        if self.active_target_id is not None and self.active_target_id not in self.aircraft_ids:
            raise ValueError("active_target_id must belong to aircraft_ids")

    @property
    def alive_aircraft_ids(self) -> tuple[str, ...]:
        return tuple(
            aircraft_id
            for aircraft_id in self.aircraft_ids
            if self.aircraft_statuses[aircraft_id]
            in (AircraftPhase.APPROACHING, AircraftPhase.LOCKED)
        )

    @property
    def remaining_aircraft_count(self) -> int:
        return len(self.alive_aircraft_ids)

    @property
    def alive_ratio(self) -> float:
        return self.remaining_aircraft_count / float(len(self.aircraft_ids))

    @property
    def all_aircraft_destroyed(self) -> bool:
        return bool(self.aircraft_ids) and all(
            self.aircraft_statuses[aircraft_id] == AircraftPhase.DESTROYED
            for aircraft_id in self.aircraft_ids
        )

    def sync_aircraft_phase(
        self,
        aircraft_id: str,
        phase: AircraftPhase,
    ) -> bool:
        """Mirror one entity transition, rejecting stale or regressive IDs."""

        aircraft_id = str(aircraft_id)
        if aircraft_id not in self.aircraft_statuses:
            return False
        phase = AircraftPhase(phase)
        current = self.aircraft_statuses[aircraft_id]
        if current in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
            return False
        if phase == AircraftPhase.APPROACHING and current == AircraftPhase.LOCKED:
            return False
        if phase not in (
            AircraftPhase.APPROACHING,
            AircraftPhase.LOCKED,
            AircraftPhase.DESTROYED,
            AircraftPhase.IMPACTED,
        ):
            return False
        if current == phase:
            return False
        self.aircraft_statuses[aircraft_id] = phase
        if self.active_target_id == aircraft_id and phase in (
            AircraftPhase.DESTROYED,
            AircraftPhase.IMPACTED,
        ):
            self.active_target_id = None
        return True

    def mark_destroyed(self, aircraft_id: str) -> bool:
        return self.sync_aircraft_phase(aircraft_id, AircraftPhase.DESTROYED)

    def mark_impacted(self, aircraft_id: str) -> bool:
        return self.sync_aircraft_phase(aircraft_id, AircraftPhase.IMPACTED)

    def set_active_target(self, aircraft_id: Optional[str]) -> None:
        if aircraft_id is not None and aircraft_id not in self.aircraft_ids:
            raise ValueError("active target must belong to this wave")
        self.active_target_id = aircraft_id


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
        elif event_type == "city_destroyed":
            self.failure_reason = FailureReason.CITY_DESTROYED
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
    anti_air_scope_enabled: bool = False
    target_in_zone: bool = False
    active_missile_ids: set[str] = field(default_factory=set)
    active_aircraft_id: Optional[str] = None
    active_encounter_id: Optional[str] = None
    aircraft_sequence: int = 0
    wave: WaveProgress = field(default_factory=WaveProgress)
    active_aircraft_type: Optional[AircraftType] = None
    city_health: float = CITY_MAX_HEALTH
    max_city_health: float = CITY_MAX_HEALTH
    stats: SessionStats = field(default_factory=SessionStats)
    wave_runtime: Optional[WaveRuntime] = None
    _processed_events: set[str] = field(default_factory=set, repr=False)

    def start_new_game(self, wave_plan: Optional["WavePlan"] = None) -> GamePhase:
        self.phase = GamePhase.AIRSTRIKE
        self.health = self.max_health
        self.held_weapon = None
        self.reset_airstrike_guidance()
        self.active_encounter_id = None
        self.city_health = self.max_city_health
        self.wave = wave_plan.to_progress() if wave_plan is not None else WaveProgress()
        self.wave_runtime = None
        self.aircraft_sequence = 1
        self.active_aircraft_id = self._aircraft_id(self.aircraft_sequence)
        self.active_aircraft_type = self.wave.active_aircraft_type
        self.stats.reset()
        self._processed_events.clear()
        return self.phase

    def initialize_wave_runtime(
        self,
        aircraft_ids: tuple[str, ...],
        aircraft_types: Optional[dict[str, AircraftType]] = None,
    ) -> WaveRuntime:
        """Create the authoritative simultaneous-wave ledger.

        This is deliberately separate from ``start_new_game`` so legacy
        callers that use the scalar transition API keep their old behavior.
        The graphical controller opts into the keyed runtime immediately
        after it has generated deterministic IDs for the roster.
        """

        self.wave_runtime = WaveRuntime(
            wave=self.wave,
            aircraft_ids=aircraft_ids,
            aircraft_types=aircraft_types or dict(
                zip(aircraft_ids, self.wave.roster)
            ),
        )
        self.active_aircraft_id = aircraft_ids[0]
        self.active_aircraft_type = self.wave_runtime.aircraft_types[aircraft_ids[0]]
        return self.wave_runtime

    def sync_aircraft_phase(self, aircraft_id: str, phase: AircraftPhase) -> bool:
        if self.wave_runtime is None:
            return False
        changed = self.wave_runtime.sync_aircraft_phase(aircraft_id, phase)
        if self.wave_runtime.active_target_id is None:
            self.active_aircraft_id = (
                self.active_aircraft_id
                if self.active_aircraft_id in self.wave_runtime.alive_aircraft_ids
                else (self.wave_runtime.alive_aircraft_ids[0]
                      if self.wave_runtime.alive_aircraft_ids else None)
            )
        return changed

    def mark_aircraft_destroyed(self, aircraft_id: str) -> bool:
        if self.wave_runtime is None:
            return False
        changed = self.wave_runtime.mark_destroyed(aircraft_id)
        if changed:
            key = f"aircraft-destroyed:{aircraft_id}"
            self.stats.record_once(key, "aircraft_destroyed")
            self.active_aircraft_id = (
                self.wave_runtime.alive_aircraft_ids[0]
                if self.wave_runtime.alive_aircraft_ids
                else None
            )
            self.active_aircraft_type = (
                self.wave_runtime.aircraft_types[self.active_aircraft_id]
                if self.active_aircraft_id is not None
                else None
            )
        return changed

    def mark_aircraft_impacted(self, aircraft_id: str) -> bool:
        if self.wave_runtime is None:
            return False
        changed = self.wave_runtime.mark_impacted(aircraft_id)
        if changed and self.active_aircraft_id == aircraft_id:
            self.active_aircraft_id = None
            self.active_aircraft_type = None
        return changed

    def set_active_target(self, aircraft_id: Optional[str]) -> None:
        if self.wave_runtime is not None:
            self.wave_runtime.set_active_target(aircraft_id)
        self.active_aircraft_id = aircraft_id
        self.active_aircraft_type = (
            self.wave_runtime.aircraft_types[aircraft_id]
            if self.wave_runtime is not None and aircraft_id is not None
            else None
        )

    def transition(
        self,
        event: SessionEvent | str,
        *,
        event_id: Optional[str] = None,
        aircraft_id: Optional[str] = None,
        encounter_id: Optional[str] = None,
        wave_plan: Optional["WavePlan"] = None,
    ) -> GamePhase:
        event = SessionEvent(event)
        if event == SessionEvent.START_GAME:
            if self.phase == GamePhase.MAIN_MENU:
                return self.start_new_game(wave_plan)
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
            if self.wave_runtime is not None:
                target_id = aircraft_id or self.wave_runtime.active_target_id or self.active_aircraft_id
                if target_id is None or target_id not in self.wave_runtime.aircraft_ids:
                    return self.phase
                key = event_id or f"aircraft-destroyed:{target_id}"
                if key in self._processed_events:
                    return self.phase
                if not self.wave_runtime.mark_destroyed(target_id):
                    return self.phase
                self._processed_events.add(key)
                self.stats.record_once(key, "aircraft_destroyed")
                self.wave_runtime.set_active_target(None)
                if self.wave_runtime.all_aircraft_destroyed:
                    self.active_encounter_id = (
                        self.wave_runtime.ground_encounter_id
                        or f"encounter:wave-{self.wave.wave_number}"
                    )
                    self.wave_runtime.ground_encounter_id = self.active_encounter_id
                    self.active_aircraft_id = None
                    self.active_aircraft_type = None
                    self.reset_airstrike_guidance()
                    self.phase = GamePhase.GROUND_COMBAT
                else:
                    self.active_aircraft_id = self.wave_runtime.alive_aircraft_ids[0]
                    self.active_aircraft_type = self.wave_runtime.aircraft_types[
                        self.active_aircraft_id
                    ]
                return self.phase
            if aircraft_id is not None and aircraft_id != self.active_aircraft_id:
                return self.phase
            target_id = aircraft_id or self.active_aircraft_id or "unknown-aircraft"
            key = event_id or f"aircraft-destroyed:{target_id}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.stats.record_once(key, "aircraft_destroyed")
            self.active_encounter_id = f"encounter:{target_id}"
            self.reset_airstrike_guidance()
            self.phase = GamePhase.GROUND_COMBAT
            return self.phase

        if event == SessionEvent.BUILDING_IMPACT:
            if self.phase != GamePhase.AIRSTRIKE:
                return self.phase
            if self.wave_runtime is not None:
                target_id = aircraft_id or self.active_aircraft_id
                if target_id is None or target_id not in self.wave_runtime.aircraft_ids:
                    return self.phase
                key = event_id or f"building-impact:{target_id}"
                if key in self._processed_events:
                    return self.phase
                if not self.wave_runtime.mark_impacted(target_id):
                    return self.phase
                self._processed_events.add(key)
                self.stats.record_once(key, "building_impact")
                self.reset_airstrike_guidance()
                self.phase = GamePhase.GAME_OVER
                return self.phase
            if aircraft_id is not None and aircraft_id != self.active_aircraft_id:
                return self.phase
            key = event_id or f"building-impact:{self.active_aircraft_id or 'unknown-aircraft'}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.stats.record_once(key, "building_impact")
            self.reset_airstrike_guidance()
            self.phase = GamePhase.GAME_OVER
            return self.phase

        if event == SessionEvent.CREW_CLEARED:
            if self.phase != GamePhase.GROUND_COMBAT:
                return self.phase
            if self.wave_runtime is not None:
                current_id = encounter_id or self.active_encounter_id
                if (
                    current_id is None
                    or self.wave_runtime.ground_encounter_id not in (None, current_id)
                ):
                    return self.phase
                key = event_id or f"crew-cleared:{current_id}"
                if key in self._processed_events:
                    return self.phase
                self._processed_events.add(key)
                next_wave = (
                    wave_plan.to_progress()
                    if wave_plan is not None
                    else WaveProgress(
                        wave_number=self.wave.wave_number + 1,
                        aircraft_count=self.wave.aircraft_count + 1,
                        aircraft_cap=(
                            self.wave.aircraft_cap + 2
                            if self.wave.aircraft_count >= self.wave.aircraft_cap
                            else self.wave.aircraft_cap
                        ),
                        is_boss_wave=(self.wave.wave_number + 1) % 10 == 0,
                        roster=tuple(
                            AircraftType.NORMAL
                            for _ in range(self.wave.aircraft_count + 1)
                        ),
                    )
                )
                self.wave = next_wave
                self.wave_runtime = None
                self.active_encounter_id = None
                self.aircraft_sequence += 1
                base_id = self._aircraft_id(self.aircraft_sequence)
                ids = tuple(
                    base_id if index == 0 else f"{base_id}-{index + 1:02d}"
                    for index in range(next_wave.aircraft_count)
                )
                self.initialize_wave_runtime(ids, dict(zip(ids, next_wave.roster)))
                self.reset_airstrike_guidance()
                self.phase = GamePhase.AIRSTRIKE
                return self.phase
            if encounter_id is not None and encounter_id != self.active_encounter_id:
                return self.phase
            current_id = encounter_id or self.active_encounter_id or "unknown-encounter"
            key = event_id or f"crew-cleared:{current_id}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.active_encounter_id = None
            if self.wave.advance_aircraft():
                pass
            elif wave_plan is not None:
                self.wave = wave_plan.to_progress()
            else:
                next_count = self.wave.aircraft_count + 1
                next_cap = self.wave.aircraft_cap + 2 if self.wave.aircraft_count >= self.wave.aircraft_cap else self.wave.aircraft_cap
                self.wave = WaveProgress(
                    wave_number=self.wave.wave_number + 1,
                    aircraft_count=next_count,
                    aircraft_cap=next_cap,
                    is_boss_wave=(self.wave.wave_number + 1) % 10 == 0,
                    roster=tuple(AircraftType.NORMAL for _ in range(next_count)),
                )
            self.aircraft_sequence += 1
            self.active_aircraft_id = self._aircraft_id(self.aircraft_sequence)
            self.active_aircraft_type = self.wave.active_aircraft_type
            self.reset_airstrike_guidance()
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
            self.reset_airstrike_guidance()
            self.phase = GamePhase.GAME_OVER
            return self.phase

        if event == SessionEvent.CITY_DESTROYED:
            if self.phase != GamePhase.GROUND_COMBAT:
                return self.phase
            key = event_id or "city-destroyed"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.city_health = 0.0
            self.stats.record_once(key, "city_destroyed")
            self.reset_airstrike_guidance()
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

    def take_city_damage(self, amount: float) -> bool:
        """Apply city damage and transition once when its health reaches zero."""

        if self.phase != GamePhase.GROUND_COMBAT or amount <= 0:
            return False
        self.city_health = max(0.0, self.city_health - amount)
        if self.city_health <= 0.0:
            self.transition(SessionEvent.CITY_DESTROYED)
            return True
        return False

    def tick(self, delta_seconds: float) -> None:
        if self.phase in (GamePhase.AIRSTRIKE, GamePhase.GROUND_COMBAT):
            self.stats.tick(delta_seconds)

    def can_use_anti_air(self) -> bool:
        return self.phase == GamePhase.AIRSTRIKE and self.held_weapon == WeaponKind.ANTI_AIRCRAFT

    def set_anti_air_scope(self, enabled: bool) -> None:
        """Set the anti-air scope state; closing it clears lock progress immediately."""

        self.anti_air_scope_enabled = bool(enabled)
        if not self.anti_air_scope_enabled:
            self.lock_state = LockState.WHITE
            self.lock_elapsed = 0.0
            self.target_in_zone = False
            if self.wave_runtime is not None:
                self.wave_runtime.set_active_target(None)

    def reset_airstrike_guidance(self, *, clear_missiles: bool = True) -> None:
        """Clear transient lock/target/missile state at an airstrike boundary."""

        self.anti_air_scope_enabled = False
        self.target_in_zone = False
        self.lock_state = LockState.WHITE
        self.lock_elapsed = 0.0
        if self.wave_runtime is not None:
            self.wave_runtime.set_active_target(None)
        if clear_missiles:
            self.active_missile_ids.clear()

    def _reset_to_menu(self) -> None:
        self.phase = GamePhase.MAIN_MENU
        self.health = self.max_health
        self.held_weapon = None
        self.reset_airstrike_guidance()
        self.active_aircraft_id = None
        self.active_encounter_id = None
        self.aircraft_sequence = 0
        self.wave = WaveProgress()
        self.wave_runtime = None
        self.active_aircraft_type = None
        self.city_health = self.max_city_health
        self.stats.reset()
        self._processed_events.clear()

    @staticmethod
    def _aircraft_id(sequence: int) -> str:
        return f"aircraft-{sequence:03d}"
