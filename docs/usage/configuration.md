# Configuration

## Where the app looks for `config.json`

The app loads the **first existing file** in this order:

| Priority | Path | When it applies |
|----------|------|-----------------|
| 1 | `$TV_TIME_CAPSULE_CONFIG` | Explicit override (any install) |
| 2 | `<repo>/config.json` | Development — Poetry checkout, `pip install -e .`, or `PYTHONPATH=src` |
| 3 | `~/.config/tv-time-capsule/config.json` | Installed app (pipx, system package, non-checkout run) |

`$XDG_CONFIG_HOME` replaces `~/.config` when set.

**Development:** you can copy the example into the repo root, or skip that step — if no config file exists anywhere in the search order, the app creates one automatically on first launch (`./config.json` in a checkout).

```bash
cp config.example.json config.json   # optional — richer defaults and comments
poetry run tv-time-capsule --windowed --media-dir ./media
```

**Development defaults:** `--windowed` uses **0%** safe zone (full 640×480 UI in the window). Fullscreen / kiosk uses the config default (**10%** on all sides unless you change it). Screensaver, admin, channel snow, analog artifacts, and shutdown collapse are **on** in the default config — no extra CLI flags needed for local dev.

Key rebinding and in-app saves write back to whichever file was loaded.

**Installed (pipx):** the app creates `~/.config/tv-time-capsule/config.json` on first run if missing. To start from the annotated example instead:

```bash
mkdir -p ~/.config/tv-time-capsule
cp config.example.json ~/.config/tv-time-capsule/config.json
```

Credentials and temporary mount password files always live under `~/.config/tv-time-capsule/` even when the main config is `./config.json` in a dev checkout.

## Other files

| File | Purpose |
|------|---------|
| Active `config.json` (see table above) | Media paths, remote mounts, key bindings |
| `~/.local/share/tv-time-capsule/state.json` | Per-episode watch flags, in-progress bookmarks |
| `~/.local/share/tv-time-capsule/youtube/` | YouTube catalog cache (~24h) and per-video pillarbox crop cache (~30d) |
| First writable `media_paths` entry (else `~/.local/share/tv-time-capsule/youtube-offline/`) | Forever yt-dlp offline episode tree when `youtube.cache.enabled` and `cache.directory` is unset |
| `~/.local/share/tv-time-capsule/admin.pid` | Previous admin server PID (used to free the port on restart) |
| `~/.config/tv-time-capsule/` | Credentials files, temp CIFS creds, secrets helpers |

**Full annotated example** (all settings, mount types, key codes): [`config.example.json`](../../config.example.json) in the repo root.

On first run with **no config file anywhere in the search path**, `load_config()` writes a minimal default to the appropriate location (`$TV_TIME_CAPSULE_CONFIG` when set, else `./config.json` in a checkout, else `~/.config/tv-time-capsule/config.json`):

```json
{
  "media_paths": ["/media/usb"],
  "mounts": [],
  "keymap": {}
}
```

## `media_paths`

List of directories to scan for shows. Paths may use `~` and environment variables.

```json
{
  "media_paths": [
    "/media/usb",
    "/mnt/tv/nas-kids",
    "~/Videos/kids"
  ]
}
```

CLI `--media-dir` (repeatable) **overrides** `media_paths` for that invocation only. Mounts still run unless `--skip-mounts` is set.

## `mounts`

Optional remote filesystems mounted before discovery. See [Remote mounts](remote-mounts.md).

Mountpoints from `mounts` are also scanned even if they are not listed in `media_paths`.

## `keymap`

Optional custom key bindings. Each action accepts a **readable key name** or an **array of names** for aliases. Listing an action **replaces** its defaults completely (no merge). Omitted actions keep the defaults in [Controls](controls.md). Rebinding in-app (**F2**) writes here and also replaces that action’s bindings with the single captured key.

```json
{
  "keymap": {
    "select": ["space"],
    "quit": ["q", "escape"]
  }
}
```

In this example only Space selects (Enter and keypad Enter do nothing for select). Quit accepts both `q` and `escape` because both are listed. Unlisted actions (up, back, digits, …) still use code defaults.

Common names: `up`, `down`, `left`, `right`, `enter`, `kp-enter`, `escape`, `esc`, `space`, `tab`, `delete`, `f1`–`f12`, `a`–`z`, `0`–`9`, `num-0`–`num-9`. `enter` is the main Return key; `kp-enter` is the physically separate numeric-keypad Enter key. Both remain distinct in config so either key works, while in-app help combines them into one `enter` label. Legacy integer pygame key codes still load.

The in-app key-setup screen is paginated (**← / →**). **F3** on that screen resets to defaults (empty object). **Delete** removes the last key when more than one is bound.

## Full example

See [`config.example.json`](../../config.example.json) in the repo root for every field, all mount types, and default key codes. Minimal production example:

```json
{
  "media_paths": ["/media/usb", "/mnt/tv/nas-kids"],
  "mounts": [
    {
      "type": "cifs",
      "source": "//nas.local/KidsShows",
      "mountpoint": "/mnt/tv/nas-kids",
      "username": "media",
      "keyring": "nas-kids",
      "options": ["uid=1000", "gid=1000", "vers=3.0"]
    }
  ],
  "keymap": {}
}
```

## `screensaver`

**Fun tweak** — optional idle screensaver: a greyscale VHS logo (`assets/vhs.bmp`) bounces on a black screen like a DVD screensaver. The logo is drawn at **2×** its source size with **nearest-neighbor scaling** (crisp, pixelated edges). On each edge bounce it picks a new random **multiply** tint color. **Any key** returns to the menu. Applies while browsing menus only (not during video playback, key configuration, or exit confirm).

See also [Fun tweaks & easter eggs → Screensaver](fun-tweaks-and-easter-eggs.md#screensaver).

The bundled asset is a 32-bit BMP so pygame can load it even when extended image formats (PNG/GIF) are unavailable.

```json
{
  "screensaver": {
    "enabled": true,
    "timeout_seconds": 300
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Turn screensaver on |
| `timeout_seconds` | `30` | Menu inactivity before start (minimum 10) |

CLI overrides for one run: `--screensaver` / `--no-screensaver` and `--screensaver-timeout SEC`.

## `playback`

Controls automatic advance to the next episode when one finishes naturally (Esc still stops immediately).

```json
{
  "playback": {
    "autoplay": "next_in_season_only",
    "autoplay_countdown_seconds": 5,
    "now_playing_splash": true,
    "now_playing_splash_seconds": 1.5
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `autoplay` | `next_in_season_only` | `off`, `next_episode` (includes next season), or `next_in_season_only` |
| `autoplay_countdown_seconds` | `5` | “Up next” wait before starting (0 = instant). **Esc** cancels during countdown |
| `now_playing_splash` | `true` | Episode summary (show, season/episode, title) before playback starts |
| `now_playing_splash_seconds` | `1.5` | How long the summary stays visible (0 = skip). Skipped after autoplay “Up next” — only manual episode select shows it |
| `hw_decode` | `auto` | Pi hardware H.264 decode: `auto`, `on`, or `off` |

## `cache`

Background local copy of episodes read from remote mounts (NFS, SMB, SSHFS, etc.) for smoother playback. See [Remote mounts → Playback cache](remote-mounts.md#playback-cache).

```json
{
  "cache": {
    "enabled": true,
    "directory": null,
    "max_bytes": 2147483648,
    "prefetch_next": true,
    "cache_before_playing": false
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Copy remote episodes to disk while playing |
| `directory` | `~/.local/share/tv-time-capsule/playback-cache` | Cache folder (`null` = default) |
| `max_bytes` | `2147483648` (2 GiB) | LRU size cap; oldest cached files are removed when full |
| `prefetch_next` | `true` | Cache the next autoplay episode during the up-next countdown |
| `cache_before_playing` | `false` | Wait on the title screen with a progress bar until caching finishes before playback starts. **Enter** plays from the stream immediately; **Esc** cancels |

While streaming with background caching, pause to see cache progress; press **C** to cancel the cache copy.

## `ui`

CRT-style **fun tweaks** when tuning channels or quitting. See [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md) for behavior details and suggested combos.

```json
{
  "ui": {
    "channel_snow": false,
    "shutdown_collapse": false,
    "channel_snow_audio": false,
    "analog_artifacts": false,
    "analog_artifact_rate": 12,
    "marquee_scroll": "always"
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `channel_snow` | `true` | **Fun tweak** — B&W static burst when committing a channel number (show, season, or episode list). Not arrow keys. |
| `shutdown_collapse` | `true` | **Fun tweak** — CRT vertical collapse animation on quit |
| `channel_snow_audio` | `true` | Quiet white-noise with channel snow (defaults **on** when `channel_snow` is enabled; set `false` to mute) |
| `analog_artifacts` | `true` | **Fun tweak** — Random brief static, line tear, and vertical roll on the **show browser** |
| `analog_artifact_rate` | `12` | Glitches per minute when `analog_artifacts` is on (`0` = no timed glitches) |
| `footer_hints` | `true` | Bottom status bar (clock + help key) on browse screens in **parent mode** (toggle in-app with **F5**; always hidden in kids mode) |
| `marquee_scroll` | `"always"` | How overflowing list/header titles scroll: `"always"` (every visible row) or `"selected"` (only the highlighted row) |
| `safe_zone` | `10` on all sides | CRT overscan inset — see [Safe zone](#safe-zone) |

CLI overrides: `--channel-snow` / `--no-channel-snow`, `--shutdown-collapse` / `--no-shutdown-collapse`, `--analog-artifacts` / `--no-analog-artifacts`, `--analog-artifact-rate N`, `--safe-zone PCT`, `--safe-zone-offset X,Y`. Omit a flag to use config. In **`--windowed`** mode the safe zone defaults to **0%** unless you pass `--safe-zone` explicitly (handy for dev on a monitor).

### Safe zone

Analog TVs often **overscan** the picture: the outer ~5–10% of the frame is clipped. Title-safe / action-safe margins keep important UI away from those edges.

When any `safe_zone` margin is greater than zero:

- The **logical framebuffer grows** with margin % (e.g. 5% → 704×528), but the **OS window** is separate: **800×600** by default in windowed mode (`--windowed`), or an integer multiple of 640×480 with `--scale N` (`2`–`6`), resizable with a locked **4:3** aspect ratio.
- SDL GPU-scales the logical frame into that window (letterboxed as needed).
- **Menus, splashes, overlays, and screensaver** always render at native **640×480** (no interpolation) and are composited into the padded frame; border pixels use the **same background color** as that screen.
- **Video** is **full-bleed on the whole window** during playback (including margin areas). The window does not resize when you start an episode.
- **Playback HUD** (progress, volume, pause, Up Next) still respects safe-zone inset so controls stay title-safe on CRTs.
- **Secret test patterns** (`001` / `002` / `003`) fill the **entire extended framebuffer**.
- **Screensaver** bounces inside the same title-safe UI inset as menus.

Percentages are of the **UI viewport** — width for left/right padding, height for top/bottom. Maximum 25% per edge.

```json
{
  "ui": {
    "safe_zone": 5
  }
}
```

Uniform 5% on all sides. Per-edge control:

```json
{
  "ui": {
    "safe_zone": {
      "top": 5,
      "bottom": 8,
      "left": 5,
      "right": 5
    }
  }
}
```

Shorthand keys: `margin` or `percent` (uniform), `vertical`, `horizontal`.

**Offset** — shift the 640×480 UI block within the extended frame when overscan is not symmetric. Pixel values; positive `offset_x` moves right, positive `offset_y` moves down.

```json
{
  "ui": {
    "safe_zone": {
      "top": 5,
      "bottom": 5,
      "left": 5,
      "right": 5,
      "offset_x": 0,
      "offset_y": 12
    }
  }
}
```

CLI one-run override: `--safe-zone 5` (uniform percent), `--safe-zone-offset 0,12` (pixels).

### In-app calibration

Press **Z** from any browse screen to open the safe zone setup view:

- Full-frame black background with a **white rectangle** and diagonal guides showing where menus will draw.
- **Enter** toggles **ZOOM** (margin size) vs **POSITION** (pixel offset within the frame).
- **Arrow keys** adjust the active mode (zoom: vertical/horizontal margins; position: move the inset).
- **Esc** opens a **Save changes?** prompt (Yes / No). Esc again cancels the prompt and returns to editing.

Values are written to `ui.safe_zone` in your config file when you choose Yes.

Typical CRT starting point: **5%** all sides, or **8% bottom** (where many sets clip hardest).

### Easter egg: secret test patterns

On any **parent** browse screen, press `001`, `002`, or `003` to display full-screen test patterns from your own PNGs in `src/tv_time_capsule/assets/` (`colorbars.png`, `grid.png`, `indianhead.png`). The app never generates these files. **Esc** exits. Full details: [Fun tweaks & easter eggs → Secret test patterns](fun-tweaks-and-easter-eggs.md#secret-test-patterns-show-browser).

Legacy `channel_change_effects` (`off` \| `visual` \| `visual+audio`) is still read once and mapped to `channel_snow` / `channel_snow_audio` if the new keys are absent.

## `gamepad`

USB game controllers (SDL mapping). Enabled by default when a controller is connected. Remap live in-app with **F4** (gamepad configuration) — press a button, D-pad direction, or stick while capturing.

```json
{
  "gamepad": {
    "enabled": true,
    "bindings": {
      "select": ["button-0", "button-7"],
      "back": ["button-1", "button-6"],
      "up": ["hat-up", "stick-up"],
      "down": ["hat-down", "stick-down"],
      "left": ["hat-left", "stick-left"],
      "right": ["hat-right", "stick-right"]
    }
  }
}
```

| Token | Meaning |
|-------|---------|
| `button-N` | Face or menu button index (SDL numbering) |
| `hat-up` / `hat-down` / `hat-left` / `hat-right` | D-pad |
| `stick-up` / `stick-down` / `stick-left` / `stick-right` | Left analog stick |

Each action accepts one token or an array of aliases. **F3** on the gamepad setup screen resets to defaults; **Delete** removes the last alias.

See [Controls → Gamepad](controls.md#gamepad).

## `channels`

Customize show browse order and cable-style channel numbers on the **show list**.

```json
{
  "channels": {
    "order": ["Bluey", "Mister Rogers", "Movies"],
    "numbers": { "Bluey": 1, "Movies": 9 }
  }
}
```

| Field | Description |
|-------|-------------|
| `order` | Show folder names in priority order. Unknown names are skipped. |
| `numbers` | Optional fixed channel numbers. Other shows use their 1-based position in the ordered lineup. |

Typing a channel number on the show list jumps to the matching show (gaps are allowed — e.g. channel 9 without a channel 8). On the **season** and **episode** lists, numbers select season or episode index instead. See [Controls → Channel numbers](controls.md#channel-numbers).

With [channel snow](fun-tweaks-and-easter-eggs.md#channel-snow) enabled, committing a number plays a static burst on every browse screen.

## `kids_mode`

Simplified browsing for young viewers. Toggle at runtime with **Tab** (default `kids_mode_toggle` key); switch back to parent mode with the same key.

```json
{
  "kids_mode": {
    "default_enabled": false,
    "interleave_shows_movies": false,
    "enabled": false,
    "allowlist": null
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `default_enabled` | `false` | Used on first launch when `enabled` has never been saved |
| `enabled` | *(from `default_enabled`)* | **Persisted** last parent/kids mode — written when you toggle at runtime; restored on next start |
| `interleave_shows_movies` | `false` | In kids mode, show one combined alphabetical list of shows and movies instead of separate library screens |
| `allowlist` | *(absent / `null`)* | Tagged titles for kids mode (`shows` / `movies`). Parent **K** creates and updates it. Kids mode cannot be entered until at least one tagged title is in the library |

Kid mode auto-plays when a show is selected (resume or next-up in the last-watched season). Autoplay after an episode ends follows `playback.autoplay`. Quit (**Esc**, **Q**, window close) is disabled until you toggle back to parent mode. See [Controls → Kid-friendly mode](controls.md#kid-friendly-mode).

## `home_menu`

Top-level **LIBRARY** picker rows for parent vs kids. Pin Weather, decades, or other specials next to Shows / Movies.

```json
{
  "home_menu": {
    "parent": ["shows", "movies", "weather"],
    "kids": ["shows", "movies", "weather"]
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `parent` | `["shows", "movies", "weather"]` | Adult home-menu tokens (order = on-screen order) |
| `kids` | `["shows", "movies", "weather"]` | Kids home-menu tokens |

**Tokens:** `shows`, `movies`, `weather`, `1950s`…`2000s`, `directory` (`000`), `001` / `002` / `003` (test patterns). Unknown tokens are skipped. Rows for disabled features (`features.weather` / `features.retro_tv`) are omitted. Empty show/movie libraries are omitted when that library type is not present.

Kids can open pinned specials from the menu; digit easter-egg codes remain parent-only. See [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md).

## `network`

LAN hostname for mDNS (`vintage-tv.local`). **Set automatically** by `./install.sh` and `./install-pi.sh` (see `--hostname`).

```json
{
  "network": {
    "mdns_hostname": "vintage-tv",
    "admin_port": 8765
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `mdns_hostname` | `vintage-tv` | Short name registered on the LAN (browse as `<name>.local`) |
| `admin_port` | `8765` | Web admin port; install also publishes `_http._tcp` via Avahi |

Re-apply after editing: `sudo ./scripts/ensure-mdns-hostname.sh --hostname <name>`

## `library`

Hot-rescan without restarting the app.

```json
{
  "library": {
    "rescan_interval_seconds": 1800,
    "rescan_long_press_ms": 800
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `rescan_interval_seconds` | `0` | Rescan while idle on the show list (`0` = off) |
| `rescan_long_press_ms` | `800` | Hold **R** (reset key) to rescan; tap **R** still resets watch status |

CLI one-shot scan (mounts + discovery, no UI): `tv-time-capsule --rescan-only`

## `admin`

Local web UI for channel order, library rescan, logs, and watch summary. See [Web admin](web-admin.md).

```json
{
  "admin": {
    "enabled": true,
    "port": 8765,
    "bind": "0.0.0.0"
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Start HTTP admin on app launch |
| `port` | `8765` | TCP port |
| `bind` | `0.0.0.0` | Listen address (`127.0.0.1` = local only; `--windowed` forces loopback) |

No authentication — only enable on a home LAN you trust.

## Watch state (`state.json`)

Progress is stored per show under `~/.local/share/tv-time-capsule/state.json`:

```json
{
  "Bluey": {
    "s01": {
      "watched": [1, 3, 5],
      "pos_ep": 2,
      "pos": 45.0
    }
  },
  "Ghostwriter": {
    "s01": {
      "watched_ids": ["dQw4w9WgXcQ"],
      "pos_id": "xxxxxxxxxxx",
      "pos_ep": 3,
      "pos": 120.0
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `watched` | Local episode numbers finished (any order — out-of-order viewing is supported) |
| `watched_ids` | YouTube video ids finished (stable across playlist reorders) |
| `pos_ep` / `pos` | In-progress bookmark for local media (seconds into `pos_ep`) |
| `pos_id` / `pos` | In-progress bookmark for YouTube (`pos_ep` is also kept as a convenience) |

YouTube completion and resume are keyed by video id so reshuffling a playlist does not mark the wrong episode or lose a bookmark. Legacy seasons that only stored YouTube progress as episode numbers still count as watched when those numbers match the current catalog; the next finish/reset migrates to `watched_ids`.

Legacy seasons with a single `ep` field (highest completed in order) migrate to `watched` automatically on the next save.

Episode list labels: **NEXT** (first unwatched), **RESUME** (bookmark), **WATCHED** (completed). Season list shows `21 eps` and `E-05 next` when applicable. Tap **R** on an episode to clear its watched flag and bookmark; hold **R** to rescan the library.

> **Defaults:** the app ships **native Weather**, **YouTube `prefer_cache` + offline fills**, and **Decades `cached`**. Live Chrome modes stay fully supported — see [Native weather & cached defaults](native-cached-defaults.md).

## `retro_tv`

Preferences for MyRetroTVs decade streams (dial years **1950–2009**). Updated automatically when you change channel types or volume in-app.

```json
{
  "retro_tv": {
    "playback_mode": "cached",
    "cache_directory": null,
    "filters": {
      "box_c": true,
      "box_s": true,
      "box_a": false,
      "box_d": true,
      "box_g": true,
      "box_k": true,
      "box_e": true,
      "box_m": true,
      "box_n": true,
      "box_o": true,
      "box_z": false,
      "box_p": true,
      "box_r": true,
      "box_t": true,
      "box_f": true
    },
    "volume": 80
  }
}
```

| Field | Default | Meaning |
|-------|---------|---------|
| `playback_mode` | **`cached`** | `cached` = site as playlist oracle + rolling yt-dlp pair + ffmpeg (**default**). `live` = full Chrome CDP screencast (opt-in). |
| `cache_directory` | `null` | Temp tree root for `cached` mode (`null` → `~/.local/share/tv-time-capsule/retro-tv-cache/`). Wiped per decade when you leave Decades — never the forever YouTube offline cache. |
| `filters` | `null` | Map of checkbox ids (`box_c` = Cartoons, `box_s` = Comedy, …) to on/off. `null` leaves the site default (all on) until you change them. Shared across all decades. |
| `volume` | `null` | Last media gain 0–100. `null` starts at 100. |

See [Native weather & cached defaults](native-cached-defaults.md) and [Fun tweaks → MyRetroTVs](fun-tweaks-and-easter-eggs.md#myretrotvs-decades-19502009).

## `youtube_title_rules`

Global regex rewrites for scraped YouTube **playlist** and **episode** titles (after OSD-safe character cleanup). Config `title` overrides are not rewritten. Omit the key to use the built-in kids/classic defaults; set `"youtube_title_rules": []` (or `{ "deletions": [], "substitutions": [] }`) to disable.

Patterns are full Python regexes (`re.sub`). Use inline flags such as `(?i)` for case-insensitive.

**Preferred shape** — deletions (remove matches) + substitutions (find/replace pairs):

```json
{
  "youtube_title_rules": {
    "deletions": [
      "(?i)\\s*\\|\\s*Scholastic Classic\\s*$",
      { "pattern": "(?i)\\s*\\|\\s*Full Episodes?\\b", "scope": "episode" }
    ],
    "substitutions": [
      ["(?i)\\b(\\d+)\\s*x\\s*(\\d+)\\b", "\\1x\\2"]
    ]
  }
}
```

| Field | Meaning |
|-------|---------|
| `deletions` | List of patterns to remove (string, or `{pattern, scope?}`) |
| `substitutions` | List of `[pattern, replace]` pairs, or `{pattern, replace, scope?}` |
| `rules` | Optional extra full rule list (same as the legacy array form) |
| `scope` | `all` (default), `episode`, or `playlist` |

**Legacy array form** is still supported: objects `{pattern, replace, scope?}`, bare deletion strings, or `[pattern, replace]` pairs.

Built-in defaults strip brand pipes (`\| Scholastic Classic`, `\| PBS KIDS`, …), `Full Episode(s)`, leading season/episode wrappers (`Season 3, Episode 2b, …`, `Show FULL EPISODE | …`, `S01E02 …`), trailing `| Season N`, rip tags (`ItunesRip`), runtime suffixes (`\| 90 Minutes!`), quality tags on playlists (`- 480p`, `4K UPSCALE`), and similar noise.

Episode titles that embed codes such as `S01E02`, `1x02`, `Season 7 Episode 22` (including Arthur-style `2b` / `5A` suffixes), or a leading `1 - ` / `2 - ` have those markers removed from the display name, and the episode list number is taken from the code (playlist order fills any gaps). `Part 1` / `Pt. 1` style markers are shortened to `P1`; composites like `Pt 1&2` / `Part 1 & 2` become `P1/P2`. Compilation uploads that duplicate already-present separated episodes (e.g. `My Name Is Jake P1/P2 | Underground` when P1, P2, and Underground exist) are dropped.

Per-channel rules (below) run **after** these globals. Prefer globals for patterns that repeat across shows; keep `title_deletions` / `title_substitutions` for brand-specific marketing lines only. `strip_title_prefix` strips a leading `Title -` / `Title |` / `Title :` when `title` is set.

## `features`

Master switches. When false, the feature is removed from dials/help and Chrome is never started for it.

```json
{
  "features": {
    "weather": true,
    "retro_tv": true,
    "youtube": true
  }
}
```

| Field | Default | Meaning |
|-------|---------|---------|
| `weather` | `true` | Dial `004` Weather Channel |
| `retro_tv` | `true` | MyRetroTVs decade dials (`1950`–`2009`) |
| `youtube` | `true` | YouTube virtual shows + catalog scrape |

## `youtube_channels`

List YouTube channels (or a specific playlist URL) as virtual shows on the normal browse list. Catalog is scraped via headless Chrome (no API key) and cached under `~/.local/share/tv-time-capsule/youtube/` (about 24 hours). Per-video pillarbox crop decisions from playback are cached under `youtube/crops/` for 30 days so replaying an episode skips the load-time crop probe. Press **T** during playback to toggle zoom on/off for that episode (persisted in the crop cache). Long-press **R** / admin rescan refreshes the catalog cache. **Default playback** uses a forever yt-dlp file when present (`prefer_cache`), and falls back to Chrome live on a miss. Force Chrome always with `playback_mode: live`.

### `youtube` (playback mode + forever offline cache)

Dual-backend settings (file cache + live Chrome). Distinct from the remote-mount **`cache`** block (NFS/SMB copy). Defaults are documented in [Native weather & cached defaults](native-cached-defaults.md).

```json
{
  "youtube": {
    "playback_mode": "prefer_cache",
    "cache": {
      "enabled": true,
      "directory": null,
      "max_bytes": null,
      "download_when_idle": true,
      "idle_seconds": 30,
      "idle_gap_seconds": 60,
      "rate_limit_cooldown_seconds": 1800,
      "exclude_unavailable": false,
      "format": "bv*[height<=480]+ba/b[height<=480]/bv*[height<=360]+ba/b[height<=360]/bv*[height<=720]+ba/b[height<=720]/b"
    }
  }
}
```

| Field | Default | Meaning |
|-------|---------|---------|
| `playback_mode` | **`prefer_cache`** | File when present, else **live Chrome**. `live` always uses Chrome; `cached_only` blocks uncached episodes (Pi 1 / Zero) |
| `cache.enabled` | **`true`** | Download configured channels into a forever tree via yt-dlp. Set `false` to disable fills (live fallback still works under `prefer_cache`) |
| `cache.directory` | first writable `media_paths` entry | Offline tree root (null → first writable media path, usually `/media/usb`; falls back to `~/.local/share/tv-time-capsule/youtube-offline` if media is missing/unwritable). Layout matches the local library: `Show/s01/S01E01 - Title [id].mp4`. Override to a NAS path to fill once and play everywhere |
| `cache.max_bytes` | `null` | Soft cap; `null` never deletes completed files. When set, new downloads are skipped once over budget |
| `cache.download_when_idle` | `true` | Background downloads while browsing/menus/screensaver (paused during PLAYING / Weather / Retro). Priority cache-now (Y / Enter on miss) still runs immediately unless rate-limited |
| `cache.idle_seconds` | `30` | Seconds without UI input before background fills start (screensaver uses its own timeout; cache progress does not count as activity) |
| `cache.idle_gap_seconds` | `60` | Seconds to wait between background idle batches (does not apply to priority Y/Enter) |
| `cache.rate_limit_cooldown_seconds` | `1800` | After a bot / HTTP 429 style block, pause **all** cache downloads for this long (escalates on repeat hits, capped at 6h). Queued priority jobs resume when the cooldown ends |
| `cache.exclude_unavailable` | `false` | Hide YouTube episodes marked **UNAVAILABLE** from browse lists and episode counts (alias `excludeUnavailable`). Leave false if you want to retry them with **Y** |
| `cache.format` | **≤480p preferred** | yt-dlp format string. Default biases to the 640×480 canvas: best ≤480, then ≤360, then ≤720 — smallest practical file at SD quality |
| `cache.layout` | `season_folders` | `season_folders` → `Show/sNN/SxxExx - Title [id].mp4`; `flat` → `Show/SxxExx - Title [id].mp4` (no season subfolder) |
| `cache.batch_size` | `1` | Concurrent yt-dlp downloads (clamped 1–8). Raise to 2–4 when a single connection is throttled |

**Priority cache-now:** press **Y** to queue (show → bulk ``rest``; season/episode → end of that show's boost lane, still ahead of bulk fill). **Y** also clears an **UNAVAILABLE** skip for the selected episode/season/show so a failed id can be retried; idle fills still skip those until cleared. Play (**Enter**) on an uncached episode in `cached_only` jumps that title to the **front** of the line and auto-plays it when caching finishes — unless you **Enter** another episode first (that becomes the new pending target). **Y** alone does not set pending autoplay. Background idle fills pause while any priority job remains. Episode subtitles show **CACHING...** / **NOT CACHED**. yt-dlp uses web/tv player clients. Permanent removals / private / members-only / unavailable live recordings are marked **UNAVAILABLE**. Bot / rate-limit errors pause further requests until cooldown.

**CLI:** `tv-time-capsule --youtube-cache-sync` fills missing episodes headlessly (requires `cache.enabled` and `yt-dlp`; Poetry installs yt-dlp on Python ≥3.10). Episode rows show **CACHED** / **CACHING...** / **NOT CACHED** when the offline cache is enabled. With `cached_only`, play attempts on misses show a **CACHING...** snackbar when queued (or **NOT CACHED** / unavailable). File and live backends share the pillarbox crop cache; press **T** to toggle zoom on either path.

See also [Pi offline YouTube plan](../development/pi-features-offline-youtube-plan.md).

Weather lives under `weather`: **`provider` defaults to `native`** (custom pygame Retro Weather). Also `auto` (→ native), `twc`, `ws4kp`. Location fields, optional `ws4kp_base_url`, `music`, `native` (`page_seconds`, `alert_style` = `marquee`|`page`), `maps` (Radar page), and screencast knobs for **live** providers only. While watching Weather, **Enter / Space** opens an in-app provider picker that writes `weather.provider` and restarts the channel — choose `twc` / `ws4kp` to enable live Chrome. Native music + RetroCast announcements are fetched on install via `scripts/fetch-weather-music.sh`; override with `weather.music.directory` / `weather.music.announcements_directory`. Full guide: [Native weather & cached defaults](native-cached-defaults.md).

**Native Radar page** (`weather.maps`): free [NWS RIDGE regional loops](https://radar.weather.gov/) such as `radar.weather.gov/ridge/standard/NORTHEAST_loop.gif` — **no API key**. The mosaic sector is chosen from your lat/lon (nearest region; override with `maps.region`, e.g. `NORTHEAST`, `CENTGRLAKES`, `CONUS`). The loop is prefetched while the Current page is on screen, then animated on Radar. If a stale on-disk loop is shown, the lower-thirds bar shows `cached`. Live screencast providers (`twc` / `ws4kp`) still need Chromium. See `config.example.json` and [Raspberry Pi profiles](raspberry-pi.md#device-profiles-features--youtube-cache).

**Channel numbers** work like local shows: auto 1-based position in the ordered lineup, with optional overrides via `channels.order` / `channels.numbers` or the web admin **Channel lineup** page.

```json
{
  "youtube_channels": [
    { "url": "https://www.youtube.com/@msrachel/", "title": "Ms Rachel" },
    {
      "url": "https://www.youtube.com/@BillNyeTheScienceGuyHD/",
      "title": "Bill Nye the Science Guy",
      "strip_title_prefix": true,
      "title_deletions": [
        "(?i)\\s*[-–—]\\s*(?:Best Quality\\s*[-–—]\\s*)?4K UPSCALED\\s*$"
      ]
    },
    {
      "url": "https://www.youtube.com/playlist?list=PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ",
      "title": "Beakman's World",
      "title_deletions": [
        "(?i)^Beakman's World\\s+",
        { "pattern": "(?i)\\bPDTV\\b.*$", "scope": "episode" }
      ],
      "title_substitutions": [
        ["(?i)\\b(\\d+)\\s*x\\s*(\\d+)\\b", "\\1x\\2"]
      ]
    }
  ]
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `handle` | one of `handle` / `url` | Channel handle (`@name`, bare name, or `UC…` id) |
| `url` | one of `handle` / `url` | Channel URL, `/channel/UC…`, or a playlist / `watch?…&list=` URL |
| `title` | no | Show name override (defaults to the YouTube channel or playlist title) |
| `channel` | no | Optional fixed dial number (merged into `channels.numbers`; prefer web admin) |
| `playlists_as_shows` | no | When true, each public playlist (except **All Videos**) becomes its own show — or use `playlist_shows` to pick/group which ones |
| `playlist_shows` | no | Whitelist / group playlists when unrolling. Strings are exact title matches; objects may set `title`, `match` (regex; digit capture → season #), or `playlists: [...]`. Implies `playlists_as_shows`. Example: Ghostwriter Season 1–3 → one **Ghostwriter** show with three seasons |
| `include_playlists` | no | Keep a **single** channel show, but only selected playlist seasons (same selector shape as `playlist_shows`). Pair with `include_all_videos: false` to drop uploads |
| `include_all_videos` | no | With `playlists_as_shows`, also keep the parent channel as an **All Videos** show (default **false** when unrolling). With `include_playlists`, default keeps All Videos unless set false |
| `strip_title_prefix` | no | When true (and `title` is set), strip a leading `Title -` / `Title —` / `Title |` / `Title:` from playlist and episode names |
| `title_deletions` | no | Patterns to remove for this entry (same as global `deletions`) |
| `title_substitutions` | no | `[pattern, replace]` pairs for this entry (same as global `substitutions`) |
| `title_rules` | no | Alternate form: rule list, or `{deletions, substitutions}` object. Applied after `strip_title_prefix` / `title_deletions` / `title_substitutions` |

```json
{
  "url": "https://www.youtube.com/@90sProject",
  "title": "90s Project",
  "playlist_shows": [
    "Wishbone",
    "Bobby's World",
    {
      "title": "Ghostwriter",
      "match": "(?i)^Ghostwriter\\s+Season\\s+(\\d+)$"
    }
  ]
}
```

For full channels, season **0** is **All Videos** (uploads); other seasons are public playlists — unless `playlists_as_shows` / `playlist_shows` is set, in which case those playlists appear as separate shows (or multi-season groups). A playlist-only URL becomes a single-season show. Private/unlisted playlists are not included. If Chrome is missing, shows still appear from cache when available; play shows **YOUTUBE UNAVAILABLE**.

The default config unrolls **true series** only from 90s Project, PBS KIDS, and Scholastic Classic; Bill Nye / Thomas / Reading Rainbow / Mister Rogers keep one show with filtered season playlists. Compilations and promo playlists are omitted. Set `"youtube_channels": []` to disable.

## Precedence

### Config file search

1. `$TV_TIME_CAPSULE_CONFIG` if set  
2. `<checkout>/config.json` when running from a dev tree  
3. `~/.config/tv-time-capsule/config.json` (or `$XDG_CONFIG_HOME/...`)

### Media paths at runtime

1. CLI `--media-dir` list (if any)  
2. Else `media_paths` from the loaded config, plus mountpoints from `mounts`  
3. Default `/media/usb` if the config is missing/empty  

Secrets for mounts: [Secrets & keychain](secrets.md).
