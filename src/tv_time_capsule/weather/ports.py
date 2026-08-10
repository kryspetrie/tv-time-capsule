"""Ports (protocols) for weather providers.

The default product path is the **native** pygame Retro Weather presenter
(:class:`~tv_time_capsule.weather.adapters.presenter_native.NativePygamePresenter`).
Live screencast adapters (weather.com/retro, WeatherStar 4000+) remain available
when ``weather.provider`` is set to ``twc`` or ``ws4kp``.

| Port | Typical adapter |
|------|-----------------|
| :class:`WeatherPresenter` | ``presenter_native``, ``presenter_twc``, ``presenter_ws4kp`` |
| :class:`ForecastClient` | ``forecast_resilient.build_forecast_client`` (NWS → Open-Meteo → MET Norway + disk) |
| :class:`AlertClient` | ``alert_feeds.build_alert_client`` (NWS + FlashAlert + RSS/CAP queue) |
| :class:`ForecastSnapshotStore` | ``forecast_cache.DiskForecastStore`` |
| :class:`LocationResolver` | ``geocode_twc.resolve_location`` (function adapter) |
| :class:`RadarLoopSource` | ``radar_image.RidgeRadarLoopSource`` |
| :class:`MusicPlayer` | ``music_pygame.PygameMusicPlayer`` |
| :class:`PageAnnouncer` | ``announcements.AnnouncementPlayer`` |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pygame

from .models import Alert, Location, WeatherSnapshot


@runtime_checkable
class WeatherPresenter(Protocol):
    """Renders weather to a full-bleed pygame surface."""

    @property
    def needs_screencast_pacing(self) -> bool:
        """True when the app should cap clock.tick from effective_fps."""
        ...

    @property
    def effective_fps(self) -> float:
        ...

    @property
    def volume(self) -> int:
        ...

    def start(self) -> bool:
        ...

    def stop(self) -> None:
        ...

    def is_available(self) -> bool:
        ...

    def get_frame(self) -> pygame.Surface | None:
        ...

    def adjust_volume(self, delta: int) -> int:
        ...

    def note_present_stats(self, present_fps: float, blit_ms: float) -> None:
        ...


@runtime_checkable
class ForecastClient(Protocol):
    """Live or cached forecast bundle for a location."""

    def fetch(self, location: Location) -> WeatherSnapshot:
        ...


@runtime_checkable
class AlertClient(Protocol):
    """Active watches/warnings (polled more often than the full forecast)."""

    def fetch_alerts(self, location: Location) -> list[Alert]:
        ...


@runtime_checkable
class ForecastSnapshotStore(Protocol):
    """Durable last-good forecast for cold start / total outage."""

    def save(self, location: Location, snap: WeatherSnapshot) -> None:
        ...

    def load(
        self, location: Location, *, max_age_s: float
    ) -> WeatherSnapshot | None:
        ...


@runtime_checkable
class LocationResolver(Protocol):
    def resolve(self, weather_cfg: dict) -> Location | None:
        ...


@runtime_checkable
class RadarLoopSource(Protocol):
    """Fetches / caches an animated regional radar loop."""

    def fetch_loop(
        self,
        latitude: float,
        longitude: float,
        *,
        maps_cfg: dict[str, Any] | None,
        force_refresh: bool = True,
    ) -> Any:
        """Return a :class:`~tv_time_capsule.weather.adapters.radar_image.RadarLoop` or ``None``."""
        ...


@runtime_checkable
class MusicPlayer(Protocol):
    def start(self, tracks: list[Path], volume: int) -> None:
        ...

    def stop(self) -> None:
        ...

    def tick(self) -> None:
        ...

    def set_volume(self, volume: int) -> None:
        ...

    def adjust_volume(self, delta: int) -> int:
        ...

    @property
    def volume(self) -> int:
        ...


@runtime_checkable
class PageAnnouncer(Protocol):
    def start(self, clips: dict[str, Path], volume: int) -> None:
        ...

    def stop(self) -> None:
        ...

    def play_for_page(self, page: str) -> None:
        ...

    def set_volume(self, volume: int) -> None:
        ...
