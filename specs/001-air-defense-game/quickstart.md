# Quickstart: 3D 防空守衛無限模式

## Prerequisites

- Windows 桌面環境。
- Python 3.13 或符合本功能依賴需求的 Python 3.12+。
- 已建立專案虛擬環境。
- 可用的圖形視窗與滑鼠輸入。

## Setup

從 repository root 執行：

```powershell
Set-Location 'C:\Users\lamun\OneDrive\Desktop\pythonSDD'
python -m pip install -r requirements-game.txt
```

若專案被移到其他位置，將 `Set-Location` 的路徑換成該專案根目錄；必須在包含
`requirements-game.txt` 與 `air_defense/` 的目錄執行，不能從其他 `_proj` 或教學子目錄執行。

SDD 工具仍使用既有的 `requirements-sdd.txt`；兩者不互相取代。

## Automated Validation

```powershell
python -m compileall air_defense tests
python -m unittest discover -s tests -p "test_*.py" -v
```

預期結果：語法檢查成功，所有純邏輯測試通過；測試不得要求建立遊戲視窗。

若要驗證實際 Ursina 視窗事件橋接、主選單按鈕 fallback 與物品欄按鍵，可在有圖形桌面的環境執行：

```powershell
python -B -c "from direct.showbase.MessengerGlobal import messenger; from ursina import mouse; from air_defense.main import create_application; from air_defense.state import GamePhase, SessionEvent, WeaponKind; app, game = create_application(); mouse.hovered_entity = game.hud.start_button; game.hud.start_button.hovered = True; messenger.send('buttonDown', ['mouse1']); assert game.session.phase == GamePhase.AIRSTRIKE; messenger.send('buttonDown', ['1']); assert game.session.held_weapon == WeaponKind.ANTI_AIRCRAFT; messenger.send('buttonDown', ['2']); assert game.session.held_weapon == WeaponKind.ANTI_AIRCRAFT; game.session.transition(SessionEvent.AIRCRAFT_DESTROYED); messenger.send('buttonDown', ['2']); assert game.session.held_weapon == WeaponKind.SNIPER; print('REAL_EVENT_MENU_INVENTORY_SMOKE OK'); app.userExit()"
```

預期輸出包含 `REAL_EVENT_MENU_INVENTORY_SMOKE OK`；此命令會開啟並關閉一次遊戲視窗，不替代後續人工遊玩驗收。

## Launch

```powershell
python -m air_defense.main
```

首次啟動時先確認視窗能開啟、主選單按鈕可點擊、接受滑鼠/鍵盤輸入並正常關閉；這是基礎階段的手動 smoke check。

目前實作會在啟動時將 Panda3D 時鐘限制為 60 FPS。為了避免部分 Ursina 8.3.0 發行包缺少 editor UI 圖示而無法建立視窗，遊戲停用可選的 Ursina editor UI；這不影響遊戲 HUD 或操作。場景中的飛機、乘員、建築與武器使用程序化幾何，沒有外部模型下載要求。

## Manual Acceptance Flow

1. 在主選單點擊「開始遊戲」（也確認 `Enter`/`Space` 可作為快捷鍵），確認玩家出現在城市街區的防守點，生命值與統計已重置，且畫面下方顯示物品欄 `1 防空炮`、`2 狙擊槍`；重新啟動後點擊「離開遊戲」（也確認 `Q`/`Escape` 可關閉視窗）。
2. 在空襲階段直接按 `1`，確認不需靠近武器即可裝備防空炮，並在中央出現白色正方形瞄準框（`E` 仍可作為傳統互動鍵）。
3. 將框對準直線俯衝的戰鬥機：確認顯示「鎖定中」並以每 0.12 秒切換一次可見/不可見的紅框，持續對準 3 秒後變成顯示「可發射」的穩定綠框。
4. 在綠框時按左鍵，確認一枚導引彈擊落飛機；在紅框或白框時按左鍵，確認不會發射。
5. 確認墜機後只出現該架飛機的 2–5 名持槍乘員；每名敵人有預設掩體與角色，掩護射手留在掩體，推進射手只在預設掩體間移動並依冷卻射擊。
6. 墜機後直接按 `2` 切換狙擊槍（不需走到武器架；`G`、`E` 仍可作為傳統操作）；按右鍵確認狙擊瞄準視覺切換，以狙擊槍命中敵人，確認一發擊倒且不需要補彈。
7. 清除當前乘員後，確認下一架飛機立即開始接近大樓，沒有勝利畫面或地面增援；若玩家仍持有狙擊槍，HUD 必須提示使用物品欄按 `1` 切換防空炮，且不能用狙擊槍攔截。
8. 分別測試不攔截讓飛機撞樓，以及讓玩家被射擊至生命值歸零；確認兩者都進入失敗畫面並顯示正確原因與統計。
9. 從失敗畫面點擊「返回主選單」（也確認 `Enter`/`Escape` 可返回），再開始新局；確認上一局敵人、飛機、武器狀態與統計沒有殘留。

## Measured Acceptance Protocol

- **SC-001**：由首次遊玩的測試者從開始新局計時，到看懂物品欄、按 `1` 裝備防空炮並看到中央瞄準框；結果 MUST 不超過 30 秒。
- **SC-002**：重複 10 次鎖定嘗試；每次記錄白框 → 紅框閃爍 → 綠框、每 0.12 秒閃爍半週期及中斷後立即回白框，10 次都必須通過。
- **SC-003**：完成 5 次「擊落飛機 → 看到 2–5 名乘員 → 按 `2` 切換狙擊槍 → 右鍵狙擊 → 清場 → 下一架空襲」流程，不重開程式。
- **SC-004**：分別觸發飛機撞樓與生命值歸零；以單調時鐘記錄事件成立至停止戰鬥並顯示 Game Over 的時間，兩種原因都 MUST 不超過 1 秒且原因正確。
- **SC-005**：重複 5 次墜機測試，確認每架飛機只建立一組 2–5 名乘員，清場後不再出現該架飛機的敵人。
- **SC-006**：邀請 5 名未玩過本遊戲的測試者，只提供 HUD 與正常操作，不額外解釋狀態；至少 4 人必須能指出未鎖定、鎖定中、可發射與需要切換狙擊槍。
- **Performance**：在一架飛機、一棟目標大樓與五名乘員的最大原型負載下，記錄遊戲內 FPS、作業系統與硬體；目標為 60 FPS，若未達成必須記錄限制與原因。

## Implementation Verification Notes

- 目前環境（Windows、Python 3.13.5、Ursina 8.3.0）已通過主選單按鈕/快捷鍵事件、最小主選單啟動/關閉與建立完整空襲場景 smoke check；程序化 fallback 未依賴外部資產。
- 目前環境的自動檢查結果為 `compileall` 成功、18 個 `unittest` 全部通過，且已驗證實際 Ursina `buttonDown` 事件可驅動物品欄選取與主選單按鈕 fallback。2026-08-27 使用者回報人工驗收流程已完成且沒有問題，涵蓋主選單、物品欄、鎖定/發射、墜機乘員、循環、兩種失敗與返回主選單重置；本紀錄不臆造未提供的逐次計數、首次使用者理解度或硬體 FPS 數值。

## Known Platform Limitations

- Ursina/Panda3D 在部分自動化或遠端桌面環境可能顯示 `SetForegroundWindow() failed`；只要視窗仍能開啟，這是視窗焦點警告。
- 某些 Panda3D Windows 組合可能額外顯示找不到 Ursina 預設視窗圖示的警告；這只影響標題列圖示，不影響遊戲視窗、HUD 或操作。
- 若 Windows 沒有 `NotoSansTC-VF.ttf` 或 `kaiu.ttf`，HUD 會回退到 Ursina 內建英文字型；繁體中文字形可能缺字，應在正式測試機安裝可顯示繁中的系統字型。
- 若 OneDrive 或受限資料夾無法建立 Panda3D cache，Panda3D 會停用快取；首次載入可能較慢，但不影響規則與程序化場景。

## References

- 詳細狀態、欄位與不變條件請參閱 [data-model.md](./data-model.md)。
- 螢幕狀態與輸入規則請參閱 [contracts/ui.md](./contracts/ui.md)。
