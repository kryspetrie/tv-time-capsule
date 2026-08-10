"""Weather adapters (live presenters, forecast providers, radar, audio)."""

from __future__ import annotations

from .alert_feeds import NwsAlertClient, QueuedAlertClient, build_alert_client
from .forecast_cache import DiskForecastStore
from .forecast_met_norway import MetNorwayForecastClient
from .forecast_nws import NwsForecastClient, OpenMeteoForecastClient
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
    "QueuedAlertClient",
    "ResilientForecastClient",
    "RidgeRadarLoopSource",
    "build_alert_client",
    "build_forecast_client",
]
