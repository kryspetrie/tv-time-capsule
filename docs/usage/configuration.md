# Configuration

## Locations

| File | Purpose |
|------|---------|
| `~/.config/tv-time-capsule/config.json` | Media paths and remote mounts |
| `~/.local/share/tv-time-capsule/state.json` | Resume positions, keymap |

On first run without a config file, a default is written:

```json
{
  "media_paths": ["/media/usb"],
  "mounts": []
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

## Full example

```json
{
  "media_paths": [
    "/media/usb",
    "/mnt/tv/nas-kids"
  ],
  "mounts": [
    {
      "type": "cifs",
      "source": "//nas.local/KidsShows",
      "mountpoint": "/mnt/tv/nas-kids",
      "username": "media",
      "keyring": "nas-kids",
      "options": ["uid=1000", "gid=1000", "vers=3.0"]
    }
  ]
}
```

## Precedence

1. CLI `--media-dir` list (if any)  
2. Else `media_paths` from config, plus mountpoints from `mounts`  
3. Default `/media/usb` if the config is missing/empty  

Secrets for mounts: [Secrets & keychain](secrets.md).
