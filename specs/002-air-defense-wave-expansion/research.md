# Research: 3D 防空守衛波次與 Boss 擴充

## Decision 1: Reuse the existing Ursina/Panda3D runtime

- **Decision**: Keep `ursina==8.3.0`, the current procedural-geometry scene and the existing first-person controller.
- **Rationale**: The repository already has a working 3D window, camera raycast, colliders, HUD bridge and asset-free startup. A second engine would duplicate input/rendering code and increase the approved dependency exception.
- **Alternatives considered**: Rebuilding the game in Pygame would not provide the requested true 3D camera and obstacle occlusion; adding a new 3D engine is unnecessary for the current prototype.

## Decision 2: Keep gameplay rules engine-independent

- **Decision**: Put wave rosters, type profiles, health, movement limits, city damage, weapon range and event guards in `state.py`, `rules.py` and `entities.py`.
- **Rationale**: The current project already tests lock timing and encounter behavior without opening a graphics window. The new requirements contain deterministic boundaries—five aircraft hits, ten Boss hits, 12-unit pistol range and speed-limited movement—that should remain reproducible.
- **Alternatives considered**: Storing these rules only on Ursina Entities would make headless tests difficult and would allow visual callbacks to bypass de-duplication.

## Decision 3: Use a deterministic wave roster with a type cycle

- **Decision**: Start at two aircraft; increase by one per wave; use cap milestones 6, 8, 10 and onward; rotate regular slots through normal, manpower support and fast. Every tenth wave replaces the first slot with one armored Boss.
- **Rationale**: This exactly expresses the confirmed product rule while keeping tests stable and ensuring regular waves never accidentally create an armored Boss.
- **Alternatives considered**: Fully random rosters would make acceptance tests flaky and could omit a requested aircraft type for many waves; a fixed three-aircraft roster would not satisfy the increasing-pressure requirement.

## Decision 4: Implement evasion and walking as bounded continuous movement

- **Decision**: Aircraft use a bounded lateral weave over a forward interpolation; ground enemies move toward fixed route points with a per-frame distance limit and only then change their cover node.
- **Rationale**: Both requirements explicitly reject static/teleported behavior. A deterministic weave and waypoint interpolation are simple enough for the current shallow architecture and easy to assert in unit tests.
- **Alternatives considered**: Full pathfinding is unnecessary because the route is authored around fixed cover obstacles; instant node assignment fails the user-visible movement requirement.

## Decision 5: Let the existing center raycast provide obstacle occlusion

- **Decision**: Give map obstacles colliders and place crew visual entities behind them at route nodes; do not add a separate geometric visibility service.
- **Rationale**: The existing `center_raycast` already returns the first collidable entity. Preserving that path means the same line-of-sight result governs sniper hit selection and visual cover.
- **Alternatives considered**: A second line-of-sight calculation could disagree with the rendered scene and duplicate collision logic.

## Decision 6: Add pistol as a third direct inventory slot and scope zoom through FOV

- **Decision**: Use `1` anti-air, `2` sniper, `3` pistol; use right-click scope toggle with FOV 90/35; pistol uses 0.20-second cooldown and 12-unit range.
- **Rationale**: The three-slot choice was confirmed by the user. Camera FOV is the smallest change that produces actual zoom while the HUD adds a clear scope overlay; pistol range/cooldown are centralized balance defaults.
- **Alternatives considered**: Keeping two slots would make the third weapon ambiguous; a decorative scope overlay without FOV change would not satisfy “放大”.

## Decision 7: Model city destruction as a finite health resource

- **Decision**: City starts at 100 health; every living enemy in the city attack zone deals 10 damage per second; zero health triggers `CITY_DESTROYED`.
- **Rationale**: The user specified that enemies begin destroying the city after arrival. A visible health resource makes that behavior observable and gives the player time to respond instead of introducing an undocumented instant failure.
- **Alternatives considered**: Immediate failure on first arrival would not represent “開始破壞”; a background-only route would not make city attack mechanically meaningful.
