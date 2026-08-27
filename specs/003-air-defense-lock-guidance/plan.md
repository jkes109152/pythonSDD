# Implementation Plan: 防空鎖定、機頭飛行與導引飛彈

**Branch**: `003-air-defense-lock-guidance` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `./spec.md`

## Summary

把目前空襲階段的「中心射線直接判定、失去目標立即清零、按下即扣血」改成可讀且可驗證的防空瞄準流程：防空炮右鍵開鏡後，以敵機畫面投影是否位於螢幕短邊直徑 15% 的圓形區域判定鎖定；進度在 3 秒內累積、離區後 0.75 秒線性衰減；HUD 顯示放大固定框、跟隨敵機的縮小圈與水平進度條。敵機改用機頭 forward vector 前進並以受限偏航／俯仰轉向，第二階段再把四種敵機的閃避調整為更寬、更明顯且仍可預判的遊戲內轉彎；防空射擊改為可同時存在的黃色實體追蹤飛彈，碰撞時才造成傷害與爆炸。

純規則仍與 Ursina 分離；`scene.py` 負責投影、視線、鏡頭、吸附與程序化視覺，`hud.py` 負責鎖定視覺，`main.py` 負責更新順序、飛彈生命週期與既有波次／Boss 事件整合。

## Technical Context

**Language/Version**: Python 3.13 in the current environment; retain the existing Python 3.12+ game requirement.

**Primary Dependencies**: Existing `ursina==8.3.0` with Panda3D runtime, plus Python standard library modules and `unittest`; no new dependency.

**Storage**: N/A; lock, aircraft, missile and scope state remain in memory and reset with the session.

**Testing**: `compileall`, engine-independent `unittest`, real Ursina smoke checks and the manual acceptance flow in [quickstart.md](./quickstart.md).

**Target Platform**: Windows desktop, offline single-player, keyboard and mouse input, graphics-capable window.

**Project Type**: Single-player desktop 3D game.

**Performance Goals**: Preserve the existing 60 FPS target with one active aircraft, multiple cooldown-limited missiles and the largest existing ground encounter; lock and HUD changes appear on the next rendered frame. The acceptance run observes the maximum-load scene for at least 30 seconds and records average and minimum FPS.

**Constraints**: Preserve the 002 wave/Boss lifecycle and `day1`/`day2` isolation; keep domain modules free of Ursina; use procedural geometry; permit multiple missiles but only one active aircraft; do not add joystick support in this feature.

**Scale/Scope**: One active aircraft, a bounded list of in-flight guided missiles, one player camera, one anti-air scope, one lock HUD, existing four aircraft types, waves and ground encounters.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Readability and incremental abstraction**: PASS. Add focused lock, vector-turning and missile value objects/functions only where the existing direct implementation cannot express the new behavior clearly.
- **II. Encapsulated game objects**: PASS. Aircraft and missiles own movement state; the tracker owns lock progress; cross-object damage and session transitions remain in named rule/controller functions.
- **III. Small, verifiable steps**: PASS. Lock decay, projection boundaries, forward movement, steering, missile collision and cleanup are independently testable before scene integration.
- **IV. Explicit loop and state transitions**: PASS. The existing four phases remain. The airstrike update order explicitly handles aircraft impact, missile collision, lock state, fire reset and stale-target cleanup.
- **V. Appropriate scope and simple dependencies**: PASS WITH EXISTING SCOPED EXCEPTION. The feature reuses the already approved Ursina/Panda3D 3D game package, adds no dependency or service, and stays inside the existing package and tests.

**Gate result**: PASS. No new constitution exception is required; the existing isolated 3D-game exception documented by 001/002 is reused.

## Project Structure

### Documentation (this feature)

```text
specs/003-air-defense-lock-guidance/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Created by $speckit-tasks; not part of this phase
```

### Source Code (repository root)

```text
air_defense/
├── config.py       # scope, lock, steering, missile and UI tuning values
├── state.py        # scope/lock session fields and existing guarded phases
├── rules.py        # lock decay, projection math, steering and missile rules
├── entities.py     # forward-flight Aircraft and GuidedMissile state
├── scene.py        # camera projection, visibility, aim assist and missile visuals
├── hud.py          # enlarged frame, tracking ring and progress bar
└── main.py         # input, update ordering, missile/aircraft lifecycle integration

tests/
├── test_rules.py          # existing regression suite, extended where compatible
└── test_airstrike_guidance.py  # focused lock, flight and missile rule cases
```

**Structure Decision**: Extend the existing shallow `air_defense` package. Keep state and movement/collision math importable without Ursina; keep camera projection, UI entities and procedural yellow missile visuals in the scene adapter; keep orchestration in `main.py`. Do not create a new engine, service, asset pipeline or input framework.

## Design Overview

### Lock and targeting pipeline

1. Selecting slot `1` shows the enlarged anti-air frame but does not accumulate lock.
2. Right-click is a toggle: the button-down event opens or closes anti-air scope, button release has no effect, and opening scope resets any stale lock state. Opening sets the camera to the dedicated initial FOV of 55°; closing restores normal FOV and clears lock state.
3. During scope, project the active aircraft center and bounding samples into aspect-correct screen coordinates. A target is lockable when its center is inside the hidden circular acquisition zone and a camera-to-aircraft ray is not blocked.
4. `LockOnTracker` increases progress at one second per second while lockable. Otherwise it decreases linearly to zero over 0.75 seconds. The state is green only when progress is full and the target is currently inside the zone; fire gating also requires the current in-zone flag.
5. HUD keeps the fixed frame centered, positions the tracking ring at the projected aircraft point, interpolates its radius from the acquisition radius to the aircraft screen radius plus padding, and updates the horizontal bar/percentage. During decay the ring expands as progress falls.

### Aircraft movement and aim assist

- Replace the current direct lateral sine offset with mutable aircraft position, forward direction, yaw/pitch and flight elapsed state. Each update rotates toward a deterministic target/evasion direction by configured maximum yaw and pitch rates, then advances only by `forward * speed * delta`.
- Preserve continuous approach, type-specific speed/evasion profiles, impact timing and `Aircraft.advance(delta_seconds)` compatibility for existing callers. Scene orientation uses the stored forward vector rather than `look_at(target)` so the model cannot visually turn without moving in that direction.
- While anti-air scope is open, the target is visible and its projected center is no farther from the screen center than 1.5 times the lock-zone radius, apply a capped angular correction toward the projected target after the existing mouse rotation for that frame. The correction is at most `3°/second * delta_seconds`, is clamped at the boundary, is deliberately weaker than direct mouse input, and is disabled outside scope, beyond the band or after target loss. The version does not add joystick support.

The second-stage default evasion profile uses amplitude/frequency/yaw/pitch values of `24.0/0.25/48/22` for normal, `16.0/0.20/34/16` for manpower support, `32.0/0.40/70/30` for fast and `20.0/0.22/30/14` for armored Boss. The larger amplitudes and lower frequencies create visible, deliberate turns while the bounded rates and forward-only update preserve fair, nose-led movement. A deterministic 10-second trace verifies horizontal spans above `4.0/2.5/7.0/2.4` world units respectively, with fast remaining more evasive than normal.

### Guided missile lifecycle

- A valid anti-air shot creates a domain `GuidedMissile` bound to the current aircraft id and a yellow cuboid scene entity. The shot resets lock progress and starts the existing 1.25-second weapon cooldown; it does not immediately damage the aircraft.
- Every frame advances missiles with forward-only steering toward the live aircraft position. Collision uses the swept segment from the previous missile position to its proposed position against the target's current hit sphere, so a missile cannot tunnel through the aircraft between frames. A collision consumes that missile, applies exactly 1 aircraft damage, creates one explosion and removes the missile entity. Cooldown completion plus a new green in-zone lock may create another missile while earlier missiles remain active.
- The airstrike update order is: advance aircraft; resolve aircraft impact if it has reached the building; if still active, advance missiles and resolve swept contacts in insertion order; then update scope lock and HUD. Impact wins an exact same-frame tie because it is evaluated first. Any terminal aircraft event removes all missiles bound to that aircraft id before another contact or aircraft transition.
- If the aircraft is destroyed, `resolve_aircraft_outcome` and the existing ground encounter transition run once. Stale missiles are removed before the next aircraft is spawned and cannot damage or count against it.

### Camera, HUD and reset integration

- Add separate anti-air scope state beside the existing sniper scope. Anti-air uses FOV 55°, sniper remains at 35°, normal view remains at 90°; right-button release never toggles scope.
- Build the tracking ring as one continuous ordinary circle (the user's image-2 style) with a code-native UI primitive or equivalent procedural circle; do not use segmented tick marks or an image-1-style dashed ring. No external texture is required. The permanent 15% acquisition zone is logic-only, while the tracking ring is visible only during active anti-air scope and target tracking/decay.
- Add explicit reset paths for scope close, weapon switch, drop, aircraft transition, game over and return to menu. Reticle families remain mutually exclusive.

## Public Internal Interfaces

- `LockOnTracker(lock_duration=3.0, decay_duration=0.75)` exposes `set_scope_enabled(enabled)`, `update(target_in_zone, delta_seconds)`, `progress`, `target_in_zone`, `scope_enabled`, `state`, `reset()` and existing blink behavior. Closing scope through `set_scope_enabled(False)` immediately resets to white/zero; `update` is only allowed to accumulate or decay while scope is enabled and never makes a target outside the zone fireable.
- `can_fire_anti_air(lock_state, cooldown_remaining, held_weapon, target_in_zone=False) -> bool` fails closed when the current zone result is omitted, and requires an explicit `True` from the current visibility/zone evaluation for new callers.
- `Aircraft.advance(delta_seconds)` remains the domain entry point; aircraft state additionally exposes current position, forward vector, heading and profile turn limits. Position changes are bounded by speed × delta.
- `GuidedMissile.advance(delta_seconds, target_position) -> MissileStep` returns the updated position plus `hit`/`expired` outcome; hit evaluation uses the swept movement segment and configured target radius, and the missile carries the target aircraft id so stale events can be rejected.
- Scene adapter methods expose target lock information (`visible`, projected position, projected radius, in-zone result), separate anti-air scope control, aim-assist application and missile entity create/update/remove operations.
- `GameHUD.update_lock(...)` accepts progress and target projection data; the existing `update_reticle(...)` interface remains the single place that enforces mutually exclusive weapon reticles.

## Implementation Sequence

1. Add focused failing rule tests for toggle/scope gating, lock accumulation/decay/fire gating, circular boundary math, forward-only aircraft steering, the 1.5× aim-assist band and cap, swept missile collision and stale-target cleanup.
2. Add centralized tuning values and extend `LockOnTracker`, anti-air fire gating, aircraft movement state and `GuidedMissile` without importing Ursina; make all domain tests pass.
3. Extend the scene adapter with aspect-correct aircraft projection, non-center target visibility raycasts, anti-air FOV, bounded aim assist, forward model orientation and yellow missile visuals.
4. Rebuild the anti-air HUD with the larger fixed frame, tracking ring, progress bar, percentage and scope-only lock presentation while preserving sniper/pistol behavior.
5. Integrate the new right-click anti-air scope, frame update order, delayed missile damage, multiple in-flight missiles, collision explosions and terminal cleanup in `main.py`.
6. Run full regression tests, real Ursina smoke checks, the 5-participant/10-run acceptance matrix and the 30-second maximum-load performance observation; adjust only centralized tuning values and record observed limits.

## Testing Strategy

- **Pure lock tests**: toggle/scope gating, explicit scope-close reset, 15% circle inside/boundary/outside cases, 3-second completion, 0.25-second partial decay, 0.75-second reset, resume-before-zero and no-fire-during-decay.
- **Pure flight tests**: displacement never exceeds speed × delta, displacement follows the current forward vector, yaw/pitch changes obey caps, evasion changes direction continuously and no lateral teleport remains; a deterministic 10-second trace also checks the second-stage horizontal-span thresholds of 4.0/2.5/7.0/2.4 world units for normal/support/fast/armored profiles.
- **Pure missile tests**: moving-target pursuit, bounded steering, swept-segment collision at high speed, collision damage exactly once, multiple missiles, expiry, target-id validation, aircraft-impact cleanup and no cross-aircraft damage.
- **Scene/HUD smoke tests**: anti-air FOV 55/90 transitions, sniper FOV 35 regression, projected ring movement and shrinking, progress bar visibility, reticle exclusivity, procedural yellow cuboid and explosion.
- **Regression/manual tests**: existing 002 wave/Boss/ground flow, empty encounters, five-hit armored aircraft, reset behavior, `compileall`, all `unittest` tests, the 5-participant/10-run acceptance evidence and the full [quickstart.md](./quickstart.md) protocol.

### Acceptance Evidence

- SC-001 uses five independent participants and records each participant's first-second interpretation of the fire condition; at least four must be correct.
- SC-002–SC-006 each use ten independent repetitions and record pass/fail plus the failure reason. Deterministic cases may provide the repeated evidence for pure rules, while visual and transition cases use the manual flow.
- SC-007 uses the largest supported scene for a continuous 30-second observation with one aircraft, several missiles, the long map, fixed obstacles and the largest ground encounter; record OS, hardware, average FPS and minimum FPS, or explicitly record why the run was unavailable.

## Post-Design Constitution Check

- **Principles I–III**: PASS. The design uses focused domain objects, retains the shallow module layout and defines deterministic tests before engine integration.
- **Principle IV**: PASS. Scope, missile, impact, aircraft transition and reset states have explicit ordering and duplicate/stale-event guards.
- **Principle V**: PASS WITH EXISTING SCOPED EXCEPTION. No new dependency, service or asset requirement is introduced; the existing approved Ursina 3D boundary is reused.

## Complexity Tracking

No new constitution exception is required. The only platform exception is the existing isolated Ursina/Panda3D game package documented in `specs/001-air-defense-game/` and `specs/002-air-defense-wave-expansion/`.
