# Quickstart: 防空 HUD、動態鎖定與整波敵機

## Prerequisites

- Windows desktop、Python 3.12+（目前工作區以 Python 3.13 驗證）。
- 已安裝 `requirements-game.txt` 的既有依賴，尤其是 `ursina==8.3.0`。
- 在功能分支 `004-air-defense-hud-wave` 執行；本功能不需要網路、搖桿、存檔或新增外部資產。

## Automated checks

在 repository root `C:\Users\lamun\OneDrive\Desktop\pythonSDD` 執行：

```powershell
python -m compileall air_defense tests
python -m unittest discover -s tests -p "test_*.py" -v
```

實作後應新增／更新純規則測試，至少涵蓋：

- 多架飛機同時生成、各自 advance、部分擊落後仍維持空戰，以及全波完成的單次 transition。
- 可見／框內／距中心最近的 target selection、sticky target、矩形含邊界與準心 clamp。
- 3 秒累積、0.25 秒部分衰減、0.75 秒歸零、回框續鎖，以及衰減期間不可發射。
- 任一飛機撞城的全域 game over、重複 callback 去重、零 crew 直接進下一波。
- 三把武器各自的 cooldown fill ratio、切槍後互不污染、start／new wave／game-over／menu reset，以及 ground tracer 到期不產生傷害。

實作驗證紀錄（2026-08-27）：

- `python -m compileall air_defense tests` 通過。
- `python -m unittest discover -s tests -p "test_*.py" -q`：84 tests passed；包含原有導引飛彈、Boss、城市耐久、滑鼠輸入與新增 HUD／wave／lock／cooldown／tracer 測試，以及本次 code review 的 CD 邊界、準心顏色、動態物件清理、EncounterFactory 相容性與 game-over 卡片快照回歸測試。
- `git diff --check` 通過；`ruff` 未安裝，因此未宣稱 lint 結果。

## Local Ursina smoke check

先確認程式可建立 app，再啟動遊戲流程。若目前環境沒有可用顯示器，保留 compile／unit test 結果並在驗收紀錄說明原因。

```powershell
python -c "from air_defense.main import create_application; app, game = create_application(); game.start_game(); print(game.session.phase, game.session.wave.wave_number); app.userExit()"
```

預期：不因 HUD 建立、程序化 scope 視覺或多飛機 collection 產生 import／attribute error；`start_game()` 後進入 `AIRSTRIKE`，第一波的全部 aircraft entities 已存在。

已執行的 Ursina smoke evidence：

- app construction／`start_game()`：`AIRSTRIKE`、2 架 keyed aircraft、2 個 scene aircraft entities。
- 實際 update frame：同時得到 2 個 aircraft screen targets。
- HUD readability smoke：使用 `NotoSansTC-VF.ttf` 顯示繁中與圖示，狀態卡與 bar track／武器槽改為透明背景、主要文字為白色大字，右上可列出本波多種敵機與目前鎖定目標；狀態卡改以 viewport safe margin 動態定位，1280×720 與 800×600／600×720 resize 後卡片仍在 viewport 內，進度文字維持單行不溢出。
- 逐架擊落：部分擊落仍留在 `AIRSTRIKE`；全波擊落後只建立 `encounter:wave-1` aggregate encounter 並進入 `GROUND_COMBAT`。
- 清空地面 encounter：下一波一次生成 3 架 aircraft；ground tracer create／tick／expiry smoke 通過。
- game-over／return-to-menu／重新開局：三把武器 cooldown 歸零，重新進入 `AIRSTRIKE` 並生成 2 架 aircraft。
- Ursina 在此 Windows 環境會輸出 `SetForegroundWindow failed` 等非致命顯示器警告，但 construction、update 與 lifecycle smoke 均成功。

## Manual acceptance flow

### 1. Status cards

1. 啟動 `python -m air_defense.main`。
2. 開始遊戲，確認左上透明背景（可有白色輪廓）卡片顯示紅色 heart、`100 / 100`、紅色滿條，以及藍色 shield、城市耐久 100% 與藍色滿條。
3. 讓玩家與城市分別受傷，確認只有對應 row 的數值與比例下降；確認卡片沒有不透明底色、主要文字為白色大字；進入 game over 後兩張卡保留最後值。
4. 確認右上顯示 `第 N 波`、與 roster 等數的藍色 dots、`敵機進度：100%`、本波所有不重複 aircraft type（例如快速・普通・Boss）與 `鎖定：...` 目標列。
5. 擊落部分 aircraft，確認對應 dots 變灰、其餘 dots 與飛機仍活動，percentage 等於 alive／total；若數量超過一行，確認縮小或換行而不遮文字。若 aircraft 進入 `IMPACTED`，其 dot 也為灰色、不計入 alive ratio，並在 game-over 後凍結卡片。

### 2. Anti-air reticle and sticky lock

1. 取得防空炮並按右鍵開啟 scope；確認 white frame 的寬、高是舊值兩倍（目前目標 normalized size `0.210`），frame 在所有狀態維持白色。
2. 無 target 或 progress 0% 時，確認小準心在 frame 中心；把一架可見 aircraft 帶入 frame，確認小準心從中心向 aircraft projection 漸進，且不越過 frame。
3. 持續追蹤 3 秒，確認 progress 到 100%、小準心短暫紅閃後變綠、文字顯示完成；frame 仍為白色。
4. 讓 target 離開 frame 0.25 秒，確認 progress 保留部分值、reticle 停留在 frame 內且不能射擊；0.75 秒後歸零，再讓另一架進框確認可重新選取。
5. 在舊 target 衰減期間讓另一架進框，確認不跳鎖；原 target 回框時從剩餘 progress 繼續。
6. 確認 target 在 expanded 1.5× frame 內但原 frame 外時只得到每秒最多 3° 的 aim assist，超出範圍或 scope 關閉時停止。
7. 發射多枚 missile 追蹤不同 aircraft，確認指定 target 終止後不會轉而傷害其他 aircraft。

### 3. Whole-wave lifecycle

1. 在至少兩架的固定 wave 開始時截圖或觀察場景，確認全部 aircraft 同時以 horizontal formation 出現。
2. 摧毀其中一架，確認其他架仍前進、攻擊與可被選取；遊戲不提前切換 ground combat。
3. 摧毀全波 aircraft，確認所有地面 crew 在一個 encounter 中一次生成；若 factory 給出零 crew，確認直接進入下一波。
4. 清除 aggregate encounter，確認下一波的全部 aircraft 一次生成；重複撞擊 callback 不應重複生成 crew 或增加統計。
5. 讓任一 aircraft 抵達 city，確認立即 game over，其他 aircraft、missile、lock、ground encounter 與 HUD 動態更新停止。

### 4. Cooldown and sniper scope

1. 分別裝備防空炮、狙擊槍與手槍，確認準心正下方顯示各自 CD bar；ready 為滿格綠色。
2. 每把武器成功射擊後確認 bar 從空開始，按其個別 duration 填滿；切換武器時讀取新武器自己的 cooldown。
3. Ground combat 取得狙擊槍並按右鍵，確認 35° FOV、圓形瞄準視野、圓外深色遮罩、十字線與中央紅點；畫面不得出現棋盤格。
4. 關閉 scope、切槍、離開 ground phase 或 game over，確認 scope overlay 消失且不與其他準心重疊。

### 5. Ground attack feedback and performance

1. 讓一名或多名 ground enemy 進入可攻擊狀態，確認每次成功 attack 同步出現一條從敵人朝玩家的短暫黃色 elongated tracer；head 由 enemy 線性移向 player，tail 保持固定視覺長度，預設 lifetime 為 `0.18 s`。
2. 確認 tracer 到期後清除，不會額外造成 damage、重置 attack cooldown 或增加 enemy defeated 統計；同時攻擊可看見多條獨立 tracer。
3. 執行固定 SC-010 兩個子場景：空戰使用 `WaveDirector.plan_wave(6, aircraft_count=6, cap=6)` 建立 6 架 aircraft、最多 6 枚 missile；地面壓力另使用 6 組 `MANPOWER_SUPPORT`（最多 36 名 crew）與 6 條 tracer。兩個子場景都 warm-up 5 秒後每 1 秒取樣 30 秒，最低觀測 FPS 應 >= 60。若無法量測，記錄顯示器／執行環境限制與已完成的 compile／unit checks，不宣稱 FPS 結果。

SC-010 限制：本次完成 compile、84 個 unit tests、Ursina construction／update／lifecycle smoke，但沒有執行 30 秒互動式 FPS benchmark，因此不宣稱 `>= 60 FPS` 的量測結果；SC-010 仍需在可控顯示器與遊玩流程下補測。

## Reset matrix

手動重複每項至少 10 次：

| Action | Verify |
|---|---|
| weapon switch | old reticle／scope hidden; AA lock reset on every weapon switch; new CD shown from that weapon's own remaining value |
| scope close | AA lock immediately zero or sniper camera restored |
| start game / new wave | all three weapon CDs reset to 0; lock／reticle reset; cards reflect current roster |
| game over / return to menu | all three weapon CDs reset to 0; dynamic HUD／scope／tracers stopped or hidden |
| aircraft destroyed | matching dot gray; no stale target or missile target switch |
| all aircraft destroyed | one ground encounter only |
| ground cleared | all crew/tracers removed; next wave spawns together |
| aircraft impact / player death / city death | terminal screen; dynamic updates stopped |
| return to menu then start | cards, wave, aircraft, lock, CD and scope return to initial state |
