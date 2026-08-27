# Research: 防空鎖定、機頭飛行與導引飛彈

## Context Reviewed

- `air_defense.rules.LockOnTracker` currently resets progress immediately whenever the center ray no longer sees the aircraft.
- `can_fire_anti_air` currently checks only weapon, green state and cooldown.
- `air_defense.entities.Aircraft` currently derives position from a start/target interpolation plus a lateral sine offset; the scene calls `look_at` toward the target independently of movement.
- `air_defense.scene.AirDefenseScene` currently uses a center raycast for aircraft visibility and `set_scope_enabled` only bridges the existing sniper 90°/35° FOV behavior.
- `air_defense.main.AirDefenseGame._fire_anti_aircraft` currently applies aircraft damage immediately and only creates an explosion when the aircraft is removed.
- The installed Ursina `FirstPersonController` exposes `mouse_sensitivity`, while the camera exposes a Panda3D perspective lens after the game window is initialized. The lens API supports projection of a 3D point into screen coordinates.

## Decision 1: Screen-space lock zone and visibility

**Decision**: Evaluate the active aircraft center in aspect-correct screen coordinates. Treat it as lockable when it is inside a hidden circular zone whose diameter is 15% of the viewport's shorter dimension. Use a camera-to-aircraft visibility ray rather than requiring the ray to hit the exact center of the screen.

**Rationale**: The user wants a forgiving circular tracking area instead of a single center pixel, while the existing obstacle/visibility rule should still prevent locking through an obstruction. Screen projection is the smallest reliable bridge between a 3D target and a HUD element, and it keeps the acquisition rule independent from the rendered reticle geometry.

**Alternatives considered**:

- Keeping the center ray would make most of the new circle meaningless and would preserve the overly brittle behavior.
- Ignoring visibility would allow a target behind a collidable object to lock, contradicting the existing obstruction semantics.
- Making the circle radius 15% rather than its diameter would double the intended tolerance and make tracking too permissive.

## Decision 2: Lock progress and fire gating

**Decision**: Extend the tracker with a progress value and a 0.75-second decay window. Progress increases at real time while the target is in-zone and visible; outside the zone it decreases linearly at a rate that reaches zero in 0.75 seconds. A target outside the zone is never fireable, even if progress is still 100% during decay.

**Rationale**: This preserves the user's requested recovery window without allowing a player to fire after losing the target. Re-entry before zero naturally resumes from the remaining value and is simple to verify with deterministic delta-time tests.

**Alternatives considered**:

- Immediate reset was rejected because it creates the reported frustration when an aircraft turns sharply.
- Allowing fire during decay was rejected because it makes the visible target-zone requirement ineffective.
- Keeping a separate `DECAYING` enum was rejected; the existing red tracking state plus progress and target-in-zone flag conveys the same information with less state churn.

## Decision 3: Anti-air scope and aim assistance

**Decision**: Add an anti-air-specific right-click toggle scope at an initial 55° FOV; button release has no effect and the next right-button press closes it. Lock accumulation and aim assist are active only while this scope is open. Define the near-assist band as a visible target within 1.5 times the lock-zone radius from screen center, and apply a capped 3°/second angular pull after the normal mouse rotation. Use a capped angular pull toward the target, not a global sensitivity mutation or a forced snap. Keep the existing sniper scope at 35° and normal view at 90°.

**Rationale**: Separate scope modes prevent sniper behavior from being coupled to air-defense tuning. The installed controller already accepts camera and mouse state changes, so a small scene-level correction can be added without modifying the dependency. A capped pull preserves player control and is easier to disable/reset than changing controller internals every frame.

**Alternatives considered**:

- Reducing global mouse sensitivity was rejected because it changes the feel even when the target is not near the reticle and does not help correct angular error directly.
- Strong snap-to-target was rejected because it can override player intent and make a fast aircraft feel automated.
- Joystick support was deferred because the current project has no gamepad input abstraction and the specification explicitly keeps this version mouse-only.

## Decision 4: Forward-only aircraft kinematics

**Decision**: Store a mutable position and forward vector for each aircraft. Each update turns toward a deterministic target/evasion direction by bounded yaw and pitch rates, then moves only along the current forward vector. Keep type-specific speed and evasion profiles, but express evasion by changing desired heading rather than adding a lateral position offset. The second-stage balance baseline uses `24.0/0.25/48/22` for normal, `16.0/0.20/34/16` for manpower support, `32.0/0.40/70/30` for fast and `20.0/0.22/30/14` for armored Boss, in amplitude/frequency/max-yaw/max-pitch order.

**Rationale**: The requirement is about movement semantics, not just model orientation. Updating a forward vector makes it possible to test that displacement follows the nose and prevents the scene from visually turning independently of actual travel. The first wider-turn pass was still too subtle in play traces, so the second-stage values increase route amplitude, slow the reversal frequency and raise bounded turn rates enough to make evasion legible without adding a lateral teleport.

**Observed balance guard**: A deterministic 10-second trace with the second-stage defaults produces horizontal path spans of `4.678505` (normal), `2.883718` (manpower support), `7.885713` (fast) and `2.727640` (armored Boss) world units. The fast aircraft remains the most evasive, while all four profiles continue to move only along their current forward vector.

**Alternatives considered**:

- Retaining the lateral sine offset would violate the no-sideways movement rule even if the model were rotated.
- Calling `look_at(target)` without changing movement would create a visual-only fix and could hide incorrect physics.
- A full physics engine was rejected because the prototype only needs deterministic kinematic steering and must not add a dependency.

## Decision 5: Delayed multi-missile damage

**Decision**: Add an engine-independent guided missile state object per valid shot. The scene represents it as a yellow rectangular cuboid. It advances toward its bound aircraft using forward-only steering; collision is tested against the swept segment from the previous position to the proposed position so high-speed missiles cannot tunnel through the target. A valid collision applies one damage point, then creates one explosion and expires. Multiple missiles may be in flight while the weapon cooldown and new lock gate later shots.

**Rationale**: Delayed collision is required for the requested visual cause-and-effect and allows aircraft movement to remain meaningful after firing. Binding each missile to an aircraft id prevents delayed callbacks from affecting the next target.

**Alternatives considered**:

- Immediate damage with a decorative projectile was rejected because it would not make collision the actual hit event.
- A one-missile restriction was rejected because the confirmed design allows re-locking and firing again after cooldown.
- Engine physics bodies were rejected in favor of deterministic swept-segment distance checks, which are sufficient for one active aircraft, prevent endpoint tunneling and are directly unit-testable.

## Decision 6: Deterministic update ordering and cleanup

**Decision**: Within the airstrike update, advance the aircraft first; resolve building impact before missile contacts for an exact same-frame tie; otherwise resolve missile contacts in stable creation order; then update lock state and HUD. Any aircraft terminal event removes every missile bound to that aircraft before ground combat or the next aircraft begins.

**Rationale**: An explicit order avoids ambiguous outcomes and satisfies the existing first-event and stale-event protections. Stable insertion order makes multi-hit Boss tests reproducible.

**Alternatives considered**:

- Allowing engine callback order to decide would make simultaneous events non-deterministic.
- Processing missiles after spawning the next aircraft risks stale damage crossing the aircraft boundary.

## Decision 7: Procedural HUD geometry and centralized tuning

**Decision**: Keep the permanent acquisition circle hidden. Build the visible tracking ring as one continuous ordinary circle in the user's image-2 style—not segmented tick marks—positioned from the target's screen projection. Interpolate its radius from the acquisition radius to the target screen radius plus a small padding. Add a larger fixed frame, a horizontal progress bar and a percentage label. Put FOV, lock, steering, assist and missile values in `air_defense/config.py`.

**Rationale**: The repository already supports procedural primitives and has no mandatory external art. Centralized tuning lets playtesting adjust feel without changing rule interfaces or scattering constants through the adapter.

**Alternatives considered**:

- A target-attached 3D ring was rejected because it would not remain a stable HUD element under camera motion and zoom.
- A texture asset was rejected because it adds an unnecessary dependency and violates the asset-free fallback boundary.
- Scattered magic numbers were rejected by the constitution's configuration rule.

## Dependency and Compatibility Result

No new package, service, storage or input framework is required. The work stays within `air_defense/`, `tests/` and this feature directory, preserves the existing 002 wave/Boss contract except for the explicitly superseded lock details, and keeps `day1/` and `day2/` untouched.

## Acceptance Evidence Decision

The measurable success criteria are treated as acceptance evidence rather than unverified claims. SC-001 uses five independent participants with a first-second comprehension record; SC-002–SC-006 each use ten independent repetitions with pass/fail and failure reasons; SC-007 uses a 30-second maximum-load observation with operating system, hardware, average FPS and minimum FPS. The Quickstart and final validation tasks own these records.
