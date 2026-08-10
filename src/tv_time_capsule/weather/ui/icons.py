"""Standard weather icons — real NWS PNG assets (cached), not hand-drawn glyphs."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import pygame

LOG = logging.getLogger(__name__)

ICON_IDS = (
    "clear-day",
    "clear-night",
    "partly-cloudy-day",
    "partly-cloudy-night",
    "cloudy",
    "fog",
    "rain",
    "snow",
    "sleet",
    "thunder",
    "wind",
    "unknown",
)

# Map our ids → NWS land icon tokens (api.weather.gov/icons).
_NWS_TOKEN: dict[str, tuple[str, str]] = {
    "clear-day": ("day", "skc"),
    "clear-night": ("night", "skc"),
    "partly-cloudy-day": ("day", "sct"),
    "partly-cloudy-night": ("night", "sct"),
    "cloudy": ("day", "ovc"),
    "fog": ("day", "fog"),
    "rain": ("day", "rain"),
    "snow": ("day", "snow"),
    "sleet": ("day", "sleet"),
    "thunder": ("day", "tsra"),
    "wind": ("day", "wind_skc"),
    "unknown": ("day", "skc"),
}

_UA = "tv-time-capsule/weather (https://github.com/kryspetrie/tv-time-capsule)"


def icon_from_wmo(code: int) -> str:
    """Map Open-Meteo / WMO weathercode to a standard icon id."""
    c = int(code)
    if c == 0:
        return "clear-day"
    if c in (1, 2):
        return "partly-cloudy-day"
    if c == 3:
        return "cloudy"
    if c in (45, 48):
        return "fog"
    if c in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if c in (71, 73, 75, 77, 85, 86):
        return "snow"
    if c in (95, 96, 99):
        return "thunder"
    return "unknown"


def wmo_condition_text(code: int) -> str:
    """Human-readable label for a WMO weather code."""
    c = int(code)
    table = {
        0: "Clear",
        1: "Mostly Clear",
        2: "Partly Cloudy",
        3: "Cloudy",
        45: "Fog",
        48: "Icy Fog",
        51: "Light Drizzle",
        53: "Drizzle",
        55: "Heavy Drizzle",
        61: "Light Rain",
        63: "Rain",
        65: "Heavy Rain",
        71: "Light Snow",
        73: "Snow",
        75: "Heavy Snow",
        80: "Rain Showers",
        81: "Rain Showers",
        82: "Heavy Showers",
        95: "Thunderstorms",
        96: "Thunderstorms",
        99: "Severe Thunderstorms",
    }
    return table.get(c, f"Code {c}")


def icon_from_nws_token(icon_url_or_name: str) -> str:
    """Best-effort map of NWS icon URL path tokens → standard id."""
    text = (icon_url_or_name or "").lower()
    token = text.rsplit("/", 1)[-1]
    token = token.split("?")[0].split(",")[0]
    mapping = {
        "skc": "clear-day",
        "few": "partly-cloudy-day",
        "sct": "partly-cloudy-day",
        "bkn": "cloudy",
        "ovc": "cloudy",
        "fog": "fog",
        "haze": "fog",
        "rain": "rain",
        "rain_showers": "rain",
        "rain_showers_hi": "rain",
        "tsra": "thunder",
        "tsra_sct": "thunder",
        "tsra_hi": "thunder",
        "snow": "snow",
        "blizzard": "snow",
        "sleet": "sleet",
        "fzra": "sleet",
        "wind_skc": "wind",
        "wind_few": "wind",
        "wind_sct": "wind",
        "wind_bkn": "wind",
        "wind_ovc": "wind",
    }
    for key, icon in mapping.items():
        if token.startswith(key) or f"/{key}" in text or key in token:
            if "night" in text or token.endswith("_n") or ",n" in text:
                if icon == "clear-day":
                    return "clear-night"
                if icon == "partly-cloudy-day":
                    return "partly-cloudy-night"
            return icon
    return "unknown"


def nws_icon_url(icon_id: str, *, size: str = "large") -> str:
    daypart, token = _NWS_TOKEN.get(icon_id, _NWS_TOKEN["unknown"])
    return f"https://api.weather.gov/icons/land/{daypart}/{token}?size={size}"


def _cache_dir() -> Path:
    xdg = Path.home() / ".cache" / "tv-time-capsule" / "weather-icons"
    xdg.mkdir(parents=True, exist_ok=True)
    return xdg


def _download_png(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "image/png"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = resp.read()
        if len(data) < 200:
            return None
        return data
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        LOG.debug("Icon download failed %s: %s", url, exc)
        return None


@lru_cache(maxsize=64)
def _load_png_bytes(url: str) -> bytes | None:
    """Fetch (or disk-cache) PNG bytes. Failures are not memoized as Surfaces."""
    key = "".join(c if c.isalnum() else "_" for c in url)[-120:]
    path = _cache_dir() / f"{key}.png"
    data: bytes | None = None
    if path.is_file() and path.stat().st_size > 200:
        data = path.read_bytes()
    if data is None:
        data = _download_png(url)
        if data is None:
            return None
        try:
            path.write_bytes(data)
        except OSError:
            pass
    return data


def _load_png_surface(url: str) -> pygame.Surface | None:
    """Decode a PNG URL to a Surface (does not permanently cache convert failures)."""
    data = _load_png_bytes(url)
    if data is None:
        return None
    try:
        surf = pygame.image.load(BytesIO(data))
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            try:
                return surf.convert_alpha()
            except Exception:
                return surf
        return surf
    except Exception:
        LOG.debug("Failed to decode icon PNG from %s", url)
        return None


def load_icon(
    size: int,
    icon_id: str,
    *,
    icon_url: str | None = None,
) -> pygame.Surface:
    """Load a real weather icon PNG scaled to *size* (NWS assets)."""
    size = max(16, int(size))
    urls: list[str] = []
    if icon_url:
        urls.append(icon_url)
        # Prefer large size when NWS omitted it.
        if "api.weather.gov/icons" in icon_url and "size=" not in icon_url:
            urls.insert(0, icon_url + ("&" if "?" in icon_url else "?") + "size=large")
    iid = icon_id if icon_id in ICON_IDS else "unknown"
    urls.append(nws_icon_url(iid, size="large"))
    urls.append(nws_icon_url(iid, size="medium"))

    for url in urls:
        surf = _load_png_surface(url)
        if surf is None:
            continue
        if surf.get_size() != (size, size):
            surf = pygame.transform.smoothscale(surf, (size, size))
        return surf

    # Last resort: empty transparent tile (never hand-draw fake glyphs).
    empty = pygame.Surface((size, size), pygame.SRCALPHA)
    empty.fill((0, 0, 0, 0))
    return empty


# Back-compat name used by older call sites / tests.
def draw_icon(size: int, icon_id: str) -> pygame.Surface:
    return load_icon(size, icon_id)
