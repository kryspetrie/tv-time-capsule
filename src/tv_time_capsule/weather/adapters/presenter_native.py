"""Pygame-native Retro Weather presenter (no Chromium)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pygame

from ...fonts import make_font
from ..adapters.forecast_nws import NwsAlertClient, upcoming_hourly
from ..adapters.forecast_resilient import build_forecast_client
from ..adapters.geocode_twc import resolve_location
from ..adapters.radar_image import RadarLoop, RidgeRadarLoopSource
from ..models import Location, WeatherSnapshot
from ..ports import AlertClient, ForecastClient, PageAnnouncer, RadarLoopSource
from ..ui.lower_thirds import LowerThirds, bar_height
from ..ui.pages import (
    CITIES_PER_PAGE,
    HOURS_PER_PAGE,
    draw_alerts_page,
    draw_current,
    draw_daily,
    draw_hourly,
    draw_radar,
    draw_regional,
)
from .announcements import AnnouncementPlayer, discover_announcements
from .music_pygame import PygameMusicPlayer, discover_tracks

LOG = logging.getLogger(__name__)

# Re-fetch forecast on a short cadence; also kick on each full page-loop wrap.
_FORECAST_REFRESH_S = 180.0
_FORECAST_LOOP_MIN_GAP_S = 45.0
_ALERT_REFRESH_S = 90.0
_RADAR_REFRESH_S = 300.0
_RADAR_RETRY_S = 60.0


class NativePygamePresenter:
    """Standard-layout weather channel drawn entirely in pygame."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        weather_cfg: dict[str, Any] | None = None,
        forecast: ForecastClient | None = None,
        alerts: AlertClient | None = None,
        radar_source: RadarLoopSource | None = None,
        announcements: PageAnnouncer | None = None,
    ) -> None:
        self._width = max(width, 320)
        self._height = max(height, 240)
        self._cfg = dict(weather_cfg or {})
        native = self._cfg.get("native") if isinstance(self._cfg.get("native"), dict) else {}
        self._page_seconds = float(native.get("page_seconds") or 14)
        self._alert_style = str(native.get("alert_style") or "marquee").lower()
        if self._alert_style not in ("marquee", "page"):
            self._alert_style = "marquee"
        self._maps_cfg = (
            dict(self._cfg["maps"])
            if isinstance(self._cfg.get("maps"), dict)
            else {}
        )
        music_cfg = self._cfg.get("music") if isinstance(self._cfg.get("music"), dict) else {}
        self._music_enabled = bool(music_cfg.get("enabled", True))
        try:
            self._volume = int(music_cfg.get("volume", 70))
        except (TypeError, ValueError):
            self._volume = 70
        self._music_dir = music_cfg.get("directory")
        self._announcements_dir = music_cfg.get("announcements_directory")
        self._music = PygameMusicPlayer()
        self._announcements: PageAnnouncer = announcements or AnnouncementPlayer()
        self._forecast: ForecastClient = forecast or build_forecast_client()
        self._alerts: AlertClient = alerts or NwsAlertClient()
        self._radar_source: RadarLoopSource = radar_source or RidgeRadarLoopSource()
        self._lock = threading.Lock()
        self._snap: WeatherSnapshot | None = None
        self._radar_loop: RadarLoop | None = None
        self._radar_prefetching = False
        self._radar_prefetch_gen = 0
        self._radar_frame_idx = 0
        self._radar_frame_elapsed_ms = 0.0
        self._last_radar_ok_at = 0.0
        self._last_radar_attempt_at = 0.0
        self._forecast_refreshing = False
        self._last_forecast_ok_at = 0.0
        self._forecast_stale = False
        self._alerts_refreshing = False
        self._last_alerts_ok_at = 0.0
        self._error: str | None = None
        self._available = False
        self._running = False
        self._thread: threading.Thread | None = None
        self._page_idx = 0
        self._page_started = 0.0
        self._active_page: str | None = None
        self._active_announce: str | None = None
        self._last_draw = time.time()
        self._lower = LowerThirds()
        self._fonts: dict[str, pygame.font.Font] | None = None
        self._frame = pygame.Surface((self._width, self._height))

    @property
    def needs_screencast_pacing(self) -> bool:
        return False

    @property
    def effective_fps(self) -> float:
        return 30.0

    @property
    def volume(self) -> int:
        return int(self._volume)

    def _maps_enabled(self) -> bool:
        return self._maps_cfg.get("enabled") is not False

    def _prune_hourly(self, snap: WeatherSnapshot) -> WeatherSnapshot:
        """Drop elapsed hours in-place so the UI advances without a network hit."""
        pruned = upcoming_hourly(list(snap.hourly))
        if pruned is snap.hourly or pruned == list(snap.hourly):
            return snap
        snap.hourly = pruned
        return snap

    def _start_forecast_refresh(self, *, reason: str, min_gap_s: float) -> None:
        """Background re-fetch; on failure keep the last good snapshot (cached)."""
        now = time.time()
        with self._lock:
            if self._forecast_refreshing:
                return
            if (
                self._last_forecast_ok_at > 0
                and now - self._last_forecast_ok_at < min_gap_s
            ):
                return
            self._forecast_refreshing = True

        def _worker() -> None:
            loc = resolve_location(self._cfg)
            if loc is None:
                with self._lock:
                    self._forecast_refreshing = False
                return
            try:
                snap = self._forecast.fetch(loc)
                stale = "disk" in (snap.source or "")
                with self._lock:
                    self._snap = snap
                    self._last_forecast_ok_at = time.time()
                    self._forecast_stale = stale
                LOG.debug(
                    "Weather forecast refreshed (%s) source=%s",
                    reason,
                    snap.source,
                )
            except Exception:
                LOG.exception(
                    "Weather forecast refresh failed (%s); keeping cached snapshot",
                    reason,
                )
                with self._lock:
                    if self._snap is not None:
                        self._forecast_stale = True
            finally:
                with self._lock:
                    self._forecast_refreshing = False

        threading.Thread(
            target=_worker, daemon=True, name="weather-forecast-refresh"
        ).start()

    def _start_alerts_refresh(self, location: Location) -> None:
        """Poll watches/warnings more often than the full forecast bundle."""
        now = time.time()
        with self._lock:
            if self._alerts_refreshing:
                return
            if (
                self._last_alerts_ok_at > 0
                and now - self._last_alerts_ok_at < _ALERT_REFRESH_S
            ):
                return
            self._alerts_refreshing = True

        def _worker() -> None:
            try:
                alerts = self._alerts.fetch_alerts(location)
                with self._lock:
                    if self._snap is not None:
                        self._snap.alerts = alerts
                    self._last_alerts_ok_at = time.time()
            except Exception:
                LOG.debug("Weather alerts refresh failed", exc_info=True)
            finally:
                with self._lock:
                    self._alerts_refreshing = False

        threading.Thread(
            target=_worker, daemon=True, name="weather-alerts-refresh"
        ).start()

    def _start_radar_prefetch(self, snap: WeatherSnapshot, *, force_refresh: bool) -> None:
        """Download the regional RIDGE loop in the background (Current page)."""
        if not self._maps_enabled():
            return
        with self._lock:
            if self._radar_prefetching:
                return
            self._radar_prefetching = True
            self._radar_prefetch_gen += 1
            self._last_radar_attempt_at = time.time()
            gen = self._radar_prefetch_gen

        def _worker() -> None:
            loop: RadarLoop | None = None
            try:
                loop = self._radar_source.fetch_loop(
                    snap.location.latitude,
                    snap.location.longitude,
                    maps_cfg=self._maps_cfg,
                    force_refresh=force_refresh,
                )
            except Exception:
                LOG.exception("Weather radar loop fetch failed")
                loop = None
            with self._lock:
                if gen != self._radar_prefetch_gen:
                    # A newer prefetch superseded this one.
                    return
                if loop is not None and loop.ready:
                    self._radar_loop = loop
                    self._radar_frame_idx = 0
                    self._radar_frame_elapsed_ms = 0.0
                    self._last_radar_ok_at = time.time()
                self._radar_prefetching = False

        threading.Thread(
            target=_worker, daemon=True, name="weather-radar-prefetch"
        ).start()

    def start(self) -> bool:
        if self._available:
            return True
        loc = resolve_location(self._cfg)
        if loc is None:
            self._error = "location required"
            LOG.warning("Native weather: no location configured")
            return False
        self._running = True
        try:
            snap = self._forecast.fetch(loc)
            with self._lock:
                self._snap = snap
                self._radar_loop = None
                self._last_forecast_ok_at = time.time()
                self._last_alerts_ok_at = time.time()
                self._forecast_stale = "disk" in (snap.source or "")
            self._available = True
        except Exception as exc:
            LOG.exception("Native weather initial fetch failed")
            self._error = str(exc)
            self._running = False
            return False
        self._page_started = time.time()
        self._active_page = None
        self._active_announce = None
        self._thread = threading.Thread(
            target=self._refresh_loop, daemon=True, name="weather-native-refresh"
        )
        self._thread.start()
        if self._music_enabled:
            tracks = discover_tracks(
                Path(self._music_dir) if self._music_dir else None
            )
            self._music.start(tracks, self._volume)
            clips = discover_announcements(
                Path(self._announcements_dir)
                if self._announcements_dir
                else None
            )
            pages = {"current", "hourly", "daily", "regional", "radar", "alerts"}
            clips = {k: v for k, v in clips.items() if k in pages}
            self._announcements.start(clips, self._volume)
        return True

    def stop(self) -> None:
        self._running = False
        self._available = False
        self._announcements.stop()
        self._music.stop()
        with self._lock:
            self._radar_prefetch_gen += 1
            self._radar_prefetching = False
            self._radar_loop = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_available(self) -> bool:
        return self._available

    def _advance_radar_frame(self, loop: RadarLoop, dt_ms: float) -> pygame.Surface | None:
        if not loop.frames:
            return None
        n = len(loop.frames)
        idx = self._radar_frame_idx % n
        dur = loop.durations_ms[idx] if idx < len(loop.durations_ms) else 200
        self._radar_frame_elapsed_ms += max(0.0, dt_ms)
        while self._radar_frame_elapsed_ms >= dur and n > 0:
            self._radar_frame_elapsed_ms -= dur
            self._radar_frame_idx = (self._radar_frame_idx + 1) % n
            idx = self._radar_frame_idx
            dur = loop.durations_ms[idx] if idx < len(loop.durations_ms) else 200
        return loop.frames[self._radar_frame_idx % n]

    def get_frame(self) -> pygame.Surface | None:
        if not self._available:
            return None
        if self._music_enabled:
            self._music.tick()
        fonts = self._ensure_fonts()
        now = time.time()
        dt_ms = (now - self._last_draw) * 1000.0
        self._last_draw = now
        with self._lock:
            snap = self._snap
            radar_loop = self._radar_loop
            radar_prefetching = self._radar_prefetching
            forecast_stale = self._forecast_stale
            last_ok = self._last_forecast_ok_at
            last_radar = self._last_radar_ok_at
            last_radar_attempt = self._last_radar_attempt_at
            last_alerts = self._last_alerts_ok_at
        if snap is None:
            self._frame.fill((0, 0, 0))
            return self._frame.copy()

        # Drop elapsed hours immediately (no network) so 2PM vanishes after 3:00.
        snap = self._prune_hourly(snap)

        pages = self._page_names(snap, has_radar=self._maps_enabled())
        if self._page_idx >= len(pages):
            self._page_idx = 0
        wrapped = False
        if now - self._page_started >= self._page_seconds:
            prev_idx = self._page_idx
            self._page_idx = (self._page_idx + 1) % max(1, len(pages))
            self._page_started = now
            # Full carousel wrap → refresh forecast + radar.
            if self._page_idx == 0 and prev_idx != 0:
                wrapped = True
                self._start_forecast_refresh(
                    reason="loop", min_gap_s=_FORECAST_LOOP_MIN_GAP_S
                )
        # Periodic refresh even if the user stays on one page a long time.
        if last_ok <= 0 or now - last_ok >= _FORECAST_REFRESH_S:
            self._start_forecast_refresh(
                reason="timer", min_gap_s=_FORECAST_REFRESH_S
            )
        if last_alerts <= 0 or now - last_alerts >= _ALERT_REFRESH_S:
            self._start_alerts_refresh(snap.location)
        page = pages[self._page_idx % len(pages)]
        announce_key = page.split(":", 1)[0]
        entered = page != self._active_page
        if entered:
            self._active_page = page
            if self._music_enabled and announce_key != self._active_announce:
                self._active_announce = announce_key
                self._announcements.play_for_page(announce_key)

        # Radar: on Current entry, carousel wrap, TTL, or retry after failure.
        if self._maps_enabled() and not radar_prefetching:
            attempt_ok = (
                last_radar_attempt <= 0 or now - last_radar_attempt >= _RADAR_RETRY_S
            )
            need_radar = False
            if page == "current" and entered:
                need_radar = True
            elif wrapped and attempt_ok:
                need_radar = True
            elif last_radar > 0 and now - last_radar >= _RADAR_REFRESH_S:
                need_radar = True
            elif radar_loop is None and attempt_ok:
                need_radar = True
            if need_radar:
                self._start_radar_prefetch(snap, force_refresh=True)

        content_bottom = self._height - bar_height(self._height)
        radar_image: pygame.Surface | None = None
        radar_cached = False
        if page == "radar" and radar_loop is not None and radar_loop.ready:
            radar_image = self._advance_radar_frame(radar_loop, dt_ms)
            radar_cached = bool(radar_loop.cached)

        if page == "current":
            draw_current(self._frame, snap, fonts, content_bottom=content_bottom)
        elif page.startswith("hourly"):
            idx = 0
            if ":" in page:
                try:
                    idx = int(page.split(":", 1)[1])
                except ValueError:
                    idx = 0
            draw_hourly(
                self._frame,
                snap,
                fonts,
                content_bottom=content_bottom,
                page_index=idx,
                hours_per_page=HOURS_PER_PAGE,
            )
        elif page == "daily":
            draw_daily(self._frame, snap, fonts, content_bottom=content_bottom)
        elif page.startswith("regional"):
            ridx = 0
            if ":" in page:
                try:
                    ridx = int(page.split(":", 1)[1])
                except ValueError:
                    ridx = 0
            draw_regional(
                self._frame,
                snap,
                fonts,
                content_bottom=content_bottom,
                page_index=ridx,
                cities_per_page=CITIES_PER_PAGE,
            )
        elif page == "radar":
            draw_radar(
                self._frame,
                fonts,
                content_bottom=content_bottom,
                image=radar_image,
                loading=radar_image is None and radar_prefetching,
            )
        elif page == "alerts":
            draw_alerts_page(self._frame, snap, fonts, content_bottom=content_bottom)
        else:
            draw_current(self._frame, snap, fonts, content_bottom=content_bottom)

        if self._alert_style == "marquee":
            self._lower.set_alerts(snap.alerts, fonts["sm"])
        else:
            self._lower.set_alerts([], fonts["sm"])
        loc_line: str | None = None
        if page == "current":
            loc_line = snap.location.display_name()
            if forecast_stale:
                loc_line = f"{loc_line} (cached)" if loc_line else "cached"
        elif page == "radar" and radar_cached:
            loc_line = "cached"
        self._lower.draw(
            self._frame,
            fonts,
            dt_ms=dt_ms,
            location_line=loc_line,
            show_alerts=self._alert_style == "marquee" and loc_line is None,
        )
        return self._frame.copy()

    def adjust_volume(self, delta: int) -> int:
        self._volume = max(0, min(100, self._volume + int(delta)))
        self._music.set_volume(self._volume)
        self._announcements.set_volume(self._volume)
        return self._volume

    def note_present_stats(self, present_fps: float, blit_ms: float) -> None:
        return

    def _page_names(
        self, snap: WeatherSnapshot, *, has_radar: bool = False
    ) -> list[str]:
        pages = ["current"]
        if has_radar:
            pages.append("radar")
        n_hours = len(snap.hourly)
        if n_hours:
            n_pages = max(1, (n_hours + HOURS_PER_PAGE - 1) // HOURS_PER_PAGE)
            for i in range(n_pages):
                pages.append(f"hourly:{i}")
        pages.append("daily")
        n_cities = len(snap.regional)
        if n_cities:
            n_reg = max(1, (n_cities + CITIES_PER_PAGE - 1) // CITIES_PER_PAGE)
            for i in range(n_reg):
                pages.append(f"regional:{i}")
        if self._alert_style == "page" and snap.alerts:
            # Keep radar immediately after Current; alerts follow that pair.
            pages.insert(1 + (1 if has_radar else 0), "alerts")
        return pages

    def _ensure_fonts(self) -> dict[str, pygame.font.Font]:
        if self._fonts is None:
            # Match main app CRT type (VCR OSD), slightly smaller than browse UI.
            scale = min(self._width / 960.0, self._height / 720.0)
            self._fonts = {
                "sm": make_font(max(22, int(28 * scale))),
                "md": make_font(max(30, int(40 * scale))),
                "lg": make_font(max(40, int(54 * scale))),
                "xl": make_font(max(56, int(80 * scale))),
                "xxl": make_font(max(72, int(110 * scale))),
            }
        return self._fonts

    def _refresh_loop(self) -> None:
        """Wake often; actual fetches are gated by ``_FORECAST_REFRESH_S``."""
        while self._running:
            time.sleep(30.0)
            if not self._running:
                break
            self._start_forecast_refresh(
                reason="timer", min_gap_s=_FORECAST_REFRESH_S
            )
