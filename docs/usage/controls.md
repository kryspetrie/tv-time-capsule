# Controls

Default bindings (rebindable in-app via **Tab**):

## Menu / browsing

| Key | Action |
|-----|--------|
| ↑ / ↓ | Browse up/down |
| → / Enter | Select / Play |
| ← / Esc | Back / Stop |
| 0–9 | Type channel number (auto-commits after ~1.5s) |
| R | Reset watch status for the current show/season |
| H | Help / controls screen |
| Tab | Key configuration |
| Q | Quit |

**In-progress episodes:** if you stop mid-episode (Esc), the app bookmarks the
timestamp. That episode shows `||` and a `Resume M:SS` line; playing it again
continues from there. Finishing the episode (or stopping in the last ~10s)
clears the bookmark and marks it watched (`*`).

**Reset watch status** clears the `*` watched marks, in-progress bookmarks, and
“next up” (`>`) pointer for the current context:

- Show list → whole show  
- Season list → highlighted season  
- Episode list → current season  

## During playback

| Key | Action |
|-----|--------|
| ↑ / ↓ | Volume up / down |
| ← / → | Seek back / forward 10s |
| Space / Enter | Pause / resume |
| Esc | Stop and return to menu |

Custom key maps are stored in the watch-state file under `~/.local/share/tv-time-capsule/`.
