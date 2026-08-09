"""MET Norway Locationforecast 2.0 adapter (no API key; User-Agent required)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from ..models import (
    CurrentConditions,
    DayForecast,
    HourlyPeriod,
    Location,
    WeatherSnapshot,
)
from ..ui.icons import icon_from_wmo, nws_icon_url, wmo_condition_text
from .forecast_nws import _deg_to_cardinal, _hour_label, _iso_to_epoch, upcoming_hourly

LOG = logging.getLogger(__name__)

_UA = "tv-time-capsule/weather (https://github.com/kryspetrie/tv-time-capsule)"


def _c_to_f(c: float | None) -> float | None:
    if c is None:
        return None
    return (float(c) * 9.0 / 5.0) + 32.0


def _mm_to_in(mm: float | None) -> float | None:
    if mm is None:
        return None
    return float(mm) / 25.4


def _as_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


# Rough yr.no symbol_code → WMO-ish code for our icon set.
_SYMBOL_WMO: dict[str, int] = {
    "clearsky": 0,
    "fair": 1,
    "partlycloudy": 2,
    "cloudy": 3,
    "fog": 45,
    "lightrainshowers": 80,
    "rainshowers": 81,
    "heavyrainshowers": 82,
    "lightrain": 61,
    "rain": 63,
    "heavyrain": 65,
    "lightsleet": 66,
    "sleet": 67,
    "lightsnow": 71,
    "snow": 73,
    "heavysnow": 75,
    "lightsnowshowers": 85,
    "snowshowers": 86,
    "heavysnowshowers": 86,
    "thunderstorm": 95,
}


def _symbol_to_wmo(symbol: str) -> int:
    raw = (symbol or "").strip().lower()
    # strip day/night / polar suffixes: partlycloudy_day → partlycloudy
    base = raw.split("_", 1)[0]
    return _SYMBOL_WMO.get(base, 3)


class MetNorwayForecastClient:
    """Global compact forecast from api.met.no (tertiary fallback)."""

    def fetch(self, location: Location) -> WeatherSnapshot:
        url = (
            "https://api.met.no/weatherapi/locationforecast/2.0/compact"
            f"?lat={location.latitude:.4f}&lon={location.longitude:.4f}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _UA,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=18.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"MET Norway fetch failed: {exc}") from exc

        series = ((data.get("properties") or {}).get("timeseries") or [])
        if not series:
            raise RuntimeError("MET Norway returned no timeseries")

        now = time.time()
        first = series[0].get("data") or {}
        instant = (first.get("instant") or {}).get("details") or {}
        n1 = first.get("next_1_hours") or first.get("next_6_hours") or {}
        sym = str((n1.get("summary") or {}).get("symbol_code") or "")
        wmo = _symbol_to_wmo(sym)
        iid = icon_from_wmo(wmo)
        current = CurrentConditions(
            temperature_f=_c_to_f(_as_float(instant.get("air_temperature"))),
            feels_like_f=None,
            humidity_pct=_as_float(instant.get("relative_humidity")),
            wind_mph=_as_float(instant.get("wind_speed")),  # m/s ≈ close enough for CRT
            wind_gust_mph=_as_float(instant.get("wind_speed_of_gust")),
            wind_dir=_deg_to_cardinal(_as_float(instant.get("wind_from_direction")) or 0)
            if instant.get("wind_from_direction") is not None
            else "",
            dewpoint_f=None,
            pressure_inhg=(
                (_as_float(instant.get("air_pressure_at_sea_level")) or 0) / 33.8639
                if instant.get("air_pressure_at_sea_level") is not None
                else None
            ),
            precip_pct=_as_float((n1.get("details") or {}).get("probability_of_precipitation")),
            precip_in=_mm_to_in(_as_float((n1.get("details") or {}).get("precipitation_amount"))),
            condition_text=wmo_condition_text(wmo),
            icon_id=iid,
            icon_url=nws_icon_url(iid),
            observed_at=str(series[0].get("time") or ""),
        )
        # wind_speed from MET is m/s — convert to mph for display consistency.
        if current.wind_mph is not None:
            current = CurrentConditions(
                **{
                    **current.__dict__,
                    "wind_mph": current.wind_mph * 2.23694,
                    "wind_gust_mph": (
                        current.wind_gust_mph * 2.23694
                        if current.wind_gust_mph is not None
                        else None
                    ),
                }
            )

        hourly: list[HourlyPeriod] = []
        for entry in series:
            t = str(entry.get("time") or "")
            start_epoch = _iso_to_epoch(t)
            if start_epoch > 0 and start_epoch + 3600 <= now:
                continue
            d = entry.get("data") or {}
            inst = (d.get("instant") or {}).get("details") or {}
            nxt = d.get("next_1_hours") or d.get("next_6_hours") or {}
            sym_h = str((nxt.get("summary") or {}).get("symbol_code") or "")
            code = _symbol_to_wmo(sym_h)
            hid = icon_from_wmo(code)
            wind_ms = _as_float(inst.get("wind_speed"))
            wind_deg = _as_float(inst.get("wind_from_direction"))
            hourly.append(
                HourlyPeriod(
                    time_label=_hour_label(t) if "T" in t else t,
                    temperature_f=_c_to_f(_as_float(inst.get("air_temperature"))),
                    humidity_pct=_as_float(inst.get("relative_humidity")),
                    wind_mph=wind_ms * 2.23694 if wind_ms is not None else None,
                    wind_dir=_deg_to_cardinal(wind_deg) if wind_deg is not None else "",
                    icon_id=hid,
                    icon_url=nws_icon_url(hid),
                    condition_text=wmo_condition_text(code),
                    precip_pct=_as_float(
                        (nxt.get("details") or {}).get("probability_of_precipitation")
                    ),
                    precip_in=_mm_to_in(
                        _as_float((nxt.get("details") or {}).get("precipitation_amount"))
                    ),
                    start_epoch=start_epoch,
                )
            )
            if len(hourly) >= 12:
                break

        # Build 5-day highs/lows from the timeseries envelope.
        by_day: dict[str, dict[str, Any]] = {}
        for entry in series[:120]:
            t = str(entry.get("time") or "")
            day = t[:10]
            if len(day) < 10:
                continue
            temp = _c_to_f(
                _as_float(
                    ((entry.get("data") or {}).get("instant") or {})
                    .get("details", {})
                    .get("air_temperature")
                )
            )
            if temp is None:
                continue
            slot = by_day.setdefault(day, {"hi": temp, "lo": temp, "sym": ""})
            slot["hi"] = max(slot["hi"], temp)
            slot["lo"] = min(slot["lo"], temp)
            nxt = (entry.get("data") or {}).get("next_6_hours") or (
                entry.get("data") or {}
            ).get("next_12_hours")
            if nxt and not slot["sym"]:
                slot["sym"] = str((nxt.get("summary") or {}).get("symbol_code") or "")

        days_out: list[DayForecast] = []
        for day in sorted(by_day.keys())[:5]:
            slot = by_day[day]
            try:
                from datetime import date

                weekday = date.fromisoformat(day).strftime("%a")
            except Exception:
                weekday = day[5:]
            code = _symbol_to_wmo(str(slot.get("sym") or ""))
            did = icon_from_wmo(code)
            days_out.append(
                DayForecast(
                    weekday=weekday,
                    high_f=slot["hi"],
                    low_f=slot["lo"],
                    icon_id=did,
                    icon_url=nws_icon_url(did),
                    condition_text=wmo_condition_text(code),
                )
            )

        return WeatherSnapshot(
            location=location,
            current=current,
            hourly=upcoming_hourly(hourly),
            daily=days_out,
            alerts=[],
            fetched_at=time.time(),
            source="met_norway",
        )
