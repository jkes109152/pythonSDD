# UI Contract: 防空 HUD、動態鎖定與整波敵機

## Scope and precedence

本 contract 描述玩家可見的 HUD 與視覺回饋。附件圖片只作版面與狙擊鏡的視覺參考；不引入圖片中的棋盤格、額外文字或未指定互動。既有中央警告、Boss HP、FPS、統計與下方武器欄保留，並透過 responsive anchor 避免與兩張狀態卡、中央瞄準 UI 重疊。遊戲內 HUD 卡片、進度條 track 與武器欄槽位背景必須透明；主要資訊文字使用白色大字體。狙擊鏡圓外遮罩與主選單／失敗對話框是視野或流程畫面，不屬於 HUD 卡片背景。

## Screen layout

所有位置以 `camera.ui` 的 viewport-relative 座標定位，並以固定邊距、最小可讀寬度與目前視窗 aspect ratio 做縮放：

```text
┌─ player / city card ─┐                         ┌─ wave / aircraft card ─┐
│ ♥ 100 / 100           │                         │ ⚑ 第 N 波              │
│   health bar          │                         │ ●●●○○○  敵機進度       │
│ shield 城市耐久 100% │                         │ 敵機種類：...           │
│   city bar            │                         └────────────────────────┘
└───────────────────────┘

                     [ fixed white anti-air frame ]
                         [ constrained reticle ]
                         lock status / lock bar
                         weapon CD bar

                         [ retained warning / Boss HP ]
                         [ retained weapon inventory ]
```

- 左上卡固定在 top-left safe margin；右上卡固定在 top-right safe margin。
- 兩卡使用透明背景，可用低透明度白色圓角輪廓分隔，不能蓋住畫面中央或下方 weapon inventory。
- 卡片主要資訊文字使用繁體中文、白色大字體；code-side enum／ID 使用英文名稱。
- 卡片比例、圓點換行與字體縮放必須在 1280×720 目標視窗和較窄視窗下保持可讀；圓點不得覆蓋 wave number 或 aircraft type。

## Player and city status card

### Player row

- 顯示紅色 heart icon、`目前值 / 最大值`（初始 `100 / 100`）與紅色 horizontal bar。
- bar fill 為 `clamp(health / max_health, 0, 1)`；生命歸零後停在 0，不顯示負值。

### City row

- 顯示藍色 shield icon、`城市耐久：<percent>%` 與藍色 horizontal bar。
- percent 與 bar 都從 `city_health / max_city_health` 推導；玩家受傷不應改變 city row，城市受傷不應改變 player row。
- 失敗畫面出現時保留最後一個有效值，不再被後續 update 改寫。

## Wave and aircraft status card

- 第一行顯示 flag icon 與 `第 N 波`。
- 第二行顯示每一架飛機一個 dot，順序與 `WavePlan.roster` 相同：存活（`APPROACHING`／`LOCKED`）為藍色，已摧毀或撞擊（`DESTROYED`／`IMPACTED`）為灰色 terminal dot。
- 第二行或其旁顯示 `敵機進度：<alive / total>%`，百分比是存活比例，不是擊落比例。
- 第三行列出本波 roster 中所有不重複的 aircraft type，順序與 roster 相同，例如 `敵機：快速・普通・Boss`；另顯示目前防空 sticky target 的 aircraft type。沒有有效 target 時顯示 `鎖定：未選定`。地面戰或空戰剛切換時不得保留上一個目標種類。
- 多於單行容量時優先縮小 dot 到最低可辨識尺寸，再換成兩行；不可使用省略號代替實際總數。
- 任何一架撞城進入 game over 後，包含 `IMPACTED` dot 在內的 dot 與 percentage 保留最後狀態並停止變動；`IMPACTED` 不計入 alive ratio。

## Anti-air reticle and lock frame

### Visibility

- 裝備防空炮時顯示固定白色 frame；未裝備、進入地面戰、game over 或 menu 時隱藏。
- 開啟防空 scope 後才顯示 dynamic reticle、lock text 與 lock bar；防空炮已裝備但 scope 關閉時，frame 可留在畫面上但 dynamic feedback 必須隱藏。

### Fixed frame

- frame 寬、高各為既有 `0.105` 的兩倍（目標 `0.210`），以 viewport-relative 正方形繪製。
- frame 是實際 lock boundary；四邊含邊界值，只有中心超出任一邊才視為 out-of-frame。
- frame 在 white、red tracking、decay、green ready、無目標等所有狀態都必須維持白色，不因鎖定狀態變色或閃爍。

### Constrained small reticle

- scope 初開、沒有 target 或 progress 為 0% 時，小準心位於 frame 中心。
- target 選取條件為可見、在 frame 內、距畫面中心最近；選定後顯示該 target 的 aircraft type。
- 小準心位置由 `frame_center → clamp(target_projection, frame_bounds)` 按 lock progress 插值；因此 progress 越高越靠近飛機中心，但永遠不離開 frame。
- current target 尚未 destroyed／impacted／terminated 且 progress 尚未衰減到 0% 時，不因另一架飛機進框而跳鎖。target 暫時不可投影時，保留最後有效位置並限制在 frame 內。
- target 離框時小準心仍留在 frame 內；不允許用準心位置或 target projection 直接把它移出白框。

### Lock states and fire feedback

| State | Small reticle | Text / bar | Fire |
|---|---|---|---|
| no target / zero | white | `未鎖定`、`鎖定 0%`、empty | no |
| accumulating | red／可依既有 flash 規則閃爍 | `鎖定中`、0–99%、bar increases | no |
| decaying | red | `鎖定中`、bar linearly decreases | no |
| completed and in frame | brief red flash, then green | `已鎖定`、`鎖定 100%`、full | yes if weapon CD ready |
| completed but out of frame | red / non-ready | progress may remain during 0.75 s buffer | no |

完成紅閃只套用小準心與其完成提示，不套用到白框。3 秒累積、0.75 秒線性衰減、離框 0.25 秒不立即歸零與離框 0.75 秒歸零沿用既有時序。

### Aim assist and firing

- scope 開啟、持有防空炮、target 可見且位於 frame 外但在 frame expanded 1.5× 範圍內時，提供每秒最多 3° 的 camera correction。
- target 超出 expanded range、不可見、scope 關閉或持有其他武器時不修正。
- firing gate 同時要求 target ID 有效、target 可見且在原始白框內、lock state 為 green ready、scope 開啟、anti-air CD 完成。任一條件失敗都不消耗 CD、不生成 missile。

## Weapon cooldown bar

- 目前持有防空炮、狙擊槍或手槍時，在目前武器準心正下方顯示一條獨立 CD bar；空手、非遊戲 phase 或無可用武器時隱藏。
- 射擊成功後 bar 從空開始，按該武器自己的 cooldown elapsed／duration 比例填滿；滿格代表可射擊。
- 預設色彩：冷卻中為黃色，ready 為綠色；bar track 背景透明，只顯示填充色，並與 lock bar 保持間距。
- 切換武器立即改讀新武器的剩餘時間，不能沿用上一把武器的 fill ratio；三把武器的 duration 分別為 1.25 s、0.75 s、0.20 s。
- 同一 phase 內切換武器只切換目前 view，保留三把武器各自的剩餘 CD；`START_GAME`、進入下一波、`GAME_OVER` 與 `RETURN_TO_MENU` 將三把武器 CD 集中重設為 0，關閉 scope 不重設 weapon CD。
- lock bar 與 CD bar 在防空 scope、sniper scope、pistol reticle 下都不得重疊；scope 關閉或武器切換時，舊 weapon reticle／scope overlay 必須隱藏。

## Sniper scope

- 僅在 ground combat 持有狙擊槍且右鍵 scope 開啟時顯示。
- 視覺包含：圓形瞄準視野、圓外深色遮罩、十字線與中央小紅點；不得顯示附件的棋盤格背景，也不得依賴外部圖片。
- 保留既有 `CAMERA_SCOPE_FOV = 35°`；scope 關閉、切槍、離開 ground combat、game over 或 menu 時恢復一般視野並隱藏 overlay。
- 狙擊鏡視覺與防空 frame、手槍準心互斥，不得同時顯示。

## Ground attack tracer

- 每次既有 ground attack 成功觸發時，從攻擊者位置朝玩家位置建立一條短暫、細長、黃色 tracer；方向需能看出 projectile source → player。
- tracer 預設 lifetime 為 `0.18 s`，由 head 從攻擊者位置到玩家位置做線性插值，tail 保留固定視覺長度；場景每 frame 呼叫 `update_ground_tracer(...)`，travel progress 到 1 時 destroy。
- 多名敵人同時攻擊時各自建立 effect；effect 由場景 effect ticker 在短 lifetime 後 destroy。
- tracer 只提供視覺回饋，不參與 collision、damage、attack cooldown 或 enemy defeated 統計；同一 attack event 最多建立一個 tracer。

## Lifecycle and reset contract

| Event | Required UI result |
|---|---|
| start game / new wave | cards reset to current state; all aircraft dots blue; lock target cleared; reticles center; all three weapon CDs reset to 0 |
| partial aircraft destroyed | matching dot gray; alive ratio recalculated; other aircraft and target continue |
| all aircraft destroyed | one aggregate ground encounter shown; no premature ground card transition |
| aircraft impact / game over | stop all dynamic update; retain last card values; hide scope and lock feedback; reset all three weapon CDs to 0 |
| weapon switch | reset anti-air lock on every weapon switch; hide old reticle; show new CD view while preserving each weapon's own remaining CD |
| scope close | reset anti-air lock immediately or restore normal camera for sniper |
| ground encounter cleared | clear crew/tracers; spawn next wave together |
| return to menu | hide gameplay HUD, scope, frame, lock/CD details and transient tracers; reset all three weapon CDs to 0 |
