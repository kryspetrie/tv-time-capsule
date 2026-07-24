# TV Time Capsule

A child-friendly CRT media player for Raspberry Pi. Cable-TV style interface with channel numbers, single-show focus, and vintage TV aesthetics.

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

Or on a Raspberry Pi appliance:

```bash
./install-pi.sh
./scripts/set-mode.sh kiosk --reboot
```

Config lives at `~/.config/tv-time-capsule/config.json`. See [Getting started](docs/usage/getting-started.md) and [Configuration](docs/usage/configuration.md).

## License

[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/) — copy and adapt with attribution for non-commercial use. Full text in [LICENSE](LICENSE).
