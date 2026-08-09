"""TWC location search / resolve (moved from weather_channel)."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from ..models import Location

LOG = logging.getLogger(__name__)

# Public key embedded in weather.com/retro (same key the site uses for search).
_TWC_API_KEY = "b7f0783d80e94fd4b0783d80e94fd48b"
_TWC_LOCATION_SEARCH = "https://api.weather.com/v3/location/search"


def _twc_search(query: str, *, location_type: str | None = None) -> dict | None:
    """Return first match from weather.com location search, or None."""
    q = (query or "").strip()
    if len(q) < 2:
        return None
    params: dict[str, str] = {
        "query": q,
        "language": "en-US",
        "format": "json",
        "apiKey": _TWC_API_KEY,
    }
    if location_type:
        params["locationType"] = location_type
    url = f"{_TWC_LOCATION_SEARCH}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "tv-time-capsule/weather-channel"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        LOG.warning("Weather location search failed for %r: %s", q, exc)
        return None

    loc = data.get("location") if isinstance(data, dict) else None
    if not isinstance(loc, dict):
        return None
    place_ids = loc.get("placeId") or []
    if not place_ids:
        return None

    types = loc.get("type") or []
    idx = 0
    if isinstance(types, list):
        for i, t in enumerate(types):
            if t == "city":
                idx = i
                break

    def _at(key: str, default: str = "") -> str:
        vals = loc.get(key)
        if isinstance(vals, list) and idx < len(vals) and vals[idx] is not None:
            return str(vals[idx])
        return default

    try:
        lat = float(loc["latitude"][idx])
        lon = float(loc["longitude"][idx])
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    name = _at("displayName") or _at("city") or q
    context = _at("displayContext") or _at("adminDistrict") or ""
    return {
        "geocode": f"{lat},{lon}",
        "latitude": lat,
        "longitude": lon,
        "name": name,
        "context": context,
    }


def resolve_weather_location(cfg: dict | None) -> dict | None:
    """Resolve weather config into a cookie-shaped location dict, or None."""
    loc = resolve_location(cfg)
    return loc.to_cookie_dict() if loc is not None else None


def resolve_location(cfg: dict | None) -> Location | None:
    """Resolve optional weather config into a :class:`Location`."""
    weather = cfg or {}
    if not isinstance(weather, dict):
        return None

    lat = weather.get("latitude")
    lon = weather.get("longitude")
    name = (weather.get("name") or "").strip() or None
    zip_code = (weather.get("zip") or "").strip() or None
    query = (weather.get("query") or "").strip() or None

    if lat is not None and lon is not None:
        try:
            la = float(lat)
            lo = float(lon)
        except (TypeError, ValueError):
            la = lo = None  # type: ignore[assignment]
        if la is not None and lo is not None:
            if not name:
                hit = _twc_search(f"{la},{lo}") or _twc_search(f"{la:g},{lo:g}")
                if hit:
                    return Location(
                        latitude=float(hit["latitude"]),
                        longitude=float(hit["longitude"]),
                        name=str(hit.get("name") or ""),
                        context=str(hit.get("context") or ""),
                        geocode=str(hit.get("geocode") or f"{hit['latitude']},{hit['longitude']}"),
                    )
                name = f"{la:.2f}, {lo:.2f}"
            context = (
                weather.get("context")
                if isinstance(weather.get("context"), str)
                else ""
            ) or ""
            return Location(
                latitude=la,
                longitude=lo,
                name=name or "",
                context=context,
                geocode=f"{la},{lo}",
            )

    search_q = zip_code or query
    if not search_q:
        return None

    hit = None
    if zip_code and zip_code.replace("-", "").isdigit():
        hit = _twc_search(zip_code)
    else:
        hit = _twc_search(search_q, location_type="city") or _twc_search(search_q)

    if hit is None:
        LOG.warning("Could not resolve weather location for %r", search_q)
        return None
    if name:
        hit = dict(hit)
        hit["name"] = name
    hit["geocode"] = f"{hit['latitude']},{hit['longitude']}"
    LOG.info(
        "Weather location resolved: %s (%s) @ %s",
        hit.get("name"),
        hit.get("context"),
        hit.get("geocode"),
    )
    return Location(
        latitude=float(hit["latitude"]),
        longitude=float(hit["longitude"]),
        name=str(hit.get("name") or ""),
        context=str(hit.get("context") or ""),
        geocode=str(hit.get("geocode") or ""),
    )


class TwcLocationResolver:
    """:class:`~tv_time_capsule.weather.ports.LocationResolver` via TWC search."""

    def resolve(self, weather_cfg: dict) -> Location | None:
        return resolve_location(weather_cfg)
