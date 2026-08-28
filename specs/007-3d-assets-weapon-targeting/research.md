# 研究：3D 資產與武器瞄準整合

**功能**：`007-3d-assets-weapon-targeting`
**研究日期**：2026-08-28

## 研究範圍與現況基線

本功能承接目前 `air_defense` 的 Ursina 3D 執行環境，沒有改造 `day1/` 或
`day2/` 教學專案。現有遊戲依賴 `ursina==8.3.0`，純規則與實體模組不匯入
Ursina；`tests/` 使用 Python `unittest`。在建立本功能分支後，
`python -m compileall -q air_defense tests` 與完整測試套件均通過，基線為 159 個測試。

現有基線已包含以下可重用能力：

- `AirDefenseScene.create_optional_model()` 能在本機資產不存在或載入失敗時使用程序化
  fallback。
- `Aircraft`、`GuidedMissile`、`LockOnTracker`、RPG 爆炸結算及每幀清理流程已在
  `entities.py`、`rules.py`、`main.py` 分離。
- `effective_whitebox_scale()` 已是普通防空炮白框的集中升級倍率來源。
- `scene.project_aircraft_targets()` 已能產生帶有穩定敵機 ID、可見性、畫面位置與白框
  判定的投影資料。

## 決策 1：使用標準函式庫建立可重複的 STL → OBJ 轉換器

**決策**：新增本機工具 `tools/convert_stl_assets.py`，只使用 Python 標準函式庫解析
ASCII 與 binary STL、清理面資料、套用方向轉換並輸出 OBJ；不把模型產物納入版本庫。
遊戲啟動不依賴轉換器或原始 STL。

**依據**：目前七個來源檔案的大小都符合 binary STL 的 `84 + 50*n` 位元組結構，且
`requirements-game.txt` 只有已釘選的 Ursina。轉換工作的必要功能是三角面讀取、頂點
清理、法線與文字輸出，不需要 Blender 或第三方網格框架。

**輸出位置與命名**：轉換器預設將產物寫入
`assets/air_defense/models/`，名稱固定為：

| 來源 STL | 遊戲用途 | 產出 OBJ |
|---|---|---|
| `普通飛行.stl` | 普通飛機 | `aircraft_normal.obj` |
| `多人飛機.stl` | 人力支援飛機 | `aircraft_manpower_support.obj` |
| `速度飛行.stl` | 快速飛機 | `aircraft_fast.obj` |
| `魔王飛行.stl` | Boss 飛機 | `aircraft_boss.obj` |
| `普通陸地.stl` | 一般地面人物，也供人力支援掉落人物使用 | `crew_normal.obj` |
| `魔王陸地.stl` | 地面 Boss | `crew_boss.obj` |
| `大樓.stl` | 目標大樓 | `target_building.obj` |

**替代方案**：使用 Blender、`trimesh`、`numpy` 或外部 STL 工具轉檔。這些方案會增加
安裝與版本負擔、使離線教學環境難以重現，也無法自動解決目前 Ursina OBJ 匯入的座標
慣例，因此不採用。

## 決策 2：在轉換階段固定座標慣例，不在遊戲執行時堆疊旋轉補正

**決策**：每個資產在 manifest 中有固定的來源軸排列／符號轉換；轉換後的語意座標一律
為 Y 軸向上、飛機機頭／人物面向為 +Z，大樓正面也以 +Z 為基準。場景建立與更新使用
飛機的飛行方向，或地面人物的水平實際移動／下一個路徑目標；人物只更新 yaw 並保持
Y 軸向上，不新增每個模型的 runtime rotation offset。

canonical 採右手座標系，`+X` 為右方、`+Y` 為上方、`+Z` 為機頭／人物面向。為讓
轉換可測試且不靠人工猜測，manifest 使用下列 signed-permutation；表中的
`(Xc, Yc, Zc)` 對來源 `(Xs, Ys, Zs)`，每個矩陣行列式都是 `+1`，不改變三角面繞序：
六個飛機／人物列已依本機校正工具儲存結果更新；大樓尚未完成人工校正，先保留原矩陣：

| `asset_id` | 來源上方 | 來源前方 | 固定轉換 `(Xc, Yc, Zc)` |
|---|---|---|---|
| `aircraft_normal` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `aircraft_manpower_support` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `aircraft_fast` | `+Z` | `-X` | `(-Ys, Zs, -Xs)` |
| `aircraft_boss` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `crew_normal` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `crew_boss` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `target_building` | 未確認 | 未確認 | `(-Xs, Zs, Ys)`（暫保留） |

這張表就是本功能的方向決策來源；視覺 smoke 只驗證產物是否符合它，若不符合必須
回報轉換失敗並修正轉換器／規格，不得在 `scene.py` 另加模型專屬旋轉角度。

目前來源預覽顯示飛機、人物與大樓的初始朝向不一致，因此不能以一個全域旋轉角度
可靠修正。`air_defense/scene.py` 目前仍以 `aircraft.glb`、`crew.glb` 與一個
`rotation=(12, 0, 0)` 的程序化假設為基線，這正是本功能要收斂的方向來源。

**Ursina 相容處理**：本機安裝的 Ursina 8.3.0 `mesh_importer.py` 會對 OBJ 頂點與
法線使用 `L(x, y, z) = (-x, y, z)`。轉換器先得到 canonical 頂點／法線 `C`／`N`，
再寫出 `v_obj=L(C)`、`vn_obj=L(N)`，並保留每個三角面的 canonical 索引順序，使
loader 讀回後的位置、法線與繞序仍是 canonical 結果；反向索引會使幾何繞序與顯式
法線相反。這項補償只存在於轉換器，不會
散落到 `scene.py` 的單一資產旋轉參數。

**替代方案**：在 `create_aircraft()`、`create_crew_members()` 分別保留旋轉角度，或
執行時讀取模型名稱再套用不同角度。這會讓程序化 fallback、OBJ 與每個敵人類型的
方向規則分叉，且無法滿足「轉換階段統一」的需求，因此不採用。

## 決策 3：資產無材質依賴，顏色、碰撞與瞄準包絡留在遊戲語意層

**決策**：STL 轉出的 OBJ 只保留有效幾何與可載入的法線，不依賴貼圖或外部 MTL。
場景依敵人類型套用既定顏色：普通與一般地面人物紅色、人力支援橙色、快速藍色、
Boss 紫色、大樓藍灰色。模型與既有物件一樣使用簡化 `box` 碰撞，模型只取代可見外觀；
地面人物的 Entity box 另使用 `aim_collider_multiplier=5.0`，與陸地外部模型的可見倍率
一致，讓中央準心射線可以取得完整人物外觀。
這個瞄準包絡只屬場景 adapter，不改變傷害、武器射程或陸地自動防禦選取。
含有完整外觀的 OBJ 不再無條件疊加舊的 wing／head 裝飾；只有程序化 fallback 才保留
必要的輔助幾何以維持原來的可辨識性。

**依據**：STL 本身不提供可依賴的遊戲材質；現有 `create_optional_model()` 已有安全的
檔案範圍檢查與 Entity 載入 fallback，適合由一份 `asset_manifest` 同時提供模型檔名、
類型色、fallback 與比例包絡。

**比例與錨點**：轉換器套用固定矩陣、移至包絡中心並重新計算法線；runtime 以來源
包絡計算 `uniform_scale = min(target_extent_i / source_extent_i) × visual_scale_multiplier`，因此保留長寬比且
不超過既有程序化 fallback 的視覺上限。target extent 固定為一般飛機 `(1.6, 0.45, 2.8)`、
Boss 飛機 `(1.9, 0.60, 3.2)`、一般人物 `(0.65, 1.8, 0.65)`、Boss 人物 `(0.9, 2.4, 0.9)`、
目標大樓 `(10, 12, 9)`；飛機以包絡中心錨定，人物與大樓以包絡底面對齊地面。一般／Boss
人物的外部模型瞄準 box 使用與可見模型相同的包絡；任一
來源軸為零或非有限時選擇 fallback。runtime 的 `RuntimeAssetChoice` 是不持久化的
選擇結果，至少保存 asset ID、模型／fallback 路徑、是否 fallback、類型色、均勻比例、
`box` 碰撞器與載入錯誤，讓單項失敗不污染其他選擇。

## 決策 4：RPG 射程直接重用手槍常數

**決策**：RPG 的中心射線與合法目標驗證都使用 `config.PISTOL_MAX_RANGE`，目前值為
12.0，且使用包含邊界 `<=`。`rules.is_valid_target()` 的 RPG 預設射程映射同步改為
手槍常數；`main._fire_rpg()` 的 raycast 與第二次距離驗證不可再讀取狙擊槍的 180.0。

**依據**：目前 `can_fire_pistol()` 已集中實作 12.0 邊界，RPG 的地面目標、爆炸半徑、
傷害、彈藥與冷卻邏輯已可重用；現有 RPG 路徑有兩處直接使用
`config.SNIPER_MAX_RANGE`，是明確的錯誤來源。

**替代方案**：新增另一份 RPG 射程常數或把 RPG 射程留在場景 raycast 參數。這會讓「與
手槍相同」失去單一來源，也可能造成射線能找到目標但規則拒絕（或反向）的不一致，因此
不採用。

## 決策 5：多目標鎖定以動態 ID 集合與既有導引導彈實作

**決策**：`MultiLockOnTracker` 仍以每個目標一個 `LockOnTracker` 為基礎，但移除 2、6
或其他固定容量的截斷。每幀從所有目前可見的敵機投影加入／移除目標：新進入白框者
開始獨立進度，離開白框者保留既有進度並進入衰減，死亡、不可見或衰減歸零者移除。
新增 `MultiLockView` 資料供 HUD 顯示每個 ID 的位置、進度與鎖定狀態。

多目標開火必須先取得「所有目前有效目標皆已完成鎖定」的快照，再重新驗證每個 ID
仍存在、可見、在白框內且類別合法；任何一個失效都取消整次開火，不得部分齊射。通過
驗證後，對每個 ID 建立一個現有 `GuidedMissile`，讓 `active_missiles`、目標識別、
掃掠碰撞、命中、過期與清理路徑共用單一實作。每次齊射只設定一次多目標武器冷卻，
齊射後鎖定集合重設，下一次需重新全數鎖定。

**依據**：現有 `GuidedMissile` 已保存 `target_aircraft_id`，且
`_update_active_missiles()` 已能同時管理多枚飛彈與過期／死亡目標；目前多目標開火卻
直接呼叫 `target.take_damage(1)`，沒有延遲命中與獨立飛彈視覺，應改為重用既有導引邏輯。

**替代方案**：保留固定 2→6 容量、用一次群體傷害代替飛彈，或只建立一枚帶目標清單的
群體飛彈。這些方案都違反無固定目標上限、每目標一枚導彈與固定目標 ID 的驗收條件，
因此不採用。

## 決策 6：多目標白框是普通白框的明確倍率，升級仍只有一個來源

**決策**：保留 `config.AA_LOCK_FRAME_SIZE` 作為普通防空炮的現行基準，新增
`config.AA_MULTI_LOCK_FRAME_MULTIPLIER = 2.0`。實際投影與 HUD 尺寸分別計算：普通為
`base_size * effective_whitebox_scale`，多目標為普通結果乘以
`AA_MULTI_LOCK_FRAME_MULTIPLIER`。
`effective_whitebox_scale()` 與既有 `aa_whitebox` 商店項目不分叉；舊的
`multi_anti_aircraft_targets` 存檔鍵可被讀取但不再出現在商店，也不參與目標集合。

**依據**：目前白框升級已集中於 `progression.py`，而現有多目標目標數升級、
`multi_aa_target_count()` 與 hard limit 正是導致固定上限的來源。保留舊鍵只為避免舊
JSON 因未知欄位失敗，將它從有效目錄移除即可避免新購買與 HUD 繼續宣稱容量規則。
存檔 schema 維持 1，不需要把短暫鎖定或飛彈寫入永久 Profile。

## 決策 7：用純規則測試加上最小 GUI smoke 驗證

**決策**：所有方向轉換、RPG 距離、動態集合、全數鎖定閘門、齊射數量、目標隔離、
升級倍率與 reset 優先在不啟動視窗的 `unittest` 驗證；HUD／Scene 只做最小 mock 或
Ursina adapter smoke。完整測試仍使用 `compileall` 與 `unittest discover`，FPS 與模型
方向的視覺結果需在可用的 1280×720 圖形環境中手動記錄，headless 不宣稱通過。

**依據**：憲章要求純邏輯可脫離畫面測試，且目前完整套件已能在無視窗環境快速執行。
多目標無固定上限可以用 10 個以上的合成投影驗證，不必建立昂貴或不可重現的真實場景。

## 研究結論

技術選擇與整合邊界均已確定：標準函式庫轉換器負責 OBJ 的幾何與方向契約，
`asset_manifest` 負責映射／顏色／fallback，純規則層負責目標與齊射規則，Ursina scene
與 HUD 只負責視覺轉接，既有 Profile schema 只做舊升級鍵的相容處理。所有技術選擇、
實作邊界與驗收條件均已在本文件及相關契約固定。

## 補充決策 8：RPG 使用獨立的綠色長方體視覺投射物

**決策**：合法 RPG 射擊仍在射擊事件建立既有爆炸快照，避免改變目前的傷害時序；同一
事件另外建立 `RPGProjectileEffect`，由 scene adapter 以固定綠色、固定寬高與有限生命週期
的 cube 沿玩家視角起點到爆炸中心更新。投射物有唯一 ID，過期、波次、終止與返回選單
時清理，但不持有或重複執行傷害。

**依據**：使用者要求「發射時飛出綠色長方體子彈」，而現有 RPG 規則測試與生命週期已
依賴合法射擊後立即結算爆炸；將可見性與傷害時序拆開可以同時保留既有 gameplay API
與新的視覺回饋。

## 補充決策 9：陸地自動防禦採短射程、低傷害與手槍級基準 CD

**決策**：陸地自動防禦的有效射程固定為 32.0 世界單位，基準傷害為 1，基準 CD 使用
手槍預設 CD 0.20 秒；一般生成非 Boss 地面敵人的生命值調為 3，需三發命中。Boss
仍為 10 HP，但自動防禦可選取它直到剩餘 5 HP，達到 50% 剩餘生命後不再選取。每次
實際開火沿用 `GroundTracerEffect` 產生與敵方相同的黃色曳光效果；砲台 scene entity
補上固定底座與槍管以保證可辨識外觀。

這組決策是 007 對 006 陸地自動防禦契約的後續覆寫；006 的每小關彈藥與舊冷卻／傷害
數值只作歷史記錄。程式仍保留 `ProgressionConfig` 的舊彈藥欄位以維持來源相容，但
目前砲台不讀取該欄位，也不建立有限彈藥池。

**替代方案**：維持 80.0 射程、20 傷害與 1.5 秒 CD，或讓砲台只攻擊非 Boss。前者會
使自動防禦一發清除普通敵人並覆蓋過大範圍，後者無法滿足 Boss 只能受半血自動傷害的
平衡要求，因此不採用。所有新數值仍集中在 config／ProgressionConfig，cooldown 升級
只經由既有共用倍率推導。

## 決策 10：Ursina OBJ 使用明確資料夾載入，不傳入絕對路徑

**決策**：`RuntimeAssetChoice.model_path` 保留解析與診斷所需的絕對 `Path`，但 scene
不把它直接傳給 `Entity(model=...)`。Ursina 8.3.0 的字串參數會被視為 asset name，
因此 scene 以 `model_path.stem`、`model_path.parent` 與 `use_deepcopy=True` 呼叫
`load_model()`，成功取得 mesh 後再交給 Entity；`None` 或例外仍只觸發目前 asset ID
的程序化 fallback。

**依據**：在 Windows 上直接使用 `C:\...\aircraft_normal.obj` 會讓 loader 搜尋含磁碟
路徑的模型名。Ursina 預設又可能只印 warning 而不拋例外，造成模型未顯示但不會進入既有
fallback 分支。明確指定資料夾可支援不同工作目錄，並讓失敗能被 scene adapter 捕捉。

## 補充決策 11：模型方向與顏色以每個資產實例隔離

**決策**：保留 manifest 的七列固定 signed-permutation，將 canonical `+Y` 向上與
`+Z` 機頭／人物面向視為每個可用 OBJ 的顯示身份；scene 建立／更新飛機時以無 roll 的
canonical 朝向計算對齊 `aircraft.forward`，地面人物建立與更新時以水平 yaw 對齊實際
移動或下一個路徑目標，同樣不加入依模型名稱分支的旋轉角度。每次
`load_model()` 都要求獨立 mesh 副本，並由對應 `AssetSpec.runtime_tint` 強制設定該
Entity 顏色，避免 Ursina 共用模型快取或父子 Entity 著色造成模型顏色混用。

**依據**：目前四種飛機的正確辨識同時依賴檔名映射、方向契約與類型色；只驗證 OBJ
存在不能保證 runtime 建立的是正確模型，也不能防止同一 mesh 的著色狀態外溢。由
manifest 提供固定身份、由 scene 建立獨立 mesh 與顏色，是不增加材質系統的最小修正。

**替代方案**：在每種飛機建立流程中各自複製顏色／旋轉或依模型外觀臨時猜方向。這會
  產生多份容易漂移的規則，且再次遇到缺檔 fallback 時仍可能混淆，因此不採用。

## 補充決策 12：主選單提供新版與舊版防空瞄準介面

**決策**：在 Profile 主選單新增「設定」入口與獨立防空介面頁，提供「新版防空瞄準」
與「舊版圓圈鎖定」兩個選項。新版保留現行普通白框及多目標動態小準心；舊版只在
普通防空炮開啟瞄準時恢復原始 003 的較大固定框與連續跟隨圓圈，圓圈會隨鎖定進度
縮小到敵機外框。兩種模式共用同一套鎖定 tracker、射程、傷害、導彈與升級規則；
多目標防空無論選哪一種偏好都維持新版 2 倍白框與無固定上限的小準心。選擇只在本次
程式啟動期間保留，重新啟動預設新版，且不改寫既有 Profile schema。

**依據**：舊版圓形元件已存在於 HUD，但目前更新流程總是將其關閉；重新使用該元件
可以恢復使用者要求的操作提示，不必維護第二份鎖定規則。多目標仍使用新版是為了保留
每個目標獨立位置／進度，避免圓圈無法表達多目標集合。

**替代方案**：讓新版／舊版各自擁有不同鎖定邏輯，或把介面偏好寫入 Profile。前者會
  造成規則分叉，後者會改變既有存檔責任與不同 Profile 共用的 UI 偏好，因此不採用。

## 補充決策 13：舊版只恢復原始 003 的普通防空瞄準視覺

**決策**：使用者提供的 `003-air-defense-lock-guidance` spec 只作為「舊版」普通防空
介面的來源。舊版保留 55° 防空開鏡、較大的固定鎖定框、中央隱藏 15% 圓形判定、
連續跟隨圓圈、3 秒鎖定進度、0.75 秒衰減、每秒最多 3° 吸附與黃色導引飛彈等已存在
的遊戲規則；圓圈半徑從 `AA_LOCK_RING_ACQUISITION_RADIUS` 依進度插值到敵機投影
外框加 padding。這些規則與新版共用，不在舊版複製另一份 tracker 或射擊流程。

舊版不引入 003 spec 以外的設定、存檔、容量或資產行為；目前 007 的 RPG、無固定上限
多目標齊射、OBJ 資產映射、模型倍率與陸地自動防禦仍由本功能自己的需求負責。多目標
防空炮仍使用新版的小準心集合，避免把單一舊版圓圈錯套到多個目標。

**依據**：原始 003 的歷史 HUD 已使用 `tracking_ring_radius()` 讓圓圈由大縮到目標，
而現行模式切換只恢復了圓圈元件、沒有恢復半徑插值。以來源 spec 的範圍界線重新接回
這段顯示邏輯，可修正舊版而不把不相關內容整份拷貝到 007。

## 補充決策 14：提高模型可見倍率並加入日照高光／陰影

**決策**：外部 OBJ 的 `visual_scale_multiplier` 為飛機／大樓 `10.0`、陸地型態敵人
`5.0`，仍只作用於成功載入的可見 mesh；scene 以反向倍率維持 gameplay 基準
`BoxCollider`，地面人物的中央準心瞄準 box 則改為覆蓋實際可見模型包絡。對外部 OBJ，
`aim_collider_multiplier=5.0` 使 local box 經 Entity scale 後與模型相同；對 fallback 使用
unit local box 配合 fallback 尺寸。射程、傷害與自動防禦選取包絡不變。
為修正模型只剩一團類型色的問題，新增以 Ursina
內建 `lit_with_shadows_shader` 為基礎的日照 shader，加上受控 Blinn-Phong 高光，並在
scene 建立暖色方向光、低強度環境光與固定涵蓋地圖／飛行走廊的 shadow bounds。方向校正
工具同步以「前／後／左／右／上／下」六條具名線呈現來源軸。

**依據**：使用者回報現有模型過小且表面糊成單色；單純再增加類型色或在 runtime 疊加
模型旋轉不能提供輪廓深度，也會違反方向由 OBJ 轉換階段統一的契約。方向光與 shadow map
能同時讓前後表面產生明暗差、讓物件在地面留下投影，specular 項則提供可辨識的日照反射
亮點；固定 bounds 避免光源只依第一波當下 Entity 計算而漏掉後續飛機。

**替代方案**：只把模型再放大、不加光照；或直接把 `Entity.default_shader` 全域改成陰影
shader。前者仍會保留平面單色外觀，後者會把 HUD／未來 UI Entity 也套上 3D shader，
造成顯示責任外溢，因此不採用。
