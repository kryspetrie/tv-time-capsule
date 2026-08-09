"""Backward-compatible shim for ``tv_time_capsule.weather_channel``.

Prefer :mod:`tv_time_capsule.weather`.
"""

from __future__ import annotations

from .weather.adapters.geocode_twc import resolve_weather_location
from .weather.adapters.presenter_twc import (
    CDP_PORT,
    WEATHER_URL,
    WeatherChannel,
)

__all__ = [
    "CDP_PORT",
    "WEATHER_URL",
    "WeatherChannel",
    "resolve_weather_location",
]
