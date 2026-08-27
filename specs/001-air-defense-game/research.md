# Research: 3D 防空守衛無限模式

## Decision 1: 使用 Ursina 8.3.0 作為 Python 3D 遊戲引擎

**Decision**: 以 `ursina==8.3.0` 作為直接遊戲依賴，使用現有虛擬環境的 Python 3.13.5；遊戲專用依賴記錄在獨立的 `requirements-game.txt`，不改動 `requirements-sdd.txt`。

**Rationale**:

- 現有功能需求是第一人稱真 3D，需要透視相機、場景物件、碰撞、滑鼠視角與 UI。
- Ursina 官方提供第一人稱控制器、程序化 3D 基本物件、動畫與碰撞/`raycast()` 文件，能以較少樣板支援本功能。[Ursina 官方網站](https://www.ursinaengine.org/)、[FirstPersonController API](https://www.ursinaengine.org/api_reference_v8_0_0/first_person_controller.html)、[raycast API](https://www.ursinaengine.org/api_reference_v8_0_0/raycast.html)
- PyPI 的 Ursina 8.3.0 要求 Python 3.12 以上，符合目前 Python 3.13.5 環境；其相依的 Panda3D、Pillow 與 pyperclip 由套件解析安裝。[Ursina 8.3.0 on PyPI](https://pypi.org/project/ursina/8.3.0/)

**Alternatives considered**:

- **直接使用 Panda3D**：功能完整且底層控制力高，但需要自行處理更多第一人稱控制器、UI 與常用遊戲樣板，不符合目前先完成可玩原型的優先順序。[Panda3D Python Manual](https://docs.panda3d.org/1.10/python/index)
- **維持 Pygame 並製作偽 3D**：依賴最少，但無法滿足使用者對真正 3D 場景、第一人稱視角與 3D 碰撞的要求。
- **改用 Godot/Unity**：能提供更完整的 3D 工具，但會離開現有 Python SDD 專案脈絡，且需要新的語言與專案工具鏈。

**Risks and mitigations**:

- Ursina 是本專案相對既有 Pygame 教學的新技術線；將遊戲程式與依賴隔離，既有 `day1`/`day2` 不共享新 runtime。
- 遊戲邏輯不直接依賴 3D Entity；鎖定計時、狀態轉移、計分與生成規則放在純 Python 模組，降低引擎 API 變動對測試的影響。

## Decision 2: 以物品欄切換武器、以螢幕中心 raycast 處理瞄準與射擊命中

**Decision**: 武器使用 HUD 下方固定的兩格物品欄直接切換：`1` 選用防空炮、`2` 選用狙擊槍，不受場景位置限制；E 的拾取仍可作為額外互動。玩家視線中心發出單一 ray 處理防空鎖定與狙擊命中，防空鎖定只接受視線直接命中目前戰鬥機的結果。場景中的地面、大樓、掩體、飛機與敵人使用明確碰撞體。

**Rationale**:

- 使用者要求瞄準介面中央的方框，中心 ray 能讓「方框是否對準飛機」與實際命中判定一致。
- 使用者要求 `1/2` 成為物品欄操作；將裝備選擇與世界拾取分離，能讓玩家在空襲與墜機後立即切換，不被武器架距離阻斷。
- 遮擋大樓或掩體時 ray 的第一個有效命中不是飛機，鎖定即可重置，直接符合規格的遮擋邊界案例。
- Panda3D 的 `CollisionRay` 適合從相機或視窗進行選取；Ursina 對應提供較高階的 `raycast()` 介面。[Panda3D CollisionRay](https://docs.panda3d.org/1.10/python/reference/panda3d.core.CollisionRay)

**Alternatives considered**:

- **只用距離與角度判定**：實作簡單，但無法正確處理掩體遮擋，也會讓瞄準框與視覺命中不一致。
- **滑鼠游標碰撞**：適合點選物件，不適合固定在畫面中央的第一人稱瞄準。
- **建立真正導引彈物理模擬**：可增加視覺效果，但首版只需驗證完成鎖定後的一枚導引彈能擊落目標，物理彈道不帶來必要的玩家價值。

## Decision 3: 顯式狀態機與事件一次性守衛

**Decision**: 使用明確的遊戲階段 `MAIN_MENU`、`AIRSTRIKE`、`GROUND_COMBAT`、`GAME_OVER`，並以獨立鎖定狀態 `WHITE`、`RED_TRACKING`、`GREEN_READY` 管理瞄準框。飛機擊落、飛機撞樓、乘員清場與玩家死亡等事件各自只能觸發一次。

**Rationale**:

- 空襲與地面戰有清楚的先後關係；顯式狀態可避免同一幀同時生成乘員、開始下一架飛機與顯示失敗。
- 紅框 3 秒計時、遮擋重置與「只在綠框發射」都是可由純邏輯單元測試的規則。
- 這延續專案憲章對明確遊戲迴圈、封裝物件狀態與集中協調跨物件規則的要求。

**Alternatives considered**:

- **多個布林值散落在主迴圈**：短期程式碼少，但容易產生互相矛盾的階段與重複計分。
- **完整通用 FSM 框架**：對單一小型遊戲過度抽象；使用簡單 Enum 與轉移函式即可保持可讀性。

## Decision 4: 以 Python 標準庫 `unittest` 測試純邏輯

**Decision**: 使用 Python 內建 `unittest` 執行鎖定計時、狀態轉移、事件去重、武器互動、生成數量與統計規則；3D 場景則以可重現的手動 quickstart 流程驗證，不新增 pytest 依賴。

**Rationale**:

- 目前虛擬環境沒有 pytest，但有 Python 3.13 與標準庫；`python -m unittest` 可直接執行測試與 discovery。[Python unittest 文件](https://docs.python.org/3.11/library/unittest.html)
- 純邏輯測試不需要建立視窗，能涵蓋最容易出錯的 3 秒計時、飛機/大樓競速、乘員只生成一次與死亡重置。
- 減少外部依賴符合專案憲章的依賴簡單原則。

**Alternatives considered**:

- **pytest**：語法便利，但首版只為測試引入額外依賴沒有必要。
- **只做手動測試**：無法穩定重現計時與事件順序，不能滿足憲章對純邏輯可重複案例的要求。

## Decision 5: 混合使用 CC0 資產與程序化幾何

**Decision**: 城市街區與角色優先使用合法的 CC0 低多邊形資產；武器、掩體、碰撞標記與缺少資產的飛機模型使用簡單幾何或可替換 placeholder。資產來源與授權記錄在遊戲資產目錄。

**Rationale**:

- 符合使用者選定的卡通街機與混合資產方向。
- Kenney 的 City Kit 與 Blocky Characters 頁面標示為 Creative Commons CC0，適合原型使用且不要求引入付費資產。[City Kit (Suburban)](https://kenney.nl/assets/city-kit-suburban)、[Blocky Characters](https://kenney.nl/assets/blocky-characters)
- 程序化 fallback 讓遊戲在資產未下載、載入失敗或替換模型時仍能啟動與測試。

**Alternatives considered**:

- **全程序化幾何**：最快完成玩法，但角色與城市辨識度較低。
- **一開始導入完整寫實資產包**：超出首版範圍，增加下載、授權、格式與動畫整合風險。

## Decision 6: 直接註冊 Ursina 更新/輸入事件並保留按鈕 fallback

**Decision**: 在建立 `Ursina` 應用程式後，直接註冊 `buttonDown` 事件與 task manager 更新工作，將事件轉送給遊戲控制器；主選單與失敗畫面的滑鼠按鈕仍使用 `Button.on_click`，並由控制器在游標懸停按鈕時提供同一事件的 fallback。

**Rationale**:

- Ursina 會在應用程式建立時保存模組層 `input`/`update` 回呼；只在建立後賦值 `app.input` 或 `app.update` 不一定能接到實際視窗事件。
- 同時保留 `Button.on_click` 與控制器 fallback，可涵蓋正常 UI 路徑及部分 Windows/Panda3D 視窗焦點或事件派送差異，且不改變遊戲規則。
- 直接事件橋接也讓 `1`/`2`、滑鼠射擊與狙擊瞄準使用同一套公開控制器輸入名稱，方便以實際 Ursina event 做 smoke check。

**Alternatives considered**:

- **只把 `app.input`/`app.update` 指派成控制器方法**：程式碼較短，但在 Ursina 8.3.0 的事件生命週期中可能無法取代已保存的模組層回呼，造成物品欄與射擊輸入失效。
- **只依賴按鈕的 `on_click`**：正常滑鼠點擊可用，但無法覆蓋事件橋接或焦點異常；保留鍵盤快捷鍵與 fallback 更符合主選單契約。
