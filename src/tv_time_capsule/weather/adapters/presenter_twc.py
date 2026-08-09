"""Weather.com/retro CDP screencast presenter."""

from __future__ import annotations

import base64
import io
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time

import pygame

from ...chrome_cdp import ensure_chromium, kill_port_process, wait_for_page_ws
from ...screencast_adapt import (
    ScreencastAdaptState,
    initial_screencast_params,
    observe_frame_latency,
    observe_present_stats,
    read_load_per_cpu,
)

try:
    import websocket  # type: ignore[import-untyped]
except ImportError:
    websocket = None  # type: ignore[assignment]

LOG = logging.getLogger(__name__)

CDP_PORT = 9224
WEATHER_URL = "https://weather.com/retro/"


class WeatherChannel:
    """Headless Chrome CDP screencast → pygame surfaces.

    A background thread owns the WebSocket (connect, send, recv, ack).
    :meth:`get_frame` only reads the latest JPEG from shared state — never
    blocks the UI event loop.

    The thread continuously polls for **Start RetroCast** / **Unmute audio**
    buttons (they reappear after session resets) and applies media gain for
    volume (Howler / HTML media inside Chrome — not a site volume widget).

    Optional *location* (from resolve_weather_location / config ``weather``)
    is injected via the site's ``user-location`` cookie so forecasts work on
    devices without meaningful GeoIP (e.g. a Raspberry Pi on home ISP NAT).
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        location: dict | None = None,
        screencast: dict | None = None,
        url: str | None = None,
        site_mode: str = "twc",
    ) -> None:
        self._width = max(width, 320)
        self._height = max(height, 240)
        self._location = location  # {geocode, name, context, latitude?, longitude?}
        self._url = (url or WEATHER_URL).strip() or WEATHER_URL
        self._site_mode = str(site_mode or "twc").strip().lower()
        self._screencast_cfg = dict(screencast or {})
        self._adapt = ScreencastAdaptState(
            params=initial_screencast_params(
                self._screencast_cfg,
                canvas_w=self._width,
                canvas_h=self._height,
            )
        )
        self._chrome: subprocess.Popen | None = None
        self._user_data_dir: str | None = None
        self._ws = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._available = False
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._frame_count = 0
        self._start_time = 0.0
        self._cmd_id = 0
        self._error: str | None = None
        # 0–100, applied to Chrome page media gain via CDP.
        self._volume = 100
        self._volume_dirty = False
        self._last_start_log = 0.0
        self._last_unmute_log = 0.0
        self._last_frame_wall = 0.0
        self._restart_screencast = False

    @property
    def effective_fps(self) -> float:
        with self._lock:
            return float(self._adapt.params.effective_fps)

    @property
    def needs_screencast_pacing(self) -> bool:
        return True

    def note_present_stats(self, present_fps: float, blit_ms: float) -> None:
        """Feed UI present FPS / blit cost into the adaptive controller.

        Safe to call from the pygame thread; never talks to Chrome. May request
        a screencast restart when the UI cannot keep up with arrivals.
        """
        if not self._available or not self._running:
            return
        try:
            fps = float(present_fps)
            blit = float(blit_ms)
        except (TypeError, ValueError):
            return
        if fps <= 0.05 or blit < 0:
            return
        load = read_load_per_cpu()
        with self._lock:
            self._adapt, need_restart = observe_present_stats(
                self._adapt,
                fps,
                blit,
                self._screencast_cfg,
                canvas_w=self._width,
                canvas_h=self._height,
                load_per_cpu=load,
            )
            if need_restart:
                self._restart_screencast = True
                p = self._adapt.params
                LOG.info(
                    "Weather screencast adapt (present): nth=%s q=%s %sx%s ~%.1ffps "
                    "(ui=%.1ffps blit=%.0fms load=%s)",
                    p.every_nth_frame,
                    p.quality,
                    p.max_width,
                    p.max_height,
                    p.effective_fps,
                    self._adapt.ema_present_fps,
                    self._adapt.ema_blit_ms,
                    f"{load:.2f}" if load is not None else "n/a",
                )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Launch Chrome and begin the screencast. Returns True on success.

        Retries once if the first attempt fails — cold Chrome starts are
        occasionally flaky (port race, page not ready).
        """
        if self._available:
            return True

        if websocket is None:
            LOG.warning("websocket-client not installed")
            return False

        chrome_path = ensure_chromium(log_label="weather channel")
        if chrome_path is None:
            LOG.warning("Chrome not found – weather channel unavailable")
            return False

        for attempt in (1, 2):
            if self._start_once(chrome_path):
                return True
            self.stop()
            if attempt == 1:
                LOG.info("Weather channel first start failed; retrying…")
                time.sleep(0.8)
        return False

    def _start_once(self, chrome_path: str) -> bool:
        """Single Chrome + CDP connect attempt. Caller handles retries."""
        kill_port_process(CDP_PORT)
        time.sleep(0.3)

        # Isolated profile: avoids clashing with a running Google Chrome
        # instance and keeps extensions out of the CDP target list.
        self._user_data_dir = tempfile.mkdtemp(prefix="ttc-weather-")

        try:
            self._chrome = subprocess.Popen(
                [
                    chrome_path,
                    f"--remote-debugging-port={CDP_PORT}",
                    f"--user-data-dir={self._user_data_dir}",
                    "--headless=new",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                    "--disable-sync",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-gpu",
                    "--force-device-scale-factor=1",
                    f"--window-size={self._width},{self._height}",
                    # Start blank so we can set location cookies before weather.com loads.
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            LOG.warning("Failed to launch Chrome: %s", exc)
            self._cleanup_user_data()
            return False

        ws_url = wait_for_page_ws(CDP_PORT, chrome=self._chrome, timeout=12.0)
        if ws_url is None:
            LOG.warning("No CDP page target found for weather channel")
            return False

        self._running = True
        self._available = True
        self._frame_count = 0
        self._start_time = time.time()
        self._error = None
        self._volume_dirty = True  # apply gain once the page streams
        self._thread = threading.Thread(
            target=self._ws_thread, args=(ws_url,), daemon=True, name="weather-cdp"
        )
        self._thread.start()

        # Wait briefly for the first frame so we fail fast if CDP is broken.
        deadline = time.time() + 12.0
        while time.time() < deadline and self._running:
            with self._lock:
                if self._latest_jpeg is not None:
                    LOG.info(
                        "Weather channel started (%d frames so far)",
                        self._frame_count,
                    )
                    return True
            if self._error:
                break
            time.sleep(0.05)

        LOG.warning(
            "Weather channel: no frames after %.1fs (%s)",
            time.time() - self._start_time,
            self._error or "timeout",
        )
        return False

    def stop(self) -> None:
        """Stop the screencast and tear down Chrome."""
        self._running = False
        self._available = False

        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
            self._ws = None

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

        if self._chrome is not None:
            try:
                self._chrome.terminate()
                self._chrome.wait(timeout=5)
            except Exception:
                try:
                    self._chrome.kill()
                except Exception:
                    pass
            self._chrome = None

        self._cleanup_user_data()
        LOG.info("Weather channel stopped (frames=%d)", self._frame_count)

    def get_frame(self) -> pygame.Surface | None:
        """Return the latest screencast frame as a Surface (never blocks)."""
        if not self._available:
            return None

        with self._lock:
            jpeg = self._latest_jpeg

        if jpeg is None:
            return None

        try:
            return pygame.image.load(io.BytesIO(jpeg))
        except Exception:
            return None

    def is_available(self) -> bool:
        return self._available

    @property
    def volume(self) -> int:
        """Current gain 0–100 applied to Chrome page media."""
        with self._lock:
            return self._volume

    def adjust_volume(self, delta: int) -> int:
        """Adjust Chrome media gain by *delta* (e.g. +10 / -10). Returns new level."""
        with self._lock:
            self._volume = max(0, min(100, self._volume + int(delta)))
            self._volume_dirty = True
            return self._volume

    def set_volume(self, level: int) -> int:
        """Set Chrome media gain to *level* (0–100). Returns clamped level."""
        with self._lock:
            self._volume = max(0, min(100, int(level)))
            self._volume_dirty = True
            return self._volume

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _cleanup_user_data(self) -> None:
        if self._user_data_dir is None:
            return
        try:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
        except Exception:
            pass
        self._user_data_dir = None

    def _next_id(self) -> int:
        self._cmd_id += 1
        return self._cmd_id

    def _send(self, ws, method: str, params: dict | None = None) -> None:
        msg: dict = {"id": self._next_id(), "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))

    def _apply_location(self, ws) -> None:
        """Set user-location cookie + CDP geolocation before Page.navigate."""
        if self._site_mode != "twc":
            # ws4kp uses permalink lat/lon; optional CDP geolocation only.
            loc = self._location
            if not loc:
                return
            try:
                lat = float(loc.get("latitude"))
                lon = float(loc.get("longitude"))
            except (TypeError, ValueError):
                return
            try:
                self._send(
                    ws,
                    "Emulation.setGeolocationOverride",
                    {"latitude": lat, "longitude": lon, "accuracy": 100},
                )
            except Exception as exc:
                LOG.warning("Weather geolocation override failed: %s", exc)
            return
        loc = self._location
        if not loc:
            return

        geocode = loc.get("geocode")
        name = loc.get("name") or "Home"
        context = loc.get("context") or ""
        try:
            lat = float(loc.get("latitude") if loc.get("latitude") is not None
                        else str(geocode).split(",")[0])
            lon = float(loc.get("longitude") if loc.get("longitude") is not None
                        else str(geocode).split(",")[1])
        except (TypeError, ValueError, IndexError):
            LOG.warning("Invalid weather location; skipping inject: %s", loc)
            return

        cookie_body = {
            "geocode": geocode or f"{lat},{lon}",
            "name": name,
            "context": context,
        }
        # Retro reads Nuxt useCookie("user-location") — raw JSON works.
        self._send(ws, "Network.enable")
        self._send(
            ws,
            "Network.setCookie",
            {
                "name": "user-location",
                "value": json.dumps(cookie_body, separators=(",", ":")),
                "domain": ".weather.com",
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            },
        )
        try:
            self._send(
                ws,
                "Browser.grantPermissions",
                {
                    "origin": "https://weather.com",
                    "permissions": ["geolocation"],
                },
            )
        except Exception:
            pass
        self._send(
            ws,
            "Emulation.setGeolocationOverride",
            {
                "latitude": lat,
                "longitude": lon,
                "accuracy": 100,
            },
        )
        LOG.info("Weather location cookie set: %s @ %s", name, cookie_body["geocode"])

    # Continuously look for Start / Unmute — both can reappear after a
    # session ends or when re-entering the experience.
    _JS_WATCHDOG = r"""
(() => {
  const out = {start: false, unmute: false};
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0)
      return false;
    return true;
  };
  const start = [...document.querySelectorAll(
    'button, a, [role="button"], input[type="button"], input[type="submit"]'
  )].find((el) =>
    /start\s*retro\s*cast/i.test(
      ((el.innerText || el.textContent || el.value || "") + " " +
        (el.getAttribute("aria-label") || "")).trim()
    )
  );
  if (visible(start)) {
    start.click();
    out.start = true;
  }
  const unmute =
    document.querySelector('[aria-label="Unmute audio"]') ||
    document.querySelector('[aria-label*="Unmute" i]') ||
    [...document.querySelectorAll("button, [role=button], [aria-label]")].find(
      (el) => /unmute\s*audio/i.test(el.getAttribute("aria-label") || "")
    );
  if (visible(unmute)) {
    unmute.click();
    out.unmute = true;
  }
  return out;
})()
""".strip()

    # ws4kp: unmute Howler / click speaker controls (toolbar may be hidden in kiosk).
    _JS_WATCHDOG_WS4KP = r"""
(() => {
  const out = {start: false, unmute: false};
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || Number(s.opacity) === 0)
      return false;
    return true;
  };
  try {
    if (window.Howler) {
      Howler.mute(false);
      if (Howler.ctx && Howler.ctx.state === "suspended") Howler.ctx.resume();
      out.unmute = true;
    }
  } catch (e) {}
  const hit = [...document.querySelectorAll(
    'button, a, [role="button"], [aria-label], [title]'
  )].find((el) => {
    const t = (
      (el.getAttribute("aria-label") || "") + " " +
      (el.getAttribute("title") || "") + " " +
      (el.innerText || el.textContent || "")
    ).toLowerCase();
    if (!t.trim()) return false;
    if (/\bmute\b/.test(t) && !/\bunmute\b/.test(t)) return false;
    return /\bunmute\b|\bplay\b.*\bmusic\b|\bsound\b.*\bon\b|\bvolume\b/.test(t);
  });
  if (visible(hit)) {
    hit.click();
    out.unmute = true;
  }
  for (const m of document.querySelectorAll("audio, video")) {
    try { m.muted = false; if (m.paused) m.play().catch(() => {}); } catch (e) {}
  }
  return out;
})()
""".strip()

    @staticmethod
    def _js_set_media_gain(level_0_100: int) -> str:
        """Set gain on all page media / Howler (Chrome's output for this tab)."""
        v = max(0.0, min(1.0, level_0_100 / 100.0))
        return f"""
(() => {{
  const v = {v:.4f};
  try {{
    if (window.Howler) {{
      Howler.mute(false);
      Howler.volume(v);
      if (Howler.ctx && Howler.ctx.state === "suspended") Howler.ctx.resume();
    }}
  }} catch (e) {{}}
  for (const m of document.querySelectorAll("audio, video")) {{
    try {{ m.muted = false; m.volume = v; }} catch (e) {{}}
  }}
  try {{
    if (window.__ttcAudioCtxs) {{
      for (const ctx of window.__ttcAudioCtxs) {{
        if (ctx && ctx.gainNode) ctx.gainNode.gain.value = v;
      }}
    }}
  }} catch (e) {{}}
  return v;
}})()
""".strip()

    def _ws_thread(self, ws_url: str) -> None:
        """Create the WebSocket, start screencast, drive UI, and pump frames."""
        LOG.info("Weather WS thread connecting…")
        try:
            ws = websocket.create_connection(
                ws_url,
                timeout=10,
                suppress_origin=True,
            )
        except Exception as exc:
            self._error = f"connect failed: {exc}"
            LOG.warning("CDP WebSocket connection failed: %s", exc)
            self._available = False
            self._running = False
            return

        self._ws = ws
        # Bounded timeout so we can notice stop() without a hard hang.
        ws.settimeout(1.0)

        # Headless Chrome often ignores --window-size for the CSS viewport
        # (we saw 640×393 with ~58px black pillars).  Force layout metrics
        # to match the TV canvas so weather.com fills edge-to-edge.
        try:
            self._send(
                ws,
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": self._width,
                    "height": self._height,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                    "screenWidth": self._width,
                    "screenHeight": self._height,
                },
            )
        except Exception as exc:
            LOG.warning("Device metrics override failed: %s", exc)

        # Inject forecast location before the retro app hydrates (Pi has no
        # useful GeoIP; weather.com stores the user's choice in a cookie).
        try:
            self._apply_location(ws)
        except Exception as exc:
            LOG.warning("Weather location inject failed: %s", exc)

        try:
            self._send(ws, "Page.navigate", {"url": self._url})
            # Allow HTML/JS shell to begin before screencast + Start buttons.
            time.sleep(2.5)
        except Exception as exc:
            self._error = f"navigate failed: {exc}"
            LOG.warning("Page.navigate failed: %s", exc)
            self._available = False
            self._running = False
            try:
                ws.close()
            except Exception:
                pass
            return

        try:
            self._send_screencast_start(ws)
            p = self._adapt.params
            LOG.info(
                "Weather screencast started (%dx%d) nth=%d q=%d ~%.1ffps",
                p.max_width,
                p.max_height,
                p.every_nth_frame,
                p.quality,
                p.effective_fps,
            )
        except Exception as exc:
            self._error = f"startScreencast failed: {exc}"
            LOG.warning("Page.startScreencast failed: %s", exc)
            self._available = False
            self._running = False
            try:
                ws.close()
            except Exception:
                pass
            return

        # Eval bookkeeping: id → "watchdog" | "volume"
        pending: dict[int, str] = {}
        last_watchdog = 0.0
        WATCHDOG_INTERVAL = 1.0

        def fire_eval(kind: str, expression: str) -> None:
            eid = self._next_id()
            pending[eid] = kind
            ws.send(
                json.dumps(
                    {
                        "id": eid,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "returnByValue": True,
                            "userGesture": True,
                        },
                    }
                )
            )

        def pump_side_effects() -> None:
            """Periodic Start/Unmute + pending volume apply + adapt restart."""
            nonlocal last_watchdog
            now = time.time()
            if now - last_watchdog >= WATCHDOG_INTERVAL:
                last_watchdog = now
                if self._site_mode == "twc":
                    fire_eval("watchdog", self._JS_WATCHDOG)
                elif self._site_mode == "ws4kp":
                    fire_eval("watchdog", self._JS_WATCHDOG_WS4KP)

            with self._lock:
                dirty = self._volume_dirty
                vol = self._volume
                if dirty:
                    self._volume_dirty = False
                restart = self._restart_screencast
                if restart:
                    self._restart_screencast = False
            if dirty:
                fire_eval("volume", self._js_set_media_gain(vol))
            if restart:
                try:
                    self._send(ws, "Page.stopScreencast")
                    self._send_screencast_start(ws)
                    p = self._adapt.params
                    LOG.info(
                        "Weather screencast adapted nth=%d q=%d %dx%d ~%.1ffps",
                        p.every_nth_frame,
                        p.quality,
                        p.max_width,
                        p.max_height,
                        p.effective_fps,
                    )
                except Exception as exc:
                    LOG.warning("Weather screencast adapt restart failed: %s", exc)

        # Immediate first probes.
        pump_side_effects()

        while self._running:
            pump_side_effects()
            try:
                data = ws.recv()
            except Exception as exc:
                name = type(exc).__name__
                if "Timeout" in name or "timed out" in str(exc).lower():
                    continue
                if not self._running:
                    break
                LOG.warning("Weather recv error: %s", exc)
                self._error = f"recv failed: {exc}"
                break

            if not data:
                continue
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            mid = msg.get("id")
            if mid is not None and mid in pending:
                kind = pending.pop(mid)
                if kind == "watchdog":
                    value = (
                        ((msg.get("result") or {}).get("result") or {}).get("value")
                    )
                    if isinstance(value, dict):
                        now = time.time()
                        if value.get("start") and now - self._last_start_log > 3.0:
                            LOG.info("Weather UI: Start RetroCast clicked")
                            self._last_start_log = now
                            # Re-apply gain after a fresh program start.
                            with self._lock:
                                self._volume_dirty = True
                        if value.get("unmute") and now - self._last_unmute_log > 3.0:
                            LOG.info("Weather UI: Unmute audio clicked")
                            self._last_unmute_log = now
                            with self._lock:
                                self._volume_dirty = True
                continue

            if msg.get("method") != "Page.screencastFrame":
                continue

            params = msg.get("params") or {}
            data_b64 = params.get("data") or ""
            session_id = params.get("sessionId", 0)

            try:
                self._send(
                    ws, "Page.screencastFrameAck", {"sessionId": session_id}
                )
            except Exception:
                if self._running:
                    LOG.warning("Weather frame ack failed")
                break

            if not data_b64:
                continue
            try:
                jpeg = base64.b64decode(data_b64)
            except Exception:
                continue

            now = time.time()
            with self._lock:
                prev = self._last_frame_wall
                self._last_frame_wall = now
                self._latest_jpeg = jpeg
                self._frame_count += 1
                count = self._frame_count
            if prev > 0:
                latency_ms = (now - prev) * 1000.0
                load = read_load_per_cpu()
                with self._lock:
                    self._adapt, need_restart = observe_frame_latency(
                        self._adapt,
                        latency_ms,
                        self._screencast_cfg,
                        canvas_w=self._width,
                        canvas_h=self._height,
                        load_per_cpu=load,
                    )
                    if need_restart:
                        self._restart_screencast = True
                        p = self._adapt.params
                        LOG.info(
                            "Weather screencast adapt (latency): nth=%s q=%s "
                            "%sx%s ~%.1ffps (ema=%.0fms)",
                            p.every_nth_frame,
                            p.quality,
                            p.max_width,
                            p.max_height,
                            p.effective_fps,
                            self._adapt.ema_latency_ms,
                        )

            if count == 1:
                LOG.info("Weather first frame (%d bytes)", len(jpeg))

        try:
            if self._running is False:
                try:
                    self._send(ws, "Page.stopScreencast")
                except Exception:
                    pass
            ws.close()
        except Exception:
            pass
        self._ws = None
        LOG.info("Weather WS thread stopped (frames=%d)", self._frame_count)

    def _send_screencast_start(self, ws) -> None:
        p = self._adapt.params
        self._send(
            ws,
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": int(p.quality),
                "maxWidth": int(p.max_width),
                "maxHeight": int(p.max_height),
                "everyNthFrame": int(p.every_nth_frame),
            },
        )
