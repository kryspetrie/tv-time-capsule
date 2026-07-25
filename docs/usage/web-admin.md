# Web admin

Configure TV Time Capsule from a phone or laptop on the same network — no SSH or JSON editing required. **No login or token**; only enable it on a network you trust.

## Enable

Off by default. Pass **`--admin`** when launching, or set in config:

```json
{
  "admin": {
    "enabled": true,
    "port": 8765,
    "bind": "0.0.0.0"
  }
}
```

Example:

```bash
poetry run tv-time-capsule --windowed --media-dir ./media --admin
```

When using `--windowed`, the admin server binds to **127.0.0.1** only (safe local dev). The terminal prints:

```text
Admin UI: http://127.0.0.1:8765/
```

Open that exact URL (include `http://`). The message appears right after the library scan, before the pygame window opens.

## Open the UI

On the same machine:

```text
http://127.0.0.1:8765/
```

From another device on the LAN:

```text
http://<pi-ip-address>:8765/
```

## Features

| Screen | What it does |
|--------|----------------|
| **Status** | Show count, current menu/playback state |
| **Player settings** | Toggle channel snow, shutdown collapse, scanlines, screensaver (saved to config; applies immediately) |
| **Media paths** | Edit local library roots, verify readability, preview or apply library scans |
| **Network mounts** | Edit CIFS/NFS/SSHFS/FTP entries, verify/mount shares |
| **Cached library** | Full hierarchical tree of the in-memory discovery cache (shows → seasons → episodes) |
| **Channel lineup** | Reorder shows, set fixed channel numbers, save to config |
| **Config file** | Edit raw JSON, save, or reload from disk without restarting |
| **Watch progress** | Read-only view of watch state (shows/seasons only) |
| **Keymap** | Current keyboard bindings with labels like `<up>`, `r`, `<escape>` |
| **Logs** | Recent app log lines |

### API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/library` | Cached library tree + summary |
| GET/POST | `/api/config` | Read or save config |
| POST | `/api/config/reload` | Reload config from disk |
| GET/POST | `/api/settings` | Read or patch player toggles |
| GET/POST | `/api/paths` | Read or update `media_paths` / `mounts` |
| POST | `/api/paths/verify` | Probe a local media path |
| POST | `/api/mounts/verify` | Mount or confirm a configured share |
| POST | `/api/library/scan` | Discover shows under paths (`apply: true` updates the running cache) |

Playback cannot be started or controlled from the web UI (by design).

## Security notes

- The server binds to **`0.0.0.0`** by default (all interfaces). Anyone on your LAN can open the page and change channels.
- Use `"bind": "127.0.0.1"` if you only need local access via SSH tunnel.
- HTTP only (no TLS). Do not expose port 8765 to the public internet.

## SSH tunnel (optional)

If `bind` is `127.0.0.1`:

```bash
ssh -L 8765:127.0.0.1:8765 pi@tv-time-capsule
```

Then open `http://localhost:8765/` on your laptop.

See also [Configuration → admin](configuration.md#admin) and [Controls](controls.md).
