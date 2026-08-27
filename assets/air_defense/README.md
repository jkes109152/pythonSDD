# Air-defense game assets

The prototype starts with procedural Ursina geometry, so external art is never a
startup dependency. Optional models and textures may be added under this folder
only after their source, license and redistribution terms have been recorded.

## Approved asset policy

- Prefer original project assets or clearly licensed CC0 assets.
- Record the source URL, asset name, license and local filename before use.
- Do not commit assets with unclear redistribution rights.
- Keep a procedural-geometry fallback for every optional model so the manual
  quickstart and automated rule tests work without downloading assets.

## Current asset inventory

| Local file | Source/license | Runtime role |
|---|---|---|
| `README.md` | Project documentation | Records the asset policy; not loaded by the game |
| *(none)* | *(none)* | All aircraft, crew, buildings, weapons, roads and cover are procedural Ursina geometry |

The HUD may use an already-installed Windows Traditional Chinese system font
(`NotoSansTC-VF.ttf` or `kaiu.ttf`); it is not redistributed by this project and
is never a startup dependency. If no such font exists, the game falls back to
Ursina's bundled font and the platform limitation is documented in
`specs/001-air-defense-game/quickstart.md`.
