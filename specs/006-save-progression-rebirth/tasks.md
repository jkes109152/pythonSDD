# 任務清單：持久化存檔、進度與重生戰役

**輸入**：`specs/006-save-progression-rebirth/` 下的 spec、plan、research、data-model、UI 契約與 quickstart

**前置條件**：006 的設計文件已完成；005 已合併至 `main`；既有 Ursina 執行環境例外依 004／005 治理備註沿用且不擴大；本任務清單與所有 SDD 文件使用繁體中文。

**測試策略**：規格明確要求先建立純邏輯測試，再接入狀態模組、場景、HUD 與手動流程，因此每個使用者故事都先列測試任務。

**任務格式**：`[P]` 表示可平行執行；`[USx]` 對應 `spec.md` 的使用者故事。

## 階段 1：設定與共用基礎

**目的**：建立可被後續純邏輯與存檔工作使用的檔案邊界與測試骨架。

- [X] T001 [P] 在 `air_defense/progression.py` 建立不依賴 Ursina 的進度規則模組骨架，保留既有 `air_defense` 匯入風格。
- [X] T002 [P] 在 `air_defense/save_data.py` 建立本機存檔模組骨架，定義存檔讀寫結果與警告回傳邊界。
- [X] T003 [P] 在 `tests/test_progression.py` 建立純關卡、經濟、回血與狀態規則的測試固定資料，確認測試可在沒有圖形視窗時執行。
- [X] T004 [P] 在 `tests/test_save_data.py` 建立隔離暫存目錄、五欄位與 JSON 往返測試固定資料。
- [X] T005 更新 `air_defense/__init__.py` 匯出新增的 `progression` 與 `save_data` 模組，不改變既有模組匯入結果（依賴 T001、T002）。

---

## 階段 2：基礎資料與狀態邊界

**目的**：完成所有使用者故事都依賴的 Profile、RunState、設定目錄與冪等結算基礎。

**重要關卡**：本階段完成前不得開始使用者故事實作；完成後才可依依賴平行處理各故事。

- [X] T006 在 `air_defense/progression.py` 定義集中式 `ProgressionConfig`、標準升級／武器 ID、A 公式、獎勵公式、重生費用公式、升級上限成長表、回血總額度、自動防禦每小關 20 發／每次射擊冷卻 1.5 秒／每次命中傷害 20、多目標鎖定升級價格與所有建議預設值。
- [X] T007 在 `air_defense/save_data.py` 實作 `SaveProfile`、結構版本（`schema_version`）1、預設 Profile、欄位型別驗證、最近完成 a-b 紀錄與 `max_aircraft_count == 2 + rebirth_count` 正規化；超過推導上限的等級視為損壞資料。
- [X] T008 在 `air_defense/save_data.py` 實作五個獨立存檔欄位的 `SaveStore`，包含 AppData 預設路徑、可注入測試根目錄、同目錄暫存檔、flush/fsync 與原子替換。
- [X] T009 [P] 在 `air_defense/state.py` 擴充 `GamePhase`、武器 ID 與結果事件，明確加入 `SAVE_SELECT`、`SHOP`、小關完成與個人主選單轉移。
- [X] T010 [P] 在 `air_defense/config.py` 清理 006 Profile 流程會使用的固定進度常數引用，保留純視窗、飛行、下降與場景常數，不放入 Profile 資料；005 整數波次相容 API 的邊界另以 `LEGACY_COMPATIBILITY_*` 明確隔離。
- [X] T011 在 `air_defense/state.py` 實作 `RunState` 與 `SaveProfile` 的邊界，建立單小關開始、完成、死亡、返回主選單時的暫時資料重置操作（依賴 T006、T007、T009）。
- [X] T012 在 `air_defense/state.py` 實作嘗試識別碼（`attempt_id`）、購買操作 ID、事件去重與獎勵／購買／重生結算防重機制，使相同回呼不會重複修改資料；RunState 清除後仍能回傳原獎勵結算結果（依賴 T011）。
- [X] T013 在 `tests/test_progression.py` 與 `tests/test_save_data.py` 補上基礎資料驗證、結構版本、預設值、最近完成紀錄、上限正規化與模組不匯入 Ursina 的測試，並執行語法檢查、基礎測試與入口啟動煙霧檢查（依賴 T006～T012）。

**關卡檢查**：Profile 與 RunState 邊界、五欄位存取介面、A／獎勵／重生公式與事件冪等防重檢查已可由無視窗測試驗證。

---

## 階段 3：使用者故事 1——選擇存檔並管理個人進度（P1）🎯 最小可行版本

**目標**：啟動時先選擇五個存檔，載入後進入只包含開始遊戲、升級商店與重生的個人主選單，不直接進入戰鬥。

**獨立測試**：在隔離存檔根目錄建立兩個不同 Profile，啟動選檔流程，確認每個欄位資料隔離且選擇後不自動開始遊戲。

### 使用者故事 1 的測試

- [X] T014 [US1] 在 `tests/test_save_data.py` 測試 1～5 號欄位的建立、保存、載入、空欄位預設、最近完成 a-b、指定欄位刪除與欄位互不影響（依賴 T008）。
- [X] T015 [P] [US1] 在 `tests/test_menu_flow.py` 建立滑鼠／選檔→個人主選單→開始遊戲的流程邊界測試，確認選檔後不會自動進入戰鬥，刪除後仍停留選檔畫面且不建立 RunState（依賴 T009、T011）。
- [X] T016 [US1] 在 `tests/test_hud_progression.py` 與 `tests/test_save_recovery_ui.py` 建立五欄位、金幣、重生次數、A、最近完成 a-b、刪除二次確認與三個主選單功能的可見狀態測試（依賴 T015）。

### 使用者故事 1 的實作

- [X] T017 [US1] 在 `air_defense/main.py` 注入 `SaveStore`，新增啟動時的 `SAVE_SELECT` 狀態、1～5 號欄位選擇與滑鼠點擊直接路由（依賴 T008、T009）。
- [X] T018 [US1] 在 `air_defense/main.py` 實作載入 Profile 後進入 `MAIN_MENU`，明確提供開始遊戲、升級商店與重生三個主要入口，不在選檔後呼叫戰鬥開始。
- [X] T019 [US1] 在 `air_defense/hud.py` 建立五欄位選檔畫面、滑鼠可點擊欄位、非空欄位刪除按鈕、二次確認／取消、空白欄位停用提示、Profile 摘要與三個主選單按鈕，所有使用者文字使用繁體中文。
- [X] T020 [US1] 在 `air_defense/state.py` 與 `air_defense/main.py` 將目前選取存檔欄位綁定至 `SessionProgress`，並由 `GameSession` 關聯每次建立的 RunState，確保切換主選單與開始小關時不遺失 Profile 邊界。
- [X] T021 [US1] 在 `air_defense/hud.py` 與 `air_defense/main.py` 接入返回／離開操作，確保返回主選單只清除暫時戰鬥狀態，不清除已載入的永久 Profile。
- [X] T022 [US1] 在 `tests/test_game_lifecycle.py` 更新既有啟動與返回測試，驗證選檔、主選單、清除世界與既有空戰初始化可以共同運作，並執行語法檢查與相關自動化測試（依賴 T017～T021）。

**關卡檢查**：可獨立展示五存檔啟動流程；選擇存檔不會直接開始遊戲，且兩個 Profile 的金幣與升級完全隔離。

---

## 階段 4：使用者故事 2——可預期且可擴充的 a-b 戰役（P1）

**目標**：移除固定 18 關與固定 4 台飛機，依 A 與 a-b 公式產生完整、固定方向的飛機排列，並在同次程式執行內暫存正常完成後的下一關。

**獨立測試**：對 A=2、3、4、5、19 產生完整關卡，驗證所有 b、飛機類型、魔王條件、位置方向與死亡／重載／重生後的 1-1 重設。

### 使用者故事 2 的測試

- [X] T023 [P] [US2] 在 `tests/test_level_progression.py` 測試 `LevelKey`、`LevelPlan`、a-b 格式、a／b 範圍、A=2/3/4/5 與 A=19 的完整排列。
- [X] T024 [US2] 在 `tests/test_game_lifecycle.py` 測試中間小關完成後只在記憶體前進、死亡／重載／重生後回到 1-1，以及完成目前 A 最終小關後設定重生資格並將下一次手動開始設為 1-1（依賴 T023）。

### 使用者故事 2 的實作

- [X] T025 [US2] 在 `air_defense/progression.py` 實作 `LevelKey`、`LevelPlan`、A 驗證、a-b 排序、普通／特別／魔王數量公式與目前 A 最終小關判定（依賴 T006、T023）。
- [X] T026 [US2] 在 `air_defense/progression.py` 實作右至左普通轉特別、左至右特別轉魔王的確定性飛機編隊，並將 `特` 映射至既有 `MANPOWER_SUPPORT` 行為。
- [X] T027 [US2] 在 `air_defense/rules.py` 讓 `WaveDirector` 的 006 `a-b` 路徑使用動態 `LevelPlan`，移除 Profile 流程的固定 18 編隊、固定 4 台限制與波次範圍拒絕；005 整數波次僅保留明確隔離的相容適配器。
- [X] T028 [US2] 在 `air_defense/state.py` 將 `WaveProgress`／`WavePlan` 的 006 核心流程接到 `SessionProgress` 與 a-b RunState，加入中間小關下一關指標、最終小關判定與最終關／死亡／重載／重生的 1-1 重設，並遵守憲章定義的主迴圈順序。
- [X] T029 [US2] 在 `air_defense/main.py` 將開始遊戲與完成流程改為一次只執行一個 a-b，完成後清除戰鬥世界、保存邊界資料並返回 Profile 主選單。
- [X] T030 [US2] 在 `air_defense/entities.py` 與 `air_defense/rules.py` 保留下降／混合戰鬥生命週期，讓確定性編隊的飛機類型、Boss 與地面遭遇仍使用既有行為。
- [X] T031 [US2] 在 `air_defense/hud.py` 顯示目前 a-b、A、普通／特別／魔王資訊與暫存下一關提示，移除 006 Profile 流程的固定 18 關文字。
- [X] T032 [US2] 在新增 006 關卡與生命週期測試中加入固定 18、wave 19、固定編隊與階段限制的回歸覆蓋，並執行語法檢查與相關自動化測試（依賴 T025～T031）。

**關卡檢查**：純規則可產生大於 18 的 A；`a<A` 永不出現魔王；同次執行正常完成會前進，但重新載入或死亡必回 1-1。

---

## 階段 5：使用者故事 3——賺取、使用並保留永久進度（P1）

**目標**：完成小關只獎勵一次，商店可購買永久 HP、鎧甲、鎖定、白框、輔助瞄準、冷卻與新武器，且永久資料跨所有戰鬥邊界保存。

**獨立測試**：完成小關、重複送出完成事件、購買升級、死亡、完成最終小關並重新載入，確認永久與暫時資料分界正確。

### 使用者故事 3 的測試

- [X] T033 [P] [US3] 在 `tests/test_economy.py` 測試小關獎勵、魔王加成、重生倍率、升級價格、每次重生上限 +1、硬上限與金幣不足／達上限拒絕。
- [X] T034 [P] [US3] 在 `tests/test_profile_lifecycle.py` 測試最大 HP、鎧甲減傷、鎖定時間、白框、輔助瞄準與冷卻升級跨死亡、完成、勝利與重新載入保留。
- [X] T035 [US3] 在 `tests/test_game_lifecycle.py` 與 `tests/test_profile_lifecycle.py` 測試同一嘗試識別碼（`attempt_id`）的重複完成回呼（包含 RunState 清除後）與同一操作識別碼（`operation_id`）的重複購買回呼各只結算一次，並確認 HP、敵人、城市、彈藥、砲塔與戰鬥狀態重置（依賴 T012、T033）。

### 使用者故事 3 的實作

- [X] T036 [US3] 在 `air_defense/progression.py` 實作完整 `UpgradeCatalogEntry`、效果公式、價格公式、基礎上限、每次重生上限 +1、六台硬上限與陸地自動防禦容量價格（依賴 T006、T033）。
- [X] T037 [US3] 在 `air_defense/progression.py` 實作小關獎勵公式與 `purchase_upgrade()`，成功才回傳扣款後的新 Profile，失敗不得部分修改。
- [X] T038 [US3] 在 `air_defense/state.py` 實作 `complete_sublevel_once()`，依嘗試識別碼（`attempt_id`）發放一次金幣、寫入最近完成 a-b、更新記憶體下一關（最終小關改為 1-1）、設定最終關重生資格並清除 RunState（依賴 T012、T037）。
- [X] T039 [US3] 在 `air_defense/entities.py`、`air_defense/state.py`、`air_defense/rules.py` 與 `tests/test_progression.py` 接入並驗證有效最大 HP、鎧甲減傷、5 秒延遲／每秒 2 HP／每次週期上限／每小關總額度 20% 的回血規則。
- [X] T040 [US3] 在 `air_defense/main.py` 將完成、死亡、返回主選單的保存時機接入 `SaveStore`，確保完成獎勵與最近完成 a-b 先結算一次再清除暫時世界。
- [X] T041 [US3] 在 `air_defense/main.py` 實作升級商店選項、購買操作 ID、購買驗證、成功保存與失敗訊息，不讓控制器自行散落價格或效果常數。
- [X] T042 [US3] 在 `air_defense/hud.py` 實作商店畫面，顯示金幣、目前等級、購買上限、價格、最近完成 a-b 與繁體中文結果訊息；下一級效果由升級規則與遊戲行為提供，不在按鈕旁重複顯示。
- [X] T043 [US3] 在 `air_defense/hud.py` 與 `air_defense/rules.py` 將 HUD HP 最大值、鎧甲減傷、鎖定、白框、冷卻與輔助瞄準狀態改為讀取有效 Profile 值，不再讀取固定玩家常數，並執行語法檢查與相關自動化測試。

**關卡檢查**：完成一個小關、購買一項升級並重開同一存檔後，永久資料保留；重複回呼不會重複加錢。

---

## 階段 6：使用者故事 4——明確選擇重生（P1）

**目標**：死亡或目前 A 最終小關完成後才開放重生；成功重生清空金幣、增加 A 與升級上限，並回到主選單等待玩家自行開始。

**獨立測試**：分別以死亡與最終小關取得資格，測試費用、金幣歸零、A 增加、上限增加、資格保存與重複按鍵防護。

### 使用者故事 4 的測試

- [X] T044 [P] [US4] 在 `tests/test_rebirth.py` 測試 `1000*(目前重生次數+1)` 費用、金幣歸零、重生次數加一、A 推導、每次重生上限 +1 與六台硬上限。
- [X] T045 [US4] 在 `tests/test_profile_lifecycle.py` 測試戰鬥中拒絕重生、死亡／最終關設定資格、成功後回 1-1 與相同回呼不重複扣款（依賴 T044）。

### 使用者故事 4 的實作

- [X] T046 [US4] 在 `air_defense/progression.py` 實作純函式 `calculate_rebirth_cost()` 與 `apply_rebirth()`，以資格、金幣與目前 n 驗證後原子產生新 Profile（依賴 T036、T044）。
- [X] T047 [US4] 在 `air_defense/state.py` 實作 `rebirth_available` 的死亡／最終關來源、戰鬥中防護檢查、成功清除資格與記憶體下一關回 1-1（依賴 T046）。
- [X] T048 [US4] 在 `air_defense/main.py` 接入主選單重生確認、一次性保存、清除暫時狀態與返回同一 Profile 主選單，不得自動呼叫 `start_game()`。
- [X] T049 [US4] 在 `air_defense/hud.py` 顯示重生資格、費用、目前金幣、重生後 A 與按鈕禁用原因，所有結果訊息使用繁體中文。
- [X] T050 [US4] 在 `tests/test_save_data.py` 與 `tests/test_profile_lifecycle.py` 驗證重生後重新載入仍保留新 Profile、資格為假、A 正確、最近完成紀錄保留且永久升級未被清除，並執行語法檢查與相關自動化測試。

**關卡檢查**：玩家只能在死亡或目前 A 最終小關後從主選單重生；成功後停留主選單，不會直接開始新局。

---

## 階段 7：使用者故事 5——所有已解鎖武器與新武器（P2）

**目標**：移除戰鬥階段武器限制，加入 RPG、多目標防空炮與有限固定砲塔，保留合法目標、射程、冷卻與彈藥檢查。

**獨立測試**：在三個戰鬥階段切換 1～5 武器，測試合法／非法目標、零彈藥、冷卻、RPG 去重、多目標鎖定與砲塔限制。

### 使用者故事 5 的測試

- [X] T051 [P] [US5] 在 `tests/test_weapon_system.py` 測試所有已解鎖武器可跨 `AIRSTRIKE`、`HYBRID_COMBAT`、`GROUND_COMBAT` 切換，以及目標／距離／冷卻／彈藥判定。
- [X] T052 [P] [US5] 在 `tests/test_new_weapons.py` 測試 RPG 只命中地面敵人、爆炸半徑與唯一命中、多目標鎖定數量／HUD 資料、砲塔落地小兵目標規則、固定位置自動建立、每小關彈藥／冷卻／傷害與六台上限。
- [X] T053 [P] [US5] 在 `tests/test_input_contract.py` 測試 E/G 在選單、三個戰鬥階段與結果狀態均不改變任何資料或產生任何效果。
- [X] T054 [US5] 在 `tests/test_game_lifecycle.py` 測試武器切換不重置冷卻／鎖定，並確認下降中的小兵與既有混合戰鬥行為可被正確處理（依賴 T051～T053）。

### 使用者故事 5 的實作

- [X] T055 [US5] 在 `air_defense/state.py` 與 `air_defense/entities.py` 擴充 `WeaponKind`、武器庫存、每小關彈藥、武器冷卻與目前選取槽位，建立 1～5 對應規則。
- [X] T056 [US5] 在 `air_defense/rules.py` 移除依戰鬥階段拒絕武器的邏輯，保留單目標防空炮鎖定追蹤器，並集中實作所有武器的合法目標／距離／冷卻／彈藥檢查。
- [X] T057 [US5] 在 `air_defense/main.py` 移除 E 互動、G 丟棄、拾取與單持有武器流程，改為所有已解鎖槽位直接切換且不改變其他武器冷卻。
- [X] T058 [US5] 在 `air_defense/entities.py` 與 `air_defense/rules.py` 實作 RPG 地面敵人爆炸中心、半徑 6、傷害 35、冷卻 2.5 秒、每小關 3 發與唯一地面敵人 ID 命中快照，明確排除飛機。
- [X] T059 [US5] 在 `air_defense/entities.py` 與 `air_defense/rules.py` 實作 `MultiLockOnTracker` 與多目標防空炮，解鎖後初始 2 個目標、目標數量升級等級從 0 開始且第一次價格為 500、每級加 1、硬上限 6，並建立每個目標的鎖定狀態。
- [X] T060 [US5] 在 `air_defense/entities.py` 與 `air_defense/rules.py` 實作陸地自動防禦砲塔，每台單一目標、只選已落地非魔王小兵，套用確定性距離／穩定 ID 選擇，並使用集中設定的每小關 20 發、1.5 秒冷卻與每次命中傷害 20。
- [X] T061 [US5] 在 `air_defense/scene.py` 建立六個固定砲塔位置、依 RunState 容量自動建立砲塔實體、RPG 爆炸效果與多目標鎖定投影，確保每小關最多建立六台砲塔並可完整清理。
- [X] T062 [US5] 在 `air_defense/main.py` 接入 RPG、多目標防空炮、砲塔更新／射擊／目標釋放與每小關臨時彈藥重建，不讓非法射擊消耗錯誤狀態。
- [X] T063 [US5] 在 `air_defense/hud.py` 擴充 1～5 武器槽位、彈藥、冷卻、多目標鎖定列表、砲塔數量與鎖定目標顯示，刪除 E/G 及舊階段武器提示。
- [X] T064 [US5] 在 `air_defense/rules.py`、`air_defense/scene.py` 與 `air_defense/main.py` 讓輔助瞄準只在 Profile 解鎖後生效，未購買時保留原本手動瞄準與鎖定。
- [X] T065 [US5] 在 `tests/test_rules.py`、`tests/test_airstrike_guidance.py`、`tests/test_game_lifecycle.py` 與新增 006 測試更新舊階段限制、E/G、單武器拾取與瞄準輔助測試，保留既有導引飛彈、下降與地面 AI 回歸覆蓋，並執行語法檢查與相關自動化測試。

**關卡檢查**：三個戰鬥階段都能切換已解鎖武器；非法目標不受傷；RPG 不重複命中；多鎖定與砲塔不超過規格上限。

---

## 階段 8：使用者故事 6——安全處理存檔邊界（P2）

**目標**：空白、有效、格式錯誤與未知版本的五個存檔都能安全載入，損壞資料保留且不影響其他欄位。

**獨立測試**：對五個隔離欄位分別製造空檔、有效 JSON、截斷 JSON、錯誤型別與未支援結構版本，驗證結果與警告。

### 使用者故事 6 的測試

- [X] T066 [P] [US6] 在 `tests/test_save_recovery.py` 測試截斷 JSON、錯誤欄位型別、未知結構版本、缺少欄位與負值資料的安全恢復及原檔保留。
- [X] T067 [P] [US6] 在 `tests/test_save_recovery_ui.py` 測試損壞存檔警告、空白 Profile 顯示、刪除二次確認與載入／刪除 1 號存檔欄位不影響 2～5 號存檔欄位。

### 使用者故事 6 的實作

- [X] T068 [US6] 在 `air_defense/save_data.py` 完成嚴格結構版本驗證、未知版本拒絕、最近完成 a-b 歷史摘要（`a>=1`、`1<=b<=2a+1`）欄位驗證、損壞原檔保留、可診斷的 `SaveLoadResult` 與指定欄位 `SaveDeleteResult`；載入不得刪除損壞原檔，刪除則必須由流程層確認後執行。
- [X] T069 [US6] 在 `air_defense/save_data.py` 補強原子寫入失敗、暫存檔清理與重新載入一致性，確保單欄位寫入不會改動其他欄位。
- [X] T070 [US6] 在 `air_defense/main.py` 與 `air_defense/hud.py` 顯示繁體中文恢復警告、無法讀取原因、刪除結果與可繼續使用的安全預設 Profile。
- [X] T071 [US6] 在 `tests/test_save_data.py`、`tests/test_save_recovery.py` 與 `tests/test_save_recovery_ui.py` 驗證成功購買、死亡、完成、重生與返回主選單都使用原子保存邊界，並執行語法檢查與相關自動化測試（依賴 T068～T070）。

**關卡檢查**：任一損壞欄位不會讓遊戲崩潰或改寫原始資料，也不會影響其他四個欄位。

---

## 階段 9：收尾與跨故事驗證

**目的**：清理舊固定邏輯、執行完整回歸、完成 quickstart 與手動交付證據。

- [X] T072 [P] 在 `air_defense/` 全域搜尋並移除 006 Profile 流程對固定 18、固定 4、舊戰鬥階段武器限制、E/G 操作與散落進度常數的未使用引用；005 整數波次相容適配器已以 `LEGACY_COMPATIBILITY_*` 明確隔離並記錄限制。
- [X] T073 在 `air_defense/` 檢查並清理未使用匯入、除錯輸出、過時實體映射、重複保存與重複結算路徑。
- [X] T074 [P] 在 `tests/` 補齊跨故事回歸案例：五存檔、A=2/3/4/5/19、永久資料邊界、死亡／最終關／重生、武器與 E/G。
- [X] T075 執行 `python -m compileall -q air_defense tests`，修正所有語法或匯入錯誤並在 `tests/` 保留可重現的測試入口。
- [X] T076 執行 `python -m unittest discover -s tests -p "test_*.py" -v`，針對 `tests/` 確認完整純邏輯與整合測試通過，並將包含滑鼠選檔、刪除隔離、二次確認、RPG 最後一批敵人結算、商店項目文字格式與遭遇快取同步的 159 個測試結果記錄於 quickstart 交付說明。
- [X] T077 執行 `python -m air_defense.main`，針對入口 `air_defense/main.py` 進行 Ursina 啟動檢查，並依使用者人工驗收確認五存檔、滑鼠選檔、刪除確認、Profile 主選單、1-1、死亡、完成、重生與返回流程無屬性／匯入錯誤。
- [ ] T078 依 `specs/006-save-progression-rebirth/quickstart.md` 完成手動流程、損壞存檔流程與 A=5 效能觀察，確認平均 FPS 至少 60 且沒有超過 5 秒的連續低於 45 FPS 區段；無圖形環境時將結果明確標記為未測量。
- [X] T079 在 `specs/006-save-progression-rebirth/quickstart.md` 更新實際驗證日期、159 個測試、滑鼠選檔／刪除驗證項目、RPG 最後一批敵人結算、命令結果、已知限制與不宣稱未測量結果的證據摘要。
- [X] T080 在 `air_defense/`、`tests/` 與 `specs/006-save-progression-rebirth/` 做最終差異檢查，確認程式、測試與所有 SDD 文件符合憲章第 VI 原則及 006 規格；本次已同步滑鼠選檔、刪除確認、欄位隔離與 RPG 結算邊界文件。
- [X] T081 在 `air_defense/main.py` 與 `tests/test_game_lifecycle.py` 修正 RPG 爆炸使用錯誤遭遇參照而只顯示特效、不結算敵人的問題；以 RunState 聚合遭遇完成 RPG 最後一批敵人回歸測試，並重新執行語法檢查、完整測試與差異檢查。
- [X] T082 在 `air_defense/hud.py` 與 `tests/test_hud_progression.py` 將商店項目按鈕統一為「編號名稱(目前等級/上限)價格元」格式並移除重複白色明細文字，加入 `1鎧甲(1/4)220元` 格式及目前目錄實際 `2鎧甲(1/4)220元` 編號的回歸測試，並同步 006 UI 文件與驗證紀錄。
- [X] T083 記錄使用者人工驗收結果：功能流程與本次商店／RPG／存檔相關修正均回報無問題；未將未提供數值的 FPS 門檻結果標記為已通過。
- [X] T084 在 `air_defense/main.py` 與 `tests/test_game_lifecycle.py` 統一以 `RunState.ground_encounter` 修復地面更新、武器與砲塔的遭遇快取不同步邊界，並加入控制器快取修復回歸測試。

## 相依性與執行順序

### 階段相依性

- **階段 1**：無前置相依，可先建立模組與測試骨架。
- **階段 2**：依賴階段 1，阻塞所有使用者故事。
- **US1**：依賴 T008～T013，建立五存檔與 Profile 主選單最小可行版本。
- **US2**：依賴 T006、T009～T013；可在 US1 的 UI 工作之外先完成純關卡規則，但整合啟動依賴 US1 的 Profile 流程。
- **US3**：依賴 US1 的保存邊界與 US2 的小關完成事件；完成後提供可持久化的金幣與商店。
- **US4**：依賴 US3 的 Profile 變更與升級上限；重生必須在其後整合。
- **US5**：依賴階段 2；武器解鎖與彈藥顯示整合依賴 US3，戰鬥目標純邏輯可先平行撰寫。
- **US6**：依賴 US1 的存檔流程與階段 2；可與 US4／US5 的部分純邏輯平行，最後與主流程整合。
- **階段 9**：依賴所有預定使用者故事完成。

### 使用者故事完成順序

```text
階段 1 → 階段 2
              ├─ US1 ─┐
              ├─ US2 ─┴─ US3 → US4
              ├─ US5（純規則可平行，Profile／HUD 整合依 US3）
              └─ US6（存檔純測試可平行，主流程依 US1）
                         ↓
                      階段 9
```

### 同一故事內的規則

- 測試任務先建立，並在實作任務前確認會因新行為而失敗。
- 資料模型與純函式先於控制器、場景與 HUD 整合。
- 同一檔案的任務不得標示 `[P]`；只有不同檔案且不依賴未完成任務時才可平行。
- 每個關卡檢查都要先通過，再進入下一個會擴大影響範圍的故事。
- 每個實作任務與每個關卡檢查完成時，都必須執行受影響範圍的 Python 語法檢查、相關自動化測試與至少一個可重現的手動流程；未具備圖形環境時必須記錄未測量，不得宣稱通過。

## 平行執行範例

### 使用者故事 1

```text
工作 A：T014，測試 tests/test_save_data.py 的五欄位隔離。
工作 B：T015，測試 tests/test_menu_flow.py 的選檔與不自動開始。
工作 C：T016，測試 tests/test_hud_progression.py 的五欄位與三個主選單功能。
```

### 使用者故事 2

```text
工作 A：T023，測試 tests/test_level_progression.py 的 A 與 a-b 公式。
工作 B：T024，測試 tests/test_game_lifecycle.py 的記憶體前進與 1-1 重設。
```

### 使用者故事 3

```text
工作 A：T033，測試 tests/test_economy.py 的獎勵、價格與上限。
工作 B：T034，測試 tests/test_profile_lifecycle.py 的永久資料邊界。
工作 C：T035，測試 tests/test_game_lifecycle.py 的重複完成回呼。
```

### 使用者故事 5

```text
工作 A：T051，測試 tests/test_weapon_system.py 的跨階段切換與合法性。
工作 B：T052，測試 tests/test_new_weapons.py 的 RPG、多鎖定與砲塔。
工作 C：T053，測試 tests/test_input_contract.py 的 E/G 無效果。
```

## 實作策略

### 最小可行版本優先

1. 完成階段 1 與階段 2。
2. 完成 US1，交付五存檔與 Profile 主選單。
3. 先以無視窗測試驗證五個欄位隔離，再做 Ursina 啟動檢查。
4. US1 通過後才加入動態戰役與經濟，避免在尚未穩定的存檔邊界上堆疊戰鬥功能。

### 增量交付

1. US2 取代固定 18 關並保留既有下降／混合戰鬥。
2. US3 加入一次性金幣、永久升級與商店。
3. US4 加入可保存資格的明確重生。
4. US5 加入新武器、彈藥、固定砲塔與多鎖定。
5. US6 強化損壞存檔恢復，最後執行跨故事回歸與手動驗收。

### 提交節奏

- 每個關卡檢查後提交一個可描述的邏輯群組，提交前至少執行語法檢查、相關測試與一個可重現的手動流程。
- 不把未完成的場景／HUD 工作混入尚未通過的純規則提交。
- 最終提交必須附上 `spec.md`、`plan.md`、`tasks.md`、quickstart 驗證結果與已知限制。

## 任務完成定義

- 所有已選任務均以 `- [x]` 標記前，必須有相應測試或手動證據；每個實作任務至少附語法檢查與一個可重現的手動流程記錄。
- 不得宣稱未測量的圖形效能或手動結果已通過。
- 所有 SDD 文件、任務描述與驗證記錄使用繁體中文；必要的程式碼識別字、路徑與命令保留原格式。
