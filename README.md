# TV Time Capsule

A child-friendly CRT media player for Raspberry Pi. Cable-TV style interface with channel numbers, single-show focus, and vintage TV aesthetics.

## Quick Start (macOS / Linux desktop)

Requires **ffmpeg** (with `ffprobe` and `ffplay`) on your `PATH`:
`brew install ffmpeg` (macOS) or `sudo apt install ffmpeg` (Linux).

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run with sample media (test mode)
python tv_time_capsule.py --test

# Run with your own media (always fullscreen)
python tv_time_capsule.py --media-dir /path/to/media

# Force 4:3 aspect ratio for CRT TVs
python tv_time_capsule.py --media-dir /path/to/media --force-43
```

## Controls

| Key | Action |
|-----|--------|
| ↑ / ↓ | Browse up/down |
| → / Enter | Select / Play |
| ← / Esc | Back / Stop |
| 0–9 | Type channel number (auto-commits after 1.5s) |
| H | Show help / controls screen |
| Tab | Key configuration |
| Q | Quit |

### During playback

| Key | Action |
|-----|--------|
| ↑ / ↓ | Volume up / down |
| ← / → | Seek back / forward 10s |
| Space / Enter | Pause / resume |
| Esc | Stop and return to menu |

## Media folder structure

Organize your shows under a media directory:

```
media/
  Bluey/
    thumbnail.png
    s01/
      s01e01 - Dancing.mp4
      s01e02 - Swimming.mp4
      s01e01.png          ← episode thumbnail
    s01.png               ← season thumbnail
  Sesame Street/
    thumbnail.png
    s01e01 - Big Bird.mp4
    s01e02 - Big Bird.mp4
```

Supported structures:
1. **Flat**: `Show/01.mp4, 02.mp4, ...`
2. **Named flat**: `Show/s01e01 - Name.mp4, ...`
3. **Season folders**: `Show/s01/01.mp4, ...`
4. **Season folders + names**: `Show/s01/s01e01 - Name.mp4, ...`

## Raspberry Pi setup

See `install-pi.sh` for automated Pi setup (installs pygame, omxplayer, configures autostart).

## License

MIT