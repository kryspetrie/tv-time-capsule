# Getting started

## Requirements

- Python 3.9+
- **ffmpeg** with `ffprobe` and `ffplay` on your `PATH`

You don't need to install these by hand — both installers do it for you.

## Install everything (recommended)

From a checkout, this installs system prerequisites and the app in one step:

```bash
./install.sh            # macOS, Debian/Ubuntu, Fedora, Arch
./install.sh --from-git # pull the app from GitHub instead of the local checkout
./install.sh --venv     # install into ./.venv instead of pipx
```

On a Raspberry Pi appliance use [`install-pi.sh`](raspberry-pi.md) instead — it does the same
plus kiosk, mounts, and autostart wiring.

## System prerequisites only

```bash
./scripts/install-system-deps.sh
```

Installs **ffmpeg** (required) and tries optional packages (remote mounts, keyring, NetworkManager). The player runs without the optionals and logs a skip message if a configured feature needs a missing tool.

Manual equivalent if you prefer: `brew install ffmpeg` / `sudo apt install ffmpeg`.

On Raspberry Pi, see also [Raspberry Pi setup](raspberry-pi.md).

## Install (pipx only)

If prerequisites are already present:

```bash
# From GitHub (SSH)
pipx install git+ssh://git@github.com/kryspetrie/tv-time-capsule.git

# From GitHub (HTTPS)
pipx install git+https://github.com/kryspetrie/tv-time-capsule.git

# From a local checkout
pipx install /path/to/tv-time-capsule
```

Upgrade:

```bash
pipx upgrade tv-time-capsule
# or force reinstall from git:
pipx install --force git+ssh://git@github.com/kryspetrie/tv-time-capsule.git
```

## First run

With no flags, the app loads the first matching config file (see [Configuration](configuration.md#where-the-app-looks-for-configjson)) and scans `media_paths`:

```bash
tv-time-capsule
```

For a full starting point — media folders, network mounts, key bindings — copy the repo example:

```bash
# Development (repo root — picked up automatically):
cp config.example.json config.json

# Installed app (pipx / production):
mkdir -p ~/.config/tv-time-capsule
cp config.example.json ~/.config/tv-time-capsule/config.json
```

Edit paths and remove mount blocks you do not need. See [Configuration](configuration.md#where-the-app-looks-for-configjson).

Override media directories for one run (repeatable):

```bash
tv-time-capsule --media-dir /path/to/media
tv-time-capsule --media-dir /usb/shows --media-dir ~/Videos/kids
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--media-dir DIR` | Scan this directory (repeatable). Overrides config paths for this run. |
| `--windowed` | Run in a window instead of fullscreen (handy for testing) |
| `--force-43` | Kept for compatibility; 4:3 letterboxing is always on |
| `--scanlines` | **Fun tweak** — CRT scanline overlay |
| `--channel-snow` | **Fun tweak** — B&W static burst when committing channel numbers |
| `--shutdown-collapse` | **Fun tweak** — CRT vertical collapse on quit |
| `--analog-artifacts` | **Fun tweak** — random glitches on the show browser |
| `--analog-artifact-rate N` | Glitches per minute with `--analog-artifacts` (default: config or 12) |
| `--safe-zone PCT` | CRT overscan safe zone — uniform inset % on all sides (0–25) |
| `--skip-mounts` | Do not mount remote shares from config |
| `--screensaver` | **Fun tweak** — VHS logo screensaver after idle timeout |
| `--screensaver-timeout SEC` | Idle seconds before screensaver (overrides config) |
| `--admin` | Web admin UI at http://127.0.0.1:8765/ (see [Web admin](web-admin.md)) |
| `--admin-port PORT` | Port for `--admin` (default 8765) |

CRT polish and hidden test patterns: [Fun tweaks & easter eggs](fun-tweaks-and-easter-eggs.md).

## Display behaviour

The UI is drawn to a fixed **640×480** canvas (true 4:3 with square pixels) and
SDL/`pygame.SCALED` GPU-scales it to the real display, letterboxing on widescreen
outputs. That keeps the CRT aspect correct and avoids a per-frame CPU upscale
to 4K.

Fullscreen is borderless at your existing video mode (`FULLSCREEN | SCALED`),
so it never changes monitor resolution or disturbs desktop scaling.
`--windowed` opens a scaled window at the same logical resolution.

## What happens on startup

1. Load config (unless you only care about CLI paths)  
2. Mount any configured remote shares (unless `--skip-mounts`)  
3. Discover shows under media paths (+ mountpoints)  
4. Open the pygame UI  

If no shows are found, the process exits with a short message pointing at the config file.

## Next steps

- Organize files: [Media library layout](media-library.md)  
- Persist paths and mounts: [Configuration](configuration.md)  
- Raspberry Pi appliance: [Raspberry Pi setup](raspberry-pi.md) and [Kiosk ↔ desktop](kiosk-desktop.md)
