"""Weather domain models shared by all providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Location:
    """Resolved geographic location for forecasts."""

    latitude: float
    longitude: float
    name: str = ""
    context: str = ""
    geocode: str = ""

    def to_cookie_dict(self) -> dict[str, Any]:
        """Shape expected by the legacy TWC Chrome cookie injector."""
        geo = self.geocode or f"{self.latitude},{self.longitude}"
        return {
            "geocode": geo,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "name": self.name,
            "context": self.context,
        }

    def display_name(self) -> str:
        """Compact ``City, ST`` (state/country codes; long towns truncated)."""
        from .ui.text import format_place_line

        return format_place_line(self.name, self.context)


@dataclass(frozen=True)
class CurrentConditions:
    temperature_f: float | None = None
    feels_like_f: float | None = None
    humidity_pct: float | None = None
    wind_mph: float | None = None
    wind_gust_mph: float | None = None
    wind_dir: str = ""
    dewpoint_f: float | None = None
    pressure_inhg: float | None = None
    visibility_mi: float | None = None
    precip_pct: float | None = None
    precip_in: float | None = None
    condition_text: str = ""
    narrative: str = ""
    sunrise: str = ""
    sunset: str = ""
    icon_id: str = "unknown"
    icon_url: str = ""
    observed_at: str = ""


@dataclass(frozen=True)
class HourlyPeriod:
    time_label: str
    temperature_f: float | None = None
    feels_like_f: float | None = None
    humidity_pct: float | None = None
    wind_mph: float | None = None
    wind_dir: str = ""
    icon_id: str = "unknown"
    icon_url: str = ""
    condition_text: str = ""
    precip_pct: float | None = None
    precip_in: float | None = None
    # Unix epoch for period start (0 = unknown; display keeps the row).
    start_epoch: float = 0.0


@dataclass(frozen=True)
class DayForecast:
    weekday: str
    high_f: float | None = None
    low_f: float | None = None
    icon_id: str = "unknown"
    icon_url: str = ""
    condition_text: str = ""
    precip_pct: float | None = None
    precip_in: float | None = None
    # Calendar day ``YYYY-MM-DD`` when known (enrich / cache matching).
    date_iso: str = ""


@dataclass(frozen=True)
class RegionalCity:
    """Nearby major-city snapshot for the regional page."""

    name: str
    temperature_f: float | None = None
    feels_like_f: float | None = None
    humidity_pct: float | None = None
    wind_mph: float | None = None
    wind_dir: str = ""
    condition_text: str = ""
    icon_id: str = "unknown"
    icon_url: str = ""
    distance_mi: float | None = None


@dataclass(frozen=True)
class Alert:
    """Weather / school / emergency alert for the lower-thirds marquee."""

    severity: str
    headline: str
    description: str = ""
    event: str = ""
    # weather | emergency | school | other — used for marquee prefixes / ordering.
    category: str = "weather"
    source: str = ""


@dataclass
class WeatherSnapshot:
    """Latest fetched forecast bundle for the native presenter."""

    location: Location
    current: CurrentConditions | None = None
    hourly: list[HourlyPeriod] = field(default_factory=list)
    daily: list[DayForecast] = field(default_factory=list)
    regional: list[RegionalCity] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    radar_station: str = ""
    fetched_at: float = 0.0
    source: str = ""
