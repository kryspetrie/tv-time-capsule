# Development setup

## Prerequisites

- Python 3.9+  
- [Poetry](https://python-poetry.org/) 2.x  
- ffmpeg (`ffprobe`, `ffplay`) on `PATH` — `./scripts/install-system-deps.sh`  

## Clone and install

```bash
git clone git@github.com:kryspetrie/tv-time-capsule.git
cd tv-time-capsule
poetry install
```

## Run

```bash
poetry run tv-time-capsule --media-dir ./media
poetry run tv-time-capsule --help
poetry run tv-time-capsule-secrets --help

# or:
poetry shell
tv-time-capsule --media-dir ./media
```

Use `--windowed` during development so the app does not take over the screen:

```bash
poetry run tv-time-capsule --windowed --media-dir sample/media-a
```

## Project layout (high level)

```
src/tv_time_capsule/   # installable package
scripts/               # Pi ops: autostart, networking, mounts, mode switch
docs/usage/            # operator documentation
docs/development/      # this tree
install-pi.sh          # appliance bootstrap
pyproject.toml         # Poetry + console scripts
```

## Useful checks

```bash
poetry check
poetry run python -m compileall -q src
poetry build
```

See [Architecture](architecture.md) and [Module map](modules.md).
