"""National Weather Service + Open-Meteo forecast clients."""

from __future__ import annotations

import json
import logging
import math
import re
import time
import urllib.error
import urllib.request
from typing import Any

from ..models import (
    Alert,
    CurrentConditions,
    DayForecast,
    HourlyPeriod,
    Location,
    RegionalCity,
    WeatherSnapshot,
)
from ..ui.icons import icon_from_nws_token, icon_from_wmo, nws_icon_url, wmo_condition_text

LOG = logging.getLogger(__name__)

_UA = "tv-time-capsule/weather (https://github.com/kryspetrie/tv-time-capsule)"

# Major US cities for the regional page (name, lat, lon).
_MAJOR_CITIES: tuple[tuple[str, float, float], ...] = (
    ("New York", 40.71, -74.01),
    ("Boston", 42.36, -71.06),
    ("Philadelphia", 39.95, -75.17),
    ("Washington", 38.91, -77.04),
    ("Atlanta", 33.75, -84.39),
    ("Miami", 25.76, -80.19),
    ("Chicago", 41.88, -87.63),
    ("Detroit", 42.33, -83.05),
    ("Minneapolis", 44.98, -93.27),
    ("St. Louis", 38.63, -90.20),
    ("Dallas", 32.78, -96.80),
    ("Houston", 29.76, -95.37),
    ("Denver", 39.74, -104.99),
    ("Phoenix", 33.45, -112.07),
    ("Las Vegas", 36.17, -115.14),
    ("Los Angeles", 34.05, -118.24),
    ("San Francisco", 37.77, -122.42),
    ("Seattle", 47.61, -122.33),
    ("Portland", 45.52, -122.68),
    ("Salt Lake City", 40.76, -111.89),
    ("Kansas City", 39.10, -94.58),
    ("New Orleans", 29.95, -90.07),
    ("Nashville", 36.16, -86.78),
    ("Charlotte", 35.23, -80.84),
    ("Cleveland", 41.50, -81.69),
    ("Pittsburgh", 40.44, -79.99),
    ("Buffalo", 42.89, -78.88),
    ("Albany", 42.65, -73.76),
    ("Hartford", 41.76, -72.69),
    ("Providence", 41.82, -71.41),
)


def _get_json(url: str, *, timeout: float = 12.0) -> dict[str, Any] | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/geo+json, application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        LOG.info("Weather fetch failed %s: %s", url, exc)
        return None


def _f_from_c(c: float | None) -> float | None:
    if c is None:
        return None
    return round(c * 9.0 / 5.0 + 32.0, 1)


def _as_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _temp_f(props: dict[str, Any]) -> float | None:
    val = props.get("temperature")
    unit = str(props.get("temperatureUnit") or "F").upper()
    try:
        t = float(val)
    except (TypeError, ValueError):
        return None
    if unit.startswith("C"):
        return _f_from_c(t)
    return t


def _precip_pct(props: dict[str, Any]) -> float | None:
    block = props.get("probabilityOfPrecipitation")
    if isinstance(block, dict) and block.get("value") is not None:
        return _as_float(block.get("value"))
    return None


def _precip_in(props: dict[str, Any]) -> float | None:
    for key in ("quantitativePrecipitation", "precipitationAmount"):
        block = props.get(key)
        if not isinstance(block, dict) or block.get("value") is None:
            continue
        val = _as_float(block.get("value"))
        unit = str(block.get("unitCode") or "").lower()
        if val is None:
            continue
        if "milli" in unit or unit.endswith(":mm"):
            return round(val / 25.4, 2)
        return round(val, 2)
    return None


def _humidity_pct(props: dict[str, Any]) -> float | None:
    block = props.get("relativeHumidity")
    if isinstance(block, dict) and block.get("value") is not None:
        return _as_float(block.get("value"))
    return _as_float(props.get("relativeHumidity"))


def _wind_mph_period(props: dict[str, Any]) -> float | None:
    """Parse NWS ``windSpeed`` (``\"5 mph\"`` / ``\"5 to 10 mph\"``)."""
    ws = props.get("windSpeed")
    if isinstance(ws, dict) and ws.get("value") is not None:
        val = _as_float(ws.get("value"))
        unit = str(ws.get("unitCode") or "").lower()
        if val is None:
            return None
        if "km" in unit:
            return round(val * 0.621371, 1)
        return round(val, 1)
    text = str(ws or "")
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def _haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _fmt_sun(iso: str) -> str:
    """``2026-08-09T06:12`` → ``6:12 AM``."""
    text = str(iso or "")
    if "T" in text:
        hm = text.split("T", 1)[1][:5]
    else:
        hm = text[:5]
    try:
        h, m = hm.split(":")
        hour = int(h)
        minute = int(m)
    except (TypeError, ValueError):
        return hm
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def _parse_nws_alerts(alerts: dict[str, Any]) -> list[Alert]:
    from .alert_feeds import parse_nws_alert_features

    return parse_nws_alert_features(alerts)


# Re-export — preferred construction is ``alert_feeds.build_alert_client``.
from .alert_feeds import NwsAlertClient as NwsAlertClient  # noqa: E402


class NwsForecastClient:
    """Fetch forecast, hourly, and alerts from api.weather.gov."""

    def fetch(self, location: Location) -> WeatherSnapshot:
        points = _get_json(
            f"https://api.weather.gov/points/{location.latitude:.4f},{location.longitude:.4f}"
        )
        if not points:
            raise RuntimeError("NWS points lookup failed")
        props = points.get("properties") or {}
        # Prefer relativeLocation city/state when our name is thin.
        rel = ((props.get("relativeLocation") or {}).get("properties") or {})
        city = str(rel.get("city") or "").strip()
        state = str(rel.get("state") or "").strip()
        loc = location
        if city and (not location.name or location.name.lower() == "local"):
            loc = Location(
                latitude=location.latitude,
                longitude=location.longitude,
                name=city,
                context=state or location.context,
                geocode=location.geocode,
            )

        forecast_url = props.get("forecast")
        hourly_url = props.get("forecastHourly")
        stations_url = props.get("observationStations")
        forecast = _get_json(str(forecast_url)) if forecast_url else None
        hourly = _get_json(str(hourly_url)) if hourly_url else None
        alerts = _get_json(
            "https://api.weather.gov/alerts/active"
            f"?point={location.latitude:.4f},{location.longitude:.4f}"
        )

        current = self._current_from_station(stations_url)
        if current is None and hourly:
            current = self._current_from_hourly(hourly)

        narrative = ""
        if forecast:
            narrative = self._narrative(forecast)
            if current is not None and narrative:
                current = CurrentConditions(
                    **{**current.__dict__, "narrative": narrative}
                )

        daily = self._parse_daily(forecast) if forecast else []
        hours = upcoming_hourly(self._parse_hourly(hourly) if hourly else [])
        alert_list = _parse_nws_alerts(alerts) if alerts else []
        radar = str(props.get("radarStation") or "").strip().upper()
        if radar and len(radar) == 3:
            radar = "K" + radar

        return WeatherSnapshot(
            location=loc,
            current=current,
            hourly=hours,
            daily=daily[:5],
            alerts=alert_list,
            radar_station=radar,
            fetched_at=time.time(),
            source="nws",
        )

    def _narrative(self, forecast: dict[str, Any]) -> str:
        for p in (forecast.get("properties") or {}).get("periods") or []:
            if not p.get("isDaytime", True):
                continue
            detail = str(p.get("detailedForecast") or "").strip()
            short = str(p.get("shortForecast") or "").strip()
            return detail or short
        periods = (forecast.get("properties") or {}).get("periods") or []
        if periods:
            return str(periods[0].get("detailedForecast") or periods[0].get("shortForecast") or "")
        return ""

    def _current_from_station(self, stations_url: Any) -> CurrentConditions | None:
        if not stations_url:
            return None
        listing = _get_json(str(stations_url))
        if not listing:
            return None
        features = listing.get("features") or []
        if not features:
            return None
        station_id = (features[0].get("properties") or {}).get("stationIdentifier")
        if not station_id:
            return None
        obs = _get_json(f"https://api.weather.gov/stations/{station_id}/observations/latest")
        if not obs:
            return None
        p = obs.get("properties") or {}

        def _qty(key: str) -> float | None:
            block = p.get(key)
            if not isinstance(block, dict):
                return None
            try:
                return float(block.get("value"))
            except (TypeError, ValueError):
                return None

        temp_c = _qty("temperature")
        wind_kph = _qty("windSpeed")
        gust_kph = _qty("windGust")
        vis_m = _qty("visibility")
        icon = str(p.get("icon") or "")
        text = str(p.get("textDescription") or "")
        wind_deg = _qty("windDirection")
        wind_dir = _deg_to_cardinal(wind_deg) if wind_deg is not None else ""
        return CurrentConditions(
            temperature_f=_f_from_c(temp_c),
            feels_like_f=_f_from_c(_qty("heatIndex") or _qty("windChill") or temp_c),
            humidity_pct=_qty("relativeHumidity"),
            wind_mph=round(wind_kph * 0.621371, 1) if wind_kph is not None else None,
            wind_gust_mph=round(gust_kph * 0.621371, 1) if gust_kph is not None else None,
            wind_dir=wind_dir,
            dewpoint_f=_f_from_c(_qty("dewpoint")),
            pressure_inhg=(
                round(float(_qty("barometricPressure") or 0) / 3386.39, 2)
                if _qty("barometricPressure")
                else None
            ),
            visibility_mi=round(vis_m / 1609.34, 1) if vis_m is not None else None,
            condition_text=text,
            icon_id=icon_from_nws_token(icon) or "unknown",
            icon_url=icon.split("?")[0] + "?size=large" if icon else "",
            observed_at=str(p.get("timestamp") or ""),
        )

    def _current_from_hourly(self, hourly: dict[str, Any]) -> CurrentConditions | None:
        periods = (hourly.get("properties") or {}).get("periods") or []
        if not periods:
            return None
        p0 = periods[0]
        icon = str(p0.get("icon") or "")
        return CurrentConditions(
            temperature_f=_temp_f(p0),
            feels_like_f=_temp_f(p0),
            condition_text=str(p0.get("shortForecast") or ""),
            icon_id=icon_from_nws_token(icon) or "unknown",
            icon_url=icon.split("?")[0] + "?size=large" if icon else "",
            wind_dir=str(p0.get("windDirection") or ""),
            precip_pct=_precip_pct(p0),
            precip_in=_precip_in(p0),
        )

    def _parse_daily(self, forecast: dict[str, Any]) -> list[DayForecast]:
        periods = (forecast.get("properties") or {}).get("periods") or []
        by_day: list[DayForecast] = []
        i = 0
        while i < len(periods) and len(by_day) < 5:
            p = periods[i]
            name = str(p.get("name") or "")
            is_day = bool(p.get("isDaytime", True))
            high = _temp_f(p) if is_day else None
            low = None
            icon = str(p.get("icon") or "")
            text = str(p.get("shortForecast") or "")
            precip = _precip_pct(p)
            amount = _precip_in(p)
            weekday = _nws_weekday_label(name, is_day=is_day)
            start = str(p.get("startTime") or "")
            date_iso = start[:10] if len(start) >= 10 else ""
            if is_day and i + 1 < len(periods) and not periods[i + 1].get("isDaytime", True):
                night = periods[i + 1]
                low = _temp_f(night)
                if precip is None:
                    precip = _precip_pct(night)
                if amount is None:
                    amount = _precip_in(night)
                i += 2
            else:
                if not is_day:
                    low = _temp_f(p)
                i += 1
            by_day.append(
                DayForecast(
                    weekday=weekday,
                    high_f=high,
                    low_f=low,
                    icon_id=icon_from_nws_token(icon) or "unknown",
                    icon_url=icon.split("?")[0] + "?size=large" if icon else "",
                    condition_text=text,
                    precip_pct=precip,
                    precip_in=amount,
                    date_iso=date_iso,
                )
            )
        return by_day

    def _parse_hourly(self, hourly: dict[str, Any]) -> list[HourlyPeriod]:
        out: list[HourlyPeriod] = []
        for p in (hourly.get("properties") or {}).get("periods") or []:
            start = str(p.get("startTime") or "")
            label = _hour_label(start) if start else str(p.get("name") or "")
            icon = str(p.get("icon") or "")
            out.append(
                HourlyPeriod(
                    time_label=label,
                    temperature_f=_temp_f(p),
                    humidity_pct=_humidity_pct(p),
                    wind_mph=_wind_mph_period(p),
                    wind_dir=str(p.get("windDirection") or ""),
                    icon_id=icon_from_nws_token(icon) or "unknown",
                    icon_url=icon.split("?")[0] + "?size=large" if icon else "",
                    condition_text=str(p.get("shortForecast") or ""),
                    precip_pct=_precip_pct(p),
                    precip_in=_precip_in(p),
                    start_epoch=_iso_to_epoch(start),
                )
            )
        return out

def _nws_weekday_label(name: str, *, is_day: bool) -> str:
    text = (name or "").strip()
    low = text.lower()
    if low in ("today", "this afternoon"):
        return "Today"
    if low in ("tonight", "overnight", "this evening"):
        return "Tonight"
    token = text.split()[0] if text else ("Day" if is_day else "Night")
    # Monday → Mon
    return token[:3] if len(token) > 3 else token


def _hour_label(start_iso: str) -> str:
    if len(start_iso) < 16:
        return start_iso
    hm = start_iso[11:16]
    try:
        hour = int(hm[:2])
    except ValueError:
        return hm
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12}{suffix}"


def _iso_to_epoch(
    start_iso: str, *, utc_offset_seconds: int | None = None
) -> float:
    """Parse NWS / Open-Meteo ISO timestamps to unix seconds (0 on failure).

    Open-Meteo with ``timezone=auto`` often returns offset-less local wall
    times plus a top-level ``utc_offset_seconds``. Pass that offset so we do
    not interpret wall times in the machine's timezone.
    """
    text = (start_iso or "").strip()
    if not text:
        return 0.0
    try:
        from datetime import datetime, timedelta, timezone

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        t_idx = text.find("T")
        rest = text[t_idx + 1 :] if t_idx >= 0 else ""
        naive_local = t_idx >= 0 and "+" not in rest and "-" not in rest
        if naive_local:
            if len(text) == 16:
                text = text + ":00"
            if "." in text:
                text = text.split(".", 1)[0]
            dt = datetime.fromisoformat(text)
            if utc_offset_seconds is not None:
                aware = dt.replace(
                    tzinfo=timezone(timedelta(seconds=int(utc_offset_seconds)))
                )
                return aware.timestamp()
            # Prefer UTC over host-local when the location offset is unknown.
            return dt.replace(tzinfo=timezone.utc).timestamp()
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def upcoming_hourly(
    hours: list[HourlyPeriod],
    *,
    now: float | None = None,
    limit: int = 12,
) -> list[HourlyPeriod]:
    """Drop periods whose hour has already ended; keep up to ``limit``.

    Rows with ``start_epoch == 0`` are kept only when *no* timed rows exist
    (legacy / parse failure). Otherwise untimed orphans are dropped so they
    cannot pin a stale label on screen forever.
    """
    t = time.time() if now is None else float(now)
    timed = [h for h in hours if h.start_epoch > 0]
    untimed = [h for h in hours if h.start_epoch <= 0]
    if timed:
        out: list[HourlyPeriod] = []
        for h in timed:
            if h.start_epoch + 3600 <= t:
                continue
            out.append(h)
            if len(out) >= limit:
                break
        return out
    return untimed[:limit]


def _deg_to_cardinal(deg: float) -> str:
    dirs = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return dirs[int((deg + 22.5) // 45) % 8]


class OpenMeteoForecastClient:
    """Open-Meteo forecast (+ enrichment / regional helpers)."""

    def fetch(self, location: Location) -> WeatherSnapshot:
        data = self._forecast_json(location)
        if not data:
            raise RuntimeError("Open-Meteo fetch failed")
        current, hourly, daily = self._parse_bundle(data)
        return WeatherSnapshot(
            location=location,
            current=current,
            hourly=hourly,
            daily=daily,
            alerts=[],
            fetched_at=time.time(),
            source="open-meteo",
        )

    def enrich(self, location: Location, snap: WeatherSnapshot) -> WeatherSnapshot:
        """Fill sunrise/sunset/precip/dewpoint gaps from Open-Meteo."""
        data = self._forecast_json(location)
        if not data:
            return snap
        current_om, hourly_om, daily_om = self._parse_bundle(data)
        cur = snap.current
        if cur is None:
            snap.current = current_om
        else:
            snap.current = CurrentConditions(
                temperature_f=cur.temperature_f if cur.temperature_f is not None else current_om.temperature_f,
                feels_like_f=cur.feels_like_f if cur.feels_like_f is not None else current_om.feels_like_f,
                humidity_pct=cur.humidity_pct if cur.humidity_pct is not None else current_om.humidity_pct,
                wind_mph=cur.wind_mph if cur.wind_mph is not None else current_om.wind_mph,
                wind_gust_mph=cur.wind_gust_mph if cur.wind_gust_mph is not None else current_om.wind_gust_mph,
                wind_dir=cur.wind_dir or current_om.wind_dir,
                dewpoint_f=cur.dewpoint_f if cur.dewpoint_f is not None else current_om.dewpoint_f,
                pressure_inhg=cur.pressure_inhg if cur.pressure_inhg is not None else current_om.pressure_inhg,
                visibility_mi=cur.visibility_mi,
                precip_pct=cur.precip_pct if cur.precip_pct is not None else current_om.precip_pct,
                precip_in=cur.precip_in if cur.precip_in is not None else current_om.precip_in,
                condition_text=cur.condition_text or current_om.condition_text,
                narrative=cur.narrative or current_om.narrative,
                sunrise=cur.sunrise or current_om.sunrise,
                sunset=cur.sunset or current_om.sunset,
                icon_id=cur.icon_id if cur.icon_id != "unknown" else current_om.icon_id,
                icon_url=cur.icon_url or current_om.icon_url,
                observed_at=cur.observed_at,
            )
        # Merge precip / wind / humidity by matching hour start (not list index).
        om_by_hour: dict[int, HourlyPeriod] = {}
        for om in hourly_om:
            if om.start_epoch > 0:
                om_by_hour[int(om.start_epoch) // 3600] = om
        for i, h in enumerate(snap.hourly):
            om: HourlyPeriod | None = None
            if h.start_epoch > 0:
                om = om_by_hour.get(int(h.start_epoch) // 3600)
            elif i < len(hourly_om):
                # Untimed legacy rows only — index fallback.
                om = hourly_om[i]
            if om is None:
                continue
            patch: dict[str, Any] = {}
            if h.precip_pct is None and om.precip_pct is not None:
                patch["precip_pct"] = om.precip_pct
            if h.precip_in is None and om.precip_in is not None:
                patch["precip_in"] = om.precip_in
            if h.humidity_pct is None and om.humidity_pct is not None:
                patch["humidity_pct"] = om.humidity_pct
            if h.wind_mph is None and om.wind_mph is not None:
                patch["wind_mph"] = om.wind_mph
            if not h.wind_dir and om.wind_dir:
                patch["wind_dir"] = om.wind_dir
            if h.feels_like_f is None and om.feels_like_f is not None:
                patch["feels_like_f"] = om.feels_like_f
            if patch:
                snap.hourly[i] = HourlyPeriod(**{**h.__dict__, **patch})
        om_by_date = {d.date_iso: d for d in daily_om if d.date_iso}
        for i, d in enumerate(snap.daily):
            om = om_by_date.get(d.date_iso) if d.date_iso else None
            if om is None and not d.date_iso and i < len(daily_om):
                # Untimed legacy rows only — index fallback.
                om = daily_om[i]
            if om is None:
                continue
            patch = {}
            if d.precip_pct is None:
                patch["precip_pct"] = om.precip_pct
            if d.precip_in is None:
                patch["precip_in"] = om.precip_in
            if not d.condition_text:
                patch["condition_text"] = om.condition_text
            if not d.date_iso and om.date_iso:
                patch["date_iso"] = om.date_iso
            if patch:
                snap.daily[i] = DayForecast(**{**d.__dict__, **patch})
        return snap

    def fetch_regional(self, location: Location, *, limit: int = 8) -> list[RegionalCity]:
        ranked = sorted(
            (
                (_haversine_mi(location.latitude, location.longitude, lat, lon), name, lat, lon)
                for name, lat, lon in _MAJOR_CITIES
            ),
            key=lambda t: t[0],
        )
        # Skip the city that is essentially our own location (< 25 mi).
        picks = [t for t in ranked if t[0] >= 25.0][:limit]
        if not picks:
            picks = ranked[:limit]
        out: list[RegionalCity] = []
        for dist, name, lat, lon in picks:
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat:.4f}&longitude={lon:.4f}"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m,wind_direction_10m"
                "&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=auto"
            )
            data = _get_json(url, timeout=8.0)
            if not data:
                continue
            cur = data.get("current") or {}
            try:
                wmo = int(cur.get("weather_code"))
            except (TypeError, ValueError):
                wmo = 0
            iid = icon_from_wmo(wmo)
            wind_deg = _as_float(cur.get("wind_direction_10m"))
            out.append(
                RegionalCity(
                    name=name,
                    temperature_f=_as_float(cur.get("temperature_2m")),
                    feels_like_f=_as_float(cur.get("apparent_temperature")),
                    humidity_pct=_as_float(cur.get("relative_humidity_2m")),
                    wind_mph=_as_float(cur.get("wind_speed_10m")),
                    wind_dir=_deg_to_cardinal(wind_deg) if wind_deg is not None else "",
                    condition_text=wmo_condition_text(wmo),
                    icon_id=iid,
                    icon_url=nws_icon_url(iid),
                    distance_mi=round(dist),
                )
            )
        return out

    def _forecast_json(self, location: Location) -> dict[str, Any] | None:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={location.latitude:.4f}&longitude={location.longitude:.4f}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            "dewpoint_2m,weather_code,wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
            "surface_pressure,precipitation"
            "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,"
            "weather_code,precipitation_probability,precipitation,"
            "wind_speed_10m,wind_direction_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,precipitation_sum,sunrise,sunset"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
            "&timezone=auto&forecast_days=5"
        )
        return _get_json(url)

    def _parse_bundle(
        self, data: dict[str, Any]
    ) -> tuple[CurrentConditions, list[HourlyPeriod], list[DayForecast]]:
        cur = data.get("current") or {}
        try:
            wmo = int(cur.get("weather_code"))
        except (TypeError, ValueError):
            wmo = 0
        wind_deg = _as_float(cur.get("wind_direction_10m"))
        daily = data.get("daily") or {}
        sunrise = _fmt_sun((daily.get("sunrise") or [""])[0]) if daily.get("sunrise") else ""
        sunset = _fmt_sun((daily.get("sunset") or [""])[0]) if daily.get("sunset") else ""
        pressure_hpa = _as_float(cur.get("surface_pressure"))
        iid = icon_from_wmo(wmo)
        utc_offset: int | None = None
        raw_off = data.get("utc_offset_seconds")
        if isinstance(raw_off, (int, float)):
            utc_offset = int(raw_off)
        current = CurrentConditions(
            temperature_f=_as_float(cur.get("temperature_2m")),
            feels_like_f=_as_float(cur.get("apparent_temperature")),
            humidity_pct=_as_float(cur.get("relative_humidity_2m")),
            wind_mph=_as_float(cur.get("wind_speed_10m")),
            wind_gust_mph=_as_float(cur.get("wind_gusts_10m")),
            wind_dir=_deg_to_cardinal(wind_deg) if wind_deg is not None else "",
            dewpoint_f=_as_float(cur.get("dewpoint_2m")),
            pressure_inhg=round(pressure_hpa * 0.02953, 2) if pressure_hpa is not None else None,
            precip_in=_as_float(cur.get("precipitation")),
            condition_text=wmo_condition_text(wmo),
            sunrise=sunrise,
            sunset=sunset,
            icon_id=iid,
            icon_url=nws_icon_url(iid),
        )
        hourly: list[HourlyPeriod] = []
        h = data.get("hourly") or {}
        times = h.get("time") or []
        temps = h.get("temperature_2m") or []
        feels = h.get("apparent_temperature") or []
        hums = h.get("relative_humidity_2m") or []
        codes = h.get("weather_code") or []
        precip = h.get("precipitation_probability") or []
        amounts = h.get("precipitation") or []
        winds = h.get("wind_speed_10m") or []
        wdirs = h.get("wind_direction_10m") or []
        now = time.time()
        for i in range(len(times)):
            t = str(times[i])
            start_epoch = _iso_to_epoch(t, utc_offset_seconds=utc_offset)
            if start_epoch > 0 and start_epoch + 3600 <= now:
                continue
            try:
                code = int(codes[i])
            except (TypeError, ValueError, IndexError):
                code = 0
            hid = icon_from_wmo(code)
            wind_deg = _as_float(wdirs[i] if i < len(wdirs) else None)
            hourly.append(
                HourlyPeriod(
                    time_label=_hour_label(t) if "T" in t else t,
                    temperature_f=_as_float(temps[i] if i < len(temps) else None),
                    feels_like_f=_as_float(feels[i] if i < len(feels) else None),
                    humidity_pct=_as_float(hums[i] if i < len(hums) else None),
                    wind_mph=_as_float(winds[i] if i < len(winds) else None),
                    wind_dir=_deg_to_cardinal(wind_deg) if wind_deg is not None else "",
                    icon_id=hid,
                    icon_url=nws_icon_url(hid),
                    condition_text=wmo_condition_text(code),
                    precip_pct=_as_float(precip[i] if i < len(precip) else None),
                    precip_in=_as_float(amounts[i] if i < len(amounts) else None),
                    start_epoch=start_epoch,
                )
            )
            if len(hourly) >= 12:
                break

        days_out: list[DayForecast] = []
        days = daily.get("time") or []
        for i in range(min(5, len(days))):
            try:
                code = int((daily.get("weather_code") or [0])[i])
            except (TypeError, ValueError, IndexError):
                code = 0
            day = str(days[i])
            date_iso = day[:10] if len(day) >= 10 else ""
            try:
                from datetime import date

                weekday = date.fromisoformat(date_iso).strftime("%a") if date_iso else day
            except Exception:
                weekday = day[5:10] if len(day) >= 10 else day
            did = icon_from_wmo(code)
            days_out.append(
                DayForecast(
                    weekday=weekday,
                    high_f=_as_float((daily.get("temperature_2m_max") or [None])[i]),
                    low_f=_as_float((daily.get("temperature_2m_min") or [None])[i]),
                    icon_id=did,
                    icon_url=nws_icon_url(did),
                    condition_text=wmo_condition_text(code),
                    precip_pct=_as_float(
                        (daily.get("precipitation_probability_max") or [None])[i]
                    ),
                    precip_in=_as_float((daily.get("precipitation_sum") or [None])[i]),
                    date_iso=date_iso,
                )
            )
        return current, hourly, days_out