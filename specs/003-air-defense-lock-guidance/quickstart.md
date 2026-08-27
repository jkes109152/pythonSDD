# Quickstart: 防空鎖定、機頭飛行與導引飛彈

## Prerequisites and Setup

Use the existing game environment from the repository root:

```powershell
Set-Location 'C:\Users\lamun\OneDrive\Desktop\pythonSDD'
python -m pip install -r requirements-game.txt
```

No additional dependency, joystick driver or external model is required for this feature.

## Automated Validation

```powershell
python -m compileall air_defense tests
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected result: compilation succeeds and the full deterministic suite passes without opening a game window.

Observed adapter smoke (2026-08-27, Windows/Python 3.13):

```powershell
python -c "from air_defense.main import create_application; from ursina import camera; app, game = create_application(); game.start_game(); game.input('1'); game.input('right mouse down'); game.update(); print(game.session.anti_air_scope_enabled, camera.fov, game.hud.lock_frame.enabled, game.hud.lock_bar_background.enabled, game._aircraft_screen_target is not None); app.userExit()"
```

Result: `True 55.0 True True True`. The real Ursina adapter created the gameplay scene, opened the anti-air scope at 55°, enabled the enlarged lock frame/progress bar and produced a projected aircraft target. The window backend emitted its existing foreground/focus warnings; no fatal error occurred.

Observed deterministic decay/fire-gate check (2026-08-27): the focused suite records 100% → 66.7% after 0.25 s outside the circle, resumes from the remaining value on re-entry, reaches 0% after the full 0.75 s buffer, and rejects firing whenever `target_in_zone` is false.

Observed real-adapter flight step (2026-08-27, 12 × 0.1 s): with the anti-air scope open, the aircraft heading samples changed from `(-0.0325, -0.0718, -0.9969)` through `(0.0364, -0.0730, -0.9967)` to `(0.0402, -0.0876, -0.9953)`; 11 consecutive heading changes were observed while the scene adapter updated the aircraft orientation. This confirms the implemented forward-steering path; a longer hands-on evasion observation remains part of the manual flow.

Observed guided-missile adapter smoke (2026-08-27): a valid green in-zone shot created one yellow cuboid missile and left aircraft HP unchanged before the update; forcing the deterministic missile into the target on the next collision step reduced HP from 5 to 4, removed the missile, and left one explosion effect. This verifies delayed collision-time damage and visual cleanup; the full moving-target manual timing remains listed below.

Observed scope/FOV/reset smoke (2026-08-27): opening anti-air reported `(55.0, 'Circle', True, True)`; a right-button release left FOV at `55.0`; closing returned FOV to `90.0`, reset progress and hid the lock UI. An in-flight missile count stayed `1 → 1` across scope close. The existing sniper smoke returned `35.0` and showed its crosshair while the anti-air frame was hidden.

Observed T040 lockability regression fix (2026-08-27): the visibility ray now unwraps Ursina's `HitInfo.entity` and follows the hit entity's parent chain to the active aircraft. With the real adapter camera centered on the aircraft, projection reported `target=True`, `visible=True`, `in_lock_zone=True`; running the normal airstrike update for 30 × 0.1 seconds reported `lock_elapsed=3.0`, `GREEN_READY`, `target_in_zone=True`. The post-fix full suite completed with 56 tests passed.

Observed T041 evasion tuning (2026-08-27): high-frequency small wobble was changed to wider, slower nose-led turns. In deterministic 10-second traces, horizontal path span increased from approximately `0.15` to `2.88` world units for the normal aircraft and from `0.35` to `5.20` for the fast aircraft. Forward-only displacement and yaw/pitch bounds remained green, and a post-tuning real-adapter lock still reached `3.0`, `GREEN_READY`, `visible=True`, `in_lock_zone=True`. The full suite completed with 57 tests passed.

Observed T042 second-stage evasion tuning (2026-08-27): the first tuning pass was still not energetic enough, so the centralized defaults were raised to normal `24.0/0.25/48/22`, manpower support `16.0/0.20/34/16`, fast `32.0/0.40/70/30` and armored Boss `20.0/0.22/30/14` in amplitude/frequency/max-yaw/max-pitch order. Deterministic 10-second horizontal path spans are `4.678505`, `2.883718`, `7.885713` and `2.727640` world units respectively; forward-only displacement and bounded steering tests remained green. The focused and full suites completed with 58 tests passed; the real-adapter lock smoke was rerun after tuning and still reached `3.0`, `GREEN_READY`, `visible=True`, `in_lock_zone=True`.

Observed T043 local code review (2026-08-27): terminal transitions could leave the independent `LockOnTracker` and projected aircraft target populated after `GameSession` had already reset. `_on_aircraft_destroyed` and `_present_game_over` now use the centralized guidance reset, clear the projected target, and force the scope tracker closed. The review also found that selecting the anti-air weapon hid the enlarged fixed frame before scope opened; `update_reticle` now keeps that frame visible while showing dynamic lock information only in scope. Empty ground encounters previously cleared a just-created missile explosion immediately; encounter cleanup now preserves short-lived effects until `tick_effects` expires them. Four lifecycle/scene cleanup regression tests and the real HUD smoke cover these paths; the post-review full suite completed with 62 tests passed.

Focused rule coverage must include:

- Right-button toggle semantics, immediate scope-close reset and 15% circular lock-zone inside, boundary and outside cases.
- 3-second accumulation, 0.25-second partial decay, 0.75-second reset and re-entry resume.
- No fire while the target is outside the zone or decaying.
- Forward-only aircraft displacement, bounded yaw/pitch turns and no lateral teleport.
- Aim-assist 1.5× activation boundary, 3°/second cap after mouse rotation and scope-only activation.
- Guided missile pursuit, swept-segment high-speed collision, hit-before-expiry precedence, one-hit collision, multiple in-flight missiles, expiry and stale-target cleanup.

## Launch

```powershell
python -m air_defense.main
```

## Manual Acceptance Flow

1. Start a new game and press `1`. Confirm the enlarged anti-air frame appears and the existing wave/aircraft HUD remains visible. The target-tracking indicator is one continuous ordinary circle (the image-2 style), not segmented tick marks.
2. Press and release right mouse once. Confirm the anti-air view changes from 90° to the dedicated approximately 55° FOV; releasing the button must not close it. Confirm the lock bar and percentage are visible only in this scope. Press right mouse again and confirm the scope closes and the FOV returns to 90°.
3. Move the view so the aircraft projection enters the hidden central circular zone. Hold it there for 3 seconds. Confirm the ring follows the aircraft, shrinks toward its outline, the progress bar reaches 100%, and the state becomes `可發射`.
4. Move the aircraft outside the zone for roughly 0.25 seconds. Confirm progress decreases but does not become 0%; press left mouse and confirm no missile launches. Return to the zone before 0.75 seconds and confirm progress resumes. Keep it outside for at least 0.75 seconds and confirm the state returns to `未鎖定`.
5. Observe the aircraft through at least two of the stronger second-stage evasion changes. Confirm it makes wide but deliberate turns by rotating its nose first, moves continuously along its nose direction, never reverses or slides sideways, and does not teleport. While scoped, verify the aim assist activates at or inside 1.5× the lock-zone radius, never exceeds 3°/second, and stops beyond the boundary or after target loss.
6. Complete a green in-zone lock and press left mouse. Confirm a yellow elongated cuboid leaves the firing point, follows the aircraft, collides, creates one explosion and applies one aircraft damage event. During flight, after cooldown and a new lock, fire again and confirm multiple missiles can coexist.
7. Use a wave-10 armored aircraft or a controlled test state. Confirm each missile collision removes exactly 1 HP and the existing five-hit Boss transition still occurs. Confirm stale missiles disappear when the aircraft is destroyed or impacts.
8. Close anti-air scope after a shot and confirm FOV returns to 90°, lock progress/ring/bar/assist disappear, while an in-flight missile continues. Switch/reset the game or complete the aircraft terminal transition and confirm no missile remains. Select the sniper and confirm its existing 35° scope still works; select the pistol and confirm the anti-air UI stays hidden.
9. Repeat the existing 002 manual wave, ground-combat, city-destruction and reset flow to confirm no regression outside the airstrike targeting changes.

## Initial Tuning Reference

| Item | Initial value |
|---|---:|
| Normal FOV | 90° |
| Anti-air scope FOV | 55° |
| Sniper scope FOV | 35° |
| Lock duration | 3.0 seconds |
| Lock decay | 0.75 seconds |
| Lock-zone diameter | 15% of viewport short side |
| Missile speed | 90 world units/second |
| Missile turn rate | 240°/second |
| Missile hit radius | 1.5 world units |
| Missile lifetime | 5.0 seconds |
| Aim-assist cap | 3°/second |

These are centralized starting values. Any balance adjustment must be recorded with the observed manual result.

### Stronger Evasion Tuning

| Aircraft | Evasion amplitude | Frequency | Max yaw | Max pitch |
|---|---:|---:|---:|---:|
| Normal | 24.0 | 0.25 Hz | 48°/s | 22°/s |
| Manpower support | 16.0 | 0.20 Hz | 34°/s | 16°/s |
| Fast | 32.0 | 0.40 Hz | 70°/s | 30°/s |
| Armored Boss | 20.0 | 0.22 Hz | 30°/s | 14°/s |

## Performance Check

Measure the largest supported playable scene for a continuous 30-second run: one active aircraft, several in-flight missiles, the long map, all fixed obstacles and the largest existing ground encounter. Record average FPS, the lowest observed FPS, operating system and hardware. The target is 60 FPS; report any shortfall rather than inferring a result.

## Acceptance Evidence Record

- SC-001: use five independent participants; after showing the first second of the scoped HUD without coaching, record each participant's answer about the fire condition. At least four correct answers are required.
- SC-002–SC-006: perform ten independent repetitions for each criterion and record every pass/fail result plus the failure reason. Pure-rule repetitions may use deterministic tests; visual and lifecycle repetitions use the manual flow.
- SC-007: use the 30-second maximum-load run above and record average FPS, minimum FPS, operating system and hardware. If a graphics-capable run is unavailable, record the reason and leave the result unclaimed.
- Do not infer a complete success criterion from a single successful run or from an unmeasured headless check.

## Known Limitations

The existing Ursina/Panda3D focus, font, cache and remote-desktop warnings documented in `specs/001-air-defense-game/quickstart.md` still apply. This feature does not claim joystick support or a numeric performance result until a graphics-capable manual run records one.

## Phase 7 Evidence Record

- T034: `python -m compileall air_defense tests` completed successfully; `python -m unittest discover -s tests -p "test_*.py" -v` completed with 55 tests passed.
- T035: The real Ursina adapter smoke checks recorded the 55° anti-air scope, 35° sniper regression, continuous `Circle` lock-ring model, reticle exclusivity, projected target, yellow cuboid missile, delayed collision damage, one explosion effect and reset behavior above. The existing foreground/focus warnings were non-fatal.
- T036: `python -m unittest tests.test_rules -v` completed with 37 tests passed, covering the existing 002 rule regression surface. This implementation made no edits to `day1/` or `day2/`; the pre-existing user change `M day2/prj06.py` was retained. The full hands-on wave/ground/Boss/city manual flow was not available in this run and remains unclaimed.
- T037: Review found no new dependency or external asset, no duplicate lock/steering rule path, guarded target-id and terminal-state missile damage, and reset coverage for scope close, aircraft terminal events, menu return and game-over. Scope limitations remain: joystick behavior, five-participant comprehension and graphics performance require hardware/user sessions; the continuous circle is implemented as a code-native Ursina procedural model.
- T038: Not executed as a human acceptance study because five independent participants were unavailable. The deterministic focused suite was repeated 10 times (`1..10 | ForEach-Object { python -m unittest tests.test_airstrike_guidance -q }`), with 18/18 tests passing in each repetition; this does not claim the visual/manual portions of SC-001–SC-006.
- T039: A 30-second maximum-load FPS run with recorded hardware was unavailable in this environment, so average/minimum FPS and SC-007 remain unclaimed rather than inferred.
- Computer Use attempt (2026-08-27): with the user's permission, the existing `python -m air_defense.main` process was started twice through a visible launch path and checked through the Windows window-control API. Panda3D reported its normal startup messages, but `list_apps()`/`list_windows()` exposed no targetable `3D 防空守衛` window (the process had no main window handle). No stale coordinates or terminal UI automation were used, and no manual mouse result is claimed from this attempt.
