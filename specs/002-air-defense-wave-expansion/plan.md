# Implementation Plan: 3D 防空守衛波次與 Boss 擴充

**Branch**: `002-air-defense-wave-expansion` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `./spec.md`

## Summary

在既有 `air_defense` Ursina 遊戲上擴充長型平原、固定障礙物、遠距離閃避敵機、波次編隊、三格武器欄與 Boss 流程。遊戲維持「同一時間一架敵機、一組地面遭遇」的循環；波次排程、敵機類型、生命值、城市破壞與移動限制放在不依賴 Ursina 的 domain 層，`scene.py` 負責把連續 domain 位置與視線遮蔽轉成 3D Entity，`hud.py` 負責依武器與 Boss 階段顯示正確準心與生命值。

## Technical Context

**Language/Version**: Python 3.13.5 in the current environment; retain the existing Python 3.12+ requirement.

**Primary Dependencies**: Existing `ursina==8.3.0` and its Panda3D runtime; Python standard library `dataclasses`, `enum`, `math`, `random` and `unittest`. No new dependency.

**Storage**: N/A; wave state, city health, aircraft health and encounter state remain in memory and reset on a new session.

**Testing**: `python -m compileall air_defense tests`, deterministic `unittest` for domain rules, existing real Ursina event smoke check, and the manual visual/gameplay flow in [quickstart.md](./quickstart.md).

**Target Platform**: Windows desktop with keyboard, mouse and a graphics-capable window; offline single-player execution.

**Project Type**: Single-player desktop 3D game.

**Performance Goals**: Preserve the nominal 60 FPS target with the extended map, one active aircraft and the largest supported active ground group; HUD state changes must be visible on the next rendered frame.

**Constraints**: Keep one active aircraft and one active encounter; use procedural geometry fallback; do not modify `day1/` or `day2/`; keep the existing lock duration and event de-duplication rules unless this specification explicitly extends them.

**Scale/Scope**: One long plain map, at least eight collidable obstacles, at least five cover nodes, three weapons, three regular aircraft archetypes, one armored aircraft Boss, one ground Boss, unbounded wave progression and one city-destruction failure state.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Readability and incremental abstraction**: PASS. Add only focused value objects and rule functions for wave planning, damage and movement; keep the existing shallow package layout.
- **II. Encapsulated game objects**: PASS. Aircraft, crew, weapons, city and wave progress own their state; cross-object outcomes remain in named rule/session coordinators.
- **III. Small, verifiable steps**: PASS. New wave, type, health, movement, city and HUD-selection behaviors have deterministic tests and manual checkpoints.
- **IV. Explicit loop and state transitions**: PASS. Existing `MAIN_MENU`, `AIRSTRIKE`, `GROUND_COMBAT` and `GAME_OVER` remain; zero-crew aircraft resolve through a guarded immediate transition, and city destruction adds an explicit terminal failure reason.
- **V. Appropriate scope and simple dependencies**: PASS. The feature reuses the existing Ursina dependency and procedural assets; no service, persistence layer or new framework is introduced.

**Gate result**: PASS. The design extends the already approved isolated 3D game package without changing the teaching examples or adding dependencies.

## Project Structure

### Documentation (this feature)

```text
specs/002-air-defense-wave-expansion/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui.md
└── tasks.md
```

### Source Code (repository root)

```text
air_defense/
├── config.py       # map dimensions, route/obstacle positions, type and weapon tuning
├── state.py        # enums, wave progress, session/city/failure state
├── rules.py        # wave plans, type profiles, damage, movement, range and event guards
├── entities.py     # aircraft, weapons, city and walking ground-enemy state
├── scene.py        # long 3D map, colliders, obstacle LOS, smooth visual movement and FOV
├── hud.py          # wave/type/city/Boss status and weapon-specific reticles
└── main.py         # frame ordering, wave/encounter orchestration and input integration

tests/
└── test_rules.py   # engine-independent regression and feature tests
```

**Structure Decision**: Extend the existing shallow package rather than adding a new engine or service layer. `state.py`, `rules.py` and most entity behavior remain importable without Ursina; `scene.py`, `hud.py` and `main.py` translate those results to the live game.

## Design Overview

### Wave and aircraft lifecycle

- `WaveDirector` creates an immutable `WavePlan` containing the wave number, aircraft count, Boss-wave flag and a deterministic type list. Count starts at 2 and increases by 1. Caps begin at 6; after a wave reaches its current cap, the next cap is increased by 2.
- Regular type selection cycles `NORMAL`, `MANPOWER_SUPPORT`, `FAST` with a wave-band offset. Boss waves replace the first slot with `ARMORED_BOSS` and leave every other slot non-Boss.
- `GameSession` tracks the current wave, aircraft index, active aircraft id/type and city health. Clearing a ground encounter advances the index; only the final aircraft advances the wave and rebuilds the roster.
- A downed aircraft with zero ground enemies uses an empty, already-cleared encounter and immediately advances to the next aircraft. There is never more than one live aircraft or encounter.

### Aircraft and ground rules

- Aircraft have `aircraft_type`, `health`, `max_health`, speed profile and an elapsed evasion phase. Their position is a continuous flight-path interpolation plus bounded lateral weaving; `ARMORED_BOSS` has 5 health and each valid green-lock shot removes exactly 1.
- `EncounterFactory` maps the aircraft type to `0–3` random crew, exactly `6` support crew, `0` fast crew or exactly one 10-health ground Boss. Standard crew has 1 health; every firearm hit removes 1.
- Ground members keep a continuous world position, current node, target node, movement speed and city-attack state. Rules move them toward route nodes by at most `speed * delta`, and only mark a node reached after arrival. Cover shooters can fire from cover; advancing members move between fixed nodes.
- The city starts at 100 health. Each living member in the city attack zone applies 10 damage per second. Zero city health emits `CITY_DESTROYED`; aircraft impact and player death remain separate first-event-wins failures.

### Scene, weapons and HUD

- The scene changes the square ground plane to a long rectangle centered around the city route, with at least eight static colliders arranged around five or more cover nodes. Center raycasts naturally hit these obstacles before a covered enemy.
- `WeaponKind` gains `PISTOL`. The inventory bar has `1=ANTI_AIRCRAFT`, `2=SNIPER`, `3=PISTOL`; phase validation allows only slot 1 in airstrike and slots 2/3 in ground combat.
- HUD owns three mutually exclusive reticle modes: anti-air lock frame, sniper crosshair and compact pistol reticle. The lock frame is disabled for sniper, pistol and empty hand. Sniper right-click toggles the scope overlay and changes camera FOV from 90 to 35; switching away restores FOV 90. Pistol uses 0.20-second cooldown and 12-unit maximum raycast distance.
- The HUD always shows wave and aircraft progress, current aircraft type, player health, city health and existing statistics. Boss-wave status shows armored aircraft HP while the Boss aircraft is active and ground Boss HP after the Boss aircraft is downed.

### Public internal interfaces

- `WaveDirector.plan_wave(wave_number, aircraft_count=None, cap=None) -> WavePlan` uses the director's count/cap progression by default while allowing explicit values for deterministic rule tests; `WaveDirector.next_progress(progress) -> WaveProgress` produces the next count/cap state.
- `EncounterFactory.create_for_aircraft(aircraft_id, aircraft_type, random_source) -> GroundEncounter` creates the type-specific finite group.
- `Aircraft.take_damage(amount) -> bool`, `CrewMember.take_damage(amount) -> bool` and `TargetBuilding.take_damage(amount) -> bool` apply guarded health changes and report destruction.
- `advance_crew_behavior(encounter, delta_seconds, route_positions=None, city_position=None) -> None` updates continuous movement and city-arrival state without engine objects, using configured route/city positions when callers omit them.
- `can_fire_sniper(...)` and `can_fire_pistol(...)` enforce weapon ownership, cooldown and range; HUD exposes `update_reticle(weapon, phase, scope_enabled=False)` and `update_boss_health(...)` for rendering.

## Implementation Sequence

1. Add failing pure-rule tests for wave counts/rosters, type-specific encounters, health damage, continuous movement, city destruction, weapon range/cooldowns and reticle selection.
2. Extend configuration, enums, session state and domain entities; implement wave/type/health/movement rules until all new pure tests pass.
3. Rebuild the scene map with the long route, collidable obstacles, aircraft evasion visuals, continuous crew positions and scope FOV bridge.
4. Expand HUD and input integration for wave progress, Boss/city health, three inventory slots, sniper scope, pistol firing and mutually exclusive reticles.
5. Integrate sequential aircraft/encounter/wave transitions, zero-crew skipping, Boss phases and city-destruction failure in `main.py`.
6. Run the complete regression suite, real Ursina event smoke check, manual Quickstart flow and performance observation; mark tasks only after their checks pass.

## Testing Strategy

- **Domain unit tests**: wave count/cap sequence, regular/Boss rosters, four aircraft profiles, health hit counts, one-time events, zero-crew transitions, continuous movement, route boundaries, city damage and pistol/sniper gates.
- **Scene/HUD smoke test**: verify the long world and colliders load without external assets, aircraft/crew visual positions follow domain positions, obstacle raycasts hide covered enemies, FOV changes for scope, and exactly one reticle family is visible at a time.
- **End-to-end manual test**: follow [quickstart.md](./quickstart.md), including first-wave controls, fast/support/normal behaviors, multiple waves, city attack, Boss wave 10, five aircraft hits, ten ground-Boss hits and reset.
- **Regression/performance**: run compileall and all tests; ensure existing 001 behavior remains intact; measure the largest supported active scene and record actual FPS/hardware if 60 FPS is not reached.

## Post-Design Constitution Check

- Principles I–III remain PASS: the plan adds focused domain objects, incremental tests and no unnecessary abstraction.
- Principle IV remains PASS: existing phases are retained, empty encounters are explicitly resolved, city destruction is terminal, and every transition has de-duplication and reset behavior.
- Principle V remains PASS: no new dependency or external asset requirement is introduced, and changes stay within `air_defense/`, `tests/` and this feature directory.

## Complexity Tracking

No new constitution exception is required. This feature reuses the existing scoped Ursina/Panda3D exception documented in `specs/001-air-defense-game/` and does not alter its rollback boundary.
