# Data Model: 防空鎖定、機頭飛行與導引飛彈

## Overview

The session remains in memory. There is still one active aircraft and one active ground encounter, but the active airstrike may contain multiple missiles. Each missile is bound to the aircraft id that existed when it was fired and is removed when that target reaches a terminal state.

## Configuration Values

| Value | Initial default | Rule |
|---|---:|---|
| Normal camera FOV | 90° | Restored outside any scope |
| Anti-air scope FOV | 55° | Used only while anti-air scope is open |
| Sniper scope FOV | 35° | Existing ground-combat behavior |
| Lock duration | 3.0 s | In-zone progress reaches 100% |
| Lock decay duration | 0.75 s | Out-of-zone progress reaches 0% |
| Acquisition diameter | 15% of viewport short side | Hidden circular lock zone |
| Fixed lock frame size | 0.10 UI units | Larger than the existing frame |
| Aim-assist activation band | 1.5 × acquisition-zone radius | Screen-center distance at or below this value enables assist |
| Aim-assist maximum | 3°/s initial tuning | Capped angular correction applied after mouse rotation |
| Missile speed | 90 world units/s initial tuning | Forward-only missile movement |
| Missile turn rate | 240°/s initial tuning | Maximum steering change |
| Missile hit radius | 1.5 world units initial tuning | Collision threshold |
| Missile lifetime | 5.0 s initial tuning | Safe expiry for a stale or unreachable target |

The values are balance defaults, not new external interfaces; they remain centralized and can be tuned after manual playtesting.

## Lock Progress

| Field | Type | Rules |
|---|---|---|
| `lock_elapsed` | non-negative float | Clamped to `[0, lock_duration]` |
| `lock_duration` | positive float | Defaults to 3.0 seconds |
| `decay_duration` | positive float | Defaults to 0.75 seconds |
| `target_in_zone` | boolean | True only when projected target is inside the hidden circle and visible |
| `state` | `LockState` | White at zero, red while tracking/decaying, green only at full progress while in-zone |
| `progress` | derived float | `lock_elapsed / lock_duration`, clamped to `[0, 1]` |
| `scope_enabled` | boolean | Owned by `LockOnTracker`; lock accumulation/decay is evaluated only when true |

### Lock transitions

1. `scope_enabled = false` or the active target is absent → `lock_elapsed = 0`, white, not fireable.
2. Scope open and target in-zone → increase by `delta_seconds`; red until full, then green.
3. Scope open and an existing target is outside the zone or not visible → decrease by `delta_seconds * lock_duration / decay_duration`; red while above zero, white at zero.
4. Target returns before zero → increase from the remaining value.
5. Green target leaves the zone → progress may remain at 100% during decay, but `target_in_zone = false` makes firing invalid until the target returns.

`set_scope_enabled(False)` performs the immediate reset in transition 1. A closed scope is never treated as a short target loss, so it cannot enter the decay state. The scene/controller supplies `target_in_zone = false` for an existing but outside, occluded or otherwise unlockable target.

## Aircraft Flight State

The existing aircraft type, health, phase and target identity remain. The movement representation changes to:

| Field | Type | Rules |
|---|---|---|
| `position` | 3D vector | Mutable current world position |
| `forward` | normalized 3D vector | Direction of actual movement |
| `yaw` | angle | Horizontal heading derived from `forward` |
| `pitch` | angle | Vertical heading derived from `forward` |
| `speed` | positive float | Type-specific forward speed |
| `max_yaw_rate` | positive float | Maximum horizontal turn per second |
| `max_pitch_rate` | positive float | Maximum vertical turn per second |
| `flight_elapsed` | non-negative float | Used for deterministic evasion phase and warning timing |
| `path_progress` | `[0, 1]` float | Compatibility/progress view of approach toward the target |
| `evasion_phase` | float | Drives desired-heading changes, never direct lateral teleportation |

`advance(delta_seconds)` computes a desired heading toward the city/evasion point, turns the current heading by no more than the configured rates, and moves by at most `speed * delta_seconds` along `forward`. It never directly adds a sideways offset or reverses the aircraft.

The second-stage default evasion profiles are centralized as follows. Amplitude changes the desired-heading bend, frequency controls how often the bend reverses, and the rate limits keep the turn nose-led rather than teleporting the position:

| Aircraft type | Evasion amplitude | Frequency | Max yaw rate | Max pitch rate |
|---|---:|---:|---:|---:|
| Normal | 24.0 | 0.25 Hz | 48°/s | 22°/s |
| Manpower support | 16.0 | 0.20 Hz | 34°/s | 16°/s |
| Fast | 32.0 | 0.40 Hz | 70°/s | 30°/s |
| Armored Boss | 20.0 | 0.22 Hz | 30°/s | 14°/s |

The deterministic 10-second horizontal path-span checks are greater than 4.0, 2.5, 7.0 and 2.4 world units for normal, manpower support, fast and armored aircraft respectively; the fast profile must exceed the normal profile. These are balance guards, not alternate movement semantics.

## Guided Missile

| Field | Type | Rules |
|---|---|---|
| `id` | unique identifier | One id per valid anti-air shot |
| `target_aircraft_id` | identifier | Must match the active aircraft before damage is applied |
| `position` | 3D vector | Current missile position |
| `forward` | normalized 3D vector | Actual missile movement direction |
| `speed` | positive float | Forward travel speed |
| `turn_rate` | positive float | Maximum steering change per second |
| `hit_radius` | positive float | Collision distance to target |
| `lifetime_remaining` | non-negative float | Missile expires safely at zero |
| `consumed` | boolean | Set on hit, expiry or terminal cleanup; prevents duplicate damage |

`advance(delta_seconds, target_position)` turns toward the current target position within `turn_rate`, computes a proposed forward position, and tests the swept segment from the previous position to that proposed position against the target hit sphere. It then decreases lifetime and returns a `MissileStep` containing the updated position plus `hit` or `expired`. A hit takes precedence over expiry when the same step intersects the target; the missile itself does not mutate aircraft health, while the rule/controller layer validates target identity and applies one guarded damage event.

## Aircraft Screen Target

This is a transient scene-to-HUD value, not persistent session state.

| Field | Type | Rules |
|---|---|---|
| `visible` | boolean | Camera-to-aircraft ray is clear |
| `screen_position` | 2D vector | Aspect-correct normalized HUD position |
| `screen_radius` | positive float | Projected aircraft size with a minimum readable radius |
| `distance_from_center` | non-negative float | Distance to HUD center |
| `in_lock_zone` | boolean | Distance is no greater than the 15% diameter circle radius and visible is true |

## Session and Lifecycle Invariants

- Only one active aircraft id is valid at a time; every missile target id must match it to affect gameplay.
- `AIRSTRIKE` may have zero or more active missiles; `GROUND_COMBAT`, `GAME_OVER` and `MAIN_MENU` have none.
- Aircraft impact, aircraft destruction, player death and city destruction remain guarded first events.
- A missile can damage an aircraft at most once, and an aircraft damage event can transition to ground combat at most once.
- Scope close and weapon switching clear lock state but do not cancel missiles while the same aircraft remains active; aircraft terminal events, ground-combat transition, game over and return to menu remove all missiles before any later target can spawn or receive damage.
- Existing wave, encounter, Boss HP, city HP and statistics invariants from 002 remain unchanged.
