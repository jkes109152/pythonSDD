---

description: "依照固定 18 波、混合戰鬥與降落敵人規格的實作任務"
---

# Tasks: 飛機擊落後敵人降落戰役

**Input**: Design documents from `specs/005-aircraft-enemy-descent-campaign/`

**Prerequisites**: `spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/ui.md`、`quickstart.md`

**Tests**: 本功能規格與實作計畫明確要求純規則測試、生命週期測試、HUD 測試、compileall、Ursina smoke 與手動驗收，因此測試任務列入每個使用者故事。

**Constitution / branch**: 維持 `005-aircraft-enemy-descent-campaign` 分支；沿用 `spec.md` 記錄的 004 Ursina runtime exception 與 `air_defense` 責任邊界，不修改不屬於本功能的工作區變更。完成後依 Phase 7 執行 base=`main` 的 PR、review、merge verification 與分支清理。

**Pre-implementation governance gate**: 在開始 T001 或任何程式碼實作前，必須取得專案負責人對 `spec.md` 所記錄之 004 Ursina runtime exception 的明確同意；若未取得，不得進入實作階段。此 gate 不改變憲章原則，也不代表本文件自行授權該例外。

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 先把所有故事共用的戰役與降落調校值集中到既有設定區，避免 magic numbers 散落在 domain、scene 或 controller。

- [X] T001 在通過 pre-implementation governance gate 後，集中加入固定戰役長度、4.0 秒降落時間、±0.25 秒驗收容差、ground Y 與半徑不超過 2.5 的 deterministic X/Z spread offsets 到 `air_defense/config.py`，並保留既有 60 FPS、資產 fallback 與無新增依賴設定。

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 建立所有使用者故事共用的 state、entity、wave、batch 與純規則 API；本階段完成前不接入混合戰鬥 controller。

**⚠️ CRITICAL**: 此階段阻擋所有使用者故事。

- [X] T002 在 `air_defense/state.py` 新增 `GamePhase.HYBRID_COMBAT`、`GamePhase.VICTORY` 與 `SessionEvent.DROP_STARTED`／`WAVE_CLEARED`／`VICTORY`，並擴充 `WaveRuntime` 的 source drop ledger、hybrid sticky flag、僅以 `DESTROYED` 成功清波且以 `IMPACTED` 進入失敗的 aircraft 判定與雙條件 clear predicate。
- [X] T003 在 `air_defense/entities.py` 新增 `CrewBehaviorState.DESCENDING`，讓 `CrewMember` 封裝 source aircraft、降落起點／落點、elapsed／duration／offset、`begin_descent()`、`advance_descent()` 與死亡後禁止落地的規則；實作 `GroundEncounter.add_reinforcement(members, source_aircraft_id)`、`record_crew_cleared(member_id)` 與 `batch_progress(source_aircraft_id)` 的 source／crew ID 驗證、per-batch spawned／alive／cleared counters 與 aggregate bookkeeping。
- [X] T004 在 `air_defense/rules.py` 將 `WaveDirector` 改為不可變的固定 18 波 roster，實作 `普`／`特`／`魔` 對應、將輸入別名 `摩` 正規化為 `魔`、以 1 起算且奇數為 `MANPOWER_SUPPORT`／偶數為 `FAST` 的全戰役特殊飛機交替、Boss 左至右位置、1–18 邊界拒絕與供壓力測試使用的明確 synthetic override。
- [X] T005 在 `air_defense/rules.py` 實作 `EncounterFactory.create_drop_batch(aircraft_id, aircraft_type, encounter_id, hit_position, random_source=None)` 與既有 factory compatibility wrappers，保留既有各機型 crew composition，建立同批成員的 source ID、Boss 身分、deterministic spread 與空批次語義。
- [X] T006 在 `air_defense/rules.py` 更新 `damage_crew_member()`、`advance_crew_behavior()`、`apply_city_damage()`、武器 selection／fire predicates，使 `DESCENDING` 可被攻擊但不移動、不攻擊、不造成城市傷害，並使 `HYBRID_COMBAT` 的三種武器 gate 可被純邏輯測試。
- [X] T007 [P] 更新 `tests/test_rules.py` 的 domain regression cases，覆蓋新 phase／event、`WaveRuntime` source ledger、aggregate reinforcement、空 batch 與既有 `create_for_aircraft()`／`create_for_wave()` compatibility 行為；確認舊 scalar `CREW_CLEARED` 只保留相容性，不可繞過 keyed runtime 的雙條件 clear。
- [X] T008 [P] 更新 `tests/test_game_lifecycle.py` 的共用 fixture 與既有失敗／地面戰回歸案例，使測試可建立新 phase/event，同時保留飛機撞城、player death、reset 與舊地面行為的斷言。
- [X] T009 執行 `python -m compileall -q air_defense tests` 與 `python -m unittest discover -s tests -p "test_*.py" -q`，確認 `air_defense/state.py`、`air_defense/entities.py`、`air_defense/rules.py` 與 `tests/` 在進入故事實作前仍可匯入並通過目前回歸測試。

**Checkpoint**: 共用 domain API、固定 roster、source-scoped batch 與純規則 gate 已可被 headless 測試使用。

---

## Phase 3: User Story 1 - 擊落飛機並攔截降落敵人 (Priority: P1) 🎯 MVP

**Goal**: 飛機在實際擊落位置立即產生自己的敵人批次；敵人在約 4 秒下降期間可被攻擊，落地後才恢復既有地面行為。

**Independent Test**: 使用單架會產生 crew 的測試波次，記錄擊落位置並觸發擊落；確認同一批成員立即出現、4.0 秒 ±0.25 秒完成下降、X/Z 保留、空中可擊殺且不會在落地前移動／攻擊／傷害城市。

### Tests for User Story 1

> 先加入以下新測試並確認它們在實作前因缺少降落／即時生成行為而失敗，再完成 implementation tasks。

- [X] T010 [P] [US1] 在 `tests/test_rules.py` 加入 `CrewMember` 降落起點／落點、clamped linear interpolation、4.0 秒與 ±0.25 秒邊界、X/Z offset、死亡前置、只觸發一次 landing transition，以及單一 source batch 的 spawned／alive／cleared counters 純規則測試。
- [X] T011 [P] [US1] 在 `tests/test_game_lifecycle.py` 加入單架飛機擊落即生成 batch、來源位置快照、同批同時出現、空 batch 不建立 encounter、重複 destroy callback 不重複生成，以及降落敵人可被計一次且只計一次清除的生命週期測試。

### Implementation for User Story 1

- [X] T012 [US1] 在 `air_defense/main.py` 改造單架飛機擊落 handler：先保存實際 `Aircraft.position`，再以 `WaveRuntime` source ledger 去重、移除該架 visual／missile／lock，建立其 batch 並立即加入 aggregate encounter，不等待其他飛機。
- [X] T013 [US1] 在 `air_defense/scene.py` 新增 idempotent `create_crew_members(members)`，讓新 batch 的每名 crew 立即建立既有模型與 collider，並同步 airborne／landed position、Boss tint、enabled 狀態與單名 cleanup。
- [X] T014 [US1] 在 `air_defense/rules.py` 完成 descending／landed behavior guards，並在 `air_defense/main.py` 建立一個供各 gameplay phase 共用的 crew update helper：降落中的成員保持可見可 raycast 命中，只有首次落地後才進入既有 ground movement、attack cooldown、tracer 與 city-damage 流程；本任務不重複建立 phase-specific update branch。
- [X] T015 [US1] 在 `air_defense/entities.py`、`air_defense/scene.py` 與 `air_defense/main.py` 完成 descending crew 的死亡與移除邊界，呼叫 per-source `record_crew_cleared()` 並確保被擊殺者不會稍後落地、攻擊、傷害城市或再次計入清除，並保留存活者的 landing target。
- [X] T016 [US1] 執行 `tests/test_rules.py` 與 `tests/test_game_lifecycle.py` 的 US1 focused tests、`python -m compileall -q air_defense tests`，以及 `specs/005-aircraft-enemy-descent-campaign/quickstart.md` 的單架飛機手動流程，確認 MVP 垂直切片可獨立運作且既有地面回歸未破壞。（使用者回報功能手動驗收完成且未發現問題。）

**Checkpoint**: 單架飛機的 immediate drop、空中可攻擊、降落動畫與落地後地面行為可獨立驗收；此 checkpoint 是 MVP。

---

## Phase 4: User Story 2 - 同時處理空戰與降落敵人 (Priority: P1)

**Goal**: 第一批非空降落開始後，玩家可同時處理尚存飛機與多批降落／地面敵人，並立即使用三種武器與武器架。

**Independent Test**: 使用至少兩架飛機的測試波次先擊落一架；確認另一架仍飛行、鎖定與可被防空砲攻擊，再切換防空砲／狙擊槍／手槍攻擊 airborne 或 landed crew，且清除任一類目標都不會提前換波。

### Tests for User Story 2

> 先加入以下新測試並確認它們在實作前失敗，再接入 hybrid lifecycle 與輸入。

- [X] T017 [P] [US2] 在 `tests/test_game_lifecycle.py` 加入多架飛機同時更新、第一架擊落後其他 aircraft 繼續前進、兩個 source batch 各自計時與分開計算 cleared count，以及只清除一類目標不得換波的 hybrid lifecycle 測試。
- [X] T018 [P] [US2] 在 `tests/test_rules.py` 與 `tests/test_hud_wave.py` 加入 `DROP_STARTED` 後三種武器 gate、AA 對剩餘 aircraft、sniper／pistol 對 airborne crew、武器架啟用與「沒有額外降落 HUD」的測試。

### Implementation for User Story 2

- [X] T019 [US2] 在 `air_defense/state.py` 實作 `DROP_STARTED` 的 hybrid transition 與 sticky semantics，讓空 batch 不啟動 hybrid、最後一架 aircraft 全部為 `DESTROYED` 且有 crew 時才進入 `GROUND_COMBAT`，並以 aggregate encounter 保存多個 source batch。
- [X] T020 [US2] 在 `air_defense/main.py` 將 `update()` 擴充為 `AIRSTRIKE`／`HYBRID_COMBAT`／`GROUND_COMBAT` 的明確 frame order，重用 T014 的 crew update helper，持續更新所有 aircraft、lock／missile、descent crew 與 landed crew；`IMPACTED` 立即短路至既有 `GAME_OVER`，只有 `DESTROYED` 可作為成功清波狀態。
- [X] T021 [US2] 在 `air_defense/main.py` 接入 hybrid 期間的 weapon selection、anti-air／sniper／pistol fire、scope 與 `E` 武器架互動 gate，使三種武器切換不暫停 aircraft、descent、ground AI 或各自 cooldown。
- [X] T022 [US2] 在 `air_defense/main.py` 與 `air_defense/scene.py` 只負責清理 hybrid 期間的 stale lock、target、missile、crew collider 與 source map，並呼叫既有 named clear predicate；該 predicate 的成功條件必須是「所有 aircraft `DESTROYED` 且 aggregate crew cleared」，final next-wave／victory transition 留給 T028。
- [X] T023 [US2] 執行 `tests/test_game_lifecycle.py`、`tests/test_rules.py`、`tests/test_hud_wave.py` 的 US2 focused tests、`python -m compileall -q air_defense tests`，以及 `specs/005-aircraft-enemy-descent-campaign/quickstart.md` 的雙飛機三武器手動流程，驗證多批次混合戰鬥可啟動。（使用者回報功能手動驗收完成且未發現問題。）

**Checkpoint**: 混合空戰與地面戰可同時遊玩；尚存 aircraft、降落 crew、武器架與雙條件 wave clear 均可獨立驗收。

---

## Phase 5: User Story 3 - 完成固定 18 波戰役並獲得勝利 (Priority: P1)

**Goal**: 依最後確認的 18 波表建立固定 aircraft roster，正確產生 Boss 地面敵人，完成第 18 波後顯示勝利且不建立第 19 波。

**Independent Test**: headless 逐一檢查 `WaveDirector.plan_wave(1..18)` 的完整序列、特殊輪替與 Boss slot；再以測試清除第 18 波所有 aircraft 與 crew，確認只進入 `VICTORY`、不建立 successor，並可從勝利畫面返回乾淨主選單。

### Tests for User Story 3

> 下列三組測試可在不同檔案平行撰寫；先確認新 roster、final guard、victory UI 測試失敗，再實作終局流程。

- [X] T024 [P] [US3] 在 `tests/test_rules.py` 加入 18 波表逐波 exact equality、aircraft count／aircraft cap validation、`摩`→`魔` normalization、以第 1 個 `特` 為 `MANPOWER_SUPPORT`／第 2 個為 `FAST` 的全戰役交替、Boss 波 4／9／15／16／17／18 的位置、Boss drop composition 與 wave 19 拒絕測試。
- [X] T025 [P] [US3] 在 `tests/test_game_lifecycle.py` 加入雙條件 wave clear、Boss aircraft 對應地面 Boss、第 18 波 `VICTORY`、impact 優先失敗、duplicate clear event、最後一個目標至勝利畫面不超過 1 秒與 victory／menu reset 測試。
- [X] T026 [P] [US3] 在 `tests/test_hud_wave.py` 加入 hybrid 三武器可用、victory 的 `你贏了`／`返回主選單`／frozen stats、Enter／Escape 導航，以及不產生 descent countdown／progress widget 的測試。

### Implementation for User Story 3

- [X] T027 [US3] 在 `air_defense/state.py` 完成 `WAVE_CLEARED`、final-wave guard、`VICTORY` idempotency 與 `RETURN_TO_MENU` 的 victory／game-over 共用 reset transition，禁止從第 18 波建立 successor。
- [X] T028 [US3] 在 `air_defense/main.py` 改造 encounter completion：只有 aircraft 全部為 `DESTROYED` 且 aggregate crew 全部清除才建下一固定波或進入 `VICTORY`，並維持 Boss source drop、impact failure precedence 與停止 gameplay updates。
- [X] T029 [US3] 在 `air_defense/hud.py` 擴充 hybrid phase-aware inventory／status 顯示與 victory presentation，顯示 exact primary message `你贏了`、統計與 `返回主選單`，且不加入降落倒數或進度條。
- [X] T030 [US3] 在 `air_defense/main.py`、`air_defense/scene.py` 與 `air_defense/hud.py` 接通 Enter、Escape、返回按鈕的同一 callback，並在 victory／menu reset 清除 aircraft、crew、missile、lock、scope、cooldown、wave runtime 與 statistics。
- [X] T031 [US3] 執行 `tests/test_rules.py`、`tests/test_game_lifecycle.py`、`tests/test_hud_wave.py` 的 US3 focused tests、`python -m compileall -q air_defense tests`，以及 `specs/005-aircraft-enemy-descent-campaign/quickstart.md` 的 wave 18 victory／reset 手動流程，確認 18 波終局與舊失敗流程均通過。（使用者回報功能手動驗收完成且未發現問題。）

**Checkpoint**: 固定 18 波、Boss 地面生成、雙條件終局、勝利畫面與乾淨 reset 均可獨立驗收。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 完成全套回歸、啟動與手動／效能驗證，並把實際結果記錄到 feature 文件。

- [X] T032 [P] 依實作後的實際操作更新 `specs/005-aircraft-enemy-descent-campaign/quickstart.md`，補上 hybrid、multiple batch、Boss、victory 與 reset 的可重現驗收步驟；不加入規格未要求的 HUD 或依賴。
- [X] T033 [P] 審查 `air_defense/config.py`、`air_defense/state.py`、`air_defense/entities.py`、`air_defense/rules.py`、`air_defense/scene.py`、`air_defense/hud.py`、`air_defense/main.py` 的 unused imports、debug output、重複 source／cleanup 邏輯與 stale references，並確認 `requirements-game.txt` 未新增套件或素材。
- [X] T034 執行完整 `python -m compileall -q air_defense tests` 與 `python -m unittest discover -s tests -p "test_*.py" -v`，保存 `air_defense/state.py`、`air_defense/entities.py`、`air_defense/rules.py`、`air_defense/main.py` 與 `tests/test_rules.py`、`tests/test_game_lifecycle.py`、`tests/test_hud_wave.py` 的通過結果及任何環境限制。
- [X] T035 執行等價於 `python -m air_defense.main` 的 Ursina construction／start-wave smoke，確認 `air_defense/main.py` 可開啟主選單、開始 wave 1、建立並更新 drop batch，且無 import／attribute error；本輪以 `create_application()` 搭配 `start_game()` 與 deterministic drop 驗證並記錄於 quickstart。
- [ ] T036 依 `specs/005-aircraft-enemy-descent-campaign/quickstart.md` 完成手動 18 波、混合武器、撞城失敗、victory reset 與 FPS 壓力場景，並依 acceptance evidence protocol 執行 SC-001／SC-004 各 10 次、SC-002／SC-003／SC-006 各 20 次、SC-005 1 次完整 18 波、SC-007／SC-008 各 10 次與 SC-009 1 次回歸驗收；記錄 SC-007 的 1 秒延遲、6 aircraft／6 missile 與最多 36 crew／6 tracer 的暖機 5 秒／觀測 30 秒結果或量測限制於 `specs/005-aircraft-enemy-descent-campaign/quickstart.md`。（使用者回報功能手動驗收完成且未發現問題；本次未取得逐項 sample count／FPS 原始紀錄，因此不宣稱 protocol 數值已量測通過。）

---

## Phase 7: Delivery Governance

**Purpose**: 依專案憲章完成 review、PR、merge verification、分支清理與正式 Release 的前置治理；Release 只能從已合併且驗證的 `main` 建立，且必須先確認明確 semver 版本號。

- [X] T037 在 `specs/005-aircraft-enemy-descent-campaign/spec.md`、`specs/005-aircraft-enemy-descent-campaign/plan.md`、`specs/005-aircraft-enemy-descent-campaign/tasks.md` 與 `specs/005-aircraft-enemy-descent-campaign/quickstart.md` 核對驗證結果與已知限制，推送 `005-aircraft-enemy-descent-campaign` 並建立 base=`main` 的 PR。（已建立並合併 GitHub PR #5。）
- [X] T038 在 `specs/005-aircraft-enemy-descent-campaign/spec.md`、`specs/005-aircraft-enemy-descent-campaign/plan.md`、`specs/005-aircraft-enemy-descent-campaign/tasks.md`、`specs/005-aircraft-enemy-descent-campaign/quickstart.md`、`air_defense/main.py`、`air_defense/rules.py`、`tests/test_rules.py` 與 `tests/test_game_lifecycle.py` 上完成 code review、compileall、自動化測試與必要手動驗證；將 review 結果、對應文件與限制寫入 PR。（本地 review、compileall、106 項測試、Ursina smoke 與使用者人工驗收已完成，結果已寫入 PR #5。）
- [X] T039 PR 合併後先確認合併 commit 已存在於 `main`，再刪除遠端與本地 `005-aircraft-enemy-descent-campaign` 分支；清理時保留 `day2/prj06.py` 與 `output/` 下不屬於本功能的工作區變更。（已確認 merge commit `660af80` 位於 `main`，並完成遠端／本地功能分支清除。）
- [ ] T040 在使用者確認明確 semver 版本號後，從已合併且驗證的 `main` 建立 annotated tag、推送 tag 並建立 GitHub Release；若版本號尚未確認，保留未完成並記錄此治理限制，不得先建立正式 Release。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (T001)**: 先通過 pre-implementation governance gate，之後無程式依賴；再集中共用常數。
- **Phase 2 (T002–T009)**: 依賴 T001；T002–T006 建立 domain API，T007–T008 依賴 API，T009 在 foundation 修改後執行並阻擋故事階段。
- **Phase 3 / US1 (T010–T016)**: 依賴 Phase 2；先寫 T010–T011 紅測試，再完成 T012–T015，T016 為 MVP checkpoint。
- **Phase 4 / US2 (T017–T023)**: 依賴 US1 的 source-scoped drop 與 scene cleanup；先寫 T017–T018，再完成 hybrid state/controller/input，T023 為混合戰鬥 checkpoint。
- **Phase 5 / US3 (T024–T031)**: 依賴 US1／US2 的批次與雙條件 lifecycle；先寫 T024–T026，再完成 final transition、HUD 與 reset。
- **Phase 6 (T032–T036)**: 依賴所有要交付的使用者故事；T034–T036 是交付前的完整驗證門檻。
- **Phase 7 (T037–T040)**: 依賴 Phase 6 的驗證結果；先 review／push／開 PR，再確認 merge commit，清理分支後，只有在版本號確認時才從 `main` 建立正式 Release。

### User Story Dependencies

- **US1 (P1)**: 只依賴 Phase 2；是可先交付的 MVP，能以單架 aircraft／單批 crew 獨立驗收。
- **US2 (P1)**: 依賴 US1 的 per-aircraft drop 與 airborne crew target path，擴充為同波多威脅；不改變 US1 的降落與擊殺語義。
- **US3 (P1)**: 依賴 US1／US2 的 source ledger、aggregate clear 與 phase freeze，才能可靠實作 18 波換波與 final victory；其 roster 純規則測試仍可在 T024 獨立執行。

### Within Each User Story

- 測試任務 MUST 先建立並觀察新行為失敗；這些紅測試是緊接 implementation tasks 前的明確暫存狀態，且每個 checkpoint 必須恢復為綠測試並保持程式可啟動。
- 先完成 domain／entity，再接 scene adapter，最後接 controller／HUD 與 reset。
- 每個 checkpoint 都要執行該故事的 focused tests、compileall 與至少一個邊界案例。
- 不得因新 phase 或 batch 而繞過既有 impact、damage、asset fallback、event dedupe 或 reset 規則。

### Parallel Opportunities

- T007 與 T008 觸及不同測試檔，可在 T002–T006 完成後平行處理。
- T010 與 T011 分別位於 `tests/test_rules.py` 與 `tests/test_game_lifecycle.py`，可平行建立 US1 測試。
- T017 與 T018 分別以 lifecycle 與 rules/HUD 為主，可平行建立 US2 測試。
- T024、T025、T026 分別位於 `tests/test_rules.py`、`tests/test_game_lifecycle.py`、`tests/test_hud_wave.py`，可平行建立 US3 測試。
- T032 與 T033 分別處理 feature 文件與 source audit，可在故事實作完成後平行進行；完整測試仍須等 audit 結束。

## Parallel Example: User Story 3

```text
Task T024: 在 tests/test_rules.py 驗證固定 18 波、特殊輪替與 Boss roster
Task T025: 在 tests/test_game_lifecycle.py 驗證雙條件 clear、VICTORY 與 reset
Task T026: 在 tests/test_hud_wave.py 驗證 victory presentation 與無降落 HUD
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 T001–T009，建立集中設定、固定 domain API、source ledger、batch factory 與回歸基線。
2. 完成 T010–T016，交付單架飛機的 immediate drop、4 秒下降、空中可擊殺與落地行為。
3. T016 是 US1 的手動驗收 checkpoint；本輪若只完成 focused tests、compileall 與 construction smoke，仍可繼續以 headless evidence 開發後續故事，但不得把 T016 或相關手動驗收宣稱為完成，且必須在交付前補測或記錄限制。

### Incremental Delivery

1. Foundation ready → US1：單批降落與攻擊。
2. US2：加入多架 aircraft、多個獨立 batch、三武器與 hybrid phase。
3. US3：加入固定 18 波、Boss roster、final victory 與 reset。
4. Polish：完成全套回歸、Ursina smoke、手動驗收與 FPS evidence；每一步保留前一 checkpoint 的行為。
5. Phase 7：完成 base=`main` PR、review、merge verification，再依憲章清理功能分支並保留 unrelated working-tree changes；版本確認後才執行 T040 Release。

## Traceability Notes

- FR-001–FR-003、FR-013、FR-015 主要由 T004、T024、T027–T031 覆蓋。
- FR-004–FR-009、FR-017–FR-018 主要由 T003、T005、T010–T016 覆蓋。
- FR-010–FR-012、FR-014、FR-018 主要由 T019–T023、T025、T028 覆蓋。
- FR-016、FR-019–FR-020 主要由 T029–T036 覆蓋。
- Success criteria 的手動與效能證據由 T032、T034–T036 記錄；沒有實際 GUI／FPS 量測時 MUST 記錄限制，不宣稱未測得結果。
- Constitution 的 runtime exception、T001 前核准 gate 與交付治理由 `spec.md` Runtime Governance Note、tasks.md pre-implementation gate、T033、T037–T040 追蹤；本 feature 不修改憲章原則，且在版本號確認前不建立正式 Release。
