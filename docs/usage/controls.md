# Controls

Default bindings (rebindable in-app via **Tab**):

## Menu / browsing

| Key | Action |
|-----|--------|
| ↑ / ↓ | Browse up/down |
| → / Enter | Select / Play |
| ← / Esc | Back / Stop |
| 0–9 | Type a number (auto-commits after ~1.5s) — see [Channel numbers](#channel-numbers) |
| R | Reset watch status (tap) / rescan library (hold) |
| H | Help / controls screen |
| Tab | Key configuration |
| Z | Safe zone calibration (CRT overscan setup) |
| Q | Quit (from anywhere) |

### Channel numbers

Same numeric entry on every browse screen; meaning depends on where you are:

| Screen | What 1–9 selects |
|--------|------------------|
| **Show list** | Cable-style show channel (from [Configuration → channels](configuration.md#channels)) |
| **Season list** | Season 1, 2, 3… for the current show |
| **Episode list** | Episode 1, 2, 3… for the current season (starts playback) |

Digits build in the corner until the timeout commits. Invalid numbers show a brief error.

**Fun tweak:** with [channel snow](fun-tweaks-and-easter-eggs.md#channel-snow) enabled, committing a number plays a short static burst (not when using arrow keys).

**Easter egg:** on the show list only, dial `0`, `00`, or `000` for [secret test patterns](fun-tweaks-and-easter-eggs.md#secret-test-patterns-show-browser).

### Quit confirmation

On the show list, **Esc** opens a **Quit?** dialog (not an instant exit). **← / →** choose Yes or No; **Enter** confirms. Left = Yes, Right = No.

**In-progress episodes:** if you stop mid-episode (Esc), the app bookmarks the
timestamp. That episode shows `||` and a `Resume M:SS` line; playing it again
continues from there. Finishing the episode (or stopping in the last ~10s)
clears the bookmark and marks it watched (`*`).

**Reset watch status** (tap **R**) clears the `*` watched marks, in-progress bookmarks, and
“next up” (`>`) pointer for the current context:

- Show list → entire series (all seasons)  
- Season list → highlighted season  
- Episode list → highlighted episode only  

**Rescan library** (hold **R** ~0.8s on menus): re-reads media folders without restarting. Use after copying files to USB or NAS. See [Configuration → library](configuration.md#library).

## During playback

| Key | Action |
|-----|--------|
| ↑ / ↓ | Volume up / down |
| ← / → | Seek back / forward 10s |
| Space / Enter | Pause / resume |
| Esc | Stop and return to menu |

**Autoplay:** when enabled in config, finishing an episode naturally advances to the next one (within the season, or into the next season when `autoplay` is `next_episode`). A brief “Up next” countdown appears; press **Esc** to cancel and return to the episode list. See [Configuration → playback](configuration.md#playback).

Custom key maps are stored in the active `config.json` under the `keymap` key (pygame key codes). An empty `keymap` object uses the defaults above. See [Configuration](configuration.md#where-the-app-looks-for-configjson).

## Gamepad

USB controllers use the same actions as the keyboard (see table above). D-pad or left stick to move; **A** or **Start** to select; **B** or **Back** to go back. Disable with `"gamepad": { "enabled": false }` in config.

## Screensaver

When enabled in config (or via `--screensaver`), a bouncing VHS logo appears after the configured idle timeout while browsing menus. **Any key** dismisses it and returns to the menu. See [Configuration → screensaver](configuration.md#screensaver) and [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md#screensaver).

## Fun tweaks & easter eggs

Optional CRT polish (snow on channel change, scanlines, analog glitches, shutdown animation) and hidden test patterns (`0` / `00` / `000` on the show list). Full guide: [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md).
