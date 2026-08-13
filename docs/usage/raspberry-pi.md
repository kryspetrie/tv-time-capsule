# Raspberry Pi — from empty board to TV

This guide takes you from a **Pi with no OS** to TV Time Capsule running as a living-room appliance. Desktop / laptop installs stay in [Getting started](getting-started.md).

**Typical time:** 30–60 minutes (plus media copy time).

---

## 1. What you need

| Item | Notes |
|------|--------|
| Raspberry Pi | Any model with video out works; see [which Pi?](#11-which-pi) |
| microSD card | **16 GB+** (32 GB recommended). Class 10 / A1 or better |
| Power supply | Official or rated PSU for your model (undervoltage causes freezes) |
| Display | HDMI TV/monitor, or **composite** (3.5 mm AV or RCA) on models that support it |
| Keyboard (or USB gamepad) | Needed for first-time setup; optional later if you use [web admin](web-admin.md) |
| Network | Ethernet is simplest; Wi‑Fi works (configure in Imager or after first boot) |
| Another computer | To flash the SD card (Windows, macOS, or Linux) |

### 1.1 Which Pi? (OS version matters)

Raspberry Pi’s download page currently has two tracks (names change over time — always read the **Debian** line in Imager / on [software downloads](https://www.raspberrypi.com/software/operating-systems/)):

| Track (Imager / download name) | Debian base (as of mid‑2026) | Role |
|--------------------------------|------------------------------|------|
| **Raspberry Pi OS** (current) | **Trixie** (13) | Newest — prefer on Pi 4 / 5 |
| **Raspberry Pi OS (Legacy)** | **Bookworm** (12) | Older stack — **prefer on Pi 1 / Zero / Zero W** (and often what Imager offers when you select those devices) |

Do **not** assume “newest Lite” is best on a 512 MB board. Imager deliberately steers older devices toward **Legacy** because current releases have been painful on ARMv6 without workarounds.

| Board | Recommendation | Exact image to flash | Notes |
|-------|----------------|----------------------|--------|
| **Pi 5** | Best | **Raspberry Pi OS** Desktop **64-bit** (current / Trixie) | Full features including live Chrome modes |
| **Pi 4** (2 GB+) | Excellent | **Raspberry Pi OS** Desktop **64-bit** (current / Trixie) | Comfortable defaults; live Chrome OK |
| **Pi 4** (1 GB) | Good | Current Desktop **64-bit**, or current / Legacy **Lite** | Prefer stock app defaults (native Weather, cached YouTube) |
| **Pi 3 / 3B+** | Good daily driver | Current Desktop **64-bit**, or **Legacy** Desktop/Lite if current misbehaves | Sweet spot for full product **without** live Chrome |
| **Pi 2** | Good | **Legacy Lite 32-bit** (or Legacy Desktop 32-bit) | Prefer Legacy over bleeding-edge current on this class |
| **Zero 2 W** | OK with care | **Legacy Lite 64-bit** preferred (or current Lite 64-bit) | Avoid live Weather / YouTube / Retro |
| **Pi 1 / Zero / Zero W** | Conditional | **Legacy Lite 32-bit only** — see [§1.2](#12-pi-1--original-zero--use-the-smallest-os) | 512 MB; never Desktop; never 64-bit; avoid current/Trixie unless you know you need it |

### 1.2 Pi 1 / original Zero — Legacy Lite 32-bit (smallest that works)

These boards have **512 MB RAM** and an older ARMv6 CPU. Use the **most minimal OS that Raspberry Pi still supports well for this hardware**:

| Do | Don’t |
|----|--------|
| **Raspberry Pi OS (Legacy) Lite (32-bit)** — Debian **Bookworm** | Current/Trixie Desktop or Full |
| **32-bit** only | Any **64-bit** image (will not boot / wrong CPU) |
| Trust Imager when it offers **Legacy** after you pick Pi 1 / Zero | Force “newest” via *No filtering* unless Legacy truly will not boot |
| Console + **SSH** admin from a laptop | Expect a usable on-Pi desktop |
| USB / local media; `youtube.playback_mode: cached_only` | Live Chrome Weather / YouTube / Retro on-device |

**Why Legacy, not “newest Lite”?** Current Raspberry Pi OS (Trixie) is listed as compatible with all models in theory, but on Pi 1 / original Zero the practical path is still **Legacy (Bookworm) Lite 32-bit**: less RAM pressure, fewer compositor/Wayland regressions, and the same image family Imager recommends when you select those devices. Hacking a brand-new image onto a Pi 1 is exactly what we want to avoid.

In Raspberry Pi Imager:

1. **Choose device** → Raspberry Pi **1** (or Zero / Zero W).
2. **Choose OS** → prefer what Imager lists for that device (often under **Raspberry Pi OS (Legacy)**) → **Lite (32-bit)**.  
   Confirm the description says **Debian Bookworm** (Legacy) and **Lite** / no desktop.  
   If you only see current/Trixie images, open *Raspberry Pi OS (other)* / Legacy category, or briefly use *No filtering* and still pick **Legacy Lite 32-bit** — not Trixie Desktop.
3. Enable **SSH** and (if needed) Wi‑Fi in OS customisation — you will administer this Pi over the network / HDMI console, not a GUI.

Do **not** install Desktop “just to configure Wi‑Fi once.” Set Wi‑Fi in Imager (or `nmcli` over SSH after Ethernet first boot). After `install-pi.sh`, stay on console — Lite has no desktop, which is what you want for free RAM.

Feature limits and config: [§9 Suggested config](#9-suggested-config-by-pi-class) and [§10 Readiness](#10-device-readiness--feature-completeness).

**Display out by era**

- **Pi 4 / 5:** HDMI only (micro-HDMI on Pi 4).
- **Pi 1–3 / Zero:** HDMI and/or composite (AV jack or separate RCA on older boards). `install-pi.sh` enables composite tweaks on original Model B.
- Always connect the display **before** first boot so the firmware picks the right output.

---

## 2. Flash the OS (empty SD → bootable card)

### 2.1 Choose an image

| Goal | Image | When to use |
|------|-------|-------------|
| **Pi 1 / Zero / Zero W (required)** | **Raspberry Pi OS (Legacy) Lite (32-bit)** — Debian **Bookworm** | Smallest practical OS for 512 MB ARMv6. See [§1.2](#12-pi-1--original-zero--use-the-smallest-os). |
| **Pi 2 / Zero 2 (lean)** | **Legacy Lite** (32-bit on Pi 2, 64-bit on Zero 2) | Prefer Legacy over current/Trixie for fewer surprises |
| **Recommended appliance (Pi 3+)** | **Raspberry Pi OS** Desktop (current / **Trixie**), matching bitness in the table below | Day-to-day use [kiosk mode](kiosk-desktop.md) so the desktop is not using RAM |
| Headless Pi 3 / 4 | Current or Legacy **Lite** | SSH-only; more free RAM than Desktop |

Use images from the official [Raspberry Pi OS downloads](https://www.raspberrypi.com/software/operating-systems/) / Imager catalog only (not random third-party images).

| Hardware | Pick in Imager |
|----------|----------------|
| Pi 5, Pi 4 | **Current** Desktop **64-bit** (Trixie) |
| Pi 3 | Current Desktop **64-bit**, or Legacy if current is unstable for you |
| Zero 2 W | **Legacy Lite 64-bit** preferred |
| Pi 2 | **Legacy Lite 32-bit** (or Legacy Desktop 32-bit) |
| **Pi 1, Zero, Zero W** | **Legacy Lite 32-bit only** — never Desktop, never 64-bit, avoid current/Trixie |

Quick check after first boot:

```bash
# Should look like "bookworm" on Pi 1 / Zero; "trixie" is fine on Pi 4/5
cat /etc/os-release | grep -E 'VERSION_CODENAME|PRETTY_NAME'
```

### 2.2 Raspberry Pi Imager steps

On your PC/Mac:

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Insert the microSD card.
3. **Choose device** → your Pi model (helps Imager filter images — for Pi 1 / Zero this often surfaces **Legacy** first).
4. **Choose OS** → match [§2.1](#21-choose-an-image).  
   For **Pi 1 / Zero / Zero W**: **Raspberry Pi OS (Legacy) Lite (32-bit)** only — not Desktop, not current/Trixie unless you deliberately override.
5. **Choose storage** → the SD card (double-check the device name).
6. Open **OS customisation** (gear / edit settings) **before** writing:

   | Setting | Suggested value |
   |---------|-----------------|
   | Hostname | e.g. `vintage-tv` (optional; `install-pi.sh` can set mDNS later) |
   | Username / password | Create a user (default `pi` is fine if you set a strong password) |
   | Wireless LAN | SSID + password + country **if** you will use Wi‑Fi |
   | Enable SSH | **On** (password or public key) — strongly recommended |
   | Locale / timezone / keyboard | Your region |

7. Write the image and wait for verification.
8. Eject the card, insert it into the Pi, connect display + power.

### 2.3 First boot

- First boot can take **2–5 minutes** (resize filesystem, reboot once).
- Desktop: finish the welcome wizard if it appears (updates can wait until after install if you prefer).
- Lite: log in over HDMI keyboard or SSH.

### 2.4 Connect from another computer (SSH)

You almost always administer the Pi from a laptop over the network. Enable **SSH in Imager** (step 2.2) so this works on first boot.

**1. Find the Pi**

```bash
# Hostname from Imager, or the name install-pi.sh registers later:
ping vintage-tv.local

# If .local does not resolve, use the IP from your router’s DHCP list
ping 192.168.1.50
```

**2. Log in with SSH**

```bash
# macOS / Linux / Windows (PowerShell or Windows Terminal):
ssh YOUR_USER@vintage-tv.local

# Or by IP:
ssh YOUR_USER@192.168.1.50
```

Use the **username and password** (or SSH key) you set in Imager. The first connection asks you to trust the host key — type `yes`.

**3. Copy files**

```bash
# To the Pi
scp -r '/path/to/Show Name' YOUR_USER@vintage-tv.local:/media/usb/

# From the Pi (example: grab config)
scp YOUR_USER@vintage-tv.local:~/.config/tv-time-capsule/config.json ./
```

SSH works whether the Pi is in **kiosk** or **desktop** mode. You do not need a keyboard plugged into the TV for install or updates once SSH is on.

**Wi‑Fi after first boot** (if you skipped Imager Wi‑Fi):

- **On the Pi Desktop:** use the network applet, then make the connection system-wide (see [Networking](networking.md)).
- **Over SSH / Lite:**

  ```bash
  sudo nmcli device wifi connect "YourSSID" password "secret"
  sudo nmcli connection modify "YourSSID" connection.permissions ""
  ```

---

## 3. Get TV Time Capsule onto the Pi

You need a **git checkout** of this repo on the Pi (the installer copies it into `/opt/tv-time-capsule`).

### Option A — clone over the network (usual)

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/kryspetrie/tv-time-capsule.git
cd tv-time-capsule
```

Private/SSH clone if you use deploy keys:

```bash
git clone git@github.com:kryspetrie/tv-time-capsule.git
cd tv-time-capsule
```

### Option B — copy from another machine

On your PC (with a local checkout):

```bash
rsync -a --exclude '.venv' --exclude '.git' ./tv-time-capsule/ YOUR_USER@vintage-tv.local:~/tv-time-capsule/
ssh YOUR_USER@vintage-tv.local
cd ~/tv-time-capsule
```

---

## 4. Install (one script)

From the checkout on the Pi:

```bash
chmod +x install-pi.sh
./install-pi.sh
```

Second TV on the same LAN (unique mDNS name):

```bash
./install-pi.sh --hostname vintage-tv-bedroom
```

Skip hostname registration:

```bash
./install-pi.sh --skip-hostname
```

### What `install-pi.sh` does

- Installs system packages via `scripts/install-system-deps.sh` (ffmpeg/ffprobe/ffplay, SDL, **system Chromium**, mount helpers, NetworkManager, etc.)
- File playback uses **ffmpeg** (with `playback.hw_decode` on supported Pi)
- Ensures networking + passwordless mount sudoers
- Registers **`<hostname>.local`** (Avahi / mDNS) unless `--skip-hostname`
- Copies the project to `/opt/tv-time-capsule` and installs into a venv
- Creates a sample media tree under `/media/usb` (override with `MEDIA_ROOT=...`)
- Enables systemd autostart for the player (unless `AUTOSTART=no`)
- Installs a desktop shortcut when a Desktop environment is present
- Tweaks audio / original Model B composite settings when relevant

### Chromium (YouTube catalog / live screencast / Retro oracle)

**One install path everywhere:** the OS package (or Homebrew cask on macOS). The app never downloads a browser zip at runtime.

| Feature | Needs Chromium? |
|---------|-----------------|
| Local library playback (ffmpeg) | No |
| Weather **native** (default) | No |
| YouTube **cached** file play | No (yt-dlp files) |
| YouTube catalog scrape / **live** play | **Yes** |
| Retro TV **cached** (playlist oracle) | **Yes** (short-lived) |
| Weather `twc` / `ws4kp` or Retro **live** | **Yes** (heavy) |

`install-pi.sh`, `install.sh`, and `scripts/install-system-deps.sh` install distro **Chromium** (apt/`chromium-browser`, dnf/pacman `chromium`, or `brew install --cask chromium`). At runtime the app only looks for that system binary (`chromium`, `chromium-browser`, or Google Chrome).

Verify after install:

```bash
command -v chromium || command -v chromium-browser
# macOS:
ls "/Applications/Chromium.app" "/Applications/Google Chrome.app" 2>/dev/null
```

If missing: re-run `./scripts/install-system-deps.sh`, or `sudo apt install -y chromium`.

On Pi 1 / Zero, Chromium may still be installed for catalog/oracle, but set `youtube.playback_mode: cached_only` and avoid live screencast so Chrome is not running during normal watch.

| Variable | Default | Meaning |
|----------|---------|---------|
| `MEDIA_ROOT` | `/media/usb` | Sample media + optional `--media-dir` for autostart |
| `INSTALL_DIR` | `/opt/tv-time-capsule` | Install location |
| `MDNS_HOSTNAME` | `vintage-tv` | Same as `--hostname` (env override) |
| `AUTOSTART` | `yes` | Set to `no` to skip systemd enable |

Reinstall OS packages only later:

```bash
./scripts/install-system-deps.sh
```

---

## 5. Add your media

```text
/media/usb/
  Show Name/
    s01/
      s01e01.mp4
      s01e02.mp4
    thumbnail.png          # optional poster
  Movies/
    Some Film (1999).mp4   # see media-library.md for movie layouts
```

Copy over the network:

```bash
scp -r '/path/to/Show Name' YOUR_USER@vintage-tv.local:/media/usb/
```

Or plug in a USB drive and copy with the Desktop file manager / `rsync`. Full layout rules: [Media library](media-library.md). Remote NAS: [Remote mounts](remote-mounts.md).

Edit config as the **same user** that runs the service:

```bash
mkdir -p ~/.config/tv-time-capsule
nano ~/.config/tv-time-capsule/config.json
```

Start from [`config.example.json`](../../config.example.json) if the file is missing. See [Configuration](configuration.md).

After adding files without rebooting: **hold R** on the show list to rescan, or from SSH:

```bash
tv-time-capsule --rescan-only
```

---

## 6. Kiosk mode (recommended daily use)

If you installed **Desktop**, switch to console kiosk so the GUI is not burning RAM while watching:

```bash
cd ~/tv-time-capsule   # or /opt/tv-time-capsule
./scripts/set-mode.sh kiosk --reboot
```

When you need Wi‑Fi UI / file manager:

```bash
./scripts/set-mode.sh desktop --reboot
# …tinker…
./scripts/set-mode.sh kiosk --reboot
```

Details: [Kiosk ↔ desktop](kiosk-desktop.md), [Autostart](autostart.md), [Networking](networking.md).

**Lite** installs (required on Pi 1 / original Zero) already boot to console; `install-pi.sh` enables the player service — a reboot is usually enough. There is no desktop mode on Lite; administer with [SSH](#24-connect-from-another-computer-ssh) and optional [web admin](web-admin.md).

---

## 7. Verify it works

1. Reboot: `sudo reboot`
2. You should see the TV Time Capsule UI on the HDMI/composite display.
3. From another machine (with admin enabled in config):

   ```text
   http://vintage-tv.local:8765/
   ```

4. Service health:

   ```bash
   sudo systemctl status tv-time-capsule
   sudo journalctl -u tv-time-capsule -f
   ```

5. Manual start (debugging):

   ```bash
   /opt/tv-time-capsule/.venv/bin/tv-time-capsule --media-dir=/media/usb
   ```

Controls: [Controls](controls.md). Common failures: [Troubleshooting](troubleshooting.md).

---

## 8. Day-to-day administration (SSH vs desktop vs web)

After install you have three ways to manage the box. Pick by task:

| Task | Best approach |
|------|----------------|
| Install, update, `journalctl`, edit config by hand | **SSH** from a laptop |
| Wi‑Fi GUI, file manager, USB drag-and-drop, Samba browse | **Desktop mode** on the Pi |
| Channel lineup, rescan, mounts, watch progress from the couch | **Web admin** on phone/laptop |
| Kids/parent mode, play, seek | Keyboard / gamepad on the TV |

### SSH (recommended for most admin)

Works in kiosk and desktop. From your laptop:

```bash
ssh YOUR_USER@vintage-tv.local

sudo systemctl status tv-time-capsule
sudo journalctl -u tv-time-capsule -f
nano ~/.config/tv-time-capsule/config.json
sudo systemctl restart tv-time-capsule
```

See [§2.4](#24-connect-from-another-computer-ssh) if you still need to find the host.

### Desktop mode (GUI on the TV or a monitor)

Use when you want the Raspberry Pi OS desktop (Wi‑Fi applet, file manager):

```bash
# From SSH or a local terminal on the Pi:
cd ~/tv-time-capsule   # or /opt/tv-time-capsule
./scripts/set-mode.sh desktop --reboot
```

After reboot you get a normal desktop login (auto-login if configured). When finished:

```bash
./scripts/set-mode.sh kiosk --reboot
```

Light alternative without leaving kiosk wiring: `sudo systemctl stop tv-time-capsule`, do your work, then `sudo systemctl start tv-time-capsule`. Full detail: [Kiosk ↔ desktop](kiosk-desktop.md).

### Web admin (phone or laptop browser)

No SSH and no desktop required — best for day-to-day library tweaks. Enable in config (`admin.enabled: true`) or launch with `--admin`, then open:

```text
http://vintage-tv.local:8765/
```

(or `http://<pi-ip>:8765/`). Guide: [Web admin](web-admin.md). Only enable on a trusted LAN (no login).

### Keyboard / gamepad on the TV

Needed for watching and for in-app menus (kids mode, help in parent mode). Not required for SSH-based install/updates once the network is up.

---

## 9. Suggested config by Pi class

Stock product defaults (native Weather, YouTube `prefer_cache`, Retro `cached`) are the target for Pi 2/3/4. Weaker boards should tighten YouTube:

| Hardware | YouTube | Weather | Retro TV |
|----------|---------|---------|----------|
| **Pi 1 / Zero** | `cached_only` (pre-fill cache if possible) | Keep **`native`**, or disable feature | Prefer **`cached`** or disable |
| **Zero 2 / Pi 2 / 3** | `prefer_cache` (default) | **`native`** | **`cached`** |
| **Pi 4 / 5** | `prefer_cache` or `live` | **`native`** or live `twc` / `ws4kp` | **`cached`** or `live` |

Pi 1 / Zero / Zero W must already be on **Legacy Lite 32-bit (Bookworm)** ([§1.2](#12-pi-1--original-zero--use-the-smallest-os)). On top of that, tighten YouTube so Chrome never starts for library play:

Example snippet for a Pi 1 / Zero:

```json
{
  "youtube": {
    "playback_mode": "cached_only",
    "cache": { "enabled": true, "download_when_idle": false }
  },
  "features": {
    "retro_tv": false
  }
}
```

Disable idle yt-dlp for one run: `tv-time-capsule --no-youtube-idle-cache`.

More: [Native weather & cached defaults](native-cached-defaults.md).

---

## 10. Device readiness & feature completeness

Assumptions: **kiosk / framebuffer** (not a loaded desktop), **USB or local media** preferred over flaky NFS, and **stock product defaults** — Weather `native`, YouTube `prefer_cache` + cache enabled, Retro TV `cached`. Live Chrome modes (`twc` / `ws4kp`, YouTube `live`, Retro `live`) are opt-in and dominate CPU/RAM.

**Cost drivers:** Chromium CDP screencast ≫ yt-dlp fills ≫ native pygame Weather / ffmpeg file play.

### Readiness by board

| Board (typical RAM) | Deploy ready? | Completeness @ defaults | Notes |
|---------------------|---------------|-------------------------|--------|
| **Pi 1 / Zero (512 MB)** | Conditional | **~55–65%** | **Require Legacy Lite 32-bit (Bookworm).** Browse + local video + native Weather if careful. yt-dlp fills are slow; concurrent Chrome is unrealistic. Prefer `youtube.playback_mode: cached_only`, USB media; consider `features.retro_tv: false` if the playlist oracle hurts. |
| **Zero 2 W (~1 GB)** | Yes, with care | **~75–85%** | Prefer Legacy Lite 64-bit. Closer to a weak Pi 3. Default stack usually works; avoid live Weather / YouTube / Retro. Idle cache fills OK but slow. |
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

### Rules of thumb

- **Browse UI, kids mode, dials, test patterns, screensaver** — fine on all Pi classes.
- **YouTube `live` / Retro `live` / Weather `twc`/`ws4kp`** — Chrome screencast; realistic on Pi 4+ (Weather screencast can limp on older boards via adapt).
- **Weather `native`** — pygame UI + NWS/Open-Meteo; **no Chromium**; **product default** on all platforms.
- **YouTube `cached_only` + Retro `cached`** — Chrome mostly avoided for playback (Retro still needs a light Chrome “oracle”); Pi 2/3 sweet spot for full features.
- **yt-dlp** runs on every device when cache is enabled; fills are slower on weak boards.

**Weather providers** (`weather.provider`): **`native` (default)**; `auto` → native; live opt-in `twc` / `ws4kp`. Switch with **Enter** on channel `004`. See [Native weather & cached defaults](native-cached-defaults.md).

**Offline YouTube workflow:** defaults enable `prefer_cache` + `youtube.cache.enabled`. Fill with idle downloads and/or `tv-time-capsule --youtube-cache-sync`. Use `cached_only` so weak devices never spawn Chrome for library playback.

**Decades (`1950`–`2009`):** default `retro_tv.playback_mode: cached`. Set `live` for full CDP screencast (Pi 4+).

---

## 11. Updating later

```bash
cd ~/tv-time-capsule          # your git checkout
git pull
./install-pi.sh               # re-copies into /opt and reinstalls the venv package
sudo systemctl restart tv-time-capsule
```

Or update only the installed tree after syncing into `/opt/tv-time-capsule`.

---

## 12. Display & runtime notes

- You need a **display** (HDMI or composite), not necessarily a full desktop session.
- Default kiosk uses SDL/pygame on the console framebuffer / KMS when possible.
- `--graphical` autostart waits for a desktop session and sets `DISPLAY=:0`.

See [Autostart & login](autostart.md), [Networking](networking.md), and [Troubleshooting](troubleshooting.md).

Related: [Native weather & cached defaults](native-cached-defaults.md), [Configuration](configuration.md), [offline YouTube plan](../development/pi-features-offline-youtube-plan.md).
