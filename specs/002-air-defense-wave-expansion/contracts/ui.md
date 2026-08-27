# UI Contract: 3D 防空守衛波次與 Boss 擴充

## Input Contract

| Input | Context | Result |
|---|---|---|
| `W/A/S/D` | Gameplay | Move through the long map with existing controller collision |
| Mouse movement | Gameplay | First-person look |
| `1` | Airstrike | Equip anti-aircraft gun; no effect in ground combat |
| `2` | Ground combat | Equip sniper; no effect in airstrike |
| `3` | Ground combat | Equip pistol; no effect in airstrike |
| Left mouse | Anti-air | Fire only after a stable green lock and cooldown |
| Left mouse | Sniper | Fire long-range center shot when cooldown is ready |
| Left mouse | Pistol | Fire center shot only within 12 units and cooldown |
| Right mouse | Sniper | Toggle scope overlay and zoomed FOV |
| Right mouse | Other weapon | No scope action |
| `E` / `G` | Existing optional interaction | Preserve pickup/drop behavior where valid |

## Reticle Contract

- `ANTI_AIRCRAFT`: show only the centered square lock frame and its text state (`未鎖定`, `鎖定中`, `可發射`).
- `SNIPER`: hide the lock frame; show a clear crosshair. When scoped, show the scope overlay and zoomed view.
- `PISTOL`: hide the lock frame and sniper crosshair; show a smaller close-range reticle.
- Empty hand or an inactive phase: hide all weapon reticles.
- Reticle state must be conveyed by shape/text as well as color; no color-only information.

## Gameplay HUD

The gameplay HUD continuously shows:

- `第 N 波` and current aircraft progress such as `敵機 1 / 2`.
- Current aircraft type: `普通`, `人力支援`, `快速` or `裝甲 Boss`.
- Player health and `城市耐久`.
- Survival time, aircraft destroyed count and enemies defeated count.
- Current weapon and the three inventory slots; unavailable phase slots are dimmed.
- Airstrike warning while the active aircraft is within the existing warning threshold.

## Boss Health Contract

- On a Boss wave with the armored aircraft active, show `裝甲飛機 HP: current / 5`.
- After that aircraft is down and its ground Boss is active, replace it with `大魔王 HP: current / 10`.
- While other non-Boss aircraft in the same Boss wave are active, keep the Boss-wave indicator visible but hide the inactive Boss health number; show it again when the armored aircraft becomes active.
- When the ground Boss is defeated, clear the Boss health display before the next aircraft is shown.

## Failure and Reset

- Aircraft impact shows the existing building-impact failure.
- Player health zero shows player-death failure.
- City health zero shows `城市被摧毀`.
- After any failure, movement, firing, wave progression, enemy movement and counters stop.
- Returning to the main menu clears all wave, city, Boss, cooldown and reticle state before the next game.
