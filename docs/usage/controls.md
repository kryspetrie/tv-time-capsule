# Controls

Every keyboard action is remappable in-app via **F2** (key configuration). Defaults live in code; listing an action in `config.json` **replaces** that action’s defaults entirely (it does not merge). For example, `"select": ["space"]` means only Space selects — Enter no longer does. Multi-key aliases are an explicit array in config.

Defaults below; yours may differ after rebinding.

## Menu / browsing

| Key | Action |
|-----|--------|
| ↑ / ↓ | Browse up/down |
| → / Enter / Space | Select / Play |
| ← / Esc | Back |
| 0–9 (and keypad) | Type a number (auto-commits after ~1.5s) — see [Channel numbers](#channel-numbers) |
| R | Reset watch status (tap) / rescan library (hold) |
| H | Context help (page for current screen; ←/→ for other topics) |
| Tab | Toggle kid / parent mode |
| L | Alphabet jump menu (parent show/movie list) |
| K | Tag / untag current title for kids mode |
| F5 | Toggle bottom status bar (clock + help) |
| F2 | Key configuration |
| F4 | Gamepad configuration |
| F3 | Reset all key bindings (on key-setup screen only) |
| Delete | Remove last alias (on key-setup or gamepad-setup screen) |
| Z | Safe zone calibration (CRT overscan setup) |
| Q | Quit (parent mode only) |
| C | Cancel background playback cache (during streamed playback) |

### Channel numbers

Same numeric entry on every browse screen; meaning depends on where you are. Digits are committed by **exact key sequence** (leading zeros are never normal channels).

| Press | Timing | Action |
|------|--------|--------|
| `1`…`999` (no leading zero) | Timeout ~1.5s | Jump to that channel / list index and show its page |
| `0` | Timeout | **Back** one level (same as Esc); during playback, stops to the episode list |
| `01` | Short delay (~0.5s) | **Previous page** (by visible row count) |
| `02` | Short delay (~0.5s) | **Next page** |
| `00` | Timeout | Alphabet jump menu (parent show/movie only) |
| `001` / `002` / `003` | Short hold on 3rd digit | Secret test patterns (parent screens + playback) |
| Other leading-zero codes | — | Invalid |

Shows, movies, seasons, and episodes use a **paged stack**: several titles visible at once. `01`/`02` move the window by one full page (e.g. items 1–5 → 6–10). ↑/↓ still move one row.

| Screen | What 1–9 selects |
|--------|------------------|
| **Library / home** | Home-menu row (Shows, Movies, Weather, pinned decades, …) |
| **Kids catalog** | Show or movie channel |
| **Show list** | Cable-style show channel |
| **Movie list** | Movie channel |
| **Season list** | Season 1, 2, 3… |
| **Episode list** | Episode 1, 2, 3… (starts playback after static burst) |
| **During playback** | Show (or movie) cable channel — cancellable countdown, then nested list |

**Fun tweak:** with [channel snow](fun-tweaks-and-easter-eggs.md#channel-snow) enabled (default), committing a number plays a short static burst over the destination screen (not when using arrow keys).

**Easter egg:** on any parent browse screen, press `001`, `002`, or `003` for [secret test patterns](fun-tweaks-and-easter-eggs.md#secret-test-patterns-show-browser). Press the digits without long pauses — after ~1.5s a lone `00` opens the alphabet menu instead.

### Alphabet jump menu

On the **parent** show or movie list, press **`00`** (or press **L**) to open the letter menu. Only letters that exist in the list appear. ↑/↓ or ←/→ pick a letter; Enter jumps to that page. Digits **1–9** jump to fixed bands (A–C … Y–Z/#); empty bands are disabled. Press **`0`** or Esc to close.

### Kids allowlist

In **parent** mode on the show or movie list, press **K** to tag/untag the current title for kids mode (a small blue `[kids]` stays at the right of the title bar, immediately before the channel number). Kids mode only shows tagged titles; **Tab** into kids mode is blocked with **Assign kids shows first** until at least one tagged title is in the library.

### Back / quit

**Esc** (and dial `0`) moves **one level up**: episode → season or show list → home menu → **Quit?** at the top level (parent mode only). Weather / Retro / secret overlays exit first. On Retro TV, Esc closes Channel Setup → root menu → then exits Decades.

**Retro TV (Decades):** Enter opens **Change Channel** / **Channel Setup**; Enter again on Change Channel retunes. See [Fun tweaks → MyRetroTVs](fun-tweaks-and-easter-eggs.md#myretrotvs-decades-19502009).

**←** uses the same hierarchical back (without opening Quit? from mid-stack).

### Watch progress

**In-progress episodes:** if you stop mid-episode (Esc), the app bookmarks the timestamp. That episode shows a green `Resume M:SS` subtitle line; playing it again continues from there. Finishing the episode (or stopping in the last ~10s) marks it **WATCHED**.

**Next up:** the first unwatched episode in the season shows **NEXT** (green border).

**Out of order:** each finished episode is tracked individually in `state.json` (`watched: [2, 5, 7]` for local files; `watched_ids` for YouTube videos). You can watch episodes in any order.

**Reset watch status** (tap **R**) clears watched flags and in-progress bookmarks for the current context:

- Library picker → not available (no row context)  
- Show list → entire series (all seasons)  
- Movie list → highlighted movie only  
- Season list → highlighted season  
- Episode list → highlighted episode only (any episode, not just the latest)

**Rescan library** (hold **R** ~0.8s on menus): re-reads media folders without restarting. Use after copying files to USB or NAS. See [Configuration → library](configuration.md#library).

### Kid-friendly mode

Press **Tab** (or your configured `kids_mode_toggle` key) to switch between **parent mode** (normal browse) and **kids mode**:

- **Shows:** selecting a show starts playback immediately — resumes the in-progress episode in the last-watched season, or plays the next unwatched episode in that season.
- **Movies:** selecting a movie plays it directly.
- **Stop / Esc** during playback returns to the top-level browse screen (not season/episode menus).
- **Autoplay:** when an episode finishes, behavior follows `playback.autoplay` in config.
- **Simpler UI:** no status bar, no **H** help screen, no alphabet menu, and no key remapping (**F2**). Browse lists use taller rows and fewer per page.
- **No quit:** **Esc**, **Q**, and closing the window do not exit the app while kids mode is on. Switch back to **parent mode** with **Tab** first.
- **Allowlist:** only titles tagged with **K** in parent mode appear. Entering kids mode requires at least one tagged title. Press **`0`** for back; **`01`/`02`** still page.

### Status bar & help

In **parent mode**, the bottom bar shows the local time on the left and your **help** key on the right. Press **F5** (or your configured `footer_hints_toggle` key) to show or hide it; the choice is saved in `ui.footer_hints`.

Press **H** for context help: it opens on the page for the current screen (Shows, Movies, Seasons, Episodes, etc.). Use ←/→ or ↑/↓ to browse other topics; Esc closes. When a gamepad is connected, **Enter** (select) toggles between **keyboard** and **gamepad** binding labels; help defaults to whichever device you used last. Startup shows a short brand splash that points you to help.

Optional config under [Configuration → kids_mode](configuration.md#kids_mode):

- `default_enabled` — used on first launch before you have toggled mode at least once
- `enabled` — saved automatically when you toggle; restored on next start (last used parent/kids mode)
- `interleave_shows_movies` — one combined alphabetical list of shows and movies as the first screen while in kids mode (only when both libraries exist)
- `allowlist` — `{ "shows": [...], "movies": [...] }` written when you tag with **K**; required before kids mode can be entered

## During playback

| Key | Action |
|-----|--------|
| ↑ / ↓ | Volume up / down |
| ← / → | Seek back / forward 10s |
| Space / Enter | Pause / resume |
| Esc | Stop and return to the episode list (or movie list) |
| `0` (dial timeout) | Same as Esc — back to episode / movie list |
| `1`…`N` | Tune to that show/movie channel after a cancellable countdown |
| C | Cancel background cache (when progress overlay is shown) |

### Key configuration (F2)

- **↑ / ↓** — highlight an action (paginated; **← / →** changes page)
- **Enter** — set the binding (press the new key; **replaces** previous keys for that action; **back** cancels)
- **Delete** — remove the last key when an action has more than one (from a config array)
- **F3** — reset all keyboard bindings to defaults
- **back** — exit key setup

Assigning a key that is already bound elsewhere **moves** it to the new action (and clears it from the old one). Multi-key aliases are set in `config.json` as an array. Config uses readable names like `escape`, `enter`, `space`, `q` (legacy integer codes still load).

### Gamepad configuration (F4)

Open from the keyboard while a USB controller is connected.

- Same navigation keys as key setup (**↑ / ↓**, **← / →** pages, **Enter**, **Delete**, **F3**, **back**)
- **Enter** — wait for a live gamepad input (button, D-pad, or stick direction)
- Saved to `gamepad.bindings` in config as tokens like `button-0`, `hat-up`, `stick-left`

**Autoplay:** when enabled in config, finishing an episode naturally advances to the next one (within the season, or into the next season when `autoplay` is `next_episode`). A brief “Up next” countdown appears; press **back** to cancel and return to the episode list. Autoplay skips the pre-play episode summary splash (manual select still shows it). See [Configuration → playback](configuration.md#playback).

Custom key maps are stored in the active `config.json` under the `keymap` key using **readable key names** (e.g. `escape`, `enter`, `space`). Gamepad maps live under `gamepad.bindings`. An empty object uses defaults. See [Configuration → keymap](configuration.md#keymap) and [gamepad](configuration.md#gamepad).

## Gamepad

USB controllers use the same logical actions as the keyboard. Defaults: D-pad / left stick to move; **button-0** (A) or **button-7** (Start) to select; **button-1** (B) or **button-6** (Back) to go back. Remap live with **F4**. Disable with `"gamepad": { "enabled": false }` in config.

## Screensaver

Enabled by default in config (30s idle). A bouncing VHS logo appears inside the title-safe UI area while browsing menus. **Any key** dismisses it and returns to the menu. See [Configuration → screensaver](configuration.md#screensaver) and [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md#screensaver).

## Fun tweaks & easter eggs

CRT polish (snow on channel change, analog glitches, shutdown animation) and hidden test patterns (`001` / `002` / `003` on the show list) are **on by default** in config; disable in config or the [web admin](web-admin.md). Full guide: [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md).
