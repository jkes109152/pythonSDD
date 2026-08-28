# 實作計畫：3D 資產與武器瞄準整合

**分支**：`007-3d-assets-weapon-targeting`
**日期**：2026-08-28
**規格**：[spec.md](./spec.md)

**輸入**：來自 `specs/007-3d-assets-weapon-targeting/spec.md` 的功能規格。

## 摘要

本功能把 `遊戲3d/` 的七個本機 STL 來源轉成遊戲可選用的 OBJ，並在轉換階段統一
為 Y 軸向上、+Z 為機頭／人物面向；遊戲執行時飛機依既有飛行方向更新朝向，地面人物
依水平實際移動／下一個路徑目標更新 yaw 並維持 Y 軸向上，不新增個別模型旋轉補正。資產由一份無引擎 manifest 映射到普通、人力
支援、快速、Boss 飛機、一般／Boss 地面人物與目標大樓，缺檔或載入失敗時維持
程序化 fallback，並以每個資產的獨立 mesh／類型色避免模型互相混用或顏色污染；可見
OBJ 依角色倍率放大但不讓可見尺寸改寫基準 box 碰撞包絡；地面人物的中央準心瞄準 box
與其實際可見模型包絡一致，fallback 則與 fallback 外觀一致。場景使用暖色方向光、環境填光、太陽高光與
陰影映射提升輪廓辨識；方向不確定時可用本機校正檢視器取得來源軸。
OBJ
與 STL 都只保留在使用者本機。

本功能是 006 的後續覆寫版本；陸地自動防禦的射程、傷害、冷卻、Boss 下限與彈藥政策
以本計畫及 `spec.md` 的 US5／FR-025～FR-028 為準。006 文件中的舊數值保留為歷史
版本記錄，不在本次實作中繼續沿用。

武器部分修正 RPG 將狙擊槍 180.0 射程誤當預設值的路徑，讓 RPG 準心與手槍共用
同一視覺規格，中心射線與規則都使用手槍的 12.0 包含邊界。多目標防空炮改成
普通白框目前尺寸的 2.0 倍，依所有目前可見且在框內的敵機建立獨立鎖定；不再以
2 或 6 個固定欄位截斷。所有有效目標完成鎖定並重新驗證後，使用既有導引導彈
建立一目標一枚的同時齊射，整次只套用一次冷卻，所有目標 ID 固定且互不轉移。

既有 `aa_whitebox` 升級同時作用於普通與多目標白框，舊的固定目標數升級只作
schema 1 相容讀取，不再出現在商店、HUD 或遊戲行為中。Profile 主選單另提供設定頁，
讓玩家在新版白框介面與舊版圓圈鎖定介面間切換；介面偏好只影響視覺，不分叉武器規則。

## 技術背景

**語言／版本**：Python 3.12 以上；目前驗證環境為 Python 3.13.5，符合憲章最低
Python 3.11 要求與 `requirements-game.txt` 的遊戲執行需求。

**主要依賴**：既有 `ursina==8.3.0`；轉換器與純規則只使用 Python 標準函式庫
（`dataclasses`、`enum`、`pathlib`、`struct`、`math`、`unittest` 等），不新增第三方依賴。

**儲存**：OBJ 產物位於本機 `assets/air_defense/models/` 且被忽略；原始 STL 位於
本機 `遊戲3d/` 且被忽略。既有 Profile JSON schema 維持 1，不保存鎖定集合、準心、
防空介面偏好或飛彈齊射；介面偏好只存在目前程式啟動期間。

**測試**：`python -m compileall -q air_defense tests tools`、
`python -m unittest discover -s tests -p "test_*.py" -v`，並以不建立視窗的純規則／
轉換器測試、mock 的 Scene／HUD 測試與可用圖形環境的手動 smoke 驗證補足。

**目標平台**：Windows 桌面、離線單人、鍵盤／滑鼠、既有 1280×720 Ursina 第一人稱
場景；缺少本機模型或沒有圖形介面時仍需可啟動與執行純規則測試。

**專案類型**：3D 桌面遊戲應用程式，`air_defense` 採純規則／實體與 Ursina scene、
HUD、controller 的淺層分工。

**引擎例外與邊界**：憲章預設 Pygame，但本功能明確沿用既有 `air_defense` 的
`ursina==8.3.0`，因為目前 3D 場景、相機、模型載入、滑鼠輸入與即時碰撞均已由 Ursina
承載；改以 Pygame 重寫會同時改造整個 3D 顯示／輸入層，超出本功能範圍。影響只限於
既有的 `scene.py`、`hud.py`、`main.py` adapter，純規則、升級、存檔與 STL→OBJ 轉換器
仍不匯入 Ursina。風險是 Ursina 版本／平台差異可能造成 OBJ 載入或圖形 smoke 偏差；以
釘選版本、程序化 fallback、純規則測試與手動驗收降低風險。這是本功能記錄的明確技術
例外，不在本功能內遷移；若未來回到 Pygame，必須另建遷移規格，先驗證 API、模型載入、
碰撞、輸入與手動流程後再切換。

**效能目標**：在既有 1280×720、A=5 的整合場景，暖機 5 秒後連續觀察 30 秒，
包含 10 架以上多目標候選與目前導彈／地面物件時，平均 FPS 至少 60。無圖形環境
只記錄為未量測，不以 headless 結果宣稱通過。

此處 `A=5` 明確指既有 Profile 的 `maximum_aircraft_count=5`；它不是多目標鎖定上限。
10+ 目標案例由受控／合成候選建立，效能與規則測試不得把 A 解讀成 2、6 或其他鎖定容量。

**限制**：不改動 `day1/` 或 `day2/`；不依賴外部模型轉換程式；不將 STL／OBJ
加入版本庫；純規則模組不得匯入 Ursina；普通防空炮的單目標鎖定、手槍、狙擊槍、
RPG 地面爆炸、波次、存檔與程序化 fallback 的非目標行為必須回歸通過。多目標
不設固定目標容量，但實際顯示數量受目前存在且可見的敵機數量限制。

**規模／範圍**：新增一份資產 manifest、一個標準函式庫轉換工具與兩份契約；擴充
`config.py`、`progression.py`、`save_data.py`、`rules.py`、`entities.py`、`scene.py`、
`hud.py`、`main.py` 的既有責任邊界；增加資產、RPG、多鎖定、齊射、升級相容、介面
切換與生命週期測試，不重寫既有狀態機或存檔 schema。

## 憲章檢查

*關卡：階段 0 研究前必須通過；階段 1 設計後重新檢查。*

### 階段 0 前：通過

| 原則／關卡 | 證據 |
|---|---|
| I. 可讀性優先，循序抽象 | 以一份 `asset_manifest.py` 集中映射與顏色，以一個轉換工具負責檔案格式；不建立服務層、框架或無必要的資產管線分層。 |
| II. 遊戲物件封裝狀態與行為 | `MultiAntiAircraftGun`、`LockOnTracker`、`GuidedMissile` 保留自身暫時狀態；所有跨目標齊射閘門與生命週期協調集中在純規則／controller，視覺由 scene／HUD 負責。 |
| III. 小步驟開發，每項行為可驗證 | 先測試轉換、RPG 邊界、無上限 tracker 與升級相容，再接入 scene／HUD，最後驗證 controller reset、完整回歸與 FPS。 |
| IV. 遊戲迴圈順序與狀態轉移明確 | 保留目前「飛機／導彈 → 投影／鎖定 → 地面／結算 → scene／HUD」順序；scope 關閉、武器切換、波次、game over 與回選單都有集中清理路徑。 |
| V. 範圍適當與依賴簡單 | 沿用既有 `air_defense` 並已在本計畫上方記錄 Ursina 例外的原因、影響與未來遷移條件；新增轉換功能使用標準函式庫，不新增依賴、網路、資料庫或其他專案修改。 |
| VI. SDD 文件使用繁體中文 | `research.md`、`data-model.md`、`contracts/`、`quickstart.md` 與本 `plan.md` 均以繁體中文撰寫；命令、檔案路徑與程式識別字保留必要原格式。 |
| 分支與交付治理 | `.specify/scripts/powershell/create-new-feature.ps1` 已建立 `specs/007-3d-assets-weapon-targeting/` 與 `.specify/feature.json`；本 repo 腳本只負責 feature metadata，Git 分支轉換另以等價的 `git switch -c 007-3d-assets-weapon-targeting` 完成，以保留既有 dirty worktree。現行分支名稱有效，後續實作前仍須再次驗證不在 `main`。 |

## 研究結論

研究結果詳見 [research.md](./research.md)，本計畫採用的具體決策如下：

1. `tools/convert_stl_assets.py` 以標準函式庫解析 binary／ASCII STL，移除退化面，
   依 [contracts/assets.md](./contracts/assets.md) 的七列固定軸矩陣與 Ursina X 軸讀取慣例輸出 OBJ；輸出獨立回報失敗，
   遊戲永遠保留 fallback。
2. `air_defense/asset_manifest.py` 是 runtime 與 converter 共用的單一映射來源；
   `scene.py` 不再用 `aircraft.glb`／`crew.glb` 或散落的 `rotation=(12, 0, 0)`。
3. RPG 全部中心射線／距離規則重用 `config.PISTOL_MAX_RANGE`；準心由 HUD 的同一
   crosshair builder 建立，和手槍互斥顯示。
4. `MultiLockOnTracker` 以所有目前投影中的有效 ID 建立動態集合，保留每個 ID 的
   獨立 tracker；多目標開火使用全數 READY 閘門與既有 `GuidedMissile`。
5. `aa_whitebox` 是兩種防空炮唯一有效的尺寸升級；舊 target-count ID 只保留存檔
   解析／保留能力，不再有商店目錄與 runtime 行為。
6. 模型顯示身份由固定 `asset_id`、canonical 軸契約、manifest 類型色與每個實例的
   獨立 mesh 組成；scene 不再讓某個模型的著色或載入結果外溢到其他模型。
7. HUD 以本次程式啟動期間的 `AntiAirGuiMode` 控制普通防空炮顯示：新版使用現行白框
   與動態準心；舊版恢復原始 003 的較大固定框、連續跟隨圓圈與進度視覺，圓圈依進度
   縮小到敵機外框；多目標無論模式都維持新版動態小準心。
8. 外部 OBJ 與主要世界幾何共用帶日照高光／陰影的 Ursina shader；方向光使用固定的
   地圖／飛行走廊 bounds，避免後生成的飛機沒有地面陰影。

## 設計與實作方案

### 1. 資產 manifest、轉換與 fallback

- 新增 `air_defense/asset_manifest.py`，提供七個穩定 `AssetSpec`、來源／產物檔名、
  遊戲角色、類型色、fallback 模型、固定 target extent／錨點、可見模型倍率與每個資產的固定來源軸
  轉換；同一模組產生非持久化 `RuntimeAssetChoice`，保存 OBJ 或 fallback 的選擇、
  均勻比例、碰撞器與載入錯誤。
- 新增 `tools/convert_stl_assets.py`：檢查輸入根目錄與輸出根目錄範圍，讀取目前
  binary STL 並保留 ASCII 解析；將座標轉成 Y-up／+Z-forward，移除非有限值與
  退化面，重新計算法線，補償 Ursina OBJ loader 的 X 軸翻轉，再產生可重複覆寫的
  OBJ。每個資產獨立產生 `AssetConversionResult`；失敗項目不刪除其他成功輸出。
- 產物寫入暫存檔後替換，避免中斷時留下半份 OBJ；`--check` 只驗證，不覆寫任何檔案。
- 修改 `.gitignore` 與 `assets/air_defense/README.md`，明確忽略本機 STL／OBJ、記錄
  七項映射、固定軸矩陣、target extent、類型色與 fallback 政策；不把來源或產物納入
  commit。
- `scene.py` 將 `create_optional_model()` 接到 manifest 的 output path。建立飛機、
  地面人物與目標大樓時依類型選擇 OBJ，設定既有玩法包絡與 `collider="box"`；在
  外部資產成功載入時不再無條件疊加舊 wing／head 裝飾，fallback 才保留必要輔助幾何。
  每個物件失敗只回退自己的程序化模型。因 Ursina 的字串模型參數是 asset name 而非
  Windows 絕對路徑，scene 以 `load_model(stem, folder=parent, use_deepcopy=True)`
  載入每個成功 OBJ，再把已載入 mesh 傳給 Entity，避免有效模型被錯誤回退或建立空 Entity。

### 1A. 方向校正與可見模型倍率

- `tools/mark_asset_forward.py` 提供不改變原始座標的 Ursina 檢視器，顯示未旋轉 STL、
  標示前／後／左／右／上／下的六條方向線與黃色前方／青色上方箭頭；按鍵選定每個模型的來源前方與上方後，
  工具輸出本機 ignored 的 `asset_axis_calibration.json` 與可核對矩陣。人工確認結果後
  才更新 `asset_manifest.py`，再重新執行 `convert_stl_assets.py`。判定時，飛機選螺旋槳／
  機鼻側為前方；人物選腳到頭為上方、選有臉的一側為前方。
- `AssetSpec` 保存新版外部模型的 `visual_scale_multiplier`：飛機／大樓為 `10.0`，陸地型態
  敵人為 `5.0`；地面人物的 `aim_collider_multiplier` 同樣固定為 `5.0`，使外部 OBJ 的
  中央準心瞄準 box 經 Entity scale 後與可見模型相同，其他資產為 `1.0`。
  `runtime_asset_choice()` 仍採單一均勻比例，外部 mesh 只在可見層放大；`scene.py` 以
  反向倍率重建基準 `BoxCollider`，再只對人物的中央準心射線使用可見包絡大小。fallback
  不套用外部模型倍率，改用 unit local box 配合 fallback 可見尺寸；射程、傷害與自動防禦規則不變。

### 1B. 日照、高光與陰影

- 新增 `air_defense/lighting.py`，以 Ursina 8.3.0 的 `lit_with_shadows_shader` 為基礎
  加入受控 Blinn-Phong 太陽高光；中性陰影色避免原始範例的藍色偏染。
- `scene.py` 建立一盞暖色 `DirectionalLight`、低強度 `AmbientLight` 與固定陰影捕捉
  volume；外部 OBJ、地面、建築、砲台與投射物經由同一個 scene helper 套用 shader。
- 光源與 shader 只屬視覺 adapter；若 OBJ 缺失仍走原 fallback，光照不得影響 box 碰撞、
  命中、傷害、射程或升級規則；人物與可見模型相同大小的瞄準 box 只服務中央射線目標取得。

### 2. RPG 與準心互斥

- `rules.py` 的 `is_valid_target()` 將 RPG 的預設射程映射改為
  `config.PISTOL_MAX_RANGE`，保留只接受地面敵人、彈藥、冷卻與爆炸去重規則。
- `main.py` 的 `_fire_rpg()` 將中心 raycast 和距離二次驗證都改用 12.0 手槍常數；
  驗證失敗必須在 `mark_fired()` 前返回，確保不扣彈、不冷卻、不傷害。
- `hud.py` 由既有 `_make_crosshair()` 建立 `rpg_reticle`，與 `pistol_reticle`
  使用相同尺寸、子元件與顏色；`update_reticle()` 將 RPG 加入唯一 active family，
  同時隱藏防空與狙擊 UI。`main._refresh_hud()` 傳入 RPG 狀態但不開啟 scope。

### 3. 多目標鎖定、白框與導彈齊射

- `config.py` 保留 `AA_LOCK_FRAME_SIZE` 作為普通防空炮現行基準，新增語意清楚的
  `AA_MULTI_LOCK_FRAME_MULTIPLIER = 2.0`；白框尺寸升級由同一個
  `effective_whitebox_scale()` 乘上多目標倍率。
- `rules.py` 擴充 `MultiLockOnTracker`：不再依 `target_capacity` 截斷；保留舊 keyword
  參數但明確忽略，並以穩定 ID
  去重，為新 ID 建立 `LockOnTracker`，對離框／不可見／死亡目標套用衰減或移除，
  提供 `MultiLockView`、`all_targets_ready` 與「全數 READY 才回傳完整快照」的介面。
  舊建構參數可保留為不生效的相容參數，但不得再被 runtime 或 HUD 解讀為上限。
- `entities.py` 的 `MultiAntiAircraftGun.set_targets()` 不再截斷清單，並以一次
  `mark_fired()` 清除當次集合；不新增第二份持久化狀態。
- `main.py` 的 `_update_airstrike()` 依目前武器選擇普通或多目標白框投影；普通槽位
  只更新單一 tracker，多目標槽位只更新 `MultiLockOnTracker`，避免兩個鎖定 UI 互相
  污染。scope 關閉或不在多目標槽位時清空多目標集合。
- `rules.py` 新增 frozen `MissileVolley` 純資料物件；`main.py` 抽出共用的導引導彈
  建立邊界或等價協調函式。多目標左鍵先取得完整
  `fireable_target_ids`，再一次驗證每個 aircraft 仍存在、存活、可見、在多目標白框
  內；任何一個失效就整次拒絕。通過後逐 ID 建立 `GuidedMissile`、scene entity 與
  `active_missiles` 登記，以 `(target_id, missile_id)` 填入 `MissileVolley`，整批成功
  後只設定一次 cooldown；禁止直接呼叫 `target.take_damage()`。
- 既有 `_update_active_missiles()` 保持每枚導彈依自己的 `target_aircraft_id` 更新、
  命中、過期、爆炸與 stale target 清除；多枚同幀建立時仍以唯一 missile ID 隔離。
- `hud.py` 新增可回收的 `dict[target_id, multi_reticle_entity]` pool。每個目前投影
  目標顯示小準心與個別進度標記，使用 `MultiLockView` 的位置／顏色／進度；目標移除
  立即隱藏並釋放，不以 `MAX_AUTO_DEFENSE_TURRETS` 或 6 作限制。固定大白框保持白色，
  不被小準心重新著色。

### 3A. 防空介面設定頁

- `state.py` 新增 engine-independent 的 `AntiAirGuiMode`，預設 `NEW`；它是當次程式
  啟動的顯示偏好，不進入 Profile schema。
- `hud.py` 在主選單增加「設定」，並建立獨立設定頁、回主選單按鈕、新版／舊版兩個選項。
  舊版只在普通防空炮瞄準時恢復原始 003 的較大固定框與連續跟隨圓圈；圓圈由大到小
  對齊敵機投影，並沿用同一進度條／文字／顏色狀態。多目標仍保留 2 倍白框與每目標
  小準心。所有 HUD 家族與生命週期清理由同一套 update／show 方法控制。
- `main.py` 只負責開關頁面、保存當次模式與將模式傳給 HUD；武器射程、傷害、鎖定、
  導彈與升級計算不讀取此偏好。

### 4. 升級與舊存檔相容

- `progression.py` 的 `aa_whitebox`、`effective_whitebox_scale()` 與價格／上限規則
  保持單一來源；`upgrade_catalog()` 移除舊的固定 target-count 有效項目，商店不再
  顯示或允許購買它。
- 保留舊 ID 在 `save_data.py` 的已知輸入集合，讀取時允許舊等級／快照存在，但在
  上限驗證、商店、白框計算、tracker 建立與 HUD 中忽略。schema 維持 1；必要時在
  保存時保留該鍵以便相容讀取，不讓它重新成為有效規則。
- 移除 `main.py` 對 `multi_aa_target_count()` 的 runtime 依賴；普通與多目標只從
  `effective_whitebox_scale()` 計算白框，且多目標固定乘 2.0。

### 5. 測試與驗收順序

1. 新增 `tests/test_asset_conversion.py`：用暫存的合成 binary／ASCII STL 驗證映射、
   退化面清理、方向／loader 補償、輸出檢查、單項失敗隔離與缺檔結果；延伸既有
   fallback 測試確認 `.obj` 缺少時仍使用 cube。
2. 更新 `tests/test_new_weapons.py`、`tests/test_weapon_system.py`：驗證 RPG 12.0
   內含邊界與飛機拒絕，並以 10 個以上 ID 驗證 tracker 不截斷、每 ID 獨立進度、
   離框衰減、全數 READY 閘門與導彈目標固定。
3. 更新 `tests/test_economy.py`、`tests/test_save_data.py`：驗證白框升級的單一來源、
   多目標比例 2.0、舊 target-count 存檔可讀且不出現在有效商店／容量規則。
4. 更新 `tests/test_hud_wave.py`：驗證 RPG／手槍／狙擊／普通 AA／多目標 UI 互斥，
   動態小準心在 10+ 目標下正確建立／移除，且白框與小準心顏色不互相污染。
5. 更新 `tests/test_game_lifecycle.py` 與必要的 `test_airstrike_guidance.py`：驗證
   N 枚齊射不直接扣血、每枚導彈命中／過期／stale target 隔離，以及 scope、換武器、
   波次、game over、回選單、重新開始的清理。
6. 每個邏輯 checkpoint 都先執行語法檢查並做對應手動 smoke，再進入下一個整合故事：
   T004 驗證生命週期、T009 驗證資產／fallback、T016 驗證 RPG 準心與射程、T025
   驗證多目標 UI／齊射、T032 驗證升級與重載；T033～T036 固定 US1～US4 基線。
   全部 checkpoint 通過後，再依 `quickstart.md` 執行完整 `unittest`、資產轉換、方向
   校正工具 smoke、遊戲啟動與 30 秒 FPS 記錄；未能取得圖形環境時明確標記未量測。

## 檔案與責任邊界

### 本功能文件

```text
specs/007-3d-assets-weapon-targeting/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── assets.md
│   └── ui.md
├── checklists/
│   └── requirements.md
└── tasks.md                 # 已由 speckit-tasks 產生；實作依此執行
```

### 原始碼、工具與測試

```text
air_defense/
├── asset_manifest.py        # 新增：七項資產映射、方向、顏色、fallback 契約
├── config.py                # 普通／多目標白框倍率與既有武器常數
├── progression.py           # aa_whitebox 共用升級；舊 target-count 僅相容處理
├── save_data.py             # schema 1 舊升級鍵的讀取／驗證相容
├── rules.py                 # RPG 12.0、動態 MultiLockView／全數 READY 規則
├── entities.py              # 無容量截斷的多目標武器與既有導彈實體
├── scene.py                 # OBJ 選擇、fallback、投影、box 碰撞與清理
├── hud.py                   # RPG 準心、2 倍白框、動態多目標準心／進度池
└── main.py                  # 武器分流、齊射建立、冷卻與生命週期協調

tools/
├── convert_stl_assets.py    # 新增：binary／ASCII STL → canonical OBJ
└── mark_asset_forward.py    # 新增：未旋轉 STL 來源軸與前進方向校正器

assets/air_defense/
├── README.md                # 更新本機資產政策與映射
└── models/                  # 本機 ignored OBJ；不提交

tests/
├── test_asset_conversion.py # 新增：轉換器與 manifest 純邏輯測試
├── test_new_weapons.py      # RPG、多目標 tracker、固定目標導彈
├── test_weapon_system.py    # 武器類別／射程／目標門檻
├── test_economy.py          # 白框升級與舊容量規則停用
├── test_save_data.py        # 舊升級鍵 schema 1 相容
├── test_hud_wave.py         # 準心互斥與動態小準心
├── test_game_lifecycle.py   # 齊射、清理與結果轉移
├── test_airstrike_guidance.py
└── test_rules.py            # 既有 fallback 與空間規則回歸
```

**結構決定**：延續目前 `air_defense` 的淺層模組，不建立新的服務、資料庫或引擎
抽象。資產 manifest 是純資料／路徑邊界；轉換器是離線工具；rules／entities 保持
可脫離 Ursina 測試；scene／hud／main 只在需要時接到視覺與輸入。`models/`、`遊戲3d/`
與任何轉換暫存檔都不屬於可提交原始碼。

## 設計後憲章檢查：通過

| 原則／關卡 | 設計證據 |
|---|---|
| I. 可讀性優先，循序抽象 | 新增的 manifest、converter、`MultiLockView` 都有單一責任；共用導彈建立與 whitebox 計算避免重複規則。 |
| II. 遊戲物件封裝狀態與行為 | 每個 tracker／武器／導彈保留自身狀態；跨目標「全數 READY」與生命週期清理仍由命名清楚的 coordinator／純規則處理。 |
| III. 小步驟開發，每項行為可驗證 | T004、T009、T016、T025、T032、T033～T036、T043、T052、T067 各自包含 compile、建置或對應 smoke checkpoint；補充故事完成後再做 T057～T058 的整體交付驗證。 |
| IV. 遊戲迴圈順序與狀態轉移明確 | 射擊前完整驗證、同幀 N 枚導彈登記、終止清除與 scope reset 都有明確邊界；每個 checkpoint 都驗證清理後仍不取消已發射導彈，不改變既有主迴圈順序。 |
| V. 範圍適當與依賴簡單 | 不新增第三方套件；STL parser、OBJ writer 與規則使用標準函式庫；Ursina 例外的原因、影響與遷移條件已記錄，且仍限於現有 `air_defense`。 |

## 補充變更計畫：RPG／陸地自動防禦射擊視覺與平衡

本補充承接同一功能分支，不改變 OBJ 的 Y-up／+Z-forward 契約，也不把投射物的
視覺責任混入純規則。RPG 射擊沿用既有「合法時立即建立爆炸快照」的傷害時序，另在
scene adapter 建立短暫的 `RPGProjectileEffect`；投射物只負責從玩家視角附近移向
爆炸中心，不會再次呼叫傷害。

陸地自動防禦沿用現有 `GroundTracerEffect` 作為敵我一致的黃色曳光效果，並在砲台
外觀增加固定底座／槍管。砲台開火流程先通過純規則的落地、存活、Boss 剩餘生命與
32.0 世界單位射程判定，再建立曳光效果與套用一次傷害；視覺建立失敗不得阻塞規則
傷害，也不得重複造成傷害。

平衡值集中在 `config.py`／`ProgressionConfig`：自動防禦基準傷害為 1、一般生成的
非 Boss 地面敵人為 3 HP、Boss 仍為 10 HP 且自動防禦只可傷害至 5 HP，基準 CD
直接等於手槍預設 0.20 秒。射程使用單一 `AUTO_DEFENSE_MAX_RANGE`，邊界採包含式；
永久 cooldown 升級仍由既有共用 `effective_cooldown()` 套用。

### 補充實作順序

1. 先在 `tests/test_new_weapons.py`、`tests/test_game_lifecycle.py` 與必要的 scene
   mock 測試固定顏色、矩形尺寸、生命值／Boss 上限、32.0 邊界、0.20 秒 CD 與清理。
2. 在 `entities.py`／`rules.py` 增加純資料與目標判定；在 `progression.py`／`state.py`
   讓新平衡值進入新小關且不改變舊存檔格式。
3. 在 `scene.py` 接入 RPG 綠色長方體、砲台外觀與黃色曳光更新／清理；在 `main.py`
   接入合法 RPG 射擊與自動防禦發射事件。
4. 先跑新增測試，再跑完整 `compileall`／`unittest`；最後補做 quickstart 的圖形
   smoke 與資產轉換記錄。

### 文件與分支補充

- VI. SDD 文件使用繁體中文：本階段所有新文件均為繁體中文，必要的路徑、命令、常數與 enum 保留原格式。
- 分支治理：規劃與後續實作均在 `007-3d-assets-weapon-targeting`，不在 `main` 上繼續修改；既有未相關變更保持原狀。

除上方已明確記錄的既有 Ursina 技術例外外，未新增憲章例外；沒有需要 Complexity Tracking 的項目。

## Complexity Tracking

無。設計沒有違反憲章原則，也沒有引入需要額外核准的架構複雜度。
