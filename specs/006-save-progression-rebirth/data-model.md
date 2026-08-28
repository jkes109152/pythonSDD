# 資料模型：持久化存檔、進度與重生戰役

**功能**：`006-save-progression-rebirth`

**來源**：[spec.md](./spec.md)、[research.md](./research.md)

## 資料邊界

006 將資料分成兩個明確邊界：

| 類別 | 生命週期 | 內容 |
|---|---|---|
| `SaveProfile` | 跨遊戲、跨程式執行 | 金幣、重生、永久升級、已解鎖武器、購買上限、重生資格、最近完成的 a-b 紀錄 |
| `SessionProgress` | 目前程式執行期間 | 所選存檔與正常完成後的下一個 a-b 指標；不寫入 JSON |
| `RunState` | 單次小關嘗試 | HP、城市血量、敵人、彈藥、砲塔、鎖定、冷卻、戰鬥階段與目前 a-b |

目前 HP、敵人、城市血量、彈藥、砲塔、戰鬥狀態與未完成的 a-b 進度不得進入
`SaveProfile`；最近完成的 a-b 紀錄只供顯示／診斷，不代表可恢復的遊戲進度。

## 持久化實體

### `SaveProfile`

代表五個存檔欄位之一的永久進度。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `schema_version` | `int` | 目前為 1；未知版本不可直接覆蓋 |
| `coins` | `int` | 必須為非負整數 |
| `rebirth_count` | `int` | 必須為非負整數 |
| `max_aircraft_count` | `int` | 必須等於 `2 + rebirth_count`，載入時驗證 |
| `upgrade_levels` | `dict[str, int]` | 可購買升級的目前等級，必須為非負整數；缺少項目按 0 級處理 |
| `upgrade_caps` | `dict[str, int]` | 目前購買上限，依重生次數正規化；缺少項目按升級目錄推導 |
| `unlocked_weapons` | `list[str]` | 去重後保存標準武器 ID |
| `rebirth_available` | `bool` | 死亡或目前 A 最終小關完成後為真，成功重生後為假 |
| `last_completed_a_b` | `str` 或 `None` | 最近一次成功完成的小關，例如 `2-5`；須符合 `1 <= b <= 2a+1`，只供顯示／診斷，不作為續關點 |

預設資料為 0 金幣、重生次數 0、A=2、最近完成 a-b 為空、既有單目標防空炮／狙擊槍／手槍
已解鎖、所有可重複升級為 0 級、重生資格為假。

`last_completed_a_b` 是歷史摘要，不以目前 A 重新解讀；載入時只驗證其為 `a-b` 格式、
`a >= 1` 且 `1 <= b <= 2a+1`。如此可保留重生前最大 A 的最終小關紀錄，而不把它誤當成
目前可玩的關卡或續關點。

`max_aircraft_count` 與 `upgrade_caps` 是可供 HUD 顯示與資料診斷的保存欄位，但來源規則
仍是 `rebirth_count`。若保存值與推導值不一致，載入時使用推導值並在下一次成功保存時
正規化，不得接受 4 或 18 作為硬上限。

### 存檔欄位

`SaveStore` 管理 `slot_id` 1～5 與對應的 `SaveProfile`。每個存檔欄位都是獨立檔案；讀寫一個
欄位時不可載入、覆蓋或重建其他欄位。

建議的資料形狀如下，欄位名稱是機器介面，說明文字仍以繁體中文維護：

```json
{
  "schema_version": 1,
  "coins": 0,
  "rebirth_count": 0,
  "max_aircraft_count": 2,
  "upgrade_levels": {},
  "upgrade_caps": {},
  "unlocked_weapons": ["ANTI_AIRCRAFT", "SNIPER", "PISTOL"],
  "rebirth_available": false,
  "last_completed_a_b": null
}
```

不加入 `current_level`、未完成的當局進度、`current_hp` 或任何戰鬥實體序列化欄位。
`last_completed_a_b` 只在成功結算小關後更新，永遠不會使遊戲跳過 1-1 或恢復中途戰鬥。

### `SaveDeleteResult`

刪除操作的不可持久化結果物件，不包含另一份 Profile，也不會寫入 JSON。

| 欄位 | 型別 | 規則 |
|---|---|---|
| `slot_id` | `int` | 被要求處理的 1～5 號欄位 |
| `success` | `bool` | 只有實際刪除成功時為真 |
| `path` | `Path` | 精確對應的 `slot-N.json` 路徑 |
| `status` | `str` | `deleted`、`empty`、`failed` 或流程層的 `rejected` |
| `error` | `str` 或 `None` | 失敗或拒絕時的診斷原因 |

`SaveStore.delete_slot(slot_id)` 只對指定檔案執行 `unlink`；欄位不存在時回傳 `empty`，
不建立預設檔，也不觸碰其他四個欄位。`GameSession.delete_save_slot()` 只在
`SAVE_SELECT` 允許呼叫，其他狀態回傳 `rejected`。

### 選檔刪除確認狀態

`GameHUD` 只在記憶體保留 `pending_delete_slot: int | None`。它不是 `SaveProfile`、
`SessionProgress` 或 `RunState` 的欄位，也不得寫入存檔：

1. 點擊非空欄位的「刪除」後，設定目標欄位並啟用「確認刪除」與「取消」。
2. 點擊「取消」清除待確認狀態且不呼叫刪除 API。
3. 點擊「確認刪除」先清除待確認狀態，再呼叫指定欄位刪除 API；重複回呼沒有待確認目標，
   因此不得再次刪除或改動資料。
4. 刪除結果回傳後重新讀取五個欄位並刷新畫面；刪除失敗仍保留原始檔案。

## 關卡資料

### `LevelKey`

不可變的 `(a, b)` 值物件，對外格式為 `"a-b"`。

驗證規則：

- `A` 必須為大於或等於 2 的整數，並由 `2 + rebirth_count` 推導。
- `1 <= a <= A`。
- `a < A` 時，`1 <= b <= a+1`。
- `a == A` 時，`1 <= b <= 2a+1`。
- 無效的 a、b 或 A 必須拒絕，不建立部分關卡。

### `LevelPlan`

代表一個 `LevelKey` 的確定性內容。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `key` | `LevelKey` | 關卡身份 |
| `maximum_aircraft_count` | `int` | 目前 A |
| `roster` | `tuple[AircraftType, ...]` | 固定順序的普通／特別／魔王飛機排列 |
| `normal_count` | `int` | 普通飛機數量 |
| `special_count` | `int` | 特別飛機數量 |
| `boss_count` | `int` | 魔王飛機數量 |
| `is_boss_stage` | `bool` | `boss_count > 0` |
| `is_final_sublevel` | `bool` | `key.a == A` 且 `key.b == 2A+1` |

產生規則：

- `a < A`：`normal_count = a-(b-1)`、`special_count = b-1`、`boss_count = 0`。
- `a == A` 且 `b <= A+1`：同上，仍不出現魔王。
- `a == A` 且 `b > A+1`：`boss_count = b-(A+1)`、`special_count = A-boss_count`、
  `normal_count = 0`。
- 普通轉特別由右至左；特別轉魔王由左至右，排列結果不可依賴隨機數或呼叫順序。
- `特` 預設映射至既有的 `MANPOWER_SUPPORT` 行為；`魔` 映射至 `ARMORED_BOSS`。

戰役順序為 a 由 1 到 A、每個 a 的 b 由 1 到該 a 的最大 b。正常完成只把下一個
`LevelKey` 留在記憶體，並把已完成的目前 `LevelKey` 寫入 `SaveProfile.last_completed_a_b`；
該歷史紀錄不會被當成續關點。完成 `is_final_sublevel` 時，`SessionProgress.next_play_level`
重設為 1-1；玩家若尚未重生仍可手動重新遊玩目前 A 的戰役，重生資格則保持有效。

## 遊戲局實體

### `RunState`

代表一次「遊玩遊戲」的小關嘗試。

| 欄位 | 型別 | 生命週期規則 |
|---|---|---|
| `attempt_id` | `str` | 每次開始小關建立一次，供事件冪等使用 |
| `level` | `LevelKey` | 本次執行的小關，不保存 |
| `phase` | `GamePhase` | 依狀態轉移表變更 |
| `current_hp` | `float` | 範圍為 0 到有效最大 HP |
| `effective_max_hp` | `int` | 由永久升級推導 |
| `city_health` | `float` | 每次小關開始為完整值 |
| `aircrafts` | `dict[str, AircraftState]` | 本次關卡的飛機紀錄表 |
| `ground_encounter` | `GroundEncounterState` 或 `None` | 本次小關的地面敵人集合 |
| `weapon_runtime` | `dict[WeaponKind, WeaponRuntime]` | 每次小關重新建立，包含暫時彈藥與冷卻 |
| `turrets` | `list[AutoDefenseTurretState]` | 每次小關重新建立，最多六台 |
| `selected_weapon` | `WeaponKind` | 只允許已解鎖槽位 |
| `regen` | `RegenState` | 只存在本次小關 |
| `reward_settled` | `bool` | 一次嘗試只可由假轉真一次 |

### `SessionProgress`

代表目前程式執行期間的非持久化流程指標：

| 欄位 | 型別 | 生命週期規則 |
|---|---|---|
| `selected_slot_id` | `int` | 1～5；選檔後固定至返回選檔畫面或程式結束 |
| `next_play_level` | `LevelKey` | 正常完成中間小關後更新；完成最終小關、死亡、重新載入或重生後重設為 1-1 |
| `last_reward_settlement` | `RewardSettlement` 或 `None` | 結算後暫留至下一次開始小關；用於回傳同一嘗試的重複完成結果，不寫入 JSON |

`SessionProgress` 由 `GameSession` 持有，是主選單開始遊戲時的唯一下一關來源；它與
`RunState` 分開，清除戰鬥狀態時不會誤將已決定的下一關寫入存檔。

### `AircraftState`

保存一架飛機的穩定 ID、`AircraftType`、目前階段、位置快照、生命與掉落是否已處理。
飛機是 RPG 的非法目標；RPG 爆炸快照只可收錄地面敵人。
來源 ID 必須在本次 `RunState` 中唯一；`DESTROYED`、`IMPACTED` 等終止狀態轉移不得
回退或重複觸發。

### `GroundEncounterState`

保存一個聚合地面遭遇與所有已建立的降落批次。每個成員另外保存自己的穩定 ID、
來源飛機 ID、降落狀態、位置、生命與 Boss 標記。

必要欄位：

- `encounter_id`
- `members`
- `source_aircraft_ids`
- `batch_progress`
- `alive_count`
- `cleared`

同一來源飛機只能加入一次批次；批次內的每個成員只能被清除一次。下降中的成員可被
玩家攻擊，但不移動、不攻擊玩家、不造成城市傷害。

RPG 爆炸完成命中後，必須先更新每個死亡成員的 `batch_progress` 與 `cleared`，再以
`RunState.wave_runtime` 的「所有飛機已摧毀、所有掉落決策已處理、聚合遭遇已清除」條件
判定小關完成。控制器中的 `encounter` 是場景快取；若它暫時為空或不是目前聚合遭遇，
必須優先使用 `RunState.ground_encounter`，不可因視覺參照不同步而漏掉結算。

## 升級與經濟資料

### `UpgradeCatalogEntry`

集中描述一個升級或武器解鎖：

- 標準 ID
- 顯示名稱
- 是否為一次性解鎖
- 初始等級與基礎上限
- 每次重生增加的上限
- 效果增量或倍率
- 價格公式
- 前置解鎖條件

可重複升級的有效上限由 `base_cap + rebirth_count * cap_growth` 推導，再套用武器的硬上限。
最大 HP、鎧甲、鎖定時間、白框大小與各武器冷卻的 `cap_growth` 均為 1；多目標鎖定與
砲塔容量的 `cap_growth` 也為 1；多目標鎖定的基礎有效目標數量為 2、可購買 4 級，砲塔的
基礎有效容量為 1、可購買 5 級，但兩者有效等級／容量均不得超過 6。一次性解鎖的上限固定為 1，
不因重生增加。載入時若等級超過推導上限，該欄位視為格式錯誤並保留原始檔。
永久升級包括最大 HP、鎧甲、防空炮鎖定時間、白框大小、防空炮輔助瞄準，以及各武器與
砲塔冷卻時間。鎧甲每級使單次傷害減少 1，最低承受傷害為 1。

### `RewardSettlement`

記錄一次小關嘗試的結算結果：

- `attempt_id`
- `level_key`
- `raw_reward`
- `rebirth_multiplier`
- `awarded_coins`
- `settled`

只有尚未結算、成功完成且嘗試識別碼（`attempt_id`）相同的結果才能改變 Profile 金幣。死亡不建立成功
獎勵；死亡後重玩產生新的 `attempt_id`。結算結果暫存於 `SessionProgress`，即使 RunState
已清除，同一嘗試的重複回呼也只能回傳原結果；開始新的小關後，舊嘗試識別碼一律拒絕。

### `PurchaseSettlement`

記錄目前商店畫面中的一次購買操作：

- `operation_id`
- `upgrade_id`
- `result`

相同 `operation_id` 的重複回呼只能回傳第一次結果，不得再次扣款或增加等級；新的
`operation_id` 才代表玩家的新購買。此結算紀錄只存在目前程式執行期間，不寫入 JSON。
`GameSession` 至少須在目前商店操作期間保留這些結果；離開商店後，新的玩家操作必須產生新的
唯一 ID。

### `RebirthOperation`

重生是不可部分完成的 Profile 操作：

- 讀取目前 `rebirth_count`、`coins` 與 `rebirth_available`。
- 驗證不在戰鬥、資格為真且金幣不少於 `1000 * (rebirth_count+1)`。
- 一次性將金幣歸零、重生次數加一、A 重算、升級上限重算、資格清除。
- 將 `SessionProgress.next_play_level` 設為 1-1，保存後回到同一存檔主選單。
- 第二次使用同一結果或同一 UI 回呼必須讀到資格為假而不改變資料。

## 武器與回血資料

### `WeaponRuntime`

每個本局武器保存：

- `weapon_kind`
- `ammo_remaining`
- `cooldown_remaining`
- `range`
- `damage`
- `scope_enabled`（適用時）

選擇武器只驗證「已解鎖且在戰鬥中」；開火另驗證合法目標、射程、冷卻與彈藥。

### `MultiLockState`

多目標防空炮保存：

- 目標 ID 有序集合
- 每個目標的鎖定進度與狀態
- 由永久升級推導的目標數量上限
- 本次齊射的唯一事件 ID

目標上限解鎖後為 2，目標數量升級等級從 0 開始，第一次升級價格為 500，後續價格依
`500*(level+1)` 計算，每次升級增加 1，硬上限為 6；單目標防空炮仍使用現有單目標鎖定追蹤器。

### `AutoDefenseTurretState`

每台暫時砲塔保存：

- 固定位置 ID
- 是否啟用
- 目前鎖定的小兵 ID 或 `None`
- 冷卻與本局彈藥

固定位置總數為 6；商店解鎖後每個新小關自動建立目前容量的暫時砲塔，容量升級等級由 0
開始、解鎖時容量為 1，第一次升級價格為 450，後續價格依 `450*(level+1)` 計算，每次
容量升級增加 1，且不提供戰鬥中購買或任意放置。每台預設每小關 20 發、每次射擊冷卻
1.5 秒、每次命中傷害 20，同時最多鎖定一名已落地、非魔王的小兵。目標選擇採距離優先、
穩定 ID 作為同距離排序鍵；小關結束時所有砲塔與其彈藥清除。

### `RegenState`

- `last_damage_at`
- `recovery_started`
- `cycle_cap_remaining`
- `sublevel_budget_remaining`
- `recovered_this_damage_cycle`

每個新小關建立總額度 `0.2 * effective_max_hp`。受傷後等待 5 秒，以每秒 2 HP 回復；
本次週期最多使用 `min(0.2 * effective_max_hp, sublevel_budget_remaining)`，並在回血時扣除
小關剩餘額度。再次受傷只重設計時與該週期上限，不增加小關總額度；額度用完後本小關不再
自動回血。

## 狀態轉移

| 目前狀態 | 事件 | 下一狀態 | 必要結果 |
|---|---|---|---|
| `SAVE_SELECT` | 選擇 1～5 號 | `MAIN_MENU` | 載入 Profile，不開始戰鬥 |
| `SAVE_SELECT` | 滑鼠點擊非空欄位的刪除 | `SAVE_SELECT` | 只進入待確認狀態，不立即刪除 |
| `SAVE_SELECT` | 確認刪除 | `SAVE_SELECT` | 只刪除指定欄位並重新列出五欄位 |
| `SAVE_SELECT` | 取消刪除 | `SAVE_SELECT` | 清除待確認狀態，五欄位資料不變 |
| `MAIN_MENU` | 開始遊戲 | `AIRSTRIKE` | 建立一個小關 RunState，從 `SessionProgress.next_play_level` 開始 |
| `MAIN_MENU` | 升級商店 | `SHOP` | 只修改成功購買的永久資料 |
| `MAIN_MENU` | 合法重生 | `MAIN_MENU` | 原子更新 Profile、保存、準備 1-1 |
| `AIRSTRIKE`／`HYBRID_COMBAT`／`GROUND_COMBAT` | 有效完成小關 | `MAIN_MENU` | 一次結算金幣、更新 `SessionProgress.next_play_level`、清除戰鬥資料、保存 |
| 任一戰鬥狀態 | 玩家死亡 | `MAIN_MENU` | 不發獎勵、設定並保存重生資格、重設至 1-1 |
| 任一戰鬥狀態 | 城市摧毀或飛機撞擊 | `MAIN_MENU` | 同死亡處理，清除所有戰鬥資料 |
| `SHOP` | 返回 | `MAIN_MENU` | 保留已保存 Profile，不建立 RunState |

## 邊界不變量

- `SaveProfile` 不含任何戰鬥實體或未完成的 a-b 進度；最近完成紀錄不可用來續關。
- `max_aircraft_count == 2 + rebirth_count` 永遠成立。
- `a < A` 的 `LevelPlan.boss_count == 0` 永遠成立。
- 一次小關嘗試的獎勵、死亡結果與重生操作各自只可成功一次。
- 所有新小關的 current HP 都從有效永久最大 HP 開始；上一局 HP 不可帶入。
- 多目標鎖定數量與砲塔數量都受購買等級及硬上限約束；飛機 A 不受 4 或 18 限制。
- 任何 `DESCENDING` 地面敵人不移動、不攻擊、不造成城市傷害，但仍可被合法手持武器命中。
- 選檔滑鼠點擊只能載入被點擊的欄位；刪除確認只能刪除精確指定欄位，其他四個欄位不可被
  同一操作讀取、覆蓋或刪除。
- `SAVE_SELECT` 以外的刪除請求必須被拒絕；空白欄位與取消確認不得建立、刪除或修改檔案。
