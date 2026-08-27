---

description: "Dependency-ordered implementation tasks for the 3D air-defense endless game"

---

# Tasks: 3D 防空守衛無限模式

**Input**: Design documents from `specs/001-air-defense-game/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/ui.md](./contracts/ui.md), [quickstart.md](./quickstart.md)

**Tests**: Pure game rules use Python standard-library `unittest`; scene and rendering behavior use the manual validation flow in [quickstart.md](./quickstart.md). Test tasks are included because the plan and project constitution require repeatable coverage for timing, collision, state, health and reset rules.

**Organization**: Tasks are grouped by user story. Every story ends with an independent validation checkpoint; the integrated game is then extended in priority order.

**Current verification boundary**: Implementation, pure-rule tests, the real Ursina event smoke check and the user-reported manual acceptance flow are complete. The user did not provide raw per-run counts, first-time-user comprehension results or target-machine FPS values; those values are explicitly recorded as unreported in [quickstart.md](./quickstart.md), not inferred from automated checks.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the isolated game package, test package and asset/dependency boundaries without touching the existing teaching examples.

- [X] T001 [P] Create `air_defense/__init__.py` and `tests/__init__.py`, and add the empty `air_defense/`, `tests/` and `assets/air_defense/` directories required by the implementation plan.
- [X] T002 [P] Add `requirements-game.txt` with the pinned direct dependency `ursina==8.3.0`, document the Python 3.12+ minimum required by that dependency and describe its role in the true-3D game runtime.
- [X] T003 [P] Add `assets/air_defense/README.md` documenting CC0/owned asset sources, license checks and the procedural-geometry fallback policy.

**Checkpoint**: The new package and dependency boundary exist; this feature has introduced no changes to `day1/` or `day2/`, and any pre-existing worktree changes are preserved.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the engine-independent state/rule layer and the smallest launchable Ursina application. All user stories depend on this phase.

- [X] T004 [P] Create `air_defense/config.py` with centralized window size, target frame rate, colors, movement speeds, 8-second warning lead time, 0.12-second lock-flash half-period, 2-second crew-advance interval, lock duration, cooldowns, health and encounter tuning constants.
- [X] T005 [P] Create `air_defense/state.py` with `GamePhase`, `LockState`, `FailureReason`, weapon kinds, session data and the initial statistics value objects from `data-model.md`.
- [X] T006 Implement the engine-independent rule functions in `air_defense/rules.py` for phase transition validation, lock progression/reset, weapon ownership and one-time event guards (depends on T004 and T005).
- [X] T007 Add foundational deterministic unit tests in `tests/test_rules.py` for legal/illegal phase transitions, single-weapon ownership, one-time event recording and clean session initialization (depends on T006).
- [X] T008 Create the base Ursina scene adapter in `air_defense/scene.py` for world creation, colliders, camera-center raycast access and safe destruction of scene objects (depends on T004 and T005).
- [X] T009 Create the base UI adapter in `air_defense/hud.py` for screen-state switching, the two-slot inventory bar, text labels and reusable overlay elements (depends on T004 and T005).
- [X] T010 Implement the minimal launchable application and explicit frame/update ordering in `air_defense/main.py`: limit frame rate, register direct Ursina input/update callbacks, process window events, read gameplay input, update entities/state, resolve collisions/domain rules, update animations, update HUD, draw the scene and display the frame (depends on T006, T008 and T009).
- [X] T011 Run `python -m compileall air_defense tests` and `python -m unittest discover -s tests -p "test_*.py" -v`, manually launch `python -m air_defense.main` to open/operate/close the minimal window, and record the foundation result against `specs/001-air-defense-game/quickstart.md`.

**Checkpoint**: The application can open/close a window, the game state has explicit phases, and pure rule tests run without creating a graphics window.

## Phase 3: User Story 1 - 攔截攻擊大樓的戰鬥機 (Priority: P1) 🎯 MVP

**Goal**: Let the player select the anti-aircraft gun from inventory slot `1`, visually lock a straight-diving fighter for three uninterrupted seconds, fire only while the frame is green, and fail if the fighter reaches the building.

**Independent Test**: Follow User Story 1 in [spec.md](./spec.md): start a new game, select inventory slot `1`, verify white/red/green lock states, fire a guided shot, and separately allow the aircraft to collide with the building.

### Tests for User Story 1

- [X] T012 [US1] Add lock-on and airstrike rule tests to `tests/test_rules.py` covering the 0.12-second red-flash half-period, the exact 3-second green threshold, explicit white/red/green status labels, immediate reset after target loss/occlusion, the 8-second warning threshold, fire gating and aircraft outcome ordering; tests must fail before the story implementation.

### Implementation for User Story 1

- [X] T013 [P] [US1] Implement `Player`, `WeaponPickup`, `AntiAircraftGun`, `Aircraft` and `TargetBuilding` state/behavior in `air_defense/entities.py` with ownership, lock target and one-time outcome fields from `data-model.md`.
- [X] T014 [P] [US1] Add the defense point, optional ground anti-aircraft display, weapon display rack, target-building collision volume, straight-line aircraft dive path and aircraft collision adapters in `air_defense/scene.py`.
- [X] T015 [P] [US1] Implement the airstrike HUD in `air_defense/hud.py` according to `contracts/ui.md`, including the centered square, explicit `未鎖定`/`鎖定中`/`可發射` text or icons, 0.12-second red tracking flash, stable green ready state and the 8-second text/icon aircraft warning.
- [X] T016 [US1] Integrate the airstrike phase in `air_defense/main.py`: WASD/mouse movement, inventory slot `1` selection, optional `E` pickup, center-ray target visibility, 8-second warning threshold, three-second lock updates, green-only left-click firing, guided-shot destruction and building-impact failure (depends on T013–T015).
- [X] T017 [US1] Run the User Story 1 unit cases in `tests/test_rules.py` and the counted airstrike protocol in `specs/001-air-defense-game/quickstart.md`, including both successful interception, deliberate building impact, the 30-second start flow and 10 lock attempts; manual acceptance was reported complete by the user on 2026-08-27.

**Checkpoint**: User Story 1 is independently playable and testable; the player can either destroy the aircraft before impact or receive a clear airstrike failure.

## Phase 4: User Story 2 - 在墜機後切換狙擊槍並擊倒乘員 (Priority: P2)

**Goal**: After a successful interception, spawn exactly one finite group of 2–5 crew members, give them cover/group behavior and weapons, and let the player switch to the inventory-slot `2` infinite-ammo sniper rifle that defeats an enemy with one valid hit.

**Independent Test**: Start from a controlled aircraft-destroyed state, create one encounter, verify 2–5 crew members and no reinforcements, switch with inventory slot `2`, survive enemy fire and clear the encounter.

### Tests for User Story 2

- [X] T018 [US2] Add ground-encounter tests to `tests/test_rules.py` for phase-limited direct inventory selection, one-time 2–5 crew generation, required cover-node and squad-role assignment, the 2-second crew-advance interval, no ground reinforcement, optional manual weapon ownership transfer, right-mouse sniper aim state, one-hit sniper defeat, fire cooldown and player health reaching zero; tests must fail before the story implementation.

### Implementation for User Story 2

- [X] T019 [P] [US2] Implement `SniperRifle`, `CrewMember` with `cover_node`, `squad_role` and `behavior_state`, `GroundEncounter`, direct inventory-compatible ownership and optional E/G drop/pickup transitions in `air_defense/entities.py`.
- [X] T020 [P] [US2] Add the crash site, predefined cover nodes, 2–5 crew spawn positions, deterministic cover/advance movement routes and crew collision adapters in `air_defense/scene.py`.
- [X] T021 [P] [US2] Add the ground-combat HUD in `air_defense/hud.py`, including the two-slot inventory bar, current-weapon feedback, sniper aiming state, health display and hit feedback.
- [X] T022 [US2] Extend `air_defense/rules.py` and `air_defense/state.py` with finite encounter creation, required cover/squad-role assignment, `IN_COVER`/`ADVANCING`/`RELOCATING` behavior transitions, enemy damage, one-hit sniper results, right-mouse aim state, no-reinforcement invariants and `CREW_CLEARED` transition (depends on T018 and T019).
- [X] T023 [US2] Integrate `GROUND_COMBAT` in `air_defense/main.py`: spawn the current aircraft's crew after its crash, process inventory slot `2` switching with optional `G`/`E` legacy interactions, process right-mouse sniper aiming, run cover/group AI with the 2-second advance interval, apply enemy shots and health loss, process sniper hits and detect encounter clearing (depends on T019–T022).
- [X] T024 [US2] Run the User Story 2 unit cases in `tests/test_rules.py` and the ground-combat protocol in `specs/001-air-defense-game/quickstart.md`, confirming role behavior, right-mouse aiming, one-hit defeat, health loss and no additional ground enemy after the current group is cleared; manual acceptance was reported complete by the user on 2026-08-27.

**Checkpoint**: User Stories 1 and 2 work together: a downed aircraft produces only its own crew, and the player can switch weapons and clear that encounter.

## Phase 5: User Story 3 - 持續防守並查看本局統計 (Priority: P3)

**Goal**: Complete the endless loop, immediate next-aircraft attack, statistics, failure reasons and return-to-main-menu reset.

**Independent Test**: Complete at least one aircraft/crew cycle, trigger each failure cause separately, verify the displayed statistics, return to the main menu and start a clean new game.

### Tests for User Story 3

- [X] T025 [US3] Add endless-cycle, statistics, failure-screen and reset tests to `tests/test_rules.py` covering immediate next-aircraft creation, the held-sniper/no-anti-air rule, duplicate-event protection, building-impact failure, player-death failure and clean new-session state; tests must fail before the story implementation.

### Implementation for User Story 3

- [X] T026 [P] [US3] Extend `air_defense/state.py` with `SessionStats`, failure-reason snapshots and reset behavior matching `data-model.md`.
- [X] T027 [P] [US3] Extend `air_defense/hud.py` with clickable main-menu start/quit buttons, keyboard-compatible action bindings, game-over screen, failure reason, survival time, aircraft count, enemy count and return-to-menu control from `contracts/ui.md`.
- [X] T028 [US3] Extend `air_defense/rules.py` with guarded aircraft-cycle creation, the held-sniper/no-anti-air rule, one-time statistics updates and mutually exclusive player-death/building-impact failure resolution (depends on T025 and T026).
- [X] T029 [US3] Integrate the endless loop and reset in `air_defense/main.py`: clear a ground encounter, start the next aircraft immediately, preserve the held-sniper restriction, stop all updates on failure, route to the main menu through its button or keyboard fallback, quit the application, and rebuild a fresh session (depends on T026–T028).
- [X] T030 [US3] Run the User Story 3 unit cases in `tests/test_rules.py` and the counted cycle/failure/reset protocol in `specs/001-air-defense-game/quickstart.md`, including 5 complete cycles, both failure causes and 1-second response measurements; manual acceptance was reported complete by the user on 2026-08-27.

**Checkpoint**: All three user stories are integrated; the game can repeat aircraft/ground-combat cycles until either the building is hit or the player dies.

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Make the prototype resilient, understandable and runnable with or without optional art assets.

- [X] T031 [P] Add optional CC0 model loading with procedural fallback in `air_defense/scene.py`, and update `assets/air_defense/README.md` with the final asset file list and licenses.
- [X] T032 [P] Add asset-free scene/rule smoke fixtures and regression cases to `tests/test_rules.py` so tests do not require external models or a graphics window.
- [X] T033 [P] Update `specs/001-air-defense-game/quickstart.md` with the Python 3.12+ prerequisite, final launch command, dependency setup, control mapping, exact warning/flash parameters, counted acceptance protocol, FPS measurement procedure and known platform limitations discovered during implementation.
- [X] T034 Run `python -m compileall air_defense tests`, `python -m unittest discover -s tests -p "test_*.py" -v` and the real Ursina button/input bridge smoke check; record the user-reported manual acceptance result in `specs/001-air-defense-game/quickstart.md`, while leaving any raw 30-second/10-lock/5-cycle/5-encounter/1-second, first-time HUD comprehension and 60-FPS values explicitly unreported rather than claiming headless coverage.
- [X] T035 Review `air_defense/`, `tests/`, `assets/air_defense/`, `requirements-game.txt` and the feature design documents for unused imports, duplicate rules, debug output, missing paths, startup instructions, version consistency and the documented Principle IV/V exception boundaries; confirm the feature introduces no changes to `day1/` or `day2/` beyond pre-existing worktree changes.
- [X] T036 Perform the post-acceptance local code review in `air_defense/state.py` and `air_defense/main.py`: guard stale aircraft/encounter callbacks by active identifiers, reject wrong-phase fire attempts, prevent duplicate start handling, keep `Player.health` synchronized with session health, add regression coverage in `tests/test_rules.py`, and rerun the validation commands.

## Dependencies & Execution Order

### Phase Dependencies

1. **Setup (Phase 1)**: T001–T003 are independent and can run in parallel.
2. **Foundational (Phase 2)**: T004 and T005 can start after Setup; T006 depends on T004/T005; T007 depends on T006; T008 and T009 follow T004/T005 and can run in parallel; T010 depends on T006/T008/T009; T011 is the foundation checkpoint.
3. **User Story 1 (Phase 3)**: T012 starts after T011; T013–T015 can run in parallel after the test contract is agreed; T016 depends on T013–T015; T017 is the story checkpoint.
4. **User Story 2 (Phase 4)**: T018 starts after the US1 checkpoint for the integrated path; T019–T021 can be split by file after T018; T022 follows T019; T023 depends on T019–T022; T024 is the story checkpoint.
5. **User Story 3 (Phase 5)**: T025 starts after the US2 checkpoint; T026 and T027 can be split by file after T025; T028 follows T026; T029 depends on T026–T028; T030 is the story checkpoint.
6. **Polish (Phase 6)**: T031–T033 can run in parallel after T030; T034–T036 are final gates.

### User Story Dependencies

- **US1 (P1)**: Depends only on the Foundational phase. It is the MVP and establishes the aircraft-destroyed event consumed by US2.
- **US2 (P2)**: Its pure encounter rules can be tested from a controlled fixture after Foundation, but integrated gameplay depends on US1's aircraft-destroyed transition; execute after US1 for the single-developer path.
- **US3 (P3)**: Depends on US1 and US2 because the endless cycle combines both completed gameplay phases.

### Parallel Opportunities

- T001, T002 and T003 use separate paths and can run in parallel.
- T004 (`air_defense/config.py`) and T005 (`air_defense/state.py`) can run in parallel after Setup; then T008 (`air_defense/scene.py`) and T009 (`air_defense/hud.py`) can run in parallel after both foundational interfaces exist.
- Within US1, T013 (`air_defense/entities.py`), T014 (`air_defense/scene.py`) and T015 (`air_defense/hud.py`) can run in parallel after T012; T016 must wait for all three.
- Within US2, T019 (`air_defense/entities.py`), T020 (`air_defense/scene.py`) and T021 (`air_defense/hud.py`) can run in parallel after T018; T022 (`air_defense/rules.py`/`air_defense/state.py`) can proceed once the entity fields are fixed; T023 must wait for all story components.
- Within US3, T026 (`air_defense/state.py`) and T027 (`air_defense/hud.py`) can run in parallel after T025; T028 (`air_defense/rules.py`) follows T026; T029 must wait for all three.
- T031, T032 and T033 use separate asset, test and documentation concerns and can run in parallel after all stories.

## Parallel Example: User Story 1

```text
First write and run the failing rule cases in tests/test_rules.py (T012).
Then, with the state/rule interfaces fixed, run these independent work items in parallel:

Task T013: Implement aircraft and anti-aircraft entities in air_defense/entities.py
Task T014: Implement the defense scene, dive path and building collider in air_defense/scene.py
Task T015: Implement the lock overlay and warning HUD in air_defense/hud.py

After all three complete, execute T016 in air_defense/main.py, then run T017.
```

## Parallel Example: User Story 2

```text
First write and run the failing encounter/weapon/health cases in tests/test_rules.py (T018).
After US1's scene interfaces are available, split the work as follows:

Task T019: Implement sniper, crew and weapon ownership in air_defense/entities.py
Task T020: Implement crash/cover/spawn adapters in air_defense/scene.py
Task T021: Implement ground-combat HUD states in air_defense/hud.py
Task T022: Implement encounter and damage rules in air_defense/rules.py and air_defense/state.py

Integrate all components in air_defense/main.py (T023), then run T024.
```

## Parallel Example: User Story 3

```text
First write and run the failing cycle/statistics/reset cases in tests/test_rules.py (T025).
Then split the independent changes, completing T028 after T026:

Task T026: Implement session statistics and reset snapshots in air_defense/state.py
Task T027: Implement main-menu and game-over presentation in air_defense/hud.py
Task T028: Implement guarded cycle/statistics/failure rules in air_defense/rules.py after T026

Integrate the endless loop in air_defense/main.py (T029), then run T030.
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001–T011 to establish the launchable foundation.
2. Complete T012–T017 to deliver the first playable airstrike loop.
3. Stop and validate the white/red/green lock, green-only fire, aircraft destruction and building-impact failure before adding ground combat.

### Incremental Delivery

1. Foundation ready → deterministic rule tests and a launchable window.
2. US1 complete → playable air-defense MVP.
3. US2 complete → aircraft-to-ground-combat weapon-switch loop.
4. US3 complete → endless replay loop, statistics and failure/reset flow.
5. Polish complete → asset fallback, clean startup and final regression validation.

### Definition of Done

- Every task above is checked only after its referenced file path exists and the described behavior is verified.
- All task lines use `- [ ]` or `- [X]`, a sequential `T###` ID, optional `[P]`, the required story label for story phases, and an explicit file path.
- `tests/test_rules.py` and the manual flow in `quickstart.md` pass, while this feature introduces no changes to `day1/` or `day2/` and preserves any pre-existing worktree changes.
