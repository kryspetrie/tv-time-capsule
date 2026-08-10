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

## Device readiness & feature completeness

Assumptions: **kiosk / framebuffer** (not a loaded desktop), **USB or local media** preferred over flaky NFS, and **stock product defaults** — Weather `native`, YouTube `prefer_cache` + cache enabled, Retro TV `cached`. Live Chrome modes (`twc` / `ws4kp`, YouTube `live`, Retro `live`) are opt-in and dominate CPU/RAM.

**Cost drivers:** Chromium CDP screencast ≫ yt-dlp fills ≫ native pygame Weather / ffmpeg file play.

### Readiness by board

| Board (typical RAM) | Deploy ready? | Completeness @ defaults | Notes |
|---------------------|---------------|-------------------------|--------|
| **Pi 1 / Zero (512 MB)** | Conditional | **~55–65%** | Browse + local video + native Weather if careful. yt-dlp fills are slow; concurrent Chrome is unrealistic. Prefer `youtube.playback_mode: cached_only`, USB media; consider `features.retro_tv: false` if the playlist oracle hurts. |
| **Zero 2 W (~1 GB)** | Yes, with care | **~75–85%** | Closer to a weak Pi 3. Default stack usually works; avoid live Weather / YouTube / Retro. Idle cache fills OK but slow. |
| **Pi 2 (1 GB)** | Yes | **~85–90%** | Sweet spot for “full product without live Chrome.” Native Weather, cached YT, cached Decades, music/announcements, radar, alert marquee. |
| **Pi 3 / 3B+ (1 GB)** | Yes | **~90–95%** | Same as Pi 2 with more headroom. Live `ws4kp` (~4 FPS) can limp; `twc` / YouTube live still heavy. |
| **Pi 4 (2–8 GB)** | Yes | **~95–100%** | Defaults comfortable. Live Chrome modes are realistic if enabled. |
| **Pi 5** | Yes | **100%** | Full feature set including live screencast; overkill for defaults-only. |

### Feature completeness by subsystem

| Feature | Pi 1 / Zero | Zero 2 / Pi 2–3 | Pi 4 / 5 |
|---------|-------------|-----------------|----------|
| Browse UI, dials, kids mode, screensaver | Full | Full | Full |
| Local library (USB) | Full | Full | Full |
| NAS / NFS library | Fragile | OK if stable | Fine |
| YouTube **cached** play | Good if files present | Full | Full |
| YouTube **yt-dlp fill on-device** | Works, very slow | Usable | Comfortable |
| YouTube **live** Chrome | Not ready | Marginal / no | Ready |
| Weather **native** (pygame, NWS, radar, marquee) | Ready (watch RAM) | Full | Full |
| Weather **twc / ws4kp** Chrome | Not ready | Limp / optional | Ready |
| Retro **cached** (oracle + ffmpeg) | Risky (Chrome oracle + RAM) | Ready | Ready |
| Retro **live** screencast | No | No / painful | Ready |
| Alert feeds (NWS + optional RSS / FlashAlert) | Ready (network cheap) | Ready | Ready |
| Music + page VO | Ready; cut if RAM tight | Full | Full |

### What “fully featured” means

- **Full @ defaults:** browse + native Weather (radar + marquee), YouTube from the forever cache, Decades from temp clips — **no** continuous screencast.
- **Not required for “full”:** weather.com / WS4KP live, YouTube live, Retro live — treat those as **Pi 4+** experiences.

### Suggested config by class

| Hardware | Local library | YouTube | Weather | Retro TV | Suggested config |
|----------|---------------|---------|---------|----------|------------------|
| **Pi 1 / Zero** | Yes (USB preferred) | `cached_only` (or `prefer_cache` with pre-filled tree) | Keep **`native`**; or `features.weather: false` | Prefer **`cached`** or disable feature | Point `youtube.cache.directory` at a shared tree if possible; use `--no-youtube-idle-cache` if yt-dlp bot-checks |
| **Zero 2 / Pi 2 / 3** | Yes | `prefer_cache` (default) or `cached_only` | Keep **`native`**; live Chrome optional / limp | Keep **`cached`** | Stock defaults are the target |
| **Pi 4 / 5 / desktop** | Yes | `prefer_cache` or `live` | **`native`** or opt into `twc` / `ws4kp` | **`cached`** or `live` | Enable live Chrome explicitly when wanted |

### Rules of thumb

- **Browse UI, kids mode, dials, test patterns, screensaver** — fine on all Pi classes.
- **YouTube `live` / Retro `live` / Weather `twc`/`ws4kp`** — Chrome screencast; realistic on Pi 4+ (Weather screencast can limp on older boards via adapt).
- **Weather `native`** — pygame UI + NWS/Open-Meteo; **no Chromium**; **product default** on all platforms.
- **YouTube `cached_only` + Retro `cached`** — Chrome mostly avoided for playback (Retro still needs a light Chrome “oracle”); Pi 2/3 sweet spot for full features.
- **yt-dlp** runs on every device when cache is enabled; fills are slower on weak boards. Disable idle fills for one run with `tv-time-capsule --no-youtube-idle-cache`, or set `youtube.cache.download_when_idle: false`. Optional: pre-fill on a desktop/NAS and share `youtube.cache.directory`.

**Weather providers** (`weather.provider`): **`native` (default)**; `auto` → native; live opt-in `twc` / `ws4kp`. Switch with **Enter** on channel `004`. Screencast knobs apply only to live providers. TWC uses adaptive screencast (`mode: auto`); **WS4KP is fixed at ~4 FPS** by default. See [Native weather & cached defaults](native-cached-defaults.md).

**Offline YouTube workflow:** defaults enable `prefer_cache` + `youtube.cache.enabled`. Fill with idle downloads and/or `tv-time-capsule --youtube-cache-sync`. Use `cached_only` so weak devices never spawn Chrome for library playback. Crop/zoom (**T**) uses the shared crop cache for live and file backends.

**Decades (`1950`–`2009`):** default `retro_tv.playback_mode: cached` (playlist oracle + temp yt-dlp + ffmpeg). Set `live` for full CDP screencast (Pi 4+).

See [Native weather & cached defaults](native-cached-defaults.md), [Configuration](configuration.md) (`features`, `weather.screencast`, `youtube`, `retro_tv`), and the [offline YouTube plan](../development/pi-features-offline-youtube-plan.md).
