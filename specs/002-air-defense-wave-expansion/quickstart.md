# Quickstart: 3D 防空守衛波次與 Boss 擴充

## Prerequisites and Setup

Use the existing game environment from the repository root:

```powershell
Set-Location 'C:\Users\lamun\OneDrive\Desktop\pythonSDD'
python -m pip install -r requirements-game.txt
```

No additional dependency or external model is required.

## Automated Validation

```powershell
python -m compileall air_defense tests
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected result: compilation succeeds and all deterministic rule tests pass without opening a game window.

## Launch

```powershell
python -m air_defense.main
```

## Manual Acceptance Flow

1. Start a new game. Within 30 seconds confirm the long plain, distant first aircraft, `第 1 波`, aircraft progress and three inventory slots `1 防空炮 / 2 狙擊槍 / 3 手槍`.
2. Press `1`. Confirm only the anti-air lock frame is visible. Track the aircraft through its red lock phase to stable green, then fire. Confirm the aircraft moves laterally at least twice before impact and does not teleport.
3. Repeat with a normal aircraft that produces 0–3 ground enemies, a manpower-support aircraft that produces exactly 6, and a fast aircraft that produces none. For zero enemies, confirm the next aircraft starts immediately.
4. During a ground encounter, watch at least one enemy walk from the crash site through the fixed obstacles toward the city. Confirm it moves over time, cannot pass through cover, and becomes difficult or impossible to hit when an obstacle blocks the center ray.
5. Press `2` and right-click. Confirm the sniper crosshair and visible zoom; right-click again and confirm the normal view returns. Press `3` and confirm the compact pistol reticle, short range and rapid repeat fire. A pistol shot beyond 12 units must not hit.
6. Continue until the HUD shows `第 2 波` and later waves. Confirm the first wave has 2 aircraft, aircraft count increases by one per wave, regular waves never contain an armored Boss, and progress advances one aircraft at a time.
7. Reach wave 10 with a controlled test or normal play. Confirm the wave contains an armored Boss and other aircraft. While its plane is active, confirm `裝甲飛機 HP` and require five valid anti-air hits. After the crash, confirm `大魔王 HP` and require ten valid sniper/pistol hits.
8. Allow a living ground enemy to reach the city. Confirm `城市耐久` decreases while it can still attack the player, and that zero city health stops the game with `城市被摧毀`.
9. Trigger aircraft impact, player death and city destruction separately. Confirm each failure reason appears within one second and all updates stop. Return to the menu and start again; wave, city, Boss, cooldown, enemies and reticles must reset.

## Focused Rule Cases

- Wave counts: `2, 3, 4, 5, 6, 7, 8, 9, 10`; cap milestones `6 → 8 → 10`.
- Regular roster: only `NORMAL`, `MANPOWER_SUPPORT`, `FAST`.
- Boss roster: exactly one `ARMORED_BOSS` plus non-Boss aircraft.
- Aircraft health: regular `1`, armored `5`.
- Ground health: regular `1`, ground Boss `10`.
- City health: `100`; each living city attacker applies `10` damage per second.
- Pistol: `0.20` second cooldown and `12` unit range.

## Performance Check

Measure the largest active scene—one aircraft, one Boss or six-member ground encounter, the long map and all fixed obstacles—using the in-game FPS counter. Record FPS, operating system and hardware. The target is 60 FPS; any shortfall must be recorded rather than inferred away.

## Implementation Verification Notes

- On 2026-08-27, `python -m compileall air_defense tests` succeeded and the
  deterministic suite passed 33 tests.
- The real Ursina event smoke passed `REAL_EVENT_MENU_INVENTORY_SMOKE OK` and
  `REAL_SCENE_WAVE_RETICLE_SCOPE_SMOKE OK`, covering menu start, slots `1/2/3`,
  long-map obstacle/cover creation, anti-air-only lock frame, sniper scope FOV
  reset and pistol reticle selection.
- A controlled real-window Boss smoke passed
  `REAL_BOSS_FIVE_HIT_TWO_STAGE_HUD_SMOKE OK`: five anti-air hits downed the
  armored aircraft after showing `裝甲飛機 HP: 5 / 5`, then the HUD showed
  `大魔王 HP: 10 / 10` and refreshed to `大魔王 HP: 7 / 10`.
- A controlled real-window integration loop processed waves 1–10 one aircraft
  at a time, including empty encounters and the wave-10 Boss, and reached wave
  11 without a simultaneous aircraft or encounter.
- The user completed the manual acceptance flow and reported no observed issues.
  No numeric FPS or hardware measurement was included in that report, so this
  document makes no unverified performance claim.
- The automated window environment emitted the known
  `SetForegroundWindow() failed` focus warning; it did not prevent any smoke
  assertion from passing. No FPS hardware measurement or full human playthrough
  is claimed by these automated checks.

## Known Limitations

The existing Ursina/Panda3D focus, font, cache and remote-desktop warnings documented in `specs/001-air-defense-game/quickstart.md` still apply. This feature does not add a new asset or network requirement.
