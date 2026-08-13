# Fun tweaks & easter eggs

Optional polish that makes the CRT feel more alive. Everything here is **off by default** unless noted. None of it affects library layout, playback quality, or watch progress.

For config keys and CLI flags, see [Configuration](configuration.md). Toggle most **fun tweaks** live from the [Web admin → Player settings](web-admin.md#features).

---

## Fun tweaks

Cosmetic effects you can turn on deliberately. Good for demos, nostalgia, or a kid-friendly “real TV” vibe.

### Channel snow

**Label:** fun tweak

A brief burst of fine black-and-white TV static whenever you **commit a channel number** (after the ~1.5s number-entry timeout).

| Where it runs | Behavior |
|---------------|----------|
| Show list | Jump to the show on that cable channel |
| Season list | Jump to season 1–N |
| Episode list | Jump to episode 1–N and play |

- **Not** triggered by arrow keys or Enter — number keys only.
- ~320ms animation; frames are **pre-generated and cached** when snow is enabled (smooth, consistent length everywhere).
- Optional quiet white-noise audio (defaults **on** when snow is enabled; mute with `channel_snow_audio: false`).

```json
{
  "ui": {
    "channel_snow": true,
    "channel_snow_audio": true
  }
}
```

CLI one-run override: `--channel-snow`

### Shutdown collapse

**Label:** fun tweak

Classic CRT **vertical collapse** when you quit the app (after the “Quit?” confirmation). The last frame squashes to a bright line, then black.

```json
{
  "ui": {
    "shutdown_collapse": true
  }
}
```

CLI: `--shutdown-collapse`

Independent of channel snow — you can enable either or both.

### Analog signal glitches

**Label:** fun tweak

Random brief **static flash**, **horizontal line tear**, and **vertical roll** on browse UI and Weather (not during video playback, Retro TV, or easter eggs such as test patterns / dial `000`). Rate is configurable glitches per minute.

```json
{
  "ui": {
    "analog_artifacts": true,
    "analog_artifact_rate": 12
  }
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `analog_artifacts` | `true` | Master switch |
| `analog_artifact_rate` | `12` | Glitches per minute; `0` disables timing |

CLI: `--analog-artifacts` / `--no-analog-artifacts`, and `--analog-artifact-rate N` (0–60). Passing a rate `> 0` without `--no-analog-artifacts` enables glitches for that run.

### Screensaver

**Label:** fun tweak

Greyscale **VHS logo** bounces on black (DVD-style) after menu idle time. Random multiply tint on each wall bounce. Any key dismisses. Menus only — not during playback.

See [Configuration → screensaver](configuration.md#screensaver). CLI: `--screensaver`, `--screensaver-timeout SEC`.

### Autoplay

**Label:** quality-of-life (not hidden)

When an episode finishes naturally, advance to the next one with an “Up next” countdown. **Esc** cancels during the countdown.

See [Configuration → playback](configuration.md#playback) and [Controls → During playback](controls.md#during-playback).

### Gamepad / USB controller

**Label:** input convenience (enabled by default when a pad is connected)

Same actions as the keyboard. See [Controls → Gamepad](controls.md#gamepad).

---

## Easter eggs

Hidden or discoverable extras — no config switch; they are always available when assets and context match. In-app **Help → Secrets** lists the same codes; dialing **`000`** opens an on-screen secret-channel directory.

### Secret channel directory (`000`)

**Label:** easter egg

On parent screens (browse, playback, weather, retro), press **`000`** for a full-screen listing of the special channels below. Esc / `0` backs out. Help Overview points at this page under number keys.

Pin specials on the home menu with [`home_menu`](configuration.md#home_menu) (Weather and TV Guide are on by default for parent; remove `tvguide` from `home_menu.parent` to hide the guide row).

### Secret test patterns (parent)

**Label:** easter egg

On any **parent** screen (home, shows, movies, seasons, episodes, playback), press these codes (third digit commits after a short hold with other `00x` codes):

| Press | Pattern | Asset file |
|------|---------|------------|
| `001` | SMPTE Color Bars | `src/tv_time_capsule/assets/colorbars.png` |
| `002` | Grid Test Pattern | `src/tv_time_capsule/assets/grid.png` |
| `003` | RCA Indian Head | `src/tv_time_capsule/assets/indianhead.png` |

### Weather Channel (`004`)

**Label:** easter egg

Dial **`004`** for the Weather Channel. **Default** is `weather.provider: native` (custom pygame Retro Weather, no Chromium). Live Chrome providers (`twc` / `ws4kp`) are opt-in via config or the in-app picker (**Enter / Space**); they adapt FPS/quality (`weather.screencast.mode: auto`). Configure `weather.zip` / location (default Boston). Volume keys control music/announcements (native) or the embedded player (live); Esc / back exits the menu first, then leaves Weather. Disable with `features.weather: false`. See [Native weather & cached defaults](native-cached-defaults.md).

### TV Guide (`005`)

**Label:** easter egg

Dial **`005`** (or the home-menu **TV GUIDE** row — on by default for parents) for a **TV Guide Channel** styled like the rest of the menus:

- **Bottom:** text-only channel list (taller rows, smaller titles, left-aligned numbers) that **opens mid-lineup** (as if the guide channel had been running) and **smooth-scrolls** one page at a time after a short dwell — **all shows, then all movies**, with **SHOWS** / **MOVIES** section headers when both kinds are in the lineup; subtitle shows air years / original network when known (e.g. `1988-1993 - NBC`). Leaving and returning resumes the virtual timeline from wall-clock time (nothing runs while the guide is hidden).
- **Top:** equal-time slots — five randomized show/movie previews (4:3 center-cropped thumbs), then local weather, then a **TV GUIDE CHANNEL** bumper, repeating. When a preview has a short description, the top panel expands to **half the screen**, lingers longer, and **scrolls vertically** through up to two sentences
- Descriptions/years/network come from NFO → OMDb (optional key) → Wikipedia/Wikidata and are cached on disk; disable with `"tv_guide": { "meta_enabled": false }`
- Esc from guide restores the previous browse screen (and cursor), like Weather
- Weather uses the native forecast disk cache and refreshes at most about every 30 minutes (not every frame)
- **← / →** steps the top panel; **Esc / back** exits (view-only — Enter does not tune)

Kids mode only lists allowlisted titles.

Bare `0` is **Back**; `00` opens the alphabet menu — patterns and weather use the `00x` special family only.

- Full-screen pattern display (no header, footer, or channel chrome).
- **Escape** exits the pattern or guide (does not open the quit dialog).
- Typing more digits stays on the pattern until commit or Esc.
- The app **never generates or overwrites** test-pattern PNGs — supply your own (classic broadcast test art works well).
- If a file is missing, you get a “not found” error like any invalid channel.
- Channel snow still plays when a pattern or the directory loads (if snow is enabled).

**Install note:** Packaged installs include the `assets/` folder; drop your PNGs next to `vcr_osd_mono.ttf` and `vhs.bmp` in the installed package data directory, or rebuild after adding files under `src/tv_time_capsule/assets/` in a checkout.

### MyRetroTVs decades (`1950`–`2009`)

**Label:** easter egg

Dial any **4-digit year from 1950–2009** on a parent screen (or pin `1990s` etc. under `home_menu`) to open that decade’s [MyRetroTVs](https://www.myretrotvs.com/) stream, cropped to the video only:

| Years | Stream |
|------|--------|
| 1950–1959 | 50s |
| 1960–1969 | 60s |
| 1970–1979 | 70s |
| 1980–1989 | 80s |
| 1990–1999 | 90s |
| 2000–2009 | 00s |

**Playback modes** (`retro_tv.playback_mode`; **default `cached`**):

- `cached` (**default**) — Chrome only drives the site (power on, filters, CH▼) to learn which YouTube clip is next; yt-dlp downloads a **temporary** rolling pair of files and ffmpeg plays them. Much lighter on Raspberry Pi. Temp files are wiped when you leave Decades (not the forever YouTube offline cache).
- `live` (opt-in) — Chromium CDP screencast of the site.

Volume keys adjust gain; left/right change channel (in `cached` mode both directions skip forward to the next prefetched clip). **Enter / Space** opens the Retro TV menu with **Change Channel** focused — Enter again retunes (cached: drop current clip, play the prefetched next, start caching the following; live: site CH▲). **Channel Setup** is the channel-type filter checklist. Esc backs one menu level, then exits Decades from playback. Filter choices and volume are saved under `retro_tv` in config. Requires Chrome/Chromium and, for `cached`, yt-dlp. Disable with `features.retro_tv: false`.

---

## Quick reference

| Item | Type | Config / CLI | Default |
|------|------|--------------|---------|
| Channel snow | Fun tweak | `ui.channel_snow`, `--channel-snow` | off |
| Channel snow audio | Fun tweak | `ui.channel_snow_audio` | off (follows snow when enabled) |
| Shutdown collapse | Fun tweak | `ui.shutdown_collapse`, `--shutdown-collapse` | off |
| Analog glitches | Fun tweak | `ui.analog_artifacts`, `--analog-artifacts`, `--analog-artifact-rate` | on |
| Screensaver | Fun tweak | `screensaver.enabled`, `--screensaver` | off |
| Autoplay | QoL | `playback.autoplay` | `next_in_season_only` |
| Gamepad | Input | `gamepad.enabled` | on |
| Test patterns `001` / `002` / `003` | Easter egg | *(none)* | always if PNGs exist |
| Secret directory `000` | Easter egg | *(none)* | always |
| Weather `004` | Easter egg | `weather.*`, `features.weather` | on (`native` pygame; live `twc`/`ws4kp` opt-in) |
| TV Guide `005` | Easter egg | `home_menu` token `tvguide` | always |
| MyRetroTVs `1950`–`2009` | Easter egg | `features.retro_tv`, `retro_tv.playback_mode` | on (`cached` default; `live` screencast opt-in) |

Legacy config `ui.channel_change_effects` (`off` \| `visual` \| `visual+audio`) is still read once and mapped to `channel_snow` / `channel_snow_audio` when the new keys are absent.

---

## Suggested combos

**Kid TV night:** `channel_snow: true`, `screensaver` with a long timeout, `autoplay: next_in_season_only`.

**Demo / showroom:** `channel_snow`, `analog_artifacts`, `shutdown_collapse` — enable via `--channel-snow --analog-artifacts --shutdown-collapse` for one run.

**Purist / low CPU:** leave all fun tweaks off; easter egg patterns still work when you press their number sequences.

See also [Controls](controls.md) (channel numbers, quit flow) and [Web admin](web-admin.md) (live toggles).
