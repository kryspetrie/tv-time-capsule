"""Weather channel package (ports, adapters, native + screencast providers)."""

from __future__ import annotations

from .adapters.geocode_twc import resolve_location, resolve_weather_location
from .models import (
    Alert,
    CurrentConditions,
    DayForecast,
    HourlyPeriod,
    Location,
    WeatherSnapshot,
)
from .resolve import normalize_provider, resolve_provider
from .service import WeatherSession

__all__ = [
    "Alert",
    "CurrentConditions",
    "DayForecast",
    "HourlyPeriod",
    "Location",
    "WeatherSession",
    "WeatherSnapshot",
    "normalize_provider",
    "resolve_location",
    "resolve_provider",
    "resolve_weather_location",
]
