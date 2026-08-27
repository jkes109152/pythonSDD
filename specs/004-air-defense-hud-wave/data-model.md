# Data Model: 防空 HUD、動態鎖定與整波敵機

## Scope

本模型將「一波的遊戲狀態」、「純規則的鎖定狀態」與「只負責顯示的 UI／效果狀態」分開。數值由 domain 層維護，`scene.py` 只保存 Ursina entity 的對應表，`hud.py` 只接收已整理的 view；不把 Entity、camera 或全域可變物件放入 `state.py`／`rules.py`。

## Existing enums retained

`GamePhase`、`SessionEvent`、`WeaponKind`、`AircraftType`、`AircraftPhase`、`LockState`、`FailureReason`、`SquadRole` 與 `CrewBehaviorState` 延續現有定義。新增狀態時優先擴充既有 enum，不以任意字串表示 transition。

## Wave plan and runtime

### `WavePlan`

既有 immutable roster 定義，欄位維持：

| Field | Type | Rule |
|---|---|---|
| `wave_number` | positive `int` | 顯示於右上卡片 |
| `aircraft_count` | positive `int` | 必須等於 `len(roster)` |
| `aircraft_cap` | positive `int` | 延續既有波次成長規則 |
| `is_boss_wave` | `bool` | 延續既有 Boss 波規則 |
| `roster` | `tuple[AircraftType, ...]` | 固定順序，供 ID 與 formation 排序 |

### `WaveProgress`

保留作為波次顯示與 director 交界的 mutable progress。`wave_number`、`aircraft_count`、`aircraft_cap`、`is_boss_wave`、`roster` 延續既有欄位；`aircraft_index` 只能作為舊呼叫者的相容性 view，不再作為空戰轉換條件。顯示值由 runtime 的 status map 計算。

### `WaveRuntime`

建議新增於 `state.py` 的同波 runtime 集合，避免把整波規則散落在 controller：

| Field | Type | Meaning |
|---|---|---|
| `wave` | `WaveProgress` | 本波 roster 與波次 metadata |
| `aircraft_ids` | `tuple[str, ...]` | 依 roster 順序產生的唯一 ID |
| `aircraft_statuses` | `dict[str, AircraftPhase]` | 波次層級的 canonical status ledger；只能由 runtime transition／sync API 更新 |
| `aircraft_types` | `dict[str, AircraftType]` | 右上卡片與地面遭遇使用 |
| `active_target_id` | `Optional[str]` | 防空目前黏著目標 |
| `ground_encounter_id` | `Optional[str]` | 全波地面遭遇 ID，空戰期間為 `None` |

Required derived views／methods：

- `alive_aircraft_ids`：status 為 `APPROACHING` 或 `LOCKED` 的 ID，依原始順序回傳。
- `remaining_aircraft_count`：`len(alive_aircraft_ids)`，範圍為 `[0, aircraft_count]`。
- `alive_ratio`：`remaining_aircraft_count / aircraft_count`，總數保證大於零。
- `all_aircraft_destroyed`：只有每個 ID 都為 `DESTROYED` 才為 true；`IMPACTED` 只觸發失敗，不可完成波次。
- `sync_aircraft_phase(aircraft_id, phase)`：將對應 `Aircraft` 完成自身 transition 後的 phase 寫入唯一受控 ledger；禁止 controller 直接修改 `aircraft_statuses`。
- `mark_destroyed(aircraft_id)`／`mark_impacted(aircraft_id)`：以 ID 去重並回報是否是第一次有效 transition，內部透過同一個 sync／transition path 更新 ledger。

Ownership：`Aircraft.phase` 是單架物件自身移動／生命行為的 authoritative state；`WaveRuntime.aircraft_statuses` 是波次 UI、alive count 與 phase transition 的 authoritative snapshot，不能被另一處獨立計算。每次 `Aircraft.advance()`、`take_damage()` 或 `impact()` 回報 transition 後，controller MUST 呼叫 `sync_aircraft_phase(...)`；測試以這個 API 驗證兩者同步。`LockOnTracker.target_aircraft_id` 是鎖定目標的唯一 authoritative owner，`WaveRuntime.active_target_id` 與 `GameSession` 的舊 scalar 只能是由 controller 更新的 read-only mirror／compatibility view。

Invariants：`aircraft_ids` 不重複；所有 status/type map key 都必須屬於該 tuple；一架飛機終止後不得回到活動狀態；任一 `IMPACTED` 使 session 進入 `GAME_OVER`，不再建立 ground encounter；任何 UI／transition 不得直接讀取未同步的 entity phase。

### `Aircraft`

延續現有 engine-independent entity，必要時補充 formation 與顯示所需欄位：`id`、`aircraft_type`、position／forward／speed／flight progress、health／max health、`AircraftPhase`。每架物件獨立 advance、take damage、destroy、impact；controller 在這些受控方法回傳的 transition 後透過 `WaveRuntime.sync_aircraft_phase(...)` 同步 wave ledger。所有同波飛機在同一個 spawn frame 建立，但各自使用水平 offset 與獨立位置／閃避時間。

## Aggregate ground encounter

### `GroundEncounter`

保留 `crew`、`cleared`、`boss_id`、city damage 累積與既有查找行為，並新增 `source_aircraft_ids: tuple[str, ...]`。對整波地面戰，`aircraft_id` 固定使用 `wave-<wave_number>`，因此 `GroundEncounter.id` 固定為 `encounter:wave-<wave_number>`，不再代表單一已擊落飛機；`create_for_aircraft(...)` 保留為相容性 wrapper，新的主要入口為明確簽名的 `create_for_wave(...)`。

`EncounterFactory.create_for_wave(wave_number, aircraft_ids, aircraft_types, random_source=None) -> GroundEncounter` 的 contract 為：`aircraft_ids` 是與 roster 相同順序的非空 tuple；`aircraft_types` 是以每個 ID 為 key 的 mapping，key 集合必須完全相等；`random_source` 若提供則必須實作既有 `randint`，未提供才使用 module random。方法使用 `aircraft_ids` 順序建立 crew，NORMAL 每個 source ID 最多消耗一次 `randint`，固定人數的 type 不消耗 random，並使用 `wave-<wave_number>` 作 group key。

合併規則：

- `NORMAL` 使用既有隨機範圍。
- `MANPOWER_SUPPORT` 使用既有固定人數。
- `FAST` 產生零人員。
- `ARMORED_BOSS` 保留一名 Boss 及既有 Boss HP。
- crew ID 以 source aircraft ID 作為 prefix，避免不同飛機的成員碰撞；`source_aircraft_ids` 保留完整輸入順序。

若合併後 crew 為零，controller 不建立空的 ground phase，而是直接要求 `WaveDirector` 產生下一個 `WavePlan`。

## Anti-air target and lock state

### `AircraftScreenTarget`

延續 `scene.py` 的 immutable projection view，補充 `aircraft_id`，並將 `in_lock_zone` 的語意改為 `in_lock_frame`（可保留 property alias 供舊程式暫時使用）：

| Field | Type | Meaning |
|---|---|---|
| `aircraft_id` | `str` | 對應同波 runtime 的唯一目標 |
| `visible` | `bool` | camera raycast／projection 可見 |
| `screen_position` | `tuple[float, float]` | viewport pixel 座標 |
| `hud_position` | `tuple[float, float]` | camera UI normalized 座標 |
| `screen_radius` | `float` | 供 HUD target marker 使用 |
| `distance_from_center` | `float` | 目標選擇 tie-break 主鍵 |
| `in_lock_frame` | `bool` | 可見且中心位於白框內，邊界包含在內 |

### `LockOnTracker`

既有 tracker 擴充為「單一 target ID + 時間狀態」：

| Field | Type | Range / default |
|---|---|---|
| `target_aircraft_id` | `Optional[str]` | `None` when no target |
| `lock_elapsed` | `float` | `[0, 3.0]` seconds |
| `lock_duration` | `float` | `3.0` seconds |
| `decay_duration` | `float` | `0.75` seconds |
| `target_visible` | `bool` | current projection visibility |
| `target_in_frame` | `bool` | current rectangle membership |
| `scope_enabled` | `bool` | false immediately resets lock |
| `state` | `LockState` | `WHITE`, `RED_TRACKING`, `GREEN_READY` |

Required operations：

- `set_target(target_id)`：ID 不同時 reset progress；同 ID 不重置。
- `clear_target()`／`reset()`：清除 ID、progress、zone flags 與 fire gate。
- `update(target_visible, target_in_frame, delta_seconds)`：scope 開啟且 target 在框內時以 real time 累積；離框或不可見時按 `lock_duration / decay_duration` 線性衰減；progress 永遠 clamp 到 `[0, 1]`。
- `fireable`：只有 `GREEN_READY`、target 可見、target 在白框內、scope 開啟且 target ID 存在時為 true；武器自身 CD 另由 weapon rule 判斷。
- `flash_visible(...)`：沿用既有 0.12 秒閃爍語意；完成事件先呈現短暫紅閃，穩定完成後小準心為綠色。

Transitions：

1. scope 關閉、武器切換、進入 ground、game over 或 return menu → immediate reset。
2. 無 target／progress 0 → white，小準心在框中心。
3. 同一 target 在框內 → progress 增加；未滿為 red tracking，滿為 green ready。
4. 同一 target 離框或暫時不可見 → progress 線性衰減；即使數值曾為 100%，fireable 也為 false。
5. 離框期間另一目標進框 → 保留原 target；只有原 target 終止或 progress 歸零後才允許新選取。

### Target selection and reticle view

`select_lock_target(candidates, current_target_id, progress)` 使用以下順序：

1. 若 current target 仍未終止且 `progress > 0`，直接保留。
2. 否則只從 `visible and in_lock_frame` candidates 選擇。
3. 以 `distance_from_center` 最小者為主鍵，以 `aircraft_id` 字典序為 deterministic tie-break。

`reticle_position_for_progress(frame_center, frame_bounds, target_position, progress)` 將目標位置 clamp 到白框，再以 progress 從中心線性插值到 clamp 後的位置；無 target 或 progress 為零時回傳 frame center。這個純函式不得讓小準心超出框線。

## Weapon cooldown view

武器物件仍各自擁有 `fire_cooldown`；不得在 HUD 再開一個計時器。`WeaponCooldownView` 是由目前武器推導的短暫 view：

| Field | Type | Rule |
|---|---|---|
| `weapon` | `Optional[WeaponKind]` | 空手／非遊戲階段為 `None` |
| `remaining_seconds` | `float` | clamp 到 `[0, duration]` |
| `duration_seconds` | `float` | AA 1.25、sniper 0.75、pistol 0.20 |
| `fill_ratio` | `float` | `1 - remaining / duration`，ready 時為 1 |
| `ready` | `bool` | remaining 為 0 |

射擊成功時，武器物件先設定自己的 duration，HUD 下一次 refresh 看到空條；冷卻經過後填滿。切換武器只改 view，不互相複製 cooldown；同 phase 切換保留每種武器自己的剩餘 CD。`START_GAME`、進入下一波、`GAME_OVER` 與 `RETURN_TO_MENU` 必須透過集中 reset helper 將三種武器 CD 設為 0；關閉 scope 不重置 weapon CD。

## HUD status-card view

HUD 讀取下列 derived values，不直接讀取多架 entity：

- `PlayerStatusView`: `health`、`max_health`、`health_ratio`，顯示紅色 heart icon、數值與 bar。
- `CityStatusView`: `city_health`、`max_city_health`、`health_ratio`，顯示藍色 shield icon、百分比與 bar。
- `WaveStatusView`: `wave_number`、`aircraft_total`、`aircraft_alive`、`aircraft_ratio`、ordered dot statuses、roster-order `aircraft_type_labels` 與 `selected_aircraft_type`；alive（`APPROACHING`／`LOCKED`）為藍點，`DESTROYED` 與 `IMPACTED` 都為灰色 terminal dot，無目標為 `未選定`。`aircraft_type_labels` 只保留本波不重複種類，供右上清單同時顯示快速／普通／Boss 等類型。`IMPACTED` 不可觸發下一波，且 game-over snapshot 凍結。

所有比例與文字數值在 view 層 clamp；卡片、bar track 與武器槽位的背景透明，主要資訊文字為白色大字體；卡片超過單行容量時依固定最大寬度縮小 dot 或換行，不覆蓋中央 lock／CD UI、Boss HP、FPS、統計與武器欄。

## `GroundTracerEffect`

短壽命視覺資料放在 `entities.py`：`id`、`start_position`、`target_position`、`remaining_seconds`、`lifetime_seconds`、`travel_progress`。預設 lifetime 為 `0.18` 秒；`advance(delta_seconds)` 以 `travel_progress = elapsed / lifetime` 線性移動 head 從 start 到 target，tail 保留固定的視覺長度，並在 progress 到 1 時 expired。它只產生黃色 elongated mesh 的位置／朝向與到期清除，不包含 damage、collision、命中統計或攻擊 cooldown。建立時機是既有 `CrewMember.ready_to_attack()` 通過且 `mark_attacked()` 已執行的同一個 controller step。

## Reset and terminal invariants

- Building impact 是全域 terminal event：清除／停止所有飛機、飛彈、ground encounter、lock target、scope、tracer 與波次更新。
- 全波飛機 destroyed 才能建立一個 aggregate encounter；aggregate encounter cleared 才能建立下一波。
- 目標 destroyed、impact、波次轉換、weapon switch、scope close、game over 與 menu reset 都不得讓 lock target、reticle progress 或 fire gate 洩漏到下一生命週期。
- 每個 transition 以 event ID／aircraft ID／encounter ID 去重；重複 callback 不得重複統計、生成敵人或切換 phase。
