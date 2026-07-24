# Scripts reference

All paths relative to the repo root. Most scripts re-exec with `sudo` when needed.

## Appliance

| Script | Purpose |
|--------|---------|
| `install.sh` | Cross-platform desktop install: system deps + pipx/venv install of the app |
| `install-pi.sh` | Full Pi bootstrap: packages, copy to `/opt`, venv, networking, mounts sudoers, optional autostart, desktop shortcut |
| `scripts/install-system-deps.sh` | OS package prerequisites — ffmpeg required; remotes/keyring/NetworkManager best-effort |
| `scripts/fetch-sample-media.sh` | Download SampleLib MP4/PNG clips into `sample/media-a` + `sample/media-b` for layout testing |
| `scripts/reinstall-pipx.sh` | Force-reinstall this checkout into pipx (`--editable`) so bare `tv-time-capsule` on PATH tracks `src/` |

## Mode & session

| Script | Purpose |
|--------|---------|
| `scripts/set-mode.sh` | `kiosk` / `desktop` / `status` — auto-login + autostart (+ networking on kiosk) |
| `scripts/enable-autologin.sh` | Console or desktop auto-login (`raspi-config` nonint or fallback) |
| `scripts/enable-autostart.sh` | Install/enable systemd unit from template |
| `scripts/disable-autostart.sh` | Disable (and optionally remove) the unit |

## Networking & mounts

| Script | Purpose |
|--------|---------|
| `scripts/ensure-networking.sh` | Enable NetworkManager/dhcpcd/networkd, Wi‑Fi radio, wait-online |
| `scripts/ensure-mount-privileges.sh` | sudoers drop-in for passwordless mount/umount; `user_allow_other` for FUSE |

## Desktop integration

| Script | Purpose |
|--------|---------|
| `scripts/install-desktop-shortcut.sh` | `.desktop` on `~/Desktop` + applications menu (Pi Desktop only) |

## Templates

| Path | Purpose |
|------|---------|
| `scripts/systemd/tv-time-capsule.service.in` | systemd unit placeholders |
| `scripts/desktop/tv-time-capsule.desktop.in` | FreeDesktop launcher template |

## Environment variables (common)

| Variable | Used by | Meaning |
|----------|---------|---------|
| `TV_TIME_CAPSULE_BIN` | autostart / shortcut | Explicit path to the console script |
| `MEDIA_DIR` | autostart / shortcut / install | Single media dir convenience |
| `MEDIA_ROOT` | `install-pi.sh` | Default media tree location |
| `INSTALL_DIR` | `install-pi.sh` | Install prefix |
| `AUTOSTART` | `install-pi.sh` | `yes` / `no` |

Operator-facing behaviour for these scripts is documented under [Usage](../usage/README.md).
