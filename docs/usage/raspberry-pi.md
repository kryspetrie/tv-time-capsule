# Raspberry Pi setup

## Recommended image

Use **Raspberry Pi OS Desktop**, and run day-to-day in **kiosk mode** (console auto-login + player service).

You keep a real desktop for Wi‑Fi UI, Samba browsing, and file management, without paying desktop RAM/CPU cost during normal TV use. Versus Lite: more disk and packages to update; kiosk runtime is similar to Lite.

Details and switching: [Kiosk ↔ desktop](kiosk-desktop.md).

## Full install

From a git checkout on the Pi:

```bash
chmod +x install-pi.sh && ./install-pi.sh
```

This typically:

- Installs all system prerequisites via `scripts/install-system-deps.sh`
  (ffmpeg/ffprobe/ffplay, SDL runtime, keyring, cifs/nfs/sshfs/curlftpfs, NetworkManager, exFAT, mpv/omxplayer)  
- Ensures networking + mount sudoers privileges  
- Registers **`vintage-tv.local`** on the LAN (mDNS via Avahi) for SCP and web admin  
- Copies the project to `/opt/tv-time-capsule` and installs into a venv  
- Creates a sample media tree under `/media/usb`  
- Enables systemd autostart  
- Installs a desktop shortcut when a Desktop environment is present  
- Tweaks audio / older-Pi settings as needed  

To (re)install system packages later:

```bash
./scripts/install-system-deps.sh
```

Environment overrides:

| Variable | Default | Meaning |
|----------|---------|---------|
| `MEDIA_ROOT` | `/media/usb` | Sample media + optional `--media-dir` for autostart |
| `INSTALL_DIR` | `/opt/tv-time-capsule` | Install location |
| `MDNS_HOSTNAME` | `vintage-tv` | Same as `--hostname` (env override) |
| `AUTOSTART` | `yes` | Set to `no` to skip systemd enable |

Install flags:

```bash
./install-pi.sh --hostname vintage-tv          # default LAN name
./install-pi.sh --hostname vintage-tv-bedroom   # second TV on the network
./install-pi.sh --skip-hostname                # skip mDNS registration
```

The chosen hostname is written to `network.mdns_hostname` in the service user's `config.json` and registered on the LAN as `<name>.local`.

Example for a second TV:

```bash
./install-pi.sh --hostname vintage-tv-bedroom
```

## After install

1. Add shows under your media root(s) or configure [remote mounts](remote-mounts.md)  
2. Edit `~/.config/tv-time-capsule/config.json` as the service user  
3. Reboot (or `sudo systemctl start tv-time-capsule`)  

After adding files on USB or NAS without rebooting, **hold R** on the show list to rescan, or run `tv-time-capsule --rescan-only` to validate paths from SSH.

## Display notes

- You need a **display** (HDMI or composite), not necessarily a full desktop session  
- Default kiosk uses SDL/pygame on the console framebuffer / KMS when possible  
- `--graphical` autostart waits for a desktop session and sets `DISPLAY=:0`  

See [Autostart & login](autostart.md) and [Networking](networking.md).

## Device profiles (features + YouTube cache)

| Hardware | Suggested config |
|----------|------------------|
| Pi 1 / Zero | `features.retro_tv: true` with `retro_tv.playback_mode: cached` (or `features.retro_tv: false`); `weather.screencast.mode: auto`; `youtube.playback_mode: cached_only`; `youtube.cache.enabled: true` with `directory` on NAS |
| Pi 2 / 3 | Weather auto; Retro `cached` recommended; `prefer_cache` + optional local cache |
| Pi 4 / 5 / desktop | All features on; Retro `live` or `cached`; `prefer_cache` or `live`; optional idle cache |

**Offline YouTube workflow:** on a desktop/NAS with good bandwidth, set `youtube.cache.enabled: true` and run `tv-time-capsule --youtube-cache-sync`. Mount that directory on the Pi and use `cached_only` so weak devices never spawn Chrome for YouTube library playback. Crop/zoom (**T**) uses the shared crop cache for both live and file backends.

**Decades (`1950`–`2009`):** `retro_tv.playback_mode: cached` keeps Chrome as a playlist oracle only (no screencast) and plays a rolling pair of yt-dlp temp files via ffmpeg — much cheaper than live CDP blit on Pi.

See [Configuration](configuration.md) (`features`, `weather.screencast`, `youtube`, `retro_tv`) and the [offline YouTube plan](../development/pi-features-offline-youtube-plan.md).
