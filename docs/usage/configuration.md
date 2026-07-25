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
poetry run tv-time-capsule --windowed
```

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
| `~/.local/share/tv-time-capsule/state.json` | Resume positions and watch progress |
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
| `enabled` | `false` | Turn screensaver on |
| `timeout_seconds` | `300` | Menu inactivity before start (minimum 10) |

CLI overrides for one run: `--screensaver` and `--screensaver-timeout SEC`.

## `playback`

Controls automatic advance to the next episode when one finishes naturally (Esc still stops immediately).

```json
{
  "playback": {
    "autoplay": "next_in_season_only",
    "autoplay_countdown_seconds": 5
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `autoplay` | `next_in_season_only` | `off`, `next_episode` (includes next season), or `next_in_season_only` |
| `autoplay_countdown_seconds` | `5` | “Up next” wait before starting (0 = instant). **Esc** cancels during countdown |
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
| `channel_snow` | `false` | **Fun tweak** — B&W static burst when committing a channel number (show, season, or episode list). Not arrow keys. |
| `shutdown_collapse` | `false` | **Fun tweak** — CRT vertical collapse animation on quit |
| `channel_snow_audio` | `false` | Quiet white-noise with channel snow (defaults **on** when `channel_snow` is enabled; set `false` to mute) |
| `scanlines` | `false` | **Fun tweak** — Semi-transparent CRT scanline overlay |
| `analog_artifacts` | `false` | **Fun tweak** — Random brief static, line tear, and vertical roll on the **show browser** |
| `analog_artifact_rate` | `12` | Glitches per minute when `analog_artifacts` is on (`0` = no timed glitches) |

CLI overrides: `--channel-snow`, `--shutdown-collapse`, `--scanlines`, `--analog-artifacts`, `--analog-artifact-rate N`

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
| `enabled` | `false` | Start HTTP admin on app launch |
| `port` | `8765` | TCP port |
| `bind` | `0.0.0.0` | Listen address (`127.0.0.1` = local only) |

No authentication — only enable on a home LAN you trust.

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
