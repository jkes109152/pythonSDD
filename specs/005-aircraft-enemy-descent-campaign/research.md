# Phase 0 Research: 飛機擊落後敵人降落戰役

**Date**: 2026-08-27
**Feature**: `005-aircraft-enemy-descent-campaign`

## Research Scope

本階段以現有程式、004 已合併的設計文件、專案憲章與本次已確認的玩家規則為主要來源。此功能沒有外部服務、網路協定或新素材需求，因此不需要外部技術選型研究。

## Findings

### Existing runtime and dependency boundary

- `air_defense/main.py` 是 Ursina 3D desktop game 的 controller，依序處理輸入、cooldown、飛機、飛彈、地面遭遇、HUD 與 terminal state。
- `air_defense/state.py` 與 `air_defense/rules.py` 已將 session state、wave ledger、鎖定、武器規則與地面規則分離，且可在不建立 Ursina 視窗的情況下測試。
- `air_defense/scene.py` 維護 aircraft、crew、missile 與 tracer 的 scene entity map；`air_defense/hud.py` 負責 HUD 與瞄準視覺。
- `requirements-game.txt` 固定 `ursina==8.3.0`，本機 Python 為 3.13.5 且 Ursina 可匯入；本次不新增依賴。
- 功能開發前的 baseline 是 `python -m compileall -q air_defense tests` 通過，以及 84 件 unittest 全數通過；實作後的完整 suite 已擴充為 106 件測試，最新結果記錄於 `quickstart.md`。

### Current behavior relevant to this feature

- 004 已讓一波飛機以 `WaveRuntime` 同時存在，`aircraft_statuses` 是波次存活狀態的 canonical ledger。
- 目前 `AirDefenseGame._on_aircraft_destroyed()` 只在全波飛機都摧毀後呼叫 `EncounterFactory.create_for_wave()`，因此必須把生成時機移到單架飛機擊落事件。
- `GroundEncounter` 已支援 `source_aircraft_ids`，但 `add_reinforcement()` 仍是 stub；這是合併多個即時 drop batch 的最小延伸點。
- `CrewMember` 目前只有地面行為狀態，位置預設為固定 crash site；降落需要新增物件自身的降落狀態與計時，不應把計時散落在 scene controller。
- `damage_crew_member()` 目前只接受 `GROUND_COMBAT`，武器與武器架也以空戰／地面兩個 phase 分流；混合戰鬥必須集中調整這些 phase gates。
- `WaveDirector` 目前依波次編號遞增數量並每 10 波建立單一 Boss，與本次固定 18 波表不一致，必須改為有限、資料驅動的 roster。

## Decisions

### Decision 1: Reuse existing domain/adapter split

- **Decision**: 在 `state.py`、`entities.py`、`rules.py` 放純資料與規則，在 `scene.py`、`hud.py` 放視覺轉換，在 `main.py` 集中跨物件 lifecycle。
- **Rationale**: 符合憲章 I、II、III；降落與波次條件可用 headless tests 驗證，Ursina 只負責顯示和碰撞查詢。
- **Alternatives considered**: 新增獨立 drop manager 或新 feature framework；拒絕，因為會增加不必要的抽象層，且既有 `GroundEncounter`／`WaveRuntime` 已能表達所需邊界。

### Decision 2: Use an explicit hybrid phase and retain ground phase

- **Decision**: 新增 `HYBRID_COMBAT` 與 `VICTORY`。`AIRSTRIKE` 表示尚未有非空降落批次；同時有存活飛機與降落／地面敵人時使用 `HYBRID_COMBAT`；所有飛機終止但敵人仍存在時使用既有 `GROUND_COMBAT`；第 18 波雙條件完成後使用 `VICTORY`。
- **Rationale**: 明確表達玩家可同時處理兩類威脅，又保留現有地面戰與舊測試的責任邊界。若飛機沒有敵人，不應因空 batch 進入 hybrid。
- **Alternatives considered**: 以單一 boolean 表示 hybrid；拒絕，因為憲章要求可追蹤的明確 state transition，且 weapon／input gate 需要可測試的 phase。

### Decision 3: One aggregate encounter with per-aircraft drop batches

- **Decision**: 每架飛機擊落時由 factory 建立一個有來源 ID 的 drop batch，加入同一波的 aggregate `GroundEncounter`；每個 batch 保留來源飛機、成員與獨立降落時間，encounter 負責整波 ground-clear 判定。
- **Rationale**: 現有 controller、scene 與 weapon raycast 都以單一 `self.encounter` 工作；沿用 aggregate 可避免同時管理多個 active encounter，同時透過 source ID 防止重複生成。
- **Alternatives considered**: 每架飛機建立獨立 encounter；拒絕，因為會放大 weapon target、city damage、clear transition 與 reset 的同步複雜度。

### Decision 4: Model descent as a CrewMember-owned state

- **Decision**: 在 `CrewBehaviorState` 加入 `DESCENDING`，由 `CrewMember` 保存 descent start、landing target、elapsed、duration 與水平 spread offset，並提供單一 advance operation。落地後轉為現有 `IN_COVER` 流程。
- **Rationale**: 降落是敵人自身的狀態與行為；把它放在 entity 可保證 headless test 與 scene update 使用同一真相。controller 只協調批次與波次條件。
- **Alternatives considered**: 在 scene entity 上保存降落 timer；拒絕，因為會違反 domain state 封裝並使無視窗測試困難。

### Decision 5: Deterministic 18-wave table with derived special rotation

- **Decision**: `WaveDirector` 使用固定 18 個 roster，Boss slot 依表由左至右配置；`特` 依所有前置波次的特殊 slot 總數推導全戰役交替類型，避免呼叫順序影響結果。第 19 波不可規劃。
- **Rationale**: 直接反映玩家最後確認的表格，支援可重現測試與重開遊戲；Boss 不消耗特殊飛機的輪替序號。
- **Alternatives considered**: 保留「每波 +1、每 10 波單 Boss」公式；拒絕，因為與 18 波表衝突。

### Decision 6: Fixed, testable descent tuning

- **Decision**: 使用集中設定的 4.0 秒降落時間、±0.25 秒驗收容差與 2.5 world-unit 以內的 deterministic horizontal spread；落地保留擊落點 X/Z，只將 Y 對齊地面。
- **Rationale**: 符合「約 4 秒、空中分散、同 X/Z 地面」三項已確認偏好，且不依賴 random 便可驗證。
- **Alternatives considered**: 每名敵人使用隨機 spread 或每批不同 duration；拒絕，因為會造成難以重現的測試與不一致的玩家感受。

### Decision 7: Preserve existing enemy composition and visual scope

- **Decision**: 沿用目前 ground roster 規則：普通飛機 0–3 名、人力支援 6 名、快速飛機 0 名、裝甲 Boss 1 名。降落期間只顯示既有敵人模型與位置動畫，不新增 HUD countdown/progress 或新素材。
- **Rationale**: 使用者只要求生成時機與可攻擊降落，不要求改變敵人能力；保持範圍符合憲章 V。
- **Alternatives considered**: 為降落新增專用 enemy type、HUD bar 或 particle asset；拒絕，因為會擴大需求且沒有驗收依據。

## Resolved Unknowns

所有 Technical Context 需要的選擇均已由現有程式或已確認需求決定：runtime 為 Python 3.12+／Ursina 8.3.0、儲存為單次 session 記憶體、測試沿用 compileall／unittest／Ursina smoke／手動流程、平台為 Windows desktop offline single-player，沒有待處理的 clarification。
