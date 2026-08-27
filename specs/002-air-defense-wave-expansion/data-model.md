# Data Model: 3D 防空守衛波次與 Boss 擴充

## Overview

The session remains in memory. One session owns the current wave plan, one active aircraft and at most one active ground encounter. A wave completes only after every aircraft in its roster and every non-empty ground encounter has resolved.

## Enums and Profiles

### `AircraftType`

| Value | Flight behavior | Aircraft HP | Ground result |
|---|---|---:|---|
| `NORMAL` | Standard speed and medium lateral weave | 1 | Random 0–3 regular enemies |
| `MANPOWER_SUPPORT` | Slow approach and low-amplitude weave | 1 | Exactly 6 regular enemies |
| `FAST` | Fast approach and stronger weave | 1 | No ground enemies |
| `ARMORED_BOSS` | Slow armored approach and visible weave | 5 | Exactly 1 ground Boss with 10 HP |

### `WeaponKind`

`ANTI_AIRCRAFT`, `SNIPER`, `PISTOL`.

### `FailureReason`

Existing `BUILDING_IMPACT` and `PLAYER_DEAD`, plus `CITY_DESTROYED`.

## Wave State

### `WaveProgress`

| Field | Type | Rules |
|---|---|---|
| `wave_number` | positive integer | Starts at 1; increases only after the complete roster is resolved |
| `aircraft_index` | non-negative integer | Index of the active aircraft in the current roster |
| `aircraft_count` | positive integer | Wave 1 is 2; each later wave is previous count + 1 |
| `aircraft_cap` | positive integer | Starts at 6; after reaching it, the next wave cap increases by 2 |
| `is_boss_wave` | boolean | True when `wave_number % 10 == 0` |
| `roster` | list[`AircraftType`] | Length equals `aircraft_count`; regular waves contain no armored type, Boss waves contain exactly one |

The first counts are 2, 3, 4, 5, 6, 7, 8, 9, 10. Cap milestones are 6, 8, 10 and onward; a count increment never skips a number merely because a cap changed.

### `WavePlan`

An immutable plan containing `wave_number`, `aircraft_count`, `aircraft_cap`, `is_boss_wave` and the ordered `roster`. The regular type cycle is `NORMAL → MANPOWER_SUPPORT → FAST`, offset by the current cap band. On a Boss wave, roster index 0 is `ARMORED_BOSS`; every other slot uses the regular cycle.

## Session State

`GameSession` retains the existing phases `MAIN_MENU`, `AIRSTRIKE`, `GROUND_COMBAT` and `GAME_OVER`, and adds:

| Field | Type | Rules |
|---|---|---|
| `wave` | `WaveProgress` | Reset to wave 1 on a new session |
| `active_aircraft_type` | `AircraftType \| None` | Must match the active roster slot |
| `city_health` | number | Starts at `CITY_MAX_HEALTH` (100); fractional per-frame damage is allowed, and zero emits `CITY_DESTROYED` |
| `active_aircraft_id` | identifier | Only one valid id at a time |
| `active_encounter_id` | identifier or None | Empty encounters resolve immediately |

Old aircraft, encounter and failure event guards remain mandatory.

## Entities

### `Aircraft`

Fields include `id`, `aircraft_type`, `start_position`, `target_position`, `flight_duration`, `path_progress`, `evasion_elapsed`, `evasion_amplitude`, `evasion_frequency`, `health`, `max_health`, `phase` and `crew_spawned`.

- `advance(delta)` changes forward progress and evasion phase continuously.
- `position` applies a bounded lateral offset to the forward path.
- `take_damage(1)` returns true only when health reaches zero; destroyed or impacted aircraft reject later damage.

### `CrewMember`

Fields include `id`, `encounter_id`, `position`, `cover_node`, `target_cover_node`, `route_index`, `move_speed`, `behavior_state`, `health`, `max_health`, `is_boss`, `attack_cooldown`, `advance_elapsed`, `at_city` and `city_attack_elapsed`.

- A normal member starts with 1 HP; the ground Boss starts with 10 HP.
- Movement is limited to `move_speed * delta_seconds` and uses only configured route nodes plus the city attack point.
- `take_damage(1)` updates health and returns true only on defeat.
- A defeated member cannot shoot, damage the city or move.

### `GroundEncounter`

Fields include `aircraft_id`, `aircraft_type`, `crew`, `crew_count`, `boss_id`, `cleared` and `city_damage_accumulator`.

- Normal, support, fast and armored creation rules come from the aircraft type.
- `crew_count == 0` means `cleared == True` immediately.
- No reinforcement operation is allowed; each encounter belongs to exactly one aircraft.

### `TargetBuilding`

Fields include `id`, `position`, `max_health=100`, `health`, `collision_radius`, `is_protected` and `attack_zone_radius`.

- Aircraft impact remains an immediate `BUILDING_IMPACT` event.
- Living ground enemies inside the attack zone apply city damage over time.
- Health cannot fall below zero; the first zero-health event transitions to `GAME_OVER` with `CITY_DESTROYED`.

### Weapons

| Weapon | Phase | Damage | Cooldown | Range/lock |
|---|---|---:|---:|---|
| Anti-aircraft | Airstrike | 1 aircraft HP | Existing 1.25 s | 3 s uninterrupted green lock |
| Sniper | Ground | 1 enemy HP | Existing 0.75 s | Long center ray; right-click scope |
| Pistol | Ground | 1 enemy HP | 0.20 s | Maximum 12 units; compact reticle |

## State Transitions

1. `MAIN_MENU → AIRSTRIKE`: start a new `WaveProgress`, reset city/player/stats and spawn roster slot 0 from the far spawn point.
2. `AIRSTRIKE → AIRSTRIKE/GROUND_COMBAT`: a valid anti-air hit subtracts aircraft HP. If HP remains, reset lock and continue; if HP reaches zero, create its type-specific encounter.
3. Downed aircraft with an empty encounter immediately advances to the next roster slot. A non-empty encounter enters `GROUND_COMBAT`.
4. `GROUND_COMBAT → AIRSTRIKE`: all encounter members are defeated; advance to the next aircraft or create the next wave if the roster is complete.
5. `AIRSTRIKE → GAME_OVER`: aircraft reaches the target building before destruction.
6. `GROUND_COMBAT → GAME_OVER`: player health or city health reaches zero; the first guarded failure event wins.
7. `GAME_OVER → MAIN_MENU`: return action clears wave, city, aircraft, encounter, weapons, cooldowns, reticles and statistics.

## Invariants

- Only one active aircraft and one active encounter exist.
- Regular waves contain no `ARMORED_BOSS`; each Boss wave contains exactly one.
- Aircraft and crew positions change continuously within their configured speed limits.
- Ground enemies cannot move outside the authored route or through obstacle nodes.
- Only anti-air equipment shows the anti-air lock frame; sniper and pistol use their own reticles.
- Pistol cannot hit targets beyond 12 units; scope state cannot persist after leaving sniper.
- A standard aircraft takes one valid anti-air hit; an armored aircraft takes five; the ground Boss takes ten firearm hits.
- Every aircraft, crew defeat, city damage failure and player death is counted or applied at most once.
