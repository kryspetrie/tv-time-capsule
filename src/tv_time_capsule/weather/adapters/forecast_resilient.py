"""Resilient forecast client: NWS → Open-Meteo → MET Norway + disk cache.

Composes :class:`~tv_time_capsule.weather.ports.ForecastClient` adapters so the
native presenter never depends on a single upstream.
"""

from __future__ import annotations

import logging
from typing import Sequence

from ..models import Location, WeatherSnapshot
from ..ports import ForecastClient, ForecastSnapshotStore
from .forecast_cache import DiskForecastStore
from .forecast_met_norway import MetNorwayForecastClient
from .forecast_nws import NwsForecastClient, OpenMeteoForecastClient, upcoming_hourly
from .radar_image import resolve_nws_radar_station

LOG = logging.getLogger(__name__)


class ResilientForecastClient:
    """Try live adapters in order; enrich/regional from Open-Meteo when possible."""

    def __init__(
        self,
        clients: Sequence[ForecastClient] | None = None,
        *,
        open_meteo: OpenMeteoForecastClient | None = None,
    ) -> None:
        self._om = open_meteo or OpenMeteoForecastClient()
        self._clients: list[ForecastClient] = list(
            clients
            or (
                NwsForecastClient(),
                self._om,
                MetNorwayForecastClient(),
            )
        )

    def fetch(self, location: Location) -> WeatherSnapshot:
        errors: list[str] = []
        snap: WeatherSnapshot | None = None
        for client in self._clients:
            name = type(client).__name__
            try:
                snap = client.fetch(location)
                LOG.info("Weather forecast from %s", name)
                break
            except Exception as exc:
                LOG.info("Weather provider %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
        if snap is None:
            raise RuntimeError(
                "All weather providers failed (" + "; ".join(errors) + ")"
            )

        # Enrich + regional from Open-Meteo even when primary was NWS / MET.
        try:
            snap = self._om.enrich(location, snap)
        except Exception:
            LOG.debug("Open-Meteo enrich failed", exc_info=True)
        if not snap.regional:
            try:
                snap.regional = self._om.fetch_regional(location)
            except Exception:
                LOG.debug("Regional cities fetch failed", exc_info=True)

        if not snap.radar_station:
            try:
                site = resolve_nws_radar_station(
                    location.latitude, location.longitude
                )
                if site:
                    snap.radar_station = site
            except Exception:
                LOG.debug("Radar station lookup failed", exc_info=True)

        snap.hourly = upcoming_hourly(list(snap.hourly))
        return snap


class CachedForecastClient:
    """Write-through disk cache; serve last-good snapshot when live chain fails."""

    def __init__(
        self,
        inner: ForecastClient,
        store: ForecastSnapshotStore | None = None,
        *,
        max_age_s: float = 6 * 3600.0,
    ) -> None:
        self._inner = inner
        self._store = store or DiskForecastStore()
        self._max_age_s = max_age_s

    def fetch(self, location: Location) -> WeatherSnapshot:
        try:
            snap = self._inner.fetch(location)
        except Exception as exc:
            cached = self._store.load(location, max_age_s=self._max_age_s)
            if cached is not None:
                LOG.warning(
                    "Live forecast failed (%s); using disk cache from %s",
                    exc,
                    cached.source,
                )
                return cached
            raise
        try:
            self._store.save(location, snap)
        except Exception:
            LOG.debug("Forecast cache save failed", exc_info=True)
        return snap


def build_forecast_client() -> ForecastClient:
    """Default product stack: resilient live providers + disk last-good."""
    return CachedForecastClient(ResilientForecastClient())


class CompositeForecastClient:
    """Back-compat alias for :func:`build_forecast_client`."""

    def __init__(self) -> None:
        self._inner = build_forecast_client()

    def fetch(self, location: Location) -> WeatherSnapshot:
        return self._inner.fetch(location)
