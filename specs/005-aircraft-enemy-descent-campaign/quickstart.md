# Quickstart: 飛機擊落後敵人降落戰役

**Feature**: `005-aircraft-enemy-descent-campaign`
**References**: [spec.md](./spec.md), [data-model.md](./data-model.md), [UI contract](./contracts/ui.md)

## Prerequisites

- Windows desktop with a graphics-capable display.
- Python 3.12 or newer. The feature was planned against the workspace Python 3.13.5 baseline.
- Existing game dependency `ursina==8.3.0` from `requirements-game.txt`.
- Run commands from the repository root.

If the game dependency is not installed in the active environment:

```powershell
python -m pip install -r requirements-game.txt
```

## Automated validation

Run syntax validation:

```powershell
python -m compileall -q air_defense tests
```

Expected result: command exits successfully without syntax errors.

Run the complete unit suite:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected result: all baseline and feature tests pass, including fixed roster, source-scoped drop, descent timing, hybrid weapon gates, two-condition wave clear, victory and reset cases.

Run the graphical application smoke check:

```powershell
python -m air_defense.main
```

Expected result: the Ursina window opens, the main menu is responsive, and no import or attribute error occurs while starting a game.

## Manual acceptance flow

1. Start a new game from the main menu and equip the anti-aircraft weapon.
2. In a wave containing at least two aircraft, lock and destroy one aircraft while the other remains in flight.
3. Confirm the destroyed aircraft visual disappears and its enemy batch appears immediately at the saved hit location.
4. Switch with `2` and `3`. Confirm sniper and pistol are available as soon as the first non-empty batch begins descending, while the remaining aircraft continue flying.
5. Aim at a descending crew member and fire. Confirm the member disappears immediately, counts once as defeated, and does not attack or damage the city before landing.
6. Let another crew member complete its approximately four-second descent. Confirm it lands at the hit point's X/Z position and then follows the existing ground movement and attack behavior.
7. Destroy another aircraft before the existing ground encounter is cleared. Confirm its batch joins the same wave encounter and descends independently.
8. Confirm the next wave does not start until every aircraft has status `DESTROYED` and every descending or landed crew member is cleared; an `IMPACTED` aircraft must fail the campaign instead.
9. Progress through the fixed campaign and verify the wave table in `spec.md`, especially Boss waves 4, 9, 15, 16, 17 and 18. Confirm Boss slots remain left-to-right, the first `特` resolves to `MANPOWER_SUPPORT`, the second to `FAST`, and each Boss aircraft produces its existing ground Boss.
10. Clear all four Boss aircraft and all resulting ground Bosses in wave 18. Confirm the game freezes on `你贏了`, no wave 19 appears, and Enter, Escape or `返回主選單` returns to a clean main menu.

## Boundary checks

- Destroy a `FAST` aircraft and confirm it produces no empty ground encounter.
- Destroy two aircraft in adjacent frames and confirm both batches remain visible with independent descent timers.
- Kill a descending member just before its landing time and confirm it does not land or attack afterward.
- Allow an aircraft to impact the city during hybrid combat and confirm failure takes precedence over all drops and ground updates.
- Return to the main menu from both failure and victory, restart, and confirm no old aircraft, crew, missile, scope, cooldown or wave state remains.

## Acceptance Evidence Protocol

For each run, record the date, commit, wave or fixture, observed result, and pass/fail outcome. The required sample counts are:

| Criterion | Minimum runs | Pass condition |
|---|---:|---|
| SC-001 | 10 | Every eligible aircraft starts its own visible drop immediately after destruction. |
| SC-002 | 20 | Every descent completes in 4.0 ± 0.25 seconds, preserves hit-point X/Z with configured offset, and has no complete member overlap. |
| SC-003 | 20 | Every airborne kill removes exactly one member and causes no descent-time attack or city damage. |
| SC-004 | 10 | Remaining aircraft continue operating and all three weapons work in the same wave. |
| SC-005 | 1 complete campaign | All 18 rosters, Boss counts/positions, and the absence of wave 19 match `spec.md`. |
| SC-006 | 20 | A next wave starts only when every aircraft is `DESTROYED` and aggregate crew is cleared. |
| SC-007 | 10 | No premature victory; the last-target-to-`你贏了` presentation latency is at most 1 second. |
| SC-008 | 10 | Enter, Escape, and the return button each produce a clean main-menu reset. |
| SC-009 | 1 regression pass | Impact failure, empty-drop behavior, and landed ground behavior remain compatible. |

If a GUI or real-time measurement is unavailable, mark the affected criterion as not measured, preserve the automated evidence, and do not claim a pass based on an unmeasured result.

## Implementation evidence (2026-08-27)

- `python -m compileall -q air_defense tests`: passed.
- `python -m unittest discover -s tests -p "test_*.py" -q`: passed, 106 tests.
- Ursina construction/start-wave smoke: passed. The app opened the main menu, started wave 1 with two aircraft, and a forced deterministic normal-aircraft hit created and updated a two-member descending batch without import or attribute errors.
- Headless evidence covers the fixed 18-wave roster, source-scoped batches, empty drops, descent interpolation and death guards, hybrid phases, impact precedence, aggregate clear, wave-18 victory, and menu reset.
- Manual functional acceptance owner report: the requested gameplay flows were completed without observed issues. Raw SC-001 through SC-009 sample counts and the 5-second/30-second FPS measurements were not supplied in this session, so no numeric GUI or FPS result is claimed. The desktop smoke above remains construction/lifecycle evidence only.

## Local code review evidence (2026-08-27)

- Review found and fixed unresolved drop-source completion guards, aggregate batch-counter double counting when supplied progress is reconstructed, stale aircraft scene references during replacement, authoritative roster type lookup, and no-target sniper cooldown consumption.
- `git diff --check` and `python -m compileall -q air_defense tests`: passed after the fixes.

## Delivery status (2026-08-27)

- Feature documents have been audited against the implementation and the project constitution; the feature is marked Ready for Review on branch `005-aircraft-enemy-descent-campaign`.
- The required PR target is `main`. After merge, verify the merge commit on `main` before deleting the remote and local feature branches; preserve unrelated `day2/prj06.py` and `output/` changes.
- No formal Release has been created yet. The constitution requires an explicit semver version before creating a tag and GitHub Release from verified `main`.

## Performance evidence

Use the existing FPS display and record the environment. Run two scenarios:

1. Air scenario: a six-aircraft fixture with up to six guided missiles.
2. Ground scenario: six `MANPOWER_SUPPORT` batches with at most 36 crew and six tracer effects.

For each scenario, warm up for 5 seconds, observe for 30 seconds, sample once per second, and record average and minimum FPS. The acceptance target is minimum observed FPS of 60. If the environment cannot provide a real display measurement, record the limitation and the automated evidence instead of claiming the target was measured.
