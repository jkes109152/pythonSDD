"""Engine-independent state, enums and guarded session transitions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional
from uuid import uuid4

from .config import (
    AA_FIRE_COOLDOWN_SECONDS,
    AUTO_DEFENSE_TURRET_POSITIONS,
    CITY_MAX_HEALTH,
    PISTOL_FIRE_COOLDOWN_SECONDS,
    PISTOL_MAX_RANGE,
    SNIPER_FIRE_COOLDOWN_SECONDS,
    SNIPER_MAX_RANGE,
    LEGACY_COMPATIBILITY_WAVE_COUNT,
    PLAYER_MAX_HEALTH,
)
from .progression import (
    DEFAULT_CONFIG,
    LevelKey,
    LevelPlan,
    ProgressionConfig,
    RegenState,
    apply_damage,
    apply_rebirth,
    auto_defense_capacity,
    build_level_plan,
    calculate_rebirth_cost,
    calculate_reward,
    create_regen_state,
    effective_cooldown,
    effective_max_hp,
    next_level,
    purchase_upgrade,
    tick_regeneration,
)
from .save_data import SaveDeleteResult, SaveLoadResult, SaveProfile, SaveStore


class GamePhase(str, Enum):
    SAVE_SELECT = "SAVE_SELECT"
    MAIN_MENU = "MAIN_MENU"
    SHOP = "SHOP"
    AIRSTRIKE = "AIRSTRIKE"
    HYBRID_COMBAT = "HYBRID_COMBAT"
    GROUND_COMBAT = "GROUND_COMBAT"
    GAME_OVER = "GAME_OVER"
    VICTORY = "VICTORY"


class LockState(str, Enum):
    WHITE = "WHITE"
    RED_TRACKING = "RED_TRACKING"
    GREEN_READY = "GREEN_READY"


class AntiAirGuiMode(str, Enum):
    """主選單可選的防空瞄準介面；只影響 HUD，不改變規則。"""

    NEW = "NEW"
    LEGACY = "LEGACY"


class FailureReason(str, Enum):
    BUILDING_IMPACT = "BUILDING_IMPACT"
    PLAYER_DEAD = "PLAYER_DEAD"
    CITY_DESTROYED = "CITY_DESTROYED"


class WeaponKind(str, Enum):
    ANTI_AIRCRAFT = "ANTI_AIRCRAFT"
    SNIPER = "SNIPER"
    PISTOL = "PISTOL"
    RPG = "RPG"
    MULTI_ANTI_AIRCRAFT = "MULTI_ANTI_AIRCRAFT"
    MULTI_AA = "MULTI_ANTI_AIRCRAFT"


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
    DESCENDING = "DESCENDING"


class SessionEvent(str, Enum):
    SELECT_SAVE = "SELECT_SAVE"
    START_GAME = "START_GAME"
    OPEN_SHOP = "OPEN_SHOP"
    PURCHASE_UPGRADE = "PURCHASE_UPGRADE"
    REBIRTH = "REBIRTH"
    AIRCRAFT_DESTROYED = "AIRCRAFT_DESTROYED"
    DROP_STARTED = "DROP_STARTED"
    BUILDING_IMPACT = "BUILDING_IMPACT"
    CREW_CLEARED = "CREW_CLEARED"
    WAVE_CLEARED = "WAVE_CLEARED"
    VICTORY = "VICTORY"
    PLAYER_DIED = "PLAYER_DIED"
    CITY_DESTROYED = "CITY_DESTROYED"
    RETURN_TO_MENU = "RETURN_TO_MENU"


@dataclass
class WeaponRuntime:
    """單一小關內的暫時武器狀態。"""

    weapon_kind: WeaponKind
    ammo_remaining: Optional[int] = None
    cooldown_remaining: float = 0.0
    cooldown_duration: float = 0.0
    range: float = 0.0
    damage: int = 0
    scope_enabled: bool = False

    def __post_init__(self) -> None:
        self.weapon_kind = WeaponKind(self.weapon_kind)
        if self.ammo_remaining is not None:
            self.ammo_remaining = max(0, int(self.ammo_remaining))
        self.cooldown_remaining = max(0.0, float(self.cooldown_remaining))
        self.cooldown_duration = max(0.0, float(self.cooldown_duration))
        self.range = max(0.0, float(self.range))
        self.damage = max(0, int(self.damage))
        self.scope_enabled = bool(self.scope_enabled)

    @property
    def can_fire(self) -> bool:
        return self.cooldown_remaining <= 0.0 and (
            self.ammo_remaining is None or self.ammo_remaining > 0
        )

    def mark_fired(self, cooldown_seconds: Optional[float] = None) -> bool:
        if not self.can_fire:
            return False
        if self.ammo_remaining is not None:
            self.ammo_remaining -= 1
        if cooldown_seconds is None:
            cooldown_seconds = self.cooldown_duration
        self.cooldown_remaining = max(0.0, float(cooldown_seconds))
        return True

    def tick(self, delta_seconds: float) -> None:
        self.cooldown_remaining = max(
            0.0, self.cooldown_remaining - max(0.0, float(delta_seconds))
        )


@dataclass(frozen=True)
class RewardSettlement:
    """一次小關獎勵的冪等結算結果。"""

    attempt_id: str
    level_key: LevelKey
    raw_reward: int
    rebirth_multiplier: float
    awarded_coins: int
    settled: bool = True

    @property
    def ok(self) -> bool:
        return self.settled


@dataclass(frozen=True)
class PurchaseSettlement:
    """一次商店操作的冪等結果。"""

    operation_id: str
    upgrade_id: str
    success: bool
    profile: SaveProfile
    price: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success


@dataclass(frozen=True)
class RebirthSettlement:
    """一次重生操作的冪等結果。"""

    operation_id: str
    success: bool
    profile: SaveProfile
    cost: int
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success


@dataclass
class SessionProgress:
    """目前程式執行期間的選檔與下一個小關指標。"""

    selected_slot_id: Optional[int] = None
    next_play_level: LevelKey = field(default_factory=lambda: LevelKey(1, 1))
    last_reward_settlement: Optional[RewardSettlement] = None

    def reset_level(self) -> None:
        self.next_play_level = LevelKey(1, 1)


@dataclass
class RunState:
    """單次小關嘗試的暫時狀態，不會寫入 SaveProfile。"""

    attempt_id: str
    level: LevelKey
    phase: GamePhase
    current_hp: float
    effective_max_hp: int
    city_health: float = CITY_MAX_HEALTH
    max_city_health: float = CITY_MAX_HEALTH
    aircrafts: dict[str, Any] = field(default_factory=dict)
    ground_encounter: Any = None
    weapon_runtime: dict[WeaponKind, WeaponRuntime] = field(default_factory=dict)
    turrets: list[Any] = field(default_factory=list)
    selected_weapon: WeaponKind = WeaponKind.ANTI_AIRCRAFT
    regen: Optional[RegenState] = None
    reward_settled: bool = False
    level_plan: Optional[LevelPlan] = None

    def __post_init__(self) -> None:
        self.attempt_id = str(self.attempt_id)
        self.level = LevelKey.parse(self.level)
        self.phase = GamePhase(self.phase)
        self.effective_max_hp = max(1, int(self.effective_max_hp))
        self.current_hp = min(
            float(self.effective_max_hp), max(0.0, float(self.current_hp))
        )
        self.city_health = min(
            float(self.max_city_health), max(0.0, float(self.city_health))
        )
        self.max_city_health = max(1.0, float(self.max_city_health))
        self.selected_weapon = WeaponKind(self.selected_weapon)
        if self.regen is None:
            self.regen = create_regen_state(self.effective_max_hp)
        self.reward_settled = bool(self.reward_settled)


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
        wave_number = int(self.wave_number)
        aircraft_count = int(self.aircraft_count)
        aircraft_cap = int(self.aircraft_cap)
        if not 1 <= wave_number <= LEGACY_COMPATIBILITY_WAVE_COUNT:
            raise ValueError(
                f"wave_number must be between 1 and {LEGACY_COMPATIBILITY_WAVE_COUNT}"
            )
        if aircraft_count < 1:
            raise ValueError("aircraft_count must be positive")
        if aircraft_cap < aircraft_count:
            raise ValueError("aircraft_cap must be at least aircraft_count")
        roster = tuple(AircraftType(item) for item in self.roster)
        if len(roster) != aircraft_count:
            raise ValueError("roster length must match aircraft_count")
        object.__setattr__(self, "wave_number", wave_number)
        object.__setattr__(self, "aircraft_count", aircraft_count)
        object.__setattr__(self, "aircraft_cap", aircraft_cap)
        object.__setattr__(self, "is_boss_wave", bool(self.is_boss_wave))
        object.__setattr__(self, "roster", roster)

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
    drop_spawned_aircraft_ids: set[str] = field(default_factory=set)
    hybrid_started: bool = False

    def __post_init__(self) -> None:
        self.aircraft_ids = tuple(str(aircraft_id) for aircraft_id in self.aircraft_ids)
        if not self.aircraft_ids:
            raise ValueError("aircraft_ids must not be empty")
        if len(set(self.aircraft_ids)) != len(self.aircraft_ids):
            raise ValueError("aircraft_ids must be unique")
        if len(self.aircraft_ids) != self.wave.aircraft_count:
            raise ValueError("aircraft_ids length must match wave aircraft_count")
        if self.active_target_id is not None:
            self.active_target_id = str(self.active_target_id)
        if self.ground_encounter_id is not None:
            self.ground_encounter_id = str(self.ground_encounter_id)

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
        self.drop_spawned_aircraft_ids = {
            str(aircraft_id) for aircraft_id in self.drop_spawned_aircraft_ids
        }
        if not self.drop_spawned_aircraft_ids.issubset(set(self.aircraft_ids)):
            raise ValueError("drop source IDs must belong to aircraft_ids")
        self.hybrid_started = bool(self.hybrid_started)

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

    @property
    def has_active_drop(self) -> bool:
        return self.hybrid_started or self.ground_encounter_id is not None

    @property
    def all_drop_decisions_processed(self) -> bool:
        """Return whether every destroyed source has had its drop resolved."""

        return self.drop_spawned_aircraft_ids == set(self.aircraft_ids)

    def mark_drop_spawned(self, aircraft_id: str) -> bool:
        """Record one source decision, including an intentionally empty batch."""

        aircraft_id = str(aircraft_id)
        if (
            aircraft_id not in self.aircraft_ids
            or self.aircraft_statuses[aircraft_id] != AircraftPhase.DESTROYED
            or aircraft_id in self.drop_spawned_aircraft_ids
        ):
            return False
        self.drop_spawned_aircraft_ids.add(aircraft_id)
        return True

    def start_hybrid_drop(self) -> bool:
        """Mark the first non-empty drop without resetting later source batches."""

        if self.hybrid_started:
            return False
        self.hybrid_started = True
        return True

    def can_complete_wave(self, ground_cleared: bool) -> bool:
        return (
            self.all_aircraft_destroyed
            and self.all_drop_decisions_processed
            and bool(ground_cleared)
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
    """Small explicit state machine for one finite campaign session."""

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
    # 006 的永久／暫時資料邊界。profile 為 None 時保留舊版純戰鬥 API，
    # 讓既有下降與混合戰鬥測試可以逐步遷移。
    profile: Optional[SaveProfile] = None
    session_progress: SessionProgress = field(default_factory=SessionProgress)
    run_state: Optional[RunState] = None
    save_store: Optional[SaveStore] = None
    progression_config: ProgressionConfig = field(default=DEFAULT_CONFIG, repr=False)
    _purchase_settlements: dict[str, PurchaseSettlement] = field(
        default_factory=dict, repr=False
    )
    _rebirth_settlements: dict[str, RebirthSettlement] = field(
        default_factory=dict, repr=False
    )
    _processed_events: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        if self.save_store is not None:
            self.progression_config = self.save_store.config
        if self.profile is not None:
            self.progression_config = self.profile.config
            self._sync_profile_boundary()

    # ------------------------------------------------------------------
    # 006 永久 Profile／單小關 RunState 邊界
    # ------------------------------------------------------------------
    def select_save_slot(
        self,
        slot_id: int,
        *,
        store: Optional[SaveStore] = None,
    ) -> SaveLoadResult:
        """載入一個存檔並停留在該存檔主選單，不自動開始戰鬥。"""

        if store is not None:
            self.save_store = store
        if self.save_store is None:
            self.save_store = SaveStore()
        self.progression_config = self.save_store.config
        result = self.save_store.load_slot(slot_id)
        self.profile = result.profile
        self.progression_config = self.profile.config
        self.session_progress = SessionProgress(
            selected_slot_id=result.slot_id,
            next_play_level=LevelKey(1, 1),
        )
        self._purchase_settlements.clear()
        self._rebirth_settlements.clear()
        self.run_state = None
        self._clear_transient_to_menu()
        self.phase = GamePhase.MAIN_MENU
        self._sync_profile_boundary()
        return result

    def start_sublevel(
        self,
        profile: Optional[SaveProfile] = None,
        level_key: Optional[LevelKey | str | tuple[int, int]] = None,
    ) -> RunState:
        """建立一個新的 a-b 小關與所有本局暫時資料。"""

        if self.run_state is not None or self.phase != GamePhase.MAIN_MENU:
            raise ValueError("只能從個人主選單開始新的小關")
        if profile is not None:
            self.profile = profile
        if self.profile is None:
            self.profile = SaveProfile.default(config=self.progression_config)
        self.progression_config = self.profile.config
        self._sync_profile_boundary()
        # 最近一次結算只服務尚未開始下一小關前的重複 callback；新的
        # attempt 建立後，舊 attempt_id 一律失效。
        self.session_progress.last_reward_settlement = None
        maximum = self.profile.max_aircraft_count
        key = LevelKey.parse(level_key or self.session_progress.next_play_level)
        plan = build_level_plan(
            key,
            maximum,
            config=self.progression_config,
        )
        attempt_id = str(uuid4())
        aircrafts: dict[str, dict[str, Any]] = {}
        type_map = {
            "普": AircraftType.NORMAL,
            "特": AircraftType.MANPOWER_SUPPORT,
            "魔": AircraftType.ARMORED_BOSS,
        }
        for index, token in enumerate(plan.roster, start=1):
            aircraft_id = f"aircraft-{key.a}-{key.b}-{index:02d}"
            aircrafts[aircraft_id] = {
                "id": aircraft_id,
                "token": token,
                "aircraft_type": type_map[token],
                "phase": AircraftPhase.APPROACHING,
                "alive": True,
                "is_boss": token == "魔",
            }

        runtimes = self._create_weapon_runtimes()
        selected = self._first_unlocked_weapon()
        turrets: list[Any] = []
        if auto_defense_capacity(
            self.profile,
            config=self.progression_config,
        ) > 0:
            from .entities import AutoDefenseTurret

            turrets = [
                AutoDefenseTurret(
                    id=f"turret-{index + 1:02d}",
                    position=position,
                    cooldown_seconds=effective_cooldown(
                        self.progression_config.auto_defense_cooldown_seconds,
                        self.profile,
                        config=self.progression_config,
                    ),
                    damage=self.progression_config.auto_defense_damage,
                )
                for index, position in enumerate(
                    AUTO_DEFENSE_TURRET_POSITIONS[
                        : auto_defense_capacity(
                            self.profile,
                            config=self.progression_config,
                        )
                    ]
                )
            ]
        run = RunState(
            attempt_id=attempt_id,
            level=key,
            phase=GamePhase.AIRSTRIKE,
            current_hp=float(self.max_health),
            effective_max_hp=self.max_health,
            city_health=self.max_city_health,
            max_city_health=self.max_city_health,
            aircrafts=aircrafts,
            weapon_runtime=runtimes,
            turrets=turrets,
            selected_weapon=selected,
            regen=create_regen_state(
                self.max_health,
                config=self.progression_config,
            ),
            level_plan=plan,
        )
        self.run_state = run
        self.phase = GamePhase.AIRSTRIKE
        run.phase = self.phase
        self.health = self.max_health
        self.max_health = run.effective_max_hp
        self.held_weapon = selected
        self.city_health = self.max_city_health
        self.reset_airstrike_guidance()
        self.stats.reset()
        self._processed_events.clear()
        # 舊場景仍會讀取 wave/wave_runtime；這裡同步一份相容快照，新的
        # 完成與重置判定則以 RunState 為準。
        legacy_roster = tuple(type_map[token] for token in plan.roster)
        self.wave = WaveProgress(
            wave_number=1,
            aircraft_index=0,
            aircraft_count=plan.aircraft_count,
            aircraft_cap=maximum,
            is_boss_wave=plan.is_boss_stage,
            roster=legacy_roster,
        )
        ids = tuple(aircrafts)
        self.aircraft_sequence = 1
        self.initialize_wave_runtime(ids, dict(zip(ids, legacy_roster)))
        self.active_aircraft_id = ids[0] if ids else None
        self.active_aircraft_type = legacy_roster[0] if legacy_roster else None
        return run

    def complete_sublevel_once(
        self,
        attempt_id: Optional[str] = None,
    ) -> Optional[RewardSettlement]:
        """成功結算目前小關一次；清除 RunState 後仍可回傳同一結果。"""

        requested_id = str(attempt_id) if attempt_id is not None else None
        previous = self.session_progress.last_reward_settlement
        if previous is not None and (
            requested_id is None or requested_id == previous.attempt_id
        ) and self.run_state is None:
            return previous
        run = self.run_state
        if run is None:
            return None
        if requested_id is not None and requested_id != run.attempt_id:
            if previous is not None and requested_id == previous.attempt_id:
                return previous
            return None
        if self.phase not in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        ):
            return None
        if run.reward_settled:
            return previous
        if self.profile is None:
            return None
        self.progression_config = self.profile.config
        plan = run.level_plan or build_level_plan(
            run.level,
            self.profile.max_aircraft_count,
            config=self.progression_config,
        )
        awarded = calculate_reward(
            plan,
            self.profile.rebirth_count,
            config=self.progression_config,
        )
        raw = (
            self.progression_config.base_reward
            + self.progression_config.reward_per_aircraft * plan.key.a
            + self.progression_config.reward_per_sublevel * (plan.key.b - 1)
            + self.progression_config.boss_reward * plan.boss_count
        )
        multiplier = (
            1.0
            + self.progression_config.rebirth_reward_multiplier
            * self.profile.rebirth_count
        )
        settlement = RewardSettlement(
            attempt_id=run.attempt_id,
            level_key=run.level,
            raw_reward=raw,
            rebirth_multiplier=multiplier,
            awarded_coins=awarded,
        )
        updated = self.profile.clone()
        updated.coins += awarded
        updated.last_completed_a_b = str(run.level)
        if plan.is_final_sublevel:
            updated.rebirth_available = True
            self.session_progress.reset_level()
        else:
            self.session_progress.next_play_level = next_level(
                run.level, updated.max_aircraft_count
            )
        self.profile = updated
        self.session_progress.last_reward_settlement = settlement
        run.reward_settled = True
        self._save_selected_profile()
        self.clear_run_state()
        return settlement

    def fail_sublevel_once(
        self,
        reason: FailureReason | str = FailureReason.PLAYER_DEAD,
        *,
        event_id: Optional[str] = None,
    ) -> bool:
        """處理死亡／城市毀損一次，保留永久資料並開放重生資格。"""

        if self.run_state is None:
            return False
        key = str(event_id or reason)
        if key in self._processed_events:
            return False
        self._processed_events.add(key)
        if self.profile is not None:
            updated = self.profile.clone()
            updated.rebirth_available = True
            self.profile = updated
        self.session_progress.reset_level()
        self.health = 0
        self._save_selected_profile()
        self.clear_run_state()
        return True

    def clear_run_state(self) -> None:
        """清除本局 HP、敵人、城市、彈藥、砲塔、鎖定與冷卻。"""

        self.run_state = None
        self._clear_transient_to_menu()
        self.phase = GamePhase.MAIN_MENU
        self._sync_profile_boundary()

    def open_shop(self) -> GamePhase:
        if self.profile is None or self.run_state is not None:
            return self.phase
        if self.phase == GamePhase.MAIN_MENU:
            self.phase = GamePhase.SHOP
        return self.phase

    def return_to_profile_menu(self) -> GamePhase:
        """從商店或戰鬥返回目前存檔主選單並保存永久資料。"""

        if self.run_state is not None:
            self.session_progress.reset_level()
            self.clear_run_state()
            self._save_selected_profile()
        else:
            self.phase = GamePhase.MAIN_MENU
            self._clear_transient_to_menu()
            self._save_selected_profile()
        return self.phase

    def delete_save_slot(self, slot_id: int) -> SaveDeleteResult:
        """只允許在選檔畫面刪除指定欄位，避免誤刪目前戰鬥資料。"""

        if self.save_store is None:
            self.save_store = SaveStore(config=self.progression_config)
        path = self.save_store.slot_path(slot_id)
        if self.phase != GamePhase.SAVE_SELECT:
            return SaveDeleteResult(
                slot_id,
                False,
                path,
                "rejected",
                error="只能在選檔畫面刪除存檔",
            )
        return self.save_store.delete_slot(slot_id)

    def purchase_upgrade_once(
        self,
        operation_id: str,
        upgrade_id: str,
    ) -> PurchaseSettlement:
        """以操作 ID 去重的商店購買。"""

        operation_id = str(operation_id)
        if operation_id in self._purchase_settlements:
            return self._purchase_settlements[operation_id]
        if self.profile is None:
            result = PurchaseSettlement(
                operation_id,
                str(upgrade_id),
                False,
                SaveProfile.default(config=self.progression_config),
                error="尚未選擇存檔",
            )
            self._purchase_settlements[operation_id] = result
            return result
        self.progression_config = self.profile.config
        if self.run_state is not None or self.phase not in (GamePhase.MAIN_MENU, GamePhase.SHOP):
            result = PurchaseSettlement(
                operation_id, str(upgrade_id), False, self.profile.clone(), error="戰鬥中不可購買升級"
            )
            self._purchase_settlements[operation_id] = result
            return result
        try:
            updated = purchase_upgrade(
                self.profile,
                upgrade_id,
                config=self.progression_config,
            )
            price = self.profile.coins - updated.coins
        except (ValueError, TypeError) as exc:
            result = PurchaseSettlement(
                operation_id,
                str(upgrade_id),
                False,
                self.profile.clone(),
                error=str(exc),
            )
        else:
            self.profile = updated
            self._sync_profile_boundary()
            self._save_selected_profile()
            result = PurchaseSettlement(
                operation_id,
                str(upgrade_id),
                True,
                self.profile.clone(),
                price=price,
            )
        self._purchase_settlements[operation_id] = result
        return result

    def apply_rebirth_once(self, operation_id: str) -> RebirthSettlement:
        """在主選單執行一次重生；成功後仍停留主選單。"""

        operation_id = str(operation_id)
        if operation_id in self._rebirth_settlements:
            return self._rebirth_settlements[operation_id]
        if self.profile is None:
            result = RebirthSettlement(
                operation_id,
                False,
                SaveProfile.default(config=self.progression_config),
                0,
                error="尚未選擇存檔",
            )
            self._rebirth_settlements[operation_id] = result
            return result
        self.progression_config = self.profile.config
        cost = calculate_rebirth_cost(
            self.profile.rebirth_count,
            config=self.progression_config,
        )
        if self.run_state is not None or self.phase != GamePhase.MAIN_MENU:
            result = RebirthSettlement(
                operation_id, False, self.profile.clone(), cost, error="戰鬥中不可重生"
            )
            self._rebirth_settlements[operation_id] = result
            return result
        try:
            updated = apply_rebirth(
                self.profile,
                config=self.progression_config,
            )
        except (ValueError, TypeError) as exc:
            result = RebirthSettlement(
                operation_id, False, self.profile.clone(), cost, error=str(exc)
            )
        else:
            self.profile = updated
            self.session_progress.reset_level()
            self.session_progress.last_reward_settlement = None
            self._clear_transient_to_menu()
            self.phase = GamePhase.MAIN_MENU
            self._sync_profile_boundary()
            self._save_selected_profile()
            result = RebirthSettlement(
                operation_id, True, self.profile.clone(), cost
            )
        self._rebirth_settlements[operation_id] = result
        return result

    def select_weapon(self, weapon: WeaponKind | str) -> bool:
        """切換已解鎖武器；不重置其他武器冷卻或鎖定。"""

        if self.phase not in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        ):
            return False
        try:
            selected = WeaponKind(weapon)
        except (TypeError, ValueError):
            return False
        if self.profile is not None:
            unlocked = set(self.profile.unlocked_weapons)
            if selected.value not in unlocked:
                return False
        self.held_weapon = selected
        if self.run_state is not None:
            self.run_state.selected_weapon = selected
        return True

    def _sync_profile_boundary(self) -> None:
        if self.profile is None:
            return
        self.max_health = effective_max_hp(
            self.profile,
            config=self.progression_config,
        )
        self.health = min(self.max_health, max(0, int(self.health)))
        self.max_city_health = CITY_MAX_HEALTH
        if self.run_state is None:
            self.city_health = self.max_city_health

    def _first_unlocked_weapon(self) -> WeaponKind:
        if self.profile is None:
            return WeaponKind.ANTI_AIRCRAFT
        for weapon in (
            WeaponKind.ANTI_AIRCRAFT,
            WeaponKind.SNIPER,
            WeaponKind.PISTOL,
            WeaponKind.RPG,
            WeaponKind.MULTI_ANTI_AIRCRAFT,
        ):
            if weapon.value in set(self.profile.unlocked_weapons):
                return weapon
        return WeaponKind.ANTI_AIRCRAFT

    def _create_weapon_runtimes(self) -> dict[WeaponKind, WeaponRuntime]:
        profile = self.profile or SaveProfile.default()
        return {
            WeaponKind.ANTI_AIRCRAFT: WeaponRuntime(
                WeaponKind.ANTI_AIRCRAFT,
                cooldown_remaining=0.0,
                cooldown_duration=effective_cooldown(
                    AA_FIRE_COOLDOWN_SECONDS,
                    profile,
                    config=self.progression_config,
                ),
                range=180.0,
                damage=1,
                scope_enabled=False,
            ),
            WeaponKind.SNIPER: WeaponRuntime(
                WeaponKind.SNIPER,
                cooldown_remaining=0.0,
                cooldown_duration=effective_cooldown(
                    SNIPER_FIRE_COOLDOWN_SECONDS,
                    profile,
                    config=self.progression_config,
                ),
                range=SNIPER_MAX_RANGE,
                damage=1,
            ),
            WeaponKind.PISTOL: WeaponRuntime(
                WeaponKind.PISTOL,
                cooldown_remaining=0.0,
                cooldown_duration=effective_cooldown(
                    PISTOL_FIRE_COOLDOWN_SECONDS,
                    profile,
                    config=self.progression_config,
                ),
                range=PISTOL_MAX_RANGE,
                damage=1,
            ),
            WeaponKind.RPG: WeaponRuntime(
                WeaponKind.RPG,
                ammo_remaining=(
                    self.progression_config.rpg_ammo_per_sublevel
                    if "RPG" in profile.unlocked_weapons
                    else 0
                ),
                cooldown_remaining=0.0,
                cooldown_duration=effective_cooldown(
                    self.progression_config.rpg_cooldown_seconds,
                    profile,
                    config=self.progression_config,
                ),
                range=PISTOL_MAX_RANGE,
                damage=self.progression_config.rpg_damage,
            ),
            WeaponKind.MULTI_ANTI_AIRCRAFT: WeaponRuntime(
                WeaponKind.MULTI_ANTI_AIRCRAFT,
                cooldown_remaining=0.0,
                cooldown_duration=effective_cooldown(
                    AA_FIRE_COOLDOWN_SECONDS,
                    profile,
                    config=self.progression_config,
                ),
                range=180.0,
                damage=1,
            ),
        }

    def _save_selected_profile(self) -> Optional[object]:
        if self.save_store is None or self.profile is None:
            return None
        slot_id = self.session_progress.selected_slot_id
        if slot_id is None:
            return None
        return self.save_store.save_slot(slot_id, self.profile)

    def _clear_transient_to_menu(self) -> None:
        self.held_weapon = None
        self.reset_airstrike_guidance()
        self.active_aircraft_id = None
        self.active_encounter_id = None
        self.aircraft_sequence = 0
        self.wave_runtime = None
        self.active_aircraft_type = None
        self.city_health = self.max_city_health
        self.health = self.max_health
        self.stats.reset()
        self._processed_events.clear()

    def start_new_game(self, wave_plan: Optional["WavePlan"] = None) -> GamePhase:
        if self.profile is not None and wave_plan is None:
            self.start_sublevel()
            return self.phase
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

        ids = tuple(str(aircraft_id) for aircraft_id in aircraft_ids)
        types = (
            {str(aircraft_id): AircraftType(aircraft_type)
             for aircraft_id, aircraft_type in aircraft_types.items()}
            if aircraft_types
            else dict(zip(ids, self.wave.roster))
        )
        self.wave_runtime = WaveRuntime(
            wave=self.wave,
            aircraft_ids=ids,
            aircraft_types=types,
        )
        self.active_aircraft_id = ids[0]
        self.active_aircraft_type = self.wave_runtime.aircraft_types[ids[0]]
        return self.wave_runtime

    def sync_aircraft_phase(self, aircraft_id: str, phase: AircraftPhase) -> bool:
        if self.wave_runtime is None:
            return False
        changed = self.wave_runtime.sync_aircraft_phase(aircraft_id, phase)
        if self.run_state is not None and aircraft_id in self.run_state.aircrafts:
            record = self.run_state.aircrafts[aircraft_id]
            if isinstance(record, dict):
                record["phase"] = AircraftPhase(phase)
                record["alive"] = AircraftPhase(phase) not in (
                    AircraftPhase.DESTROYED,
                    AircraftPhase.IMPACTED,
                )
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
            if self.run_state is not None and aircraft_id in self.run_state.aircrafts:
                record = self.run_state.aircrafts[aircraft_id]
                if isinstance(record, dict):
                    record["phase"] = AircraftPhase.DESTROYED
                    record["alive"] = False
            key = f"aircraft-destroyed:{aircraft_id}"
            self._processed_events.add(key)
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
        if changed and self.run_state is not None and aircraft_id in self.run_state.aircrafts:
            record = self.run_state.aircrafts[aircraft_id]
            if isinstance(record, dict):
                record["phase"] = AircraftPhase.IMPACTED
                record["alive"] = False
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
        slot_id: Optional[int] = None,
        operation_id: Optional[str] = None,
        upgrade_id: Optional[str] = None,
        aircraft_id: Optional[str] = None,
        encounter_id: Optional[str] = None,
        wave_plan: Optional["WavePlan"] = None,
        ground_cleared: Optional[bool] = None,
    ) -> GamePhase:
        event = SessionEvent(event)
        if event == SessionEvent.SELECT_SAVE:
            if slot_id is not None:
                self.select_save_slot(slot_id)
            return self.phase
        if event == SessionEvent.OPEN_SHOP:
            return self.open_shop()
        if event == SessionEvent.PURCHASE_UPGRADE:
            if operation_id is not None and upgrade_id is not None:
                self.purchase_upgrade_once(operation_id, upgrade_id)
            return self.phase
        if event == SessionEvent.REBIRTH:
            if operation_id is not None:
                self.apply_rebirth_once(operation_id)
            return self.phase
        if event == SessionEvent.START_GAME:
            if self.phase == GamePhase.MAIN_MENU:
                if self.profile is not None:
                    self.start_sublevel()
                    return self.phase
                return self.start_new_game(wave_plan)
            return self.phase

        if event == SessionEvent.RETURN_TO_MENU:
            if self.profile is not None:
                self.return_to_profile_menu()
            elif self.phase in (GamePhase.GAME_OVER, GamePhase.VICTORY):
                self._reset_to_menu()
            return self.phase

        # 新流程的結算先於舊版逐飛機事件處理；profile 為 None 的舊測試
        # 仍使用下方既有波次生命週期。
        if self.profile is not None and self.run_state is not None:
            if event == SessionEvent.WAVE_CLEARED or event == SessionEvent.VICTORY:
                self.complete_sublevel_once(event_id)
                return self.phase
            if event in (
                SessionEvent.PLAYER_DIED,
                SessionEvent.CITY_DESTROYED,
                SessionEvent.BUILDING_IMPACT,
            ):
                reason = (
                    FailureReason.PLAYER_DEAD
                    if event == SessionEvent.PLAYER_DIED
                    else FailureReason.CITY_DESTROYED
                    if event == SessionEvent.CITY_DESTROYED
                    else FailureReason.BUILDING_IMPACT
                )
                self.fail_sublevel_once(reason, event_id=event_id)
                return self.phase

        if self.phase in (GamePhase.GAME_OVER, GamePhase.VICTORY):
            return self.phase

        if event == SessionEvent.AIRCRAFT_DESTROYED:
            if self.phase not in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT):
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
                    self.active_encounter_id = self.wave_runtime.ground_encounter_id
                    self.active_aircraft_id = None
                    self.active_aircraft_type = None
                    self.reset_airstrike_guidance()
                    # The controller performs the aggregate clear predicate.
                    # Keep the old keyed transition useful for callers that do
                    # not create a drop manager by entering ground combat.
                    self.phase = GamePhase.GROUND_COMBAT
                elif self.wave_runtime.hybrid_started:
                    self.active_aircraft_id = self.wave_runtime.alive_aircraft_ids[0]
                    self.active_aircraft_type = self.wave_runtime.aircraft_types[
                        self.active_aircraft_id
                    ]
                    self.phase = GamePhase.HYBRID_COMBAT
                else:
                    self.active_aircraft_id = self.wave_runtime.alive_aircraft_ids[0]
                    self.active_aircraft_type = self.wave_runtime.aircraft_types[
                        self.active_aircraft_id
                    ]
                    self.phase = GamePhase.AIRSTRIKE
                if self.run_state is not None:
                    self.run_state.phase = self.phase
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

        if event == SessionEvent.DROP_STARTED:
            if self.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            ):
                return self.phase
            runtime = self.wave_runtime
            source_id = aircraft_id
            if runtime is None or source_id is None or source_id not in runtime.aircraft_ids:
                return self.phase
            if runtime.aircraft_statuses[source_id] != AircraftPhase.DESTROYED:
                return self.phase
            if (
                encounter_id is not None
                and runtime.ground_encounter_id not in (None, encounter_id)
            ):
                return self.phase
            key = event_id or f"drop-started:{runtime.wave.wave_number}:{source_id}"
            if key in self._processed_events:
                return self.phase
            if not runtime.mark_drop_spawned(source_id):
                return self.phase
            self._processed_events.add(key)
            runtime.start_hybrid_drop()
            if encounter_id is not None:
                runtime.ground_encounter_id = encounter_id
                self.active_encounter_id = encounter_id
            if runtime.all_aircraft_destroyed:
                self.phase = GamePhase.GROUND_COMBAT
            else:
                self.phase = GamePhase.HYBRID_COMBAT
            if self.run_state is not None:
                self.run_state.phase = self.phase
            return self.phase

        if event == SessionEvent.BUILDING_IMPACT:
            if self.phase not in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT):
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

        if event == SessionEvent.WAVE_CLEARED:
            if self.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            ):
                return self.phase
            runtime = self.wave_runtime
            if runtime is not None:
                current_id = encounter_id or self.active_encounter_id or runtime.ground_encounter_id
                if not runtime.all_aircraft_destroyed:
                    return self.phase
                if not runtime.all_drop_decisions_processed:
                    return self.phase
                if runtime.has_active_drop and ground_cleared is not True:
                    return self.phase
                if current_id is not None and runtime.ground_encounter_id != current_id:
                    return self.phase
            elif self.phase != GamePhase.GROUND_COMBAT:
                return self.phase
            key = event_id or f"wave-cleared:{self.wave.wave_number}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            if self.wave.wave_number >= LEGACY_COMPATIBILITY_WAVE_COUNT:
                self.phase = GamePhase.VICTORY
                self.active_aircraft_id = None
                self.active_aircraft_type = None
                self.reset_airstrike_guidance()
                return self.phase

            if runtime is not None:
                next_wave = (
                    wave_plan.to_progress()
                    if wave_plan is not None
                    else WaveProgress(
                        wave_number=self.wave.wave_number + 1,
                        aircraft_count=self.wave.aircraft_count,
                        aircraft_cap=self.wave.aircraft_cap,
                        is_boss_wave=False,
                        roster=self.wave.roster,
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
                    is_boss_wave=False,
                    roster=tuple(AircraftType.NORMAL for _ in range(next_count)),
                )
            self.aircraft_sequence += 1
            self.active_aircraft_id = self._aircraft_id(self.aircraft_sequence)
            self.active_aircraft_type = self.wave.active_aircraft_type
            self.reset_airstrike_guidance()
            self.phase = GamePhase.AIRSTRIKE
            return self.phase

        if event == SessionEvent.VICTORY:
            if self.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            ):
                return self.phase
            runtime = self.wave_runtime
            if self.wave.wave_number != LEGACY_COMPATIBILITY_WAVE_COUNT:
                return self.phase
            if runtime is not None and not runtime.all_aircraft_destroyed:
                return self.phase
            if runtime is not None and not runtime.all_drop_decisions_processed:
                return self.phase
            if runtime is not None and runtime.has_active_drop and ground_cleared is not True:
                return self.phase
            if runtime is None and (
                self.phase != GamePhase.GROUND_COMBAT
                or ground_cleared is not True
            ):
                return self.phase
            key = event_id or f"victory:{self.wave.wave_number}"
            if key in self._processed_events:
                return self.phase
            self._processed_events.add(key)
            self.phase = GamePhase.VICTORY
            self.active_aircraft_id = None
            self.active_aircraft_type = None
            self.reset_airstrike_guidance()
            return self.phase

        if event == SessionEvent.CREW_CLEARED:
            if self.phase != GamePhase.GROUND_COMBAT:
                return self.phase
            # Keyed runtimes use WAVE_CLEARED after the aggregate predicate;
            # this compatibility event must never bypass that condition.
            if self.wave_runtime is not None:
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
                    is_boss_wave=False,
                    roster=tuple(AircraftType.NORMAL for _ in range(next_count)),
                )
            self.aircraft_sequence += 1
            self.active_aircraft_id = self._aircraft_id(self.aircraft_sequence)
            self.active_aircraft_type = self.wave.active_aircraft_type
            self.reset_airstrike_guidance()
            self.phase = GamePhase.AIRSTRIKE
            return self.phase

        if event == SessionEvent.PLAYER_DIED:
            if self.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            ):
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
            if self.phase not in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT):
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
        if self.phase not in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        ):
            return False
        if self.run_state is not None and self.profile is not None:
            self.run_state.current_hp = apply_damage(
                self.run_state.current_hp,
                amount,
                self.run_state.effective_max_hp,
                self.run_state.regen,
                profile=self.profile,
                config=self.progression_config,
            )
            self.health = int(self.run_state.current_hp)
            if self.run_state.current_hp <= 0.0:
                self.fail_sublevel_once(FailureReason.PLAYER_DEAD)
                return True
            return False
        self.health = max(0, self.health - max(0, amount))
        if self.health == 0:
            self.transition(SessionEvent.PLAYER_DIED)
            return True
        return False

    def take_city_damage(self, amount: float) -> bool:
        """Apply city damage and transition once when its health reaches zero."""

        if self.phase not in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) or amount <= 0:
            return False
        self.city_health = max(0.0, self.city_health - amount)
        if self.run_state is not None:
            self.run_state.city_health = self.city_health
        if self.city_health <= 0.0:
            self.transition(SessionEvent.CITY_DESTROYED)
            return True
        return False

    def tick(self, delta_seconds: float) -> None:
        if self.phase in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        ):
            self.stats.tick(delta_seconds)
            if self.run_state is not None:
                self.run_state.current_hp = tick_regeneration(
                    self.run_state.regen,
                    self.run_state.current_hp,
                    self.run_state.effective_max_hp,
                    delta_seconds,
                    config=self.progression_config,
                )
                self.health = int(self.run_state.current_hp)
                for runtime in self.run_state.weapon_runtime.values():
                    runtime.tick(delta_seconds)
                self.run_state.phase = self.phase

    def can_use_anti_air(self) -> bool:
        return self.phase in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        ) and self.held_weapon in (
            WeaponKind.ANTI_AIRCRAFT,
            WeaponKind.MULTI_ANTI_AIRCRAFT,
        )

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
        self.run_state = None
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
