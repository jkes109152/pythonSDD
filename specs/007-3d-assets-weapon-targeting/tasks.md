---

description: "3D 資產與武器瞄準整合的依賴排序實作任務"
---

# 任務：3D 資產與武器瞄準整合

**輸入**：`specs/007-3d-assets-weapon-targeting/` 下的 `spec.md`、`plan.md`、
`research.md`、`data-model.md`、`contracts/` 與 `quickstart.md`。

**前置條件**：目前工作分支必須是 `007-3d-assets-weapon-targeting`；不得在 `main` 或
其他分支上進行本功能修改。STL 與 OBJ 都是本機資產，不得加入版本庫。

**測試策略**：規格明確提供各故事的獨立測試與量化驗收，因此每個故事都先建立會失敗
的純規則、轉換器或 mock 測試，再完成實作；最後才執行圖形環境 smoke 與 FPS 驗收。

**專案結構**：單一 Python 3D 桌面遊戲專案。純規則與資料保持不依賴 Ursina；
`scene.py`、`hud.py`、`main.py` 負責 Ursina 整合；`tools/convert_stl_assets.py`
只使用標準函式庫。

## Phase 1：設定（共用基礎）

**目的**：先固定本機資產政策與可提交範圍，不改動既有遊戲規則。

- [X] T001 [P] 在 `.gitignore` 加入 `遊戲3d/*.stl`、`assets/air_defense/models/*.obj` 與轉換暫存檔規則，並確認既有使用者產物不會被加入版本庫。
- [X] T002 [P] 在 `assets/air_defense/README.md` 記錄七個 STL→OBJ 映射、Y-up／+Z-forward 座標契約、類型色、程序化 fallback 與本機資產限制。

---

## Phase 2：基礎能力（阻擋所有使用者故事）

**目的**：建立所有武器故事共用的白框倍率與暫時狀態清理邊界；完成前不得開始故事整合。

- [X] T003 [P] 在 `air_defense/config.py` 新增命名清楚的 `AA_MULTI_LOCK_FRAME_MULTIPLIER = 2.0`，保留普通防空炮既有 `AA_LOCK_FRAME_SIZE` 基準與其他武器常數不變。
- [X] T004 先在 `tests/test_game_lifecycle.py` 新增會失敗的清理邊界測試，再於 `air_defense/main.py` 與 `air_defense/hud.py` 建立共用的暫時武器 UI／鎖定清理入口，涵蓋 scope 關閉、武器切換、波次切換、game over、返回選單與重新開始；清理瞄準 UI 時不得取消已發射且仍有效的導彈。完成後立即執行 `python -m compileall -q air_defense tests` 並依 `quickstart.md` 做一次既有遊戲生命週期 smoke，通過才進入 US1。

**檢查點**：基礎倍率與生命週期邊界已固定；各使用者故事可以依序實作。

---

## Phase 3：使用者故事 1 — 在遊戲中辨識各類 3D 敵人與目標大樓（優先級：P1）🎯 MVP

**目標**：將七個本機 STL 轉成穩定命名的 OBJ，依遊戲用途載入模型、套用類型色與既有
玩法包絡，並在任何單一模型缺少或損壞時獨立 fallback。

**獨立測試**：準備七個輸出後建立普通／人力支援／快速／Boss 飛機、一般／Boss 人物
與大樓，驗證映射、方向、站立／落地與顏色；再移除或損壞單一 OBJ 重新啟動，確認只有
對應物件回退且遊戲仍可進入戰鬥。

### US1 測試

- [X] T005 [P] [US1] 在 `tests/test_asset_conversion.py` 新增七項 manifest 映射、binary／ASCII STL、非有限值與退化三角面清理、Y-up／+Z-forward、Ursina X 軸補償、`--check` 與單項失敗隔離測試，先確認測試會因缺少實作而失敗。
- [X] T006 [P] [US1] 在 `tests/test_rules.py` 擴充缺少或無法載入 `.obj` 時的程序化 fallback 測試，確認純規則模組不匯入 Ursina，並保留其他資產可獨立使用的驗收案例。

### US1 實作

- [X] T007 [US1] 在 `air_defense/asset_manifest.py` 建立無引擎的 `AssetSpec`、非持久化 `RuntimeAssetChoice` 與七項固定映射，包含來源／輸出檔名、遊戲角色、[contracts/assets.md](contracts/assets.md) 所列的 canonical 軸矩陣、類型色、fallback 模型、target extent／錨點與 runtime scale；確保人力支援飛機掉落的一般人物使用 `crew_normal`，且 choice 保存 fallback、均勻比例、`box` 碰撞器與載入錯誤。
- [X] T008 [US1] 在 `tools/convert_stl_assets.py` 實作 binary／ASCII STL 解析、有限值與退化面過濾、法線重算、嚴格套用 `contracts/assets.md` 的七列 Y-up／+Z-forward signed-permutation（不得依外觀推測）、Ursina OBJ loader X 軸補償、原子輸出、`--source-root`／`--output-root`／`--check` 參數與 0／1／2 結束碼；驗證每個矩陣行列式為 `+1`。
- [X] T009 [US1] 在 `air_defense/scene.py` 將飛機、地面人物與目標大樓建立流程接到 `asset_manifest.py` 與 `create_optional_model()`，依 `uniform_scale = min(target_extent_i / source_extent_i)` 套用七項 OBJ、類型色、中心／底面錨點、站立／落地位置與 `collider="box"`；來源包絡軸為零或載入／方向驗證失敗時只讓該物件 fallback，外部模型成功時移除舊的無條件旋轉／wing／head 補正，僅在 fallback 時保留必要輔助幾何。完成後立即執行 `python -m compileall -q air_defense tests tools` 與資產／fallback 手動 smoke，通過才進入 US2。

**檢查點**：`python tools/convert_stl_assets.py --check` 可獨立報告資產狀態；有輸出與無輸出兩種情境都能啟動並進入戰鬥。

---

## Phase 4：使用者故事 2 — 使用 RPG 進行有限射程的地面攻擊（優先級：P1）

**目標**：RPG 顯示與手槍相同的中央準心，並讓中心射線與合法目標驗證共用手槍的
12.0 包含邊界；超距離、飛機或資源不足時完全不消耗資源。

**獨立測試**：在混合戰鬥與地面戰切換 RPG，驗證準心互斥、12.0 內含邊界、超距離、
飛機、無彈藥與冷卻中情況，以及合法爆炸的既有半徑／傷害／去重規則。

### US2 測試

- [X] T010 [P] [US2] 在 `tests/test_weapon_system.py` 新增 RPG 距離等於 12.0 可開火、超過 12.0 拒絕、飛機目標拒絕、無彈藥與冷卻拒絕案例，並驗證拒絕不改變彈藥、冷卻或目標生命。
- [X] T011 [P] [US2] 在 `tests/test_new_weapons.py` 擴充 RPG 只選地面爆炸中心、半徑內每個地面敵人只受一次傷害、飛機不受範圍傷害的規則測試。
- [X] T012 [P] [US2] 在 `tests/test_hud_wave.py` 新增 RPG／手槍／狙擊槍／普通防空炮準心家族互斥測試，確認 RPG 與手槍的尺寸、子元件與顏色規格一致。
- [X] T013 [US2] 在 `tests/test_game_lifecycle.py` 新增 RPG 無效射擊與生命週期測試，確認超距離、飛機、無目標、無彈藥與冷卻中不扣資源，且切換武器、終止與重新開始不殘留 RPG 準心。

### US2 實作

- [X] T014 [US2] 在 `air_defense/rules.py` 將 `is_valid_target()` 的 RPG 射程來源改為 `config.PISTOL_MAX_RANGE`，保留 RPG 僅接受地面敵人、彈藥、冷卻與既有爆炸規則，並使用 `<= 12.0` 包含邊界。
- [X] T015 [US2] 在 `air_defense/main.py` 修改 `_fire_rpg()` 的中心 raycast 與第二次距離驗證，使兩者都使用 `config.PISTOL_MAX_RANGE`；任何驗證失敗都必須發生在 `mark_fired()`、扣彈與爆炸前。
- [X] T016 [US2] 在 `air_defense/hud.py` 以既有 crosshair builder 建立 RPG 準心，讓 RPG 與手槍共用樣式／尺寸／子元件，並接入唯一 active weapon family 與所有切換／終止清理路徑；RPG 不得開啟 scope。完成後立即執行 `python -m compileall -q air_defense tests` 與 RPG 準心／12.0 邊界手動 smoke，通過才進入 US3。

**檢查點**：RPG 的有效攻擊距離與手槍完全一致；無效操作零資源變化，且準心不與其他武器重疊。

---

## Phase 5：使用者故事 3 — 以多目標防空炮完成全數鎖定與多導彈齊射（優先級：P1）

**目標**：多目標防空炮在普通白框兩倍尺寸內追蹤所有可見敵機，不受 2／6 或其他固定
上限限制；只有全部有效目標 READY 時，才以一目標一枚導引導彈完成一次齊射。

**獨立測試**：建立 10 架以上同時在框內的敵機，驗證每個 ID 都有獨立小準心／進度，
部分鎖定不開火，全數 READY 建立 N 枚導彈且各自保存固定目標 ID；再驗證目標死亡、
導彈失效、scope 關閉與波次／終止清理互不污染。

### US3 測試

- [X] T017 [US3] 在 `tests/test_new_weapons.py` 將舊的固定容量案例改為 10 個以上目標，驗證 `MultiLockOnTracker` 不截斷、每個 ID 進度獨立、離框衰減／死亡移除與空集合不可 READY，先確認測試會阻止舊 2／6 行為。
- [X] T018 [P] [US3] 在 `tests/test_airstrike_guidance.py` 新增多目標鎖定快照與導引導彈測試，驗證所有目標 READY 閘門、N 枚導彈、每枚固定 `target_aircraft_id`、命中／過期／stale target 清除與目標隔離。
- [X] T019 [US3] 在 `tests/test_game_lifecycle.py` 新增多目標齊射生命週期測試，驗證部分鎖定、空目標與射擊前失效目標都不產生導彈或冷卻；成功齊射只套用一次冷卻，且 scope、武器、波次、game over、選單與重新開始會清除鎖定集合。
- [X] T020 [US3] 在 `tests/test_hud_wave.py` 新增 10 個以上動態多目標小準心／進度池測試，驗證白／紅／綠狀態、目標移除、固定大白框保持白色，以及普通 AA、RPG、手槍與狙擊 UI 互斥。

### US3 實作

- [X] T021 [US3] 在 `air_defense/rules.py` 擴充 `MultiLockOnTracker` 與 `MultiLockView`，移除 `target_capacity` 的實際截斷，保留舊 `target_capacity` keyword 參數但明確忽略，依穩定 ID 建立／保留獨立 `LockOnTracker`，處理加入、離框衰減、不可見／死亡移除，提供 `all_targets_ready` 與完整 `fireable_target_ids` 快照，並新增 frozen 的 `MissileVolley` 純資料物件契約。
- [X] T022 [US3] 在 `air_defense/entities.py` 修改 `MultiAntiAircraftGun.set_targets()` 不再截斷目標清單，讓 `mark_fired()` 一次清除當次目標；保留每枚 `GuidedMissile` 的唯一識別與固定 `target_aircraft_id` 語意。
- [X] T023 [US3] 在 `air_defense/scene.py` 讓飛機投影接受普通／多目標明確白框尺寸，輸出穩定 ID、可見性、畫面位置與框內狀態；更新多目標視覺標記的建立／移除，不以固定砲塔數或 6 作為容量。
- [X] T024 [US3] 在 `air_defense/main.py` 修改 `_update_airstrike()` 與 `_fire_multi_anti_aircraft()`：依武器分流普通／多目標白框，更新動態集合，射擊前重新驗證所有 ID，通過後逐 ID 建立 `GuidedMissile` 與 scene entity，將每組 `(target_id, missile_id)` 填入 `MissileVolley`，整批成功後一次套用冷卻，禁止直接 `target.take_damage()`，並維持既有導彈更新／命中／過期／stale 清理流程。
- [X] T025 [US3] 在 `air_defense/hud.py` 建立可回收的 `dict[target_id, reticle_entity]` 多目標準心池，依 `MultiLockView` 更新位置、進度與白／紅／綠狀態；目標離開、死亡或清理時立即隱藏／釋放，固定大白框維持白色。完成後立即執行 `python -m compileall -q air_defense tests` 與 10+ 目標多目標 UI／齊射手動 smoke，通過才進入 US4。

**檢查點**：10+ 目標可同時鎖定；部分鎖定不發射；全數 READY 時 N 個目標恰好產生 N 枚固定目標導彈，且一枚導彈的結果不改變其他導彈。

---

## Phase 6：使用者故事 4 — 透過升級擴大兩種防空炮的白框（優先級：P2）

**目標**：既有 `aa_whitebox` 是普通與多目標防空炮唯一有效的白框升級來源；普通白框
維持原基準，多目標永遠是普通白框的 2.0 倍，舊固定目標數升級只作 schema 1 相容。

**獨立測試**：購買一級或多級白框升級，重新進入普通與多目標瞄準模式，比較升級前後
尺寸與目標集合；重新載入存檔後確認升級保留，且商店／HUD 不再顯示舊容量規則。

### US4 測試

- [X] T026 [P] [US4] 在 `tests/test_economy.py` 新增 `aa_whitebox` 的價格／上限／有效倍率測試，驗證普通基準不變、多目標比例固定 2.0，且 `multi_anti_aircraft_targets` 不再出現在有效商店或限制目標容量。
- [X] T027 [P] [US4] 在 `tests/test_save_data.py` 新增 schema 1 舊 `multi_anti_aircraft_targets` 等級／快照讀取與保存相容測試，確認舊資料不因未知升級鍵失效，但不重新成為有效規則。
- [X] T028 [US4] 在 `tests/test_game_lifecycle.py` 新增白框升級保存／重新載入測試，驗證普通與多目標重新進入瞄準模式都使用相同升級倍率，且多目標仍為普通尺寸的 2.0 倍。

### US4 實作

- [X] T029 [US4] 在 `air_defense/progression.py` 讓 `aa_whitebox` 與 `effective_whitebox_scale()` 成為唯一有效白框升級來源，從 `upgrade_catalog()` 移除舊固定 target-count 有效項目，保留必要的舊 ID 相容常數／讀取語意而不讓它影響 runtime。
- [X] T030 [US4] 在 `air_defense/save_data.py` 調整 schema 1 的已知升級鍵、等級／上限驗證與保存策略，允許舊 `multi_anti_aircraft_targets` 資料被讀取／保留但跳過有效上限規則，並維持其他存檔錯誤檢查。
- [X] T031 [US4] 在 `air_defense/main.py` 移除 `multi_aa_target_count()` 的 runtime 依賴，普通白框使用 `AA_LOCK_FRAME_SIZE × effective_whitebox_scale`，多目標白框再乘 `AA_MULTI_LOCK_FRAME_MULTIPLIER`，並把升級後尺寸傳給投影與鎖定流程。
- [X] T032 [US4] 在 `air_defense/hud.py` 使用普通／多目標的有效白框尺寸呈現升級結果，只顯示 `aa_whitebox` 的有效升級資訊，不顯示舊固定目標容量或 2／6 限制。完成後立即執行 `python -m compileall -q air_defense tests` 與升級／重新載入手動 smoke，通過才進入 Phase 7。

**檢查點**：升級重載後仍有效；任一升級等級下普通與多目標白框比例都為 2.0，舊容量鍵不會限制鎖定或出現在商店／HUD。

---

## Phase 6：US1～US4 收尾與基線驗證

**目的**：在新增 RPG／陸地自動防禦與舊版介面補充前，先固定原始資產、武器、多目標
與升級故事的文件、啟動與回歸驗證結果；後續補充不得破壞此基線。

- [X] T033 [P] 更新 `specs/007-3d-assets-weapon-targeting/quickstart.md`，記錄 US1～US4 的啟動方式、模型／fallback、RPG 12.0 邊界、多目標齊射、白框升級與生命週期驗證入口。
- [X] T034 [P] 執行 `air_defense/`、`tests/` 的 `compileall` 與完整 `unittest`，確認 US1～US4 的資產、RPG、多目標、升級與清理回歸未失敗，並把實際結果寫入 `specs/007-3d-assets-weapon-targeting/quickstart.md`。
- [X] T035 [P] 以 `air_defense/main.py:create_application()` 建立 Ursina adapter，啟動第一波並在 `air_defense/scene.py` 實際建立四種飛機 OBJ 與目標大樓，確認模型可載入、用途映射正確且沒有 import／attribute error。
- [X] T036 審查 `air_defense/asset_manifest.py`、`air_defense/config.py`、`air_defense/progression.py`、`air_defense/save_data.py`、`air_defense/rules.py`、`air_defense/entities.py`、`air_defense/scene.py`、`air_defense/hud.py`、`air_defense/main.py` 與 `tests/` 的未使用匯入、重複規則、除錯輸出、stale reference、清理邊界及 `day1/`／`day2/` 範圍。

**檢查點**：US1～US4 的自動化回歸、轉換器與第一波 Ursina 建立 smoke 已通過；未完成的
圖形手動驗收與 PR 治理仍由 Phase 7 的 T058／T059 管理。

---

## Phase 6A：RPG／陸地自動防禦投射物與平衡補充

**目的**：補上使用者新增的可見射擊回饋與地面防禦平衡；不改變 OBJ 方向契約、
多目標防空炮或既有 RPG 合法射程規則。

- [X] T037 更新 `spec.md`、`plan.md`、`research.md`、`data-model.md`、`contracts/ui.md`、`checklists/requirements.md` 與 `quickstart.md`，明確記錄 RPG 綠色長方體、自動防禦砲台／曳光、32.0 射程、1 點傷害、普通敵人 3 HP、Boss 50% 累計上限與 0.20 秒基準 CD。
- [X] T038 [P] [US5] 在 `tests/test_new_weapons.py` 與必要的純規則測試新增 RPG 投射物資料、綠色／矩形尺寸、一般敵人三發擊倒、Boss 自動防禦 50% 上限、32.0 包含邊界與超距離拒絕案例，先確認測試會阻止舊的 80.0／20 傷害／1.5 秒行為。
- [X] T039 [P] [US5] 在 `tests/test_game_lifecycle.py` 新增 RPG 開火建立視覺投射物、自動防禦每次開火建立敵方同款曳光、射擊事件不重複傷害，以及波次／終止／返回選單清理投射物的 mock／生命週期案例。
- [X] T040 [US5] 在 `air_defense/config.py`、`air_defense/progression.py`、`air_defense/entities.py` 與 `air_defense/rules.py` 集中新增 32.0 射程、1 點基準傷害、0.20 秒基準 CD、普通地面敵人 3 HP、Boss 50% 自動防禦傷害下限與投射物資料／純規則判定；保留既有存檔格式與玩家武器語意。
- [X] T041 [US5] 在 `air_defense/scene.py` 建立 RPG 綠色長方體投射物的建立／移動／過期清理，讓 `GroundTracerEffect` 可使用自身顏色，並把陸地自動防禦砲台呈現為可辨識底座／槍管且沿用敵方黃色曳光效果；OBJ 使用 explicit-folder loader 確保實際模型可見。
- [X] T042 [US5] 在 `air_defense/main.py` 接入合法 RPG 射擊的視覺投射物、陸地自動防禦短射程／Boss 上限／低傷害／手槍級 CD 與每次開火曳光；視覺建立失敗不得重複或阻塞規則傷害。
- [X] T043 [US5] 完成補充需求 checkpoint：先執行 `python -m compileall -q air_defense tests tools`、新增測試與完整測試，確認 32.0 邊界、普通敵人三發、Boss 50%、0.20 秒 CD、RPG 綠色長方體及自動防禦黃色曳光結果，再進入 Phase 7。

---

## Phase 6B：原始 003 舊版瞄準介面與方向校正補充

**目的**：只把使用者提供的原始 `003-air-defense-lock-guidance` 提示詞中屬於舊版
普通防空瞄準的行為接回來；不把 003 的完整文件或無關規則複製到本功能。

- [X] T044 [US6] 更新 `spec.md`、`research.md`、`plan.md`、`data-model.md`、`contracts/ui.md`、`quickstart.md` 與 `checklists/requirements.md`，明確記錄舊版來源界線：55° 防空開鏡、較大固定框、連續縮小跟隨圓圈、3 秒進度、0.75 秒衰減及與新版／多目標的互斥關係。
- [X] T045 [P] [US6] 在 `tests/test_hud_wave.py` 新增舊版固定框／圓圈模式、圓圈半徑隨進度縮小、READY 顏色與新版動態準心互斥測試；在 `tests/test_game_lifecycle.py` 驗證設定頁模式為程式啟動期間狀態且可返回主選單。
- [X] T046 [P] [US1] 在 `tests/test_asset_conversion.py` 與必要的 scene mock 測試驗證可見模型倍率、fallback 維持原尺寸、每實例類型色／方向 metadata 隔離，並為 `tools/mark_asset_forward.py` 的來源軸矩陣加入非 GUI 測試。
- [X] T047 [US1] 在 `air_defense/asset_manifest.py` 固定七列來源映射、Y-up／+Z-forward 契約與飛機／人物／大樓可見倍率；在 `tools/convert_stl_assets.py` 重新產生本機 OBJ 並維持 ignored 產物。
- [X] T048 [US1] 在 `air_defense/scene.py` 維持 explicit-folder OBJ loader、每實例獨立 mesh／類型色與反向倍率 `BoxCollider`，使放大可見模型不改變既有基準 gameplay 包絡；載入失敗仍只回退該 asset ID。
- [X] T049 [US6] 在 `air_defense/hud.py` 恢復原始 003 的普通防空固定框／連續跟隨圓圈／進度視覺，圓圈由取得範圍依鎖定進度縮小至敵機外框；維持新版普通動態準心與多目標小準心的互斥分流。
- [X] T050 [US6] 在 `air_defense/main.py` 與 `air_defense/state.py` 接入主選單設定、新版／舊版模式、右鍵防空開鏡與生命週期清理；模式不得讀寫 Profile 或改變鎖定／射擊規則。
- [X] T051 [US1] 新增並驗證 `tools/mark_asset_forward.py`：顯示未旋轉 STL、前／後／左／右／上／下六條具名方向線及黃／青方向箭頭，支援逐項標記、部分儲存與 ignored JSON 輸出；人工結果確認前不得臆測新的 manifest 矩陣。
- [X] T052 [US1][US6] 執行 `python -m compileall -q air_defense tests tools`、完整 `unittest`、`python tools/convert_stl_assets.py --check` 與 `python tools/mark_asset_forward.py --help`，確認自動化結果及本機方向校正入口可用。

---

## Phase 7：收尾與跨故事品質驗證

**目的**：完成非目標行為回歸、清理、文件驗證與圖形環境驗收；所有故事完成後才能執行。

- [X] T053 在 `tests/test_rules.py` 補齊 FR-022 回歸案例，確認普通防空炮單目標、狙擊槍、手槍、飛機飛行、地面敵人、城市傷害、波次結算與程序化 fallback 的既有行為未被改變。
- [X] T054 在 `tests/test_game_lifecycle.py` 完成跨狀態清理矩陣，覆蓋 scope 關閉後既有導彈仍可飛行、武器切換、下一波、game over、返回選單與重新開始的 tracker／準心／導彈清理邊界。
- [X] T055 在 `tests/test_asset_conversion.py` 補上轉換器重複執行的確定性／原子輸出與所有結束碼驗證，確認單一失敗不刪除其他成功產物。
- [X] T056 檢查並清理 `air_defense/asset_manifest.py`、`air_defense/config.py`、`air_defense/progression.py`、`air_defense/save_data.py`、`air_defense/rules.py`、`air_defense/entities.py`、`air_defense/scene.py`、`air_defense/hud.py` 與 `air_defense/main.py` 的未使用匯入、重複規則常數、除錯輸出與違反責任邊界的暫時程式碼。
- [X] T057 依 `specs/007-3d-assets-weapon-targeting/quickstart.md` 執行 `python -m compileall -q air_defense tests tools`、`python -m unittest discover -s tests -p "test_*.py" -v`、資產轉換、`--check` 與方向工具 help，記錄完整測試結果及本機 STL／OBJ 未追蹤狀態。
- [X] T060 [US1] 建立七個外部 OBJ 的可見倍率、三軸均勻縮放、fallback 原尺寸與反向 box 基準碰撞包絡，並同步更新資產契約與驗證案例；後續倍率分流由 T064 固定。
- [X] T061 [US1] 在 `air_defense/lighting.py` 建立帶受控太陽高光的陰影 shader；在 `air_defense/scene.py` 接入暖色方向光、環境填光與固定地圖／飛行走廊 shadow bounds，讓外部 OBJ、地面與主要世界幾何呈現明暗及投射陰影。
- [X] T062 [US1] 更新 `spec.md`、`plan.md`、`data-model.md`、`contracts/assets.md`、`quickstart.md`、`assets/air_defense/README.md` 與必要測試，驗證倍率、方向線標籤、shader 載入、場景 smoke 與既有規則回歸。
- [X] T063 [US1] 依使用者已儲存的校正結果更新六個飛機／人物來源矩陣與軸 metadata，維持大樓既有方向矩陣；重新產生七個本機 OBJ 並更新方向／倍率文件。
- [X] T064 [US1] 將新版飛機／大樓外部模型可見倍率設為 `10.0`、陸地型態敵人設為 `5.0`，維持反向 box 基準碰撞包絡；重新執行 compileall、完整 unittest 與轉換器 `--check`。
- [X] T065 [US1] 修正方向校正器的 RGB 顯示與 OBJ 面繞序，修正 Ursina 反向航向造成的隱藏 roll，讓飛機與地面人物保持 +Y 向上；地面人物以水平 yaw 面向實際行走方向，並重新產生 OBJ。
- [X] T066 [US1] 修正人物瞄準判定過小：在 `AssetSpec` 增加 `aim_collider_multiplier`，由 `scene.py` 建立地面人物中央準心射線使用的獨立 box（包含 OBJ 與 fallback），且不改變人物外觀、武器射程、傷害或陸地自動防禦規則；補齊資產契約、測試與回歸驗證。
- [X] T067 [US1] 依最新補充將一般／Boss 地面人物的瞄準 box 調整為與敵人可見外觀相同大小：外部 OBJ 使用與 `visual_scale_multiplier=5.0` 相同的瞄準包絡，fallback 使用 unit local box 配合 fallback 尺寸；更新 manifest、scene、資產文件、quickstart 與回歸測試。
- [ ] T058 依 `specs/007-3d-assets-weapon-targeting/quickstart.md` 執行 1280×720、A=5 的遊戲 smoke、模型方向／fallback、舊版／新版瞄準、RPG 邊界與綠色長方體、自動防禦短射程／三發／Boss 50%／曳光、多目標 10+ 齊射、升級重載與生命週期手動驗收；暖機 5 秒後記錄 30 秒平均／最低 FPS，無圖形環境時明確記錄為未量測。
- [ ] T059 依憲章在目前功能分支推送並建立以 `main` 為 base 的 PR，於 `specs/007-3d-assets-weapon-targeting/quickstart.md` 記錄 PR URL、base branch、對應的 `spec.md`／`plan.md`／`tasks.md`、T057／T058 結果與已知限制；未通過審查不得宣稱可合併。

---

## 依賴與執行順序

### 階段依賴

- **Phase 1 設定**：T001、T002 互不依賴，可平行執行。
- **Phase 2 基礎**：T003、T004 在 Phase 1 完成後執行；T003 與 T004 可平行，但 T004 必須成為所有故事共用的清理邊界。
- **US1（Phase 3）**：T005、T006 可先平行撰寫；T007 在測試契約確定後建立 manifest；T008 依賴 T007；T009 依賴 T007、T008 及 T006 的 fallback 契約。
- **US2（Phase 4）**：T010～T013 先建立測試；T014 → T015 → T016，分別完成規則、主控制器與 HUD 接入。
- **US3（Phase 5）**：T017～T020 先完成測試；T021 → T022 → T023 → T024 → T025，依序完成純規則、實體、投影、控制器與 HUD。因為會修改 `rules.py`、`main.py`、`hud.py`，實作上接續 US2 以避免檔案衝突。
- **US4（Phase 6）**：T026～T028 先完成測試；T029 → T030 → T031 → T032，依序完成升級、存檔、控制器與 HUD。US4 接續 US3 以確保白框公式與多目標投影只保留一份來源。
- **Phase 6 收尾**：T033～T036 在 US1～US4 實作完成後固定基線；T035 的 Ursina 建立 smoke 不取代後續新增功能的圖形手動驗收。
- **Phase 6A 補充**：T037 先完成文件契約；T038、T039 先建立測試；T040 → T041 → T042 依序完成純規則／實體、scene 與 controller 接線；T043 是補充 checkpoint。
- **Phase 6B 舊版／方向補充**：T044 先同步來源界線文件；T045、T046 可平行補測試；T047 → T048 完成資產映射／scene，T049 → T050 完成舊版 HUD／主選單接線，T051 完成校正工具，T052 是自動化 checkpoint。
- **Phase 7 收尾**：T053～T056 與所有需要交付的使用者故事完成後才能執行；T057 是包含補充功能的自動化最終驗收，T060～T067 是模型可見性／日照／方向校正／人物瞄準包絡補充，完成後才進行 T058 圖形手動驗收，最後 T059 才是分支推送與 PR 治理，不得在驗收或審查失敗時宣稱完成。

### 使用者故事依賴

- **US1（P1）**：依賴 Phase 2；不依賴其他故事，完成後即可獨立驗證本機資產與 fallback。
- **US2（P1）**：依賴 Phase 2；規則上不依賴 US1，但因 `main.py`／`hud.py` 共用生命週期入口，與本工作分支採 US1 後接續實作。
- **US3（P1）**：依賴 Phase 2 與 US2 的共用武器／HUD 分流；其純規則可獨立測試，但整合需沿用既有 `GuidedMissile` 與同一清理入口。
- **US4（P2）**：依賴 US3 的多目標白框接線，才能驗證升級後普通／多目標尺寸與動態目標集合的一致性；存檔相容測試本身可獨立執行。
- **US1～US4 收尾**：T033～T036 依賴前述四個故事的 checkpoint，形成補充功能進入前的基線；T035 只驗證 adapter 建立，不宣稱完成方向／FPS 手動驗收。
- **US5（P1）**：依賴既有 RPG 開火、地面敵人、砲台與曳光 adapter；T038／T039 的測試先於 T040～T043，且不改變多目標防空炮的導彈齊射契約。
- **US6（P1）**：T044～T046 先固定原始 003 舊版範圍與測試；T049、T050 依賴既有鎖定 tracker／HUD 生命週期，但不得改變 US1～US5 的規則；T051 的方向輸出需在人工確認後才可作為 manifest 修改依據。

### 故事內執行原則

- 每個故事的測試任務先於同故事實作任務；先確認新測試能捕捉舊行為，再開始修改程式；T033～T036 只負責基線收尾，不重複建立另一份業務規則。
- 先完成純規則／資料，再接入 scene／HUD／main；每一個 checkpoint 都應能獨立啟動或完成無視窗測試。
- 同一檔案的任務不標記 `[P]`；不同檔案且沒有未完成依賴的測試任務才標記 `[P]`。
- 不得以增加固定目標容量、直接群體扣血、runtime 個別旋轉補正或忽略載入錯誤來繞過規格。

## 平行執行範例

### US1

```text
可平行：T005 tests/test_asset_conversion.py
可平行：T006 tests/test_rules.py
依序：T007 air_defense/asset_manifest.py → T008 tools/convert_stl_assets.py → T009 air_defense/scene.py
```

### US2

```text
可平行：T010 tests/test_weapon_system.py
可平行：T011 tests/test_new_weapons.py
可平行：T012 tests/test_hud_wave.py
可平行：T013 tests/test_game_lifecycle.py
依序：T014 air_defense/rules.py → T015 air_defense/main.py → T016 air_defense/hud.py
```

### US3

```text
可平行：T017 tests/test_new_weapons.py（接續該檔案既有 US2 任務後）
可平行：T018 tests/test_airstrike_guidance.py
可平行：T019 tests/test_game_lifecycle.py（接續該檔案既有 US2 任務後）
可平行：T020 tests/test_hud_wave.py（接續該檔案既有 US2 任務後）
依序：T021 air_defense/rules.py → T022 air_defense/entities.py → T023 air_defense/scene.py → T024 air_defense/main.py → T025 air_defense/hud.py
```

### US4

```text
可平行：T026 tests/test_economy.py
可平行：T027 tests/test_save_data.py
依序：T028 tests/test_game_lifecycle.py → T029 air_defense/progression.py → T030 air_defense/save_data.py → T031 air_defense/main.py → T032 air_defense/hud.py
```

## 實作策略

### MVP 優先（US1）

1. 完成 Phase 1 設定與 Phase 2 基礎。
2. 完成 US1 的轉換器、manifest、Scene 映射與 fallback 測試。
3. 執行 `convert_stl_assets.py --check`、無模型 fallback 啟動與有模型手動 smoke。
4. 在 US1 checkpoint 通過前，不擴大到武器行為；通過後再進入 US2。

### 增量交付

1. US1：本機模型映射、方向校正入口與 fallback 可用。
2. US2：RPG 準心與 12.0 有限射程可用。
3. US3：多目標無固定上限、全數鎖定與 N 枚導彈齊射可用。
4. US4：白框升級共用、2.0 比例與舊存檔相容可用。
5. US5：RPG 綠色長方體、自動防禦曳光與受限平衡可用。
6. US6：原始 003 舊版普通防空瞄準可由設定頁選取，並與新版／多目標互斥。
7. Phase 7：完成回歸、手動驗收與 FPS 記錄後才提交審查。

### 交付治理

1. 所有工作只在 `007-3d-assets-weapon-targeting` 功能分支進行，不修改 `main`；feature metadata 由 `create-new-feature.ps1` 建立，Git 分支切換則以等價的獨立 Git 操作完成，因為本 repo 腳本本身不建立 Git branch。
2. 每個邏輯群組完成後保留可啟動狀態，並在 T004、T009、T016、T025、T032、T043、T052 checkpoint 記錄 compile 與對應 smoke 結果。
3. 交付前保留 `spec.md`、`plan.md`、`tasks.md` 與驗證結果的對應關係；依憲章由 T059 建立以 `main` 為 base 的 PR，通過審查與所有必要驗證後才可合併。

## 格式與完成條件

- 所有實作任務均以 `- [ ]` 或 `- [X]` 開頭，具有 `T001`～`T067` 編號；`[X]` 表示已完成任務。
- 使用者故事任務均具有 `[US1]`～`[US6]` 標籤；設定、基礎與收尾任務不加故事標籤。
- `[P]` 僅用於不同檔案且無未完成依賴的可平行任務。
- 每個任務描述都包含實際檔案路徑；沒有保留範本 placeholder 或模糊的「實作功能」任務。
- 交付前必須完成 T057、T058、T059；若無圖形環境，FPS 只能標記為未量測，且 T059 必須記錄 PR 的 base branch 與審查狀態。
