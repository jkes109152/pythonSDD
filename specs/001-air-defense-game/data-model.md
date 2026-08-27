# Data Model: 3D 防空守衛無限模式

## Overview

本功能採單人、單場景、記憶體內本局狀態。遊戲同時間只存在一架有效戰鬥機與其對應的一組地面乘員；清除該組乘員後才建立下一架戰鬥機。玩家使用兩格物品欄切換武器：空襲階段按 `1` 選用防空炮，地面戰階段按 `2` 選用狙擊槍。玩家若仍持有狙擊槍，下一架仍會建立，但在切回防空炮前不能鎖定或擊落它。

## Game State

### `GamePhase`

| State | Entry | Allowed transitions | Player input |
|---|---|---|---|
| `MAIN_MENU` | 程式啟動或返回主選單 | `AIRSTRIKE` | 點擊開始/離開按鈕、`Enter`/`Space`/`Q`/`Escape` |
| `AIRSTRIKE` | 新局開始或地面戰清場 | `GROUND_COMBAT`, `GAME_OVER` | 移動、瞄準、物品欄切換、發射 |
| `GROUND_COMBAT` | 當架飛機被擊落且乘員生成 | `AIRSTRIKE`, `GAME_OVER` | 移動、瞄準、物品欄切換、射擊 |
| `GAME_OVER` | 飛機撞樓或玩家生命值歸零 | `MAIN_MENU` | 返回主選單 |

本功能不建立 `VICTORY` 或球體生命週期狀態；這是 [spec.md](./spec.md) 所記錄的 Principle IV 功能範圍例外。四個狀態仍必須具備明確進入、更新停止、重置與退出條件。

進入 `GAME_OVER` 後，所有遊戲世界更新、射擊、生成與互動都停止。返回 `MAIN_MENU` 時清除本局所有 Entity 參照與統計。

## Entities

### Player

| Field | Type | Rules |
|---|---|---|
| `position` | 3D position | 受場景碰撞限制；新局回到防守點 |
| `health` | integer | 新局為滿值；敵人命中時下降；小於等於零進入 `GAME_OVER` |
| `held_weapon` | `None \| ANTI_AIRCRAFT \| SNIPER` | 同時最多持有一把武器 |
| `aim_mode` | enum | 依目前武器切換防空或狙擊瞄準介面 |

### Inventory

| Field | Type | Rules |
|---|---|---|
| `slots` | fixed mapping | `1` 對應防空炮，`2` 對應狙擊槍；兩個欄位在 HUD 持續顯示 |
| `selected_weapon` | nullable weapon enum | 數字鍵直接選取，不受與場景武器展示架的距離限制 |
| `phase_restriction` | phase mapping | 空襲階段只允許選用防空炮，地面戰階段只允許選用狙擊槍；不適用按鍵不改變狀態 |

### WeaponPickup

| Field | Type | Rules |
|---|---|---|
| `kind` | weapon enum | 防空炮或狙擊槍 |
| `world_position` | 3D position | 用於場景展示或 E/G 傳統互動；物品欄選取不依賴此位置 |
| `holder` | `None \| Player` | 直接選取或拾取後轉為玩家持有；丟下後回到世界 |
| `available` | boolean | 控制場景展示與傳統拾取；物品欄欄位本身始終可供對應階段選取 |

### AntiAircraftGun

| Field | Type | Rules |
|---|---|---|
| `lock_state` | `WHITE \| RED_TRACKING \| GREEN_READY` | 決定 HUD 顏色與是否可發射 |
| `lock_elapsed` | seconds | 只有中心 ray 未遮擋命中當前飛機時累積；中斷立即歸零 |
| `target_aircraft_id` | nullable identifier | 只能指向目前唯一有效戰鬥機 |
| `fire_cooldown` | seconds | 發射後阻止重複觸發；彈藥不耗盡 |

### SniperRifle

| Field | Type | Rules |
|---|---|---|
| `scope_enabled` | boolean | 由右鍵切換；只影響狙擊瞄準視覺 |
| `fire_cooldown` | seconds | 冷卻期間不能再次發射；彈藥不耗盡 |
| `last_hit` | nullable crew identifier | 有效命中一名存活乘員時更新並立即擊倒 |

### TargetBuilding

| Field | Type | Rules |
|---|---|---|
| `collision_volume` | 3D volume | 戰鬥機進入即觸發空襲失敗 |
| `is_protected` | boolean | 本局失敗前為 true；不設計建築損壞階段 |

### Aircraft

| Field | Type | Rules |
|---|---|---|
| `id` | identifier | 本局唯一 |
| `phase` | `APPROACHING \| LOCKED \| DESTROYED \| IMPACTED` | 只允許向前推進，不重複結算 |
| `target_building_id` | identifier | 指向唯一目標大樓 |
| `path_progress` | normalized number | 沿直線自殺式航線接近大樓 |
| `crew_spawned` | boolean | 墜機事件最多設為 true 一次 |

### GroundEncounter

| Field | Type | Rules |
|---|---|---|
| `aircraft_id` | identifier | 指向觸發此遭遇的戰鬥機 |
| `crew_count` | integer | 每次隨機產生 2–5 名 |
| `crew_ids` | list of identifiers | 只包含此飛機的乘員，不接受地面增援 |
| `cleared` | boolean | 所有乘員倒下後設為 true，觸發下一次空襲 |

### CrewMember

| Field | Type | Rules |
|---|---|---|
| `id` | identifier | 遭遇內唯一 |
| `encounter_id` | identifier | 不可跨遭遇移動或計分 |
| `alive` | boolean | 狙擊槍有效命中後變為 false，只計分一次 |
| `cover_node` | nullable identifier | 由預設掩體節點指定 |
| `squad_role` | enum | 掩護射手或推進射手，用於分組行為 |
| `behavior_state` | enum | `IN_COVER`, `ADVANCING`, `RELOCATING`；限制在預設掩體節點間轉移 |
| `attack_cooldown` | seconds | 控制對玩家的射擊間隔 |

### SessionStats

| Field | Type | Update rule |
|---|---|---|
| `survival_seconds` | number | 遊戲進行中累積；失敗時固定 |
| `aircraft_destroyed` | integer | 每架戰鬥機成功擊落只增加一次 |
| `enemies_defeated` | integer | 每名乘員被擊倒只增加一次 |
| `failure_reason` | `BUILDING_IMPACT \| PLAYER_DEAD \| None` | 進入失敗時設定 |

## State Transition Rules

1. `MAIN_MENU → AIRSTRIKE`: 玩家點擊開始按鈕或按下開始快捷鍵後，建立玩家、場景、武器、第一架戰鬥機與空白統計。
2. `AIRSTRIKE → GROUND_COMBAT`: 綠框狀態下發射導引彈並完成戰鬥機擊落；建立一次 `GroundEncounter`。
3. `AIRSTRIKE → GAME_OVER`: 戰鬥機先進入目標大樓碰撞體；只結算一次 `BUILDING_IMPACT`。
4. `GROUND_COMBAT → AIRSTRIKE`: 當前 `GroundEncounter.cleared` 變為 true；清除當前乘員並立即建立下一架戰鬥機。
5. `AIRSTRIKE/GROUND_COMBAT → GAME_OVER`: 玩家生命值歸零；只結算一次 `PLAYER_DEAD`。
6. `GAME_OVER → MAIN_MENU`: 玩家點擊返回按鈕或按下返回快捷鍵；所有本局狀態釋放，下一局不沿用上一局統計。
7. 乘員行為：生成時為每名乘員指定 `cover_node`、`squad_role` 與 `behavior_state`；掩護射手保持在目前掩體並於攻擊冷卻完成且視線有效時射擊，推進射手每 2.0 秒才可嘗試依序移動到下一個預設掩體節點，抵達後才射擊，不建立臨時增援路徑。
8. 若 `GROUND_COMBAT → AIRSTRIKE` 時玩家仍持有 `SNIPER`，保留該武器且禁止防空鎖定/發射；HUD 提示使用物品欄按 `1` 切換防空炮，飛機仍依正常航線前進並可因撞樓觸發 `BUILDING_IMPACT`。
9. 物品欄切換不建立第二把同時持有的武器；切換時先釋放目前選取欄位，再裝備目標欄位，不在地面生成自動丟棄物。
10. 事件回呼若帶有 `aircraft_id` 或 `encounter_id`，只有與目前作用中的物件識別碼相符時才可轉移狀態；延遲或重複的舊物件事件必須忽略。

## Invariants

- 不可在 `GREEN_READY` 以外發射防空炮。
- 不可同時持有防空炮與狙擊槍。
- 物品欄固定為 `1=防空炮`、`2=狙擊槍`；不適用當前階段的欄位按鍵不得改變持有武器。
- 不可同時存在兩架有效空襲戰鬥機。
- 每架戰鬥機最多產生一次、且只產生 2–5 名乘員。
- 每名乘員必須有一個預設 `cover_node` 與一個 `squad_role`；推進行為不得離開預設掩體節點集合。
- 玩家死亡或大樓碰撞後不可再更新敵人、飛機、武器或統計。
- 每個擊落、擊倒與失敗事件最多更新一次統計。
- 舊飛機或舊乘員遭遇的延遲事件不可改變目前循環的階段或統計。
