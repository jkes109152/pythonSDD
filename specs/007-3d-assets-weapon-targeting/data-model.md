# 資料模型：3D 資產與武器瞄準整合

## 模型關係

```text
AssetSpec ──> RuntimeAssetChoice ──> Ursina Entity
Aircraft ──> AircraftScreenTarget ──> MultiLockTargetState
                                      │
                                      └──全部 READY──> MissileVolley
SaveProfile ──aa_whitebox──> WhiteboxDimensions
```

本功能的鎖定、準心、齊射與導彈都是單次戰鬥的暫時資料，不加入永久存檔；
`SaveProfile` 只保留既有的 `aa_whitebox` 升級以及可相容讀取的舊目標數鍵。

## 標準化 3D 資產

### `RuntimeAssetChoice`

場景依 `AssetSpec` 與目前檔案狀態產生的暫時選擇結果。它由
`air_defense/asset_manifest.py` 提供資料、由 `air_defense/scene.py` 在建立 Entity
時消費；不寫入 Profile 或其他永久存檔。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `asset_id` | 穩定字串 | 對應一筆 `AssetSpec`，不可因 fallback 改名 |
| `model_path` | 可選路徑 | 通過檔案範圍與 OBJ 可載入檢查的本機產物；fallback 時為 `None` |
| `fallback_model` | 字串 | 失敗或缺檔時建立的程序化模型名稱 |
| `fallback_used` | 布林值 | `model_path` 不可用、解析失敗或方向／包絡驗證失敗時為真 |
| `runtime_tint` | RGB 浮點三元組 | 由資產角色固定提供，OBJ 材質不覆寫此值 |
| `runtime_scale` | 正浮點數 | `min(target_extent_i / source_extent_i) × visual_scale_multiplier` 的單一均勻比例，保留模型比例 |
| `visual_scale_multiplier` | 正浮點數 | 只放大可見 OBJ；fallback 為 `1.0`，基準 box 碰撞包絡以反向倍率維持原值 |
| `collider` | 字串 | 固定為簡化 `box`；地面人物的瞄準取得包絡可依 `AssetSpec.aim_collider_multiplier` 放大 |
| `load_error` | 可選字串 | fallback 時保存使用者可讀原因，不含堆疊追蹤 |

選擇流程固定為：檢查來源／產物路徑 → 嘗試載入 OBJ → 套用固定方向與包絡驗證 →
成功使用 OBJ，否則只讓該 `asset_id` 回退。`RuntimeAssetChoice` 不得把另一個資產的
錯誤、材質或 fallback 選擇帶入目前 Entity。`model_path` 雖為絕對診斷路徑，Ursina
scene adapter 必須以 `model_path.stem` 與 `model_path.parent` 的明確資料夾載入 mesh，
不可直接把 Windows 絕對路徑當成 `Entity` 的字串模型名。

### `AssetSpec`

由無引擎的資產 manifest 提供每一類模型的固定契約。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `asset_id` | 穩定字串 | 例如 `aircraft_normal`、`crew_boss`、`target_building`；不可因語系改名 |
| `source_file` | 相對路徑 | 指向 `遊戲3d/` 下的指定 STL；只供本機轉換器使用 |
| `output_file` | 相對路徑 | 指向 `assets/air_defense/models/` 下的 OBJ；產物不提交版本庫 |
| `game_roles` | 字串集合 | 對應 `AircraftType`、地面人物或目標大樓 |
| `source_to_canonical` | 固定 signed-permutation | 僅能使用本文件的方向表；只在轉換階段套用，結果必須是 Y-up、+Z-forward |
| `runtime_tint` | RGB 浮點三元組 | 普通／一般地面人物紅色、人力支援橙色、快速藍色、Boss 紫色、大樓藍灰色 |
| `fallback_model` | 字串 | 目前場景使用的程序化模型，至少維持 `cube` fallback |
| `target_extent`／`anchor` | 三軸包絡／錨點 | 由 `AssetSpec` 提供既有物件的視覺與落地基準；瞄準 box 另依資產策略處理 |
| `visual_scale_multiplier` | 正浮點數 | 飛機／大樓 `10.0`、陸地型態敵人 `5.0`；只作用於可見 OBJ，fallback 不套用 |
| `aim_collider_multiplier` | 正浮點數 | 中央準心射線使用的 box 相對基準倍率；一般／Boss 地面人物為 `5.0`，與其外部可見倍率一致，其餘資產為 `1.0` |

canonical 採右手座標系，`+X` 為右方、`+Y` 為上方、`+Z` 為機頭／人物面向。固定轉換
如下；`(Xc, Yc, Zc)` 對來源 `(Xs, Ys, Zs)`，所有矩陣行列式均為 `+1`。六個已校正模型
使用本機工具儲存結果；`target_building` 的方向欄位尚未確認，矩陣暫保留既有值：

| `asset_id` | 來源上方 | 來源前方 | 固定轉換 `(Xc, Yc, Zc)` |
|---|---|---|---|
| `aircraft_normal` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `aircraft_manpower_support` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `aircraft_fast` | `+Z` | `-X` | `(-Ys, Zs, -Xs)` |
| `aircraft_boss` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `crew_normal` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `crew_boss` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `target_building` | 未確認 | 未確認 | `(-Xs, Zs, Ys)`（暫保留） |

轉換器套用矩陣、移至包絡中心並重新計算法線；runtime 使用
`uniform_scale = min(target_extent_i / source_extent_i) × visual_scale_multiplier`。
固定 target extent 為一般
飛機 `(1.6, 0.45, 2.8)`、Boss 飛機 `(1.9, 0.60, 3.2)`、一般人物 `(0.65, 1.8, 0.65)`、
Boss 人物 `(0.9, 2.4, 0.9)`、目標大樓 `(10, 12, 9)`。飛機以包絡中心對齊飛行位置，
人物與大樓以可見包絡底面對齊既有地面；可見模型放大不改變基準 box 碰撞包絡，
fallback 不套用可見模型放大倍率。`scene.py` 對成功載入的地面人物以
`aim_collider_multiplier=5.0` 建立與可見 OBJ 相同世界包絡的中央準心 box；fallback
使用 unit local box 配合 fallback 的 `target_extent`，因此也與 fallback 外觀相同。此
Entity 包絡不參與傷害、射程或陸地自動防禦規則。來源任一包絡軸為零或非有限時不得計算比例，必須改用 fallback。

其中 `aircraft_normal`、`aircraft_manpower_support` 與 `aircraft_fast` 共用一般飛機
包絡，`crew_normal` 也供人力支援飛機產生的地面人物使用。

### 場景日照狀態

場景 adapter 持有一組不進入存檔的日照顯示狀態：

| 欄位 | 型別 | 語意 |
|---|---|---|
| `sun_light` | Ursina `DirectionalLight` | 暖色方向光與陰影投射來源 |
| `ambient_light` | Ursina `AmbientLight` | 低強度環境填光，避免背光面變成純黑 |
| `shadow_bounds` | 隱藏場景 Entity | 固定涵蓋地圖與飛行走廊的陰影捕捉範圍 |
| `lit_with_sun_specular_shader` | Ursina `Shader` | 漫反射、太陽高光與 shadow map 的共同材質 |

上述狀態只負責世界 Entity 的外觀；清理場景時可保留光源並重新套用固定 bounds，
不得被碰撞、命中、傷害或 Profile 序列化讀寫。

Ursina loader 的固定補償為 `L(x, y, z)=(-x, y, z)`：OBJ 寫出時使用
`v_obj=L(v_canonical)`、`vn_obj=L(n_canonical)`，並保留三角面索引順序，loader 讀回後
才得到 canonical 頂點、法線與繞序。若反向索引，幾何繞序會與顯式法線相反；此補償由
轉換器負責，不屬於 `RuntimeAssetChoice`
或任何 runtime rotation。

必要映射如下：

| `asset_id` | 遊戲物件 | STL → OBJ |
|---|---|---|
| `aircraft_normal` | `AircraftType.NORMAL` | `普通飛行.stl` → `aircraft_normal.obj` |
| `aircraft_manpower_support` | `AircraftType.MANPOWER_SUPPORT` | `多人飛機.stl` → `aircraft_manpower_support.obj` |
| `aircraft_fast` | `AircraftType.FAST` | `速度飛行.stl` → `aircraft_fast.obj` |
| `aircraft_boss` | `AircraftType.ARMORED_BOSS` | `魔王飛行.stl` → `aircraft_boss.obj` |
| `crew_normal` | 非 Boss 地面人物 | `普通陸地.stl` → `crew_normal.obj` |
| `crew_boss` | Boss 地面人物 | `魔王陸地.stl` → `crew_boss.obj` |
| `target_building` | `TargetBuilding` | `大樓.stl` → `target_building.obj` |

### `AssetConversionResult`

轉換器對每一個 `AssetSpec` 回報一筆結果，不因其他資產失敗而短路。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `asset_id` | 字串 | 對應 manifest 項目 |
| `source_path`／`output_path` | 路徑 | 實際輸入與輸出位置 |
| `status` | `converted`／`skipped`／`failed` | 缺檔、無有效三角面或不可解析時為 `failed` |
| `vertex_count` | 非負整數 | 輸出有效頂點數；成功時大於 0 |
| `triangle_count` | 非負整數 | 移除退化面後的有效三角面數；成功時大於 0 |
| `error` | 可選字串 | 失敗原因；使用者可讀且不包含堆疊追蹤 |

轉換成功的必要條件是：所有座標為有限數、三角面面積大於退化門檻、輸出可被 OBJ
讀取器解析，且經 `L` 補償後仍符合 Y-up／+Z-forward 並保留 canonical 繞序。輸出不依賴
MTL 或貼圖。

## 武器準心與白框

### `AircraftScreenTarget`

由 `air_defense/scene.py` 每幀產生、交給規則層的暫時投影資料；它不是新的敵機實體，
也不寫入存檔。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `target_id` | 穩定字串 | 對應目前存在的 `Aircraft.id` |
| `visible` | 布林值 | 通過場景可見性／視線檢查才為真 |
| `screen_position` | 像素座標或 HUD 座標 | 由目前相機投影產生 |
| `in_lock_frame` | 布林值 | 投影位置位於指定武器的白框內 |
| `alive` | 布林值 | 目標仍存在且未被摧毀 |
| `eligible` | 布林值 | 目前類別與武器規則允許被鎖定 |

### `MultiLockView`

由 `MultiLockSet` 與 `AircraftScreenTarget` 組合出的唯讀 HUD view；
`air_defense/hud.py` 只消費它，不自行保存第二份鎖定進度。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `target_id` | 穩定字串 | 與來源 `AircraftScreenTarget` 相同 |
| `screen_position` | 像素座標或 HUD 座標 | 對應該目標目前投影位置 |
| `progress` | `[0, 1]` 浮點數 | 直接反映該 ID 的 `LockOnTracker` 進度 |
| `state` | `WHITE`／`RED_TRACKING`／`GREEN_READY` | 由目前可見性、框內狀態與進度推導 |
| `visible` | 布林值 | 為假時 HUD 不顯示小準心 |
| `fireable` | 布林值 | 只有仍存在、可見、框內、合法且 READY 時為真 |

### `ReticleState`

HUD 的暫時顯示狀態，不保存至 `RunState` 或 JSON。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `weapon` | `WeaponKind?` | 目前武器；RPG 與手槍各自使用相同外觀規格 |
| `family` | `normal_crosshair`／`single_aa`／`multi_aa`／`sniper`／`none` | 同一時間只能顯示一個武器家族 |
| `visible` | 布林值 | 只在可使用的戰鬥階段顯示 |
| `scope_enabled` | 布林值 | 只有防空炮或狙擊槍的對應瞄準模式可為真 |
| `whitebox_size` | 正浮點數 | 普通防空炮使用升級後尺寸；多目標使用其 2.0 倍 |

RPG 不開啟狙擊鏡或防空鎖定 UI；它與手槍共用十字準心的視覺規格，但以獨立的
武器選擇條件顯示。切換武器、關閉瞄準、離開戰鬥與終止狀態都會清除上一個家族。

防空介面偏好只存在目前程式啟動期間：

| 模式 | 普通防空炮 HUD | 多目標防空炮 HUD |
|---|---|---|
| `NEW` | 固定白框與新版動態鎖定準心 | 2 倍白框與每目標小準心 |
| `LEGACY` | 原始 003 的較大固定框、連續跟隨圓圈、進度條與狀態文字；圓圈半徑由取得範圍依進度縮至目標外框 | 仍使用新版多目標小準心，不建立單一圓圈 |

舊版圓圈不是第二份鎖定資料；它直接消費同一個 `LockOnTracker` 的進度、目標投影與
狀態，並在無目標、關閉瞄準或生命週期清理時隱藏。

## 多目標鎖定

### `MultiLockTargetState`

每架目前有效敵機各有一筆狀態。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `target_id` | 唯一字串 | 必須對應目前仍存在的 `Aircraft.id` |
| `visible` | 布林值 | 由場景投影／視線結果提供 |
| `in_lock_frame` | 布林值 | 投影位置在當前多目標白框內 |
| `screen_position` | 像素座標或 HUD 座標 | 用於小準心位置 |
| `progress` | `[0, 1]` 浮點數 | 由該 ID 專屬 `LockOnTracker` 更新 |
| `state` | `WHITE`／`RED_TRACKING`／`GREEN_READY` | 與進度及可射擊條件一致 |
| `fireable` | 布林值 | 必須同時滿足 scope、visible、in-frame、READY 與目標仍存活 |

### `MultiLockSet`

`MultiLockOnTracker` 的暫時聚合狀態。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `targets` | 穩定順序的 ID 清單 | 去重但不截斷；數量只受目前有效投影數量限制 |
| `trackers` | `dict[target_id, LockOnTracker]` | 每個 ID 獨立累積與衰減 |
| `scope_enabled` | 布林值 | 關閉時清空整個集合 |
| `all_targets_ready` | 計算值 | `targets` 非空且每筆狀態都可射擊；空集合永遠為假 |
| `fireable_target_ids` | ID tuple | 只有 `all_targets_ready` 時才回傳完整當次快照，否則回傳空 tuple |

狀態更新順序固定為：

1. 讀取所有目前存在、可投影的敵機 ID。
2. 白框內的新 ID 加入；已在集合的 ID 保留自己的 tracker。
3. 離開白框但仍可見的 ID 執行既有衰減；歸零後移除。
4. 不可見、死亡、撞樓或不存在的 ID 立即移除。
5. 只有所有剩餘 ID 都是 `GREEN_READY` 且仍在框內時，才形成可射擊快照。

為保留既有呼叫端的 source compatibility，`MultiLockOnTracker` 可繼續接受舊的
`target_capacity` keyword 參數；參數值只被忽略並不得進入 `MultiLockSet`、HUD、白框
或齊射驗證。新程式碼不得以該參數表達目標上限，測試必須以 10 個以上目標證明它不會
截斷集合。

## 導彈齊射

### `MissileVolley`

一次多目標射擊的暫時事件，沿用既有 `GuidedMissile` 實體。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `volley_id` | 唯一字串 | 同一按鍵事件只產生一個齊射識別 |
| `weapon` | `MULTI_ANTI_AIRCRAFT` | 不與普通防空炮的單發事件混淆 |
| `target_ids` | 唯一 ID tuple | 是射擊前重新驗證的完整快照，N 可大於 6 |
| `missile_ids` | 不可變 `(target_id, missile_id)` tuple | 一個有效目標恰好一枚導彈，建立後不改寫對應關係 |
| `cooldown_applied` | 布林值 | 整次齊射只設定一次武器冷卻 |
| `active` | 計算值 | 任一導彈仍存在時為真；每枚導彈獨立命中、過期或清除 |

`MissileVolley` 是 `air_defense/rules.py` 中的 frozen 純資料物件，由
`air_defense/main.py` 在射擊前重新驗證後建立；`main.py` 接著依 `target_ids` 一一建立
`GuidedMissile`，把每枚實體的 ID 填入 `missile_ids`，並只在整批建立成功後將
`cooldown_applied` 設為真。齊射建立前必須重新驗證 `target_ids` 全部存在、存活、可見、
在白框內且屬於飛機；任何一個失效都不建立任何導彈。建立後，每枚
`GuidedMissile.target_aircraft_id` 固定不變；目標死亡或導彈失效只移除該枚導彈，不轉移
給其他敵機。此事件只存在於當次戰鬥記憶體，不寫入存檔。

## 升級與持久化

### `WhiteboxDimensions`

由 `config.AA_LOCK_FRAME_SIZE`、`effective_whitebox_scale(profile)` 與多目標倍率共同
計算，不是一份新的永久資料。

| 武器 | 尺寸公式 |
|---|---|
| 普通防空炮 | `AA_LOCK_FRAME_SIZE × effective_whitebox_scale` |
| 多目標防空炮 | `普通防空炮尺寸 × AA_MULTI_LOCK_FRAME_MULTIPLIER`（`2.0`） |

`SaveProfile.upgrade_levels["aa_whitebox"]` 是唯一有效的白框升級來源。舊的
`multi_anti_aircraft_targets` 可在 schema 1 讀取與保留，避免舊存檔失效，但不得進入
商店目錄、HUD 顯示、白框計算或 `MultiLockSet` 目標數判定。鎖定集合、準心與齊射不會
寫入存檔。

## 生命週期不變量

- 普通防空炮只使用單一 `LockOnTracker`；多目標防空炮只使用自己的 `MultiLockSet`，兩者不共享進度。
- 沒有有效目標時，多目標永遠不可射擊，也不會建立空齊射。
- 射擊成功後多目標鎖定集合清空，下一次齊射必須重新取得所有目前有效目標的完整鎖定。
- `main.py` 的每幀流程先更新飛機與既有導彈，再更新投影／鎖定／HUD；終止、切換武器、波次、game over、回選單與重新開始都清除暫時集合。
- 既有 `GuidedMissile` 的 swept collision、命中優先於過期、一次傷害與 stale target 清理規則保持不變。
- 缺少或損壞的 OBJ 只影響該模型的 `RuntimeAssetChoice`，不影響其他模型或純規則狀態。

## 補充：RPG 與陸地自動防禦射擊效果／平衡資料

### `RPGProjectileEffect`

短暫、非持久化且不持有傷害權責的視覺資料。`id` 必須在一次遊戲執行中唯一；
`start_position` 來自玩家視角附近，`target_position` 是合法 RPG 爆炸中心；
`travel_progress` 由 0 到 1 推進，`remaining_seconds` 歸零時清除。固定
`visual_color=GREEN_RGB`，以長方體尺寸建立 cube，並以目標方向對齊長軸。

### `GroundTracerEffect`（陸地自動防禦來源）

自動防禦發射沿用既有敵方地面攻擊的曳光資料模型，使用黃色、短生命週期與
`start_position=turret.position`、`target_position=crew.position`。射擊序號併入
`id`，確保同一砲台連續發射不覆蓋錯誤事件；效果過期只移除視覺，不重新結算傷害。

### 陸地自動防禦平衡欄位

| 欄位 | 預設 | 規則 |
|---|---:|---|
| `AUTO_DEFENSE_MAX_RANGE` | `32.0` | 3D 距離包含邊界；超過即不可選取 |
| `auto_defense_damage` | `1` | 每發對一般地面敵人造成 1 點 |
| 一般生成非 Boss 地面敵人 HP | `3` | 三發自動防禦命中後擊倒 |
| `GROUND_BOSS_HEALTH` | `10` | 自動防禦最多打到剩餘 5 HP |
| `auto_defense_cooldown_seconds` | `0.20` | 與 `PISTOL_FIRE_COOLDOWN_SECONDS` 相同；可受既有升級倍率影響 |

006 版的 `auto_defense_ammo_per_sublevel` 欄位只為舊呼叫端／資料快照保留，007 的
陸地自動防禦不讀取它，也沒有有限彈藥池；目前規則以本表與 `spec.md` FR-025～FR-028
為準。

Boss 的 50% 是自動防禦累計傷害上限，而不是把玩家武器的傷害限制為 50%；
達到下限後，Boss 從自動防禦候選集合移除，玩家仍可正常攻擊。
