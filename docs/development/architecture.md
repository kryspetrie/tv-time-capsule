# Architecture

## Runtime overview

```
CLI (cli.py)
  ├─ load config.json
  ├─ ensure_mounts()          # optional CIFS/NFS/SSHFS/FTP
  ├─ discover_shows()         # walk media_paths
  └─ TVTimeCapsule.run()      # pygame event loop
        ├─ menu / channel UI
        └─ EmbeddedPlayer     # ffmpeg frames + ffplay audio
              └─ omxplayer fallback on older Pi when needed
```

## Display model

- All UI is drawn to a fixed virtual canvas (640×480, true 4:3). `pygame.SCALED`
  GPU-scales that surface to the window/desktop; the app does **not** CPU-scale
  with `transform.scale` every frame  
- Fullscreen uses `FULLSCREEN | SCALED` (SDL fullscreen-desktop). Plain
  `FULLSCREEN` without a matching size requests an exclusive mode set that
  rewrites the monitor resolution and wipes RandR scaling on mixed-DPI desktops  
- `--windowed` uses the same logical surface with `SCALED` only  
- 4:3 is preserved by SDL letterboxing; `--force-43` is kept for compatibility  
- Embedded video is already scaled/padded to canvas size by FFmpeg, so frames
  are blitted without a second resize  
- **Display required**; full desktop environment optional  
  - Console / KMS / framebuffer: default kiosk systemd unit  
  - Desktop session: `--graphical` sets `DISPLAY=:0`  

## Persistence

| Path | Contents |
|------|----------|
| Active `config.json` | media_paths, mounts, keymap — see [config search order](../usage/configuration.md#where-the-app-looks-for-configjson) |
| `~/.config/tv-time-capsule/` | user config dir; credentials and temp mount files even in dev |
| `~/.local/share/tv-time-capsule/state.json` | Per-episode watch flags and in-progress bookmarks |
| OS keyring service `tv-time-capsule` | optional mount passwords |

## Pi appliance model

Recommended: Raspberry Pi OS **Desktop** image, operated mostly as **kiosk**:

1. `ensure-networking.sh` keeps NetworkManager / Wi‑Fi alive without a panel  
2. `enable-autologin.sh` + `enable-autostart.sh` (via `set-mode.sh kiosk`)  
3. Unit waits on `network-online.target`, then mounts remotes and starts pygame  

Switch to desktop mode when configuring Samba/Wi‑Fi UIs; switch back for daily TV use. See usage docs on [kiosk ↔ desktop](../usage/kiosk-desktop.md).

## Secrets

Mount auth resolution order (simplified):

1. Literal `password` / `username` in config (discouraged for passwords)  
2. Keyring item (`keyring` / `password_keyring`)  
3. Credentials file (`credentials`)  

CIFS passwords from keyring are materialized as a short-lived `0600` credentials file for `mount.cifs`.

Wi‑Fi is **out of band**: NetworkManager system connections, not the app keyring API.
