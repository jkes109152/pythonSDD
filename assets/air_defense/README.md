# 防空遊戲資產

原型遊戲以 Ursina 程序化幾何啟動，因此外部美術資產永遠不是啟動依賴。只有在記錄
來源、授權與再散布條件後，才可在此資料夾增加可選模型或貼圖。

## 核准資產政策

- 優先使用專案原創資產或明確採 CC0 授權的資產。
- 使用前記錄來源 URL、資產名稱、授權與本機檔名。
- 不得提交再散布權不明的資產。
- 每個可選模型都必須保留程序化幾何 fallback，讓快速驗證與自動化規則測試不需下載
  外部資產即可執行。

## 目前資產清單

下表描述版本庫追蹤的文件；`遊戲3d/` 下的 STL 輸入與 `models/` 下的 OBJ 產物都是
使用者本機的 ignored 檔案，刻意不列入追蹤清單。若本機已有轉換產物，遊戲會直接使用它們。

| 本機檔案 | 來源／授權 | 執行時用途 |
|---|---|---|
| `README.md` | 專案文件 | 記錄資產政策；遊戲不載入 |
| `遊戲3d/*.stl`（本機） | 使用者提供；未納入版本庫 | STL→OBJ 轉換輸入 |
| `models/*.obj`（本機） | 由本專案轉換器產生；未納入版本庫 | 飛機、人物與大樓的可選 runtime 模型 |

## 本機轉換與載入

在專案根目錄執行：

```powershell
python tools/convert_stl_assets.py
python tools/convert_stl_assets.py --check
python -m air_defense.main
```

若遊戲在轉換器之前已啟動，請關閉後重新啟動；場景建立時才會重新選擇 OBJ。scene
adapter 會以 OBJ 的 stem 與明確 parent folder 呼叫 Ursina loader，不會把 Windows 絕對
路徑當成模型名。缺少或損壞的單一 OBJ 仍只會讓該類型回到程序化 fallback。

## 本機 STL 轉 OBJ 契約

七個本機輸入由 `tools/convert_stl_assets.py` 轉換。canonical 採右手座標系：`+X` 為右方、
`+Y` 為上方、`+Z` 為機頭／人物面向。下表的六個飛機／人物映射已依本機校正工具儲存結果
更新；大樓的校正結果目前仍是空值，因此先保留既有 manifest 映射，不能視為已完成人工確認。
執行時不得新增模型專屬旋轉。

| 資產 ID | 本機 STL | 產生的 OBJ | 固定映射 `(Xc, Yc, Zc)` | runtime 包絡 |
|---|---|---|---|---|
| `aircraft_normal` | `普通飛行.stl` | `aircraft_normal.obj` | `(Xs, Zs, -Ys)` | `(1.6, 0.45, 2.8)` |
| `aircraft_manpower_support` | `多人飛機.stl` | `aircraft_manpower_support.obj` | `(Xs, Zs, -Ys)` | `(1.6, 0.45, 2.8)` |
| `aircraft_fast` | `速度飛行.stl` | `aircraft_fast.obj` | `(-Ys, Zs, -Xs)` | `(1.6, 0.45, 2.8)` |
| `aircraft_boss` | `魔王飛行.stl` | `aircraft_boss.obj` | `(Xs, Zs, -Ys)` | `(1.9, 0.60, 3.2)` |
| `crew_normal` | `普通陸地.stl` | `crew_normal.obj` | `(Xs, Zs, -Ys)` | `(0.65, 1.8, 0.65)` |
| `crew_boss` | `魔王陸地.stl` | `crew_boss.obj` | `(Xs, Zs, -Ys)` | `(0.9, 2.4, 0.9)` |
| `target_building` | `大樓.stl` | `target_building.obj` | `(-Xs, Zs, Ys)`（暫保留，待校正） | `(10, 12, 9)` |

轉換後 runtime 使用均勻比例
`min(target_extent_i / source_extent_i) × visual_scale_multiplier`，並保留既有簡化
`box` 碰撞器的基準世界包絡。放大倍率只作用於可見 OBJ，碰撞器會以反向倍率重建，避免
模型變大後改變射程或基準玩法包絡；一般／Boss 人物的中央準心瞄準 box 會與陸地型態敵人的
`5.0` 倍可見模型相同，讓中央準心瞄準箱覆蓋人物的完整外觀；程序化
fallback 則維持與 fallback 外觀相同的瞄準箱大小。此瞄準包絡不改變傷害、射程或自動防禦
選取規則。倍率目前
為飛機／大樓 `10.0` 倍、陸地型態敵人 `5.0` 倍。飛機以包絡中心對齊飛行位置；
人物與大樓以可見包絡底面對齊既有地面；人物以水平 yaw 面向實際行走方向，且不會因轉向翻到頭下腳上。缺少、無效、包絡軸為零或無法載入的 OBJ 只
影響該資產 ID，並回退到程序化幾何。

若無法從模型外觀判定來源前方／上方，執行
`python tools/mark_asset_forward.py`。工具會顯示未旋轉的 STL、前／後／左／右／上／下六條具名方向線與前方／
上方標記，將結果寫入本機 ignored 的
`assets/air_defense/models/asset_axis_calibration.json`；確認後再把結果更新回
`asset_manifest.py` 並重新執行轉換器。

目前校正檔已提供六個模型的完整資料；`target_building` 的 `source_forward`、`source_up`
與矩陣仍為空值，請勿在未確認前自行替換大樓方向。

校正時的判定語意固定為：有螺旋槳的飛機以螺旋槳／機鼻側為前方；人物以腳到頭的方向
為上方、以有臉的一側為前方。這些是人工校正來源軸的判定規則，不是在遊戲執行時猜測
或追加模型旋轉。

## 日照、反射與陰影

外部 OBJ 與主要世界幾何使用 `air_defense/lighting.py` 的統一日照 shader。遊戲建立暖色
方向光、低強度環境填光、受控太陽高光與固定涵蓋地圖／飛行走廊的陰影捕捉範圍，讓模型
不再只呈現一團平面類型色；這些設定只改變可見明暗與輪廓，不改變原本的基準 `box` 碰撞包絡。
人物瞄準 box 與陸地可見模型相同大小，是獨立的目標取得設定，不是光照或材質效果。

STL 是使用者提供的本機來源資料，本版本庫沒有記錄其再散布授權。STL 與產生的 OBJ 都
必須維持未追蹤狀態；不得提交它們，也不得宣稱未被文件記錄的授權。

HUD 可以使用 Windows 已安裝的繁體中文系統字型（`NotoSansTC-VF.ttf` 或 `kaiu.ttf`）；
本專案不再散布該字型，也不把它當作啟動依賴。若系統沒有這些字型，遊戲回退到 Ursina
內建字型，平台限制記錄於 `specs/001-air-defense-game/quickstart.md`。
