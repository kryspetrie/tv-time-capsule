"""NWS Local Standard regional radar loops — no API key.

Loops: https://radar.weather.gov/ridge/standard/{REGION}_loop.gif
e.g.   https://radar.weather.gov/ridge/standard/NORTHEAST_loop.gif
"""

from __future__ import annotations

import logging
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import pygame

LOG = logging.getLogger(__name__)

_UA = "tv-time-capsule/weather (https://github.com/kryspetrie/tv-time-capsule)"
_CACHE_DIR = Path.home() / ".cache" / "tv-time-capsule" / "weather-radar"
_DEFAULT_TTL_S = 5 * 60  # RIDGE updates about every 5 minutes

# Approximate mosaic centers (lat, lon) for nearest-region pick.
# Names match ``{REGION}_loop.gif`` on radar.weather.gov/ridge/standard/.
_REGION_CENTERS: tuple[tuple[str, float, float], ...] = (
    ("NORTHEAST", 42.8, -72.5),
    ("MIDATLANTIC", 38.5, -76.5),
    ("CENTGRLAKES", 42.0, -85.0),
    ("UPPERMISSVLY", 44.5, -93.5),
    ("SOUTHEAST", 32.5, -82.0),
    ("SOUTHMISSVLY", 34.0, -90.5),
    ("SOUTHPLAINS", 33.0, -99.0),
    ("SOUTHROCKIES", 35.0, -108.0),
    ("NORTHROCKIES", 45.0, -110.0),
    ("PACNORTHWEST", 45.5, -120.5),
    ("PACSOUTHWEST", 37.0, -119.5),
    ("ALASKA", 64.0, -153.0),
    ("HAWAII", 20.5, -157.0),
    ("GUAM", 13.4, 144.7),
    ("CARIB", 18.2, -66.5),
    ("CONUS", 39.0, -98.0),
)


@dataclass
class RadarLoop:
    """RIDGE regional loop — GIF on disk; Surfaces filled on the UI thread."""

    region: str
    frames: list[pygame.Surface] = field(default_factory=list)
    durations_ms: list[int] = field(default_factory=list)
    cached: bool = False
    fetched_at: float = 0.0
    path: Path | None = None

    @property
    def ready(self) -> bool:
        return bool(self.frames)

    @property
    def pending_decode(self) -> bool:
        """True when a GIF file is cached but not yet decoded to Surfaces."""
        return (
            not self.frames
            and self.path is not None
            and self.path.is_file()
        )

    @property
    def has_payload(self) -> bool:
        return self.ready or self.pending_decode


def materialize_radar_loop(
    loop: RadarLoop,
    *,
    fit_size: tuple[int, int] | None = None,
) -> bool:
    """Decode ``loop.path`` into pygame Surfaces (call from the UI thread).

    When ``fit_size`` is set ``(max_w, max_h)``, each frame is smooth-scaled
    once to fit inside that box (aspect preserved) so playback does not
    re-scale every tick. Re-fitting always reloads from ``path`` when
    available so scales never compound.
    """
    frames: list[pygame.Surface] = []
    durations: list[int] = []

    if loop.path is not None and loop.path.is_file():
        frames, durations = _load_loop_file(loop.path)
        if not frames:
            loop.path = None
            loop.frames = []
            loop.durations_ms = []
            return False
    elif loop.frames:
        frames, durations = list(loop.frames), list(loop.durations_ms)
    else:
        return False

    if fit_size is not None:
        frames, durations = _smooth_fit_frames(frames, durations, fit_size)
    loop.frames = frames
    loop.durations_ms = durations
    return bool(loop.frames)


def _smooth_fit_frames(
    frames: list[pygame.Surface],
    durations: list[int],
    fit_size: tuple[int, int],
) -> tuple[list[pygame.Surface], list[int]]:
    """Smooth-scale every frame once to fit inside ``fit_size``."""
    max_w, max_h = int(fit_size[0]), int(fit_size[1])
    if max_w <= 0 or max_h <= 0 or not frames:
        return frames, durations
    iw, ih = frames[0].get_size()
    if iw <= 0 or ih <= 0:
        return frames, durations
    scale = min(max_w / iw, max_h / ih)
    size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
    if size == (iw, ih):
        return frames, durations
    out = [pygame.transform.smoothscale(frame, size) for frame in frames]
    return out, list(durations)


def cache_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def resolve_radar_region(
    latitude: float,
    longitude: float,
    *,
    override: str | None = None,
) -> str:
    """Pick the NWS standard mosaic sector for a lat/lon."""
    if override:
        name = str(override).strip().upper().replace(" ", "").replace("-", "")
        # Allow common aliases from weather.gov radar_lite URLs.
        aliases = {
            "NORTHEAST": "NORTHEAST",
            "NE": "NORTHEAST",
            "MIDATLANTIC": "MIDATLANTIC",
            "CENTGRLAKES": "CENTGRLAKES",
            "GREATLAKES": "CENTGRLAKES",
            "GRLAKES": "CENTGRLAKES",
            "UPPERMISSVLY": "UPPERMISSVLY",
            "UPPERMISS": "UPPERMISSVLY",
            "SOUTHEAST": "SOUTHEAST",
            "SOUTHMISSVLY": "SOUTHMISSVLY",
            "SOUTHMISS": "SOUTHMISSVLY",
            "SOUTHPLAINS": "SOUTHPLAINS",
            "SOUTHROCKIES": "SOUTHROCKIES",
            "NORTHROCKIES": "NORTHROCKIES",
            "PACNORTHWEST": "PACNORTHWEST",
            "PACNW": "PACNORTHWEST",
            "PACSOUTHWEST": "PACSOUTHWEST",
            "PACSW": "PACSOUTHWEST",
            "ALASKA": "ALASKA",
            "HAWAII": "HAWAII",
            "GUAM": "GUAM",
            "CARIB": "CARIB",
            "CARIBBEAN": "CARIB",
            "CONUS": "CONUS",
            "NATIONAL": "CONUS",
        }
        if name in aliases:
            return aliases[name]
        known = {r for r, _, _ in _REGION_CENTERS}
        if name in known:
            return name

    lat, lon = float(latitude), float(longitude)
    # Non-CONUS shortcuts.
    if lat > 50.0 and lon < -130.0:
        return "ALASKA"
    if 18.5 <= lat <= 22.5 and -161.0 <= lon <= -154.0:
        return "HAWAII"
    if 12.0 <= lat <= 15.0 and 144.0 <= lon <= 146.5:
        return "GUAM"
    if 17.0 <= lat <= 19.5 and -68.0 <= lon <= -64.0:
        return "CARIB"

    best = "CONUS"
    best_d = 1e18
    for name, clat, clon in _REGION_CENTERS:
        if name in ("CONUS", "ALASKA", "HAWAII", "GUAM", "CARIB"):
            continue
        d = _haversine_mi(lat, lon, clat, clon)
        if d < best_d:
            best_d = d
            best = name
    return best


def build_ridge_loop_url(region: str) -> str:
    reg = str(region or "").strip().upper().replace(" ", "").replace("-", "")
    if not reg:
        reg = "CONUS"
    return f"https://radar.weather.gov/ridge/standard/{reg}_loop.gif"


def _as_display_surface(surf: pygame.Surface) -> pygame.Surface:
    try:
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            return surf.convert()
    except Exception:
        pass
    return surf


def _pil_frames_to_surfaces(data: bytes) -> tuple[list[pygame.Surface], list[int]]:
    """Decode an animated GIF into pygame surfaces + per-frame durations."""
    try:
        from PIL import Image
    except ImportError:
        LOG.warning("Pillow required to animate radar loops; showing first frame only")
        try:
            surf = _as_display_surface(pygame.image.load(BytesIO(data)))
            return ([surf], [200])
        except Exception:
            return ([], [])

    frames: list[pygame.Surface] = []
    durations: list[int] = []
    try:
        img = Image.open(BytesIO(data))
    except Exception:
        LOG.exception("Failed to open radar GIF")
        return ([], [])

    idx = 0
    while True:
        try:
            img.seek(idx)
        except EOFError:
            break
        duration = int(img.info.get("duration") or 200)
        duration = max(50, min(2000, duration))
        frame = img.convert("RGBA")
        mode = frame.mode
        size = frame.size
        raw = frame.tobytes()
        try:
            surf = pygame.image.frombytes(raw, size, mode)
        except Exception:
            # Older pygame
            surf = pygame.image.fromstring(raw, size, mode)  # type: ignore[attr-defined]
        frames.append(_as_display_surface(surf))
        durations.append(duration)
        idx += 1

    if not frames:
        return ([], [])
    return frames, durations


def _load_loop_file(path: Path) -> tuple[list[pygame.Surface], list[int]]:
    try:
        data = path.read_bytes()
    except OSError:
        return ([], [])
    return _pil_frames_to_surfaces(data)


class RidgeRadarLoopSource:
    """Adapter: NWS RIDGE regional ``{REGION}_loop.gif`` (implements RadarLoopSource).

    Returns an undecoded :class:`RadarLoop` (path only) so Surfaces are created
    on the UI thread via :func:`materialize_radar_loop`.
    """

    def fetch_loop(
        self,
        latitude: float,
        longitude: float,
        *,
        maps_cfg: dict[str, Any] | None,
        force_refresh: bool = True,
    ) -> RadarLoop | None:
        return fetch_radar_loop(
            latitude,
            longitude,
            maps_cfg=maps_cfg,
            force_refresh=force_refresh,
            decode=False,
        )


def fetch_radar_loop(
    latitude: float,
    longitude: float,
    *,
    maps_cfg: dict[str, Any] | None,
    station: str | None = None,
    force_refresh: bool = True,
    decode: bool = True,
) -> RadarLoop | None:
    """Download (prefer fresh) the regional RIDGE loop for this location.

    ``station`` is accepted for call-site compatibility but unused — mosaics
    are regional, not single-site.

    When ``decode`` is False, only the GIF file path is returned; call
    :func:`materialize_radar_loop` on the UI thread before playback.
    """
    del station
    cfg = maps_cfg if isinstance(maps_cfg, dict) else {}
    if cfg.get("enabled") is False:
        return None

    try:
        ttl_s = float(cfg.get("ttl_seconds", _DEFAULT_TTL_S))
    except (TypeError, ValueError):
        ttl_s = float(_DEFAULT_TTL_S)
    ttl_s = max(60.0, min(3600.0, ttl_s))

    override = str(cfg.get("region") or "").strip() or None
    region = resolve_radar_region(latitude, longitude, override=override)
    path = cache_dir() / f"{region}_loop.gif"
    url = build_ridge_loop_url(region)
    data: bytes | None = None

    def _loop_from_path(*, cached: bool, fetched_at: float) -> RadarLoop | None:
        if not path.is_file():
            return None
        if not decode:
            return RadarLoop(
                region=region,
                frames=[],
                durations_ms=[],
                cached=cached,
                fetched_at=fetched_at,
                path=path,
            )
        frames, durations = _load_loop_file(path)
        if not frames:
            return None
        return RadarLoop(
            region=region,
            frames=frames,
            durations_ms=durations,
            cached=cached,
            fetched_at=fetched_at,
            path=path,
        )

    # Fresh download unless caller allows serving a still-fresh cache.
    if (
        not force_refresh
        and path.is_file()
        and (time.time() - path.stat().st_mtime) < ttl_s
    ):
        built = _loop_from_path(cached=False, fetched_at=path.stat().st_mtime)
        if built is not None:
            return built

    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "image/gif,image/*"}
    )
    try:
        with urllib.request.urlopen(req, timeout=45.0) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        LOG.info("NWS RIDGE loop fetch failed %s: %s", url, exc)
        data = None

    if data and data[:3] in (b"GIF", b"gif"):
        try:
            path.write_bytes(data)
        except OSError:
            LOG.debug("Could not cache radar loop", exc_info=True)
        built = _loop_from_path(cached=False, fetched_at=time.time())
        if built is not None:
            return built

    # Fall back to on-disk loop (stale).
    if path.is_file():
        age = time.time() - path.stat().st_mtime
        cached = age >= ttl_s or data is None
        built = _loop_from_path(cached=cached, fetched_at=path.stat().st_mtime)
        if built is not None:
            return built
    return None


# --- Back-compat helpers used by tests / older call sites -------------------


def normalize_station(station: str | None) -> str | None:
    raw = (station or "").strip().upper()
    if not raw:
        return None
    if len(raw) == 3 and raw.isalpha():
        return "K" + raw
    if len(raw) == 4 and raw[0] == "K":
        return raw
    return raw if raw.isalpha() else None


def build_ridge_standard_url(station: str, *, frame: int = 0) -> str:
    site = normalize_station(station) or str(station).upper()
    frame_i = max(0, min(9, int(frame)))
    return f"https://radar.weather.gov/ridge/standard/{site}_{frame_i}.gif"


def resolve_nws_radar_station(latitude: float, longitude: float) -> str | None:
    """Nearest WSR-88D site from api.weather.gov points (free, no key)."""
    url = f"https://api.weather.gov/points/{latitude:.4f},{longitude:.4f}"
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/geo+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=12.0) as resp:
            import json

            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        LOG.info("NWS radar station lookup failed: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    props = data.get("properties") or {}
    return normalize_station(str(props.get("radarStation") or ""))


def fetch_radar_surface(
    latitude: float,
    longitude: float,
    *,
    maps_cfg: dict[str, Any] | None,
    width: int,
    height: int,
    station: str | None = None,
) -> tuple[pygame.Surface | None, str]:
    """Compatibility wrapper — returns the first loop frame."""
    del width, height
    loop = fetch_radar_loop(
        latitude,
        longitude,
        maps_cfg=maps_cfg,
        station=station,
        force_refresh=False,
    )
    if loop is None or not loop.frames:
        return None, ""
    label = loop.region + (" cached" if loop.cached else "")
    return loop.frames[0], label
