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

Cost is dominated by **Chromium** (especially CDP screencast). Local/cached file playback via ffmpeg is comparatively cheap. Prefer filling the forever YouTube cache on a desktop/NAS, then pointing weak Pis at that tree.

| Hardware | Local library | YouTube | Weather | Retro TV | Suggested config |
|----------|---------------|---------|---------|----------|------------------|
| **Pi 1 / Zero** | Yes (USB preferred over flaky NFS) | Tighten to `cached_only` + NAS/desktop tree | Keep **`native`** (default; no Chromium); or `features.weather: false` | Keep **`cached`** (default) or disable feature | Stock defaults already match; set `youtube.playback_mode: cached_only` and point `youtube.cache.directory` at NAS |
| **Pi 2 / 3** | Yes | Keep `prefer_cache` (default) or `cached_only` | Keep **`native`**; opt into `ws4kp`/`twc` if Chromium is fine | Keep **`cached`** | Defaults are Pi-friendly; live Chrome is opt-in |
| **Pi 4 / 5 / desktop** | Yes | Keep `prefer_cache` or set `live` | Keep **`native`** or opt into `twc` / `ws4kp` | Keep **`cached`** or set `live` | All features on; enable live Chrome explicitly when wanted |

**Rules of thumb**

- **Browse UI, kids mode, dials, test patterns, screensaver** — fine on all Pi classes.
- **YouTube `live` / Retro `live` / Weather `twc`/`ws4kp`** — Chrome screencast; realistic on Pi 4+ (Weather screencast can limp on older boards via adapt).
- **Weather `native`** — pygame UI + NWS/Open-Meteo; **no Chromium**; **product default** on all platforms (live `twc`/`ws4kp` are opt-in).
- **YouTube `cached_only` + Retro `cached`** — Chrome mostly avoided for playback (Retro still needs a light Chrome “oracle”); Pi 2/3 sweet spot for full features.
- Do **not** use a weak Pi as the yt-dlp fill machine — run `tv-time-capsule --youtube-cache-sync` on a desktop/NAS.

**Weather providers** (`weather.provider`): **`native` (default)** pygame Retro Weather; `auto` → native; live opt-in `twc` (weather.com/retro CDP) / `ws4kp` (WeatherStar 4000+ CDP). Switch with **Enter** on channel `004` (saved to config). Screencast modes need Chromium. TWC uses adaptive screencast (`mode: auto`); **WS4KP is fixed at ~4 FPS** by default (`screencast.ws4kp_target_fps`). See [Native weather & cached defaults](native-cached-defaults.md).

**Offline YouTube workflow:** defaults already enable `prefer_cache` + `youtube.cache.enabled`. Fill on a desktop/NAS (`--youtube-cache-sync`), mount the same `directory` on the Pi, use `cached_only` so weak devices never spawn Chrome for library playback. Crop/zoom (**T**) uses the shared crop cache for both live and file backends.

**Decades (`1950`–`2009`):** default `retro_tv.playback_mode: cached` keeps Chrome as a playlist oracle only (no screencast) and plays a rolling pair of yt-dlp temp files via ffmpeg. Set `live` for full CDP screencast.

See [Native weather & cached defaults](native-cached-defaults.md), [Configuration](configuration.md) (`features`, `weather.screencast`, `youtube`, `retro_tv`), and the [offline YouTube plan](../development/pi-features-offline-youtube-plan.md).
