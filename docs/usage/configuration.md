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

Optional custom key bindings (pygame key codes). Omitted actions use the defaults in [Controls](controls.md). Rebinding in-app (Tab) writes here; Tab on the key-config screen resets to defaults (empty object).

```json
{
  "keymap": {
    "up": 1073741906,
    "select": 13
  }
}
```

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

CLI overrides for one run: `--screensaver` and `--screensaver-timeout SEC` (only needed to force on when disabled in config).

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

## `ui`

CRT-style **fun tweaks** when tuning channels or quitting. See [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md) for behavior details and suggested combos.

```json
{
  "ui": {
    "channel_snow": false,
    "shutdown_collapse": false,
    "channel_snow_audio": false,
    "scanlines": false,
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
| `scanlines` | `false` | **Fun tweak** — Semi-transparent CRT scanline overlay |
| `analog_artifacts` | `true` | **Fun tweak** — Random brief static, line tear, and vertical roll on the **show browser** |
| `analog_artifact_rate` | `12` | Glitches per minute when `analog_artifacts` is on (`0` = no timed glitches) |
| `safe_zone` | `10` on all sides | CRT overscan inset — see [Safe zone](#safe-zone) |

CLI overrides: `--channel-snow`, `--shutdown-collapse`, `--scanlines`, `--analog-artifacts`, `--analog-artifact-rate N`, `--safe-zone PCT`, `--safe-zone-offset X,Y`. In **`--windowed`** mode the safe zone defaults to **0%** unless you pass `--safe-zone` explicitly (handy for dev on a monitor).

### Safe zone

Analog TVs often **overscan** the picture: the outer ~5–10% of the frame is clipped. Title-safe / action-safe margins keep important UI away from those edges.

When any `safe_zone` margin is greater than zero:

- The **logical framebuffer grows** with margin % (e.g. 5% → 704×528), but the **OS window** is separate: **800×600** by default in windowed mode (`--windowed`), resizable with a locked **4:3** aspect ratio.
- SDL GPU-scales the logical frame into that window (letterboxed as needed).
- **Menus, splashes, overlays, and screensaver** always render at native **640×480** (no interpolation) and are composited into the padded frame; border pixels use the **same background color** as that screen.
- **Video** is **full-bleed on the whole window** during playback (including margin areas). The window does not resize when you start an episode.
- **Playback HUD** (progress, volume, pause, Up Next) still respects safe-zone inset so controls stay title-safe on CRTs.
- **Secret test patterns** (`0` / `00` / `000`) fill the **entire extended framebuffer**.
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

On the **show browser only**, dial `0`, `00`, or `000` to display full-screen test patterns from your own PNGs in `src/tv_time_capsule/assets/` (`colorbars.png`, `grid.png`, `indianhead.png`). The app never generates these files. **Esc** exits. Full details: [Fun tweaks & easter eggs → Secret test patterns](fun-tweaks-and-easter-eggs.md#secret-test-patterns-show-browser).

Legacy `channel_change_effects` (`off` \| `visual` \| `visual+audio`) is still read once and mapped to `channel_snow` / `channel_snow_audio` if the new keys are absent.

## `gamepad`

USB game controllers (SDL mapping). Enabled by default when a controller is connected.

```json
{
  "gamepad": {
    "enabled": true
  }
}
```

| Control | Action |
|---------|--------|
| D-pad / left stick | Navigate menus; volume / seek during playback |
| A / Start | Select / pause-resume |
| B / Back | Back / stop |

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
