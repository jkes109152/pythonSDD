# 實作計畫：持久化存檔、進度與重生戰役

**分支**：`006-save-progression-rebirth` | **日期**：2026-08-27 | **規格**：[spec.md](./spec.md)

**輸入**：來自 `specs/006-save-progression-rebirth/spec.md` 的功能規格

## 摘要

將 006 Profile 流程目前依賴的固定 18 關、固定飛機編隊與單局記憶體狀態，改為由重生次數
推導 A 的可擴充 `a-b` 小關系統。每次遊玩只執行一個小關；正常完成後只在目前程式執行
期間前進，死亡、重新載入與重生後從 1-1 開始。005 的整數波次 API 暫時保留為明確命名的
相容適配器，不能被 006 Profile 流程使用，也不能限制新的 A。

新增五個獨立的本機 JSON 存檔、可用滑鼠操作的存檔選擇畫面、具二次確認的單欄位刪除、存檔主選單、升級商店、金幣與明確重生操作。永久 Profile
與單次小關 RunState 分開，所有獎勵與重生以一次性領域操作處理，避免重複回呼洗錢
或重複扣款。新增 RPG、獨立的多目標防空炮與有限固定位置的陸地自動防禦系統；所有已
解鎖武器在空戰、混合戰鬥與地面戰鬥均可切換，但仍受目標、距離、冷卻及彈藥判定約束。

既有的下降、混合戰鬥、飛機撞擊、地面遭遇、城市傷害與資產替代行為保留，除非
與本功能的持久化、a-b 關卡、武器或邊界規則衝突。

## 技術背景

**語言／版本**：Python 3.12 以上；憲章最低要求為 Python 3.11，現有遊戲依賴要求 3.12。

**主要依賴**：既有 `ursina==8.3.0`；Python 標準函式庫的 `dataclasses`、`enum`、`json`、
`pathlib`、`tempfile`、`os` 與 `unittest`；不新增第三方套件。

**儲存**：使用者 Windows 應用程式資料區的五個 JSON 存檔檔案；測試注入暫存根目錄。

**測試**：`python -m compileall -q air_defense tests`、
`python -m unittest discover -s tests -p "test_*.py" -v`、無視窗純邏輯測試、Ursina 啟動
檢查、手動遊戲流程與 FPS 記錄。

**目標平台**：Windows 桌面、離線單人、鍵盤與滑鼠；沿用目前 1280×720 視窗與第一人稱
鏡頭輸入。

**專案類型**：3D 桌面遊戲應用程式。

**效能目標**：在 1280×720 的 A=5 整合場景中，暖機 5 秒後連續觀察 30 秒、每秒取樣，
平均 FPS 必須至少 60，且不得有超過 5 秒的連續低於 45 FPS 區段；多目標防空炮、RPG
與最多六台自動防禦砲塔必須在相同門檻下完成測試。A 大於 18 只要求純邏輯關卡生成成功，
不得以隱藏上限規避規則需求。測試記錄必須包含作業系統、Python 版本、解析度與硬體摘要；
沒有圖形環境時標記為未測量，不宣稱通過。

**限制**：不保存戰鬥中狀態或未完成的 a-b 進度；最近完成的 a-b 僅供顯示／診斷；所有永久資料不可放入 `config.py`；純規則不可
匯入 Ursina；E/G 無效果；RPG 只結算爆炸範圍內的地面敵人，且每名地面敵人每次爆炸只結算一次；自動防禦最多六個固定位置；
重生不得在戰鬥中執行，也不得自動開始下一局。

**規模／範圍**：維持 `air_defense` 的淺層分層，新增 `progression.py` 與 `save_data.py`，
擴充既有 `state.py`、`rules.py`、`entities.py`、`main.py`、`scene.py`、`hud.py` 與測試；
不改造 `day1`／`day2` 其他教學專案，不引入網路、雲端同步或資料庫。

## 憲章檢查

*關卡：階段 0 研究前必須通過；階段 1 設計後重新檢查。*

### 階段 0 前：通過

| 原則／關卡 | 證據 |
|---|---|
| I. 可讀性優先，循序抽象 | 只新增兩個有明確責任的淺層模組；進度規則與存檔邊界不拆成不必要的服務層。 |
| II. 遊戲物件封裝狀態與行為 | `Player`、武器、飛機、地面敵人與砲塔管理自身狀態；跨物件的獎勵、重生、關卡與目標規則集中於純規則模組。 |
| III. 小步驟開發，每項行為可驗證 | 先建立關卡、經濟、存檔、冪等與目標判定測試，再接入狀態模組、場景、HUD，最後做手動流程。 |
| IV. 遊戲迴圈順序與狀態轉移明確 | 以 `SAVE_SELECT`、`MAIN_MENU`、`SHOP`、三個戰鬥階段及結果轉移定義邊界；每次完成、死亡與重生都有唯一結算路徑。 |
| V. 範圍適當與依賴簡單 | 沿用 `spec.md` 所記錄、由 004／005 合併基線繼承的 Ursina 執行環境例外；不增加依賴、服務或資產，也不擴大例外範圍。 |
| VI. SDD 文件使用繁體中文 | 本功能的 plan、research、data-model、contract、quickstart 與後續 tasks 全部以繁體中文撰寫；必要的程式碼識別字與命令保留原格式。 |
| 分支與交付治理 | 使用 `006-save-progression-rebirth`，與 `specs/` 下目錄一致；保持既有不相關工作區變更，不在本功能中清理。 |

### 階段 1 後：預計通過

設計不新增憲章例外；資料模型仍維持 Profile／RunState 分離，純邏輯仍不依賴 Ursina，
所有新增 SDD 文件仍以繁體中文完成。006 沿用 `spec.md` 的既有 Ursina 執行環境治理備註，
不擴大至其他專案；若未來要改變引擎，必須另行提出憲章例外與遷移說明。

## 設計總覽

### 1. 動態 a-b 關卡

`progression.py` 提供不可變 `LevelKey` 與 `LevelPlan`。最大飛機數量由
`A = 2 + rebirth_count` 推導，不設 4 或 18 的生成上限。

- `a < A`：b 為 1～`a+1`；普通數量 `a-(b-1)`、特別數量 `b-1`、魔王數量 0。
- `a == A`：b 為 1～`2a+1`；前 `A+1` 個 b 完成普通到特別，後續每個 b 增加一台魔王，
  且 `a==A、b==2A+1` 才是目前 A 的最終小關。
- 普通轉特別由右至左，特別轉魔王由左至右，直接產生符合範例的確定性飛機編隊。
- `特` 預設使用既有 `MANPOWER_SUPPORT` 行為，`魔` 使用 `ARMORED_BOSS`。
- 戰役順序為 a 由 1 到 A、每個 a 的 b 由 1 到上限；正常完成中間小關只更新記憶體中的下一關，
  完成最終小關則把下一次手動開始重設為 1-1。

### 2. Profile、存檔與單次小關

`save_data.py` 管理五個 `slot-N.json`，以結構版本 1 驗證下列資料：

```text
coins
rebirth_count
max_aircraft_count
upgrade_levels
upgrade_caps
unlocked_weapons
rebirth_available
last_completed_a_b
```

儲存根目錄預設位於使用者 AppData，測試以建構參數注入暫存目錄。寫入採同目錄暫存檔、
flush／fsync 與原子替換；損壞或未知版本的原檔保留並回傳繁體中文警告。

`state.py` 新增或調整：

- `SAVE_SELECT`：啟動後顯示五個欄位，支援滑鼠點擊欄位載入；非空欄位提供「刪除→確認／取消」操作，確認後才刪除精確對應檔案，選擇後才載入 Profile。
- `MAIN_MENU`：所選存檔主選單，主要功能只有開始遊戲、升級商店與重生。
- `SHOP`：顯示價格、等級、上限與購買結果。
- `GameSession` 持有非持久化的 `SessionProgress`，保存所選存檔與正常完成後的下一個 a-b；
  `RunState` 保存單次小關的 HP、城市、敵人紀錄表、彈藥、砲塔紀錄表、鎖定、冷卻、回血額度與目前 a-b。
  `RunState` 是該次戰鬥邊界的唯一權威來源。
- `entities.py` 的玩家、敵人、武器與砲塔物件封裝場景執行所需的暫時狀態與行為，透過明確同步
  函式讀寫 RunState，不另建一份可獨立變更的戰鬥紀錄表。
- `attempt_id`、`reward_settled` 與商店 `operation_id`：分別保護小關、結果與購買結算；
  `GameSession` 在清除 RunState 後暫留最近一次獎勵結算，重複完成回呼只能回傳原結果，
  新小關則拒絕舊嘗試識別碼。

成功完成中間小關後保存金幣、永久資料與最近完成的 a-b 紀錄、清除戰鬥狀態，並將下一個
a-b 保留在記憶體；完成目前 A 的最終小關時保存重生資格並將記憶體下一局設為 1-1；死亡
不發獎勵、保存重生資格、清除戰鬥狀態並將下一局設為 1-1。
重新載入存檔同樣從 1-1，最近完成紀錄只供顯示／診斷，不作為續關點。刪除流程只能由
`SAVE_SELECT` 發起；`SaveStore.delete_slot()` 只處理指定欄位，HUD 在第一次點擊後等待
第二次確認，取消或空白欄位不會改動 JSON。

### 3. 金幣、升級與重生

所有經濟設定集中在 `progression.py` 的一個設定資料結構與升級目錄：

```text
raw_reward = 100 + 25*a + 10*(b-1) + 150*boss_count
awarded_coins = floor(raw_reward * (1 + 0.5*rebirth_count))
rebirth_cost = 1000 * (rebirth_count + 1)
```

陸地自動防禦解鎖價格為 600；解鎖後初始容量為 1，容量升級價格為
`450*(level+1)`，每級增加 1 台，最多 6 台。多目標防空炮解鎖後初始鎖定 2 個目標，
每次升級增加 1 個，最多 6 個；目標數量升級等級從 0 開始，第一次升級價格為 500，後續依
`500*(level+1)` 計算；一次性解鎖與容量／鎖定升級分開結算。
陸地自動防禦容量等級從 0 開始，解鎖時容量為 1，第一次容量升級價格為 450，後續依
`450*(level+1)` 計算。每台預設每小關 20 發、每次射擊冷卻 1.5 秒、每次命中傷害 20；冷卻仍讀取集中升級目錄，
彈藥不在戰鬥中自動補充。

初始金幣為 0，重生不給起始金幣。重生成功後金幣歸零、重生次數加一、A 與升級上限重算，
並清除 `rebirth_available`。最大 HP、鎧甲、鎖定時間、白框大小與各武器冷卻的基礎上限
分別為 5、3、5、5、5，每次重生各增加 1；多目標鎖定與砲塔容量每次重生增加可購買上限
1，但有效數量都不得超過 6。一次性解鎖不增加等級。重複完成事件、購買事件與重生事件
都由純規則層以穩定 ID 或狀態旗標去重。

永久升級預設：最大 HP 每級 +10、鎧甲每級減傷 1 且最低承受 1、鎖定時間每級 -0.15 秒、
白框大小每級 +10%、各武器冷卻每級 -5% 且最低為基準 50%。重複升級的上限為基礎上限
加上重生成長量；輔助瞄準與新武器為一次性解鎖。

回血由 `RunState` 管理：每個小關建立 `0.2 * effective_max_hp` 的總回血額度；受傷後
等待 5 秒，以每秒 2 HP 回復，每次受傷週期最多使用剩餘額度，再次受傷只重設計時與該週期
上限，不增加小關總額度。新小關開始時 HP 直接恢復至永久有效最大 HP。

### 4. 武器與目標判定

保留 `LockOnTracker` 作為單目標防空炮的基礎；新增 `MultiLockOnTracker`，每個目標有
獨立狀態，解鎖後初始 2 個目標，每次升級增加 1 個，硬上限 6 個。多目標防空炮使用獨立
槽位 5，HUD 顯示所有鎖定。

武器槽位為 1=單目標防空炮、2=狙擊槍、3=手槍、4=RPG、5=多目標防空炮。所有已解鎖手持
武器在三個戰鬥階段均可切換；`can_fire_*` 僅檢查目標、距離、冷卻與彈藥，不檢查戰鬥階段。

RPG 使用地面敵人爆炸中心與半徑 6 的唯一地面敵人 ID 快照，預設傷害 35、冷卻 2.5 秒、每小關 3 發；
飛機不是 RPG 的合法目標，也不得被爆炸範圍波及。爆炸結算完成後必須透過共用的小關清除判定
重新檢查整個 `RunState`；地面遭遇以 `RunState.ground_encounter` 為聚合來源，避免控制器視覺參照
短暫不同步時遺漏最後一批敵人的結算。
陸地自動防禦使用場景固定六個位置；商店解鎖後每個新小關自動建立目前容量的暫時砲塔，
初始一台，每次容量升級增加一台，最多六台，不提供戰鬥中購買或任意放置。每台只鎖定
一名已落地的非魔王小兵，預設每小關 20 發、每次射擊冷卻 1.5 秒、每次命中傷害 20，不能攻擊下降中的敵人或魔王；
小關結束時全部清除。

瞄準輔助只有在 Profile 解鎖後才傳入場景投影流程；未解鎖時沿用目前手動瞄準與鎖定。
E 與 G 從輸入協調、場景拾取／丟棄與 HUD 提示全部移除。

### 5. 場景、HUD 與遊戲迴圈

- `main.py` 只負責流程、輸入與領域／場景協調，不直接決定價格、獎勵或升級效果；商店購買
  以唯一操作 ID 經 `GameSession` 結算。
- `scene.py` 新增六個固定砲塔點、砲塔／爆炸視覺與多目標投影；不建立無上限實體，並依
  RunState 的砲塔紀錄表建立與清理。
- `hud.py` 新增存檔選擇、Profile 主選單、商店、金幣、A、升級、彈藥與多鎖定顯示。
- 完整主迴圈順序為限制幀率 → 事件 → 讀取輸入／選單事件 → 武器與回血計時 → 飛機／導彈 →
  下降與地面 AI → 城市／敵人傷害 → 結算防重機制 → 場景同步 → 更新動畫 → 繪製 → 顯示；
  終止狀態或選單狀態停止戰鬥更新。
- 小關完成、死亡與重生會先執行唯一結算，再清除暫時世界、保存 Profile 並返回主選單；RPG、狙擊槍、
  手槍與砲塔的擊倒回呼都必須回到同一個小關清除判定。

## 公開與模組介面

### `progression.py`

- `LevelKey(a, b)`：格式化、驗證與排序。
- `LevelPlan`：提供飛機編隊、普通／特別／魔王數量、`is_boss_stage` 與最終小關判定。
- `ProgressionConfig`：集中 A、獎勵、重生、升級、武器與回血的規則數值；六個固定砲塔位置
  由 `config.py` 的場景常數管理，不混入 Profile。
- `build_level_plan(level_key, maximum_aircraft_count)`：純函式生成確定性飛機編隊。
- `next_level(level_key, maximum_aircraft_count)`：純函式產生正常完成中間小關後的下一小關；
  若輸入為目前 A 的最終小關，回傳 1-1，避免產生超出範圍的關卡。
- `calculate_reward(level_plan, rebirth_count)`：純函式計算一次成功獎勵。
- `purchase_upgrade(profile, upgrade_id)`：驗證金幣、前置條件與上限後回傳新 Profile；
  `GameSession.purchase_upgrade_once(operation_id, upgrade_id)` 負責相同操作 ID 去重。
- `apply_rebirth(profile)`：驗證資格與費用後一次性回傳重生後 Profile。
- `progression.py` 不包含戰鬥目標判定；該責任由 `rules.py` 的
  `is_valid_target(weapon_kind, target, distance, cooldown_remaining, ammo_remaining, max_range)` 與爆炸／砲塔目標選擇函式負責。

### `save_data.py`

- `SaveProfile`：可驗證、可序列化的永久資料物件。
- `SaveStore(root=None)`：管理五個欄位的載入、保存、缺檔預設、損壞隔離與警告。
- `load_slot(slot_id) -> SaveLoadResult`：回傳 Profile、欄位狀態與使用者可見警告。
- `save_slot(slot_id, profile) -> SaveResult`：以原子替換保存並回報結果。
- `delete_slot(slot_id) -> SaveDeleteResult`：只刪除指定欄位，回報 `deleted`、`empty` 或 `failed`，不讀寫其他欄位。

### `state.py`

- `GamePhase`：新增 `SAVE_SELECT`、`SHOP`、小關結果／主選單轉移所需的狀態。
- `SessionProgress`：保存目前選定存檔與非持久化的 `next_play_level`；由 `GameSession` 持有，
  是主選單開始遊戲時的唯一下一關來源。
- `GameSession.start_sublevel(profile, level_key)`：由 Profile 與 `SessionProgress` 建立新 RunState，
  HP 為有效最大值。
- `GameSession.complete_sublevel_once(attempt_id)`：只允許一次獎勵、更新最近完成紀錄、
  暫存進度與返回主選單；RunState 清除後仍可對同一嘗試回傳原結算結果。
- `GameSession.fail_sublevel_once(reason)`：只允許一次死亡結果、資格保存與 1-1 重設。
- `GameSession.purchase_upgrade_once(operation_id, upgrade_id)`：只允許相同購買操作 ID
  結算一次，新的操作 ID 才能再次購買。
- `GameSession.apply_rebirth_once(operation_id)`：僅在主選單且資格有效時執行，成功後不自動開始；相同操作 ID 只回傳第一次結果。
- `GameSession.delete_save_slot(slot_id)`：僅在 `SAVE_SELECT` 接受刪除，否則回報 `rejected`；成功後由控制器重新列出五個欄位，不建立 Profile 或 RunState。

### 既有模組調整

- `rules.py`：移除 006 Profile 流程的 18 關編隊與依戰鬥階段限制庫存邏輯，加入目標、RPG、
  多鎖定、砲塔與回血純規則；動態關卡、經濟、升級與重生由 `progression.py` 負責，並保留
  下降與地面遭遇計算。005 整數波次呼叫僅作為標示清楚的相容適配器。
- `entities.py`：新增彈藥、RPG、多目標鎖定、砲塔、爆炸命中集合與回血狀態的場景物件。
- `main.py`：加入五存檔／主選單／商店／重生流程，移除 E/G、拾取／丟棄與階段武器限制。
- `scene.py`：加入固定砲塔點、爆炸、多目標 HUD 所需投影與有界清理。
- `hud.py`：加入可滑鼠點擊的選檔欄位、每欄位刪除按鈕、二次確認／取消、Profile、商店、金幣、A、升級、彈藥、多鎖定與繁體中文提示；商店項目按「編號名稱(目前等級/上限)價格元」單行格式顯示。
- `main.py`：在選檔畫面協調滑鼠欄位、刪除與確認按鈕；保留輸入後端事件的直接 hover 路由，避免按鈕回呼未送達時滑鼠失效。
- `config.py`：保留視窗、飛行、下降與場景常數；不得存放 Profile 或永久升級資料。

## 專案結構

### 本功能文件

```text
specs/006-save-progression-rebirth/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui.md
├── checklists/
│   └── requirements.md
└── tasks.md                 # 由 speckit-tasks 產生，作為實作執行清單
```

### 原始碼與測試

```text
air_defense/
├── __init__.py              # 套件公開匯出
├── config.py                # 視窗、場景與戰鬥預設
├── progression.py           # 新增：關卡、經濟、升級與重生純規則
├── save_data.py             # 新增：五存檔與結構版本驗證
├── state.py                 # Profile／RunState 邊界與流程狀態
├── entities.py              # 玩家、武器、敵人、砲塔與暫時資料
├── rules.py                 # 純戰鬥、下降、命中與轉移規則
├── main.py                  # 輸入與流程協調
├── scene.py                 # Ursina 場景轉接層
└── hud.py                   # 選單與戰鬥 HUD

tests/
├── test_progression.py          # 關卡、回血與純進度規則
├── test_level_progression.py    # a-b 關卡排列與 A 邊界
├── test_economy.py              # 獎勵、價格與升級上限
├── test_rebirth.py              # 重生費用、資格與上限
├── test_save_data.py             # 五欄位、結構版本、原子保存與損壞處理
├── test_save_recovery.py         # 損壞存檔與保存邊界
├── test_save_recovery_ui.py      # 損壞存檔、刪除二次確認與使用者警告
├── test_menu_flow.py             # 選檔、刪除與主選單流程
├── test_hud_progression.py       # Profile、商店與戰鬥資訊顯示
├── test_profile_lifecycle.py     # 永久資料跨生命週期保留
├── test_game_lifecycle.py        # 遊戲狀態、重置與重複事件
├── test_rules.py                 # 既有下降、遭遇與新規則回歸
├── test_weapon_system.py         # 武器切換、彈藥與目標判定
├── test_new_weapons.py           # RPG、多鎖定與砲塔
├── test_input_contract.py        # E/G、滑鼠選檔與輸入契約
├── test_airstrike_guidance.py    # 既有導引與瞄準輔助回歸
└── test_hud_wave.py              # 既有 HUD 回歸
```

**結構決定**：維持現有單一 `air_defense` 套件與淺層模組；`progression.py` 負責純進度規則，
`save_data.py` 負責序列化邊界，`state.py` 負責遊戲流程。除非測試或理解成本確實需要，
不新增儲存庫、服務、資料庫或第二層套件。

## 實作階段

1. **純資料與進度規則**：建立 `SaveProfile`、`SaveStore`、`LevelKey`／`LevelPlan`、升級目錄、
   獎勵、重生、回血與冪等操作；先完成無視窗測試。
2. **狀態與邊界整合**：把 Profile／RunState 接入 `GameSession`，建立選檔、主選單、商店、
   單小關完成／死亡／重生轉移，確保保存時機與重置順序正確。
3. **既有戰鬥遷移**：將 006 Profile 流程的固定 18 關 `WaveDirector` 路徑改為動態 `LevelPlan`，
   保留下降與混合戰鬥，移除戰鬥階段武器限制與 E/G 操作；005 整數波次相容路徑隔離並記錄
   遷移邊界。
4. **新武器與實體**：加入 RPG 唯一命中集合、多目標鎖定、固定砲塔、彈藥與有限回血，
   建立所有目標／距離／冷卻／彈藥檢查。
5. **場景／HUD**：加入固定砲塔點、爆炸及多鎖定視覺、可滑鼠操作的五存檔與刪除確認、商店介面，移除舊 18 關與 E/G 文案。
6. **整合與清理**：更新回歸測試、完成啟動／手動／FPS 驗證，清除未使用匯入、舊固定常數、
   過時引用與重複結算路徑。

## 測試策略

### 純邏輯與狀態測試

- 產生 A=2、3、4、5、19 的完整有效關卡；驗證 a-b 範圍、排列方向、`a<A` 無魔王、`a==A`
  才進入魔王階段，並確認沒有 4／18 隱藏限制。
- 驗證獎勵公式、魔王加成、重複完成回呼、相同購買操作 ID 與重複重生的冪等性。
- 驗證五個存檔獨立、結構版本往返、缺檔、格式錯誤、未知版本、原子替換與原檔保留。
- 驗證選檔畫面滑鼠點擊可載入正確欄位；非空欄位刪除必須二次確認，確認只刪除目標檔案，空白欄位與取消不改變任何欄位。
- 驗證永久升級在死亡、完成、勝利、重生與重新載入後保留；HP、敵人、城市、彈藥、砲塔與 a-b
  未完成進度不持久化，但最近完成的 a-b 紀錄必須保存且不可用於續關。
- 驗證死亡／完成／重生後 1-1、正常完成後記憶體前進、重生費用與升級上限。
- 驗證 5 秒回血延遲、每秒 2 HP、每次受傷週期上限、小關總額度 20% 與再次受傷重設。
- 驗證所有階段均可切換已解鎖武器，非法目標、超距離、冷卻中與無彈藥不造成傷害。
- 驗證 RPG 多目標唯一命中、RunState 遭遇參照短暫不同步時仍能以 RPG 清除最後敵人並只結算一次、
  多目標防空炮鎖定數量，以及砲塔只攻擊已落地非魔王小兵。
- 驗證 E/G 在所有狀態無效果與 HUD 文案不存在。

### 整合與手動驗證

- `python -m compileall -q air_defense tests`。
- `python -m unittest discover -s tests -p "test_*.py" -v`。
- 建立 Ursina 應用程式啟動檢查：顯示五存檔、以滑鼠載入 Profile、進入主選單、開始 1-1、清除世界且無匯入／屬性錯誤。
- 手動完成：選檔 → 1-1 → 1-2 → 2-1 → A=2 最終小關 → 取得重生資格 → 商店 → 死亡 → 重載 → 重生 → 新 A 的 1-1。
- 手動驗證空戰／混合／地面三階段切換 1～5、RPG 爆炸、多目標鎖定、下降中的小兵與六台砲塔上限。
- 使用五個存檔測試保存邊界；故意破壞一個欄位，確認其他四個欄位不受影響。
- A=5 圖形場景暖機 5 秒後觀察 30 秒，每秒記錄 FPS；通過條件為平均 FPS 至少 60，且不得有超過 5 秒的連續低於 45 FPS 區段。記錄作業系統、Python 版本、解析度與硬體摘要；若沒有圖形環境，標記未測量，不以隱藏上限代替。

## 複雜度追蹤

本設計沒有新增憲章例外。`progression.py` 與 `save_data.py` 是需求明確要求且可獨立測試的
兩個責任邊界；固定砲塔位置是為了效能安全而非額外架構層。既有 Ursina 例外依 `spec.md`
與 004／005 合併基線治理備註延續，沒有擴大到新的依賴或其他專案。
