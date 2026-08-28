# 快速驗證：3D 資產與武器瞄準整合

## 前置條件

- Windows 桌面環境、Python 3.12 以上（本次基線為 Python 3.13.5）。
- 專案根目錄：`C:\Users\lamun\OneDrive\Desktop\pythonSDD`。
- 遊戲依賴：`ursina==8.3.0`。本功能不新增第三方依賴。
- 原始 STL 為本機資產；沒有 STL 或產出的 OBJ 仍應可啟動遊戲並使用程序化 fallback。
- 若要看到新飛機／人物／大樓，必須先在啟動遊戲前執行一次 STL→OBJ 轉換；若遊戲已經
  開啟才完成轉換，請關閉並重新啟動遊戲，讓場景重新建立模型 Entity。

確認目前不在 `main`：

```powershell
git branch --show-current
```

預期必須為 `007-3d-assets-weapon-targeting`；若不是此分支，先停止，不得進行本功能修改。

本功能的 feature directory／`.specify/feature.json` 由
`.specify/scripts/powershell/create-new-feature.ps1` 建立；本 repo 腳本不直接建立 Git
branch，因此分支轉換另以 `git switch -c 007-3d-assets-weapon-targeting` 完成，以保留
原有 dirty worktree。進入任何實作任務前都要重新執行上面的 branch 檢查；若結果是
`main`，先停止，不得修改功能程式。

方向與比例的可執行來源是 [contracts/assets.md](contracts/assets.md)：canonical 為右手
座標 `+X` 右、`+Y` 上、`+Z` 機頭／人物面向，轉換器只能使用該契約的固定 signed-
permutation，不能在 runtime 增加模型專屬旋轉。OBJ 載入後以
`uniform_scale = min(target_extent_i / source_extent_i) × visual_scale_multiplier` 保留比例；
新版飛機／大樓外部模型可見倍率為 `10.0`、陸地型態敵人為 `5.0`，且場景用反向倍率維持原 box
基準包絡；一般／Boss 地面人物的中央準心瞄準 box 與陸地敵人的可見模型包絡相同，
fallback 則與 fallback 外觀相同，
不改變射程、傷害或自動防禦選取。一般／Boss 飛機、
一般／Boss 人物、大樓的 target extent 分別為 `(1.6,0.45,2.8)`、`(1.9,0.60,3.2)`、
`(0.65,1.8,0.65)`、`(0.9,2.4,0.9)`、`(10,12,9)`。飛機中心對齊飛行位置，人物與大樓
底面對齊地面；飛機／大樓碰撞仍為既有 `box` 基準包絡，人物使用較大的瞄準取得 box。

## 安裝與資產轉換

```powershell
Set-Location 'C:\Users\lamun\OneDrive\Desktop\pythonSDD'
python -m pip install -r requirements-game.txt
python tools/convert_stl_assets.py
python tools/convert_stl_assets.py --check
```

預期七個 `asset_id` 都回報成功，且 `--check` 回傳 0。若某一個 STL 缺少或損壞，
其他項目仍會完成；命令會回傳 1 並列出失敗原因，遊戲仍可進入戰鬥。產物應出現在
`assets/air_defense/models/`，但不應出現在版本庫的追蹤清單中。遊戲場景會以 OBJ 的
檔名 stem 加上產物所在資料夾呼叫 Ursina loader；不要把絕對 Windows 路徑直接當成
`Entity(model=...)` 的模型名，否則 Ursina 會找不到模型並回退或留下空 Entity。

若任一模型方向仍不確定，先執行下列校正工具；它不會旋轉或覆寫 STL：

```powershell
python tools/mark_asset_forward.py
```

目前已儲存並同步六個飛機／人物模型的校正結果；`target_building` 尚未標記，仍使用
既有暫定矩陣，完成大樓校正後才可更新該列。

工具的預設來源與輸出會自動以專案根目錄定位，因此也可以從 `tools` 資料夾啟動：

```powershell
Set-Location 'C:\Users\lamun\OneDrive\Desktop\pythonSDD\tools'
python -u .\mark_asset_forward.py
```

不要把檔名寫成 `mark\_asset\_forward.py`；實際檔名是 `mark_asset_forward.py`。工具會優先
使用 Windows 的繁中字型，若畫面仍顯示方框，請改用 `--source-root` 指定正確的 `遊戲3d`
資料夾並確認系統已安裝 `NotoSansTC-VF.ttf` 或 `kaiu.ttf`。

檢視器以六條具名方向線表示前(+Z)、後(-Z)、右(+X)、左(-X)、上(+Y)、下(-Y)；
飛機以螺旋槳／機鼻側作為黃色前方箭頭，人物以有臉的一側作為黃色前方箭頭、腳到頭作為青色向上箭頭。按 `F` 選前方、`U` 選上方，
再按 `1`～`6` 選正負軸，`Enter` 確認目前模型，
`N`／`P` 切換模型，`R` 重設，`Esc` 儲存離開。結果寫入被忽略的
`assets/air_defense/models/asset_axis_calibration.json`；確認 JSON 後才更新 manifest
並重新執行轉換器。

## 自動化驗證

```powershell
python -m compileall -q air_defense tests tools
python -m unittest discover -s tests -p "test_*.py" -v
```

必須包含並通過下列類型的案例：

- 七個來源／用途映射、binary／ASCII STL、退化面清理、Y-up／+Z-forward 與缺檔 fallback。
- RPG 12.0 內含邊界、超過 12.0、飛機目標、無彈藥與冷卻拒絕；拒絕時資源保持不變。
- 多目標同時 10 架以上、每 ID 獨立進度、離框衰減、死亡移除、部分鎖定不發射與全數鎖定閘門。
- N 個有效目標只建立 N 枚導引導彈、每枚保存固定目標 ID、命中／過期／stale target 清理互不污染。
- 普通／多目標白框升級共用、尺寸比例固定 2.0，以及舊固定目標升級不出現在有效商店規則。
- 準心互斥、武器切換、scope 關閉、波次、game over、返回選單與重新開始的清理。
- 主選單「設定」的新版／舊版選擇；舊版普通防空炮恢復原始 003 的固定框、連續縮小
  跟隨圓圈、進度條與狀態顏色，多目標仍使用新版小準心。
- 外部 OBJ 的可見倍率、每個實例的顏色隔離、反向 box 基準碰撞包絡、人物與可見模型相同大小的瞄準 box、六向方向線與日照／高光／陰影 shader。
- 四種飛機由實際 Ursina Entity 載入各自的 OBJ，而不是只通過純 parser 檢查。

## 啟動遊戲

```powershell
python -m air_defense.main
```

選擇或建立 Profile 後開始小關。若要驗證資產 fallback，可先以
`--output-root` 指向一個空的暫存目錄執行 `--check`，或在不刪除原始檔的前提下使用
空輸出目錄啟動；不要把本機原始 STL 或 OBJ 加入版本庫。

## 分階段驗證門檻

每一個 checkpoint 都必須先完成語法檢查，再做對應 smoke，通過後才可開始下一階段：

| 任務 | 必要驗證 |
|---|---|
| T004 | `compileall`；既有遊戲 scope／換武器／波次／終止／重新開始清理，且已發射導彈不被 UI 清理取消 |
| T009 | `compileall`；七類模型映射、方向、中心／底面錨點、單項 fallback |
| T016 | `compileall`；RPG 與手槍準心一致、與其他 UI 互斥、12.0 邊界 |
| T025 | `compileall`；10+ 目標小準心／獨立進度、全數 READY 齊射與導彈隔離 |
| T032 | `compileall`；普通／多目標白框升級與存檔重載，比例維持 2.0 |
| T033 | `specs/007-3d-assets-weapon-targeting/quickstart.md`；同步 US1～US4 的啟動與驗證入口 |
| T034 | `compileall`／完整 `unittest`；US1～US4 回歸結果 |
| T035 | `air_defense/main.py:create_application()`；第一波、四種飛機 OBJ 與目標大樓的 Ursina 建立 smoke |
| T036 | `air_defense/`、`tests/` 與 `day1/`／`day2/`；範圍、清理、重複規則與除錯輸出審查 |
| T043 | `compileall`／完整 `unittest`；RPG 綠色長方體、自動防禦曳光與平衡邊界 |
| T052 | `compileall`／完整 `unittest`／轉換器 `--check`／方向工具 `--help`；舊版 HUD 與方向校正入口 |
| T067 | `unittest`；外部陸地 OBJ 的瞄準 box 與可見模型包絡一致，fallback 瞄準 box 與 fallback 外觀一致 |

若任一 checkpoint 失敗，先修正並重跑該 checkpoint；不能用後續完整測試取代未通過的
手動驗證。

## 手動驗收流程

1. 建立含七個 OBJ 的輸出後重新啟動遊戲並開始戰鬥，依序觀察普通、人力支援、快速與 Boss 飛機，
   以及一般人物、地面 Boss 與目標大樓。確認模型映射正確、人物站立並面向行走方向，
   大樓落地，飛機沿飛行方向前進且機頭朝向一致；確認顏色為紅／橙／藍／紫／藍灰。
2. 將其中一個 OBJ 暫時移出輸出目錄並重新啟動，確認只有該類型回到程序化外觀，
   其他模型與遊戲流程不受影響。關閉或恢復檔案後再執行一次轉換器。
3. 在混合或地面戰鬥按 `4` 選 RPG，確認畫面中央顯示與手槍相同的十字準心，且不顯示
    狙擊鏡或防空鎖定框。以距離 12.0 的地面敵人測試可射擊；將目標移到略大於 12.0
    測試，確認不扣彈、不進冷卻、不造成傷害。將準心落在人物可見身體邊緣，確認較大的
    與人物可見外觀相同大小的瞄準 box 能取得人物；將中心瞄準飛機，確認 RPG 不接受飛機。
4. 解鎖並按 `5` 選多目標防空炮，開啟右鍵瞄準。確認白框邊長是普通防空炮目前白框
   的 2.0 倍；白框內每架可見敵機都有自己的小準心與進度，不顯示「最多 2／6」容量。
5. 讓至少 10 架敵機同時在多目標白框內。確認所有 ID 都被追蹤；讓其中一架短暫離框，
   確認只有該架進度衰減；摧毀另一架，確認其小準心立即移除且不阻塞齊射。
6. 只完成部分鎖定時按左鍵，確認沒有導彈、沒有冷卻。待目前所有有效小準心變綠後
   按左鍵，確認同一時刻建立 N 枚導引導彈，N 等於當次有效目標數，且每枚導彈追蹤
   自己的目標；某一枚命中或目標死亡時，其他導彈不得換鎖。
7. 購買一級以上「防空炮白框大小」，離開戰鬥再重新進入普通與多目標瞄準模式，
   確認兩者都保留升級且比例仍為 2.0。確認商店不再把舊的多目標固定數量升級列為有效項目。
8. 在主選單按「設定」，先選「新版防空瞄準」並返回；再選「舊版圓圈鎖定」重新進入戰鬥。
   舊版普通防空炮按右鍵後，確認 55° 防空視野、較大固定框、連續圓圈、3 秒進度條／
   百分比與可發射狀態都出現；圓圈應從大範圍隨進度縮小到飛機外框，且不出現新版普通
   動態小準心。切到多目標防空炮時，仍應使用新版 2 倍白框與多個小準心。
9. 關閉瞄準、切換手槍／RPG／狙擊槍、進入下一波、觸發 game over、返回選單與重新開始，
   確認準心、白框、所有小準心與鎖定進度沒有殘留；瞄準關閉後已發射導彈仍可完成命中
   或過期，終止狀態則全部清除。
10. 在混合／地面戰鬥選 RPG 射擊合法目標，確認從玩家視角附近飛出綠色長方體子彈，
   沿目標方向短暫移動後清除，且同一發沒有重複爆炸傷害。
11. 解鎖陸地自動防禦後觀察砲台外觀；讓落地敵人在 32.0 世界單位內，確認每次開火
    有與敵方相同的黃色曳光效果。確認一般生成非 Boss 敵人需三發自動防禦子彈擊倒，
    Boss 最多只被自動防禦打至剩 50% 生命，超出 32.0 的敵人不會被鎖定。
12. 比較自動防禦連續兩次開火間隔與手槍預設 CD；未升級應同為 0.20 秒，購買既有
    cooldown 升級後兩者仍由共用升級倍率推導。
13. 觀察外部飛機、人物與目標大樓的輪廓：正面受暖色方向光照亮，背光面應有明暗差，
    地面或鄰近物件應可看見投射陰影，模型表面應有小幅太陽高光；確認模型尺寸比原本
     更容易辨識；飛機／大樓射線與碰撞仍以原本簡化 box 基準包絡為準，人物則使用與其
     可見外觀相同大小的瞄準取得 box，且不影響武器與自動防禦規則。

## 效能記錄

在 1280×720、Profile `maximum_aircraft_count=5`（簡寫 `A=5`）的圖形環境中，暖機 5 秒後連續觀察 30 秒，記錄平均 FPS、最低 FPS、
作業系統、Python 版本、解析度與硬體摘要；場景至少包含 10 架多目標候選、目前導彈
與地面物件；A=5 不是多目標容量，10+ 候選使用受控／合成場景建立。目標為平均 FPS 至少 60。若只有無視窗環境，必須記錄「未量測」，不得
把 headless 測試結果宣稱為 FPS 通過。

## 基線與限制

本次進入規劃前的基線為 `python -m compileall -q air_defense tests` 成功，完整
`unittest` 套件 200 個測試通過；補充實作後目前為 218 個測試通過。使用者已回報新增
功能的人工驗收沒有問題；30 秒 FPS 數值仍須在圖形環境另行記錄。Ursina focus、字型、
遠端桌面與視窗環境警告若仍存在，應分別記錄而不是忽略。

## PR 交付紀錄（T059）

完成 T057／T058 後，T059 必須把實際 PR URL、`main` base、功能分支、對應的
`spec.md`／`plan.md`／`tasks.md`、測試／手動驗收結果與已知限制寫回本節；通過程式碼
審查前不得宣稱可合併。

## 補充需求驗收紀錄（RPG／陸地自動防禦）

本補充將一般生成非 Boss 地面敵人定義為 3 HP、自動防禦每發 1 點，Boss 維持 10 HP
且自動防禦累計最多造成 50% 最大生命值傷害；自動防禦射程為 32.0、未升級 CD 與
手槍預設 0.20 秒相同。RPG 綠色長方體與自動防禦黃色曳光均為短暫視覺效果，傷害
仍由既有純規則路徑負責。

實作完成後在此記錄：

- 使用者已回報人工功能驗收完成且沒有問題；本紀錄不代替 FPS 數值量測，也不虛構未提供的硬體資料。
- 新增／更新的自動化測試：`python -m unittest discover -s tests -p "test_*.py"`，218 tests
  通過；`python -m compileall -q air_defense tests tools` 通過。
- `python tools/convert_stl_assets.py --check` 回傳 0；七個本機 OBJ 均可解析，並以專案
  `create_application()`、`scene.build_world()` 與實際 Entity smoke 分別載入四種飛機、兩種
  人物及目標大樓，結果均為 `fallback_used=False`、`entity.model is not None`；飛機／大樓
  可見倍率為 `10.0`、陸地型態敵人為 `5.0`，大樓仍沿用既有方向矩陣。
- 純規則／生命週期測試已驗證 RPG 綠色長方體、自動防禦黃色曳光、32.0 邊界、普通敵人
  三發、Boss 50% 上限與 0.20 秒 CD。
- T067 已以 manifest 與 scene mock 驗證：外部陸地 OBJ 的瞄準 box 與可見模型包絡一致，
  fallback 的瞄準 box 與 fallback 外觀一致；不改變 RPG／手槍／狙擊槍射程、傷害或自動防禦規則。
- 舊版防空介面已恢復原始 003 的固定框／連續縮小跟隨圓圈，並與新版、多目標小準心
  保持互斥；圓圈的最終方向／比例仍需在可用圖形環境中依校正工具結果手動確認。
- 1280×720 圖形手動驗收已由使用者回報完成且沒有問題；30 秒平均／最低 FPS 數值仍未量測，
  不得以上述 headless／Entity smoke 代替 FPS 通過。啟動前請先轉換 OBJ，若遊戲已開啟則需
  重啟才會建立新模型。
