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
    "analog_artifact_rate": 12
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
| `enabled` | *(from `default_enabled`)* | **Persisted** parent/kids mode — written when you toggle at runtime; restored on next start |
| `interleave_shows_movies` | `false` | In kids mode, show one combined alphabetical list of shows and movies instead of separate library screens |
| `allowlist` | *(absent / `null`)* | When **absent**, kids mode shows the full library (legacy). When **present** (even empty), kids mode only shows tagged titles. Parent **K** toggles tags on the show/movie/catalog cursor and creates the list on first use |

Kid mode auto-plays when a show is selected (resume or next-up in the last-watched season). Autoplay after an episode ends follows `playback.autoplay`. Quit (**Esc**, **Q**, window close) is disabled until you toggle back to parent mode. See [Controls → Kid-friendly mode](controls.md#kid-friendly-mode).

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
  }
}
```

| Field | Meaning |
|-------|---------|
| `watched` | Episode numbers finished (any order — out-of-order viewing is supported) |
| `pos_ep` / `pos` | In-progress bookmark (seconds into `pos_ep`) |

Legacy seasons with a single `ep` field (highest completed in order) migrate to `watched` automatically on the next save.

Episode list labels: **NEXT** (first unwatched), **RESUME** (bookmark), **WATCHED** (completed). Season list shows `21 eps` and `E-05 next` when applicable. Tap **R** on an episode to clear its watched flag and bookmark; hold **R** to rescan the library.

## `retro_tv`

Preferences for MyRetroTVs decade streams (dial years **1950–2009**). Updated automatically when you change channel types or volume in-app.

```json
{
  "retro_tv": {
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
| `filters` | `null` | Map of checkbox ids (`box_c` = Cartoons, `box_s` = Comedy, …) to on/off. `null` leaves the site default (all on) until you change them. Shared across all decades. |
| `volume` | `null` | Last Chrome media gain 0–100. `null` starts at 100. |

See [Fun tweaks & easter eggs → MyRetroTVs](fun-tweaks-and-easter-eggs.md#myretrotvs-decades-19502009).

## `youtube_channels`

List YouTube channels (or a specific playlist URL) as virtual shows on the normal browse list. Catalog is scraped via headless Chrome (no API key) and cached under `~/.local/share/tv-time-capsule/youtube/` (about 24 hours). Long-press **R** / admin rescan refreshes the cache. Playback opens `youtube.com/watch?v=…` in Chrome CDP screencast (requires Chrome/Chromium, same as Weather and Retro TV).

**Channel numbers** work like local shows: auto 1-based position in the ordered lineup, with optional overrides via `channels.order` / `channels.numbers` or the web admin **Channel lineup** page.

```json
{
  "youtube_channels": [
    { "url": "https://www.youtube.com/@msrachel/", "title": "Ms Rachel" },
    {
      "url": "https://www.youtube.com/playlist?list=PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ",
      "title": "Beakman's World"
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
| `playlists_as_shows` | no | When true, each public playlist (except **All Videos**) becomes its own show on the browse list — useful when a channel is a library of series playlists (e.g. 90s Project) |
| `include_all_videos` | no | With `playlists_as_shows`, also keep the parent channel as an **All Videos** show (default **false** when unrolling) |

For full channels, season **0** is **All Videos** (uploads); other seasons are public playlists — unless `playlists_as_shows` is set, in which case those playlists appear as separate shows (flat episode lists). A playlist-only URL becomes a single-season show. Private/unlisted playlists are not included. If Chrome is missing, shows still appear from cache when available; play shows **YOUTUBE UNAVAILABLE**.

The default / example config preloads a kids and classic set (Ms Rachel, Bluey, Sesame Street, Beakman’s World playlist, **90s Project with `playlists_as_shows`**, etc.). Set `"youtube_channels": []` to disable.
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
