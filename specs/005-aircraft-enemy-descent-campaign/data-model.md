# Data Model: 飛機擊落後敵人降落戰役

**Feature**: `005-aircraft-enemy-descent-campaign`
**Source**: [spec.md](./spec.md)

## State Enumerations

### `GamePhase`

| Value | Meaning | Allowed gameplay |
|---|---|---|
| `MAIN_MENU` | No active campaign | Start or quit only |
| `AIRSTRIKE` | Current wave has aircraft combat and no non-empty drop has started | Anti-aircraft weapon and aircraft targeting |
| `HYBRID_COMBAT` | Current wave has started at least one non-empty drop while at least one aircraft remains | Anti-aircraft, sniper and pistol; aircraft, descent and landed crew all update |
| `GROUND_COMBAT` | All current-wave aircraft are destroyed and ground encounter still has living/descent crew | Sniper and pistol; descent crew remains attackable |
| `GAME_OVER` | Player death, city destruction or aircraft impact ended the run | Frozen failure presentation |
| `VICTORY` | Wave 18 aircraft and ground enemies are all cleared | Frozen victory presentation and return-to-menu input |

`HYBRID_COMBAT` is sticky for the rest of the wave after the first non-empty drop begins. It does not activate for a zero-crew aircraft. When the last aircraft is destroyed, the state changes to `GROUND_COMBAT` if the encounter still has living crew; otherwise the wave completes immediately.

### `AircraftPhase`

Existing values remain: `APPROACHING`, `LOCKED`, `DESTROYED`, `IMPACTED`.

- `DESTROYED` is the only aircraft terminal value that satisfies the wave-clear aircraft condition.
- `IMPACTED` is terminal but immediately leads to `GAME_OVER` and never satisfies wave clear.

### `CrewBehaviorState`

Existing ground values remain: `IN_COVER`, `ADVANCING`, `RELOCATING`. Add `DESCENDING`.

- `DESCENDING` is alive and targetable, but is excluded from ground movement, attacks and city damage.
- A living member transitions from `DESCENDING` to `IN_COVER` exactly once at the end of its descent.
- A dead member is not eligible for any later descent or ground transition.

### `SessionEvent`

Retain existing events and add:

| Event | Payload | Guard / result |
|---|---|---|
| `DROP_STARTED` | stable event ID `(wave_number, source_aircraft_id)`, source aircraft ID, encounter ID | First non-empty batch marks the wave as hybrid when aircraft remain; the stable event ID makes duplicate callbacks idempotent |
| `WAVE_CLEARED` | event ID, optional next `WavePlan` | Starts the next plan for waves 1–17 or enters victory for wave 18 |
| `VICTORY` | event ID | Idempotently enters `VICTORY` only after final clear predicate |

`RETURN_TO_MENU` is valid from both `GAME_OVER` and `VICTORY`. Existing `CREW_CLEARED` remains available only for legacy scalar compatibility; the feature's keyed runtime MUST NOT use it to advance a wave or bypass either clear condition, and uses `WAVE_CLEARED` only after checking both conditions. Stable event IDs are required for repeatable gameplay callbacks and statistics (`AIRCRAFT_DESTROYED`, `DROP_STARTED`, crew defeat, `WAVE_CLEARED`, `VICTORY`); user commands such as `START_GAME` and `RETURN_TO_MENU` remain phase-guarded commands.

## Campaign Roster

### `WavePlan`

Immutable value with:

- `wave_number: int` — inclusive range 1–18.
- `aircraft_count: int` — length of `roster` and 2, 3 or 4 for the campaign table.
- `aircraft_cap: int` — compatibility cap; at least `aircraft_count`.
- `is_boss_wave: bool` — true when any roster slot is `ARMORED_BOSS`.
- `roster: tuple[AircraftType, ...]` — ordered aircraft types.

Validation:

- `wave_number` outside 1–18 is rejected for campaign plans.
- `aircraft_count` is positive and equals `len(roster)`.
- `aircraft_cap` is positive and at least `aircraft_count`.
- `ARMORED_BOSS` positions match the fixed table for default campaign plans.
- `MANPOWER_SUPPORT`／`FAST` assignments are derived from the 1-based global ordinal of `特` slots before and within the current roster: odd ordinals map to `MANPOWER_SUPPORT`, even ordinals map to `FAST`; the input alias `摩` is normalized to canonical token `魔` before lookup.
- The fixed-table Boss-position and special-rotation rules apply to default campaign plans; synthetic or directly constructed custom test plans must still satisfy the structural fields above but may intentionally provide their own roster for headless tests.

`WaveDirector.plan_wave(wave_number, aircraft_count=None, cap=None)` has two explicit modes:

1. With no override, it returns the fixed campaign plan and rejects wave numbers outside 1–18.
2. With an explicit `aircraft_count`／`cap`, it creates a deterministic synthetic headless fixture for existing tests and performance checks; the fixture does not change the campaign table or successor selection. The fixture roster repeats the existing regular type cycle. A test needing a custom roster constructs `WavePlan` directly rather than passing an undocumented argument to `plan_wave()`.

`next_progress()` must not create a successor from wave 18; the controller invokes the final clear path instead.

## `WaveRuntime`

Authoritative mutable ledger for one simultaneous wave:

- `wave: WaveProgress`
- `aircraft_ids: tuple[str, ...]` — ordered, unique, stable IDs.
- `aircraft_statuses: dict[str, AircraftPhase]` — exactly one entry per aircraft ID.
- `aircraft_types: dict[str, AircraftType]` — exactly one entry per aircraft ID.
- `active_target_id: Optional[str]` — current sticky anti-air target, if any.
- `ground_encounter_id: Optional[str]` — aggregate encounter ID once a drop exists.
- `drop_spawned_aircraft_ids: set[str]` — source IDs whose drop decision has been processed, including zero-crew sources.
- `hybrid_started: bool` — true after the first non-empty drop in this wave.

Derived values:

- `alive_aircraft_ids`: statuses `APPROACHING` or `LOCKED`.
- `remaining_aircraft_count`: size of `alive_aircraft_ids`.
- `all_aircraft_destroyed`: every aircraft status is `DESTROYED`.
- `all_drop_decisions_processed`: every aircraft ID has a resolved drop decision, including an intentionally empty batch.
- `has_active_drop`: `hybrid_started` or aggregate encounter contains an alive member.
- `can_complete_wave(ground_cleared: bool)`: `all_aircraft_destroyed and all_drop_decisions_processed and ground_cleared`.

Invariants:

- Unknown IDs, duplicate IDs, stale terminal transitions and regression from `LOCKED` to `APPROACHING` are rejected.
- A source ID can be marked drop-spawned only once.
- `IMPACTED` never counts as alive or cleared for a successful wave.
- Runtime reset creates a new ledger; it does not reuse source IDs from the previous wave.

## `Aircraft`

Existing movement and health fields remain. The destruction handler reads:

- `id`
- `aircraft_type`
- `position` at the exact destruction event
- `phase`
- `crew_spawned`

The position snapshot is immutable input to the source drop batch. Removing the aircraft scene entity must not erase the saved position before the batch is initialized.

## Logical Drop Batch

A drop batch is identified by `(wave_number, source_aircraft_id)` and is represented by its source-scoped crew members plus the runtime drop ledger; no separate manager object is required.

Batch rules:

- All members use one aggregate encounter ID and one source aircraft ID.
- All members are created in the same event boundary.
- Each member receives a deterministic X/Z spread offset from the fixed offset sequence; the maximum offset radius is 2.5 world units.
- Each member starts at `hit_position + offset` and lands at `(hit_x + offset_x, ground_level_y, hit_z + offset_z)`.
- Each member uses `descent_duration = 4.0` seconds and a clamped linear interpolation.
- The batch may be empty for `FAST`; the source is still marked processed.

## `CrewMember`

Existing identity, role, health and ground behavior fields remain. Add:

- `source_aircraft_id: str`
- `descent_start_position: tuple[float, float, float]`
- `landing_position: tuple[float, float, float]`
- `descent_elapsed: float`
- `descent_duration: float` — default 4.0 seconds.
- `descent_offset: tuple[float, float]` — deterministic X/Z offset.

Operations:

- `begin_descent(start_position, landing_position, duration, offset)` sets `DESCENDING`, clears `at_city`, retains full initial attack cooldown and clamps duration to a positive value.
- `advance_descent(delta_seconds) -> bool` clamps delta to non-negative, updates the linear position, returns `True` only on the first landing transition, and never updates a dead or already-landed member.
- `take_damage(amount)` transitions an alive member to dead once, clears `at_city`, and prevents later landing or attack.
- `ready_to_attack()` returns false while `DESCENDING` and otherwise retains existing cooldown semantics.

## `GroundEncounter`

Aggregate fields:

- `aircraft_id`／`group_id`: `wave-<wave_number>` identity.
- `crew: list[CrewMember]`: all members from all processed non-empty source batches.
- `crew_count`: always `len(crew)` after construction or reinforcement.
- `source_aircraft_ids: tuple[str, ...]`: source order, no duplicates.
- `boss_id`: first Boss member ID if any; Boss members from multiple Boss aircraft remain independently addressable by crew ID.
- `cleared`: true only when no member in `crew` is alive.
- `batch_progress: dict[str, BatchProgress]`: source aircraft keyed progress; each entry tracks `spawned_count`, `alive_count` and idempotent `cleared_count`.
- `city_damage_accumulator`: existing aggregate statistic.

`add_reinforcement(members, source_aircraft_id)` validates source uniqueness, member IDs, matching encounter ID and source IDs, appends the batch in roster order, initializes its `BatchProgress`, updates count/source list, and recalculates `cleared`. `record_crew_cleared(member_id)` returns false unless the member exists, is dead, and has not already been counted; on success it decrements that source batch's `alive_count` and increments its `cleared_count` exactly once. `batch_progress(source_aircraft_id)` exposes the independent counters. An empty batch is not added.

### `BatchProgress`

Source-scoped progress record for one aircraft batch, owned by the aggregate encounter:

- `source_aircraft_id: str`
- `spawned_count: int`
- `alive_count: int`
- `cleared_count: int`

`spawned_count = alive_count + cleared_count` for a processed batch. Clearing a member decrements `alive_count` and increments `cleared_count` exactly once; a dead descending member contributes to `cleared_count` immediately and never contributes again. Landing state is read from the member records rather than changing the clear counter.

## Session Transition Matrix

| Current | Event / condition | Next | Required side effects |
|---|---|---|---|
| `MAIN_MENU` | `START_GAME` | `AIRSTRIKE` | Reset health, city, stats, weapons, runtime; spawn wave 1 |
| `AIRSTRIKE` | non-empty drop starts with aircraft alive | `HYBRID_COMBAT` | Enable rack, preserve aircraft and create batch |
| `AIRSTRIKE`／`HYBRID_COMBAT` | aircraft destroyed, aircraft remain | same／`HYBRID_COMBAT` | Remove only source aircraft; create its batch |
| `HYBRID_COMBAT` | all aircraft destroyed, crew alive | `GROUND_COMBAT` | Keep descent/ground encounter active; disable aircraft target selection |
| `AIRSTRIKE`／`HYBRID_COMBAT` | all aircraft are `DESTROYED` and no encounter exists or encounter is cleared | `AIRSTRIKE` for waves 1–17／`VICTORY` for wave 18 | Complete the wave directly without entering empty `GROUND_COMBAT` |
| any gameplay phase | aircraft impact, player death or city destruction | `GAME_OVER` | Stop updates, clear dynamic effects, freeze failure snapshot |
| `GROUND_COMBAT` | all aircraft destroyed and crew cleared, wave < 18 | `AIRSTRIKE` | Clear current runtime/encounter, build next fixed plan, spawn full roster |
| `GROUND_COMBAT` | all aircraft destroyed and crew cleared, wave = 18 | `VICTORY` | Stop updates, freeze stats, show victory presentation |
| `GAME_OVER`／`VICTORY` | `RETURN_TO_MENU` | `MAIN_MENU` | Clear entities and reset all session state |

## Reset and Counting Rules

- Aircraft destruction and crew defeat use stable event IDs and update statistics at most once.
- Descent death counts as an enemy defeat but never as a ground attack or city-damage event.
- Weapon cooldowns, lock state, target state, missiles, source drop ledger and scene maps are reset at game start, next wave, failure, victory and return to menu according to their existing lifecycle.
- Weapon switching retains each weapon's own cooldown; it does not reset the campaign or encounter.
