# Implementation Plan: 防空 HUD、動態鎖定與整波敵機

**Branch**: `004-air-defense-hud-wave` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-air-defense-hud-wave/spec.md`

## Summary

本功能將現有防空遊戲從「單架飛機、逐架轉地面戰」擴充為「整波飛機同時出場、空戰完成後一次建立地面遭遇」，並同步重製 HUD 狀態資訊。實作會保留既有 Ursina adapter、導引飛彈、敵機種類、Boss HP、城市／玩家傷害、滑鼠操作與事件去重，僅在既有 shallow package 中加入同波 runtime collection、sticky target lock、受限動態小準心、武器 CD view、程序化 sniper scope 與 visual-only ground tracer。

## Technical Context

**Language/Version**: Python 3.11+（目前工作區以 Python 3.13 執行；使用既有 package constraints）

**Primary Dependencies**: `ursina==8.3.0`；Python standard library `dataclasses`、`enum`、`unittest`；本功能不新增第三方依賴

**Storage**: N/A；所有波次、鎖定、CD 與短暫效果均為單次遊戲 session 的記憶體狀態

**Testing**: `python -m compileall air_defense tests`、`python -m unittest discover -s tests -p "test_*.py" -v`、Ursina app construction smoke、手動 gameplay／FPS 驗證

**Target Platform**: Windows desktop、offline single-player、keyboard + mouse；沿用目前 1280×720 遊戲視窗與滑鼠 camera input

**Project Type**: 3D desktop game application

**Performance Goals**: 維持既有 60 FPS 目標；SC-010 benchmark 分為兩個子場景：空戰固定呼叫 `WaveDirector.plan_wave(6, aircraft_count=6, cap=6)`，以 6 架同波 aircraft 與最多 6 枚 missile 驗證；地面壓力另以 6 組 `MANPOWER_SUPPORT`（最多 36 名 crew）與 6 條 tracer 驗證。兩個子場景都連續執行 30 秒，5 秒 warm-up 後每 1 秒取樣，最低觀測 FPS 必須 >= 60；無 GUI 時只記錄限制與 automated evidence，不宣稱未測量結果；所有 UI 以有限數量的程序化 entity 建立

**Constraints**: 不在 `main` 分支修改；所有變更只在 `004-air-defense-hud-wave` 功能分支。domain rules 不得依賴 Ursina；不引入外部 HUD／scope 圖片；白框寬高從 `0.105` 各自放大至 `0.210` 且全程白色；防空鎖定沿用 3.0 s 累積、0.75 s 線性衰減與 1.5×／3°/s aim assist；任一飛機撞城立即 game over；同波飛機及其地面敵人必須以集合／單一 aggregate encounter 管理；不新增搖桿、網路或存檔

**Scale/Scope**: 一個 session 同時處理 WaveDirector 當前 wave plan 的完整 air roster、每架獨立 aircraft／missile target、至多一個 sticky anti-air target、一個 aggregate ground encounter，以及有限壽命的 ground tracer effects；SC-010 另以 6 架 aircraft 的空戰子場景與 6 組 `MANPOWER_SUPPORT` 的地面壓力子場景驗證效能；不改造 day1/day2 其他專案。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Phase 0 gate: PASS

| Principle / gate | Evidence |
|---|---|
| I. Readability first | 沿用現有 shallow modules；將新責任分成 wave runtime、target selection、HUD view 與 scene adapter，不新增無需求的 framework。 |
| II. Encapsulated game objects | `Aircraft`、`GroundEncounter`、武器與 tracer 保留自身狀態；跨物件 transition 由命名的 `WaveRuntime`／session rule 集中處理。 |
| III. Small verifiable steps | 先以 `unittest` 驗證純集合／鎖定／CD／reset 規則，再整合 Ursina scene、HUD 與手動流程。 |
| IV. Explicit loop and boundaries | 計畫明確處理同波多物件、stable ID、impact terminal guard、scope close、zero-crew 與 duplicate callback。 |
| V. Appropriate scope/dependencies | `air_defense` 原本即以 Ursina 作為可執行遊戲 adapter；本功能重用它可避免在 HUD／scene 功能中途引入 Pygame 遷移風險。影響限定在既有遊戲模組，不新增套件、服務、輸入裝置或 persistence；domain rules 維持 Ursina-free，未來若遷移至 Pygame 可沿用規則層並替換 adapter。 |
| Spec / repository hygiene | 已有 `spec.md` 與 requirements checklist；本分支承接工作樹既有修改但不把 unrelated output／`day2/prj06.py` 納入本 feature。 |

## Design overview

### 1. Wave runtime and lifecycle

1. `WaveDirector.plan_wave()` 仍提供固定順序的 `WavePlan`；session start 將它轉成 `WaveProgress` 與新的 `WaveRuntime`。
2. runtime 依 roster 一次產生 deterministic aircraft IDs，`AirDefenseGame` 維護 `dict[id, Aircraft]`，`AirDefenseScene` 維護 `dict[id, Entity]`。`WaveRuntime.aircraft_statuses` 是 wave UI／alive count 的 canonical ledger；`Aircraft.phase` 是單架移動／生命的 authoritative state，controller 在每次受控 transition 後以 `sync_aircraft_phase(...)` 更新 ledger。formation 用集中 config（初版水平間距 10.0 world units）計算，所有飛機在同一 update boundary 前完成建立。
3. 每個 frame 以穩定 ID 順序 advance 全部尚存飛機，再處理各自 impact／missile hit／damage。destroyed 只標記該 ID 並將 dot 更新為 gray；不可清除或暫停其他 aircraft。
4. 任一 impact 先進入 `GAME_OVER`，停止後續 aircraft／missile／ground／HUD 動態更新並清理 scope、target 與 effects。
5. 只有 runtime 的所有 aircraft status 都是 `DESTROYED` 時才清除空戰 entity，呼叫 `EncounterFactory.create_for_wave(wave_number, aircraft_ids, aircraft_types, random_source=None)` 一次合併整波 crew；零 crew 直接取得下一個 plan。aggregate encounter cleared 後才建立下一波全部 aircraft。
6. 舊的 `active_aircraft_id`、`aircraft_index` 等欄位在遷移期保留為 compatibility view；`LockOnTracker.target_aircraft_id` 是 target owner，runtime／session scalar 只作 controller 更新的 read-only mirror。所有實際 transition 以 runtime 集合和 event ID 為準，避免重複 callback 造成重複生成／統計。

### 2. Target selection, lock and reticle

1. scene 對每架可見 aircraft 產生帶有 ID、screen／HUD position、radius、distance-to-center、visibility 與 `in_lock_frame` 的 `AircraftScreenTarget`。
2. target selector 先保留現有 target（只要未終止且 progress > 0），否則從「可見且在原始白色矩形框內」的候選中選距中心最近者，使用 ID 作 deterministic tie-break；expanded 1.5× 矩形只供 aim assist。
3. `AA_LOCK_FRAME_SIZE` 改為 `0.210`；矩形邊界含邊界值，取代隱藏 15% 圓形成為 lock eligibility。舊圓形 helper 只在相容性呼叫仍需要時保留，不得影響新的 selector／fire gate。
4. `LockOnTracker` 以 target ID、visibility、frame membership 與 progress 為狀態。相同 target 框內按 3 s 累積，離框／不可見按 0.75 s 線性衰減；新 target、scope close、weapon switch、phase boundary 或 progress 歸零會清除舊 target。
5. 純函式將 target projection clamp 到 frame bounds，再依 progress 從 frame center 插值到 clamp position；沒有 target／0% 時回到中心。reticle 不得離開 frame。tracker 在衰減期間保持 red/non-ready，100% 且回框才是 green/fireable；完成紅閃沿用 0.12 s half-period。
6. aim assist 對 expanded rectangle（1.5×）內的可見目標維持每秒最多 3°，scope、武器與 visibility 條件由 controller 明確傳入；不把 aim assist 誤當成 lock eligibility。

### 3. HUD and visual feedback

1. `GameHUD` 新增兩張 viewport-relative HUD cards：左上 player／city，右上 wave／aircraft；卡片、bar track 與 inventory slot 使用透明背景，主要資訊採白色大字體，可保留低透明度白色輪廓作分隔。以程序化 panel、icon／glyph、bar 與 dot 建立，不載入外部圖片；右上依 roster 順序列出不重複敵機種類並另顯示 sticky target。顯示比例全部 clamp，dots 超量時縮小或換行。
2. 既有中央 lock label／lock bar、warning、Boss HP、FPS、stats、inventory 與 weapon text 保留並重新排版；frame 固定白色，dynamic small reticle 只在 anti-air scope active 時顯示。
3. `WeaponCooldownView` 從目前武器物件的 `fire_cooldown` 與既有 duration 推導 fill ratio，放在目前準心下方。冷卻中黃色、ready 綠色；切槍立即讀新武器，空手／非 gameplay 隱藏。
4. sniper scope 保留 35° FOV，以程序化圓形視野／外圍深色遮罩、十字線與中央紅點呈現，移除棋盤格；scope 與 AA／pistol reticle 互斥。
5. ground attack 仍先由既有 `CrewMember` cooldown 與 damage rule 結算，再建立一個短壽命黃色 elongated tracer；tracer 只由 `tick_effects` 移除，不碰 collision、damage 或 statistics。

## Public and internal interfaces

### State / rules

- `WaveRuntime(progress, aircraft_ids, aircraft_statuses, aircraft_types)`：提供 `alive_aircraft_ids`、`remaining_aircraft_count`、`alive_ratio`、`all_aircraft_destroyed`、`sync_aircraft_phase(id, phase)`、`mark_destroyed(id)`、`mark_impacted(id)`；controller 不直接寫入 status map。
- `GameSession`：新增／調整 `wave_runtime`、active target ID 與 aggregate encounter ID 的 lifecycle；保留既有 `transition(...)`、`reset_airstrike_guidance(...)`、event dedupe 與 compatibility accessors。
- `EncounterFactory.create_for_wave(wave_number, aircraft_ids, aircraft_types, random_source=None) -> GroundEncounter`：`aircraft_ids` 為 roster 順序的非空 tuple，`aircraft_types` key 集合必須完全相等；以 `wave-<wave_number>` 作 group key，固定順序合併 crew；NORMAL 每個 source ID 最多消耗一次 `randint`，固定人數 type 不消耗 random；`create_for_aircraft(...)` 以 wrapper 保留既有使用者。
- `LockOnTracker.set_target(target_id)`, `clear_target()`, `update(target_visible, target_in_frame, delta_seconds)`, `progress`, `fireable`, `flash_visible(...)`：target-aware 且 progress 永遠在 `[0, 1]`。
- `reset_weapon_cooldowns(weapons)`：由 controller 在 `START_GAME`、new wave、`GAME_OVER`、`RETURN_TO_MENU` 集中設為 0；weapon switch 與 scope close 不呼叫此 reset。
- Pure helpers in `rules.py`: `select_lock_target(...)`、矩形 frame membership／clamp、`reticle_position_for_progress(...)` 與 cooldown view calculation；所有 helper 接受明確參數，不讀 Ursina global。

### Scene adapter

- `create_aircraft(aircraft)`, `update_aircraft(aircraft)`, `remove_aircraft(aircraft_id, crash=False)`：改為 keyed collection，建立／更新／移除單架 entity。
- `project_aircraft_targets(aircraft_entities) -> dict[str, AircraftScreenTarget]`：為 target selection、aim assist 與 HUD 提供 projection；不可見 target 保留 identity，不能被另一架偷換。
- `apply_aircraft_aim_assist(target, delta_seconds)`：只執行 camera correction，不改 domain lock progress。
- `create_ground_tracer(start, target, lifetime=0.18)`、`update_ground_tracer(...)`／effect cleanup：以 head 從 start 到 target 線性移動、tail 維持固定視覺長度，progress 到 1 時清除黃色 elongated visual-only entity；不得加入 damage 或 collision。
- `create_crew(aggregate_encounter)`：一次建立 encounter 的全部 crew；既有 missile、crew 與 effect cleanup API 延續。

### HUD adapter

- `update_status_cards(player_view, city_view, wave_view)`：更新透明左右卡片、白色大字、roster-order aircraft type list、sticky target、dot color、percent、icons 與 progress bars。
- `update_lock(state, visible, progress, reticle_position, active=True)`：frame 子線段固定白色；只改小準心、文字、lock bar 的狀態色。
- `update_weapon_cooldown(view)`：更新準心下方 CD bar；無 view 時隱藏。
- `update_reticle(weapon, phase, scope_enabled, anti_air_scope_enabled)` 與 `update_session(...)`：維持既有入口或提供 compatibility arguments，確保 scope／weapon family 互斥。

## Implementation sequence

1. **Configuration and pure model**: 將 frame 尺寸、formation spacing、tracer lifetime／visual dimensions 與 HUD layout constants 集中到 `config.py`；在 `state.py` 建立 `WaveRuntime`、wave status derived values、`sync_aircraft_phase` 與 reset／terminal guards；擴充 `AircraftScreenTarget`／entity data model。
2. **Rule layer first**: 新增 target selector、矩形 boundary／reticle interpolation／clamp、target-aware `LockOnTracker`、cooldown ratio 與 aggregate encounter factory。先更新／新增純 `unittest`，再保留舊 wrapper 的兼容測試。
3. **Scene collection integration**: 先在 `scene.py` 完成 keyed aircraft entity map、per-ID projection／aim assist／removal 與 `update_ground_tracer(...)`，讓 controller 有穩定的 collection API；guided missile target lookup 也以 ID 查找。
4. **Session and controller lifecycle**: 將 `AirDefenseGame` 的單 aircraft／encounter flow 改為 keyed collections；明確執行 all-aircraft advance、每次 transition 後 `sync_aircraft_phase`、per-ID missile update、impact terminal、all-destroyed aggregate encounter、zero-crew skip、weapon CD reset 與 next-wave spawn。
5. **HUD integration**: 建立兩張狀態卡、blue/gray dots、alive percentage、current target type、固定白 frame、受限小準心、lock／CD bar 與程序化 sniper circle；保留並重新排版既有 warning、Boss、FPS、stats、inventory。
6. **Verification and documentation**: 執行 compile／unit／smoke，依 `quickstart.md` 手動驗收各 lifecycle matrix，記錄 FPS 與無 GUI 環境限制；檢查 unused imports、debug output、stale entity／target／missile cleanup，並由 `$speckit-tasks` 產生可執行任務後完成最終 traceability review。

## Testing strategy

### Pure rule and state tests

- `tests/test_rules.py`: `WaveRuntime` counts and ID dedupe、`Aircraft.phase`→ledger sync、aggregate encounter composition／group identity／random consumption、zero crew、rectangle inclusive boundary、closest-center target selection and deterministic tie-break。
- `tests/test_airstrike_guidance.py`: target stickiness、target switch reset、center-to-target reticle interpolation、frame clamp、3 s accumulation、0.25 s partial decay、0.75 s reset、re-entry resume、no-fire while out/decaying、1.5×／3°/s aim assist。
- `tests/test_game_lifecycle.py`: all-aircraft same-boundary spawn、partial destruction continues air phase、single aggregate ground transition、impact global game over、duplicate callbacks、scope／weapon／menu reset、stale missile target cleanup。
- `tests/test_hud_wave.py`: derived player／city／wave views, blue/gray terminal dots including `IMPACTED`, alive ratio clamp, cooldown fill values and linear ground tracer expiry data. If the existing test layout can cover these without a new file, keep the assertions in the nearest existing suite rather than duplicating fixtures.

### Integration and manual checks

- `compileall` must pass for every modified Python module.
- Existing full unittest suite must remain green; baseline is 62 tests passed before this feature.
- Ursina smoke must construct the app, start a session, create the complete first air roster, and exit without an attribute/import error.
- Manual flow must verify both status cards, 2× white frame, reticle center-to-target motion, sticky decay, all-aircraft lifecycle, individual CD bars, circular sniper scope without checkerboard, yellow tracers and reset matrix.
- Performance check runs two SC-010 sub-scenarios: air combat uses `WaveDirector.plan_wave(6, aircraft_count=6, cap=6)` with 6 aircraft and up to 6 missiles; ground stress uses six `MANPOWER_SUPPORT` groups (maximum 36 crew) and six tracers. In each sub-scenario, warm up for 5 seconds, sample every 1 second for 30 seconds, and require minimum observed FPS >= 60. If display measurement is unavailable, record the limitation and automated evidence instead of claiming a measurement.

## Project Structure

### Documentation (this feature)

```text
specs/004-air-defense-hud-wave/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui.md
├── checklists/
│   └── requirements.md
└── tasks.md                 # generated by $speckit-tasks; T001–T058 complete
```

### Source Code (repository root)

```text
air_defense/
├── config.py                 # frame, formation, HUD and tracer constants
├── state.py                  # WaveRuntime and guarded session transitions
├── entities.py               # aircraft, weapons, encounters and effect data
├── rules.py                  # selection, lock, wave, cooldown and pure math
├── scene.py                  # Ursina aircraft collections and visual adapters
├── hud.py                    # cards, reticles, scope and CD presentation
└── main.py                   # explicit frame order and controller orchestration

tests/
├── test_rules.py
├── test_airstrike_guidance.py
├── test_game_lifecycle.py
└── test_hud_wave.py          # derived HUD views and visual-effect lifecycle rules
```

**Structure Decision**: 選擇現有單一 `air_defense` desktop-game package，因為功能是目前 prototype 的垂直切片，不是新服務或新 app。`state.py`／`rules.py` 保持 Ursina-free，`scene.py`／`hud.py` 負責 engine translation，`main.py` 只負責顯式 update order 與跨物件 transition；測試集中於既有 `tests/`，不新增 service、database、asset pipeline 或深層 feature directory。

## Post-design Constitution Check: PASS

| Principle / gate | Post-design evidence |
|---|---|
| I. Readability first | 新增的責任只有 `WaveRuntime`、target selector、view helpers 與 tracer adapter；public methods 以 named operations 表達，不用隱性 global。 |
| II. Encapsulated game objects | aircraft／weapon／encounter 保持 object-local behavior；session 只集中波次 transition，scene 只管理 entity map，HUD 只 render view。 |
| III. Small, verifiable steps | sequence 先 pure tests、再 controller、scene、HUD；quickstart 定義 compile、unit、smoke、manual 和 FPS evidence。 |
| IV. Explicit loop and boundaries | stable ID loop、impact short-circuit、all-destroyed gate、aggregate encounter gate、scope／weapon／menu reset 與 event dedupe 都已在 plan／data model 定義。 |
| V. Appropriate scope/dependencies | 沿用已批准的 Ursina desktop exception，不新增 framework、外部資產或輸入設備；所有 tuning constants 集中於 `config.py`。 |
| No unresolved clarification | spec、research、data model、UI contract、quickstart 均未保留未決澄清標記或模板佔位符。 |

## Complexity Tracking

無需 constitutional exception。功能只在既有 Ursina vertical slice 內擴充，沒有新增 project、service、repository layer 或第三方依賴；既有 Ursina 例外已由前置 feature／constitution context 承接，本計畫不擴大其範圍。
