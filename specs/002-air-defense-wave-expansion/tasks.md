---

description: "Dependency-ordered implementation tasks for the air-defense wave and Boss expansion"

---

# Tasks: 3D 防空守衛波次與 Boss 擴充

**Input**: Design documents from `specs/002-air-defense-wave-expansion/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/ui.md](./contracts/ui.md), [quickstart.md](./quickstart.md)

**Tests**: Pure rules use Python standard-library `unittest`; scene, HUD and camera behavior use the real Ursina smoke command plus the manual protocol in [quickstart.md](./quickstart.md). Tests are required because the feature specification defines exact counts, hit totals, cooldowns, ranges, movement limits and one-time outcomes.

**Organization**: Tasks are grouped by user story. Shared domain work is completed first, and every story ends with an independent validation checkpoint.

**Current verification boundary**: Implementation, pure-rule tests, real Ursina integration smoke checks and the user-reported manual acceptance flow are complete. The user did not provide a numeric target-machine FPS or hardware record, so that measurement remains explicitly unreported in [quickstart.md](./quickstart.md) and T032 remains open.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Lock the feature boundary and centralize all new tuning values before behavior changes.

- [X] T001 [P] Verify `specs/002-air-defense-wave-expansion/plan.md`, `specs/002-air-defense-wave-expansion/data-model.md` and `specs/002-air-defense-wave-expansion/contracts/ui.md` agree on the four aircraft types, three weapons, wave cap rule and city-destruction failure.
- [X] T002 [P] Add the long-map dimensions, far aircraft spawn, route/obstacle coordinates, aircraft profiles, weapon ranges/cooldowns, Boss HP and city-damage constants to `air_defense/config.py` without changing unrelated teaching-project constants.
- [X] T003 [P] Confirm `requirements-game.txt` and `assets/air_defense/README.md` need no new dependency or mandatory asset for this expansion, and record the procedural fallback boundary in `specs/002-air-defense-wave-expansion/research.md` if the check finds drift.

**Checkpoint**: All new balance and map values have one configuration source and the feature remains isolated from `day1/` and `day2/`.

## Phase 2: Foundational Domain Rules

**Purpose**: Establish testable state, type profiles, health and movement contracts before scene integration.

- [X] T004 [US1] Add failing deterministic tests in `tests/test_rules.py` for `AircraftType`, aircraft profile lookup, far-spawn distance, continuous evasion and bounded aircraft health damage.
- [X] T005 [US2] Add failing deterministic tests in `tests/test_rules.py` for wave counts `2,3,4,5,6,7,8,9,10`, cap milestones `6→8→10`, regular/Boss rosters, one active aircraft and zero-crew immediate progression.
- [X] T006 [US3] Add failing deterministic tests in `tests/test_rules.py` for type-specific encounter counts, continuous ground movement, route bounds, obstacle-aware target visibility contract, pistol cooldown/range, sniper damage and city health failure.
- [X] T007 [US4] Add failing deterministic tests in `tests/test_rules.py` for armored-aircraft five-hit damage, ground-Boss ten-hit damage, Boss HP stage selection, `CITY_DESTROYED`, reset behavior and duplicate event protection.
- [X] T008 Implement the new enums, `WaveProgress`, `WavePlan` and session fields/transitions in `air_defense/state.py`, including wave advancement, active type identity, city health and the new failure reason while preserving existing event guards.
- [X] T009 Implement aircraft, ground-enemy, encounter, city and pistol entity state in `air_defense/entities.py`, including health guards, route targets, movement progress, Boss identity and cooldown behavior.
- [X] T010 Implement `WaveDirector`, aircraft/type profiles, type-specific `EncounterFactory`, continuous movement, firearm range/cooldown checks, damage results and city-damage rules in `air_defense/rules.py` until T004–T007 pass.

**Checkpoint**: The entire new domain contract passes without importing Ursina; all old rule tests remain green.

## Phase 3: User Story 1 - 長距離平原與閃避敵機 (Priority: P1)

**Goal**: Make the world visibly longer, populate it with collidable obstacles and make every aircraft approach from far away with continuous lateral evasion.

**Independent Test**: Launch a new game, observe the far spawn and at least two lateral aircraft movements, and confirm the extended ground route and obstacles load without external assets.

### Tests for User Story 1

- [X] T011 [US1] Extend `tests/test_rules.py` with regression cases proving aircraft position changes are continuous, evasion stays within configured amplitude, far spawn precedes the city route and aircraft impact still wins only when destruction has not occurred.

### Implementation for User Story 1

- [X] T012 [US1] Rebuild `AirDefenseScene.build_world()` in `air_defense/scene.py` with a long rectangular plain, at least eight collidable obstacles, at least five authored cover nodes and a route connecting the crash site to the city.
- [X] T013 [US1] Update aircraft creation and per-frame translation in `air_defense/scene.py` so aircraft type profiles control model tint/scale, far spawn position, continuous lateral evasion and target-facing orientation.
- [X] T014 [US1] Integrate type-profile aircraft construction, evasion updates, warning timing and five-hit armored aircraft damage into `air_defense/main.py` while keeping green-lock fire gating and first-event impact ordering.
- [X] T015 [US1] Run the User Story 1 focused tests and asset-free scene smoke path, then record the result in `specs/002-air-defense-wave-expansion/quickstart.md`.

**Checkpoint**: A player can see and track a distant weaving aircraft in the long map; aircraft movement is smooth and the map obstacles exist as real colliders.

## Phase 4: User Story 2 - 多波次與敵機種類 (Priority: P1)

**Goal**: Drive sequential aircraft rosters, type-specific ground outcomes and increasing wave pressure, including Boss-wave composition.

**Independent Test**: Build wave plans 1–10 from a fixed source, verify counts/types, process each aircraft one at a time and confirm wave 10 contains exactly one armored Boss plus other aircraft.

### Tests for User Story 2

- [X] T016 [US2] Add failing lifecycle tests in `tests/test_rules.py` for normal `0–3`, support `6`, fast `0`, armored `1 Boss`, same-wave aircraft progression, wave completion and new-wave creation.

### Implementation for User Story 2

- [X] T017 [US2] Finish deterministic roster generation and cap-band rotation in `air_defense/rules.py`, guaranteeing no armored Boss before wave 10 and exactly one armored Boss on every tenth wave.
- [X] T018 [US2] Integrate wave plans, aircraft index progression, empty-encounter skipping, encounter cleanup and next-wave creation in `air_defense/main.py` and `air_defense/state.py` without allowing simultaneous aircraft.
- [X] T019 [US2] Add wave/type/progress state fixtures and regression checks to `tests/test_rules.py`, then run the complete domain suite at the wave checkpoint.

**Checkpoint**: Waves 1–10 can be generated and advanced deterministically; zero-crew aircraft do not stall the loop and regular waves never spawn armored Bosses.

## Phase 5: User Story 3 - 步行掩護、狙擊槍與手槍 (Priority: P1)

**Goal**: Replace teleporting ground movement with route-based walking, make obstacles block sniper shots, add scope zoom and provide a short-range pistol.

**Independent Test**: Spawn a six-member or Boss encounter, observe incremental movement through cover toward the city, verify blocked center ray behavior, then use sniper and pistol under their separate reticles/ranges.

### Tests for User Story 3

- [X] T020 [US3] Add failing movement and weapon cases in `tests/test_rules.py` proving per-frame distance never exceeds speed × delta, route transitions do not teleport, pistol shots beyond 12 units fail, pistol cooldown is 0.20 seconds and ground Boss firearm damage is incremental.

### Implementation for User Story 3

- [X] T021 [P] [US3] Implement continuous crew Entity positioning, cover-obstacle raycast behavior, city attack-zone translation and scope FOV reset in `air_defense/scene.py`.
- [X] T022 [P] [US3] Expand `air_defense/hud.py` with three-slot inventory presentation, anti-air-only lock frame, sniper crosshair/scope overlay and compact pistol reticle with mutually exclusive visibility.
- [X] T023 [US3] Add `Pistol`, slot `3`, weapon selection, common firearm hit resolution, sniper scope toggle, pistol range/cooldown handling and ground enemy movement/attack/city damage integration to `air_defense/main.py`.
- [X] T024 [US3] Verify the User Story 3 focused tests, real raycast/camera smoke behavior and the manual walking/cover/pistol protocol in `specs/002-air-defense-wave-expansion/quickstart.md`.

**Checkpoint**: Ground enemies visibly walk along cover routes, obstacles can block the sniper ray, sniper scope actually zooms, and pistol combat is short-range with rapid cooldown.

## Phase 6: User Story 4 - Boss HUD 與城市防守 (Priority: P2)

**Goal**: Make Boss-wave health, city damage and terminal states understandable and correctly integrated with the full loop.

**Independent Test**: Start at wave 10 with an armored aircraft, verify aircraft HP, defeat it in five valid hits, verify ground Boss HP and defeat it in ten firearm hits; separately trigger city destruction.

### Tests for User Story 4

- [X] T025 [US4] Add failing HUD/state-facing cases in `tests/test_rules.py` for wave/type labels, armored-aircraft versus ground-Boss HP stage, city damage over time, city failure and frozen statistics after terminal failure.

### Implementation for User Story 4

- [X] T026 [P] [US4] Add wave number, aircraft progress/type, city health, armored-aircraft HP and ground-Boss HP displays to `air_defense/hud.py` according to `contracts/ui.md`.
- [X] T027 [US4] Integrate Boss encounter creation, HP refresh, city destruction event, terminal update freeze and reset behavior in `air_defense/main.py`; ensure old aircraft/encounter callbacks cannot alter the current wave.
- [X] T028 [US4] Run the complete Boss-wave and city-failure rule tests plus the controlled wave-10 manual flow in `specs/002-air-defense-wave-expansion/quickstart.md`.

**Checkpoint**: Boss and city states are visible, correctly counted and safely terminate or reset the session.

## Phase 7: Polish & Cross-Cutting Validation

**Purpose**: Finish documentation, preserve regressions and validate the runnable game.

- [X] T029 [P] Update `specs/002-air-defense-wave-expansion/quickstart.md` with observed controls, exact test results, platform limitations and any tuning changes made during integration.
- [X] T030 [P] Run `python -m compileall air_defense tests` and `python -m unittest discover -s tests -p "test_*.py" -v`; resolve all failures without weakening the feature contracts.
- [X] T031 Run the real Ursina button/input bridge smoke check from `specs/001-air-defense-game/quickstart.md` adapted for slots `1/2/3`, reticle switching, scope reset and the current `002` feature path; record the output in the new Quickstart.
- [ ] T032 Run `python -m air_defense.main` in a graphics-capable environment, complete the manual acceptance flow, measure the largest active scene FPS and document unreported measurements rather than inventing values.
- [X] T033 Review `air_defense/`, `tests/`, `specs/002-air-defense-wave-expansion/` and `git diff` for unused imports, duplicate rules, debug output, stale identifiers, missing reset paths and accidental changes to `day1/` or `day2/`.

## Dependencies & Execution Order

### Phase Dependencies

1. Setup T001–T003 is independent and establishes the shared constants/document boundary.
2. Foundational T004–T010 is blocking; write the failing tests before implementing state/entities/rules.
3. User Story 1 T011–T015 depends on the domain checkpoint and supplies the long map/aircraft behavior.
4. User Story 2 T016–T019 depends on the domain checkpoint and integrates wave progression with Story 1 aircraft.
5. User Story 3 T020–T024 depends on the domain type/encounter contracts and integrates ground movement and weapons.
6. User Story 4 T025–T028 depends on wave and ground integration so the controlled Boss flow is real.
7. Polish T029–T033 runs only after all desired stories pass their checkpoints.

### User Story Dependencies

- **US1**: Depends on Foundation; can be demonstrated with one aircraft.
- **US2**: Depends on Foundation and uses US1 aircraft lifecycle; its pure roster tests remain independently runnable.
- **US3**: Depends on Foundation and the aircraft-down event; pure movement/weapon tests are independent of rendering.
- **US4**: Depends on US2 and US3 for the full Boss aircraft → ground Boss → next aircraft loop.

### Parallel Opportunities

- T001–T003 use separate documentation/config concerns.
- T004–T007 touch the same test file and should be written sequentially; T008 and T009 can be split by file after the failing cases exist, while T010 waits for both.
- T012 and T013 are sequential scene work; T014 waits for both scene and domain type profiles.
- T021 and T022 can run in parallel because they touch separate adapters; T023 integrates them.
- T026 and T029 can run in parallel after their respective story contracts; T030–T033 are final gates.

## Implementation Strategy

### MVP First

1. Complete T001–T010 and the domain checkpoint.
2. Complete T011–T015 for a long map and one evasive aircraft.
3. Complete T016–T019 for multiple aircraft and deterministic waves.
4. Stop at the US2 checkpoint to demonstrate the core wave loop before adding ground-combat polish.

### Incremental Delivery

1. Domain foundation → deterministic type, wave and damage rules.
2. US1 → long map and evasive aircraft.
3. US2 → increasing waves and type-specific aircraft encounters.
4. US3 → walking cover route, sniper scope and pistol.
5. US4 → Boss HP, city destruction and terminal/reset behavior.
6. Polish → automated regression, real-window smoke and manual Quickstart evidence.

## Definition of Done

- Every task is marked `[X]` only after its referenced file exists and the described behavior is verified.
- All deterministic tests and syntax checks pass; real-window checks are recorded with their platform limitations.
- No feature change edits `day1/` or `day2/`, and pre-existing user modifications remain intact.
