"""Paths, display constants, and config file helpers."""

from __future__ import annotations

import json
import os
from typing import Any

from .safe_zone import parse_safe_zone, parse_safe_zone_offset, safe_zone_to_config
from .youtube_titles import (
    DEFAULT_YOUTUBE_TITLE_RULES,
    _parse_title_rules,
    show_name_prefix_rule,
)
from .youtube_playlists import parse_playlist_selectors

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
MARQUEE_SPEED_PX_S = 55
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
    marquee_raw = str(ui.get("marquee_scroll", defaults["marquee_scroll"])).strip().lower()
    if marquee_raw in ("selected", "selected_only", "selection", "on_select"):
        marquee_scroll = "selected"
    else:
        marquee_scroll = "always"
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
        "marquee_scroll": marquee_scroll,
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


def _parse_home_menu(raw: dict | None) -> dict[str, list[str]]:
    from .home_menu import parse_home_menu

    return parse_home_menu(raw if isinstance(raw, dict) else None)


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


# Bias to the 640×480 canvas: prefer ≤480p (best quality at SD), then ≤360,
# and only then ≤720 — avoids caching huge HD files we downscale away.
_DEFAULT_YOUTUBE_FORMAT = (
    "bv*[height<=480]+ba/b[height<=480]/"
    "bv*[height<=360]+ba/b[height<=360]/"
    "bv*[height<=720]+ba/b[height<=720]/b"
)


def _parse_youtube_offline_cache(raw: dict | None) -> dict[str, Any]:
    """Forever yt-dlp cache (not the remote-mount playback ``cache`` block)."""
    cache = raw or {}
    if not isinstance(cache, dict):
        cache = {}
    directory = cache.get("directory")
    if directory is not None:
        directory = str(directory).strip() or None
    raw_max = cache.get("max_bytes", None)
    if raw_max is None:
        max_bytes = None
    else:
        try:
            max_bytes = max(0, int(raw_max))
        except (TypeError, ValueError):
            max_bytes = None
    try:
        idle_seconds = int(cache.get("idle_seconds", 30))
    except (TypeError, ValueError):
        idle_seconds = 30
    idle_seconds = max(5, idle_seconds)
    try:
        idle_gap_seconds = int(cache.get("idle_gap_seconds", 60))
    except (TypeError, ValueError):
        idle_gap_seconds = 60
    idle_gap_seconds = max(5, idle_gap_seconds)
    try:
        rate_limit_cooldown_seconds = int(
            cache.get("rate_limit_cooldown_seconds", 1800)
        )
    except (TypeError, ValueError):
        rate_limit_cooldown_seconds = 1800
    rate_limit_cooldown_seconds = max(60, rate_limit_cooldown_seconds)
    # snake_case preferred; camelCase accepted as an alias.
    exclude_unavailable = bool(
        cache.get(
            "exclude_unavailable",
            cache.get("excludeUnavailable", False),
        )
    )
    fmt = cache.get("format")
    if fmt is None or not str(fmt).strip():
        fmt = _DEFAULT_YOUTUBE_FORMAT
    else:
        fmt = str(fmt).strip()
    layout = str(cache.get("layout") or "season_folders").strip().lower()
    if layout not in ("season_folders", "flat"):
        layout = "season_folders"
    try:
        batch_size = int(cache.get("batch_size", 1))
    except (TypeError, ValueError):
        batch_size = 1
    batch_size = max(1, min(8, batch_size))
    return {
        "enabled": bool(cache.get("enabled", True)),
        "directory": directory,
        "max_bytes": max_bytes,
        "download_when_idle": bool(cache.get("download_when_idle", True)),
        "idle_seconds": idle_seconds,
        "idle_gap_seconds": idle_gap_seconds,
        "rate_limit_cooldown_seconds": rate_limit_cooldown_seconds,
        "exclude_unavailable": exclude_unavailable,
        "format": fmt,
        "layout": layout,
        "batch_size": batch_size,
    }


def _parse_youtube(raw: dict | None) -> dict[str, Any]:
    """Playback mode + forever offline cache settings for YouTube shows."""
    block = raw or {}
    if not isinstance(block, dict):
        block = {}
    mode = str(block.get("playback_mode") or "prefer_cache").strip().lower()
    if mode not in ("live", "prefer_cache", "cached_only"):
        mode = "prefer_cache"
    return {
        "playback_mode": mode,
        "cache": _parse_youtube_offline_cache(block.get("cache")),
    }


def _parse_features(raw: dict | None) -> dict[str, Any]:
    """Master switches — false removes dial/UI entry and never starts Chrome."""
    block = raw or {}
    if not isinstance(block, dict):
        block = {}
    return {
        "weather": bool(block.get("weather", True)),
        "retro_tv": bool(block.get("retro_tv", True)),
        "youtube": bool(block.get("youtube", True)),
    }


def _parse_weather_screencast(raw: dict | None) -> dict[str, Any]:
    """Adaptive / fixed screencast knobs for the Weather Channel."""
    block = raw or {}
    if not isinstance(block, dict):
        block = {}
    mode = str(block.get("mode") or "auto").strip().lower()
    if mode not in ("auto", "fixed"):
        mode = "auto"
    try:
        min_fps = float(block.get("min_fps", 1))
    except (TypeError, ValueError):
        min_fps = 1.0
    try:
        max_fps = float(block.get("max_fps", 15))
    except (TypeError, ValueError):
        max_fps = 15.0
    min_fps = max(0.5, min(30.0, min_fps))
    max_fps = max(min_fps, min(30.0, max_fps))
    target_raw = block.get("target_fps")
    target_fps = None
    if target_raw is not None and str(target_raw).strip() != "":
        try:
            target_fps = float(target_raw)
        except (TypeError, ValueError):
            target_fps = None
        if target_fps is not None:
            target_fps = max(min_fps, min(max_fps, target_fps))

    def _opt_int(key: str, default: int | None = None) -> int | None:
        val = block.get(key, default)
        if val is None or str(val).strip() == "":
            return default
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            return default

    try:
        jpeg_quality = int(block.get("jpeg_quality", 80))
    except (TypeError, ValueError):
        jpeg_quality = 80
    jpeg_quality = max(20, min(95, jpeg_quality))

    # Optional WS4KP-only FPS override (default 4 in the presenter when unset).
    ws4kp_raw = block.get("ws4kp_target_fps")
    ws4kp_target_fps = None
    if ws4kp_raw is not None and str(ws4kp_raw).strip() != "":
        try:
            ws4kp_target_fps = float(ws4kp_raw)
        except (TypeError, ValueError):
            ws4kp_target_fps = None
        if ws4kp_target_fps is not None:
            ws4kp_target_fps = max(0.5, min(30.0, ws4kp_target_fps))

    return {
        "mode": mode,
        "min_fps": min_fps,
        "max_fps": max_fps,
        "target_fps": target_fps,
        "ws4kp_target_fps": ws4kp_target_fps,
        "max_width": _opt_int("max_width"),
        "max_height": _opt_int("max_height"),
        "jpeg_quality": jpeg_quality,
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


def _parse_weather_music(raw: dict | None) -> dict[str, Any]:
    block = raw if isinstance(raw, dict) else {}
    try:
        volume = int(block.get("volume", 70))
    except (TypeError, ValueError):
        volume = 70
    volume = max(0, min(100, volume))
    directory = block.get("directory")
    if directory is not None:
        directory = str(directory).strip() or None
    announcements_directory = block.get("announcements_directory")
    if announcements_directory is not None:
        announcements_directory = str(announcements_directory).strip() or None
    return {
        "enabled": bool(block.get("enabled", True)),
        "directory": directory,
        "announcements_directory": announcements_directory,
        "volume": volume,
    }


def _parse_weather_native(raw: dict | None) -> dict[str, Any]:
    block = raw if isinstance(raw, dict) else {}
    try:
        page_seconds = float(block.get("page_seconds", 12))
    except (TypeError, ValueError):
        page_seconds = 12.0
    page_seconds = max(4.0, min(60.0, page_seconds))
    style = str(block.get("alert_style") or "marquee").strip().lower()
    if style not in ("marquee", "page"):
        style = "marquee"
    return {"page_seconds": page_seconds, "alert_style": style}


def _parse_weather_maps(raw: dict | None) -> dict[str, Any]:
    """NWS RIDGE regional radar loop for the native Radar page."""
    block = raw if isinstance(raw, dict) else {}
    enabled = bool(block.get("enabled", True))
    region = block.get("region")
    region_s = str(region).strip().upper().replace(" ", "").replace("-", "") if region else ""
    # Legacy station key kept for older configs; mosaics use region, not site.
    station = block.get("station") or block.get("radar_station")
    station_s = str(station).strip().upper() if station is not None else ""
    if station_s and len(station_s) == 3:
        station_s = "K" + station_s
    try:
        ttl = float(block.get("ttl_seconds", 300))
    except (TypeError, ValueError):
        ttl = 300.0
    ttl = max(60.0, min(3600.0, ttl))
    return {
        "enabled": enabled,
        "region": region_s or None,
        "station": station_s or None,
        "ttl_seconds": ttl,
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

    from .weather.resolve import normalize_provider

    provider = normalize_provider(
        weather.get("provider", defaults.get("provider", "native"))
    )
    base = weather.get("ws4kp_base_url", defaults.get("ws4kp_base_url"))
    ws4kp_base_url = str(base or "https://weatherstar.netbymatt.com/").strip()
    if not ws4kp_base_url.endswith("/"):
        ws4kp_base_url += "/"

    return {
        "provider": provider,
        "zip": _opt_str("zip"),
        "query": _opt_str("query"),
        "name": _opt_str("name"),
        "latitude": latitude,
        "longitude": longitude,
        "ws4kp_base_url": ws4kp_base_url,
        "music": _parse_weather_music(
            weather.get("music")
            if isinstance(weather.get("music"), dict)
            else defaults.get("music")
        ),
        "native": _parse_weather_native(
            weather.get("native")
            if isinstance(weather.get("native"), dict)
            else defaults.get("native")
        ),
        "maps": _parse_weather_maps(
            weather.get("maps")
            if isinstance(weather.get("maps"), dict)
            else defaults.get("maps")
        ),
        "screencast": _parse_weather_screencast(weather.get("screencast")),
    }


def _parse_retro_tv(raw: dict | None) -> dict[str, Any]:
    """MyRetroTVs decade-stream preferences (channel-type filters).

    ``filters`` maps checkbox ids (``box_c``, ``box_s``, …) to enabled flags.
    ``null`` / omitted means “use the site default” (typically all on) until
    the user changes them in the in-app menu.

    ``playback_mode`` defaults to ``cached`` (site as playlist oracle + temporary
    yt-dlp pair played via ffmpeg). Set ``live`` for Chrome CDP screencast.
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

    mode_raw = retro.get("playback_mode", defaults.get("playback_mode", "cached"))
    playback_mode = str(mode_raw or "cached").strip().lower()
    if playback_mode not in ("live", "cached"):
        playback_mode = "cached"

    cache_dir_raw = retro.get("cache_directory", defaults.get("cache_directory"))
    cache_directory = None
    if cache_dir_raw is not None and str(cache_dir_raw).strip():
        cache_directory = str(cache_dir_raw).strip()

    return {
        "filters": filters,
        "volume": volume_i,
        "playback_mode": playback_mode,
        "cache_directory": cache_directory,
    }


def _parse_youtube_channels(raw: list | None) -> list[dict[str, Any]]:
    """YouTube channels/playlists listed as virtual shows.

    Each entry needs ``handle`` (``@name``) and/or ``url`` (channel URL,
    ``/channel/UC…``, or a playlist / watch?list= URL). Optional ``title``
    overrides the show name. Set ``playlists_as_shows`` to unroll public
    playlists (except All Videos) into distinct shows. Use ``playlist_shows`` to
    limit which playlists become shows and to merge related playlists (e.g.
    Ghostwriter Season 1–3) into one multi-season show. Use ``include_playlists``
    to keep a single channel show but only selected playlist seasons.
    Optional ``title_deletions`` / ``title_substitutions`` / ``title_rules`` /
    ``strip_title_prefix`` normalize scraped playlist and episode titles for
    this entry only (after global ``youtube_title_rules``).
    Dial numbers use the same ``channels.order`` / ``channels.numbers`` path as
    local shows (web admin); optional ``channel`` on an entry is still accepted
    as a convenience merge into numbers.
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
        if bool(item.get("playlists_as_shows")) or item.get("playlist_shows"):
            entry["playlists_as_shows"] = True
            # When unrolling playlists, skip the mega "All Videos" channel show
            # unless the user explicitly keeps it.
            if "include_all_videos" in item:
                entry["include_all_videos"] = bool(item.get("include_all_videos"))
            else:
                entry["include_all_videos"] = False
        elif "include_all_videos" in item:
            entry["include_all_videos"] = bool(item.get("include_all_videos"))
        playlist_shows = parse_playlist_selectors(item.get("playlist_shows"))
        if playlist_shows:
            entry["playlist_shows"] = playlist_shows
            entry["playlists_as_shows"] = True
            if "include_all_videos" not in entry:
                entry["include_all_videos"] = False
        include_playlists = parse_playlist_selectors(item.get("include_playlists"))
        if include_playlists:
            entry["include_playlists"] = include_playlists
        title_rules = _entry_title_rules(item, title_s)
        if title_rules:
            entry["title_rules"] = title_rules
        if bool(item.get("strip_title_prefix")):
            entry["strip_title_prefix"] = True
        out.append(entry)
    return out


def _entry_title_rules(item: dict[str, Any], title_s: str) -> list[dict[str, Any]]:
    """Merge strip_title_prefix + deletions/substitutions/title_rules."""
    rules: list[dict[str, Any]] = []
    if bool(item.get("strip_title_prefix")) and title_s:
        prefix = show_name_prefix_rule(title_s)
        if prefix:
            rules.append(prefix)

    deletions = item.get("title_deletions")
    if deletions is None:
        deletions = item.get("deletions")
    substitutions = item.get("title_substitutions")
    if substitutions is None:
        substitutions = item.get("substitutions")
    if deletions is not None or substitutions is not None:
        rules.extend(
            _parse_title_rules(
                {
                    "deletions": deletions if deletions is not None else [],
                    "substitutions": substitutions if substitutions is not None else [],
                }
            )
        )

    if "title_rules" in item:
        rules.extend(_parse_title_rules(item.get("title_rules")))
    return rules


def _default_youtube_channels() -> list[dict[str, Any]]:
    """Kids / classic YouTube shows preloaded in the example and default config."""
    return [
        {
            "url": "https://www.youtube.com/@msrachel/",
            "title": "Ms Rachel",
            "title_deletions": [
                r"(?i)\s*\|\s*(?:Videos for Toddlers|Toddler Learning Videos?|"
                r"Educational Kids Videos|Kids Dance Songs|Speech(?: Delay Learning Video)?|"
                r"Videos for Babies|Baby Videos|Videos for Kids)\s*$",
                r"(?i)\s*[-–—]\s*Videos for Kids\b.*$",
                r"(?i)\s*[-–—]\s*Nursery Rhymes\s*&\s*Kids Songs\s*$",
            ],
        },
        {
            "url": "https://www.youtube.com/@BlueyOfficialChannel",
            "title": "Bluey",
            "title_deletions": [
                r"(?i)\s*\|\s*Bluey Book Reads\s*$",
                r"(?i)\s*\|\s*FULL BLUEY MINISODE\s*$",
                r"(?i)\s*\|\s*Bluey #ytshorts\s*$",
                r"(?i)\s*\|\s*Bluey (?:Cookalongs|Puppets|Dancealongs|Cake Off)\s*$",
                r"(?i)\s*\|\s*Bingo\s*-\s*Official Channel\s*$",
                r"(?i)\s*\|\s*NEW Bluey Tunes\s*$",
                r"(?i)^LIVE\s*:\s*",
                {"pattern": r"(?i)^Bluey\s*:\s*", "scope": "episode"},
            ],
        },
        {
            "url": "https://www.youtube.com/@Raffi",
            "title": "Raffi",
            "strip_title_prefix": True,
            "title_deletions": [
                r"(?i)^Raffi with(?: the)? Good Lovelies\s*[-–—]\s*",
                r"(?i)^Raffi and Lindsay Munroe\s*[-–—]\s*",
                r"(?i)^Raffi,\s*Yo-Yo Ma,\s*Lindsay Munroe\s*[-–—]\s*",
                r"(?i)^Raffi and Yo-Yo Ma\s*[-–—]\s*",
                r"(?i)\s*[-–—]\s*In Concert with the Rise and Shine Band\s*$",
                r"(?i)\s*[-–—]\s*ft\.\s*Good Lovelies\s*$",
                r"(?i)\s*\(Official Visualizer\)\s*$",
            ],
        },
        {
            "url": "https://www.youtube.com/@SciShowKids",
            "title": "SciShow Kids",
            "title_deletions": [
                r"(?i)\s*\|\s*Winter Science\s*$",
                r"(?i)\s*\|\s*Weather Science\s*$",
                r"(?i)\s*\|\s*Science Project for Kids\s*$",
                r"(?i)\s*\|\s*Amazing Animals\s*$",
                r"(?i)\s*\|\s*How We Study Space\s*$",
                r"(?i)\s*\|\s*The Science of (?:Food|Flight|Cooking)!\s*$",
                r"(?i)\s*\|\s*Spring is Here!\s*$",
                r"(?i)\s*\|\s*Winter is Alive!\s*$",
                r"(?i)\s*\|\s*Squeaks Grows a Garden!\s*$",
            ],
        },
        {
            "url": "https://www.youtube.com/@PBSKIDS",
            "title": "PBS KIDS",
            "playlists_as_shows": True,
            "playlist_shows": [
                "Phoebe & Jay",
                "WordGirl",
                "Ready Jet Go!",
                "Let's Go Luna",
                "Team Hamster with Ruff",
                "Xavier Riddle & the Secret Museum",
                "Acoustic Rooster",
                "Daniel Tiger's Neighborhood",
                "City Island",
                "Dinosaur Train",
                "Jelly, Ben & Pogo",
                "Rosie's Rules",
                "Carl the Collector",
                "Lyla in the Loop",
                "Weather Hunters",
                "Odd Squad UK",
            ],
            "title_deletions": [
                r"(?i)^PBS KIDS\s+",
                r"(?i)\s*\|\s*PBS KIDS Apps\s*&\s*Games\s*$",
            ],
        },
        {
            "url": "https://www.youtube.com/channel/UCOXkrXRpNfUu6mypF7NZxnA",
            "title": "Ms Moni",
            "title_deletions": [
                r"(?i)\s*\|\s*(?:Toddler Learning Videos?|Kids Learning Videos|"
                r"Toddler Learning with Ms\.?\s*Moni|Learn To Talk with Ms\.?\s*Moni|"
                r"Talking Toddler Learning|Learning For Toddlers|"
                r"Construction Vehicles For Kids|"
                r"Toddler Learning Videos,\s*Kids Songs\s*&\s*Nursery Rhymes Compilation|"
                r"2hrs? Compilation)\s*$",
                r"(?i)^(?:💛\s*)?Ms\.?\s*Moni\s*[-–—]\s*",
                r"(?i)^Best of Ms\.?\s*Moni\s*[-–—]\s*",
            ],
        },
        {
            "url": "https://www.youtube.com/@thomasandfriends",
            "title": "Thomas & Friends",
            "include_all_videos": False,
            "include_playlists": [
                {
                    "match": r"(?i)^Season\s+(\d+)$",
                },
                {
                    "title": "Movies & Specials",
                    "match": r"(?i)Movies\s*&\s*Specials",
                },
            ],
            "strip_title_prefix": True,
            "title_deletions": [
                r"(?i)^Thomas\s*&\s*Friends\s*[|:]\s*",
                r"(?i)\s*\|\s*Watch Out Thomas!?\s*$",
                r"(?i)\s*\|\s*Life Lessons\s*$",
                r"(?i)\s*\|\s*All Engines Go!?\s*$",
                r"(?i)\s*\|\s*On Cartoonito\b.*$",
                {"pattern": r"(?i)\s*:\s*Sing Along!\s*$", "scope": "playlist"},
                {"pattern": r"(?i)\s*\|\s*Compilations?\s*$", "scope": "playlist"},
                {
                    "pattern": r"(?i)\s*80th Anniversary Storytime\s*\|\s*Read Along\s*$",
                    "scope": "playlist",
                },
            ],
            "title_substitutions": [
                [
                    r"(?i)^Thomas\s*&\s*Friends\s*Movies\s*&\s*Specials\s*$",
                    "Movies & Specials",
                ],
            ],
        },
        {
            "url": "https://www.youtube.com/@BillNyeTheScienceGuyHD/",
            "title": "Bill Nye the Science Guy",
            "strip_title_prefix": True,
            "include_all_videos": False,
            "include_playlists": [
                {"match": r"(?i)^Season\s+(\d+)$"},
            ],
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=yzPeIKhMUOU"
                "&list=PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ"
            ),
            "title": "Beakman's World",
            "title_deletions": [
                r"(?i)^Beakman's World\s+",
                {"pattern": r"(?i)\s*(?:audio dropouts\s*)?\bPDTV\b.*$", "scope": "episode"},
                {"pattern": r"(?i)\s*\bdrngr\s*$", "scope": "episode"},
            ],
        },
        {
            "url": "https://www.youtube.com/@ReadingRainbowOfficial",
            "title": "Reading Rainbow",
            "strip_title_prefix": True,
            "include_all_videos": False,
            "include_playlists": [
                {
                    "title": "Full Episodes",
                    "match": r"(?i)^Full Episodes!?\s*$",
                },
                {
                    "title": "New Season",
                    "match": r"(?i)^(?:All New Season!?|New Season)\s*$",
                },
                {
                    "title": "Stories",
                    "match": r"(?i)^(?:Reading Rainbow\s+)?Stories\s*$",
                },
            ],
            "title_deletions": [
                r"(?i)^Reading Rainbow\s*[|\-–—]\s*",
            ],
            "title_substitutions": [
                [r"(?i)^Reading Rainbow\s+Stories\s*$", "Stories"],
                [r"(?i)^Full Episodes!?\s*$", "Full Episodes"],
                [r"(?i)^All New Season!?\s*$", "New Season"],
            ],
        },
        {
            "url": "https://www.youtube.com/@SesameStreet",
            "title": "Sesame Street",
            "strip_title_prefix": True,
            "title_deletions": [
                r"(?i)^Sesame Street Baby Band\s*:\s*",
                r"(?i)^Sesame Street on Roblox\s*:\s*",
                r"(?i)\s*\|\s*#ShareTheLaughter Challenge\s*$",
                r"(?i)\s*\|\s*Nursery Rhymes and Kids Songs\s*$",
                r"(?i)\s*\|\s*Music\s*&\s*Dance for Kids\s*$",
                r"(?i)\s*\|\s*Elmo's World\s*$",
                r"(?i)\s*\|\s*Sponsored by Dove\s*$",
                r"(?i)\s*[-–—]\s*ChuChu TV(?: Nursery Rhymes| Classics)?\s*$",
                r"(?i)\s*[-–—]\s*Toddler Learning Videos\s*$",
                r"(?i)\s*[-–—]\s*Alphabet Animals\s*$",
            ],
        },
        {
            "url": "https://www.youtube.com/@ScholasticClassic",
            "title": "Scholastic Classic",
            "playlists_as_shows": True,
            "playlist_shows": [
                {
                    "title": "Animorphs",
                    "match": r"(?i)^Animorphs(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "Astroblast",
                    "match": r"(?i)^Astroblast(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "Maya & Miguel",
                    "match": r"(?i)^Maya\s*&\s*Miguel(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "Clifford's Puppy Days",
                    "match": r"(?i)^Clifford's Puppy Days(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "Goosebumps",
                    "match": r"(?i)^Goosebumps(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "Clifford the Big Red Dog",
                    "match": r"(?i)^Clifford the Big Red Dog(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "The Magic School Bus",
                    "match": r"(?i)^The Magic School Bus(?:\s+Scholastic Classic)?\s*$",
                },
                {
                    "title": "Horrible Histories",
                    "match": r"(?i)^Horrible Histories\b",
                },
            ],
            "title_deletions": [
                r"(?i)^Animorphs\s+\d+(?:-\d+)?\s*\|\s*",
                r"(?i)^Battling Aliens with Animal Powers\s*\|\s*",
                r"(?i)^Teens Transform into Animals(?:\s+to Fight Aliens)?\s*\|\s*",
                r"(?i)\s*\|\s*Happy Halloween!\s*$",
                r"(?i)\s*\|\s*Spooky Holidays\s*$",
                r"(?i)\s+Spooky Halloween Full Episodes\b.*$",
            ],
            "title_substitutions": [
                [r"(?i)^Animorphs\s+(\d+(?:-\d+)?)\s*$", r"\1"],
            ],
        },
        {
            "url": (
                "https://www.youtube.com/watch?v=cRe1cta5nZk"
                "&list=PLBSUN2PpOgePQlEtu-ZSMcHJf1zDA8a_M"
            ),
            "title": "Arthur",
            # Season / FULL EPISODE / ItunesRip / SxxExx handled by global title rules;
            # strip_title_prefix covers "Arthur -" / "Arthur |" / "Arthur :".
            "strip_title_prefix": True,
        },
        {
            "url": "https://www.youtube.com/@90sProject",
            "title": "90s Project",
            "playlists_as_shows": True,
            "playlist_shows": [
                "Bobby's World",
                "Care Bears",
                "Timon and Pumbaa",
                "Rupert",
                "Sagwa the Chinese Siamese Cat",
                "Wishbone",
                {
                    "title": "Ghostwriter",
                    "match": r"(?i)^Ghostwriter\s+Season\s+(\d+)$",
                },
            ],
            "title_deletions": [
                r"(?i)^Wishbone\s*[:\-–—]\s*",
                r"(?i)^Bobby's [Ww]orld\s*[-–—]\s*",
                r"(?i)^Sagwa The Chinese Siamese Cat\s*[-–—:]\s*",
                r"(?i)^Ghostwriter\s*[-–—:]\s*",
                r"(?i)^Care Bears\s*[-–—:]\s*",
                r"(?i)^GW\s*[-–—:]\s*",
                r"(?i)\s*\[\(watch the rest.*$",
                r"(?i)\s*\(add\s*&fmt=18.*$",
                r"(?i)\s*\(clip\)\s*",
                r"(?i)\s+HD\s+(\d+)\s*$",
            ],
        },
        {
            "url": "https://www.youtube.com/@MisterRogersNeighborhood",
            "title": "Mister Rogers' Neighborhood",
            "include_all_videos": False,
            "include_playlists": [
                {
                    "title": "Full Episodes",
                    "match": r"(?i)Full Episodes\s*$",
                },
                {
                    "title": "New in the Neighborhood",
                    "match": r"(?i)^New in the Neighborhood\s*$",
                },
                {
                    "title": "Classic Moments",
                    "match": r"(?i)Classic Moments\s*$",
                },
            ],
            "title_deletions": [
                r"(?i)\s*\|\s*Official Channel Trailer\b.*$",
            ],
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
            "marquee_scroll": "always",
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
        "home_menu": _parse_home_menu(None),
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
        "features": _parse_features(None),
        "weather": {
            "provider": "native",
            "zip": "02108",
            "query": None,
            "name": "Boston",
            "latitude": None,
            "longitude": None,
            "ws4kp_base_url": "https://weatherstar.netbymatt.com/",
            "music": {
                "enabled": True,
                "directory": None,
                "announcements_directory": None,
                "volume": 70,
            },
            "native": {
                "page_seconds": 12,
                "alert_style": "marquee",
            },
            "maps": {
                "enabled": True,
                "region": None,
                "station": None,
                "ttl_seconds": 300,
            },
            "screencast": _parse_weather_screencast(None),
        },
        "retro_tv": {
            "filters": None,
            "volume": None,
            "playback_mode": "cached",
            "cache_directory": None,
        },
        "youtube_channels": _parse_youtube_channels(_default_youtube_channels()),
        "youtube_title_rules": list(DEFAULT_YOUTUBE_TITLE_RULES),
        "youtube": _parse_youtube(None),
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
        "home_menu": _parse_home_menu(raw.get("home_menu")),
        "network": _parse_network(raw.get("network")),
        "cache": _parse_cache(raw.get("cache")),
        "admin": _parse_admin(raw.get("admin")),
        "accessibility": _parse_accessibility(raw.get("accessibility")),
        "features": _parse_features(raw.get("features")),
        "weather": _parse_weather(raw.get("weather")),
        "retro_tv": _parse_retro_tv(raw.get("retro_tv")),
        "youtube_channels": _parse_youtube_channels(
            raw["youtube_channels"]
            if "youtube_channels" in raw
            else _default_youtube_channels()
        ),
        "youtube_title_rules": (
            _parse_title_rules(raw["youtube_title_rules"])
            if "youtube_title_rules" in raw
            else list(DEFAULT_YOUTUBE_TITLE_RULES)
        ),
        "youtube": _parse_youtube(raw.get("youtube")),
    }


def parse_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a raw config dict (same rules as load_config)."""
    cfg = _parse_config(raw)
    _apply_youtube_title_rules(cfg)
    return cfg


def _apply_youtube_title_rules(cfg: dict[str, Any]) -> None:
    try:
        from .youtube_catalog import set_youtube_title_rules
    except ImportError:
        return
    set_youtube_title_rules(cfg.get("youtube_title_rules"))


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
                cfg = _parse_config(json.load(f))
                _apply_youtube_title_rules(cfg)
                return cfg
        except (json.JSONDecodeError, OSError):
            _apply_youtube_title_rules(default)
            return default

    dest = _config_create_path()
    _active_config_path = dest
    save_config(default, path=dest)
    _apply_youtube_title_rules(default)
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
