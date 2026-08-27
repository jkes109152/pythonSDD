# UI Contract: 防空鎖定、機頭飛行與導引飛彈

## Input Contract

| Input | Context | Result |
|---|---|---|
| Mouse movement | Gameplay | Existing first-person look; after that rotation, anti-air assist may add at most 3°/second toward a visible aircraft whose screen-center distance is no more than 1.5× the lock-zone radius |
| `1` | Airstrike | Equip anti-aircraft gun; show the enlarged fixed frame but do not accumulate lock until scoped |
| Left mouse | Anti-air scope | Fire only when progress is 100%, target is currently inside the lock zone, and cooldown is ready; create a guided missile |
| Right mouse button-down | Anti-aircraft gun | Toggle anti-air scope; scope uses the dedicated 55° view and enables lock evaluation; button release has no effect |
| Right mouse | Sniper | Preserve existing sniper scope and 35° view |
| Right mouse | Pistol or empty hand | No scope action |
| `2` / `3` | Ground combat | Preserve existing sniper/pistol selection and behavior |
| `E` / `G` | Existing interaction | Preserve valid pickup/drop behavior and reset anti-air scope/lock when applicable |

## Anti-Air Reticle Contract

- With anti-air equipped but scope closed, show a centered fixed square frame enlarged from the existing version. The frame is white and no lock progress is active.
- With anti-air scope open, show the fixed frame plus one continuous ordinary tracking circle (the user's image-2 style, not segmented tick marks) centered on the aircraft's screen projection while the target is tracking or decaying.
- The hidden acquisition zone is a circle with diameter 15% of the viewport's shorter dimension. It is not permanently drawn; the initial tracking ring radius represents it while progress is near zero.
- The tracking ring shrinks from the acquisition radius to the projected aircraft radius plus a small padding as progress approaches 100%. If progress decays, the ring expands proportionally.
- Show a horizontal lock progress bar and percentage from `0%` to `100%`. The bar, ring, state text and color must agree:
  - White / `未鎖定`: no progress or scope closed.
  - Red / `鎖定中`: progress is increasing or decaying but not currently fireable.
  - Green / `可發射`: progress is full and the target is currently inside the zone.
- Retain the existing red blink behavior while tracking if it remains visually compatible with the progress ring; green is stable and must not blink.
- When scope closes, lock progress resets immediately to white/zero and the ring, bar, percentage and anti-air assist are hidden. Missiles already launched continue while the same aircraft remains active.

## Scope and Camera Contract

| Mode | FOV | Lock evaluation | Visible reticle |
|---|---:|---|---|
| Normal | 90° | No anti-air lock | Weapon-specific normal reticle |
| Anti-air scope | 55° | Yes | Enlarged fixed frame, tracking ring, progress bar and label |
| Sniper scope | 35° | No anti-air lock | Existing sniper scope overlay/crosshair |

Closing anti-air scope, switching weapon, entering ground combat, game over or returning to menu restores the correct FOV and hides the anti-air tracking elements.

## Missile Feedback Contract

- Every valid anti-air shot visibly launches one yellow, elongated rectangular missile from the weapon/camera firing point.
- The missile follows the current aircraft and is removed only when it collides, expires, or its target reaches a terminal state.
- Collision uses the swept segment between consecutive missile positions and produces one visible explosion and one damage event. A missile never damages a different aircraft or damages the same aircraft twice.
- Multiple yellow missiles may be visible simultaneously after separate valid shots.

## Existing UI Compatibility

- Sniper and pistol reticles remain mutually exclusive with the anti-air reticle.
- The stronger second-stage aircraft evasion changes only the target's nose-led route; it does not change the 15% hidden lock zone, the 3-second accumulation, the 0.75-second decay buffer, strict in-zone fire gating or the capped 3°/second aim assist. A target that turns out of the zone may therefore start visible decay without making the lock immediately disappear.
- Existing wave, aircraft progress/type, player health, city health, Boss HP, warning, statistics and failure overlays remain visible and unchanged outside the new anti-air elements.
- Failure and reset behavior remains the existing 002 contract; all anti-air scope, progress, ring, assist, missiles and FOV state are cleared on terminal/reset transitions. Closing scope or switching weapons only clears the lock presentation; in-flight missiles continue until collision, expiry or target termination.
