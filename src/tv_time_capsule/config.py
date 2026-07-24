"""Paths, display constants, and config file helpers."""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MEDIA_ROOT = "/media/usb"
STATE_DIR = os.path.expanduser("~/.local/share/tv-time-capsule")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
CONFIG_DIR = os.path.expanduser("~/.config/tv-time-capsule")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Virtual canvas: 640x480 is a true 4:3 frame with square pixels, matching
# the aspect ratio of a CRT television.
SCREEN_W = 640
SCREEN_H = 480

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".m4v",
    ".webm",
    ".wmv",
    ".flv",
    ".f4v",
    ".mpg",
    ".mpeg",
    ".vob",
}

# Channel number: type digits, after timeout -> jump to channel
CHANNEL_TIMEOUT_MS = 1500
CHANNEL_FLASH_MS = 800
CHANNEL_ERROR_MS = 1500
CHANNEL_PENDING_MS = 500

# How many items visible in the season/episode stack
STACK_VISIBLE = 4

# Overlay display durations
OVERLAY_SHOW_MS = 3000
PROGRESS_SEEK_S = 10

# Truncated list titles: pause, then scroll back and forth
MARQUEE_DELAY_MS = 900
MARQUEE_SPEED_PX_S = 40
MARQUEE_END_PAUSE_MS = 700

# Ignore leftover KEYDOWNs from the play-start key (held during splash)
PLAY_INPUT_GRACE_MS = 350


class C:
    """Vintage TV palette (white/blue primary, green overlays)."""

    # Background
    BG = (8, 14, 28)
    BG_CARD = (18, 28, 52)
    BG_CARD_SEL = (30, 60, 120)
    BG_FOOTER = (6, 10, 22)
    BG_HEADER = (12, 20, 38)

    # Text
    WHITE = (230, 235, 245)
    BRIGHT = (255, 255, 255)
    BLUE = (80, 150, 240)
    CYAN = (60, 200, 220)
    DIM = (90, 110, 140)
    DARK_DIM = (45, 55, 75)

    # Overlays (green — like CRT on-screen displays)
    GREEN = (50, 220, 100)
    GREEN_DIM = (25, 80, 45)
    GREEN_BG = (0, 15, 8, 200)
    OVERLAY_BG = (0, 0, 0, 180)

    # Misc
    BLACK = (0, 0, 0)
    SCANLINE = (0, 0, 0, 28)
    NOW_PLAYING = (255, 210, 80)
    WATCHED = (60, 80, 100)
    NEXT_UP = (40, 100, 60)


def _default_config() -> dict[str, Any]:
    return {
        "media_paths": [DEFAULT_MEDIA_ROOT],
        "mounts": [],
    }


def load_config() -> dict[str, Any]:
    """Load config from ~/.config/tv-time-capsule/config.json.

    Returns dict with:
      - media_paths: list[str]
      - mounts: list[dict]  (optional remote CIFS/NFS/SSHFS/FTP mounts)
    """
    default = _default_config()
    if not os.path.isfile(CONFIG_FILE):
        return default
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        paths = cfg.get("media_paths") or []
        if not paths:
            paths = list(default["media_paths"])
        mounts = cfg.get("mounts") or []
        if not isinstance(mounts, list):
            mounts = []
        # Expand ~ in media paths; keep entries even if not mounted yet
        expanded = [os.path.expanduser(os.path.expandvars(p)) for p in paths]
        return {"media_paths": expanded, "mounts": mounts}
    except (json.JSONDecodeError, OSError):
        return default


def save_default_config() -> None:
    """Write a default config file if none exists."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(_default_config(), f, indent=2)
            f.write("\n")
