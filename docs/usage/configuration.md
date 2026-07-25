# Configuration

## Where the app looks for `config.json`

The app loads the **first existing file** in this order:

| Priority | Path | When it applies |
|----------|------|-----------------|
| 1 | `$TV_TIME_CAPSULE_CONFIG` | Explicit override (any install) |
| 2 | `<repo>/config.json` | Development — Poetry checkout, `pip install -e .`, or `PYTHONPATH=src` |
| 3 | `~/.config/tv-time-capsule/config.json` | Installed app (pipx, system package, non-checkout run) |

`$XDG_CONFIG_HOME` replaces `~/.config` when set.

**Development:** copy the example into the repo root and edit it there:

```bash
cp config.example.json config.json
poetry run tv-time-capsule --windowed
```

Key rebinding and in-app saves write back to whichever file was loaded.

**Installed (pipx):** use the user config directory:

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

On first run with no config file anywhere in the search path, a minimal default is written to the default location for your install type (`./config.json` in a checkout, otherwise `~/.config/tv-time-capsule/config.json`):

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
