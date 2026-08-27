# Research: 防空 HUD、動態鎖定與整波敵機

**Date**: 2026-08-27
**Feature**: `004-air-defense-hud-wave`

## Baseline findings

- `air_defense/state.py` 已有 `GameSession`、`WaveProgress`、`AircraftPhase`、`LockState` 與事件去重；目前資料模型仍以 `active_aircraft_id` 和單一 `active_encounter_id` 表示流程。
- `air_defense/entities.py` 的 `Aircraft`、`GuidedMissile`、`GroundEncounter` 與武器物件已封裝大部分自身狀態；`Aircraft` 已支援不同種類、Boss 生命值、前進與閃避。
- `air_defense/rules.py` 已有 3 秒鎖定、0.75 秒線性衰減、鎖定完成閃爍、投影邊界與每秒最多 3 度的瞄準輔助；本功能需要把判定從隱藏圓形改為可見白色矩形框，並使 tracker 具有目標黏著性。
- `air_defense/main.py` 目前每波只建立一架飛機，飛機摧毀後立即建立該架的地面遭遇；更新順序已明確分為效果、玩家／武器、空襲或地面戰、HUD。
- `air_defense/scene.py` 和 `air_defense/hud.py` 都以 Ursina 程序化幾何為主；場景已有多個導引飛彈、地面成員與短暫效果的生命週期管理，HUD 已有白框、追蹤圓環、武器欄、警告、Boss HP 和統計。
- 專案沒有需要引入的外部圖片資產；`assets/air_defense/README.md` 要求保留程序化 fallback。現有測試使用 Python `unittest`，基線完整套件為 62 tests passed。

## Decision 1: Extend the existing shallow architecture

**Decision**: 只擴充 `config.py`、`state.py`、`entities.py`、`rules.py`、`scene.py`、`hud.py`、`main.py` 與既有 tests，不新增服務層、資產管線或第三方套件。

**Rationale**: 功能是既有 Ursina 遊戲循環的延伸；純規則可留在 `state.py`／`rules.py`，圖形轉譯留在 `scene.py`／`hud.py`，可直接沿用憲章的可讀性與可測試性要求。

**Alternatives considered**:

- 新增 event bus 或 ECS：拒絕，因為本功能的跨物件規則數量有限，會增加抽象與除錯成本。
- 將所有波次狀態放在 `main.py`：拒絕，會使多飛機終止、重複事件與 reset 規則分散，難以純測試。

## Decision 2: Model one wave as a runtime collection

**Decision**: 保留 `WavePlan`／`WaveProgress` 作為波次 roster 與顯示資料，新增集中管理同波飛機 ID、每架 `AircraftPhase` 與終止結果的 `WaveRuntime`（或等價的 `GameSession` 內部集合）。`AirDefenseGame` 和 `AirDefenseScene` 改用 keyed collections，而不是單一飛機欄位。

**Rationale**: 所有飛機必須同時生成、獨立飛行與獨立結算；集合物件能保證「擊落一架不影響其他架」和「全部終止後才轉地面戰」是同一個明確邊界。既有 scalar 欄位可暫留為相容性 view，避免不必要地破壞舊測試與舊呼叫者。

**Alternatives considered**:

- 以 `aircraft_index` 逐架輪替：與需求的同時出場和整波進度矛盾，拒絕。
- 在每架 `Aircraft` 中自行判斷波次完成：會造成重複 transition，拒絕；波次完成應由集中規則以 ID 去重判斷。

## Decision 3: Use the visible rectangle as the anti-air lock boundary

**Decision**: 將目前 `AA_LOCK_FRAME_SIZE = 0.105` 的寬與高各乘以 2，目標值為 `0.210`。白框在白色狀態下固定顯示，矩形邊界含邊界值；移除隱藏 15% 圓形作為主要鎖定資格的角色。可見、在框內的目標才累積鎖定。

**Rationale**: 使用者要求白框是玩家可理解的實際邊界，且無論未鎖定、鎖定、衰減或完成都不變色。保留舊圓形常數只作相容性或測試過渡，新的選取與 fire gate 不得再依賴它。

**Alternatives considered**:

- 白框只作裝飾、繼續使用隱藏圓形：玩家看到的範圍與實際規則不一致，拒絕。
- 讓框線依鎖定狀態變紅／綠：違反白框固定白色的明確需求，拒絕。

## Decision 4: Keep one sticky target and interpolate a constrained reticle

**Decision**: 自動選取可見且在白框內、距離畫面中心最近的飛機；選定後只要目標尚未摧毀、撞擊、終止或鎖定進度衰減至 0%，就不切換到其他飛機。小準心以白框中心為起點，依鎖定比例向目標投影位置插值，並在矩形邊界內 clamp；投影暫時不可用時保留最後有效位置並繼續套用邊界限制。

**Rationale**: 這同時表達「正在追蹤哪一架」與「越瞄越準」，也避免另一架飛機短暫進框造成跳鎖。鎖定離框時 tracker 仍按既有 0.75 秒線性衰減，準心不能跑出框，也不能在衰減期間發射。

**Alternatives considered**:

- 每幀重新選最近目標：會在多目標場景中跳鎖並保留錯誤進度，拒絕。
- 直接把準心吸到目標中心：沒有逐步收斂的視覺回饋，且削弱玩家追蹤操作，拒絕。

## Decision 5: Preserve existing lock timing and firing gates

**Decision**: 延續 3.0 秒累積、0.75 秒衰減、0.12 秒閃爍半週期、expanded aim-assist 1.5 倍範圍與每秒最多 3 度修正。只有 scope 開啟、目前目標仍在白框內、可見、tracker 為 `GREEN_READY` 且武器 CD 完成時才可發射。

**Rationale**: 這些規則已由既有 feature 003 建立並測試；本功能只改變目標集合與邊界語意，避免重新設計已驗證的操作手感。完成時小準心由短暫紅閃轉為綠色，白框不參與顏色提示。

**Alternatives considered**:

- 目標離框但 100% 時仍允許射擊：會使白框和衰減規則失效，拒絕。
- 關閉 scope 時讓進度衰減而非立即 reset：與既有 scope lifecycle 不一致，拒絕。

## Decision 6: Spawn the full air wave, then one aggregate ground encounter

**Decision**: 波次開始時依 roster 一次建立全部飛機，使用固定且可辨識的橫向 formation offset；所有飛機各自 advance、受傷、撞擊與移除，`IMPACTED` 以灰色 terminal dot 呈現且不計入 alive ratio。只有全波飛機都摧毀後才以一次 `create_for_wave(wave_number, aircraft_ids, aircraft_types, random_source=None)` 建立該波所有地面敵人；地面人數為零時直接產生下一個 `WavePlan`。

**Rationale**: 明確的階段邊界可避免某一架擊落就提前進入地面戰，也能讓右上卡片用同一個 roster 計算存活比例。任一架撞擊城市仍是全域失敗，必須先清理其他飛機、飛彈、鎖定與視覺效果。

**Alternatives considered**:

- 每架飛機各自產生地面小隊：與「整波一次出場」衝突，且會讓地面戰反覆切換，拒絕。
- 全部飛機共享一個位置／生命：無法表達部分擊落後其他飛機繼續飛行，拒絕。

## Decision 7: Make cooldown and scope visuals derived, procedural UI

**Decision**: 每種武器保留自己的 `fire_cooldown` 與既有時長（防空炮 1.25 秒、狙擊槍 0.75 秒、手槍 0.20 秒），HUD 只顯示目前持有武器的「剩餘 CD 反向換算為已完成比例」長條，準心下方由空填滿；同 phase 切槍保留各武器自己的 CD，`START_GAME`、new wave、`GAME_OVER`、`RETURN_TO_MENU` 由集中 helper 將三把 CD 歸零，scope close 不重置 CD；未持有武器、非遊戲階段時隱藏。狙擊鏡以程序化圓形視野、外圍遮罩、十字線與中央紅點呈現，不加入附件的棋盤格。

**Rationale**: cooldown 狀態已存在於武器物件，HUD 只需讀取 derived view，不製造第二份可漂移的計時器。程序化視覺符合資產政策，也能保留現有 35° scope FOV 與武器互斥顯示。

**Alternatives considered**:

- 為每種武器新增獨立 UI 圖片：需要外部資產和授權，且不必要，拒絕。
- 使用一個全域 CD：切換武器後會顯示錯誤數值，拒絕。

## Decision 8: Treat yellow ground rounds as visual-only effects

**Decision**: 地面敵人成功觸發既有攻擊事件時，同步建立預設 `0.18 s` 的黃色 elongated tracer；tracer 的 head 從敵人位置到玩家位置線性移動，tail 保留固定視覺長度，由 `scene.tick_effects`／`update_ground_tracer(...)` 到期清除；傷害、攻擊冷卻、統計仍由原本規則結算一次。

**Rationale**: 需求要的是方向與節奏回饋，不是新的 projectile simulation。視覺效果與傷害分離可避免重複命中，也能沿用目前 effects cleanup。

**Alternatives considered**:

- 讓 tracer 具備碰撞與傷害：會重複套用既有攻擊，拒絕。
- 只顯示固定 muzzle flash：無法清楚表達「朝玩家」方向，拒絕。

## Decision 9: Define canonical state ownership and aggregate factory inputs

**Decision**: `Aircraft.phase` 是單架物件移動／生命狀態的 authoritative owner；`WaveRuntime.aircraft_statuses` 是 HUD、alive count 與波次 transition 的 canonical snapshot。controller 在 `advance()`、`take_damage()` 或 `impact()` 回報 transition 後，必須呼叫 `sync_aircraft_phase(...)`，不得讓 UI 或 controller 直接各自推導第二份 phase。`LockOnTracker.target_aircraft_id` 是 sticky target 的唯一 owner，runtime／session scalar 只作 read-only compatibility mirror。`create_for_wave(...)` 接收 wave number、按 roster 順序的非空 ID tuple、key 完全相等的 type mapping 與可注入 `randint` source；group identity 固定為 `wave-<wave_number>`，NORMAL 每個 source ID 最多消耗一次 random，固定人數 type 不消耗 random。

**Rationale**: 明確的 ownership 與輸入契約消除多架飛機同步、aggregate encounter 及測試 fixture 的歧義，也避免 stale scalar 重新成為第二個真相來源。

## Decision 10: Use a measurable fixed performance scenario

**Decision**: SC-010 分為兩個固定 benchmark 子場景：空戰使用 `WaveDirector.plan_wave(6, aircraft_count=6, cap=6)` 的 6 架 aircraft 與最多 6 枚 missile；地面壓力另使用 6 組 `MANPOWER_SUPPORT`（最多 36 名 crew）與 6 條 tracer。兩個子場景都 warm-up 5 秒後每秒取樣 30 秒，最低觀測 FPS >= 60。無法建立 GUI／FPS counter 時記錄原因與 automated checks，不把未量測結果寫成通過。

**Rationale**: 固定 roster 與取樣協定讓效能結果可重現，並把「最大支援場景」從模糊描述轉成實作與驗收都能直接執行的條件。

## Decision 11: Use a transparent, high-contrast gameplay HUD

**Decision**: 遊戲內 gameplay HUD 的狀態卡、bar track 與 weapon inventory slot 不繪製不透明底色；主要資訊文字使用放大的白色字體。可保留低透明度白色輪廓作為卡片分隔，並保留彩色 icon、bar fill 與狀態 feedback 以維持語意辨識。狙擊鏡圓外遮罩與主選單／失敗對話框維持各自的視野／流程用途，不列入 HUD 卡片背景規則。

**Rationale**: 既有卡片底色會壓暗遊戲畫面，且小字與卡片內容容易難以閱讀或溢出。透明背景能保留戰場可見度，白色大字提高對比；將狙擊鏡遮罩與流程面板排除，可避免把視野效果或操作流程誤當成 gameplay HUD。

**Alternatives considered**:

- 所有文字與狀態都使用同一種顏色：拒絕，會降低 icon、進度 fill 與 ready／危險 feedback 的辨識度。
- 只放大文字但保留不透明卡片：拒絕，仍會遮住戰場並保留原本的背景問題。

## Validation baseline and open implementation risks

- 規則層優先使用 `unittest` 驗證：多飛機選取／黏著、矩形邊界、0.25 秒部分衰減、0.75 秒歸零、`Aircraft.phase`→ledger sync、全波 transition、空地面遭遇、CD 比例／lifecycle 與 tracer 線性移動／expiry。
- 圖形層使用 `python -m compileall`、既有 Ursina smoke construction，以及手動驗證卡片位置、白框尺寸、狙擊圓形遮罩、同波出場與固定 60 FPS benchmark。
- 主要整合風險是舊 scalar `active_aircraft_id`、`aircraft_entity`、`aircraft_index` 被測試或 UI 呼叫者直接讀取；實作時應保留相容性 accessor 或一次性遷移所有呼叫點，再移除只會產生歧義的舊語意。
- 另一個風險是 Ursina 的 screen-space circle／遮罩在不同解析度的比例；UI contract 以 viewport-relative 尺寸與不遮擋中央鎖定／武器欄為驗收條件，並保留程序化 fallback。
