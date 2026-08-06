"""Paths, display constants, and config file helpers."""

from __future__ import annotations

import json
import os
from typing import Any

from .safe_zone import parse_safe_zone, parse_safe_zone_offset, safe_zone_to_config

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

# Default OS window (windowed mode): fixed 4:3, independent of safe-zone framebuffer.
WINDOW_DEFAULT_W = 800
WINDOW_DEFAULT_H = 600
WINDOW_MIN_W = 400
WINDOW_MIN_H = 300
# Integer multiples of SCREEN_W×SCREEN_H via --scale (windowed testing).
WINDOW_SCALE_MIN = 2
WINDOW_SCALE_MAX = 6

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

AUTOPLAY_MODES = ("off", "next_episode", "next_in_season_only")
CHANNEL_FX_MODES = ("off", "visual", "visual+audio")
HW_DECODE_MODES = ("auto", "on", "off")
_PLAYBACK_CACHE_DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024


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
    NOW_PLAYING = (255, 210, 80)
    WATCHED = (60, 80, 100)
    NEXT_UP = (18, 55, 32)
    NEXT_UP_BORDER = (50, 220, 100)


def _parse_playback(raw: dict | None) -> dict[str, Any]:
    pb = raw or {}
    if not isinstance(pb, dict):
        pb = {}
    mode = str(pb.get("autoplay", "next_in_season_only")).lower()
    if mode not in AUTOPLAY_MODES:
        mode = "next_in_season_only"
    try:
        countdown = int(pb.get("autoplay_countdown_seconds", 5))
    except (TypeError, ValueError):
        countdown = 5
    countdown = max(0, min(30, countdown))
    now_playing_splash = bool(pb.get("now_playing_splash", True))
    try:
        splash_seconds = float(pb.get("now_playing_splash_seconds", 1.5))
    except (TypeError, ValueError):
        splash_seconds = 1.5
    splash_seconds = max(0.0, min(30.0, splash_seconds))
    hw = str(pb.get("hw_decode", "auto")).lower()
    if hw not in HW_DECODE_MODES:
        hw = "auto"
    return {
        "autoplay": mode,
        "autoplay_countdown_seconds": countdown,
        "now_playing_splash": now_playing_splash,
        "now_playing_splash_seconds": splash_seconds,
        "hw_decode": hw,
    }


def _parse_ui(raw: dict | None) -> dict[str, Any]:
    ui = raw or {}
    if not isinstance(ui, dict):
        ui = {}
    defaults = _default_config()["ui"]
    legacy = str(ui.get("channel_change_effects", "off")).lower()
    channel_snow = bool(ui.get("channel_snow", defaults["channel_snow"]))
    shutdown_collapse = bool(ui.get("shutdown_collapse", defaults["shutdown_collapse"]))
    if "channel_snow_audio" in ui:
        channel_snow_audio = bool(ui.get("channel_snow_audio"))
    else:
        channel_snow_audio = channel_snow
    if legacy in CHANNEL_FX_MODES and legacy != "off":
        if "channel_snow" not in ui:
            channel_snow = True
        if legacy == "visual+audio":
            channel_snow_audio = True
    analog_artifacts = bool(ui.get("analog_artifacts", defaults["analog_artifacts"]))
    footer_hints = bool(ui.get("footer_hints", defaults["footer_hints"]))
    try:
        analog_rate = float(ui.get("analog_artifact_rate", 12))
    except (TypeError, ValueError):
        analog_rate = 12.0
    analog_rate = max(0.0, min(60.0, analog_rate))
    safe_zone = parse_safe_zone(ui.get("safe_zone", defaults["safe_zone"]))
    raw_sz = ui.get("safe_zone")
    safe_zone_offset = parse_safe_zone_offset(raw_sz if isinstance(raw_sz, dict) else None)
    return {
        "channel_snow": channel_snow,
        "shutdown_collapse": shutdown_collapse,
        "channel_snow_audio": channel_snow_audio,
        "analog_artifacts": analog_artifacts,
        "analog_artifact_rate": analog_rate,
        "footer_hints": footer_hints,
        "safe_zone": safe_zone_to_config(safe_zone, safe_zone_offset),
    }


def _parse_gamepad(raw: dict | None) -> dict[str, Any]:
    gp = raw or {}
    if not isinstance(gp, dict):
        gp = {}
    bindings = gp.get("bindings") or {}
    if not isinstance(bindings, dict):
        bindings = {}
    return {"enabled": bool(gp.get("enabled", True)), "bindings": bindings}


def _parse_channels(raw: dict | None) -> dict[str, Any]:
    ch = raw or {}
    if not isinstance(ch, dict):
        ch = {}
    order = ch.get("order") or []
    if not isinstance(order, list):
        order = []
    numbers = ch.get("numbers") or {}
    if not isinstance(numbers, dict):
        numbers = {}
    return {
        "order": [str(n) for n in order],
        "numbers": numbers,
    }


def _parse_kids_mode(raw: dict | None) -> dict[str, Any]:
    km = raw or {}
    if not isinstance(km, dict):
        km = {}
    out: dict[str, Any] = {
        "default_enabled": bool(km.get("default_enabled", False)),
        "interleave_shows_movies": bool(km.get("interleave_shows_movies", False)),
        "browse_style": str(km.get("browse_style", "card")),
        "enabled": km.get("enabled"),
    }
    if "allowlist" in km:
        al = km.get("allowlist")
        if not isinstance(al, dict):
            al = {}
        shows = al.get("shows") or []
        movies = al.get("movies") or []
        if not isinstance(shows, list):
            shows = []
        if not isinstance(movies, list):
            movies = []
        out["allowlist"] = {
            "shows": [str(s) for s in shows],
            "movies": [str(m) for m in movies],
        }
    return out


def _parse_network(raw: dict | None) -> dict[str, Any]:
    net = raw or {}
    if not isinstance(net, dict):
        net = {}
    hostname = str(net.get("mdns_hostname", "vintage-tv")).strip() or "vintage-tv"
    try:
        port = int(net.get("admin_port", 8765))
    except (TypeError, ValueError):
        port = 8765
    port = max(1024, min(65535, port))
    return {
        "mdns_hostname": hostname,
        "admin_port": port,
    }


def _parse_library(raw: dict | None) -> dict[str, Any]:
    lib = raw or {}
    if not isinstance(lib, dict):
        lib = {}
    try:
        interval = int(lib.get("rescan_interval_seconds", 0))
    except (TypeError, ValueError):
        interval = 0
    interval = max(0, interval)
    try:
        long_press = int(lib.get("rescan_long_press_ms", 800))
    except (TypeError, ValueError):
        long_press = 800
    long_press = max(300, min(3000, long_press))
    return {
        "rescan_interval_seconds": interval,
        "rescan_long_press_ms": long_press,
    }


def _parse_cache(raw: dict | None) -> dict[str, Any]:
    cache = raw or {}
    if not isinstance(cache, dict):
        cache = {}
    try:
        max_bytes = int(cache.get("max_bytes", _PLAYBACK_CACHE_DEFAULT_MAX_BYTES))
    except (TypeError, ValueError):
        max_bytes = _PLAYBACK_CACHE_DEFAULT_MAX_BYTES
    max_bytes = max(64 * 1024 * 1024, max_bytes)
    directory = cache.get("directory")
    if directory is not None:
        directory = str(directory).strip() or None
    return {
        "enabled": bool(cache.get("enabled", True)),
        "directory": directory,
        "max_bytes": max_bytes,
        "prefetch_next": bool(cache.get("prefetch_next", True)),
        "cache_before_playing": bool(cache.get("cache_before_playing", False)),
    }


def _parse_accessibility(raw: dict | None) -> dict[str, Any]:
    acc = raw or {}
    if not isinstance(acc, dict):
        acc = {}
    defaults = _default_config()["accessibility"]
    return {
        "large_text": bool(acc.get("large_text", defaults["large_text"])),
        "high_contrast": bool(acc.get("high_contrast", defaults["high_contrast"])),
        "play_all_unwatched": bool(acc.get("play_all_unwatched", defaults["play_all_unwatched"])),
    }


def _parse_weather(raw: dict | None) -> dict[str, Any]:
    """Optional forecast location for the weather channel (004).

    Prefer ``latitude``/``longitude`` when both are set; otherwise ``zip`` or
    a free-text ``query`` (city name) is geocoded via weather.com.  Empty
    config leaves location to weather.com server geo / browser default.
    """
    weather = raw or {}
    if not isinstance(weather, dict):
        weather = {}
    defaults = _default_config()["weather"]

    def _opt_str(key: str) -> str | None:
        val = weather.get(key, defaults.get(key))
        if val is None:
            return None
        text = str(val).strip()
        return text or None

    lat = weather.get("latitude", defaults.get("latitude"))
    lon = weather.get("longitude", defaults.get("longitude"))
    try:
        latitude = float(lat) if lat is not None and str(lat).strip() != "" else None
    except (TypeError, ValueError):
        latitude = None
    try:
        longitude = float(lon) if lon is not None and str(lon).strip() != "" else None
    except (TypeError, ValueError):
        longitude = None
    # Both or neither — partial pairs are ignored.
    if latitude is None or longitude is None:
        latitude = None
        longitude = None

    return {
        "zip": _opt_str("zip"),
        "query": _opt_str("query"),
        "name": _opt_str("name"),
        "latitude": latitude,
        "longitude": longitude,
    }


def _parse_retro_tv(raw: dict | None) -> dict[str, Any]:
    """MyRetroTVs decade-stream preferences (channel-type filters).

    ``filters`` maps checkbox ids (``box_c``, ``box_s``, …) to enabled flags.
    ``null`` / omitted means “use the site default” (typically all on) until
    the user changes them in the in-app menu.
    """
    retro = raw or {}
    if not isinstance(retro, dict):
        retro = {}
    defaults = _default_config()["retro_tv"]
    filters_raw = retro.get("filters", defaults.get("filters"))
    filters: dict[str, bool] | None
    if filters_raw is None:
        filters = None
    elif isinstance(filters_raw, dict):
        filters = {}
        for key, val in filters_raw.items():
            kid = str(key).strip()
            if not kid.startswith("box_"):
                # Allow bare letters from older notes → normalize to box_*
                if len(kid) == 1 and kid.isalpha():
                    kid = f"box_{kid.lower()}"
                else:
                    continue
            filters[kid] = bool(val)
        if not filters:
            filters = None
    elif isinstance(filters_raw, list):
        # Enabled-id list form: ["box_c", "box_m"]
        filters = {}
        for item in filters_raw:
            kid = str(item).strip()
            if len(kid) == 1 and kid.isalpha():
                kid = f"box_{kid.lower()}"
            if kid.startswith("box_"):
                filters[kid] = True
        if not filters:
            filters = None
    else:
        filters = None

    volume = retro.get("volume", defaults.get("volume"))
    try:
        volume_i = int(volume) if volume is not None else None
    except (TypeError, ValueError):
        volume_i = None
    if volume_i is not None:
        volume_i = max(0, min(100, volume_i))

    return {
        "filters": filters,
        "volume": volume_i,
    }


def _parse_youtube_channels(raw: list | None) -> list[dict[str, Any]]:
    """YouTube channels/playlists listed as virtual shows.

    Each entry needs ``handle`` (``@name``) and/or ``url`` (channel URL,
    ``/channel/UC…``, or a playlist / watch?list= URL). Optional ``title``
    overrides the show name. Set ``playlists_as_shows`` to unroll public
    playlists (except All Videos) into distinct shows. Dial numbers use the
    same ``channels.order`` / ``channels.numbers`` path as local shows (web
    admin); optional ``channel`` on an entry is still accepted as a convenience
    merge into numbers.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        url = item.get("url")
        handle_s = str(handle).strip() if handle is not None else ""
        url_s = str(url).strip() if url is not None else ""
        if not handle_s and not url_s:
            continue
        if handle_s and not handle_s.startswith("@") and not handle_s.startswith("UC"):
            # Bare name → @handle
            if "/" not in handle_s and " " not in handle_s:
                handle_s = f"@{handle_s}"
        title = item.get("title")
        title_s = str(title).strip() if title is not None else ""
        channel_num = item.get("channel")
        try:
            channel_i = int(channel_num) if channel_num is not None else None
        except (TypeError, ValueError):
            channel_i = None
        if channel_i is not None and channel_i < 1:
            channel_i = None
        entry: dict[str, Any] = {}
        if handle_s:
            entry["handle"] = handle_s
        if url_s:
            entry["url"] = url_s
        if title_s:
            entry["title"] = title_s
        if channel_i is not None:
            entry["channel"] = channel_i
        if bool(item.get("playlists_as_shows")):
            entry["playlists_as_shows"] = True
            # When unrolling playlists, skip the mega "All Videos" channel show
            # unless the user explicitly keeps it.
            if "include_all_videos" in item:
                entry["include_all_videos"] = bool(item.get("include_all_videos"))
            else:
                entry["include_all_videos"] = False
        elif "include_all_videos" in item:
            entry["include_all_videos"] = bool(item.get("include_all_videos"))
        out.append(entry)
    return out


def _default_youtube_channels() -> list[dict[str, Any]]:
    """Kids / classic YouTube shows preloaded in the example and default config."""
    return [
        {"url": "https://www.youtube.com/@msrachel/", "title": "Ms Rachel"},
        {"url": "https://www.youtube.com/@BlueyOfficialChannel", "title": "Bluey"},
        {
            "url": "https://www.youtube.com/@MisterRogersNeighborhood",
            "title": "Mister Rogers' Neighborhood",
        },
        {"url": "https://www.youtube.com/@Raffi", "title": "Raffi"},
        {"url": "https://www.youtube.com/@SciShowKids", "title": "SciShow Kids"},
        {"url": "https://www.youtube.com/@PBSKIDS", "title": "PBS KIDS"},
        {
            "url": "https://www.youtube.com/channel/UCOXkrXRpNfUu6mypF7NZxnA",
            "title": "Ms Moni",
        },
        {
            "url": "https://www.youtube.com/@thomasandfriends",
            "title": "Thomas & Friends",
        },
        {
            "url": "https://www.youtube.com/@BillNyeTheScienceGuyHD/",
            "title": "Bill Nye the Science Guy",
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=yzPeIKhMUOU"
                "&list=PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ"
            ),
            "title": "Beakman's World",
        },
        {
            "url": "https://www.youtube.com/@ReadingRainbowOfficial",
            "title": "Reading Rainbow",
        },
        {"url": "https://www.youtube.com/@SesameStreet", "title": "Sesame Street"},
        {
            "url": (
                "https://www.youtube.com/watch?v=-rJ0nxLQ8wU"
                "&list=PLCeScks4FrgKF4Vp8-1C4OWbgJrn5BbkW"
            ),
            "title": "The Magic School Bus",
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=dcBNHNs6TdY"
                "&list=PLCeScks4FrgJTUTbM19xR52SM1ss3I65U"
            ),
            "title": "Clifford the Big Red Dog",
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=2ptL3fim9Uw"
                "&list=PLCeScks4FrgKPU26Y3gZeLTIdqK6ZggYg"
            ),
            "title": "Animorphs",
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=WHIod8ulH3E"
                "&list=PLCeScks4FrgIg0_AKYL2UiAJRH6jiGWJ_"
            ),
            "title": "Goosebumps",
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=elf250uvecY"
                "&list=PLCeScks4FrgK-ZOSpDTZmfVz7xtGY5yXv"
            ),
            "title": "Clifford's Puppy Days",
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=cRe1cta5nZk"
                "&list=PLBSUN2PpOgePQlEtu-ZSMcHJf1zDA8a_M"
            ),
            "title": "Arthur",
        },
        {
            "url": "https://www.youtube.com/@90sProject",
            "title": "90s Project",
            "playlists_as_shows": True,
        },
    ]


def _parse_admin(raw: dict | None) -> dict[str, Any]:
    admin = raw or {}
    if not isinstance(admin, dict):
        admin = {}
    defaults = _default_config()["admin"]
    try:
        port = int(admin.get("port", defaults["port"]))
    except (TypeError, ValueError):
        port = defaults["port"]
    port = max(1024, min(65535, port))
    bind = str(admin.get("bind", defaults["bind"])).strip() or defaults["bind"]
    return {
        "enabled": bool(admin.get("enabled", defaults["enabled"])),
        "port": port,
        "bind": bind,
    }


def _default_config() -> dict[str, Any]:
    return {
        "media_paths": [DEFAULT_MEDIA_ROOT],
        "mounts": [],
        "keymap": {},
        "screensaver": {
            "enabled": True,
            "timeout_seconds": 30,
        },
        "playback": {
            "autoplay": "next_in_season_only",
            "autoplay_countdown_seconds": 5,
            "now_playing_splash": True,
            "now_playing_splash_seconds": 1.5,
            "hw_decode": "auto",
        },
        "ui": {
            "channel_snow": True,
            "shutdown_collapse": True,
            "channel_snow_audio": True,
            "analog_artifacts": True,
            "analog_artifact_rate": 12,
            "footer_hints": True,
            "safe_zone": {"top": 10, "bottom": 10, "left": 10, "right": 10},
        },
        "gamepad": {
            "enabled": True,
        },
        "channels": {
            "order": [],
            "numbers": {},
        },
        "library": {
            "rescan_interval_seconds": 0,
            "rescan_long_press_ms": 800,
        },
        "kids_mode": {
            "default_enabled": False,
            "interleave_shows_movies": False,
        },
        "network": {
            "mdns_hostname": "vintage-tv",
            "admin_port": 8765,
        },
        "cache": {
            "enabled": True,
            "directory": None,
            "max_bytes": _PLAYBACK_CACHE_DEFAULT_MAX_BYTES,
            "prefetch_next": True,
            "cache_before_playing": False,
        },
        "admin": {
            "enabled": True,
            "port": 8765,
            "bind": "0.0.0.0",
        },
        "accessibility": {
            "large_text": False,
            "high_contrast": False,
            "play_all_unwatched": False,
        },
        "weather": {
            "zip": "02108",
            "query": None,
            "name": "Boston",
            "latitude": None,
            "longitude": None,
        },
        "retro_tv": {
            "filters": None,
            "volume": None,
        },
        "youtube_channels": _default_youtube_channels(),
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
    ss_defaults = _default_config()["screensaver"]
    try:
        timeout_s = int(screensaver.get("timeout_seconds", ss_defaults["timeout_seconds"]))
    except (TypeError, ValueError):
        timeout_s = ss_defaults["timeout_seconds"]
    timeout_s = max(10, timeout_s)
    return {
        "media_paths": expanded,
        "mounts": mounts,
        "keymap": keymap,
        "screensaver": {
            "enabled": bool(screensaver.get("enabled", ss_defaults["enabled"])),
            "timeout_seconds": timeout_s,
        },
        "playback": _parse_playback(raw.get("playback")),
        "ui": _parse_ui(raw.get("ui")),
        "gamepad": _parse_gamepad(raw.get("gamepad")),
        "channels": _parse_channels(raw.get("channels")),
        "library": _parse_library(raw.get("library")),
        "kids_mode": _parse_kids_mode(raw.get("kids_mode")),
        "network": _parse_network(raw.get("network")),
        "cache": _parse_cache(raw.get("cache")),
        "admin": _parse_admin(raw.get("admin")),
        "accessibility": _parse_accessibility(raw.get("accessibility")),
        "weather": _parse_weather(raw.get("weather")),
        "retro_tv": _parse_retro_tv(raw.get("retro_tv")),
        "youtube_channels": _parse_youtube_channels(
            raw["youtube_channels"]
            if "youtube_channels" in raw
            else _default_youtube_channels()
        ),
    }


def parse_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a raw config dict (same rules as load_config)."""
    return _parse_config(raw)


def _config_create_path() -> str:
    """Path where a new config should be written when none exists."""
    env = os.environ.get("TV_TIME_CAPSULE_CONFIG")
    if env:
        return os.path.expanduser(env)
    return default_config_file()


def load_config() -> dict[str, Any]:
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

    dest = _config_create_path()
    _active_config_path = dest
    save_config(default, path=dest)
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
    save_config(_default_config(), path=_config_create_path())
