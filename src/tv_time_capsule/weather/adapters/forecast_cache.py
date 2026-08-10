"""Disk-backed last-good forecast store (ForecastSnapshotStore adapter)."""

from __future__ import annotations

import dataclasses
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

from ..models import (
    Alert,
    CurrentConditions,
    DayForecast,
    HourlyPeriod,
    Location,
    RegionalCity,
    WeatherSnapshot,
)

LOG = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".cache" / "tv-time-capsule" / "weather-forecast"
# Cold-start / total-outage ceiling — presenter still keeps fresher in-memory copies.
_DEFAULT_MAX_AGE_S = 6 * 3600.0

T = TypeVar("T")


def _key(location: Location) -> str:
    return f"{location.latitude:.3f}_{location.longitude:.3f}"


def _cache_path(location: Location) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{_key(location)}.json"


def _snap_to_dict(snap: WeatherSnapshot) -> dict[str, Any]:
    return {
        "location": asdict(snap.location),
        "current": asdict(snap.current) if snap.current else None,
        "hourly": [asdict(h) for h in snap.hourly],
        "daily": [asdict(d) for d in snap.daily],
        "regional": [asdict(r) for r in snap.regional],
        "alerts": [asdict(a) for a in snap.alerts],
        "radar_station": snap.radar_station,
        "fetched_at": snap.fetched_at,
        "source": snap.source,
    }


def _from_dict(cls: type[T], raw: Any) -> T | None:
    """Build a dataclass, ignoring unknown keys and tolerating partial rows."""
    if not isinstance(raw, dict):
        return None
    try:
        field_names = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    except TypeError:
        return None
    filtered = {k: v for k, v in raw.items() if k in field_names}
    try:
        return cls(**filtered)  # type: ignore[call-arg]
    except TypeError:
        return None


def _snap_from_dict(data: dict[str, Any]) -> WeatherSnapshot:
    loc_raw = data.get("location") or {}
    if not isinstance(loc_raw, dict):
        loc_raw = {}
    loc = Location(
        latitude=float(loc_raw.get("latitude") or 0.0),
        longitude=float(loc_raw.get("longitude") or 0.0),
        name=str(loc_raw.get("name") or ""),
        context=str(loc_raw.get("context") or ""),
        geocode=str(loc_raw.get("geocode") or ""),
    )
    current = _from_dict(CurrentConditions, data.get("current"))
    hourly = [
        h
        for h in (_from_dict(HourlyPeriod, row) for row in (data.get("hourly") or []))
        if h is not None
    ]
    daily = [
        d
        for d in (_from_dict(DayForecast, row) for row in (data.get("daily") or []))
        if d is not None
    ]
    regional = [
        r
        for r in (_from_dict(RegionalCity, row) for row in (data.get("regional") or []))
        if r is not None
    ]
    alerts = [
        a
        for a in (_from_dict(Alert, row) for row in (data.get("alerts") or []))
        if a is not None
    ]
    return WeatherSnapshot(
        location=loc,
        current=current,
        hourly=hourly,
        daily=daily,
        regional=regional,
        alerts=alerts,
        radar_station=str(data.get("radar_station") or ""),
        fetched_at=float(data.get("fetched_at") or 0.0),
        source=str(data.get("source") or "disk"),
    )


class DiskForecastStore:
    """JSON files under ``~/.cache/tv-time-capsule/weather-forecast/``."""

    def save(self, location: Location, snap: WeatherSnapshot) -> None:
        path = _cache_path(location)
        try:
            path.write_text(
                json.dumps(_snap_to_dict(snap), separators=(",", ":")),
                encoding="utf-8",
            )
        except OSError:
            LOG.debug("Could not write forecast cache %s", path, exc_info=True)

    def load(
        self, location: Location, *, max_age_s: float = _DEFAULT_MAX_AGE_S
    ) -> WeatherSnapshot | None:
        path = _cache_path(location)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            LOG.debug("Could not read forecast cache %s", path, exc_info=True)
            return None
        if not isinstance(data, dict):
            return None
        try:
            snap = _snap_from_dict(data)
        except (TypeError, ValueError, KeyError):
            LOG.debug("Corrupt forecast cache %s", path, exc_info=True)
            return None
        age = time.time() - float(snap.fetched_at or path.stat().st_mtime)
        if age > max(60.0, float(max_age_s)):
            LOG.info("Forecast disk cache too old (%.0fs); ignoring", age)
            return None
        if "disk" not in snap.source:
            snap.source = f"{snap.source}+disk" if snap.source else "disk"
        return snap
