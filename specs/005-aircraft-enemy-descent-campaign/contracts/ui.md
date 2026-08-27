# UI Contract: 混合空戰、降落敵人與勝利

**Feature**: `005-aircraft-enemy-descent-campaign`
**Source**: [spec.md](../spec.md)

This is a player-facing desktop-game contract. It defines visible state and input behavior; it does not add a network or persistence API.

## Phase and Input Contract

| Phase | Available selection | Fire behavior | Interaction / navigation |
|---|---|---|---|
| `MAIN_MENU` | None | None | Enter/Space or start button starts; Q/Escape or quit button exits |
| `AIRSTRIKE` | Anti-aircraft only | Left click fires only after valid lock; right click toggles anti-air scope | E interacts with anti-air pickup when nearby; weapon rack ground slots are not yet active |
| `HYBRID_COMBAT` | Anti-aircraft, sniper, pistol | Anti-air fires at locked aircraft; sniper/pistol fire at airborne or landed crew under the center ray | E can interact with the weapon rack immediately after the first non-empty drop; right click uses the selected weapon's scope |
| `GROUND_COMBAT` | Sniper, pistol | Sniper/pistol fire at airborne or landed crew; no aircraft remain | E interacts with the weapon rack; right click toggles sniper scope |
| `GAME_OVER` | None | None | Enter/Escape or return button returns to main menu |
| `VICTORY` | None | None | Enter/Escape or return button returns to main menu |

The player may switch weapons during `HYBRID_COMBAT` without pausing aircraft, descent, ground movement or existing attack timers. A weapon that has no valid target still obeys its normal cooldown and fire gate.

## Descent Visual Contract

- A source aircraft's batch is visible immediately after that aircraft is destroyed.
- All members of one batch appear together and descend from the saved hit position with small horizontal separation.
- Each member reaches ground height after approximately 4 seconds, preserving the hit position's X/Z with its deterministic small offset.
- A descending member remains visible and targetable. Its collider follows its current airborne position.
- No countdown, progress bar or additional HUD indicator is shown for descent.
- A descending member that is killed disappears immediately. A member that survives reaches the ground and changes to the existing ground-enemy presentation.

## Gameplay HUD Contract

- Existing player, city, wave, aircraft, lock, warning, Boss, statistics, weapon and FPS information remains available according to the current gameplay HUD.
- `HYBRID_COMBAT` shows all three weapon slots as usable and keeps the anti-air frame/lock presentation available when anti-air is selected.
- No new descent timer or descent progress element is added.
- `VICTORY` shows the exact primary message `你贏了`, a frozen session result, and a `返回主選單` action.
- `GAME_OVER` continues to show the existing failure message and frozen result; victory and failure presentations are mutually exclusive.

## State-to-Visual Rules

| State | Required visual/input result |
|---|---|
| First non-empty drop begins | Weapon rack becomes available; remaining aircraft remain visible and active |
| Crew is `DESCENDING` | Crew is visible/targetable; no ground movement, enemy attack or city damage |
| Crew is landed | Existing ground movement, attack and city-damage rules resume |
| Aircraft is `DESTROYED` | Its aircraft visual is removed; its drop batch remains or is added to the encounter |
| Aircraft is `IMPACTED` | Failure presentation takes precedence; all dynamic combat input stops |
| Wave 18 clear | Victory presentation takes precedence; no wave 19 is spawned |
| Return to menu | All aircraft, crew, missiles, scopes, cooldown presentation and wave state are reset |

## Compatibility Contract

- Existing keyboard mappings remain: `1` anti-aircraft, `2` sniper, `3` pistol, `E` interact, `G` drop weapon, left mouse fire, right mouse scope.
- Existing mouse/camera targeting remains the source of aircraft and crew hit selection; airborne crew uses the same center-ray targeting family as landed crew.
- Existing enemy models, Boss presentation, sound/asset fallback behavior and failure handling are reused.
