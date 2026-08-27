---

description: "Dependency-ordered task list for anti-air lock guidance, forward aircraft flight and guided missiles"

---

# Tasks: 防空鎖定、機頭飛行與導引飛彈

**Input**: Design documents from `specs/003-air-defense-lock-guidance/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/ui.md](./contracts/ui.md), [quickstart.md](./quickstart.md)

**Tests**: Tests are required by the feature plan and constitution for the engine-independent lock, movement, steering, collision and reset rules. Scene/HUD behavior is additionally verified with the real Ursina smoke flow and the manual protocol in [quickstart.md](./quickstart.md).

**Organization**: Tasks are grouped by user story. Every story begins with focused failing tests, then implements the smallest complete slice and ends with an independent validation checkpoint.

**Current verification boundary**: The implementation, focused rule tests, full deterministic suite, real Ursina adapter smoke checks and the user's reported manual feature test are complete. T033 remains open for the complete moving-target missile protocol, T036 remains open for the full 002 wave/ground/Boss/city manual regression, and T038 remains open because the five-participant comprehension study and ten-run visual acceptance matrix were not executed. T039 records the unavailable hardware FPS measurement. These limits are documented in [quickstart.md](./quickstart.md); they must remain visible in the PR and prevent claiming full formal acceptance or an official Release until the required evidence is available.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Centralize new tuning values and create the focused test surface without changing the existing wave/Boss behavior.

- [X] T001 [P] Add anti-air scope, lock-zone, decay, frame/ring, aim-assist, aircraft steering and guided-missile tuning constants to `air_defense/config.py`, preserving all existing 002 constant names and defaults.
- [X] T002 [P] Create the engine-free test module `tests/test_airstrike_guidance.py` with deterministic vector, delta-time and aircraft/missile fixtures for the new lock, flight and projectile cases.

**Checkpoint**: New values have one configuration source and the focused test module can import the existing domain package without starting Ursina.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared state, math and reset contracts that every user story depends on.

**⚠️ CRITICAL**: No user story implementation starts until this phase is complete.

- [X] T003 [P] Add engine-independent vector normalization, bounded yaw/pitch steering, circular screen-distance and progress-to-ring-radius helpers to `air_defense/rules.py` with explicit zero-vector and boundary handling.
- [X] T004 [P] Extend anti-air scope, target-in-zone and reset-compatible session/entity fields in `air_defense/state.py` and `air_defense/entities.py` without changing existing wave, Boss, encounter or failure transitions.
- [X] T005 Add shared airstrike reset and target-id bookkeeping in `air_defense/main.py`, ensuring scope close, weapon switch, drop, terminal failure, aircraft transition and menu reset can clear lock state and future missile collections safely.
- [X] T006 Run `python -m compileall air_defense tests` and the existing deterministic suite against `air_defense/` and `tests/`; resolve only baseline/import issues before story work begins.

**Checkpoint**: The existing 002 behavior remains available, shared math/state contracts are importable without Ursina, and all pre-existing tests are green.

---

## Phase 3: User Story 1 - 以放大視野完成可讀的防空鎖定 (Priority: P1) 🎯 MVP

**Goal**: Equip the anti-air scope with a dedicated zoom, a 15% circular acquisition rule, a larger fixed frame, a target-following ring and explicit progress feedback.

**Independent Test**: Start an airstrike, equip slot `1`, open the anti-air scope, move the aircraft projection into and out of the acquisition circle, and verify scope FOV, target eligibility, frame/ring placement, progress and reticle exclusivity without requiring missile damage.

### Tests for User Story 1

- [X] T007 [US1] Add failing pure-rule cases for right-button toggle/scope gating, immediate scope-close reset, 15% short-side circular-zone center/boundary/outside results, visibility-required lockability and 0-to-100% in-zone accumulation in `tests/test_airstrike_guidance.py`.
- [X] T008 [US1] Add failing geometry cases for aspect-correct target projection, target screen-radius clamping and tracking-ring interpolation from acquisition radius to target radius in `tests/test_airstrike_guidance.py`.

### Implementation for User Story 1

- [X] T009 [US1] Implement `LockOnTracker.set_scope_enabled(enabled)`, scope-only lock accumulation, target-in-zone state and progress accessors in `air_defense/rules.py`, keeping the existing 3-second completion threshold and red/green/white state semantics; disabling scope must reset immediately rather than decay.
- [X] T010 [P] [US1] Add anti-air-specific camera scope control and aspect-correct aircraft projection/visibility/15%-zone evaluation to `air_defense/scene.py`, using the existing camera and raycast objects without modifying the Ursina dependency.
- [X] T011 [P] [US1] Build the enlarged fixed lock frame, one continuous ordinary target-following circle (image-2 style, not segmented tick marks), horizontal progress bar and percentage/status text in `air_defense/hud.py`, while preserving sniper and pistol reticle exclusivity.
- [X] T012 [US1] Integrate right-button-down toggle input (button release has no effect), anti-air scope FOV, scope-close reset, target lock evaluation and HUD refresh into `air_defense/main.py`; pass target projection/progress data to `air_defense/hud.py` each frame.
- [X] T013 [US1] Verify the User Story 1 focused tests and the anti-air scene/HUD smoke path described in `specs/003-air-defense-lock-guidance/quickstart.md`, recording any purely visual tuning adjustment in that file.

**Checkpoint**: The player can enter the anti-air zoom, see the larger frame and tracking ring follow the aircraft, watch progress reach 100%, and switch away without stale anti-air UI.

---

## Phase 4: User Story 2 - 在敵機閃避時維持公平的鎖定進度 (Priority: P1)

**Goal**: Preserve partial lock progress during short target losses, resume before the buffer expires and block firing while the target is outside the zone.

**Independent Test**: Drive the tracker with deterministic in-zone/out-of-zone intervals of 0.25 seconds, 0.75 seconds and more than 0.75 seconds; verify progress, state, re-entry behavior and fire gating.

### Tests for User Story 2

- [X] T014 [US2] Add failing rule tests for linear 0.75-second decay, partial progress preservation, re-entry resume, full reset after expiry, green-to-red decay and no-fire while outside the zone in `tests/test_airstrike_guidance.py`.

### Implementation for User Story 2

- [X] T015 [US2] Extend `LockOnTracker` in `air_defense/rules.py` with configurable decay duration, inverse-progress decay and current target-zone state; keep progress clamped to `[0, 1]` for all delta values.
- [X] T016 [US2] Update anti-air fire validation in `air_defense/rules.py`, `air_defense/entities.py` and `air_defense/state.py` so a full progress value is insufficient when the aircraft is outside the zone or scope is closed; make `target_in_zone=False` the fail-closed default and update callers/tests to pass the current explicit zone result.
- [X] T017 [US2] Integrate decaying ring expansion, progress-bar reduction, state text/color changes and scope-close reset into `air_defense/hud.py` and `air_defense/main.py` without resetting progress immediately on a short target loss.
- [X] T018 [US2] Run the focused decay/fire-gating tests plus the existing lock regression cases in `tests/test_rules.py`, then update the edge-case and manual timing evidence in `specs/003-air-defense-lock-guidance/quickstart.md`.

**Checkpoint**: A player can correct a sharp aircraft turn within 0.75 seconds, resume the remaining lock progress, and never fire while the target is outside the acquisition zone.

---

## Phase 5: User Story 3 - 以機頭方向與輕微吸附追蹤敵機 (Priority: P1)

**Goal**: Replace lateral-offset aircraft movement with bounded forward-only yaw/pitch steering and add small scope-only target attraction for mouse aiming.

**Independent Test**: Advance a deterministic aircraft through several evasion changes and verify displacement follows its forward vector, turn rates are capped and no lateral teleport occurs; then verify aim assist is capped and disabled outside anti-air scope/near-target conditions.

### Tests for User Story 3

- [X] T019 [US3] Add failing aircraft-motion tests for speed×delta displacement limits, forward-vector alignment, bounded yaw/pitch change, continuous evasion and rejection of reverse/sideways movement in `tests/test_airstrike_guidance.py`.
- [X] T020 [US3] Add failing aim-assist tests for scope-only activation, the inclusive 1.5× lock-zone-radius activation boundary, correction capped at `3°/second * delta_seconds` after mouse rotation, and no correction after target loss in `tests/test_airstrike_guidance.py`.

### Implementation for User Story 3

- [X] T021 [US3] Refactor `Aircraft` movement state in `air_defense/entities.py` to hold mutable position, normalized forward vector, yaw/pitch, flight elapsed time and type-specific speed/turn limits while retaining `advance(delta_seconds)` and impact-progress compatibility.
- [X] T022 [US3] Update aircraft profiles and deterministic desired-heading/evasion calculations in `air_defense/rules.py` and `air_defense/config.py` so evasion changes heading rather than adding a direct lateral position offset.
- [X] T023 [US3] Update aircraft visual translation and orientation in `air_defense/scene.py` to use the domain forward vector, and implement the visible-target 1.5× band plus capped `3°/second * delta_seconds` screen-to-target angular assist after normal mouse rotation without changing the installed FirstPersonController source.
- [X] T024 [US3] Integrate the new aircraft advance order and scope-only aim assist into `air_defense/main.py`, ensuring warning timing, impact detection, lock projection and existing aircraft phases continue to use the same active aircraft id.
- [X] T025 [US3] Run the forward-flight and aim-assist tests, observe at least two in-game evasion turns and record the no-sideways/no-teleport result in `specs/003-air-defense-lock-guidance/quickstart.md`.

**Checkpoint**: The aircraft visibly turns its nose before changing route, always moves forward along that nose direction, and the scoped mouse assist helps without taking control from the player.

---

## Phase 6: User Story 4 - 發射真正追蹤敵機的導引飛彈 (Priority: P1)

**Goal**: Replace immediate anti-air damage with delayed collision damage from yellow, forward-steered, target-bound missiles; support multiple missiles and safe terminal cleanup.

**Independent Test**: Fire at a live aircraft after a valid lock, observe missile pursuit/collision/explosion and one damage event, then fire again after cooldown; destroy or impact the aircraft before a stale missile arrives and verify no later target is affected.

### Tests for User Story 4

- [X] T026 [US4] Add failing guided-missile tests for forward-only pursuit, bounded steering, swept-segment hit radius including a high-speed anti-tunneling case, lifetime expiry, hit-before-expiry precedence, one-shot consumption, moving targets, multiple missiles and target-id isolation in `tests/test_airstrike_guidance.py`.
- [X] T027 [US4] Add failing integration-rule cases for delayed aircraft damage, five-hit armored aircraft progression, simultaneous swept missile contacts, aircraft-impact-before-missile ordering and cleanup before ground/next-aircraft transition in `tests/test_rules.py`.

### Implementation for User Story 4

- [X] T028 [US4] Implement the engine-independent `GuidedMissile` state and `MissileStep` hit/expiry result in `air_defense/entities.py` and `air_defense/rules.py`, including normalized forward movement, bounded steering, swept-segment collision, hit-before-expiry precedence, lifetime and consumed guards.
- [X] T029 [P] [US4] Add procedural yellow elongated-cuboid missile entities, target-facing orientation, collision explosion and safe visual removal to `air_defense/scene.py` without requiring an external model or physics dependency.
- [X] T030 [US4] Replace immediate anti-air damage in `air_defense/main.py` with missile creation, stable per-frame missile updates using current target positions and swept collision outcomes, aircraft-id validation and collision-time damage; preserve the existing 1.25-second cooldown and re-lock requirement.
- [X] T031 [US4] Implement the explicit airstrike event order and terminal cleanup in `air_defense/main.py`: advance aircraft, resolve impact before exact same-frame missile ties, process remaining missiles in insertion order, clear all target missiles and transition only once on destruction.
- [X] T032 [US4] Connect missile hit feedback and Boss HP refresh to `air_defense/hud.py` and `air_defense/main.py`, then verify armored-aircraft five-hit, ground-Boss ten-hit, stale-missile and reset behavior in `tests/test_rules.py`.
- [ ] T033 [US4] Run the guided-missile scene smoke flow and the complete User Story 4 manual protocol in `specs/003-air-defense-lock-guidance/quickstart.md`, recording collision timing, visual warnings, swept-collision behavior and any balance-only tuning changes. The adapter smoke flow is recorded; the full hands-on protocol remains pending.

**Checkpoint**: Each valid shot visibly launches a yellow tracking missile, collision produces one explosion and one damage event, multiple missiles can coexist, and no stale missile crosses an aircraft or session boundary.

---

## Phase 7: Polish & Cross-Cutting Validation

**Purpose**: Validate the integrated game, preserve the 002 baseline and document actual runtime evidence.

- [X] T034 [P] Run `python -m compileall air_defense tests` and `python -m unittest discover -s tests -p "test_*.py" -v`; resolve failures in `air_defense/` or `tests/` without weakening the feature contracts.
- [X] T035 [P] Run the real Ursina smoke checks for anti-air 55°/90° FOV, sniper 35° regression, reticle exclusivity, projection/ring rendering, yellow missile visuals, explosion cleanup and reset; record commands and results in `specs/003-air-defense-lock-guidance/quickstart.md`.
- [ ] T036 Run the full 002 regression/manual wave, ground-combat, Boss and city-failure flow after 003 integration, and record that `day1/` and `day2/` remain untouched in `specs/003-air-defense-lock-guidance/quickstart.md`.
- [X] T037 Review `air_defense/`, `tests/`, `specs/003-air-defense-lock-guidance/` and `git diff` for unused imports, duplicate steering/lock rules, stale target callbacks, incomplete reset paths and accidental edits outside scope; record review findings and scope limitations in `specs/003-air-defense-lock-guidance/quickstart.md`.
- [ ] T038 [P] Execute the SC-001 five-participant first-second comprehension check and ten independent repetitions for SC-002 through SC-006 using the acceptance evidence protocol, recording every pass/fail result and failure reason in `specs/003-air-defense-lock-guidance/quickstart.md`.
- [X] T039 [P] Measure the largest supported scene for a continuous 30-second run with one aircraft, several missiles, the long map, fixed obstacles and the largest ground encounter; record operating system, hardware, average FPS and minimum FPS, or the unavailable measurement reason, in `specs/003-air-defense-lock-guidance/quickstart.md`.
- [X] T040 [US1] Reproduce and fix the Ursina target-visibility regression where the raycast `HitInfo` wrapper is traversed instead of `hit.entity`, leaving a centered aircraft at 0% lock; add a pure hit-entity/parent-chain regression test and rerun focused plus full validation.
- [X] T041 [US3] Strengthen aircraft evasion with wider, slower nose-led turns for every aircraft profile, keep the fast aircraft most agile, add deterministic lateral-span coverage, and preserve forward-only displacement plus bounded yaw/pitch steering.
- [X] T042 [US3] Apply second-stage stronger aircraft evasion tuning with gameplay-scale turns for all four profiles, preserve lockability and forward-only movement, and synchronize the spec, plan, research, data model, UI contract and quickstart evidence.
- [X] T043 [P] Complete a local code review of the integrated lifecycle/UI and fix terminal-transition guidance state leakage, the equipped-weapon fixed-frame visibility contract and empty-encounter explosion cleanup; add lifecycle regression coverage and real HUD smoke checks.

**Final Checkpoint**: All desired stories pass their focused tests and independent checkpoints, the complete regression suite is green, SC-001–SC-007 have the required observed evidence or an explicit measurement limitation, and the manual quickstart contains observed rather than invented runtime evidence.

---

## Dependencies & Execution Order

### Phase Dependencies

1. **Setup (Phase 1)**: T001–T002 are independent and establish tuning/test scaffolding.
2. **Foundational (Phase 2)**: T003–T006 depend on Setup and block all story implementation.
3. **User Story 1 (Phase 3)**: T007–T013 depend on the Foundation; this is the MVP slice.
4. **User Story 2 (Phase 4)**: T014–T018 depend on US1's scope/projection/HUD contracts and refine lock behavior.
5. **User Story 3 (Phase 5)**: T019–T025 depend on the Foundation and the US1 target-projection bridge; pure motion tests can begin after T006, but integration waits for US1.
6. **User Story 4 (Phase 6)**: T026–T033 depend on the Foundation; missile integration waits for the US3 forward-aircraft state and US1/US2 fire gate.
7. **Polish (Phase 7)**: T034–T039 depend on all desired stories and their checkpoints; T040–T043 are follow-up regression, balance and code-review tasks that depend on the integrated implementation and its validation evidence.

### User Story Dependencies

- **User Story 1 (P1)**: Foundation only; independently demonstrates anti-air scope and readable lock UI.
- **User Story 2 (P1)**: Extends US1's lock tracker and HUD, so it follows US1 while remaining independently testable with deterministic time.
- **User Story 3 (P1)**: Pure flight/assist behavior depends only on Foundation; live camera integration depends on US1's projection bridge.
- **User Story 4 (P1)**: Pure missile behavior depends only on Foundation; live firing depends on US1/US2 gates and US3's moving aircraft.

### Within Each User Story

- Write the story's focused tests first and confirm they fail for the missing behavior.
- Implement pure state/rule behavior before scene/HUD integration.
- Integrate the story into `main.py` only after its domain tests pass.
- Complete the story checkpoint before changing the next story's shared behavior.

### Parallel Opportunities

- T001 and T002 can run in parallel because they touch `air_defense/config.py` and `tests/test_airstrike_guidance.py` separately.
- T003 and T004 can run in parallel after Setup because they touch separate domain files; T005 waits for their field/helper decisions.
- T010 and T011 can run in parallel after US1 tests because scene projection/FOV and HUD geometry are separate adapters; T012 integrates them.
- T021 and T022 should be coordinated sequentially because both shape the aircraft movement contract; T023 can start once the domain shape is stable.
- T028 and T029 can be split after the missile tests: domain missile state/rules and scene missile visuals use separate files; T030/T031 integrate them.
- T034 and T035 can run in parallel after all story checkpoints. T036 and T037 follow T034/T035. T038 follows T035/T036 for the acceptance evidence; T039 follows T035 and may run in parallel with T036–T038 once the integrated scene is available.

## Parallel Example: User Story 1

```text
# After T007–T008 establish the expected behavior:
Task: "Implement anti-air scope, FOV and projected aircraft lockability in air_defense/scene.py"
Task: "Build the enlarged fixed frame, tracking ring and progress bar in air_defense/hud.py"

# Then run the integration task:
Task: "Integrate anti-air scope input, lock evaluation and HUD refresh in air_defense/main.py"
```

## Parallel Example: User Story 4

```text
# After T026–T027 define collision and lifecycle expectations:
Task: "Implement GuidedMissile state and MissileStep outcomes in air_defense/entities.py and air_defense/rules.py"
Task: "Build the yellow cuboid missile and explosion visuals in air_defense/scene.py"

# Then integrate the event ordering and delayed damage:
Task: "Replace immediate anti-air damage with target-bound missile updates in air_defense/main.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational phases.
2. Complete User Story 1: anti-air scope, 15% lock zone, enlarged frame, target-following ring and progress bar.
3. Stop and validate the scope/lock experience independently with the focused tests and scene smoke flow.

### Incremental Delivery

1. Add User Story 2 for forgiving decay and strict in-zone fire gating.
2. Add User Story 3 for forward-only aircraft steering and capped mouse assist.
3. Add User Story 4 for delayed multi-missile damage, explosion feedback and stale-target cleanup.
4. Run the complete regression, the 5-participant/10-run acceptance evidence and the 30-second performance validation before declaring the 003 feature complete.

### Review Gates

- Do not mark a task complete until its referenced file exists and the described check passes.
- Keep the existing 002 wave/Boss rules as regression coverage; do not edit `day1/` or `day2/`.
- Preserve one active aircraft, target-id guards and explicit reset paths across all story integrations.
- Do not declare the feature complete until T038 and T039 record the required acceptance evidence or explicit unavailable-measurement limitations.
- Record actual smoke/performance limitations in `specs/003-air-defense-lock-guidance/quickstart.md` rather than asserting unmeasured success.
