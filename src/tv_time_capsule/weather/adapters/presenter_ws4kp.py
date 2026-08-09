"""WeatherStar 4000+ (ws4kp) CDP screencast presenter."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .presenter_twc import WeatherChannel as CdpScreencastPresenter

DEFAULT_WS4KP_BASE = "https://weatherstar.netbymatt.com/"
# Mostly static UI (page fades are rare); only the upper-right clock ticks.
DEFAULT_WS4KP_FPS = 4.0


def ws4kp_screencast_cfg(screencast: dict[str, Any] | None) -> dict[str, Any]:
    """Pin WS4KP CDP rate (~4 FPS) without changing shared TWC adapt knobs.

    Shared ``weather.screencast`` still supplies JPEG quality / max size.
    Override with ``weather.screencast.ws4kp_target_fps`` when needed.
    """
    cfg = dict(screencast or {})
    raw = cfg.get("ws4kp_target_fps")
    try:
        fps = float(raw) if raw is not None and str(raw).strip() != "" else DEFAULT_WS4KP_FPS
    except (TypeError, ValueError):
        fps = DEFAULT_WS4KP_FPS
    fps = max(0.5, min(30.0, fps))
    cfg["mode"] = "fixed"
    cfg["target_fps"] = fps
    cfg["min_fps"] = min(float(cfg.get("min_fps") or 1.0), fps)
    cfg["max_fps"] = max(float(cfg.get("max_fps") or fps), fps)
    return cfg


def build_ws4kp_url(
    base_url: str,
    location: dict[str, Any] | None,
    *,
    kiosk: bool = True,
    media_playing: bool = True,
) -> str:
    """Build a ws4kp permalink with optional lat/lon and kiosk mode.

    ``media_playing`` adds ``settings-mediaPlaying-boolean=true`` so background
    music is requested on load (ws4kp is muted by default; kiosk hides the
    speaker control). Chrome still needs ``--autoplay-policy=no-user-gesture-required``.
    """
    base = (base_url or DEFAULT_WS4KP_BASE).strip() or DEFAULT_WS4KP_BASE
    if not base.endswith("/"):
        base += "/"
    params: list[tuple[str, str]] = []
    if kiosk:
        params.append(("kiosk", "true"))
    if media_playing:
        # Official permalink knob — see ws4kp README "Music doesn't auto play".
        params.append(("settings-mediaPlaying-boolean", "true"))
    if location:
        lat = location.get("latitude")
        lon = location.get("longitude")
        try:
            la = float(lat)
            lo = float(lon)
        except (TypeError, ValueError):
            la = lo = None  # type: ignore[assignment]
        if la is not None and lo is not None:
            params.append(("latLon", json.dumps({"lat": la, "lon": lo}, separators=(",", ":"))))
            name = str(location.get("name") or "").strip()
            context = str(location.get("context") or "").strip()
            query = ", ".join(p for p in (name, context) if p) or f"{la},{lo}"
            params.append(("latLonQuery", query))
    if not params:
        return base
    return base + "?" + urllib.parse.urlencode(params)


class Ws4kpScreencastPresenter(CdpScreencastPresenter):
    """Headless Chrome pointed at a ws4kp kiosk permalink."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        location: dict | None = None,
        screencast: dict | None = None,
        base_url: str = DEFAULT_WS4KP_BASE,
    ) -> None:
        url = build_ws4kp_url(base_url, location, kiosk=True)
        super().__init__(
            width,
            height,
            location=location,
            screencast=ws4kp_screencast_cfg(screencast),
            url=url,
            site_mode="ws4kp",
        )


# Alias matching the plan name.
TwcScreencastPresenter = CdpScreencastPresenter
