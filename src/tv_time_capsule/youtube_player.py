"""YouTube watch-page playback via Chrome DevTools Protocol screencast.

Navigates to ``https://www.youtube.com/watch?v=…``, hides page chrome,
autoplays the player, and exposes an :class:`EmbeddedPlayer`-compatible API
so the main app can treat YouTube episodes like local files.
"""

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
from typing import Any

import numpy as np
import pygame

from .chrome_cdp import ensure_chromium, kill_port_process, wait_for_page_ws

try:
    import websocket  # type: ignore[import-untyped]
except ImportError:
    websocket = None  # type: ignore[assignment]

LOG = logging.getLogger(__name__)

CDP_PORT = 9227  # 9226 = catalog scrape; avoid colliding while a video plays


def detect_letterbox_rect(
    surf: pygame.Surface,
    *,
    black_max: int = 22,
    min_bar_px: int = 6,
    min_bar_frac: float = 0.03,
) -> tuple[int, int, int, int] | None:
    """Return content ``(x, y, w, h)`` for pillarboxed (side-bar) frames only.

    Used to recover 4:3 (or other) picture that was re-rendered inside a wider
    frame with black side mattes. True widescreen with only top/bottom bars is
    left alone — those letterbox bars are intentional and must not be cropped
    away (cropping then filling the canvas would non-uniformly stretch).

    Returns ``None`` for full-bleed frames and for letterbox-only (no side bars).
    """
    w, h = surf.get_size()
    if w < 32 or h < 32:
        return None
    try:
        # pygame surfarray is (w, h, 3); transpose to (h, w) for row scans.
        arr = pygame.surfarray.pixels3d(surf)
        # Copy so we can unlock the surface immediately.
        rgb = np.asarray(arr, dtype=np.uint16).transpose(1, 0, 2).copy()
        del arr
    except Exception:
        return None

    # Approximate luma without float math.
    luma = (rgb[:, :, 0] * 3 + rgb[:, :, 1] * 6 + rgb[:, :, 2]) // 10
    mid_x0, mid_x1 = w // 3, (2 * w) // 3
    mid_y0, mid_y1 = h // 3, (2 * h) // 3
    col_strip = luma[:, mid_x0:mid_x1].mean(axis=1)
    row_strip = luma[mid_y0:mid_y1, :].mean(axis=0)

    def _bar_extent(line: np.ndarray, length: int) -> tuple[int, int]:
        dark = line <= black_max
        lo = 0
        while lo < length and dark[lo]:
            lo += 1
        hi = length - 1
        while hi >= 0 and dark[hi]:
            hi -= 1
        return lo, hi

    top, bot = _bar_extent(col_strip, h)
    left, right = _bar_extent(row_strip, w)
    if bot <= top or right <= left:
        return None

    top_bar = top
    bottom_bar = h - 1 - bot
    left_bar = left
    right_bar = w - 1 - right
    min_bar = max(min_bar_px, int(min(h, w) * min_bar_frac))

    # Matching pair required — ignore one-sided mattes / UI chrome.
    letterbox = top_bar >= min_bar and bottom_bar >= min_bar
    pillarbox = left_bar >= min_bar and right_bar >= min_bar
    # Only act on side bars (4:3-in-widescreen rerenders). Top/bottom-only
    # letterbox is real widescreen — keep the bars.
    if not pillarbox:
        return None

    x = left
    rw = right - left + 1
    # If the active region is also letterboxed (windowbox), crop that too so
    # the subsequent uniform zoom fills the CRT from the real picture.
    y = top if letterbox else 0
    rh = (bot - top + 1) if letterbox else h
    # Keep a little safety inset so we don't clip soft edges.
    pad = 2
    x = min(max(0, x + pad), w - 8)
    y = min(max(0, y + pad), h - 8)
    rw = max(8, min(rw - 2 * pad, w - x))
    rh = max(8, min(rh - 2 * pad, h - y))
    if rw >= w * 0.98 and rh >= h * 0.98:
        return None
    return x, y, rw, rh


def scale_uniform(
    surf: pygame.Surface,
    target_w: int,
    target_h: int,
    *,
    mode: str = "fit",
) -> pygame.Surface:
    """Scale ``surf`` into ``target_w``×``target_h`` with equal X/Y scale.

    ``fit`` — contain (letterbox/pillarbox with black); ``cover`` — fill and
    center-crop overflow. Never uses different horizontal vs vertical ratios.
    """
    tw, th = int(target_w), int(target_h)
    sw, sh = surf.get_size()
    if tw <= 0 or th <= 0 or sw <= 0 or sh <= 0:
        return surf
    if (sw, sh) == (tw, th):
        return surf

    if mode == "cover":
        scale = max(tw / sw, th / sh)
    else:
        scale = min(tw / sw, th / sh)

    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    try:
        scaled = pygame.transform.smoothscale(surf, (nw, nh))
    except Exception:
        scaled = pygame.transform.scale(surf, (nw, nh))

    if mode == "cover":
        x = max(0, (nw - tw) // 2)
        y = max(0, (nh - th) // 2)
        # smoothscale rounding can leave us 1px short — pad rather than crash.
        if nw < tw or nh < th:
            out = pygame.Surface((tw, th))
            out.fill((0, 0, 0))
            out.blit(scaled, ((tw - nw) // 2, (th - nh) // 2))
            return out
        try:
            return scaled.subsurface((x, y, tw, th)).copy()
        except Exception:
            out = pygame.Surface((tw, th))
            out.fill((0, 0, 0))
            out.blit(scaled, (-x, -y))
            return out

    out = pygame.Surface((tw, th))
    out.fill((0, 0, 0))
    out.blit(scaled, ((tw - nw) // 2, (th - nh) // 2))
    return out


class YouTubePlayer:
    """Headless Chrome screencast of a single YouTube watch URL."""

    def __init__(self, width: int = 640, height: int = 480, *, cdp_port: int = CDP_PORT):
        self.width = width
        self.height = height
        self._cdp_port = cdp_port

        # EmbeddedPlayer-compatible public state
        self.use_omx = False
        self.paused = False
        self.volume = 100
        self.time_pos = 0.0
        self.duration = 0.0
        self.filepath: str | None = None
        self.running = False
        self.finished = False
        self.fps = 30.0

        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._available = False
        self._error: str | None = None
        self._chrome: subprocess.Popen | None = None
        self._ws = None
        self._thread: threading.Thread | None = None
        self._user_data_dir: str | None = None
        self._cmd_id = 0
        self._volume_dirty = False
        self._pause_dirty = False
        self._seek_to: float | None = None
        self._want_ended_poll = True
        self._start_mono = 0.0
        self._pause_offset = 0.0
        self._pause_start = 0.0
        self._youtube_id: str | None = None
        self._frame_count = 0
        self._content_crop: tuple[int, int, int, int] | None = None
        self._letterbox_samples: list[tuple[int, int, int, int]] = []
        self._letterbox_locked = False
        self._last_letterbox_check = 0.0
        self._play_kick_pending = False
        self._suppress_watchdog_until = 0.0

    # ------------------------------------------------------------------
    # Public API (EmbeddedPlayer-shaped)
    # ------------------------------------------------------------------

    def start(self, filepath: str, resume_pos=None) -> bool:
        """Start playback. ``filepath`` may be ``youtube:ID`` or a bare video id."""
        self.stop()
        yid = self._parse_id(filepath)
        if not yid:
            LOG.warning("YouTubePlayer: invalid video id %r", filepath)
            return False

        if websocket is None:
            LOG.warning("websocket-client not installed — YouTube playback unavailable")
            return False

        chrome_bin = ensure_chromium(log_label="youtube-player")
        if chrome_bin is None:
            LOG.warning("Chrome/Chromium not available for YouTube playback")
            return False

        self._youtube_id = yid
        self.filepath = f"youtube:{yid}"
        self.paused = False
        self.finished = False
        self.running = True
        self.time_pos = max(0.0, float(resume_pos or 0.0))
        self.duration = 0.0
        self._pause_offset = 0.0
        self._pause_start = 0.0
        self._start_mono = time.monotonic() - self.time_pos
        self._available = False
        self._error = None
        self._latest_jpeg = None
        self._volume_dirty = True
        self._pause_dirty = False
        self._frame_count = 0
        self._content_crop = None
        self._letterbox_samples = []
        self._letterbox_locked = False
        self._last_letterbox_check = 0.0
        self._play_kick_pending = True
        self._suppress_watchdog_until = 0.0

        kill_port_process(self._cdp_port)
        self._user_data_dir = tempfile.mkdtemp(prefix="ttc-yt-play-")

        url = f"https://www.youtube.com/watch?v={yid}"
        # Seek via JS after load — putting &t= in the URL makes YouTube scroll
        # the watch page, which shifts our taller screencast viewport.
        self._seek_to = self.time_pos if self.time_pos > 1.0 else None

        try:
            self._chrome = subprocess.Popen(
                [
                    chrome_bin,
                    f"--remote-debugging-port={self._cdp_port}",
                    f"--user-data-dir={self._user_data_dir}",
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-extensions",
                    f"--window-size={self.width},{self.height}",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            LOG.warning("Failed to launch Chrome for YouTube: %s", exc)
            self.running = False
            self._cleanup_user_data()
            return False

        ws_url = wait_for_page_ws(self._cdp_port, chrome=self._chrome, timeout=15.0)
        if not ws_url:
            LOG.warning("YouTubePlayer: CDP not ready")
            self.stop()
            return False

        self._navigate_url = url
        self._thread = threading.Thread(
            target=self._ws_thread, args=(ws_url,), daemon=True, name="youtube-cdp"
        )
        self._thread.start()

        # Wait briefly for first frame / availability
        deadline = time.time() + 12.0
        while time.time() < deadline and self.running and not self._available:
            if self._error:
                break
            time.sleep(0.1)

        if not self._available:
            LOG.warning(
                "YouTubePlayer: unavailable (%s)", self._error or "timeout"
            )
            # Keep running if Chrome is up — frames may still arrive.
            if self._chrome is None or self._chrome.poll() is not None:
                self.stop()
                return False
            self._available = True

        LOG.info("YouTube play start id=%s resume=%.1fs", yid, self.time_pos)
        return True

    def stop(self) -> None:
        was_running = self.running
        self.running = False
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

        kill_port_process(self._cdp_port)
        self._cleanup_user_data()
        if was_running and self.filepath:
            LOG.info(
                "YouTube play stop id=%s pos=%.1fs frames=%d",
                self._youtube_id,
                self.time_pos,
                self._frame_count,
            )
        self.filepath = None

    def get_frame(self) -> pygame.Surface | None:
        with self._lock:
            jpeg = self._latest_jpeg
            crop = self._content_crop
        if jpeg is None:
            return None
        try:
            surf = pygame.image.load(io.BytesIO(jpeg))
        except Exception:
            return None

        # Pillarbox crop only (side mattes from a 4:3-in-widescreen re-encode).
        # Then uniform cover-zoom — never different X vs Y stretch ratios.
        if crop is not None:
            x, y, cw, ch = crop
            sw, sh = surf.get_size()
            if cw > 8 and ch > 8 and x + cw <= sw and y + ch <= sh:
                try:
                    surf = surf.subsurface((x, y, cw, ch)).copy()
                except Exception:
                    pass
            return scale_uniform(surf, self.width, self.height, mode="cover")

        # True widescreen / full-bleed: fit with equal scale (letterbox OK).
        return scale_uniform(surf, self.width, self.height, mode="fit")

    def is_playing(self) -> bool:
        return self.running and not self.finished and not self.paused

    def is_finished(self) -> bool:
        return self.finished

    def check_stall(self, threshold: float = 20.0) -> bool:
        # YouTube buffering is common; avoid aggressive stall detection.
        return False

    def pause(self) -> None:
        if not self.running or self.finished:
            return
        self.paused = not self.paused
        if self.paused:
            self._pause_start = time.monotonic()
        else:
            if self._pause_start > 0:
                self._pause_offset += time.monotonic() - self._pause_start
            self._pause_start = 0.0
        with self._lock:
            self._pause_dirty = True

    def seek(self, delta: float) -> None:
        self.update_time()
        target = max(0.0, self.time_pos + float(delta))
        if self.duration > 0:
            target = min(target, max(0.0, self.duration - 1.0))
        self.time_pos = target
        self._start_mono = time.monotonic() - self.time_pos - self._pause_offset
        with self._lock:
            self._seek_to = target

    def adjust_volume(self, delta: int) -> int:
        self.volume = max(0, min(100, self.volume + int(delta)))
        with self._lock:
            self._volume_dirty = True
        return self.volume

    def set_volume(self, level: int) -> int:
        self.volume = max(0, min(100, int(level)))
        with self._lock:
            self._volume_dirty = True
        return self.volume

    def update_time(self) -> None:
        if self.paused or not self.running or self.finished:
            return
        elapsed = time.monotonic() - self._start_mono - self._pause_offset
        if self.duration > 0:
            elapsed = min(elapsed, self.duration)

    def format_time(self, seconds) -> str:
        if seconds is None or seconds < 0:
            return "--:--"
        s = int(seconds)
        if s >= 3600:
            return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
        return f"{s // 60}:{s % 60:02d}"

    def progress(self) -> float:
        if self.duration and self.duration > 0:
            return max(0.0, min(1.0, self.time_pos / self.duration))
        return 0.0

    def is_available(self) -> bool:
        return self._available

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_id(filepath: str) -> str | None:
        text = (filepath or "").strip()
        if text.startswith("youtube:"):
            text = text[8:].strip()
        if "v=" in text:
            text = text.split("v=", 1)[1].split("&", 1)[0]
        if len(text) == 11:
            return text
        return None

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
        msg: dict[str, Any] = {"id": self._next_id(), "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))

    def _apply_caption_cookie(self, ws) -> None:
        try:
            self._send(ws, "Network.enable")
            for domain in (".youtube.com", ".youtube-nocookie.com"):
                self._send(
                    ws,
                    "Network.setCookie",
                    {
                        "name": "PREF",
                        "value": "f6=8&f5=30000&hl=en",
                        "domain": domain,
                        "path": "/",
                        "secure": True,
                        "sameSite": "None",
                    },
                )
        except Exception as exc:
            LOG.debug("YouTube PREF cookie failed: %s", exc)

    def _js_watchdog(self, *, want_paused: bool) -> str:
        """Hide page chrome, fill the viewport, reinforce pause only.

        Never call playVideo or the media element's play method here. Seek
        buffering leaves the element briefly paused; hammering play from the
        layout loop trips YouTube's "something went wrong" UI.
        """
        paused_js = "true" if want_paused else "false"
        return f"""
(() => {{
  const wantPaused = {paused_js};
  const out = {{ready: false, playing: false, ended: false, t: 0, d: 0, clicked: false, paused: wantPaused}};
  const hide = [
    '#masthead-container', '#guide', '#related', '#comments',
    '#secondary', '#chat', '#chat-container', 'ytd-watch-next-secondary-results-renderer',
    '#below', '#ticket-shelf', 'tp-yt-paper-dialog', '.ytp-pause-overlay',
    '.ytp-ce-element', '.ytp-cards-teaser', '#donation-shelf',
    'ytd-merch-shelf-renderer', '#movie_player .ytp-chrome-top',
    '.ytp-gradient-top', '.ytp-gradient-bottom',
    '.ytp-chrome-bottom', '.ytp-chrome-controls', '.ytp-progress-bar-container',
    '.ytp-caption-window-container'
  ];
  for (const sel of hide) {{
    for (const el of document.querySelectorAll(sel)) {{
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('opacity', '0', 'important');
      el.style.setProperty('pointer-events', 'none', 'important');
    }}
  }}
  document.documentElement.style.setProperty('background', '#000', 'important');
  document.body.style.setProperty('background', '#000', 'important');
  document.body.style.setProperty('overflow', 'hidden', 'important');
  document.documentElement.style.setProperty('overflow', 'hidden', 'important');
  try {{
    window.scrollTo(0, 0);
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    const scroller = document.scrollingElement;
    if (scroller) {{ scroller.scrollTop = 0; scroller.scrollLeft = 0; }}
    for (const sel of ['ytd-app', '#content', '#page-manager', '#columns', 'ytd-watch-flexy']) {{
      for (const el of document.querySelectorAll(sel)) {{
        try {{ el.scrollTop = 0; el.scrollLeft = 0; }} catch (e) {{}}
      }}
    }}
  }} catch (e) {{}}

  // Exact viewport fill — no taller "offscreen" band (that caused black bars
  // whenever YouTube scrolled the page on resume).
  const player = document.getElementById('movie_player') || document.querySelector('#player');
  if (player) {{
    player.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'right:0', 'bottom:0',
      'width:100vw', 'height:100vh', 'margin:0', 'z-index:99999',
      'background:#000', 'overflow:hidden', 'transform:none'
    ].map(s => s + ' !important').join(';');
  }}
  const html5 = document.querySelector('.html5-video-container');
  if (html5) {{
    html5.style.cssText = [
      'position:absolute', 'left:0', 'top:0', 'width:100%', 'height:100%'
    ].map(s => s + ' !important').join(';');
  }}

  const video = document.querySelector('video');
  const mp = document.getElementById('movie_player');
  if (video) {{
    out.ready = true;
    out.t = video.currentTime || 0;
    out.d = video.duration && isFinite(video.duration) ? video.duration : 0;
    out.ended = !!video.ended;
    try {{
      video.style.cssText = [
        'position:absolute', 'left:0', 'top:0', 'width:100%', 'height:100%',
        'object-fit:contain', 'background:#000'
      ].map(s => s + ' !important').join(';');
    }} catch (e) {{}}
    // Pause only — resume is handled once via _js_set_paused on user input.
    if (wantPaused) {{
      try {{
        if (mp && typeof mp.pauseVideo === 'function') mp.pauseVideo();
      }} catch (e) {{}}
      try {{ if (!video.paused) video.pause(); }} catch (e) {{}}
    }}
    out.playing = !video.paused && !video.ended;
  }}

  const cc = document.querySelector('.ytp-subtitles-button');
  if (cc && cc.getAttribute('aria-pressed') === 'true') {{
    cc.click();
  }}
  return out;
}})()
""".strip()

    @staticmethod
    def _js_set_volume(level_0_100: int) -> str:
        v = max(0.0, min(1.0, level_0_100 / 100.0))
        return f"""
(() => {{
  const v = {v:.4f};
  const video = document.querySelector('video');
  if (video) {{
    try {{ video.volume = v; video.muted = v <= 0; }} catch (e) {{}}
  }}
  try {{
    const mp = document.getElementById('movie_player');
    if (mp && typeof mp.setVolume === 'function') mp.setVolume(Math.round(v * 100));
    if (mp && typeof mp.unMute === 'function' && v > 0) mp.unMute();
    if (mp && typeof mp.mute === 'function' && v <= 0) mp.mute();
  }} catch (e) {{}}
  return v;
}})()
""".strip()

    @staticmethod
    def _js_set_paused(paused: bool) -> str:
        """Toggle via YouTube IFrame/HTML5 API only — never ``video.play()``."""
        return f"""
(() => {{
  const wantPaused = {str(paused).lower()};
  const mp = document.getElementById('movie_player');
  const video = document.querySelector('video');
  try {{
    if (mp) {{
      if (wantPaused && typeof mp.pauseVideo === 'function') mp.pauseVideo();
      else if (!wantPaused && typeof mp.playVideo === 'function') mp.playVideo();
    }}
  }} catch (e) {{}}
  // HTML5 pause as a stick for pause only. Calling the media element's play
  // method races the YouTube player and often surfaces "Something went wrong".
  if (wantPaused && video) {{
    try {{ if (!video.paused) video.pause(); }} catch (e) {{}}
  }}
  return wantPaused ? 'paused' : 'playing';
}})()
""".strip()

    @staticmethod
    def _js_seek(seconds: float) -> str:
        """Seek through the player API only (no direct currentTime write)."""
        t = max(0.0, float(seconds))
        return f"""
(() => {{
  try {{ window.scrollTo(0, 0); }} catch (e) {{}}
  const mp = document.getElementById('movie_player');
  try {{
    if (mp && typeof mp.seekTo === 'function') {{
      mp.seekTo({t:.3f}, true);
      return {t:.3f};
    }}
  }} catch (e) {{}}
  const video = document.querySelector('video');
  if (!video) return -1;
  try {{ video.currentTime = {t:.3f}; return video.currentTime; }}
  catch (e) {{ return -1; }}
}})()
""".strip()

    def _maybe_update_letterbox(self, jpeg: bytes) -> None:
        """Sample frames for baked-in pillarbox; lock a side crop + uniform zoom."""
        if self._letterbox_locked:
            return
        now = time.monotonic()
        if now - self._last_letterbox_check < 0.75:
            return
        # Wait longer after resume/seek so scrolled or black frames do not lock.
        min_frames = 36 if self.time_pos > 1.0 else 18
        if self._frame_count < min_frames:
            return
        self._last_letterbox_check = now
        try:
            surf = pygame.image.load(io.BytesIO(jpeg))
        except Exception:
            return
        # Sample at display size if screencast came back larger.
        if surf.get_width() != self.width or surf.get_height() != self.height:
            try:
                surf = scale_uniform(surf, self.width, self.height, mode="fit")
            except Exception:
                return
        rect = detect_letterbox_rect(surf)
        if rect is None:
            self._letterbox_samples.append((-1, -1, -1, -1))
        else:
            self._letterbox_samples.append(rect)
        # Keep a short window; require agreement before locking.
        self._letterbox_samples = self._letterbox_samples[-5:]
        if len(self._letterbox_samples) < 4:
            return
        valid = [r for r in self._letterbox_samples if r[0] >= 0]
        if len(valid) < 3:
            # Mostly full-bleed or letterbox-only — lock with no crop.
            if len(valid) == 0:
                self._letterbox_locked = True
            return
        # Median crop among agreeing samples.
        xs = sorted(r[0] for r in valid)
        ys = sorted(r[1] for r in valid)
        ws = sorted(r[2] for r in valid)
        hs = sorted(r[3] for r in valid)
        mid = len(valid) // 2
        crop = (xs[mid], ys[mid], ws[mid], hs[mid])
        with self._lock:
            # Side-crop the active picture; get_frame cover-zooms uniformly.
            self._content_crop = crop
            self._letterbox_locked = True
        LOG.info(
            "YouTube pillarbox crop=%s id=%s",
            crop,
            self._youtube_id,
        )

    def _ws_thread(self, ws_url: str) -> None:
        LOG.info("YouTube WS thread connecting…")
        try:
            ws = websocket.create_connection(
                ws_url, timeout=10, suppress_origin=True
            )
        except Exception as exc:
            self._error = f"connect failed: {exc}"
            LOG.warning("YouTube CDP connect failed: %s", exc)
            self._available = False
            self.running = False
            return

        self._ws = ws
        ws.settimeout(1.0)

        try:
            self._send(
                ws,
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": self.width,
                    "height": self.height,
                    "deviceScaleFactor": 1,
                    "mobile": False,
                    "screenWidth": self.width,
                    "screenHeight": self.height,
                },
            )
        except Exception as exc:
            LOG.warning("YouTube device metrics failed: %s", exc)

        self._apply_caption_cookie(ws)

        try:
            self._send(ws, "Page.navigate", {"url": self._navigate_url})
            time.sleep(2.5)
            # Pin scroll before the first screencast frames are sampled.
            self._send(
                ws,
                "Runtime.evaluate",
                {
                    "expression": (
                        "window.scrollTo(0,0);"
                        "document.documentElement.scrollTop=0;"
                        "document.body.scrollTop=0;"
                        "0"
                    ),
                    "returnByValue": True,
                },
            )
        except Exception as exc:
            self._error = f"navigate failed: {exc}"
            LOG.warning("YouTube navigate failed: %s", exc)
            self._available = False
            self.running = False
            try:
                ws.close()
            except Exception:
                pass
            return

        try:
            self._send(
                ws,
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 80,
                    "maxWidth": self.width,
                    "maxHeight": self.height,
                    "everyNthFrame": 1,
                },
            )
            LOG.info(
                "YouTube screencast started (%dx%d) %s",
                self.width,
                self.height,
                self._navigate_url,
            )
            self._available = True
        except Exception as exc:
            self._error = f"startScreencast failed: {exc}"
            LOG.warning("YouTube startScreencast failed: %s", exc)
            self._available = False
            self.running = False
            try:
                ws.close()
            except Exception:
                pass
            return

        pending: dict[int, str] = {}
        last_watchdog = 0.0
        # Layout-only cadence; keep gentle so we do not fight the player.
        WATCHDOG_INTERVAL = 1.0
        PAUSED_WATCHDOG_INTERVAL = 0.6

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
            nonlocal last_watchdog
            now = time.time()
            with self._lock:
                dirty = self._volume_dirty
                vol = self.volume
                if dirty:
                    self._volume_dirty = False
                pause_dirty = self._pause_dirty
                paused = self.paused
                if pause_dirty:
                    self._pause_dirty = False
                seek_to = self._seek_to
                self._seek_to = None
                play_kick = self._play_kick_pending
                suppress_until = self._suppress_watchdog_until

            if pause_dirty:
                # Single playVideo / pauseVideo — do not also re-enter via watchdog.
                fire_eval("pause", self._js_set_paused(paused))
                if not paused:
                    fire_eval("volume", self._js_set_volume(vol))
                    self._play_kick_pending = False
            elif dirty and not paused:
                fire_eval("volume", self._js_set_volume(vol))
            if seek_to is not None:
                fire_eval("seek", self._js_seek(seek_to))
                # Seeking buffers with video.paused=true; skip layout for a beat
                # so we do not race the player mid-seek.
                self._suppress_watchdog_until = now + 0.85
                suppress_until = self._suppress_watchdog_until
                # One deferred playVideo after scrub settles (not during buffer).
                if not paused:
                    self._play_kick_pending = True
            elif (
                play_kick
                and not paused
                and self._frame_count >= 8
                and now >= suppress_until
            ):
                # One-shot autoplay / post-seek resume — never every watchdog tick.
                fire_eval("pause", self._js_set_paused(False))
                self._play_kick_pending = False

            interval = PAUSED_WATCHDOG_INTERVAL if paused else WATCHDOG_INTERVAL
            if now < suppress_until:
                return
            if pause_dirty:
                # Pause already applied; layout on the next interval.
                last_watchdog = now
                return
            if now - last_watchdog >= interval:
                last_watchdog = now
                fire_eval("watchdog", self._js_watchdog(want_paused=paused))

        pump_side_effects()

        while self.running:
            pump_side_effects()
            try:
                data = ws.recv()
            except Exception as exc:
                name = type(exc).__name__
                if "Timeout" in name or "timed out" in str(exc).lower():
                    continue
                if not self.running:
                    break
                LOG.warning("YouTube recv error: %s", exc)
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
                        self._apply_player_state(value)
                continue

            method = msg.get("method")
            if method == "Page.screencastFrame":
                params = msg.get("params") or {}
                session_id = params.get("sessionId")
                b64 = params.get("data")
                if b64:
                    try:
                        jpeg = base64.b64decode(b64)
                    except Exception:
                        jpeg = None
                    if jpeg:
                        with self._lock:
                            paused_now = self.paused
                            # Freeze the displayed frame while paused so a
                            # failed CDP pause still looks paused.
                            if not paused_now or self._latest_jpeg is None:
                                self._latest_jpeg = jpeg
                                self._frame_count += 1
                                should_sample = not paused_now
                            else:
                                should_sample = False
                        if should_sample:
                            self._maybe_update_letterbox(jpeg)
                        self._available = True
                if session_id is not None:
                    try:
                        self._send(
                            ws,
                            "Page.screencastFrameAck",
                            {"sessionId": session_id},
                        )
                    except Exception:
                        pass

        try:
            ws.close()
        except Exception:
            pass
        self._ws = None
        LOG.info("YouTube WS thread exit (frames=%d)", self._frame_count)

    def _apply_player_state(self, state: dict) -> None:
        try:
            t = float(state.get("t") or 0)
            d = float(state.get("d") or 0)
        except (TypeError, ValueError):
            t, d = 0.0, 0.0
        if d > 0:
            self.duration = d
        if t >= 0 and not self.paused:
            self.time_pos = t
            self._start_mono = time.monotonic() - t - self._pause_offset
        if state.get("ended"):
            self.finished = True
            self.time_pos = self.duration or self.time_pos
