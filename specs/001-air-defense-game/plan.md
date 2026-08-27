# Implementation Plan: 3D 防空守衛無限模式

**Branch**: `001-air-defense-game` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `./spec.md`

## Summary

建立一個獨立的 Python 第一人稱 3D 桌面遊戲套件，實作「從物品欄按 `1` 選用防空炮並擊落自殺式戰鬥機 → 按 `2` 直接切換狙擊槍清除該機乘員 → 下一架戰鬥機立即來襲」的無限循環。遊戲使用 Ursina 8.3.0 提供 3D 視窗、第一人稱控制、碰撞與中心 raycast；鎖定計時、階段轉移、生成數量、計分與失敗競速規則保持在不依賴引擎的純 Python 邏輯中。

## Technical Context

**Language/Version**: Python 3.13.5 in the current virtual environment; this feature requires Python 3.12+ because of the pinned Ursina 8.3.0 dependency.

**Primary Dependencies**: `ursina==8.3.0`; its resolved runtime dependencies include Panda3D, Pillow and pyperclip. Python standard library `unittest` is used for pure-logic tests.

**Storage**: N/A; all game state and session statistics are in memory and reset when returning to the main menu.

**Testing**: `python -m compileall`, Python `unittest` discovery for engine-independent rules, a real Ursina button/event smoke check, and the manual end-to-end flow in [quickstart.md](./quickstart.md).

**Target Platform**: Windows desktop with keyboard, mouse and a graphics-capable window; offline single-player execution.

**Project Type**: Single-player desktop 3D game.

**Performance Goals**: Maintain a nominal 60 FPS during the playable loop with one active aircraft, one target building and at most five active crew members; UI state changes must be visible on the next rendered frame. The final smoke/acceptance run records the observed FPS and hardware.

**Constraints**: One small city-block scene; one active aircraft per cycle; one finite group of 2–5 crew members per downed aircraft; no ground reinforcements, multiplayer, save data, network services or building-damage subsystem. Game-specific dependencies and source remain isolated from the existing Pygame teaching examples.

**Scale/Scope**: One playable map, one target building, one defense point, one weapon display rack, two inventory slots, predefined cover nodes, an endless aircraft/crew cycle, and one game-over flow.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Readability and incremental abstraction**: PASS. The design uses a small number of responsibility-focused modules and avoids a general-purpose framework.
- **II. Encapsulated game objects**: PASS. Player, weapons, aircraft, building and crew own their direct state/behavior; session rules remain in named coordinators.
- **III. Small, verifiable steps**: PASS. Locking, state transitions, event de-duplication, generation and statistics are engine-independent and covered by `unittest` cases before full scene integration.
- **IV. Explicit loop and state transitions**: PASS WITH SCOPED FEATURE EXCEPTION. `MAIN_MENU`, `AIRSTRIKE`, `GROUND_COMBAT` and `GAME_OVER` are explicit; the existing constitution's ball-specific states and victory state do not apply to this endless aircraft game. The exception, equivalent states, full frame order and one-time event guards are documented in [spec.md](./spec.md), [data-model.md](./data-model.md) and the task checkpoints.
- **V. Appropriate scope and simple dependencies**: PASS WITH SCOPED EXCEPTION. The feature requires true 3D, so the existing Pygame-only default is replaced for this isolated game package by Ursina; the exception, impact and rollback boundary are recorded in Complexity Tracking below.

**Gate result**: PASS WITH TWO DOCUMENTED, FEATURE-SCOPED EXCEPTIONS. The project owner selected a Python 3D engine and an endless no-victory loop; the reasons, risks, equivalent states, approval and rollback boundaries are recorded in [spec.md](./spec.md) and Complexity Tracking below. The feature introduces no changes to the existing Pygame examples, and the new dependency is isolated in `requirements-game.txt`.

## Project Structure

### Documentation (this feature)

```text
specs/001-air-defense-game/
├── plan.md              # This implementation plan
├── research.md          # Phase 0 technology and design decisions
├── data-model.md        # Entities, states and invariants
├── quickstart.md        # Setup and end-to-end validation flow
├── contracts/
│   └── ui.md            # Keyboard/mouse and HUD contract
└── tasks.md             # Phase 2 output from $speckit-tasks
```

### Source Code (repository root)

```text
air_defense/
├── __init__.py
├── main.py              # Application entry point and frame/update orchestration
├── config.py            # Window, colors, rates, timing and gameplay constants
├── state.py             # Enums and engine-independent session data
├── rules.py             # Locking, transitions, encounters, damage and statistics
├── entities.py          # Player, weapon, aircraft, building and crew objects
├── scene.py             # Ursina scene construction, raycast and collision adapters
└── hud.py               # Main menu, inventory bar, aiming overlay, HUD and game-over presentation

tests/
└── test_rules.py        # Deterministic engine-independent behavior tests

assets/
└── air_defense/
    ├── README.md        # Asset sources, licenses and fallback policy
    └── ...              # Optional CC0 low-poly models/textures

requirements-game.txt   # Direct game dependency: ursina==8.3.0
```

**Structure Decision**: Use one shallow `air_defense` package plus one test module. `state.py` and `rules.py` remain independent of Ursina so the difficult timing and event-order rules are easy to test; `entities.py`, `scene.py` and `hud.py` contain the engine-facing behavior. This is enough separation for the game loop without introducing services, plugins or unused future layers. Existing `day1/` and `day2/` files are not edited.

## Design Overview

### Runtime boundaries

- `main.py` owns the complete frame sequence: limit frame rate, process window events, read gameplay input, update entities/state, resolve collisions and domain rules, update animations, update HUD, draw the scene, then display the frame.
- `state.py` defines `GamePhase`, `LockState`, `FailureReason`, session data and statistics.
- `rules.py` exposes pure operations for lock progression, lock reset, weapon transitions, aircraft outcome ordering, crew generation, encounter completion, damage and one-time statistics updates.
- `scene.py` translates the current camera center into a raycast result and translates engine collisions into domain events; it does not decide whether a game event is counted twice.
- `hud.py` follows [contracts/ui.md](./contracts/ui.md), including the two-slot inventory bar, white/red/green lock states, warning text and failure statistics.

### Key interfaces

- `LockOnTracker.update(target_visible: bool, delta_seconds: float) -> LockState`: accumulates uninterrupted target time, returns `WHITE`, `RED_TRACKING` or `GREEN_READY`, and resets immediately when visibility is false.
- `GameSession.transition(event) -> GamePhase`: applies one guarded domain event such as `AIRCRAFT_DESTROYED`, `BUILDING_IMPACT`, `CREW_CLEARED` or `PLAYER_DIED`.
- `EncounterFactory.create_for_aircraft(aircraft_id, random_source) -> GroundEncounter`: creates exactly one encounter with a crew count from 2–5 and no reinforcement path.
- `SessionStats.record_once(event_id, event_type)`: prevents duplicate aircraft, crew or failure counts when engine callbacks repeat.

### Implementation sequence

1. Add the isolated game dependency file and a minimal Ursina launch screen; confirm the selected Python environment can open and close a window.
2. Implement `state.py` and `rules.py` with deterministic unit tests for locking, weapon ownership, event ordering, crew counts, damage and statistics.
3. Build the small city scene, target building, defense point, weapon display rack, player movement, two-slot inventory bar and optional pickup/drop interactions.
4. Add aircraft approach, the 8-second warning threshold, center-ray lock detection, 0.12-second red/green frame behavior, guided-shot result and building-impact failure.
5. Add finite crew encounters, deterministic cover-node/group behavior, enemy damage, inventory-slot sniper/right-mouse aim/shoot and encounter clearing, including the next-aircraft case while the player still holds the sniper.
6. Add main menu buttons plus keyboard fallbacks, game-over view, session reset, statistics, asset loading and procedural fallbacks.
7. Run syntax checks, unit tests and the complete manual quickstart flow; tune only centralized constants needed to keep the loop playable.

## Testing Strategy

- **Unit tests**: cover the 3-second lock threshold, 0.12-second red state timing, stable green state, immediate reset on target loss, fire gating, one-time aircraft destruction, building-impact precedence, 2–5 crew generation, deterministic cover/role assignment, 2-second advance timing, no reinforcement, one-hit sniper result, right-mouse aim state, health-zero failure and clean session reset.
- **Scene smoke test**: launch the game, verify clickable main-menu buttons and keyboard fallbacks, player movement, colliders, two-slot inventory selection, optional weapon pickup/drop and HUD state changes without requiring external assets.
- **End-to-end manual test**: follow the counted protocol in [quickstart.md](./quickstart.md): the 30-second start flow, 10 lock attempts, 5 complete cycles, 5 one-time crew-generation checks, both failure causes with the 1-second response measurement, the exit action and the 5-person first-time HUD comprehension check.
- **Performance check**: measure the playable scene at one aircraft, one building and five crew members; record FPS and hardware, and report any inability to meet the nominal 60 FPS target.
- **Regression check**: run the new tests and syntax check without changing or requiring the existing `day1`/`day2` scripts.

## Post-Design Constitution Check

- Principles I–III remain PASS after design: module responsibilities, object ownership and pure-rule tests are represented in the chosen structure.
- Principle IV remains PASS WITH THE SAME FEATURE-SCOPED EXCEPTION: the ball-specific and victory states are replaced by the four documented aircraft-game phases, while the full required frame order, explicit transitions and event de-duplication remain enforced.
- Principle V remains PASS WITH THE SAME SCOPED EXCEPTION: the Ursina dependency is direct and version-pinned, its purpose and installation are documented, and the game runtime is isolated from the Pygame examples.
- No additional complexity violation was introduced; optional art assets have a procedural fallback and are not required for startup.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Existing project defaults to Pygame, while this feature uses Ursina/Panda3D runtime | The requested true 3D first-person camera, scene collisions, center-ray targeting and 3D aircraft/building interaction cannot be represented faithfully by the existing 2D Pygame approach without building a separate rendering/collision layer. | Pygame pseudo-3D would fail the feature's true-3D requirement; migrating the existing teaching examples would expand scope and risk unrelated regressions. |
| Constitution Principle IV contains ball-game and victory-state examples that do not fit an endless aircraft game | FR-012 explicitly requires continuous play until player death, so adding an unrelated victory state or ball lifecycle would create behavior outside the requested scope. | Forcing those states would conflict with FR-012 and add untestable gameplay branches; the feature instead documents equivalent phases, explicit terminal failure, frame order and rollback scope. |

The project owner confirmed the two feature-scoped exceptions during requirements discussion and this remediation pass. Before implementation, keep the documented approval, version boundary, risk controls and rollback scope intact.
