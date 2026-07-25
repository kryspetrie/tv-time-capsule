"""Paths, display constants, and config file helpers."""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MEDIA_ROOT = "/media/usb"
STATE_DIR = os.path.expanduser("~/.local/share/tv-time-capsule")
STATE_FILE = os.path.join(STATE_DIR, "state.json")


def user_config_dir() -> str:
    """XDG config directory for tv-time-capsule (secrets, credentials)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "tv-time-capsule")


# Credentials, temp CIFS cred files, etc. — always under the user config dir.
CONFIG_DIR = user_config_dir()

_active_config_path: str | None = None


def dev_repo_root() -> str | None:
    """Return the git checkout root when running from an editable/local install."""
    path = os.path.dirname(os.path.abspath(__file__))
    for _ in range(12):
        if os.path.isfile(os.path.join(path, "pyproject.toml")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None


def config_search_paths() -> list[str]:
    """Ordered list of config.json paths to try (first match wins)."""
    paths: list[str] = []

    env = os.environ.get("TV_TIME_CAPSULE_CONFIG")
    if env:
        paths.append(os.path.expanduser(env))

    repo = dev_repo_root()
    if repo:
        repo_config = os.path.join(repo, "config.json")
        if repo_config not in paths:
            paths.append(repo_config)

    xdg_config = os.path.join(user_config_dir(), "config.json")
    if xdg_config not in paths:
        paths.append(xdg_config)

    return paths


def default_config_file() -> str:
    """Path used when creating a new config (dev checkout vs installed app)."""
    repo = dev_repo_root()
    if repo:
        return os.path.join(repo, "config.json")
    return os.path.join(user_config_dir(), "config.json")


def resolve_config_file() -> str:
    """Return the config file to load, or the default path if none exists yet."""
    for path in config_search_paths():
        if os.path.isfile(path):
            return path
    return default_config_file()


def config_file() -> str:
    """Active config path (resolved on first use)."""
    global _active_config_path
    if _active_config_path is None:
        _active_config_path = resolve_config_file()
    return _active_config_path


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
STACK_VISIBLE = 5

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
        "keymap": {},
        "screensaver": {
            "enabled": False,
            "timeout_seconds": 300,
        },
    }


def _parse_config(raw: dict[str, Any]) -> dict[str, Any]:
    default = _default_config()
    paths = raw.get("media_paths") or []
    if not paths:
        paths = list(default["media_paths"])
    mounts = raw.get("mounts") or []
    if not isinstance(mounts, list):
        mounts = []
    keymap = raw.get("keymap") or {}
    if not isinstance(keymap, dict):
        keymap = {}
    expanded = [os.path.expanduser(os.path.expandvars(p)) for p in paths]
    screensaver = raw.get("screensaver") or {}
    if not isinstance(screensaver, dict):
        screensaver = {}
    try:
        timeout_s = int(screensaver.get("timeout_seconds", 300))
    except (TypeError, ValueError):
        timeout_s = 300
    timeout_s = max(10, timeout_s)
    return {
        "media_paths": expanded,
        "mounts": mounts,
        "keymap": keymap,
        "screensaver": {
            "enabled": bool(screensaver.get("enabled", False)),
            "timeout_seconds": timeout_s,
        },
    }


def load_config() -> dict[str, Any]:
    """Load config from the first existing file in :func:`config_search_paths`.

    Returns dict with:
      - media_paths: list[str]
      - mounts: list[dict]  (optional remote CIFS/NFS/SSHFS/FTP mounts)
      - keymap: dict[str, int]  (optional custom key bindings)
      - screensaver: dict with enabled (bool) and timeout_seconds (int)
    """
    global _active_config_path
    default = _default_config()

    for path in config_search_paths():
        if not os.path.isfile(path):
            continue
        _active_config_path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                return _parse_config(json.load(f))
        except (json.JSONDecodeError, OSError):
            return default

    _active_config_path = default_config_file()
    return default


def save_config(cfg: dict[str, Any], path: str | None = None) -> None:
    """Write config to the active config file (or ``path`` if given)."""
    global _active_config_path
    dest = path or config_file()
    _active_config_path = dest
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def save_default_config() -> None:
    """Write a default config file if none exists in the search path."""
    if any(os.path.isfile(p) for p in config_search_paths()):
        return
    save_config(_default_config(), path=default_config_file())
