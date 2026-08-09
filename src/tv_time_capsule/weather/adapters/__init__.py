"""Weather adapters (live presenters, forecast providers, radar, audio)."""

from __future__ import annotations

from .forecast_cache import DiskForecastStore
from .forecast_met_norway import MetNorwayForecastClient
from .forecast_nws import NwsAlertClient, NwsForecastClient, OpenMeteoForecastClient
from .forecast_resilient import (
    CachedForecastClient,
    CompositeForecastClient,
    ResilientForecastClient,
    build_forecast_client,
)
from .radar_image import RidgeRadarLoopSource

__all__ = [
    "CachedForecastClient",
    "CompositeForecastClient",
    "DiskForecastStore",
    "MetNorwayForecastClient",
    "NwsAlertClient",
    "NwsForecastClient",
    "OpenMeteoForecastClient",
    "ResilientForecastClient",
    "RidgeRadarLoopSource",
    "build_forecast_client",
]
