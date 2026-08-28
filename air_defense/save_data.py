"""五個獨立 JSON 存檔欄位與永久進度資料。

這個模組只處理可持久化的玩家資料，不保存任何戰鬥中的實體或未完成的
小關。讀檔失敗時回傳安全的預設 Profile，但保留原始檔案，讓使用者可以
診斷或手動備份損壞資料。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Optional

from .progression import (
    DEFAULT_CONFIG,
    WEAPON_ANTI_AIRCRAFT,
    WEAPON_MULTI_AA,
    WEAPON_PISTOL,
    WEAPON_RPG,
    WEAPON_SNIPER,
    LevelKey,
    ProgressionConfig,
    derive_upgrade_caps,
    normalize_upgrade_id,
    UPGRADE_MULTI_AA_TARGETS,
)


SCHEMA_VERSION = 1
SLOT_COUNT = 5
SLOT_FILE_TEMPLATE = "slot-{slot_id}.json"
KNOWN_WEAPONS = frozenset(
    {
        WEAPON_ANTI_AIRCRAFT,
        WEAPON_SNIPER,
        WEAPON_PISTOL,
        WEAPON_RPG,
        WEAPON_MULTI_AA,
    }
)
KNOWN_UPGRADE_IDS = frozenset(
    {
        "max_hp",
        "armor",
        "aa_lock_time",
        "aa_whitebox",
        "aa_aim_assist",
        "weapon_cooldown",
        "rpg",
        "auto_defense",
        "auto_defense_capacity",
        "multi_anti_aircraft",
        "multi_anti_aircraft_targets",
    }
)
LEGACY_UPGRADE_IDS = frozenset({UPGRADE_MULTI_AA_TARGETS})


class SaveDataError(ValueError):
    """表示一份存檔不符合目前 schema 或資料邊界。"""


@dataclass
class SaveProfile:
    """可跨遊戲保存的永久 Profile。

    `max_aircraft_count` 與 `upgrade_caps` 是為了 HUD 與診斷而保存的快照；
    它們在建立 Profile 時一律由 `rebirth_count` 推導，避免舊資料把 4 或 18
    變成永久限制。
    """

    schema_version: int = SCHEMA_VERSION
    coins: int = 0
    rebirth_count: int = 0
    max_aircraft_count: int = 2
    upgrade_levels: dict[str, int] = field(default_factory=dict)
    upgrade_caps: dict[str, int] = field(default_factory=dict)
    unlocked_weapons: list[str] = field(
        default_factory=lambda: list(DEFAULT_CONFIG.initial_unlocked_weapons)
    )
    rebirth_available: bool = False
    last_completed_a_b: Optional[str] = None
    config: ProgressionConfig = field(
        default=DEFAULT_CONFIG,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_int(self.schema_version, "schema_version")
        if self.schema_version != SCHEMA_VERSION:
            raise SaveDataError("不支援的存檔結構版本")
        self.coins = _require_non_negative_int(self.coins, "coins")
        self.rebirth_count = _require_non_negative_int(self.rebirth_count, "rebirth_count")
        stored_maximum = _require_int(self.max_aircraft_count, "max_aircraft_count")
        if stored_maximum < 1:
            raise SaveDataError("max_aircraft_count 必須為正整數")
        if not isinstance(self.upgrade_levels, Mapping):
            raise SaveDataError("upgrade_levels 必須是物件")
        if not isinstance(self.upgrade_caps, Mapping):
            raise SaveDataError("upgrade_caps 必須是物件")
        if not isinstance(self.unlocked_weapons, (list, tuple)):
            raise SaveDataError("unlocked_weapons 必須是陣列")
        if not isinstance(self.rebirth_available, bool):
            raise SaveDataError("rebirth_available 必須是布林值")
        if self.last_completed_a_b is not None and not isinstance(
            self.last_completed_a_b, str
        ):
            raise SaveDataError("last_completed_a_b 必須是字串或 null")

        self.upgrade_levels = _normalize_levels(self.upgrade_levels)
        normalized_caps = _normalize_caps(self.upgrade_caps)
        self.unlocked_weapons = _normalize_weapons(self.unlocked_weapons)
        if self.last_completed_a_b is not None:
            self.last_completed_a_b = self.last_completed_a_b.strip()
        _validate_last_completed(self.last_completed_a_b)

        if not isinstance(self.config, ProgressionConfig):
            raise SaveDataError("config 必須是 ProgressionConfig")
        expected_a = self.config.maximum_aircraft_count(self.rebirth_count)
        # 這個欄位是可修正的診斷快照，不接受它覆寫來源規則。
        self.max_aircraft_count = expected_a
        expected_caps = derive_upgrade_caps(self, config=self.config)
        # Preserve schema-1 target-count snapshots for round-trip
        # compatibility, while keeping them out of the effective caps map.
        self.upgrade_caps = {
            **expected_caps,
            **{
                upgrade_id: normalized_caps[upgrade_id]
                for upgrade_id in LEGACY_UPGRADE_IDS
                if upgrade_id in normalized_caps
            },
        }
        for upgrade_id, level in self.upgrade_levels.items():
            if upgrade_id in LEGACY_UPGRADE_IDS:
                continue
            if level > expected_caps.get(upgrade_id, 1):
                raise SaveDataError(f"升級 {upgrade_id} 超過目前購買上限")

    @classmethod
    def default(cls, *, config: ProgressionConfig = DEFAULT_CONFIG) -> "SaveProfile":
        """建立一份新的空白 Profile。"""

        profile = cls(
            schema_version=SCHEMA_VERSION,
            coins=0,
            rebirth_count=0,
            max_aircraft_count=config.maximum_aircraft_count(0),
            upgrade_levels={},
            upgrade_caps={},
            unlocked_weapons=list(config.initial_unlocked_weapons),
            rebirth_available=False,
            last_completed_a_b=None,
            config=config,
        )
        return profile

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        config: ProgressionConfig = DEFAULT_CONFIG,
    ) -> "SaveProfile":
        """嚴格從 JSON 物件建立 Profile。"""

        if not isinstance(value, Mapping):
            raise SaveDataError("存檔根資料必須是 JSON 物件")
        required = {
            "schema_version",
            "coins",
            "rebirth_count",
            "max_aircraft_count",
            "upgrade_levels",
            "upgrade_caps",
            "unlocked_weapons",
            "rebirth_available",
            "last_completed_a_b",
        }
        missing = sorted(required.difference(value.keys()))
        if missing:
            raise SaveDataError(f"存檔缺少必要欄位：{', '.join(missing)}")
        if value.get("schema_version") != SCHEMA_VERSION:
            raise SaveDataError("不支援的存檔結構版本")

        # 先使用指定設定驗證，最後再用相同設定建立正規化 Profile。
        coins = _require_non_negative_int(value["coins"], "coins")
        rebirth_count = _require_non_negative_int(value["rebirth_count"], "rebirth_count")
        stored_maximum = _require_int(value["max_aircraft_count"], "max_aircraft_count")
        if stored_maximum < 1:
            raise SaveDataError("max_aircraft_count 必須為正整數")
        levels = _normalize_levels(value["upgrade_levels"])
        caps = _normalize_caps(value["upgrade_caps"])
        weapons = _normalize_weapons(value["unlocked_weapons"])
        rebirth_available = value["rebirth_available"]
        if not isinstance(rebirth_available, bool):
            raise SaveDataError("rebirth_available 必須是布林值")
        last_completed = value["last_completed_a_b"]
        if last_completed is not None and not isinstance(last_completed, str):
            raise SaveDataError("last_completed_a_b 必須是字串或 null")
        if last_completed is not None:
            last_completed = last_completed.strip()
        _validate_last_completed(last_completed)

        expected_caps = derive_upgrade_caps(rebirth_count, config=config)
        expected_caps.update(
            {
                upgrade_id: caps[upgrade_id]
                for upgrade_id in LEGACY_UPGRADE_IDS
                if upgrade_id in caps
            }
        )
        for upgrade_id, level in levels.items():
            if upgrade_id in LEGACY_UPGRADE_IDS:
                continue
            if level > expected_caps.get(upgrade_id, 1):
                raise SaveDataError(f"升級 {upgrade_id} 超過目前購買上限")
        # 保存的 max A/caps 可是舊快照；來源欄位是 rebirth_count。
        profile = cls(
            schema_version=SCHEMA_VERSION,
            coins=coins,
            rebirth_count=rebirth_count,
            max_aircraft_count=config.maximum_aircraft_count(rebirth_count),
            upgrade_levels=levels,
            upgrade_caps=expected_caps,
            unlocked_weapons=weapons,
            rebirth_available=rebirth_available,
            last_completed_a_b=last_completed,
            config=config,
        )
        return profile

    def clone(self) -> "SaveProfile":
        """回傳不共用可變欄位的複本。"""

        return deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        """轉為可直接交給 `json.dump` 的資料。"""

        return {
            "schema_version": SCHEMA_VERSION,
            "coins": self.coins,
            "rebirth_count": self.rebirth_count,
            "max_aircraft_count": self.max_aircraft_count,
            "upgrade_levels": dict(sorted(self.upgrade_levels.items())),
            "upgrade_caps": dict(sorted(self.upgrade_caps.items())),
            "unlocked_weapons": list(self.unlocked_weapons),
            "rebirth_available": self.rebirth_available,
            "last_completed_a_b": self.last_completed_a_b,
        }


@dataclass(frozen=True)
class SaveLoadResult:
    """讀取單一欄位的可診斷結果。"""

    slot_id: int
    profile: SaveProfile
    status: str
    path: Path
    warning: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {"empty", "valid"}

    @property
    def is_empty(self) -> bool:
        return self.status == "empty"

    @property
    def is_corrupt(self) -> bool:
        return self.status == "corrupt"

    @property
    def value(self) -> SaveProfile:
        """提供給偏好 value 命名的呼叫端的相容別名。"""

        return self.profile


@dataclass(frozen=True)
class SaveResult:
    """保存單一欄位的結果。"""

    slot_id: int
    success: bool
    path: Path
    error: Optional[str] = None
    warning: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.success


@dataclass(frozen=True)
class SaveDeleteResult:
    """刪除單一存檔欄位的結果。"""

    slot_id: int
    success: bool
    path: Path
    status: str
    error: Optional[str] = None

    @property
    def deleted(self) -> bool:
        return self.success and self.status == "deleted"

    @property
    def is_empty(self) -> bool:
        return self.status == "empty"


class SaveStore:
    """管理五個互不影響的 JSON 存檔欄位。"""

    def __init__(
        self,
        root: Optional[str | os.PathLike[str]] = None,
        *,
        config: ProgressionConfig = DEFAULT_CONFIG,
    ) -> None:
        if root is None:
            app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            root = (
                Path(app_data) / "AirDefense"
                if app_data
                else Path.home() / "AppData" / "Local" / "AirDefense"
            )
        self.root = Path(root)
        self.config = config

    def validate_slot_id(self, slot_id: int) -> int:
        if isinstance(slot_id, bool) or not isinstance(slot_id, int):
            raise ValueError("存檔欄位必須是 1 到 5 的整數")
        if not 1 <= slot_id <= SLOT_COUNT:
            raise ValueError("存檔欄位必須是 1 到 5")
        return slot_id

    def slot_path(self, slot_id: int) -> Path:
        slot = self.validate_slot_id(slot_id)
        return self.root / SLOT_FILE_TEMPLATE.format(slot_id=slot)

    def load_slot(self, slot_id: int) -> SaveLoadResult:
        slot = self.validate_slot_id(slot_id)
        path = self.slot_path(slot)
        if not path.exists():
            return SaveLoadResult(slot, SaveProfile.default(config=self.config), "empty", path)
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            profile = SaveProfile.from_dict(raw, config=self.config)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            reason = str(exc) or exc.__class__.__name__
            warning = f"存檔 {slot} 無法讀取，已使用安全預設資料；原始檔案已保留。原因：{reason}"
            return SaveLoadResult(
                slot,
                SaveProfile.default(config=self.config),
                "corrupt",
                path,
                warning=warning,
                error=reason,
            )
        return SaveLoadResult(slot, profile, "valid", path)

    def save_slot(self, slot_id: int, profile: SaveProfile) -> SaveResult:
        slot = self.validate_slot_id(slot_id)
        path = self.slot_path(slot)
        try:
            if not isinstance(profile, SaveProfile):
                raise SaveDataError("profile 必須是 SaveProfile")
            # 重新建立一次以檢查外部直接修改的可變欄位，並正規化可推導快照。
            valid_profile = SaveProfile.from_dict(profile.to_dict(), config=self.config)
            self.root.mkdir(parents=True, exist_ok=True)
            temp_path: Optional[Path] = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=str(self.root),
                    prefix=f".slot-{slot}-",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temp_path = Path(handle.name)
                    json.dump(
                        valid_profile.to_dict(),
                        handle,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=False,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, path)
                temp_path = None
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            reason = str(exc) or exc.__class__.__name__
            return SaveResult(slot, False, path, error=reason)
        return SaveResult(slot, True, path)

    def delete_slot(self, slot_id: int) -> SaveDeleteResult:
        """刪除指定欄位；不存在時安全回報空白，不碰其他欄位。"""

        slot = self.validate_slot_id(slot_id)
        path = self.slot_path(slot)
        if not path.exists():
            return SaveDeleteResult(slot, False, path, "empty")
        try:
            path.unlink()
        except OSError as exc:
            reason = str(exc) or exc.__class__.__name__
            return SaveDeleteResult(slot, False, path, "failed", error=reason)
        return SaveDeleteResult(slot, True, path, "deleted")

    # 讓流程層可使用較語意化的名稱。
    def load_profile(self, slot_id: int) -> SaveLoadResult:
        return self.load_slot(slot_id)

    def save_profile(self, slot_id: int, profile: SaveProfile) -> SaveResult:
        return self.save_slot(slot_id, profile)

    def delete_profile(self, slot_id: int) -> SaveDeleteResult:
        return self.delete_slot(slot_id)

    def list_slots(self) -> tuple[SaveLoadResult, ...]:
        return tuple(self.load_slot(slot_id) for slot_id in range(1, SLOT_COUNT + 1))


def _normalize_levels(value: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise SaveDataError("upgrade_levels 必須是物件")
    result: dict[str, int] = {}
    for raw_id, raw_level in value.items():
        if not isinstance(raw_id, str):
            raise SaveDataError("升級 ID 必須是字串")
        upgrade_id = normalize_upgrade_id(raw_id)
        if upgrade_id not in KNOWN_UPGRADE_IDS:
            raise SaveDataError(f"未知的升級 ID：{raw_id}")
        level = _require_non_negative_int(raw_level, f"upgrade_levels.{raw_id}")
        if level:
            result[upgrade_id] = level
        else:
            result.setdefault(upgrade_id, 0)
    return result


def _normalize_caps(value: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise SaveDataError("upgrade_caps 必須是物件")
    result: dict[str, int] = {}
    for raw_id, raw_cap in value.items():
        if not isinstance(raw_id, str):
            raise SaveDataError("升級上限 ID 必須是字串")
        upgrade_id = normalize_upgrade_id(raw_id)
        if upgrade_id not in KNOWN_UPGRADE_IDS:
            raise SaveDataError(f"未知的升級上限 ID：{raw_id}")
        cap = _require_non_negative_int(raw_cap, f"upgrade_caps.{raw_id}")
        result[upgrade_id] = cap
    return result


def _normalize_weapons(value: list[str] | tuple[str, ...]) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise SaveDataError("unlocked_weapons 必須是陣列")
    result: list[str] = []
    for weapon in value:
        if not isinstance(weapon, str):
            raise SaveDataError("武器 ID 必須是字串")
        weapon_id = weapon.strip()
        if weapon_id not in KNOWN_WEAPONS:
            raise SaveDataError(f"未知的武器 ID：{weapon}")
        if weapon_id not in result:
            result.append(weapon_id)
    return result


def _validate_last_completed(value: Optional[str]) -> None:
    if value is None:
        return
    if re.fullmatch(r"[1-9][0-9]*-[1-9][0-9]*", value.strip()) is None:
        raise SaveDataError("last_completed_a_b 必須使用 a-b 格式")
    try:
        LevelKey.parse(value)
    except ValueError as exc:
        raise SaveDataError("last_completed_a_b 的 b 超出範圍") from exc


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SaveDataError(f"{name} 必須是整數")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    result = _require_int(value, name)
    if result < 0:
        raise SaveDataError(f"{name} 不可為負數")
    return result


__all__ = [
    "SCHEMA_VERSION",
    "SLOT_COUNT",
    "SaveDataError",
    "SaveProfile",
    "SaveLoadResult",
    "SaveResult",
    "SaveDeleteResult",
    "SaveStore",
]
