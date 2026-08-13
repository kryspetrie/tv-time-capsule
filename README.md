# TV Time Capsule

A child-friendly CRT media player for Raspberry Pi. Cable-TV style interface with channel numbers, single-show focus, and vintage TV aesthetics.

Optional **fun tweaks** (channel snow, analog glitches, screensaver) and **easter eggs** (press `001` / `002` / `003` for secret test patterns) — see [Fun tweaks & easter eggs](docs/usage/fun-tweaks-and-easter-eggs.md).

## Documentation

| | |
|--|--|
| **[Usage docs](docs/usage/README.md)** | Install, configure, Pi kiosk, mounts, networking, troubleshooting |
| **[Developer docs](docs/development/README.md)** | Architecture, modules, Poetry, scripts |
| **[Docs index](docs/README.md)** | Full table of contents |

## Quick start

```bash
# Installs ffmpeg and other prerequisites, then the app
./install.sh
tv-time-capsule --media-dir /path/to/media
```

Already have **ffmpeg** (`ffprobe`, `ffplay`) on your `PATH`? Skip straight to pipx:

```bash
pipx install git+ssh://git@github.com/kryspetrie/tv-time-capsule.git
```

**Raspberry Pi from scratch** (empty board → flash OS → install → kiosk), including
differences by Pi model (Pi 1 / Zero: **Legacy Lite 32-bit / Bookworm**):

→ **[Raspberry Pi — from empty board to TV](docs/usage/raspberry-pi.md)**

Short version once the OS is on the card and you have a git checkout on the Pi:

```bash
./install-pi.sh
./scripts/set-mode.sh kiosk --reboot
```

Config is loaded from the first match in the [search order](docs/usage/configuration.md#where-the-app-looks-for-configjson): `$TV_TIME_CAPSULE_CONFIG`, then `./config.json` in a dev checkout, then `~/.config/tv-time-capsule/config.json` when installed. Start from [`config.example.json`](config.example.json). See [Getting started](docs/usage/getting-started.md) (desktop) and [Configuration](docs/usage/configuration.md).

## License

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — copy and adapt with attribution for non-commercial use. Full text in [LICENSE](LICENSE).
