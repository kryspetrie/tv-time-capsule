# Reference: 240-MP-based Build

> **This is reference material, not setup instructions for this app.**
> It describes the [240-MP](https://github.com/anthonycaccese/240-mp)-based
> approach we're replicating — a different implementation of the same idea.
> The actual app in this repo is `tv_time_capsule.py`; see `README.md` to run it.

## Hardware You'll Need

| Item | Cost (used) | Notes |
|---|---|---|
| **Raspberry Pi 3B or 3B+** | ~$25–35 | Your 2011 Pi Model B won't work (32-bit, 256MB RAM, no HW decode) |
| **Micro-USB power supply (2.5A+)** | ~$8 | The Pi 3B draws more than your original Pi's supply |
| **8GB+ MicroSD card** | ~$7 | For the OS |
| **128GB USB flash drive** | ~$15 | For media (~160 episodes of Mister Rogers) |
| **3.5mm to RCA composite cable** | ~$2 | [Adafruit #2881](https://www.adafruit.com/product/2881) is verified working |
| **USB game controller** (optional) | ~$15–20 | 8BitDo Lite, NES-style, or any Xbox/PlayStation pad |
| **Your 14" CRT TV** | $0 | The star of the show |

> **Why not the original Pi Model B?** 240-MP requires a 64-bit OS (aarch64), 512MB+ RAM, and hardware H.264 decoding. The 2011 Pi has ARMv6, 256MB RAM, and no hardware video decoder. It can't run Qt6 or smoothly decode SD MP4s. A Pi 3B is the cheapest path that works and keeps the same GPIO header for your future big-button plans.

---

## Step 1: Flash the OS

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/):

1. Choose **Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)**
2. Click the gear icon to pre-configure:
   - Set hostname: `tvcapsule`
   - Set username/password
   - Configure WiFi
   - Enable SSH
3. Write to your SD card

---

## Step 2: Configure CRT Output

After writing, re-mount the SD card's boot partition and **replace** `config.txt` with:

```ini
# --- Global ---
disable_splash=1
disable_overscan=1
dtparam=audio=on

# Composite out to CRT
enable_tvout=1
sdtv_mode=0      # 0=NTSC (North America), 2=PAL (Europe)
sdtv_aspect=1    # 1=4:3

# --- Pi 3B ---
[pi3]
dtoverlay=vc4-fkms-v3d,cma=256
over_voltage=4
arm_freq=1300
core_freq=450
sdram_freq=500

# --- Pi 3B+ ---
[pi3+]
dtoverlay=vc4-fkms-v3d,cma=256
over_voltage=2
arm_freq=1500
core_freq=500
sdram_freq=500

[all]
```

> The composite cable wiring differs between Pi generations. If you're reusing a cable from your original Pi, test it — the 3.5mm TRRS pinout changed. The [Adafruit cable](https://www.adafruit.com/product/2881) is $2 and guaranteed correct.

---

## Step 3: Boot & Configure

```bash
# SSH into the Pi
ssh your-user@tvcapsule.local

# Enable auto-login and expand filesystem
sudo raspi-config
  → System Options → Auto Login → Yes
  → Advanced Options → Expand Filesystem → Yes
  → Finish → Reboot
```

---

## Step 4: Install 240-MP

```bash
bash <(curl -fsSL https://github.com/anthonycaccese/240-mp/releases/latest/download/install.sh)
```

When it asks **"Install systemd autostart service?"**, answer **Y** and enter your username.

This makes the Pi boot straight into 240-MP like an appliance — no desktop, no login, just TV.

---

## Step 5: Set Up the USB Drive

On your **computer** (not the Pi):

1. Format the USB drive as **exFAT** or **FAT32**
2. Create the folder structure:
   ```
   /Mister Rogers' Neighborhood/
   └── _episodes/
       ├── s01/
       │   ├── s01e01.mp4
       │   ├── s01e02.mp4
       │   └── ...
       ├── s02/
       └── ...
   ```
3. Add your episode files (organized by season)
4. Run the playlist generator (see below)
5. Plug the USB drive into the Pi

On the **Pi**, auto-mount the drive:

```bash
# Install exFAT support
sudo apt-get install -y exfat-fuse exfat-progs

# Create mount point
sudo mkdir -p /media/usb

# Find your USB drive
lsblk
# Usually /dev/sda1

# Add to fstab for auto-mount on boot
echo '/dev/sda1 /media/usb auto defaults,nofail 0 0' | sudo tee -a /etc/fstab

# Mount it now
sudo mount /dev/sda1 /media/usb
```

---

## Step 6: Generate Playlists

From your **computer**, after organizing episodes on the USB drive:

```bash
# Make the script executable, then point it at the mounted USB drive
chmod +x generate-playlists.sh
./generate-playlists.sh /Volumes/YOUR_USB_DRIVE_NAME   # macOS
# or
./generate-playlists.sh /media/usb                      # Pi via SSH
```

This creates `! Season 01.m3u8`, `! Season 02.m3u8`, etc. in each show folder.

---

## Step 7: Apply the Child-Friendly Config

```bash
mkdir -p ~/.local/share/240-MP
```

Create `~/.local/share/240-MP/config.json` with:

```json
{
  "app": {
    "color_scheme": "Video 1"
  },
  "modules": {
    "com.240mp.local_files": {
      "enabled": true,
      "media_directory": "/media/usb",
      "resume_playback": "yes",
      "shuffle_playback": "no",
      "loop_playback": "OFF",
      "hide_extensions": "ON",
      "auto_subtitles": "forced",
      "sub_lang": "-",
      "image_duration": "5"
    }
  }
}
```

### Why these settings matter

| Setting | Value | Child UX Impact |
|---|---|---|
| `resume_playback` | `"yes"` | **No overlay dialog.** Pick a season → immediately resumes where left off. No reading required. |
| `shuffle_playback` | `"no"` | **No overlay dialog.** Never asks "Play in order?" vs "Shuffle?" — always sequential. |
| `loop_playback` | `"OFF"` | Returns to menu when season finishes. Use `"ON"` for comfort-loop mode. |
| `hide_extensions` | `"ON"` | Shows `! SEASON 01` instead of `! SEASON 01.M3U8`. Cleaner on CRT. |
| `auto_subtitles` | `"forced"` | Only shows subtitles for forced/foreign segments. |

> **Critical:** `resume_playback: "yes"` + `shuffle_playback: "no"` eliminates ALL choice overlays. A child selects a season and playback starts immediately — no reading, no decisions.

---

## The Complete Child Flow

```
Power on → 240-MP boots automatically
    ↓
"LOCAL FILES" module is the only option (or auto-selected)
    ↓
Select it (1 press of A or Enter)
    ↓
Show list: "MISTER ROGERS' NEIGHBORHOOD"
    ↓
Select it (1 press)
    ↓
Season list:
  ▸ ! SEASON 01       ← always at top (! sorts first)
  ▸ ! SEASON 02
  ▸ ! SEASON 03
  ▸ _EPISODES          ← can be ignored
    ↓
Select a season (1 press)
    ↓
Episodes play sequentially, auto-advancing
    ↓
When stopped → position saved automatically
    ↓
Next time: picks up at the exact episode + time
```

**3 button presses from boot to watching. No reading. No choices.**

---

## Controls Reference

### Game Controller

| Button | In Menu | During Playback |
|---|---|---|
| D-pad ↑↓ | Navigate list | Seek ±10s |
| A (south) | Select | — |
| B (east) | Go back | — |
| Start | — | Play / Pause |

### Keyboard

| Key | In Menu | During Playback |
|---|---|---|
| ↑↓ | Navigate list | Seek ±1 min |
| Enter | Select | — |
| Esc / Backspace | Go back | — |
| Space | — | Play / Pause |
| ←→ | — | Seek ±5s |

---

## Adding More Shows

To add another show, create the same structure on the USB drive:

```
/media/usb/
├── Mister Rogers' Neighborhood/
│   ├── ! Season 01.m3u8
│   ├── ! Season 02.m3u8
│   └── _episodes/
│       ├── s01/
│       └── s02/
├── Sesame Street/
│   ├── ! Season 01.m3u8
│   └── _episodes/
│       └── s01/
└── Reading Rainbow/
    ├── ! Season 01.m3u8
    └── _episodes/
        └── s01/
```

Then re-run `generate-playlists.sh` and the new shows appear automatically.

---

## Troubleshooting

### Audio is too quiet through CRT
```bash
amixer sset PCM 100%
sudo alsactl store
```

### Video stutters on Pi 3B
Ensure you're playing SD (480i) content. 720p plays fine; 1080p may stutter. The Pi 3B's hardware H.264 decoder handles standard definition smoothly.

### Want to access the Pi terminal while 240-MP is running
- SSH in from another computer: `ssh your-user@tvcapsule.local`
- Or from 240-MP: the Quit menu has "Exit to Terminal"

### Composite output is black and white
This usually means the wrong composite cable pinout. The Pi 3B/3B+ uses a specific TRRS assignment. Get the [Adafruit cable](https://www.adafruit.com/product/2881).

### Want to temporarily stop autostart
```bash
sudo systemctl disable 240mp.service
# To re-enable:
sudo systemctl enable 240mp.service
```

---

## Future: GPIO Big Buttons (MVP+2)

The GPIO header on the Pi 3B is identical to your original Model B. Once the MVP is working, you can wire arcade buttons:

| GPIO Pin | Button | Function |
|---|---|---|
| GPIO 2 | Big Green Button | Select / Play-Pause |
| GPIO 3 | Big Red Button | Back |
| GPIO 4 | Big Blue Button (Up) | Navigate Up |
| GPIO 17 | Big Yellow Button (Down) | Navigate Down |

A Python daemon reads GPIO events and injects keyboard events via `uinput`. Since 240-MP only sees keyboard input, this works seamlessly — no app modifications needed.

---

## Future: NFC Cards (MVP+1)

240-MP has a built-in NFC Reader module. With a $15 ACS ACR122U reader:

1. Write an NFC card mapped to `! Season 01.m3u8`
2. Child taps the card on the reader
3. 240-MP starts playing immediately

This is the ultimate child interface: physical cards with show pictures that start episodes with a tap.