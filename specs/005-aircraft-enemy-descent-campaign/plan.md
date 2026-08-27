# Implementation Plan: 飛機擊落後敵人降落戰役

**Branch**: `005-aircraft-enemy-descent-campaign` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/005-aircraft-enemy-descent-campaign/spec.md`

## Summary

將目前「全波飛機摧毀後才建立地面遭遇」改為「每架飛機擊落時立即建立自己的降落敵人批次」。同一波保留一個 aggregate `GroundEncounter`，但每個來源飛機的 batch 有獨立來源、分散位置與 4 秒降落計時；降落期間可被玩家攻擊，落地後沿用既有地面行為。

`WaveDirector` 改為固定 18 波 roster，`GameSession` 新增明確的 `HYBRID_COMBAT` 與 `VICTORY` lifecycle。純狀態與規則留在 engine-independent domain modules，Ursina 只負責 aircraft／crew entity、射線與視覺更新；不新增套件、服務或素材。

## Technical Context

**Language/Version**: Python 3.12+；workspace baseline 為 Python 3.13.5，符合憲章 Python 3.11+ minimum

**Primary Dependencies**: `ursina==8.3.0`、Python standard library `dataclasses`／`enum`／`unittest`；不新增第三方依賴

**Storage**: N/A；波次、降落、遭遇與勝利均為單次遊戲 session 的記憶體狀態

**Testing**: `python -m compileall -q air_defense tests`、`python -m unittest discover -s tests -p "test_*.py" -v`、headless pure-rule tests、Ursina app construction smoke、手動 gameplay／FPS 驗證

**Target Platform**: Windows desktop、offline single-player、keyboard + mouse；沿用目前 1280×720 視窗與第一人稱 camera input

**Project Type**: 3D desktop game application

**Performance Goals**: 維持既有 60 FPS 目標；以 6 架同波 aircraft／最多 6 枚 guided missile 與最多 36 名 simultaneous crew／6 條 tracer 做壓力場景，暖機 5 秒後以 1 秒間隔觀測 30 秒，最低觀測 FPS MUST >= 60；無 GUI 時記錄限制與 automated evidence，不宣稱未測量結果

**Constraints**: 沿用既有 Ursina 3D runtime 與 asset-free domain boundary；降落時間 4.0 秒 ± 0.25 秒；水平 spread 半徑最多 2.5 world units；落地保留擊落點 X/Z；降落中不可移動、攻擊或造成城市傷害；不可加入倒數／進度 HUD；第 18 波後不可建立第 19 波；保留既有 impact、weapon damage、ground AI、event dedupe 與 reset 行為

**Scale/Scope**: 一個 session 同時處理固定波次的一組 aircraft、每架 aircraft 的 drop batch、一個 aggregate ground encounter、最多一個 sticky anti-air target、各自的降落動畫與有限壽命視覺效果；只修改 `air_defense` 與其測試／feature docs，不改造 day1/day2 其他專案

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Phase 0 gate: PASS

| Principle / gate | Evidence |
|---|---|
| I. 可讀性優先，循序抽象 | 沿用現有 shallow `air_defense` modules；只新增降落狀態、固定 wave data、aggregate reinforcement 與明確 lifecycle helpers，不引入新 framework 或 service layer。 |
| II. 遊戲物件封裝狀態與行為 | `CrewMember` 負責自己的降落／落地狀態，`Aircraft` 保留飛行／生命，`GroundEncounter` 保留 crew collection；跨物件波次完成由 `WaveRuntime`／`GameSession` 集中協調。 |
| III. 小步驟開發，每項行為可驗證 | 先測試 fixed roster、descent interpolation、batch merge、phase gates 與 clear conditions，再接入 scene 與 controller，最後做手動流程。 |
| IV. 遊戲迴圈順序與狀態轉移明確 | 計畫定義 aircraft advance → missile resolution → per-aircraft drop／crew update → ground damage／attack → wave completion 的順序，並處理 impact、duplicate callback、zero crew、final victory 與 reset。 |
| V. 範圍與依賴適當 | 既有 app 已使用 Ursina；本功能沿用已接受的 004 runtime 基線，不擴大技術例外、不新增依賴、資產、網路、存檔或輸入裝置。 |
| Existing runtime exception | `spec.md` 的 Runtime Governance Note 記錄了 Ursina 的既有範圍、理由、影響、風險與未來 adapter migration path；本功能不修改憲章原則，也不把例外擴大到其他專案。T001 前須取得專案負責人對此既有例外的明確同意。 |
| Spec / branch governance | 005 分支由 Spec Kit naming flow 對應建立，`spec.md` 已完成；004 已在 `main` 合併，既有 unrelated working-tree changes 不納入本 feature。 |

## Design Overview

### 1. Fixed campaign roster

`WaveDirector` 使用唯一的 18 波資料表，依 roster 順序建立 aircraft：

```text
1  普普
2  普特
3  特特
4  魔特
5  普普普
6  普普特
7  普特特
8  特特特
9  魔特特
10 普普普普
11 普普普特
12 普普特特
13 普特特特
14 特特特特
15 魔特特特
16 魔魔特特
17 魔魔魔特
18 魔魔魔魔
```

- `普` 對應 `NORMAL`，`魔` 對應 `ARMORED_BOSS`。
- `特` 依固定表中所有前置 `特` slot 的 1-based 全域序號交替分配：奇數序號為 `MANPOWER_SUPPORT`、偶數序號為 `FAST`；「摩」在 token normalization 時先轉為「魔」。這是純推導，不依賴 `plan_wave()` 呼叫順序。
- Boss slot 由前往後固定，`is_boss_wave` 由 roster 是否包含 Boss 推導。
- `plan_wave(wave_number, aircraft_count=None, cap=None)` 在沒有 override 時回傳 immutable 的固定 `WavePlan`；輸入小於 1 或大於 18 明確拒絕。明確提供 `aircraft_count`／`cap` 時只建立 deterministic synthetic headless fixture，不改變正式 campaign roster 或 successor。`next_progress()` 在第 18 波不可建立 successor，controller 改以 final-wave guard 進入 victory。
- 保留 `aircraft_cap` 欄位作為既有 compatibility view；固定戰役實際 aircraft count 最大為 4，測試可覆寫 count／cap 做壓力場景。

### 2. Session and wave lifecycle

新增 `GamePhase.HYBRID_COMBAT` 與 `GamePhase.VICTORY`，並調整 event guards：

```text
MAIN_MENU
  └─ START_GAME → AIRSTRIKE
       ├─ first non-empty drop while aircraft remain → HYBRID_COMBAT
       ├─ all aircraft destroyed with living/descent crew → GROUND_COMBAT
       ├─ all aircraft destroyed and no crew → next wave or VICTORY
       ├─ aircraft impact / player death / city destruction → GAME_OVER
       └─ ground clear + all aircraft destroyed → next wave or VICTORY
```

- `AIRSTRIKE` 表示本波尚未開始非空降落批次；空 batch 不啟動 hybrid。
- `HYBRID_COMBAT` 一旦本波第一批非空 drop 開始便保持到所有 aircraft resolve；若任一 aircraft 為 `IMPACTED`，立即進入 `GAME_OVER`，不再繼續成功清波判定。
- `GROUND_COMBAT` 表示所有 aircraft 狀態均為 `DESTROYED` 但 aggregate encounter 尚有降落或地面 crew；降落 crew 仍可被攻擊。
- `VICTORY` 只由第 18 波的「所有 aircraft 狀態均為 `DESTROYED`」且「encounter 沒有 alive crew」產生，停止遊戲更新並顯示勝利。
- `RETURN_TO_MENU` 同時接受 `GAME_OVER` 與 `VICTORY`，清除 dynamic entities、missiles、crew、wave runtime、weapon／scope state 與統計。
- `PLAYER_DIED`／`CITY_DESTROYED` 可從 `AIRSTRIKE`、`HYBRID_COMBAT` 或 `GROUND_COMBAT` 進入 `GAME_OVER`；降落中的 crew 不會自行造成城市傷害。

### 3. Per-aircraft drop batch and aggregate encounter

`WaveRuntime` 保留 ordered aircraft ledger，並新增 `drop_spawned_aircraft_ids` guarded source ledger 防止同一架飛機重複生成。`GroundEncounter` 保留一個 aggregate group，支援把新 batch 加入而不重置既有 crew。

Aggregate encounter 同時保留 source-scoped batch counters：每個來源 aircraft 有 `spawned_count`、`alive_count` 與 idempotent `cleared_count`；counter 由 crew stable ID 更新，可在多批次同時存在時分別查詢，不以 aggregate `cleared` 取代個別 batch 統計，也不新增獨立 drop manager。

擊落事件的固定處理順序：

1. 從 `Aircraft.position` 保存精確擊落位置。
2. 以 runtime 的 source ID 做一次性 `DESTROYED` transition 與 aircraft statistic。
3. 移除該 aircraft entity、其 target-bound missiles 與 lock target。
4. 若該 aircraft 的既有 composition 有 crew，factory 以 source ID、aircraft type、hit position 建立完整 batch；batch 成員同一 update boundary 加入 aggregate encounter。
5. 每名成員套用 deterministic spread offset：第 1 名為 `(0, 0)`，其後依固定順序使用半徑不超過 2.5 的 X/Z offset；start Y 為擊落高度，landing Y 為集中設定的 ground level。
6. 第一個非空 batch 使 scene 啟用 weapon rack、session 進入 hybrid（若仍有 aircraft），但不清除或暫停其他 aircraft。
7. 立即呼叫 wave completion guard；只有所有 aircraft 狀態均為 `DESTROYED` 且 aggregate crew 清除才可開始 next wave／victory，`IMPACTED` 只走 failure path。

Existing composition remains: `NORMAL` 由既有 0–3 random crew、`MANPOWER_SUPPORT` 6 crew、`FAST` 0 crew、`ARMORED_BOSS` 1 ground Boss。沒有 crew 的 source 仍記錄為已處理，但不建立空 encounter。

### 4. Crew descent behavior

`CrewBehaviorState` 新增 `DESCENDING`。`CrewMember` 保存：

- `source_aircraft_id`
- `descent_start_position`
- `landing_position`
- `descent_elapsed`
- `descent_duration`（預設 4.0 秒）
- `descent_offset`

`begin_descent()` 設定 start／landing、`DESCENDING` 與完整初始 attack cooldown；`advance_descent(delta_seconds)` 以 clamped linear interpolation 更新位置。當 elapsed 達 duration 時，位置固定在 landing target，狀態切換至既有 `IN_COVER`，後續交由 `advance_crew_behavior()` 處理。

在 `DESCENDING` 時：

- entity 保持 enabled 與 collider，狙擊／手槍 raycast 可以命中。
- `advance_crew_behavior()` 不得移動成員。
- `apply_city_damage()` 與 enemy attack loop 跳過成員。
- `damage_crew_member()` 可處理 `HYBRID_COMBAT`／`GROUND_COMBAT`；死亡立即標記、移除視覺 entity 並由 session event ledger 只計一次。

### 5. Controller and frame order

`AirDefenseGame.update()` 保持既有順序，將 gameplay branch 擴成 `AIRSTRIKE`、`HYBRID_COMBAT`、`GROUND_COMBAT`：

1. Tick transient effects、player position 與所有 weapon cooldown。
2. 在 gameplay phase tick session statistics。
3. `AIRSTRIKE`／`HYBRID_COMBAT` 先以穩定 ID 順序 advance 所有 alive aircraft；任一 impact 立即短路至 game over。
4. 更新 target projections、sticky lock 與 guided missiles；missile hit 走同一個 per-aircraft destroy handler。
5. 若 encounter 存在，逐名更新 descent；已落地成員才進入既有 ground movement、city damage、attack cooldown 與 tracer creation。
6. 更新 scene entity positions，移除死亡或 expired visual entities。
7. 執行 `can_complete_wave()`；若成立，清空本波 dynamic state，再由 director 建立下一波或 session 進入 victory。
8. Refresh HUD；`GAME_OVER`／`VICTORY` 只保留 frozen result view，不再更新 gameplay。

Controller 不直接修改 `WaveRuntime.aircraft_statuses` 或 crew alive flags 以外的 derived value；所有 transition 使用 named domain operation 與 stable event ID。

### 6. Weapons and scene targeting

- `inventory_selection_allowed()`、`can_fire_anti_air()`、`can_fire_sniper()`、`can_fire_pistol()` 將 `HYBRID_COMBAT` 加入適當 gate：hybrid 可使用三種武器，AA 仍只在尚有飛機時具有效目標。
- `crew_under_center()` 保持以 scene collider 查找 crew，因 airborne entity 仍使用同一模型與 collider；不建立第二套命中系統。
- `scene.create_crew_members(members)` 支援在 encounter 已存在時只新增本批成員；`update_crew()` 同時處理空中與地面位置。
- `WaveRuntime`／lock tracker／missiles 使用 source aircraft ID；crew 使用自身 stable ID；所有移除、scope close、phase change、reset 都清掉 stale references。
- weapon rack 在第一個非空 batch 建立時啟用；不新增降落 UI、倒數或進度條。

### 7. HUD and victory presentation

- Gameplay HUD 不新增 descent progress；只把已有 phase-aware inventory、reticle、weapon cooldown、wave status visibility 擴至 hybrid。
- 新增 victory presentation，顯示「你贏了」、本次統計與既有返回主選單按鈕；Enter／Escape 由 `AirDefenseGame.input()` 觸發同一 return callback。
- victory 與 game-over 的 dynamic gameplay entities、scope、lock、cooldown display 與 scene collision 都停止；返回主選單後沿用既有完整 reset。

## Public and Internal Interfaces

### Domain state and rules

- `GamePhase`: 新增 `HYBRID_COMBAT`、`VICTORY`。
- `SessionEvent`: 明確新增 `DROP_STARTED`、`WAVE_CLEARED` 與 `VICTORY`，並讓 `RETURN_TO_MENU`、player／city terminal guards 覆蓋新 phase。
- `WaveDirector.plan_wave(wave_number, aircraft_count=None, cap=None) -> WavePlan`: 無 override 時只接受 1–18 並回傳固定 roster；明確 override 僅建立 synthetic headless fixture；提供 `is_final_wave()` 與 next-plan guard。
- `WaveRuntime`: 新增已生成 drop source ledger、ground-clear／wave-clear derived checks；保留 stable aircraft IDs、status sync、target guard。
- `GameSession.transition(...)`: 以 `DROP_STARTED` 開啟 hybrid、以 `WAVE_CLEARED` 搭配 `wave_plan` 啟動下一波，或在第 18 波進入 `VICTORY`；會產生可重複 callback 的 gameplay transition 必須以 event ID 防止重複，`START_GAME`／`RETURN_TO_MENU` 則由 phase guard 保護。
- `normalize_aircraft_token(token) -> str`: 將輸入別名 `摩` 正規化為 `魔`，其他 canonical roster token 維持不變；固定 roster lookup 不得建立第四種 aircraft type。
- `CrewMember.begin_descent(...)`、`advance_descent(delta_seconds) -> bool`：自身管理狀態、位置與落地 transition。
- `EncounterFactory.create_drop_batch(aircraft_id, aircraft_type, encounter_id, hit_position, random_source=None) -> tuple[CrewMember, ...]`：建立 source-scoped 成員並套用 composition／deterministic spread；保留 `create_for_aircraft()` 與 `create_for_wave()` compatibility wrappers。
- `GroundEncounter.add_reinforcement(members, source_aircraft_id) -> bool`：驗證 encounter ID、source uniqueness、stable crew IDs，更新 `crew_count`、`source_aircraft_ids` 與 `cleared`。
- `GroundEncounter.record_crew_cleared(member_id) -> bool`、`batch_progress(source_aircraft_id) -> BatchProgress`：僅接受已死亡且尚未計數的 stable crew ID，對來源 batch 只計一次清除，提供每批 spawned／alive／cleared 進度；aggregate `cleared` 仍由全部成員 alive 狀態推導。
- `damage_crew_member(...)`、`advance_crew_behavior(...)`、`apply_city_damage(...)`：辨識 `DESCENDING` 與 hybrid，確保 airborne crew 不參與 ground-only behavior。

### Scene adapter

- `create_crew_members(members)`／idempotent `create_crew(encounter)`：新 batch 只建立尚不存在的 crew entity，保留 collider 與 boss tint。
- `update_crew(encounter)`：同步 airborne／landed position、alive／enabled 與 entity cleanup。
- `crew_under_center(max_distance)`：回傳 airborne 或 landed crew 的 stable ID，沿用既有 raycast。
- `clear_dynamic()`、`remove_aircraft()`、`remove_crew_member()`：在 wave transition、game over、victory、return menu 清除所有 stale entity references。

### HUD adapter

- `GameHUD.update_session(..., phase=...)`：接受 hybrid／victory phase；hybrid 顯示三種可用 weapon slot，victory 顯示 frozen result。
- `show_victory(stats)` 與既有 `show_game_over(stats)` 共用返回主選單 callback；不新增降落 progress widget。

## Implementation Sequence

1. **Configuration and data model**: 在 `config.py` 集中 campaign length、descent duration、ground Y、spread offset／radius；在 `state.py` 擴充 phase／event／wave runtime guards；在 `entities.py` 加入 crew source 與 descent state／behavior。
2. **Fixed wave and pure rules**: 將 `WaveDirector` 改為 18-wave table、Boss detection、global special rotation 與 final guard；新增 drop batch factory、encounter reinforcement、wave-clear predicate、hybrid weapon gates 與 descent／ground behavior guards。
3. **Headless tests first**: 在 `tests/test_rules.py`、`tests/test_game_lifecycle.py` 與必要的新測試檔加入 roster、special rotation、descent, batch merge, damage, city/attack skip, transition, final victory 與 reset cases；先維持所有既有測試通過或同步更新被規格刻意改變的 lifecycle assertions。
4. **Scene integration**: 在 `scene.py` 加入 per-batch crew creation／update、airborne raycast compatibility、ground-level placement 與 cleanup；保留既有 asset fallback，不載入新素材。
5. **Controller integration**: 在 `main.py` 接入 per-aircraft destruction handler、aggregate encounter、hybrid update loop、three-weapon input／rack gates、two-condition wave completion、victory and impact terminal paths。
6. **HUD integration**: 在 `hud.py` 擴充 hybrid visibility 與 victory screen；確認不出現 descent countdown／progress，並確保 weapon cooldown、scope、reticle、wave cards 在新 phase 正確 reset／freeze。
7. **Validation and cleanup**: 執行 compileall、完整 unittest、Ursina smoke、手動 18-wave／hybrid／victory flow 與 performance benchmark；清理 unused imports、debug prints、stale maps，更新 quickstart 與 tasks traceability。

## Testing Strategy

### Pure rule and state tests

- Fixed table exact equality for all 18 rosters, aircraft counts, Boss positions, special rotation, `is_final_wave()` and no wave 19.
- `CrewMember` descent start／target, 4.0-second interpolation, ±0.25-second boundary, landing transition, deterministic offsets and no movement/attack/city damage while descending.
- `EncounterFactory.create_drop_batch()` composition for NORMAL／MANPOWER_SUPPORT／FAST／ARMORED_BOSS, source IDs, random draw count and Boss creation.
- `GroundEncounter.add_reinforcement()` appends independent batches, rejects duplicate source／crew IDs, updates clear state and preserves existing members.
- `WaveRuntime` and session tests for one-aircraft destroy, multiple simultaneous drops, duplicate destroy／impact callbacks, partial aircraft survival, two-condition clear, final victory and return reset.
- Weapon gate tests for AA／sniper／pistol during hybrid, rack availability after first non-empty drop, airborne crew damage and no city damage from descent.

### Integration and manual validation

- `python -m compileall -q air_defense tests`.
- `python -m unittest discover -s tests -p "test_*.py" -v` with existing regression suite plus new feature cases.
- Ursina smoke: construct app, start wave 1, create all aircraft, destroy one source, create/update a drop batch, and exit without import／attribute errors.
- Manual flow: destroy one aircraft while another remains; switch all weapons; shoot airborne crew; observe landing and ground behavior; complete waves 4, 9, 15–18 Boss cases; verify victory and reset.
- Performance: air sub-scenario with `WaveDirector.plan_wave(6, aircraft_count=6, cap=6)`, 6 aircraft and up to 6 missiles; ground sub-scenario with six `MANPOWER_SUPPORT` batches (maximum 36 crew) and six tracers; 5-second warm-up, 30-second run, 1-second samples, minimum observed FPS >= 60 or documented measurement limitation.

## Project Structure

### Documentation (this feature)

```text
specs/005-aircraft-enemy-descent-campaign/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui.md
├── checklists/
│   └── requirements.md
└── tasks.md                 # generated by $speckit-tasks
```

### Source Code (repository root)

```text
air_defense/
├── config.py                 # descent, campaign and gameplay constants
├── state.py                  # phases, events and wave runtime guards
├── entities.py               # crew descent and encounter reinforcement data
├── rules.py                  # fixed roster, batch factory and pure gates
├── scene.py                  # aircraft/crew entity and raycast adapter
├── hud.py                    # hybrid visibility and victory presentation
└── main.py                   # explicit mixed-combat frame orchestration

tests/
├── test_rules.py             # pure roster, descent and encounter rules
├── test_airstrike_guidance.py
├── test_game_lifecycle.py    # mixed lifecycle, victory and reset
└── test_hud_wave.py          # phase-aware HUD and cooldown views
```

**Structure Decision**: 延續既有單一 `air_defense` desktop-game package。`state.py`、`entities.py` 與 `rules.py` 維持不依賴 Ursina；`scene.py`／`hud.py` 是 engine adapters；`main.py` 只協調明確 frame order 與跨物件 transition。這能以最少新抽象完成垂直切片，符合憲章可讀性、封裝、小步驟與簡單依賴要求。

## Post-design Constitution Check: PASS

| Principle / gate | Post-design evidence |
|---|---|
| I. Readability first | 固定 table、named phase operations、source-scoped batch 與單一 encounter 保持責任邊界；spread 與 timing 都集中設定，不散落 magic numbers。 |
| II. Encapsulated game objects | Crew 自己更新 descent，Aircraft 自己更新飛行／生命，Encounter 管理成員，WaveRuntime／Session 管理跨物件清除與 phase。 |
| III. Small verifiable steps | implementation sequence 先 domain／pure tests，再 scene／controller／HUD；每一步均可由 compile／unit／smoke 驗證。 |
| IV. Explicit loop and boundaries | aircraft、missile、drop、ground、impact、wave-clear、victory 的處理順序與 duplicate／zero／reset 邊界已明確。 |
| V. Appropriate scope/dependencies | 沿用 `spec.md` 已記錄的既有 Ursina runtime exception，不新增套件、服務、資產或資料層；沒有新的 constitutional exception。 |
| No unresolved clarification | `research.md` 已解決 Technical Context 選擇；spec、data model、UI contract、quickstart 均以固定 18 波與既定行為為準。 |

## Implementation and Delivery Evidence (2026-08-27)

- `python -m compileall -q air_defense tests` 通過；`python -m unittest discover -s tests -p "test_*.py" -v` 通過，完整 suite 為 106 件測試。
- Ursina construction／start-wave smoke 通過，包含 wave 1 啟動、單架飛機擊落、deterministic drop batch 建立與一次更新；未觀察到 import 或 attribute error。
- 使用者已回報人工功能驗收完成且未發現問題；本輪未取得 SC-001 至 SC-009 的逐項 sample count 或 FPS 原始量測，因此不宣稱那些數值門檻已完成量測。
- 本地 code review 已修正 source-drop completion guard、aggregate counter double count、stale aircraft scene reference、authoritative roster type lookup 與 no-target sniper cooldown 問題；`git diff --check` 通過。
- 文件狀態為 Ready for Review。依憲章，PR 必須以 `main` 為 base；PR 合併並確認 merge commit 存在於 `main` 後，才可清理功能分支。正式 Release 仍以使用者確認的 semver 版本號為前置條件。

## Complexity Tracking

本功能不新增 constitutional exception；它只使用 `spec.md` 已記錄、由 004 合併基線繼承的 Ursina runtime exception。單一 aggregate encounter 加上 source-scoped drop batch 是為了在混合戰鬥中保留既有單 encounter adapter 邊界；沒有新增 project、service、repository layer 或第三方依賴。
