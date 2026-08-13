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

If you ran `install-pi.sh` or `install.sh`, the device is also advertised as **`http://vintage-tv.local:8765/`** via mDNS (Bonjour/Avahi). Use a unique name when you have more than one TV:

```bash
MDNS_HOSTNAME=vintage-tv-bedroom ./install-pi.sh
# → http://vintage-tv-bedroom.local:8765/
```

Check or change the name later:

```bash
sudo ./scripts/ensure-mdns-hostname.sh --status
sudo ./scripts/ensure-mdns-hostname.sh --hostname vintage-tv-kitchen
```

The chosen name is stored in `/etc/tv-time-capsule/mdns-hostname` on Linux.

## Features

| Screen | What it does |
|--------|----------------|
| **Status** | Show count, current menu/playback state, active profile |
| **Player settings** | Fun tweaks, CRT safe zone, volume, stall auto-skip, read-only media, pause CC OSD, screensaver, etc. |
| **Profiles** | Active profile, labels, PIN (write-only), favorites counts, copy allowlist parent→kids / kids→guest |
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
| GET | `/api/profiles` | Active profile + summary (no PIN values) |
| POST | `/api/profiles/active` | Switch active profile (`{"profile":"kids"}`) |
| POST | `/api/profiles/pin` | Set/clear PIN (`{"profile":"kids","pin":"1234"}` or `null`) |
| POST | `/api/profiles/copy-allowlist` | Copy allowlist (`{"src":"parent","dest":"kids"}`) |
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
