# Controls

Default bindings (rebindable in-app via **Tab**):

## Menu / browsing

| Key | Action |
|-----|--------|
| ↑ / ↓ | Browse up/down |
| → / Enter | Select / Play |
| ← / Esc | Back / Stop |
| 0–9 | Type channel number (auto-commits after ~1.5s) |
| R | Reset watch status (tap) / rescan library (hold) |
| H | Help / controls screen |
| Tab | Key configuration |
| Q | Quit |

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

When enabled in config (or via `--screensaver`), a bouncing VHS logo appears after the configured idle timeout while browsing menus. **Any key** dismisses it and returns to the menu. See [Configuration → screensaver](configuration.md#screensaver).
