# 本機資產轉換契約：3D 資產與武器瞄準整合

## 轉換命令

從專案根目錄執行：

```powershell
python tools/convert_stl_assets.py
python tools/convert_stl_assets.py --check
```

可用參數：

| 參數 | 預設 | 說明 |
|---|---|---|
| `--source-root` | `遊戲3d` | 七個原始 STL 的本機目錄 |
| `--output-root` | `assets/air_defense/models` | 產生 OBJ 的本機目錄 |
| `--check` | 關閉 | 不寫檔，只驗證所有指定輸入／輸出與 OBJ 幾何 |

命令會逐項輸出 `asset_id`、來源、產物、頂點數、三角面數與狀態。所有項目成功時回傳
0；單一或多個資產無法解析、沒有有效面或輸出驗證失敗時仍完成其他項目，但回傳 1；
參數錯誤回傳 2。遊戲啟動不要求先執行此命令。

## 固定映射與座標

| `asset_id` | 輸入 | 輸出 | 執行時角色 | canonical 方向 |
|---|---|---|---|---|
| `aircraft_normal` | `普通飛行.stl` | `aircraft_normal.obj` | 普通飛機 | Y-up、機頭 +Z |
| `aircraft_manpower_support` | `多人飛機.stl` | `aircraft_manpower_support.obj` | 人力支援飛機 | Y-up、機頭 +Z |
| `aircraft_fast` | `速度飛行.stl` | `aircraft_fast.obj` | 快速飛機 | Y-up、機頭 +Z |
| `aircraft_boss` | `魔王飛行.stl` | `aircraft_boss.obj` | Boss 飛機 | Y-up、機頭 +Z |
| `crew_normal` | `普通陸地.stl` | `crew_normal.obj` | 一般人物與人力支援掉落人物 | Y-up、人物面向 +Z |
| `crew_boss` | `魔王陸地.stl` | `crew_boss.obj` | 地面 Boss | Y-up、人物面向 +Z |
| `target_building` | `大樓.stl` | `target_building.obj` | 目標大樓 | Y-up、正面 +Z、底部落地 |

canonical 使用右手座標系：`+X` 為右方、`+Y` 為上方、`+Z` 為機頭／人物面向。
每一列的來源軸排列／符號轉換是 manifest 中的固定 signed-permutation，只在轉換階段
執行；下表的 `(Xc, Yc, Zc)` 對來源 `(Xs, Ys, Zs)` 是唯一允許的矩陣語意。所有矩陣
行列式均為 `+1`，因此不翻轉三角面繞序。轉換器必須處理 Ursina OBJ 讀取器的 X 軸
慣例後再驗收結果；遊戲執行時不得新增個別模型旋轉角度，也不得依模型外觀臨時推測
另一組矩陣。下表六個飛機／人物列來自已儲存的人工校正結果；大樓列尚未人工確認，
目前只暫保留既有 manifest 矩陣。

| `asset_id` | 來源上方 | 來源前方 | 固定轉換 `(Xc, Yc, Zc)` |
|---|---|---|---|
| `aircraft_normal` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `aircraft_manpower_support` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `aircraft_fast` | `+Z` | `-X` | `(-Ys, Zs, -Xs)` |
| `aircraft_boss` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `crew_normal` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `crew_boss` | `+Z` | `-Y` | `(Xs, Zs, -Ys)` |
| `target_building` | 未確認 | 未確認 | `(-Xs, Zs, Ys)`（暫保留） |

Ursina 8.3.0 的 OBJ loader 會將讀入的頂點與法線套用
`L(x, y, z) = (-x, y, z)`。因此轉換器先得到 canonical 頂點 `C`，再在 OBJ 檔案中
寫入 `v_obj = L(C)`、`vn_obj = L(N)`，並保留 canonical 的三角面索引順序；loader
還原後的位置、法線與繞序才會回到 canonical 結果。若再反向索引，loader 還原後會
讓幾何繞序與顯式法線相反，造成背面剔除與日照方向錯誤。這是唯一的 loader 補償，
不能在 `scene.py` 再疊加反射或旋轉。

轉換器在套用固定矩陣及 Ursina X 軸 loader 補償後，將幾何移至包絡中心並重新計算法線。
runtime 再依下列既有程序化 fallback 包絡計算單一均勻縮放：
`uniform_scale = min(target_extent_i / source_extent_i) × visual_scale_multiplier`。
`visual_scale_multiplier` 只放大可見 OBJ；場景以反向倍率重建簡化 `box` 基準碰撞器，因此
可見模型不得直接改變既有 gameplay 基準包絡。飛機以包絡中心對齊飛行位置；人物與大樓以
可見包絡底面對齊既有地面。成功載入的地面人物另以 manifest 的
`aim_collider_multiplier=5.0` 建立與可見 OBJ 相同大小的中央準心射線 Entity box；
此瞄準包絡不改變武器規則。來源任一軸為零、非有限或無法套用矩陣時，轉換結果為
`failed`，場景改用該類型 fallback。程序化 fallback 不套用可見模型放大倍率，並使用
unit local box 讓瞄準包絡與 fallback 外觀相同。

目前新版飛機／大樓外部模型的固定可見倍率為 `10.0`，陸地型態敵人為 `5.0`。倍率只
作用於成功載入的 OBJ；程序化 fallback 維持原本大小。scene 仍以反向倍率重建 box，
因此陸地模型的基準 gameplay 碰撞箱仍維持既有 target extent；地面人物的中央準心瞄準
取得 box 則與成功載入的可見模型包絡相同，fallback 則與 fallback 外觀相同。世界中的
自動防禦射程、傷害與選取規則不變。

| 角色 | runtime target extent | aim collider multiplier |
|---|---|---:|
| 一般飛機 | `(1.6, 0.45, 2.8)` | `1.0` |
| Boss 飛機 | `(1.9, 0.60, 3.2)` | `1.0` |
| 一般人物 | `(0.65, 1.8, 0.65)` | `5.0`（與外部可見倍率相同） |
| Boss 人物 | `(0.9, 2.4, 0.9)` | `5.0`（與外部可見倍率相同） |
| 目標大樓 | `(10, 12, 9)` | `1.0` |

`aircraft_normal`、`aircraft_manpower_support` 與 `aircraft_fast` 使用一般飛機包絡；
`crew_normal` 也供人力支援飛機產生的地面人物使用。

若人工無法確認來源模型的前方／上方，可執行 `python tools/mark_asset_forward.py` 開啟
來源 STL 校正檢視器。它以「前／後／左／右／上／下」六條具名方向線標示來源軸，並輸出本機 ignored 的
`assets/air_defense/models/asset_axis_calibration.json`，包含每個模型選定的來源前方、
來源上方與可直接核對的 `source_to_canonical` 矩陣；校正結果確認後才更新 manifest。

人工判定規則：有螺旋槳的飛機以螺旋槳／機鼻側為來源前方；人物以腳到頭為來源上方，
以有臉的一側為來源前方。這只用於校正工具的來源軸選擇，不能在 runtime 以模型名稱
或外觀臨時追加旋轉。

OBJ 不要求 MTL、貼圖或內嵌材質色，顏色由遊戲物件類型提供。

## 場景光照與視覺材質

外部 OBJ 與主要場景幾何使用 `air_defense/lighting.py` 的統一日照 shader。場景建立一盞
暖色 `DirectionalLight`、低強度 `AmbientLight` 與涵蓋整條地圖／飛行走廊的固定陰影捕捉
範圍；shader 提供漫反射、受控 Blinn-Phong 太陽高光與陰影映射。這些設定只影響可見
明暗與輪廓，不改寫 asset ID、類型色、方向、box 碰撞或任何武器規則。陰影捕捉範圍不
依當下波次重新縮小，確保後續生成的飛機仍能在地面留下陰影。

方向校正器的視覺線標籤使用：`前(+Z)`、`後(-Z)`、`右(+X)`、`左(-X)`、`上(+Y)`、
`下(-Y)`。鍵盤選軸仍維持 `1`～`6` 的 signed-axis 輸入，輸出的 manifest 矩陣格式不變。

## 幾何與失敗契約

- 支援目前來源使用的 binary STL，並保留 ASCII STL 的解析能力以利後續替換來源。
- 移除非有限頂點與退化三角面；沒有有效三角面時該項目為 `failed`。
- 每個成功 OBJ 至少含一個有效頂點與三角面，且可被 Ursina 8.3.0 的 OBJ loader 建立。
- 單一來源失敗不得刪除或阻止其他成功產物；遊戲對缺少／損壞產物使用程序化 fallback。
- `遊戲3d/*.stl` 與 `assets/air_defense/models/*.obj` 維持本機忽略／未追蹤狀態，不加入
  版本庫；可重複執行命令覆寫對應本機產物。
