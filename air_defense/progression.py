"""純進度、關卡、經濟與回血規則。

本模組刻意不匯入 Ursina，也不依賴畫面或控制器。所有會影響永久進度的
數值集中在 :class:`ProgressionConfig`，讓存檔、商店、關卡與戰鬥適配層
使用同一份規則。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from math import floor
import re
from typing import Any, Iterable, Mapping, Optional, Sequence


class AircraftToken(str, Enum):
    """關卡編隊使用的三種穩定顯示標記。"""

    NORMAL = "普"
    SPECIAL = "特"
    BOSS = "魔"


UPGRADE_MAX_HP = "max_hp"
UPGRADE_ARMOR = "armor"
UPGRADE_AA_LOCK_TIME = "aa_lock_time"
UPGRADE_AA_WHITEBOX = "aa_whitebox"
UPGRADE_AIM_ASSIST = "aa_aim_assist"
UPGRADE_WEAPON_COOLDOWN = "weapon_cooldown"
UPGRADE_RPG = "rpg"
UPGRADE_AUTO_DEFENSE = "auto_defense"
UPGRADE_AUTO_DEFENSE_CAPACITY = "auto_defense_capacity"
UPGRADE_MULTI_AA = "multi_anti_aircraft"
UPGRADE_MULTI_AA_TARGETS = "multi_anti_aircraft_targets"

# 讓呼叫端可以用較具體的名稱，但目前冷卻升級採共用等級。
COOLDOWN_ANTI_AIRCRAFT = UPGRADE_WEAPON_COOLDOWN
COOLDOWN_SNIPER = UPGRADE_WEAPON_COOLDOWN
COOLDOWN_PISTOL = UPGRADE_WEAPON_COOLDOWN
COOLDOWN_RPG = UPGRADE_WEAPON_COOLDOWN
COOLDOWN_MULTI_AA = UPGRADE_WEAPON_COOLDOWN
COOLDOWN_AUTO_DEFENSE = UPGRADE_WEAPON_COOLDOWN

WEAPON_ANTI_AIRCRAFT = "ANTI_AIRCRAFT"
WEAPON_SNIPER = "SNIPER"
WEAPON_PISTOL = "PISTOL"
WEAPON_RPG = "RPG"
WEAPON_MULTI_AA = "MULTI_ANTI_AIRCRAFT"


@dataclass(frozen=True)
class ProgressionConfig:
    """集中管理所有可調整的進度與戰鬥平衡值。"""

    initial_aircraft_count: int = 2
    aircraft_count_per_rebirth: int = 1
    base_max_hp: int = 100
    hp_per_upgrade: int = 10
    armor_damage_reduction_per_level: int = 1
    minimum_damage_after_armor: int = 1
    base_lock_duration_seconds: float = 3.0
    lock_duration_reduction_seconds: float = 0.15
    base_whitebox_scale: float = 1.0
    whitebox_scale_per_level: float = 0.10
    cooldown_reduction_per_level: float = 0.05
    minimum_cooldown_ratio: float = 0.50
    base_reward: int = 100
    reward_per_aircraft: int = 25
    reward_per_sublevel: int = 10
    boss_reward: int = 150
    rebirth_reward_multiplier: float = 0.50
    rebirth_base_cost: int = 1000
    regen_delay_seconds: float = 5.0
    regen_rate_hp_per_second: float = 2.0
    regen_budget_ratio: float = 0.20
    rpg_explosion_radius: float = 6.0
    rpg_damage: int = 35
    rpg_cooldown_seconds: float = 2.5
    rpg_ammo_per_sublevel: int = 3
    auto_defense_unlock_price: int = 600
    auto_defense_capacity_price: int = 450
    auto_defense_ammo_per_sublevel: int = 20
    auto_defense_cooldown_seconds: float = 1.5
    auto_defense_damage: int = 20
    auto_defense_hard_limit: int = 6
    multi_aa_unlock_price: int = 750
    multi_aa_target_price: int = 500
    multi_aa_initial_targets: int = 2
    multi_aa_hard_limit: int = 6
    max_hp_upgrade_price: int = 250
    armor_upgrade_price: int = 350
    lock_upgrade_price: int = 300
    whitebox_upgrade_price: int = 250
    cooldown_upgrade_price: int = 300
    aim_assist_price: int = 750
    rpg_unlock_price: int = 500
    # 0 級代表尚未購買；解鎖後直接提供一台或兩個目標。
    repeatable_base_caps: tuple[tuple[str, int], ...] = (
        (UPGRADE_MAX_HP, 5),
        (UPGRADE_ARMOR, 3),
        (UPGRADE_AA_LOCK_TIME, 5),
        (UPGRADE_AA_WHITEBOX, 5),
        (UPGRADE_WEAPON_COOLDOWN, 5),
        (UPGRADE_AUTO_DEFENSE_CAPACITY, 5),
        (UPGRADE_MULTI_AA_TARGETS, 4),
    )
    initial_unlocked_weapons: tuple[str, ...] = (
        WEAPON_ANTI_AIRCRAFT,
        WEAPON_SNIPER,
        WEAPON_PISTOL,
    )

    def __post_init__(self) -> None:
        if self.initial_aircraft_count < 2:
            raise ValueError("initial_aircraft_count must be at least 2")
        if self.aircraft_count_per_rebirth < 1:
            raise ValueError("aircraft_count_per_rebirth must be positive")
        if self.base_max_hp < 1 or self.hp_per_upgrade < 0:
            raise ValueError("invalid HP configuration")
        if not 0.0 < self.regen_budget_ratio <= 1.0:
            raise ValueError("regen_budget_ratio must be in (0, 1]")
        if self.regen_delay_seconds < 0.0 or self.regen_rate_hp_per_second < 0.0:
            raise ValueError("invalid regeneration configuration")
        if self.auto_defense_hard_limit < 1 or self.multi_aa_hard_limit < 1:
            raise ValueError("weapon hard limits must be positive")

    def maximum_aircraft_count(self, rebirth_count: int) -> int:
        """依重生次數推導本次可用的最大飛機數量。"""

        count = _non_negative_int(rebirth_count, "rebirth_count")
        return self.initial_aircraft_count + count * self.aircraft_count_per_rebirth

    def cap_for(self, upgrade_id: str, rebirth_count: int) -> int:
        """計算可重複升級的購買等級上限。"""

        upgrade_id = normalize_upgrade_id(upgrade_id)
        count = _non_negative_int(rebirth_count, "rebirth_count")
        base = dict(self.repeatable_base_caps).get(upgrade_id)
        if base is None:
            return 1
        entry = next(
            (item for item in upgrade_catalog(self) if item.upgrade_id == upgrade_id),
            None,
        )
        growth = 1 if entry is None else entry.cap_growth
        cap = base + growth * count
        if upgrade_id == UPGRADE_AUTO_DEFENSE_CAPACITY:
            return min(cap, self.auto_defense_hard_limit - 1)
        if upgrade_id == UPGRADE_MULTI_AA_TARGETS:
            return min(cap, self.multi_aa_hard_limit - self.multi_aa_initial_targets)
        return cap


DEFAULT_CONFIG = ProgressionConfig()


@dataclass(frozen=True, order=True)
class LevelKey:
    """可排序且可格式化為 ``a-b`` 的小關識別字。"""

    a: int
    b: int

    def __post_init__(self) -> None:
        a = _positive_int(self.a, "a")
        b = _positive_int(self.b, "b")
        if b > 2 * a + 1:
            raise ValueError("b is outside the generic a-b range")
        object.__setattr__(self, "a", a)
        object.__setattr__(self, "b", b)

    def __str__(self) -> str:
        return f"{self.a}-{self.b}"

    @classmethod
    def parse(cls, value: str | "LevelKey" | tuple[int, int]) -> "LevelKey":
        if isinstance(value, cls):
            return value
        if isinstance(value, tuple) and len(value) == 2:
            return cls(int(value[0]), int(value[1]))
        match = re.fullmatch(r"([1-9][0-9]*)-([1-9][0-9]*)", str(value).strip())
        if match is None:
            raise ValueError("level key must use a-b format")
        return cls(int(match.group(1)), int(match.group(2)))


def validate_level_key(level_key: LevelKey | str | tuple[int, int], maximum_aircraft_count: int) -> LevelKey:
    """依目前 A 驗證 a-b 是否可生成。"""

    key = LevelKey.parse(level_key)
    maximum = _positive_int(maximum_aircraft_count, "maximum_aircraft_count")
    if maximum < 2:
        raise ValueError("maximum_aircraft_count must be at least 2")
    if not 1 <= key.a <= maximum:
        raise ValueError("a must be between 1 and A")
    maximum_b = key.a + 1 if key.a < maximum else 2 * key.a + 1
    if not 1 <= key.b <= maximum_b:
        raise ValueError("b is outside the valid range for a and A")
    return key


@dataclass(frozen=True)
class LevelPlan:
    """一個小關的確定性飛機編隊與計數資料。"""

    key: LevelKey
    maximum_aircraft_count: int
    roster: tuple[str, ...]
    normal_count: int
    special_count: int
    boss_count: int
    is_boss_stage: bool
    is_final_sublevel: bool

    @property
    def aircraft_count(self) -> int:
        return self.key.a

    @property
    def level_key(self) -> LevelKey:
        return self.key

    def __post_init__(self) -> None:
        key = LevelKey.parse(self.key)
        maximum = _positive_int(self.maximum_aircraft_count, "maximum_aircraft_count")
        validate_level_key(key, maximum)
        roster = tuple(
            token.value if isinstance(token, AircraftToken) else str(token)
            for token in self.roster
        )
        if len(roster) != key.a:
            raise ValueError("roster length must equal a")
        allowed = {token.value for token in AircraftToken}
        if any(token not in allowed for token in roster):
            raise ValueError("roster contains an unknown aircraft token")
        counts = {
            AircraftToken.NORMAL.value: roster.count(AircraftToken.NORMAL.value),
            AircraftToken.SPECIAL.value: roster.count(AircraftToken.SPECIAL.value),
            AircraftToken.BOSS.value: roster.count(AircraftToken.BOSS.value),
        }
        if (counts["普"], counts["特"], counts["魔"]) != (
            int(self.normal_count),
            int(self.special_count),
            int(self.boss_count),
        ):
            raise ValueError("roster counts do not match the plan")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "maximum_aircraft_count", maximum)
        object.__setattr__(self, "roster", roster)
        object.__setattr__(self, "normal_count", counts["普"])
        object.__setattr__(self, "special_count", counts["特"])
        object.__setattr__(self, "boss_count", counts["魔"])
        object.__setattr__(self, "is_boss_stage", counts["魔"] > 0)
        object.__setattr__(
            self,
            "is_final_sublevel",
            key.a == maximum and key.b == 2 * maximum + 1,
        )


def build_level_plan(
    level_key: LevelKey | str | tuple[int, int],
    maximum_aircraft_count: int,
    *,
    config: ProgressionConfig = DEFAULT_CONFIG,
) -> LevelPlan:
    """依 a-b 規則建立固定方向的普通、特別與魔王編隊。"""

    key = validate_level_key(level_key, maximum_aircraft_count)
    maximum = int(maximum_aircraft_count)
    special_or_boss_count = key.b - 1
    normal_count = key.a - special_or_boss_count
    if key.a < maximum or key.b <= key.a + 1:
        special_count = special_or_boss_count
        boss_count = 0
        # 由左至右保留普通，右側逐格替換成特別。
        roster = tuple(
            [AircraftToken.NORMAL.value] * normal_count
            + [AircraftToken.SPECIAL.value] * special_count
        )
    else:
        boss_count = key.b - (key.a + 1)
        special_count = key.a - boss_count
        # 特別轉魔王時由左側逐格替換。
        roster = tuple(
            [AircraftToken.BOSS.value] * boss_count
            + [AircraftToken.SPECIAL.value] * special_count
        )
        normal_count = 0
    plan = LevelPlan(
        key=key,
        maximum_aircraft_count=maximum,
        roster=roster,
        normal_count=normal_count,
        special_count=special_count,
        boss_count=boss_count,
        is_boss_stage=boss_count > 0,
        is_final_sublevel=key.a == maximum and key.b == 2 * maximum + 1,
    )
    return plan


def campaign_levels(maximum_aircraft_count: int) -> tuple[LevelKey, ...]:
    """列出目前 A 的所有有效小關，不建立固定關卡表。"""

    maximum = _positive_int(maximum_aircraft_count, "maximum_aircraft_count")
    if maximum < 2:
        raise ValueError("maximum_aircraft_count must be at least 2")
    keys: list[LevelKey] = []
    for a in range(1, maximum + 1):
        last_b = a + 1 if a < maximum else 2 * a + 1
        keys.extend(LevelKey(a, b) for b in range(1, last_b + 1))
    return tuple(keys)


def next_level(
    level_key: LevelKey | str | tuple[int, int],
    maximum_aircraft_count: int,
) -> LevelKey:
    """回傳中間小關的下一關；目前 A 最終小關後回到 1-1。"""

    key = validate_level_key(level_key, maximum_aircraft_count)
    maximum = int(maximum_aircraft_count)
    final = key.a == maximum and key.b == 2 * maximum + 1
    if final:
        return LevelKey(1, 1)
    last_b = key.a + 1 if key.a < maximum else 2 * key.a + 1
    if key.b < last_b:
        return LevelKey(key.a, key.b + 1)
    return LevelKey(key.a + 1, 1)


@dataclass(frozen=True)
class UpgradeCatalogEntry:
    """一筆商店目錄資料。"""

    upgrade_id: str
    label: str
    repeatable: bool
    price_base: int
    base_cap: int = 1
    cap_growth: int = 0
    hard_cap: Optional[int] = None
    unlocks_weapon: Optional[str] = None
    prerequisite: Optional[str] = None
    effect_description: str = ""

    @property
    def id(self) -> str:
        return self.upgrade_id


def normalize_upgrade_id(upgrade_id: str) -> str:
    aliases = {
        "max-health": UPGRADE_MAX_HP,
        "maximum_hp": UPGRADE_MAX_HP,
        "hp": UPGRADE_MAX_HP,
        "armor_level": UPGRADE_ARMOR,
        "lock_time": UPGRADE_AA_LOCK_TIME,
        "whitebox_size": UPGRADE_AA_WHITEBOX,
        "aim_assist": UPGRADE_AIM_ASSIST,
        "cooldown": UPGRADE_WEAPON_COOLDOWN,
        "multi_aa": UPGRADE_MULTI_AA,
        "multi_aa_targets": UPGRADE_MULTI_AA_TARGETS,
        "turret": UPGRADE_AUTO_DEFENSE,
        "turret_capacity": UPGRADE_AUTO_DEFENSE_CAPACITY,
    }
    value = str(upgrade_id).strip()
    return aliases.get(value, value)


def upgrade_catalog(config: ProgressionConfig = DEFAULT_CONFIG) -> tuple[UpgradeCatalogEntry, ...]:
    """回傳完整商店目錄；價格與上限不散落在控制器。"""

    caps = dict(config.repeatable_base_caps)
    return (
        UpgradeCatalogEntry(UPGRADE_MAX_HP, "最大 HP", True, config.max_hp_upgrade_price, caps[UPGRADE_MAX_HP], 1, effect_description="每級增加最大 HP"),
        UpgradeCatalogEntry(UPGRADE_ARMOR, "鎧甲", True, config.armor_upgrade_price, caps[UPGRADE_ARMOR], 1, effect_description="每級減少單次傷害 1"),
        UpgradeCatalogEntry(UPGRADE_AA_LOCK_TIME, "防空炮鎖定時間", True, config.lock_upgrade_price, caps[UPGRADE_AA_LOCK_TIME], 1, effect_description="每級縮短鎖定時間"),
        UpgradeCatalogEntry(UPGRADE_AA_WHITEBOX, "防空炮白框大小", True, config.whitebox_upgrade_price, caps[UPGRADE_AA_WHITEBOX], 1, effect_description="每級增加可鎖定範圍"),
        UpgradeCatalogEntry(UPGRADE_AIM_ASSIST, "防空炮輔助瞄準", False, config.aim_assist_price, unlocks_weapon=None, effect_description="購買後啟用輔助瞄準"),
        UpgradeCatalogEntry(UPGRADE_WEAPON_COOLDOWN, "各武器冷卻", True, config.cooldown_upgrade_price, caps[UPGRADE_WEAPON_COOLDOWN], 1, effect_description="每級縮短所有武器冷卻"),
        UpgradeCatalogEntry(UPGRADE_RPG, "RPG", False, config.rpg_unlock_price, unlocks_weapon=WEAPON_RPG, effect_description="解鎖 RPG"),
        UpgradeCatalogEntry(UPGRADE_AUTO_DEFENSE, "陸地自動防禦", False, config.auto_defense_unlock_price, unlocks_weapon=None, effect_description="解鎖固定位置砲塔"),
        UpgradeCatalogEntry(UPGRADE_AUTO_DEFENSE_CAPACITY, "陸地自動防禦容量", True, config.auto_defense_capacity_price, caps[UPGRADE_AUTO_DEFENSE_CAPACITY], 1, hard_cap=config.auto_defense_hard_limit, prerequisite=UPGRADE_AUTO_DEFENSE, effect_description="每級增加一台砲塔"),
        UpgradeCatalogEntry(UPGRADE_MULTI_AA, "多目標防空炮", False, config.multi_aa_unlock_price, unlocks_weapon=WEAPON_MULTI_AA, effect_description="解鎖多目標防空炮"),
        UpgradeCatalogEntry(UPGRADE_MULTI_AA_TARGETS, "多目標鎖定數量", True, config.multi_aa_target_price, caps[UPGRADE_MULTI_AA_TARGETS], 1, hard_cap=config.multi_aa_hard_limit, prerequisite=UPGRADE_MULTI_AA, effect_description="每級增加一個鎖定目標"),
    )


def catalog_entry(upgrade_id: str, *, config: ProgressionConfig = DEFAULT_CONFIG) -> UpgradeCatalogEntry:
    normalized = normalize_upgrade_id(upgrade_id)
    for entry in upgrade_catalog(config):
        if entry.upgrade_id == normalized:
            return entry
    raise ValueError(f"unknown upgrade: {upgrade_id}")


def derive_upgrade_caps(profile_or_rebirth: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> dict[str, int]:
    rebirth_count = (
        profile_or_rebirth.rebirth_count
        if hasattr(profile_or_rebirth, "rebirth_count")
        else profile_or_rebirth
    )
    return {
        entry.upgrade_id: config.cap_for(entry.upgrade_id, int(rebirth_count))
        for entry in upgrade_catalog(config)
        if entry.repeatable
    }


def get_upgrade_level(profile: Any, upgrade_id: str) -> int:
    normalized = normalize_upgrade_id(upgrade_id)
    levels = getattr(profile, "upgrade_levels", {})
    try:
        value = levels.get(normalized, 0)
    except AttributeError:
        value = 0
    return max(0, int(value))


def has_upgrade(profile: Any, upgrade_id: str) -> bool:
    normalized = normalize_upgrade_id(upgrade_id)
    if normalized == UPGRADE_RPG:
        return WEAPON_RPG in set(getattr(profile, "unlocked_weapons", ()))
    if normalized == UPGRADE_MULTI_AA:
        return WEAPON_MULTI_AA in set(getattr(profile, "unlocked_weapons", ()))
    return get_upgrade_level(profile, normalized) > 0


def effective_max_hp(profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> int:
    return config.base_max_hp + config.hp_per_upgrade * get_upgrade_level(profile, UPGRADE_MAX_HP)


def effective_armor(profile: Any) -> int:
    return get_upgrade_level(profile, UPGRADE_ARMOR)


def damage_after_armor(
    amount: int | float,
    profile: Any,
    *,
    config: ProgressionConfig = DEFAULT_CONFIG,
) -> int:
    raw = max(0, int(amount))
    if raw <= 0:
        return 0
    return max(config.minimum_damage_after_armor, raw - effective_armor(profile))


def effective_lock_duration(profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> float:
    level = get_upgrade_level(profile, UPGRADE_AA_LOCK_TIME)
    return max(0.1, config.base_lock_duration_seconds - config.lock_duration_reduction_seconds * level)


def effective_whitebox_scale(profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> float:
    level = get_upgrade_level(profile, UPGRADE_AA_WHITEBOX)
    return config.base_whitebox_scale * (1.0 + config.whitebox_scale_per_level * level)


def effective_cooldown(base_seconds: float, profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> float:
    level = get_upgrade_level(profile, UPGRADE_WEAPON_COOLDOWN)
    ratio = max(config.minimum_cooldown_ratio, 1.0 - config.cooldown_reduction_per_level * level)
    return max(0.0, float(base_seconds)) * ratio


def multi_aa_target_count(profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> int:
    if not has_upgrade(profile, UPGRADE_MULTI_AA):
        return 0
    level = get_upgrade_level(profile, UPGRADE_MULTI_AA_TARGETS)
    return min(config.multi_aa_hard_limit, config.multi_aa_initial_targets + level)


def auto_defense_capacity(profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> int:
    if not has_upgrade(profile, UPGRADE_AUTO_DEFENSE):
        return 0
    return min(config.auto_defense_hard_limit, 1 + get_upgrade_level(profile, UPGRADE_AUTO_DEFENSE_CAPACITY))


def price_for_upgrade(upgrade_id: str, current_level: int = 0, *, config: ProgressionConfig = DEFAULT_CONFIG) -> int:
    entry = catalog_entry(upgrade_id, config=config)
    level = _non_negative_int(current_level, "current_level")
    return int(entry.price_base if not entry.repeatable else entry.price_base * (level + 1))


def purchase_upgrade(profile: Any, upgrade_id: str, *, config: ProgressionConfig = DEFAULT_CONFIG) -> Any:
    """成功時回傳新的 Profile；失敗以 ValueError 拒絕且不修改原 Profile。"""

    entry = catalog_entry(upgrade_id, config=config)
    coins = _non_negative_int(getattr(profile, "coins", 0), "coins")
    levels = dict(getattr(profile, "upgrade_levels", {}))
    normalized = entry.upgrade_id
    current_level = max(0, int(levels.get(normalized, 0)))
    if entry.repeatable:
        cap = config.cap_for(normalized, int(getattr(profile, "rebirth_count", 0)))
        if current_level >= cap:
            raise ValueError("upgrade has reached its purchase limit")
        price = price_for_upgrade(normalized, current_level, config=config)
    else:
        if current_level >= 1 or (
            entry.unlocks_weapon is not None
            and entry.unlocks_weapon in set(getattr(profile, "unlocked_weapons", ()))
        ):
            raise ValueError("upgrade is already unlocked")
        if entry.prerequisite and not has_upgrade(profile, entry.prerequisite):
            raise ValueError("upgrade prerequisite is not unlocked")
        price = price_for_upgrade(normalized, current_level, config=config)
    if coins < price:
        raise ValueError("not enough coins")

    updated = deepcopy(profile)
    if hasattr(updated, "config"):
        updated.config = config
    updated.coins = coins - price
    updated.upgrade_levels = levels
    updated.upgrade_levels[normalized] = current_level + 1
    updated.upgrade_caps = derive_upgrade_caps(updated, config=config)
    if entry.unlocks_weapon is not None:
        unlocked = list(dict.fromkeys(str(item) for item in getattr(updated, "unlocked_weapons", ())))
        if entry.unlocks_weapon not in unlocked:
            unlocked.append(entry.unlocks_weapon)
        updated.unlocked_weapons = unlocked
    return updated


def calculate_reward(level_plan: LevelPlan | LevelKey | str | tuple[int, int], rebirth_count: int, *, maximum_aircraft_count: Optional[int] = None, config: ProgressionConfig = DEFAULT_CONFIG) -> int:
    """計算單一成功小關的一次性金幣獎勵。"""

    if not isinstance(level_plan, LevelPlan):
        if maximum_aircraft_count is None:
            key = LevelKey.parse(level_plan)
            maximum_aircraft_count = max(2, key.a)
        level_plan = build_level_plan(level_plan, maximum_aircraft_count, config=config)
    count = _non_negative_int(rebirth_count, "rebirth_count")
    raw = (
        config.base_reward
        + config.reward_per_aircraft * level_plan.key.a
        + config.reward_per_sublevel * (level_plan.key.b - 1)
        + config.boss_reward * level_plan.boss_count
    )
    return max(0, floor(raw * (1.0 + config.rebirth_reward_multiplier * count)))


def calculate_rebirth_cost(rebirth_count: int, *, config: ProgressionConfig = DEFAULT_CONFIG) -> int:
    return config.rebirth_base_cost * (_non_negative_int(rebirth_count, "rebirth_count") + 1)


def apply_rebirth(profile: Any, *, config: ProgressionConfig = DEFAULT_CONFIG) -> Any:
    """驗證資格與費用後原子產生重生後 Profile。"""

    if not bool(getattr(profile, "rebirth_available", False)):
        raise ValueError("rebirth is not available")
    rebirth_count = _non_negative_int(getattr(profile, "rebirth_count", 0), "rebirth_count")
    cost = calculate_rebirth_cost(rebirth_count, config=config)
    coins = _non_negative_int(getattr(profile, "coins", 0), "coins")
    if coins < cost:
        raise ValueError("not enough coins for rebirth")
    updated = deepcopy(profile)
    if hasattr(updated, "config"):
        updated.config = config
    updated.coins = 0
    updated.rebirth_count = rebirth_count + 1
    updated.max_aircraft_count = config.maximum_aircraft_count(updated.rebirth_count)
    updated.upgrade_caps = derive_upgrade_caps(updated, config=config)
    updated.rebirth_available = False
    return updated


@dataclass
class RegenState:
    """單一小關的有限自動回血狀態。"""

    last_damage_at: Optional[float] = None
    recovery_started: bool = False
    cycle_cap_remaining: float = 0.0
    sublevel_budget_remaining: float = 0.0
    recovered_this_damage_cycle: float = 0.0
    elapsed_since_damage: float = 0.0


def create_regen_state(effective_max_hp_value: float, *, config: ProgressionConfig = DEFAULT_CONFIG) -> RegenState:
    budget = max(0.0, float(effective_max_hp_value) * config.regen_budget_ratio)
    return RegenState(cycle_cap_remaining=budget, sublevel_budget_remaining=budget)


def register_damage(regen: RegenState, *, now: Optional[float] = None, effective_max_hp_value: Optional[float] = None, config: ProgressionConfig = DEFAULT_CONFIG) -> RegenState:
    # 沒有外部時鐘時以 0 作為小關內的相對時間起點，讓狀態層只傳入
    # delta_seconds 也能在延遲後回血；`None` 仍專門表示尚未受傷。
    regen.last_damage_at = 0.0 if now is None else float(now)
    regen.elapsed_since_damage = 0.0
    regen.recovery_started = False
    regen.recovered_this_damage_cycle = 0.0
    if effective_max_hp_value is not None:
        cycle_budget = max(0.0, float(effective_max_hp_value) * config.regen_budget_ratio)
        regen.cycle_cap_remaining = min(cycle_budget, regen.sublevel_budget_remaining)
    else:
        regen.cycle_cap_remaining = min(regen.cycle_cap_remaining or regen.sublevel_budget_remaining, regen.sublevel_budget_remaining)
    return regen


def tick_regeneration(
    regen: RegenState,
    current_hp: float,
    effective_max_hp_value: float,
    delta_seconds: float,
    *,
    now: Optional[float] = None,
    config: ProgressionConfig = DEFAULT_CONFIG,
) -> float:
    """依延遲、速度與小關總額度回傳新的 HP。"""

    delta = max(0.0, float(delta_seconds))
    previous_elapsed = regen.elapsed_since_damage
    if regen.last_damage_at is not None and now is not None:
        regen.elapsed_since_damage = max(0.0, float(now) - regen.last_damage_at)
    elif regen.last_damage_at is not None:
        regen.elapsed_since_damage += delta
    if regen.last_damage_at is None:
        return min(float(effective_max_hp_value), max(0.0, float(current_hp)))
    if regen.sublevel_budget_remaining <= 0.0:
        return min(float(effective_max_hp_value), max(0.0, float(current_hp)))
    if regen.elapsed_since_damage < config.regen_delay_seconds:
        return min(float(effective_max_hp_value), max(0.0, float(current_hp)))
    regen.recovery_started = True
    available = min(regen.cycle_cap_remaining, regen.sublevel_budget_remaining)
    missing = max(0.0, float(effective_max_hp_value) - float(current_hp))
    if previous_elapsed >= config.regen_delay_seconds:
        recovery_delta = delta
    else:
        recovery_delta = max(
            0.0,
            regen.elapsed_since_damage - config.regen_delay_seconds,
        )
    recovered = min(
        available,
        missing,
        config.regen_rate_hp_per_second * recovery_delta,
    )
    if recovered > 0.0:
        regen.cycle_cap_remaining -= recovered
        regen.sublevel_budget_remaining -= recovered
        regen.recovered_this_damage_cycle += recovered
    return min(float(effective_max_hp_value), max(0.0, float(current_hp)) + recovered)


def apply_damage(
    current_hp: float,
    amount: int | float,
    effective_max_hp_value: float,
    regen: RegenState,
    *,
    now: Optional[float] = None,
    profile: Any = None,
    config: ProgressionConfig = DEFAULT_CONFIG,
) -> float:
    """套用鎧甲後的傷害並重新啟動回血延遲。"""

    raw = max(0, int(amount))
    armor = effective_armor(profile) if profile is not None else 0
    damage = max(0, raw - armor)
    if raw > 0:
        damage = max(config.minimum_damage_after_armor, damage)
    new_hp = max(0.0, min(float(effective_max_hp_value), float(current_hp)) - damage)
    if damage > 0:
        register_damage(regen, now=now, effective_max_hp_value=effective_max_hp_value, config=config)
    return new_hp


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < 1:
        raise ValueError(f"{name} must be positive")
    return result


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result


__all__ = [
    "AircraftToken",
    "LevelKey",
    "LevelPlan",
    "ProgressionConfig",
    "UpgradeCatalogEntry",
    "RegenState",
    "DEFAULT_CONFIG",
    "UPGRADE_MAX_HP",
    "UPGRADE_ARMOR",
    "UPGRADE_AA_LOCK_TIME",
    "UPGRADE_AA_WHITEBOX",
    "UPGRADE_AIM_ASSIST",
    "UPGRADE_WEAPON_COOLDOWN",
    "UPGRADE_RPG",
    "UPGRADE_AUTO_DEFENSE",
    "UPGRADE_AUTO_DEFENSE_CAPACITY",
    "UPGRADE_MULTI_AA",
    "UPGRADE_MULTI_AA_TARGETS",
    "WEAPON_ANTI_AIRCRAFT",
    "WEAPON_SNIPER",
    "WEAPON_PISTOL",
    "WEAPON_RPG",
    "WEAPON_MULTI_AA",
    "build_level_plan",
    "campaign_levels",
    "next_level",
    "validate_level_key",
    "upgrade_catalog",
    "catalog_entry",
    "normalize_upgrade_id",
    "derive_upgrade_caps",
    "get_upgrade_level",
    "has_upgrade",
    "effective_max_hp",
    "effective_armor",
    "damage_after_armor",
    "effective_lock_duration",
    "effective_whitebox_scale",
    "effective_cooldown",
    "multi_aa_target_count",
    "auto_defense_capacity",
    "price_for_upgrade",
    "purchase_upgrade",
    "calculate_reward",
    "calculate_rebirth_cost",
    "apply_rebirth",
    "create_regen_state",
    "register_damage",
    "tick_regeneration",
    "apply_damage",
]
