"""Weather session facade used by the pygame app.

Composes a :class:`~tv_time_capsule.weather.ports.WeatherPresenter` adapter
chosen by :func:`~tv_time_capsule.weather.resolve.resolve_provider`. Default
is the native pygame channel; ``twc`` / ``ws4kp`` are live Chrome opt-ins.
"""

from __future__ import annotations

import logging
from typing import Any

import pygame

from .adapters.geocode_twc import resolve_location, resolve_weather_location
from .adapters.presenter_twc import WeatherChannel as TwcScreencastPresenter
from .ports import MusicPlayer, WeatherPresenter
from .resolve import ResolvedProvider, resolve_provider

LOG = logging.getLogger(__name__)


class WeatherSession:
    """Owns the active weather presenter (+ optional music for native)."""

    def __init__(
        self,
        presenter: WeatherPresenter,
        *,
        provider: ResolvedProvider,
        music: MusicPlayer | None = None,
    ) -> None:
        self._presenter = presenter
        self.provider = provider
        self._music = music

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        width: int,
        height: int,
    ) -> WeatherSession:
        """Factory: pick a presenter adapter from ``weather.provider``."""
        weather_cfg = config.get("weather") or {}
        if not isinstance(weather_cfg, dict):
            weather_cfg = {}
        provider = resolve_provider(weather_cfg)
        if provider == "ws4kp":
            try:
                from .adapters.presenter_ws4kp import Ws4kpScreencastPresenter

                location = resolve_location(weather_cfg)
                presenter: WeatherPresenter = Ws4kpScreencastPresenter(
                    width,
                    height,
                    location=location.to_cookie_dict() if location else None,
                    screencast=weather_cfg.get("screencast"),
                    base_url=str(
                        weather_cfg.get("ws4kp_base_url")
                        or "https://weatherstar.netbymatt.com/"
                    ),
                )
                return cls(presenter, provider=provider)
            except Exception:
                LOG.exception("ws4kp presenter unavailable; falling back to twc")
                provider = "twc"
        if provider == "native":
            try:
                from .adapters.presenter_native import NativePygamePresenter

                presenter = NativePygamePresenter(
                    width, height, weather_cfg=weather_cfg
                )
                return cls(presenter, provider="native")
            except Exception:
                LOG.exception("native presenter unavailable; falling back to twc")
                provider = "twc"

        location_dict = resolve_weather_location(weather_cfg)
        presenter = TwcScreencastPresenter(
            width,
            height,
            location=location_dict,
            screencast=weather_cfg.get("screencast"),
        )
        return cls(presenter, provider="twc")

    @property
    def needs_screencast_pacing(self) -> bool:
        return bool(getattr(self._presenter, "needs_screencast_pacing", False))

    @property
    def effective_fps(self) -> float:
        try:
            return float(self._presenter.effective_fps)
        except Exception:
            return 10.0

    @property
    def volume(self) -> int:
        return int(self._presenter.volume)

    def start(self) -> bool:
        ok = bool(self._presenter.start())
        if ok and self._music is not None:
            try:
                self._music.start([], self._presenter.volume)
            except Exception:
                LOG.exception("Weather music start failed")
        return ok

    def stop(self) -> None:
        if self._music is not None:
            try:
                self._music.stop()
            except Exception:
                LOG.exception("Weather music stop failed")
        self._presenter.stop()

    def is_available(self) -> bool:
        return bool(self._presenter.is_available())

    def get_frame(self) -> pygame.Surface | None:
        return self._presenter.get_frame()

    def adjust_volume(self, delta: int) -> int:
        vol = self._presenter.adjust_volume(delta)
        if self._music is not None:
            try:
                self._music.adjust_volume(delta)
            except Exception:
                pass
        return vol

    def note_present_stats(self, present_fps: float, blit_ms: float) -> None:
        self._presenter.note_present_stats(present_fps, blit_ms)
