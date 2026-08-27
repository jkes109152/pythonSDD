---

description: "依據規格與設計文件產生的防空 HUD、動態鎖定與整波敵機實作任務"
---

# Tasks: 防空 HUD、動態鎖定與整波敵機

**Branch**: `004-air-defense-hud-wave`（不得在 `main` 執行本任務）
**Input**: `specs/004-air-defense-hud-wave/spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/ui.md`、`quickstart.md`

**Tests**: 本任務清單包含測試，因為規格明確要求每個 user story 的 independent test、measurable outcomes 與 reset／邊界驗收；純規則優先使用 `unittest`，圖形層再以 smoke 與手動流程驗證。

**Organization**: 任務依 User Story 分組；所有任務都有嚴格的 checkbox、循序 ID、必要的 `[P]`／`[USn]` 標籤與明確檔案路徑。

## Phase 1: Setup（共用基礎）

**目的**：建立本功能的集中設定與純測試承載點，不改變既有遊戲流程。

- [X] T001 [P] 在 `air_defense/config.py` 集中加入 004 功能的 frame `0.210`、水平 formation spacing、HUD card layout、ground tracer lifetime／尺寸與必要的程序化 UI 常數，保留既有 3 秒 lock、0.75 秒 decay、1.5× aim assist 與三種 weapon cooldown 的名稱與預設值。
- [X] T002 [P] 在 `tests/test_hud_wave.py` 建立共用的純資料 fixture／assertion helper，涵蓋固定 wave roster、aircraft screen candidate、player/city view、cooldown view 與 tracer effect，測試模組不得 import Ursina。

---

## Phase 2: Foundational（阻塞性基礎）

**目的**：完成所有 user story 共用的多物件狀態、reset 邊界與相容性骨架；本階段完成前不得開始故事整合。

**⚠️ CRITICAL**：所有 User Story 都依賴本階段完成。

- [X] T003 [P] 在 `air_defense/state.py` 新增 `WaveRuntime`，保存 wave progress、ordered aircraft IDs、每架 `AircraftPhase`／`AircraftType`、active target ID 與 aggregate encounter ID，並實作 `alive_aircraft_ids`、`remaining_aircraft_count`、`alive_ratio`、`all_aircraft_destroyed`、`sync_aircraft_phase`、`mark_destroyed` 與 `mark_impacted` 的 ID 去重與範圍 invariant；明確規定 `Aircraft.phase` 是單架 authoritative state、status ledger 是 wave view 的唯一來源。
- [X] T004 [P] 在 `air_defense/main.py` 與 `air_defense/scene.py` 建立 keyed aircraft collection 的 ownership／compatibility scaffold（`dict[id, Aircraft]` 與 `dict[id, Entity]`、active target accessor），保留舊 scalar 呼叫者可讀取的相容性 view，提供後續 US3 projection 使用的 collection API，但先不移除既有單架流程。
- [X] T005 [P] 在 `air_defense/entities.py` 擴充 `GroundEncounter` 的 `source_aircraft_ids` 與 deterministic wave group identity，保留 `create_for_aircraft(...)` 與既有 Boss／crew 欄位，讓 aggregate encounter 能與舊測試並存。
- [X] T006 [P] 在 `air_defense/rules.py` 新增 Ursina-free 的比例 clamp、矩形邊界、weapon cooldown fill ratio 與顯示 view 基礎 helper，統一處理 `[0, 1]`、百分比與零 duration 邊界。
- [X] T007 在 `air_defense/state.py` 將 `GameSession` 的 start、aircraft／ground／impact、scope close、weapon switch、game over、return menu 與 new wave reset 接到 `WaveRuntime`，保留 event ID 去重與舊 scalar compatibility accessors；另定義 controller 可呼叫的 weapon cooldown reset boundary；任一 impact 必須成為不可逆 terminal state。
- [X] T008 在 `tests/test_rules.py` 與 `tests/test_game_lifecycle.py` 增加基礎回歸測試，確認舊 `create_for_aircraft(...)`、單架 wrapper、導引飛彈 target cleanup、session reset 與原有 62 tests 的既有行為在新狀態骨架下仍可通過。

**Checkpoint**：`air_defense/state.py`、`entities.py`、`rules.py` 可在不啟動 Ursina 的情況下匯入；既有 `tests/` 回歸測試保持通過。

---

## Phase 3: User Story 1 — 讀懂玩家與城市狀態（Priority: P1）🎯 MVP

**Goal**：左上顯示透明 player／city 狀態卡與白色大字，數值、圖示、顏色與兩條比例 bar 各自同步，terminal 後保留最後值。

**Independent Test**：開始遊戲並分別改變玩家生命與城市耐久；確認 heart／shield、數值、bar fill 與 game-over freeze 均正確，且兩個 row 不互相污染。

### Tests for User Story 1（先寫並確認失敗）

- [X] T009 [P] [US1] 在 `tests/test_hud_wave.py` 撰寫 player／city derived view 的 failing tests，驗證 max、partial damage、zero、negative／over-max clamp、紅色 heart／藍色 shield 的 view data 與獨立比例。
- [X] T010 [P] [US1] 在 `tests/test_game_lifecycle.py` 撰寫 failing lifecycle tests，驗證 player damage 不改 city card、city damage 不改 player card，以及進入 `GAME_OVER` 後 card snapshot 不再更新。

### Implementation for User Story 1

- [X] T011 [US1] 在 `air_defense/hud.py` 建立左上透明 player／city card 的程序化 panel、可選低透明度白色輪廓、紅色 heart、藍色 shield、白色大字、紅／藍 bar track 與 fill entity，並讓 gameplay weapon inventory slots 維持透明，保留中央 lock、Boss、FPS 與 stats 的安全間距。
- [X] T012 [US1] 在 `air_defense/hud.py` 實作 `update_status_cards(...)` 的 player／city 分支，從 clamped view 更新 icon color、`目前值 / 最大值`、`城市耐久：<percent>%` 與 fill ratio；非 gameplay／menu 時正確隱藏卡片。
- [X] T013 [US1] 在 `air_defense/main.py` 將 `GameSession.health`、`city_health` 與 terminal snapshot 傳入 HUD card view，更新 `_refresh_hud()` 與 `_present_game_over()`，避免死後或重複 callback 改寫最後數值。
- [X] T014 [US1] 在 `tests/test_hud_wave.py` 與 `tests/test_game_lifecycle.py` 執行 US1 focused tests 與手動傷害／game-over freeze 驗收；保留結果供 T058 traceability review，compile 與完整 suite 留到 T054–T055。

**Checkpoint**：US1 可獨立展示兩張 row 的正確數值與比例，且不需要 wave／lock 功能才能驗收。

---

## Phase 4: User Story 2 — 讀懂波次與敵機存活進度（Priority: P1）

**Goal**：右上顯示 wave number、完整 aircraft dots、alive／total percentage、本波不重複 aircraft type list 與 current sticky target type；部分擊落只讓對應 dot 變灰。

**Independent Test**：以固定 roster 開始 wave，逐一標記部分 aircraft destroyed，確認藍／灰 dot、存活百分比、總數、種類與超量換行／縮小都正確。

### Tests for User Story 2（先寫並確認失敗）

- [X] T015 [P] [US2] 在 `tests/test_hud_wave.py` 撰寫 failing wave view tests，驗證 dot 數量等於 roster、alive 為藍色、`DESTROYED`／`IMPACTED` 為灰色 terminal dot、alive ratio 等於 alive／total，以及零／超量輸入的 clamp 與 layout metadata。
- [X] T016 [P] [US2] 在 `tests/test_game_lifecycle.py` 撰寫 failing lifecycle tests，驗證 partial aircraft destruction 不會切換 phase、`IMPACTED` 不計入 alive ratio 且不可推進下一波、current target type 可更新、目標清除後顯示 `未選定`，且 terminal 後 percentage 停止變動。

### Implementation for User Story 2

- [X] T017 [P] [US2] 在 `air_defense/rules.py` 實作從 `WaveRuntime` 建立 `WaveStatusView` 的純 helper，輸出 wave number、ordered dot status、alive／total、alive percentage、roster-order distinct aircraft type labels 與 selected aircraft type，並以 deterministic fallback 表示 `未選定`。
- [X] T018 [P] [US2] 在 `air_defense/hud.py` 建立右上透明 wave／aircraft card、可選白色輪廓、flag icon、dot entity pool、alive percentage bar／text、multi-type roster row 與 sticky target row，依 UI contract 保持與中央瞄準及下方 weapon bar 不重疊。
- [X] T019 [US2] 在 `air_defense/hud.py` 實作 aircraft dot 的固定寬度縮小／換行策略，確保超過單行容量時完整顯示每個 dot，不遮住 `第 N 波`、percentage 或 aircraft type。
- [X] T020 [US2] 在 `air_defense/main.py` 將 `WaveRuntime` 與 lock target type 接到 `_refresh_hud()`，在 destroy／impact／new wave／ground transition 時同步 blue／gray terminal dot、alive percentage 與 `未選定` reset；保留既有 Boss HP 與統計，並在 game-over snapshot 後停止 dynamic refresh。
- [X] T021 [US2] 在 `tests/test_hud_wave.py` 與 `tests/test_game_lifecycle.py` 執行 US2 focused tests 與固定 roster 手動驗收，保留 dot overflow／解析度限制結果供 T058 traceability review；compile 與完整 suite 留到 T054–T055。

**Checkpoint**：US1 與 US2 同時可運作；右上卡只反映 wave runtime，不依賴單一 active aircraft index。

---

## Phase 5: User Story 3 — 以動態小準心完成防空鎖定（Priority: P1）

**Goal**：防空 scope 顯示放大且永遠白色的矩形 frame，小準心從中心向 sticky target 收斂、被限制在 frame 內，並以 3 秒／0.75 秒規則控制綠色 fire gate。

**Independent Test**：讓一架可見飛機進入 frame、持續追蹤至 100%，再離框 0.25／0.75 秒；確認準心位置、黏著目標、紅閃／綠色、白框與發射資格。

### Tests for User Story 3（先寫並確認失敗）

- [X] T022 [P] [US3] 在 `tests/test_airstrike_guidance.py` 撰寫 failing rule tests，驗證矩形含邊界、可見／框內 filter、距中心最近選取、ID tie-break、target sticky、target switch reset 與 progress-zero reselect。
- [X] T023 [P] [US3] 在 `tests/test_hud_wave.py` 撰寫 failing view tests，驗證 frame 尺寸為既有值兩倍、frame 所有狀態為白色、reticle 從中心插值到 clamped target、reticle 不越界，以及 red flash 後 green ready。

### Implementation for User Story 3

- [X] T024 [P] [US3] 在 `air_defense/rules.py` 實作矩形 frame membership、expanded 1.5× membership、visible candidate filtering、closest-center target selection、deterministic tie-break 與 `reticle_position_for_progress(...)` clamp／interpolation，移除隱藏圓形對新 lock eligibility 的主導作用；完成後才開始 T025。
- [X] T025 [US3] 在 `air_defense/rules.py` 擴充 `LockOnTracker` 的 target ID、visibility、frame membership、3 秒累積、0.75 秒線性衰減、fireable property、scope-close reset 與 0.12 秒 completion flash；目標離框／不可見時即使 progress 為 100% 也不可發射。
- [X] T026 [P] [US3] 在 `air_defense/scene.py` 以 T004 的 keyed collection API 擴充 `AircraftScreenTarget` 的 aircraft ID 與 `in_lock_frame` 語意，提供每架 aircraft 的 projection／visibility／screen radius／distance data，並在 projection 暫時失效時保留 target identity 所需的最後位置。
- [X] T027 [US3] 在 `air_defense/hud.py` 將既有 lock frame／ring 改為固定白色 frame 與 constrained small reticle，加入 center fallback、target interpolation position、red tracking／decay、completion red flash／green ready、白色 lock text、透明 lock bar track 與狀態 fill，移除白框變色行為。
- [X] T028 [US3] 在 `air_defense/main.py` 以 T004／T026 的 keyed target projection 更新 sticky target、aim assist、tracker、HUD 與 aircraft type；明確處理另一架進框時不得跳鎖、target 終止／progress 歸零時才重選，以及 scope／weapon／phase reset。
- [X] T029 [US3] 在 `air_defense/rules.py` 與 `air_defense/main.py` 收斂 anti-air fire gate 與 missile target lookup：必須同時滿足 scope、current target、可見、原始 frame 內、green ready、CD 完成；維持多枚 missile 對不同 aircraft 的指定 target，禁止 stale target 轉傷其他飛機。
- [X] T030 [US3] 在 `tests/test_airstrike_guidance.py`、`tests/test_hud_wave.py` 與 `tests/test_game_lifecycle.py` 執行 US3 focused tests、lock fire gate smoke，保留 frame 2×、0.25／0.75 秒衰減與 aim-assist 限制結果供 T058 traceability review；compile 與完整 suite 留到 T054–T055。

**Checkpoint**：單架與多候選 target 都能以純規則驗收；防空 UI 不會用 frame 顏色冒充 target progress，且不存在衰減期間誤發射。

---

## Phase 6: User Story 4 — 同時處理整波敵機並進入地面戰（Priority: P1）

**Goal**：同波所有 aircraft 同時以水平隊形出場並獨立更新；全波 destroyed 後只建立一次 aggregate ground encounter，零 crew 直接下一波，任一 impact 全域失敗。

**Independent Test**：啟動至少兩架的固定 wave，確認同 frame 出場；摧毀一架後其他架繼續；全波 destroyed 後一次生成全部 ground crew，再清除後一次生成下一波。

### Tests for User Story 4（先寫並確認失敗）

- [X] T031 [P] [US4] 在 `tests/test_rules.py` 撰寫 failing tests，驗證 `WaveRuntime` 的 all-destroyed gate、部分 status、ID 去重、formation offset、`create_for_wave(wave_number, aircraft_ids, aircraft_types, random_source=None)` 的 crew 合併／`wave-<wave_number>` identity／random consumption、source IDs、Boss 保留與 zero-crew 結果。
- [X] T032 [P] [US4] 在 `tests/test_game_lifecycle.py` 撰寫 failing integration tests，驗證全波 simultaneous spawn、partial destruction continues air phase、single aggregate encounter、zero-crew next wave、impact global game over 與 duplicate transition guard。

### Implementation for User Story 4

- [X] T033 [P] [US4] 在 `air_defense/rules.py` 實作 `EncounterFactory.create_for_wave(wave_number, aircraft_ids, aircraft_types, random_source=None)`，依 aircraft ID／type 固定順序合併 crew，為成員建立不碰撞的 source-prefixed IDs，使用 `wave-<wave_number>` group identity，明確控制 NORMAL 每個 source ID 最多一次 `randint`、固定人數 type 不消耗 random，保留既有人數與生命規則，並讓 `create_for_aircraft(...)` 繼續作 wrapper。
- [X] T034 [P] [US4] 在 `air_defense/scene.py` 將 aircraft visual adapter 改為 keyed entity map，實作 per-ID create／update／remove、formation position、health metadata 與全波 clear；確保移除一架不會 destroy 或 disable 其他 aircraft entity，並依賴 T004 的 collection ownership。
- [X] T035 [US4] 在 `air_defense/main.py` 將 wave start／next wave 的 `_spawn_current_aircraft()` 改為一次建立完整 roster、計算水平 formation positions、登錄每架 Aircraft 與 runtime status，並在每 frame 以 stable ID 順序 advance 所有尚存 aircraft；使用 T034 的 scene keyed API。
- [X] T036 [US4] 在 `air_defense/main.py` 將 guided missile update 改為依 `target_aircraft_id` 查找 aircraft collection，允許多枚 missile 同時追蹤不同目標，並在 target destroyed／impact／expired 時清理正確的 missile 而不轉移 target。
- [X] T037 [US4] 在 `air_defense/main.py` 與 `air_defense/state.py` 實作 all-aircraft-destroyed → single aggregate encounter → ground clear → next wave 的 guarded transition；crew 為零時直接取下一個 `WavePlan`，不得進入空 ground phase 或重複生成。
- [X] T038 [US4] 在 `air_defense/main.py` 與 `air_defense/scene.py` 實作任一 aircraft impact 的 immediate terminal cleanup，停止其他 aircraft、missile、ground、lock、HUD dynamic update，並保留最後 wave card snapshot 與 game-over reason。
- [X] T039 [US4] 在 `tests/test_rules.py`、`tests/test_game_lifecycle.py` 與 `tests/test_airstrike_guidance.py` 執行 US4 focused tests 與至少一次 Ursina spawn smoke，確認完整 wave lifecycle 不破壞既有 guided missile／Boss／city rules，保留結果供 T058 traceability review；compile 與完整 suite 留到 T054–T055。

**Checkpoint**：US3 的 target selection 可套用到多架飛機；US4 完成後一架飛機被擊落不再觸發 ground transition，整波才會轉換。

---

## Phase 7: User Story 5 — 讀懂武器冷卻與狙擊瞄準鏡（Priority: P2）

**Goal**：三種武器在目前準心下方顯示各自 CD bar；狙擊槍 scope 使用 35° FOV、圓形視野、十字線與中央紅點，不顯示棋盤格且與其他準心互斥。

**Independent Test**：分別射擊防空炮、狙擊槍、手槍，確認 CD 從空填滿且切槍不污染；開關 sniper scope 確認圓形遮罩與 camera FOV／reticle lifecycle。

### Tests for User Story 5（先寫並確認失敗）

- [X] T040 [P] [US5] 在 `tests/test_hud_wave.py` 撰寫 failing cooldown／scope view tests，驗證 AA 1.25 s、sniper 0.75 s、pistol 0.20 s 的 fill ratio、ready color、空手隱藏與 scope visual flags。
- [X] T041 [P] [US5] 在 `tests/test_game_lifecycle.py` 撰寫 failing weapon lifecycle tests，驗證射擊後 CD 從空開始、切槍讀取獨立 cooldown、scope close 不重置 weapon CD、`START_GAME`／new wave／`GAME_OVER`／`RETURN_TO_MENU` 將三把 CD 歸零、AA lock reset，以及 sniper scope close／phase transition 的 camera 與 UI reset。

### Implementation for User Story 5

- [X] T042 [P] [US5] 在 `air_defense/rules.py` 完成 typed `WeaponCooldownView` 與 active weapon mapping，從各 weapon object 的 `fire_cooldown` 推導剩餘秒數、duration、fill ratio 與 ready，禁止 HUD 產生第二份 timer；在 `air_defense/main.py` 或 session controller 暴露集中 `reset_weapon_cooldowns(...)` helper。
- [X] T043 [US5] 在 `air_defense/hud.py` 建立準心下方的透明 weapon CD track／fill bar，實作冷卻黃色、ready 綠色、空手／非 gameplay 隱藏與切槍後立即讀新 weapon view 的排版。
- [X] T044 [P] [US5] 在 `air_defense/hud.py` 將 sniper overlay 改為程序化圓形視野／圓外深色遮罩、十字線與中央小紅點，移除 checkerboard 可能來源，並讓 CD bar、lock bar、scope elements 不互相重疊。
- [X] T045 [US5] 在 `air_defense/main.py` 與 `air_defense/scene.py` 保留 35° sniper FOV，接上 scope open／close、weapon switch、ground exit、game-over reset 與 mutually exclusive reticle visibility；在 start／new wave／game over／return menu 呼叫 T042 的 CD reset helper，確認 anti-air frame／pistol reticle 不與 sniper overlay 同時顯示。
- [X] T046 [US5] 在 `tests/test_hud_wave.py`、`tests/test_game_lifecycle.py` 與 `air_defense/main.py` 的 smoke entrypoint 執行 US5 focused tests 與三武器手動射擊驗收，保留 cooldown／scope evidence 供 T058 traceability review；compile 與完整 suite 留到 T054–T055。

**Checkpoint**：US5 不改變既有 damage／missile 規則；玩家能只從 CD bar 判斷目前武器是否 ready，scope 視覺不存在 checkerboard 或 overlay 疊加。

---

## Phase 8: User Story 6 — 看見地面敵人的攻擊方向（Priority: P2）

**Goal**：每次既有 ground attack 成功時產生短暫、朝玩家方向的黃色 elongated tracer，且只提供視覺回饋，不重複 damage。

**Independent Test**：讓一名／多名 ground enemy 攻擊，確認每次有獨立 tracer、方向由 enemy 指向 player、到期自動清除，生命／cooldown／統計仍只有既有一次變化。

### Tests for User Story 6（先寫並確認失敗）

- [X] T047 [P] [US6] 在 `tests/test_hud_wave.py` 撰寫 failing tracer geometry／lifetime tests，驗證 start／target、head 的線性 travel progress、固定 tail length、預設 `0.18 s` lifetime、黃色 visual metadata、多 attacker effect identity 與到期條件。
- [X] T048 [P] [US6] 在 `tests/test_game_lifecycle.py` 撰寫 failing no-duplicate-damage tests，驗證同一 ground attack 最多一個 tracer、不新增 collision damage、不改 attack cooldown／enemy defeated 統計，且 game-over／encounter clear 會清除 effects。

### Implementation for User Story 6

- [X] T049 [P] [US6] 在 `air_defense/entities.py` 新增 engine-independent `GroundTracerEffect`（ID、start、target、remaining／lifetime、travel_progress），以 `advance(delta_seconds)` 線性移動 head、保留固定 tail 並在 progress 1 到期，明確標註它不擁有 damage、collision 或 statistics 行為。
- [X] T050 [P] [US6] 在 `air_defense/scene.py` 實作 `create_ground_tracer(...)`、每 frame `update_ground_tracer(...)`、head／tail 方向／長度計算、黃色 elongated mesh 建立、progress 到期 destroy 與 dynamic entity bookkeeping，支援多條 tracer 同時存在。
- [X] T051 [US6] 在 `air_defense/main.py` 的 `_update_ground_combat()` 將 tracer 建立掛在既有 `mark_attacked()` 與 `apply_enemy_hit()` 成功事件之後，使用 enemy／player world position 計算方向，禁止 tracer 自行呼叫 damage。
- [X] T052 [US6] 在 `air_defense/main.py` 與 `air_defense/scene.py` 補上同一 attack event 的唯一 effect guard，以及 ground clear、aircraft impact、game over、return menu 時的 tracer cleanup；保留既有 missile explosion／effect lifetime。
- [X] T053 [US6] 在 `tests/test_hud_wave.py`、`tests/test_game_lifecycle.py` 與 `air_defense/scene.py` 的 effect smoke 執行 US6 focused tests、多敵人同步攻擊手動驗收，保留 tracer／no-duplicate-damage evidence 供 T058 traceability review；compile 與完整 suite 留到 T054–T055。

**Checkpoint**：黃色 tracer 能清楚表達攻擊來源與方向，但不會變成第二套 projectile／damage system。

---

## Phase 9: Polish & Cross-Cutting Concerns

**目的**：完成全功能驗證、清理與交付證據；不在此階段加入未列於 spec 的新功能。

- [X] T054 [P] 對 `air_defense/` 與 `tests/` 執行 `python -m compileall air_defense tests`，檢查 unused imports、stale scalar／target references、debug output 與明顯重複邏輯。
- [X] T055 [P] 對 `tests/` 執行 `python -m unittest discover -s tests -p "test_*.py" -v`，確認既有回歸與 004 新增測試全部通過，記錄實際測試數於 `specs/004-air-defense-hud-wave/quickstart.md`。
- [X] T056 [P] 依 `specs/004-air-defense-hud-wave/quickstart.md` 執行 Ursina app construction、start／reset／game-over smoke 與手動 reset matrix，記錄無 GUI 環境限制或實際畫面驗收結果。
- [X] T057 在 `specs/004-air-defense-hud-wave/quickstart.md` 記錄固定 SC-010 兩個子場景：空戰以 `WaveDirector.plan_wave(6, aircraft_count=6, cap=6)` 建立 6 架 aircraft、最多 6 枚 missile；地面壓力另以 6 組 `MANPOWER_SUPPORT`（最多 36 名 crew）與 6 條 tracer；兩個子場景都 warm-up 5 秒後每 1 秒取樣 30 秒，記錄最低 FPS 並要求 >= 60；若無法測量，記錄原因與已完成的 automated evidence，不宣稱未測量的數值。
- [X] T058 在 `specs/004-air-defense-hud-wave/spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/ui.md`、`quickstart.md` 與 `tasks.md` 做最終 traceability review，彙整各 story 的驗證 evidence 到 quickstart，確認 FR-001～FR-026、SC-001～SC-011、附件僅作視覺參考、分支規則與已知限制都有對應任務／驗證。

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 Setup（T001–T002）**：互相獨立，可平行開始。
- **Phase 2 Foundational（T003–T008）**：T003–T006 依 T001 的 constants／fixture 可平行；T007 依 T003、T004；T008 依所有基礎模型完成，並阻塞所有 user stories。
- **US1（T009–T014）**：依賴 Phase 2；T009、T010 可平行，之後依序完成 HUD card 與 main wiring。
- **US2（T015–T021）**：依賴 Phase 2，且建議在 US1 完成後執行以避免共同修改 `air_defense/hud.py` 的衝突；T015/T016 測試先於 T017/T018 實作，T019 必須等 T018。
- **US3（T022–T030）**：依賴 Phase 2 的 collection scaffold；T022、T023 測試可平行且必須先於實作；T024 與 T026 可在 T004 後分開實作，T025 必須等 T024，T027 必須等 T024–T026，main integration T028–T029 最後依序完成。
- **US4（T031–T039）**：依賴 Phase 2；T031、T032 測試可平行且必須先於實作，T033 可與 T034 分開實作但兩者完成後才進入 T035；full-wave controller／missile cleanup 依序整合。US3 的 target rules 可先完成，但兩個 story 的 `main.py`／`scene.py` 整合建議順序合併。
- **US5（T040–T046）**：依賴 US1–US4 的 HUD anchor、reticle 與 phase lifecycle；T040/T041 測試先於 T042/T044 實作，避免 CD／scope 覆蓋既有 UI。
- **US6（T047–T053）**：依賴 US4 的 aggregate ground phase 與既有效果 ticker；T047/T048 測試先於 T049/T050 實作，純 tracer tests 可先於 scene/main integration。
- **Polish（T054–T058）**：依賴所有要交付的 user stories；T054–T056 可平行，T057 應在整合 build 可穩定遊玩後執行，T058 最後完成。

### User story completion order

```text
Phase 1
  ↓
Phase 2 Foundational
  ├── US1 Player/City card ──→ US2 Wave/Aircraft card
  ├── US3 Target/Lock rules ──┐
  └── US4 Full-wave lifecycle ─┴─→ US5 Cooldown/Sniper scope
                                  └─→ US6 Ground tracer
                                           ↓
                                      Polish/verification
```

US1 是可展示的 MVP，但它仍需要 Phase 2 的 shared state foundation。US3／US4 的純邏輯部分可平行；由於兩者都會整合 `main.py`／`scene.py`，實際開發時應按任務順序合併以減少衝突。

### Parallel opportunities

- Setup：T001 與 T002。
- Foundation：T003、T004、T005、T006 可在同一 constants baseline 上分工；T007／T008 需等集合骨架完成。
- 每個 story 的 test tasks 以不同檔案為主，可先平行撰寫：T009/T010、T015/T016、T022/T023、T031/T032、T040/T041、T047/T048。
- US1 完成後，US2 的純 wave view（T017）可與 US3 的純 rules（T024）平行；T018 完成後才做同檔案的 T019，並避免兩人同時修改 `air_defense/hud.py` 的同一區塊。
- Polish：T054、T055、T056 可平行執行；T057 需要可遊玩的整合版本。

## Parallel Example: User Story 1

```text
Task T009: 在 tests/test_hud_wave.py 撰寫 player/city view tests
Task T010: 在 tests/test_game_lifecycle.py 撰寫 card freeze tests

完成測試後依序：
Task T011: 在 air_defense/hud.py 建立 card entities
Task T012: 在 air_defense/hud.py 實作 card view update
Task T013: 在 air_defense/main.py 接上 session 與 terminal snapshot
```

## Parallel Example: User Story 2

```text
Task T015: 在 tests/test_hud_wave.py 驗證 dots、alive ratio、overflow
Task T016: 在 tests/test_game_lifecycle.py 驗證 partial destroy 與 target type reset

可平行準備：
Task T017: 在 air_defense/rules.py 建立 WaveStatusView helper
Task T018: 在 air_defense/hud.py 建立 wave card
Task T019: 在 air_defense/hud.py 實作 overflow layout（等 T018 完成後）
```

## Parallel Example: User Story 3

```text
Task T022: 在 tests/test_airstrike_guidance.py 驗證 selection、sticky、decay
Task T023: 在 tests/test_hud_wave.py 驗證 frame、reticle、state color

可平行實作：
Task T024: 在 air_defense/rules.py 實作 frame／selection／reticle helper
Task T026: 在 air_defense/scene.py 擴充 projection target data（兩者均在 T004 後）

依序整合：
Task T025: 在 air_defense/rules.py 擴充 tracker（等 T024 完成後）

整合依序：
Task T027: 在 air_defense/hud.py 呈現 constrained reticle
Task T028: 在 air_defense/main.py 接上 keyed lock projection、tracker 與 HUD
Task T029: 在 air_defense/rules.py 與 air_defense/main.py 收斂 fire gate／missile target lookup（等 T028 完成後）
```

## Parallel Example: User Story 4

```text
Task T031: 在 tests/test_rules.py 驗證 runtime／factory aggregate rules
Task T032: 在 tests/test_game_lifecycle.py 驗證 simultaneous wave transitions

測試完成後可分工：
Task T033: 在 air_defense/rules.py 實作 create_for_wave
Task T034: 在 air_defense/scene.py 實作 keyed aircraft entities

整合依序：
Task T035: 在 air_defense/main.py 以 T034 的 scene API 一次 spawn 完整 roster
Task T036/T037/T038: 依序整合 missile lookup、wave transition 與 terminal guards。
```

## Parallel Example: User Story 5

```text
Task T040: 在 tests/test_hud_wave.py 驗證三武器 cooldown view
Task T041: 在 tests/test_game_lifecycle.py 驗證 scope／weapon reset

可平行處理：
Task T042: 在 air_defense/rules.py 完成 WeaponCooldownView
Task T044: 在 air_defense/hud.py 完成程序化 sniper scope 視覺

依序整合 T043（CD bar）與 T045（camera／互斥生命週期）。
```

## Parallel Example: User Story 6

```text
Task T047: 在 tests/test_hud_wave.py 驗證 tracer geometry／lifetime
Task T048: 在 tests/test_game_lifecycle.py 驗證 no duplicate damage

可平行處理：
Task T049: 在 air_defense/entities.py 建立 GroundTracerEffect
Task T050: 在 air_defense/scene.py 建立黃色 elongated visual

Task T051/T052 再將 effect 接到既有 ground attack 與 reset cleanup。
```

## Implementation Strategy

### MVP first（US1 only）

1. 完成 T001–T008，建立可測試的 `WaveRuntime`、reset 邊界與相容性 scaffold。
2. 完成 T009–T014，交付左上 player／city card。
3. 執行 US1 focused tests 與手動傷害／game-over freeze 驗收；compile、完整 suite 與 quickstart evidence 由最後的 Polish tasks 統一處理。
4. 若 MVP 驗證通過，再依序加入 US2、US3、US4；P2 的 US5／US6 可延後但不能跳過其獨立測試。

### Incremental delivery

1. Foundation ready：保留舊單架流程可啟動。
2. US1：左上狀態卡可獨立展示與驗證。
3. US2：右上 wave dots／alive percentage 可獨立反映 runtime。
4. US3：單一／多候選 target 的 lock／reticle／fire gate 可獨立驗證。
5. US4：全波 simultaneous aircraft、aggregate ground encounter 與 impact terminal 可獨立驗證。
6. US5：三武器 CD 與 sniper scope 可獨立驗證。
7. US6：ground tracer 可獨立驗證且不新增 damage path。
8. Polish：完成 quickstart、reset matrix、FPS 與最終 traceability。

### Format validation

本檔共 **58 個任務**：Setup 2、Foundational 6、US1 6、US2 7、US3 9、US4 9、US5 7、US6 7、Polish 5。所有任務均以 `- [X] Txxx` 紀錄完成狀態；`[P]` 只用於可平行任務；所有 user-story 任務含 `[US1]`～`[US6]`；每個 task description 均包含一個或多個明確檔案路徑。

### Traceability summary

| User story | Tasks | Main requirements covered |
|---|---:|---|
| US1 | T009–T014 | FR-001–FR-005、SC-001 |
| US2 | T015–T021 | FR-003–FR-005、FR-007、SC-002、SC-005 |
| US3 | T022–T030 | FR-008–FR-015、FR-025–FR-026、SC-003–SC-005、SC-011 |
| US4 | T031–T039 | FR-006–FR-007、FR-016–FR-018、FR-025–FR-026、SC-005–SC-006、SC-011 |
| US5 | T040–T046 | FR-019–FR-022、FR-025–FR-026、SC-007、SC-009、SC-011 |
| US6 | T047–T053 | FR-023–FR-024、FR-025–FR-026、SC-008、SC-010–SC-011 |

## Done When

- [X] T001–T058 完成或由負責人明確標註 deferred scope。
- [X] `python -m compileall air_defense tests` 通過。
- [X] `python -m unittest discover -s tests -p "test_*.py" -v` 通過。
- [X] `quickstart.md` 的 Ursina smoke、手動 reset matrix、FPS 限制與已知問題有實際證據。
- [X] 功能分支 `004-air-defense-hud-wave` 已完成 code review 前置檢查；未在 `main` 直接修改。
