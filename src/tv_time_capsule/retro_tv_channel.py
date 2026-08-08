"""MyRetroTVs decade streams via Chrome DevTools Protocol.

Two modes:

* **live** (default) — hide decorative TV chrome and capture frames via
  ``Page.startScreencast`` (desktop-friendly).
* **director** — no screencast; drive power/filters/CH▲▼ and scrape the
  YouTube embed id so a temp yt-dlp cache can play via ffmpeg (Pi-friendly).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time

import pygame

from .chrome_cdp import ensure_chromium, kill_port_process, wait_for_page_ws

_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:embed|shorts)/|youtu\.be/|[?&]v=)([\w-]{11})"
)


def youtube_id_from_embed_url(url: str | None) -> str | None:
    """Extract an 11-char YouTube id from an embed / watch URL."""
    if not url:
        return None
    m = _YOUTUBE_ID_RE.search(str(url))
    return m.group(1) if m else None

try:
    import websocket  # type: ignore[import-untyped]
except ImportError:
    websocket = None  # type: ignore[assignment]

LOG = logging.getLogger(__name__)

CDP_PORT = 9225

_YEAR_MIN = 1950
_YEAR_MAX = 2009


def decade_slug_for_year(year: int) -> str | None:
    """Map a calendar year to a MyRetroTVs decade slug, or None if out of range."""
    if year < _YEAR_MIN or year > _YEAR_MAX:
        return None
    decade = (year // 10) * 10
    if decade == 2000:
        return "00"
    return str(decade)[2:]  # 1950 → "50", 1990 → "90"


def url_for_decade(slug: str) -> str:
    """Return the canonical HTTPS URL for a decade slug (e.g. ``90``)."""
    return f"https://{slug}s.myretrotvs.com/"


def decade_slug_from_digits(digits: str) -> str | None:
    """If *digits* is a 4-digit year in range, return its decade slug."""
    if len(digits) != 4 or not digits.isdigit() or digits.startswith("0"):
        return None
    return decade_slug_for_year(int(digits))


class RetroTvChannel:
    """Headless Chrome CDP screencast of a MyRetroTVs decade site → pygame."""

    def __init__(
        self,
        url: str,
        width: int,
        height: int,
        *,
        filters: dict[str, bool] | None = None,
        volume: int | None = None,
        director: bool = False,
    ) -> None:
        self._url = url
        self._width = max(width, 320)
        self._height = max(height, 240)
        self._director = bool(director)
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
        self._volume = 100 if volume is None else max(0, min(100, int(volume)))
        self._volume_dirty = True
        self._channel_delta = 0  # pending CH ▲/▼ clicks
        self._last_power_log = 0.0
        self._filters: list[dict] = []  # {id, name, on}
        self._filter_cmds: list[str] = []  # "all" | "none" | "toggle:box_c" | "apply"
        self._desired_filters: dict[str, bool] | None = (
            dict(filters) if filters else None
        )
        self._filters_need_apply = bool(filters)
        self._last_caption_iframe_pass = 0.0
        self._youtube_id: str | None = None
        self._tv_on = False
        self._pause_embed_pending = False

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @property
    def director_mode(self) -> bool:
        return self._director

    def start(self) -> bool:
        """Launch Chrome. Live mode starts screencast; director waits for embed id."""
        if self._available:
            return True

        if websocket is None:
            LOG.warning("websocket-client not installed")
            return False

        chrome_path = ensure_chromium(log_label="retro TV")
        if chrome_path is None:
            LOG.warning("Chrome not found – retro TV unavailable")
            return False

        for attempt in (1, 2):
            if self._start_once(chrome_path):
                return True
            self.stop()
            if attempt == 1:
                LOG.info("Retro TV first start failed; retrying…")
                time.sleep(0.8)
        return False

    def start_director(self) -> bool:
        """Launch Chrome as a playlist oracle (no screencast)."""
        self._director = True
        return self.start()

    def _start_once(self, chrome_path: str) -> bool:
        kill_port_process(CDP_PORT)
        time.sleep(0.3)

        self._user_data_dir = tempfile.mkdtemp(prefix="ttc-retro-")

        try:
            chrome_args = [
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
            ]
            if self._director:
                chrome_args.append("--mute-audio")
            chrome_args.append("about:blank")
            self._chrome = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            LOG.warning("Failed to launch Chrome: %s", exc)
            self._cleanup_user_data()
            return False

        ws_url = wait_for_page_ws(CDP_PORT, chrome=self._chrome, timeout=12.0)
        if ws_url is None:
            LOG.warning("No CDP page target found for retro TV")
            return False

        self._running = True
        self._available = True
        self._frame_count = 0
        self._start_time = time.time()
        self._error = None
        self._volume_dirty = True
        self._youtube_id = None
        self._tv_on = False
        self._thread = threading.Thread(
            target=self._ws_thread, args=(ws_url,), daemon=True, name="retro-cdp"
        )
        self._thread.start()

        # Live needs a frame. Director only needs Chrome + page control — the
        # embed id often arrives after power-on / playlist settle (wait in boot).
        deadline = time.time() + (12.0 if self._director else 25.0)
        while time.time() < deadline and self._running:
            with self._lock:
                yid = self._youtube_id
                tv_on = self._tv_on
            if not yid:
                yid = self._youtube_id_from_cdp_targets()
                if yid:
                    with self._lock:
                        self._youtube_id = yid
            if self._director:
                if yid:
                    LOG.info(
                        "Retro TV director ready id=%s url=%s",
                        yid,
                        self._url,
                    )
                    return True
                # Page is controllable once powered (or after navigate settle).
                if tv_on or (time.time() - self._start_time) >= 8.0:
                    LOG.info(
                        "Retro TV director page ready (awaiting embed) url=%s on=%s",
                        self._url,
                        tv_on,
                    )
                    return True
            elif self._latest_jpeg is not None:
                LOG.info(
                    "Retro TV started (%d frames so far) url=%s",
                    self._frame_count,
                    self._url,
                )
                return True
            if self._error:
                break
            time.sleep(0.05)

        LOG.warning(
            "Retro TV: %s after %.1fs (%s)",
            "director not ready" if self._director else "no frames",
            time.time() - self._start_time,
            self._error or "timeout",
        )
        return False

    def stop(self) -> None:
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
        LOG.info("Retro TV stopped (frames=%d)", self._frame_count)

    def get_frame(self) -> pygame.Surface | None:
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
        with self._lock:
            return self._volume

    def adjust_volume(self, delta: int) -> int:
        with self._lock:
            self._volume = max(0, min(100, self._volume + int(delta)))
            self._volume_dirty = True
            return self._volume

    def set_volume(self, level: int) -> int:
        with self._lock:
            self._volume = max(0, min(100, int(level)))
            self._volume_dirty = True
            return self._volume

    def channel_up(self) -> None:
        """Queue a click on the site's CH ▲ button."""
        with self._lock:
            self._channel_delta += 1

    def channel_down(self) -> None:
        """Queue a click on the site's CH ▼ button."""
        with self._lock:
            self._channel_delta -= 1

    def current_youtube_id(self) -> str | None:
        """Latest YouTube embed id scraped from the page (director or live)."""
        with self._lock:
            return self._youtube_id

    def wait_for_youtube_id(
        self,
        timeout: float = 30.0,
        *,
        different_from: str | None = None,
    ) -> str | None:
        """Block until an embed id is available (optionally changed)."""
        deadline = time.time() + max(0.5, float(timeout))
        while time.time() < deadline and self._running:
            with self._lock:
                yid = self._youtube_id
            if not yid:
                yid = self._youtube_id_from_cdp_targets()
                if yid:
                    with self._lock:
                        self._youtube_id = yid
            if yid and (different_from is None or yid != different_from):
                return yid
            time.sleep(0.1)
        with self._lock:
            yid = self._youtube_id
        if not yid:
            yid = self._youtube_id_from_cdp_targets()
            if yid:
                with self._lock:
                    self._youtube_id = yid
        if yid and (different_from is None or yid != different_from):
            return yid
        return None

    def _youtube_id_from_cdp_targets(self) -> str | None:
        """Fallback: read embed URL from CDP /json/list targets."""
        try:
            import urllib.request

            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1
            )
            targets = json.loads(resp.read())
        except Exception:
            return None
        if not isinstance(targets, list):
            return None
        for target in targets:
            if not isinstance(target, dict):
                continue
            url = target.get("url") or ""
            yid = youtube_id_from_embed_url(url)
            if yid:
                return yid
        return None

    def request_pause_embed(self) -> None:
        """Pause/mute the site's YouTube embed so we own playback timing."""
        with self._lock:
            self._pause_embed_pending = True

    def get_filters(self) -> list[dict]:
        """Latest channel-type filter snapshot from the page."""
        with self._lock:
            return [dict(item) for item in self._filters]

    def filter_map(self) -> dict[str, bool]:
        """Id → enabled map suitable for config persistence."""
        with self._lock:
            return {str(item["id"]): bool(item["on"]) for item in self._filters}

    def toggle_filter(self, box_id: str) -> None:
        """Queue a click on a filter checkbox (e.g. ``box_c``)."""
        box_id = (box_id or "").strip()
        if not box_id:
            return
        with self._lock:
            # Drop stale config-apply cmds so they don't fight the user.
            self._filter_cmds = [
                c for c in self._filter_cmds if not c.startswith("apply:")
            ]
            self._filters_need_apply = False
            self._filter_cmds.append(f"toggle:{box_id}")
            # Optimistic local update for immediate menu + persist.
            for item in self._filters:
                if item.get("id") == box_id:
                    item["on"] = not bool(item.get("on"))
                    break
            self._desired_filters = {
                str(item["id"]): bool(item["on"]) for item in self._filters
            }

    def select_all_filters(self) -> None:
        with self._lock:
            self._filter_cmds = [
                c for c in self._filter_cmds if not c.startswith("apply:")
            ]
            self._filters_need_apply = False
            self._filter_cmds.append("all")
            for item in self._filters:
                item["on"] = True
            self._desired_filters = {
                str(item["id"]): True for item in self._filters
            }

    def select_none_filters(self) -> None:
        with self._lock:
            self._filter_cmds = [
                c for c in self._filter_cmds if not c.startswith("apply:")
            ]
            self._filters_need_apply = False
            self._filter_cmds.append("none")
            for item in self._filters:
                item["on"] = False
            self._desired_filters = {
                str(item["id"]): False for item in self._filters
            }

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

    # Hide decorative chrome and fullscreen the YouTube player; click power.
    # 70s–00s use #btn_power; 50s/60s use #tvknob (no power button in the DOM).
    _JS_WATCHDOG = r"""
(() => {
  const out = {power: false, crop: true, on: false, youtubeId: null};
  const hideSels = [
    '#tvbackground', '#tvstencil', '#glass', '#tvbuttons', '#sidebar',
    '#logo', '#hand', '#credit', '#guide', '#yearbar',
    '#statusbar', '#channellabel', '#lcdbar', '#tvled',
    '#tvledmini', '#tubeglow', '#tvstatic', '.tvcurtain', '#iconreport',
    '#iconbsky', '#iconsuggest', '#remotestatus', '#tvpanel_menu',
    '#tvpanel_voldn', '#tvpanel_volup', '#tvpanel_chdn', '#tvpanel_chup',
    '#help', '#helpback', '#loader', '#tvknob-back',
    '#knob-container-col', '#knob-container-bri', '#knob-container-con',
    '#knob-container-sha', '#knob-container-tin', '#knob-container-vol',
    '#tvdial', '#tvdial2'
  ];
  for (const sel of hideSels) {
    for (const el of document.querySelectorAll(sel)) {
      el.style.setProperty('display', 'none', 'important');
      el.style.setProperty('visibility', 'hidden', 'important');
      el.style.setProperty('opacity', '0', 'important');
      el.style.setProperty('pointer-events', 'none', 'important');
    }
  }
  // Keep #tvknob / #tvfilters in the DOM (power + category filters) but park
  // them off-screen so site JS (jQuery handlers / opacity checks) still works.
  const parkOffscreen = (el) => {
    if (!el) return;
    el.style.setProperty('position', 'fixed', 'important');
    el.style.setProperty('left', '-9999px', 'important');
    el.style.setProperty('top', '0', 'important');
    el.style.setProperty('display', 'block', 'important');
    el.style.setProperty('visibility', 'visible', 'important');
    el.style.setProperty('pointer-events', 'auto', 'important');
  };
  parkOffscreen(document.getElementById('tvknob'));
  parkOffscreen(document.getElementById('tvfilters'));

  const wrap = document.querySelector('main.wrapper') || document.querySelector('.wrapper');
  if (wrap) {
    wrap.style.setProperty('opacity', '1', 'important');
    wrap.style.setProperty('transform', 'none', 'important');
    wrap.style.setProperty('pointer-events', 'auto', 'important');
  }
  document.body.style.setProperty('overflow', 'hidden', 'important');
  document.documentElement.style.setProperty('background', '#000', 'important');
  document.body.style.setProperty('background', '#000', 'important');

  const p = document.getElementById('myytplayer');
  if (p) {
    p.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'right:0', 'bottom:0',
      'width:100vw', 'height:100vh', 'margin:0', 'padding:0',
      'visibility:visible', 'opacity:1', 'z-index:9999',
      'background:#000', 'display:block'
    ].map(s => s + ' !important').join(';');
    for (const iframe of p.querySelectorAll('iframe')) {
      iframe.style.cssText = [
        'position:absolute', 'left:0', 'top:0',
        'width:100%', 'height:100%', 'border:0'
      ].map(s => s + ' !important').join(';');
    }
  }

  const powerBtn = document.getElementById('btn_power');
  const powerKnob = document.getElementById('tvknob');
  let isOn = false;
  if (powerBtn) {
    // 70s+: OFF = #f00 (red), ON = #0f0 (green). Toggle — never click while on.
    const color = (
      powerBtn.style.color ||
      (getComputedStyle(powerBtn).color || '') ||
      ''
    ).toLowerCase().replace(/\s+/g, '');
    isOn =
      color.includes('#0f0') ||
      color.includes('rgb(0,255,0)') ||
      color.includes('rgba(0,255,0');
  } else if (powerKnob) {
    // 50s/60s: CSS default opacity 0 (off); site sets opacity 1 when on.
    const raw = powerKnob.style.opacity;
    const op = parseFloat(raw !== '' && raw != null ? raw : getComputedStyle(powerKnob).opacity);
    isOn = !Number.isNaN(op) && op > 0.5;
  }
  if (!isOn && p && (p.querySelector('iframe') || p.querySelector('video'))) {
    isOn = true;
  }
  out.on = isOn;

  // MyRetroTVs calls He().loadVideoById on power-on. He() is null until the
  // IFrame API player is ready; clicking early leaves the TV "on" with a dead
  // power button (togglePower no-ops while on && !tv_started).
  let playerReady = false;
  try {
    playerReady = !!(window.YT && YT.get && YT.get('myytplayer'));
  } catch (e) {}
  out.playerReady = playerReady;

  if (!isOn) {
    const now = Date.now();
    const last = window.__ttcPowerClickAt || 0;
    if (playerReady && now - last > 5000) {
      window.__ttcPowerClickAt = now;
      const target = powerBtn || powerKnob;
      if (target) {
        try { target.click(); out.power = true; } catch (e) {}
      } else {
        try {
          document.dispatchEvent(new KeyboardEvent('keydown', {
            key: ' ', code: 'Space', keyCode: 32, which: 32, bubbles: true
          }));
          out.power = true;
        } catch (e) {}
      }
    }
  }

  // Sites set cc_load_policy:0, but YouTube still restores caption prefs.
  // Force captions off via IFrame API postMessage (enablejsapi is on).
  out.cc = false;
  const takeId = (raw) => {
    if (!raw || typeof raw !== 'string') return;
    const bare = raw.replace(/^#/, '');
    if (/^[\w-]{11}$/.test(bare) && !out.youtubeId) {
      out.youtubeId = bare;
      return;
    }
    let m = raw.match(/[?&]v=([\w-]{11})/);
    if (!m) m = raw.match(/\/(?:embed|shorts)\/([\w-]{11})/);
    if (!m) m = raw.match(/youtu\.be\/([\w-]{11})/);
    if (!m) m = raw.match(/"videoId"\s*:\s*"([\w-]{11})"/);
    if (m && !out.youtubeId) out.youtubeId = m[1];
  };
  // Prefer site state: power-on sets location.hash to the decoded YouTube id
  // even when the embed iframe src stays empty (common in headless Chrome).
  try { takeId(location.hash || ''); } catch (e) {}
  try {
    const pl = window.YT && YT.get && YT.get('myytplayer');
    if (pl) {
      try {
        const data = pl.getVideoData && pl.getVideoData();
        if (data && data.video_id) takeId(String(data.video_id));
      } catch (e) {}
      try {
        if (!out.youtubeId && pl.getVideoUrl) takeId(String(pl.getVideoUrl()));
      } catch (e) {}
    }
  } catch (e) {}
  for (const iframe of document.querySelectorAll(
    '#myytplayer iframe, iframe[src*="youtu"], iframe[data-src*="youtu"]'
  )) {
    try {
      takeId(iframe.src || iframe.getAttribute('src') || '');
      takeId(iframe.getAttribute('data-src') || '');
      const w = iframe.contentWindow;
      if (!w) continue;
      const send = (payload) => {
        w.postMessage(typeof payload === 'string' ? payload : JSON.stringify(payload), '*');
      };
      send({ event: 'listening', id: 1, channel: 'widget' });
      send({ event: 'command', func: 'unloadModule', args: ['captions'] });
      send({ event: 'command', func: 'unloadModule', args: ['captions'] });
      send({ event: 'command', func: 'setOption', args: ['captions', 'track', {}] });
      out.cc = true;
    } catch (e) {}
  }
  if (!out.youtubeId) {
    try {
      takeId(document.documentElement ? document.documentElement.innerHTML : '');
    } catch (e) {}
  }
  if (!out.youtubeId) {
    try {
      const scripts = document.querySelectorAll('script');
      for (const s of scripts) {
        takeId(s.textContent || '');
        if (out.youtubeId) break;
      }
    } catch (e) {}
  }

  // Early power-on before He() was ready: retune once the player exists so
  // loadClip/loadVideoById runs and hash/video_id populate.
  if (isOn && !out.youtubeId && playerReady) {
    const now = Date.now();
    const last = window.__ttcRetuneAt || 0;
    if (now - last > 4000) {
      window.__ttcRetuneAt = now;
      out.retune = true;
      try {
        const next = document.getElementById('btn_next');
        if (next) next.click();
        else {
          document.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'ArrowRight', code: 'ArrowRight', keyCode: 39, which: 39, bubbles: true
          }));
        }
      } catch (e) {}
    }
  }

  // Channel-type filters (tvfilters checkboxes).
  out.filters = [];
  for (const input of document.querySelectorAll('#tvfilters input[type=checkbox]')) {
    const id = input.id || '';
    if (!id.startsWith('box_')) continue;
    const label = document.querySelector('label[for="' + id + '"]');
    let name = ((label && (label.innerText || label.textContent)) || id).trim();
    name = name.replace(/\s*\(\d+\)\s*$/, '').trim() || id;
    if (!name) continue;
    out.filters.push({ id: id, name: name, on: !!input.checked });
  }
  return out;
})()
""".strip()

    _JS_PAUSE_EMBED = r"""
(() => {
  let n = 0;
  for (const iframe of document.querySelectorAll('#myytplayer iframe, iframe[src*="youtube"]')) {
    try {
      const w = iframe.contentWindow;
      if (!w) continue;
      const send = (payload) => {
        w.postMessage(JSON.stringify(payload), '*');
      };
      send({ event: 'command', func: 'pauseVideo', args: [] });
      send({ event: 'command', func: 'mute', args: [] });
      send({ event: 'command', func: 'setVolume', args: [0] });
      n += 1;
    } catch (e) {}
  }
  for (const m of document.querySelectorAll('audio, video')) {
    try { m.pause(); m.muted = true; m.volume = 0; } catch (e) {}
  }
  return n;
})()
""".strip()

    @staticmethod
    def _js_click_channel(direction: int) -> str:
        """Click CH ▲/▼, or synthesize arrow keys on decades without those buttons."""
        btn = "btn_next" if direction > 0 else "btn_prev"
        # ArrowUp/Right = next, ArrowDown/Left = prev (site keyboard map).
        key = "ArrowRight" if direction > 0 else "ArrowLeft"
        key_code = 39 if direction > 0 else 37
        return f"""
(() => {{
  const b = document.getElementById('{btn}');
  if (b) {{ try {{ b.click(); return 'btn'; }} catch (e) {{}} }}
  try {{
    document.dispatchEvent(new KeyboardEvent('keydown', {{
      key: '{key}', code: '{key}', keyCode: {key_code}, which: {key_code}, bubbles: true
    }}));
    return 'key';
  }} catch (e) {{}}
  return false;
}})()
""".strip()

    @staticmethod
    def _js_set_media_gain(level_0_100: int) -> str:
        v = max(0.0, min(1.0, level_0_100 / 100.0))
        return f"""
(() => {{
  const v = {v:.4f};
  for (const m of document.querySelectorAll("audio, video")) {{
    try {{ m.volume = v; m.muted = false; }} catch (e) {{}}
  }}
  return v;
}})()
""".strip()

    @staticmethod
    def _js_filter_command(cmd: str) -> str:
        """Toggle/apply filters and retune so the playing stream reflects them.

        MyRetroTVs stores the active mask in a closure (``Fe.update``). We set
        checkbox state then ``triggerHandler('click')`` so that runs without
        double-toggling. ``changeChan`` early-outs on 0, so we nudge CH▲ to
        pick the next valid channel under the new mask (immediate feedback).
        """
        retune = r"""
  try {
    const next = document.getElementById('btn_next');
    if (next) next.click();
    else document.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowRight', code: 'ArrowRight', keyCode: 39, which: 39, bubbles: true
    }));
  } catch (e) {}
"""
        helper = r"""
  const $ = window.jQuery || window.$;
  const fireUpdate = () => {
    const any = document.querySelector('#tvfilters input[type=checkbox]');
    if (!any) return;
    if ($ && $.fn) { $(any).triggerHandler('click'); return; }
    any.dispatchEvent(new Event('click', { bubbles: true }));
  };
"""
        if cmd == "all":
            return f"""
(() => {{
{helper}
  document.querySelectorAll('#tvfilters input[type=checkbox]').forEach((c) => {{
    c.checked = true;
  }});
  fireUpdate();
{retune}
  return 'all';
}})()
""".strip()
        if cmd == "none":
            return f"""
(() => {{
{helper}
  document.querySelectorAll('#tvfilters input[type=checkbox]').forEach((c) => {{
    c.checked = false;
  }});
  fireUpdate();
{retune}
  return 'none';
}})()
""".strip()
        if cmd.startswith("toggle:"):
            box_id = cmd.split(":", 1)[1]
            safe = "".join(ch for ch in box_id if ch.isalnum() or ch == "_")
            return f"""
(() => {{
{helper}
  const el = document.getElementById({safe!r});
  if (!el) return null;
  el.checked = !el.checked;
  fireUpdate();
{retune}
  return !!el.checked;
}})()
""".strip()
        if cmd.startswith("apply:"):
            payload = cmd[6:]
            return f"""
(() => {{
{helper}
  let desired;
  try {{ desired = {payload}; }} catch (e) {{ return 'bad-json'; }}
  if (!desired || typeof desired !== 'object') return 'bad';
  let changed = 0;
  document.querySelectorAll('#tvfilters input[type=checkbox]').forEach((c) => {{
    if (!(c.id in desired)) return;
    const want = !!desired[c.id];
    if (!!c.checked !== want) {{ c.checked = want; changed++; }}
  }});
  fireUpdate();
  if (changed > 0) {{
{retune}
  }}
  return changed;
}})()
""".strip()
        return "null"

    @staticmethod
    def _js_disable_captions_in_player() -> str:
        """Run inside a YouTube embed document: turn CC off if enabled."""
        return r"""
(() => {
  const btn = document.querySelector('.ytp-subtitles-button, button[aria-label*="Subtitles"], button[aria-label*="Captions"]');
  if (btn && btn.getAttribute('aria-pressed') === 'true') {
    btn.click();
    return 'clicked';
  }
  // Settings menu path as fallback when button state is unclear.
  try {
    if (window.yt && window.yt.player) {}
  } catch (e) {}
  return btn ? (btn.getAttribute('aria-pressed') || 'unknown') : 'no-btn';
})()
""".strip()

    def _apply_youtube_caption_cookie(self, ws) -> None:
        """Prefer captions-off via YouTube PREF cookie before navigate."""
        try:
            self._send(ws, "Network.enable")
            # f6=8 is widely used to keep auto-captions off for embeds.
            self._send(
                ws,
                "Network.setCookie",
                {
                    "name": "PREF",
                    "value": "f6=8&f5=30000&hl=en",
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "None",
                },
            )
            self._send(
                ws,
                "Network.setCookie",
                {
                    "name": "PREF",
                    "value": "f6=8&f5=30000&hl=en",
                    "domain": ".youtube-nocookie.com",
                    "path": "/",
                    "secure": True,
                    "sameSite": "None",
                },
            )
        except Exception as exc:
            LOG.warning("YouTube caption cookie inject failed: %s", exc)

    def _disable_captions_via_iframe_cdp(self) -> None:
        """Attach to YouTube embed targets and click the CC button if on."""
        if websocket is None:
            return
        try:
            import urllib.request

            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1
            )
            targets = json.loads(resp.read())
        except Exception:
            return

        for target in targets:
            url = (target.get("url") or "").lower()
            if "youtube.com/embed" not in url and "youtube-nocookie.com/embed" not in url:
                continue
            ws_url = target.get("webSocketDebuggerUrl")
            if not ws_url:
                continue
            try:
                iframe_ws = websocket.create_connection(
                    ws_url, timeout=2, suppress_origin=True
                )
                iframe_ws.send(
                    json.dumps(
                        {
                            "id": 1,
                            "method": "Runtime.evaluate",
                            "params": {
                                "expression": self._js_disable_captions_in_player(),
                                "returnByValue": True,
                                "userGesture": True,
                            },
                        }
                    )
                )
                try:
                    iframe_ws.recv()
                except Exception:
                    pass
                iframe_ws.close()
            except Exception:
                continue

    def _ws_thread(self, ws_url: str) -> None:
        LOG.info("Retro TV WS thread connecting…")
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
        ws.settimeout(1.0)

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

        self._apply_youtube_caption_cookie(ws)

        try:
            self._send(ws, "Page.navigate", {"url": self._url})
            time.sleep(3.0)
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

        if not self._director:
            try:
                self._send(
                    ws,
                    "Page.startScreencast",
                    {
                        "format": "jpeg",
                        "quality": 80,
                        "maxWidth": self._width,
                        "maxHeight": self._height,
                        "everyNthFrame": 1,
                    },
                )
                LOG.info(
                    "Retro screencast started (%dx%d) %s",
                    self._width,
                    self._height,
                    self._url,
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
        else:
            LOG.info("Retro director started (no screencast) %s", self._url)
            try:
                self._send(ws, "Network.enable", {})
            except Exception as exc:
                LOG.debug("Retro TV Network.enable failed: %s", exc)

        pending: dict[int, str] = {}
        last_watchdog = 0.0
        WATCHDOG_INTERVAL = 0.75 if self._director else 1.0
        CAPTION_IFRAME_INTERVAL = 2.5

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
            if now - last_watchdog >= WATCHDOG_INTERVAL:
                last_watchdog = now
                fire_eval("watchdog", self._JS_WATCHDOG)

            if not self._director:
                if now - self._last_caption_iframe_pass >= CAPTION_IFRAME_INTERVAL:
                    self._last_caption_iframe_pass = now
                    try:
                        self._disable_captions_via_iframe_cdp()
                    except Exception:
                        pass

            with self._lock:
                dirty = self._volume_dirty
                vol = self._volume
                if dirty:
                    self._volume_dirty = False
                ch_delta = self._channel_delta
                self._channel_delta = 0
                filter_cmds = list(self._filter_cmds)
                self._filter_cmds.clear()
                pause_embed = self._pause_embed_pending
                if pause_embed:
                    self._pause_embed_pending = False

            if dirty and not self._director:
                fire_eval("volume", self._js_set_media_gain(vol))
            if pause_embed:
                fire_eval("pause", self._JS_PAUSE_EMBED)
            while ch_delta > 0:
                fire_eval("channel", self._js_click_channel(1))
                ch_delta -= 1
            while ch_delta < 0:
                fire_eval("channel", self._js_click_channel(-1))
                ch_delta += 1
            for cmd in filter_cmds:
                fire_eval("filter", self._js_filter_command(cmd))

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
                LOG.warning("Retro TV recv error: %s", exc)
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
                        if value.get("power") and now - self._last_power_log > 3.0:
                            LOG.info("Retro TV UI: POWER clicked (TV was off)")
                            self._last_power_log = now
                            with self._lock:
                                self._volume_dirty = True
                        yid_raw = value.get("youtubeId")
                        yid = None
                        if isinstance(yid_raw, str) and len(yid_raw) == 11:
                            yid = yid_raw
                        filters = value.get("filters")
                        cleaned: list[dict] = []
                        if isinstance(filters, list):
                            for item in filters:
                                if not isinstance(item, dict):
                                    continue
                                fid = item.get("id")
                                fname = item.get("name")
                                if not isinstance(fid, str) or not isinstance(fname, str):
                                    continue
                                cleaned.append(
                                    {
                                        "id": fid,
                                        "name": fname,
                                        "on": bool(item.get("on")),
                                    }
                                )
                        apply_cmd: str | None = None
                        with self._lock:
                            self._tv_on = bool(value.get("on"))
                            if yid and yid != self._youtube_id:
                                self._youtube_id = yid
                                LOG.info("Retro TV embed id=%s (watchdog)", yid)
                            if cleaned:
                                self._filters = cleaned
                                if (
                                    self._filters_need_apply
                                    and self._desired_filters
                                    and cleaned
                                ):
                                    mismatch = any(
                                        item["id"] in self._desired_filters
                                        and bool(item["on"])
                                        != bool(self._desired_filters[item["id"]])
                                        for item in cleaned
                                    )
                                    if mismatch:
                                        apply_cmd = "apply:" + json.dumps(
                                            self._desired_filters,
                                            separators=(",", ":"),
                                        )
                                    else:
                                        self._filters_need_apply = False
                        if apply_cmd:
                            with self._lock:
                                self._filter_cmds.append(apply_cmd)
                continue

            method = msg.get("method")
            if self._director and method in (
                "Network.requestWillBeSent",
                "Network.responseReceived",
            ):
                params = msg.get("params") or {}
                url = ""
                if method == "Network.requestWillBeSent":
                    url = str(((params.get("request") or {}).get("url")) or "")
                else:
                    url = str(((params.get("response") or {}).get("url")) or "")
                yid = youtube_id_from_embed_url(url)
                if yid:
                    with self._lock:
                        if yid != self._youtube_id:
                            self._youtube_id = yid
                            self._tv_on = True
                            LOG.info("Retro TV embed id=%s (network)", yid)
                continue

            if self._director:
                continue

            if method != "Page.screencastFrame":
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
                    LOG.warning("Retro TV frame ack failed")
                break

            if not data_b64:
                continue
            try:
                jpeg = base64.b64decode(data_b64)
            except Exception:
                continue

            with self._lock:
                self._latest_jpeg = jpeg
                self._frame_count += 1
                count = self._frame_count

            if count == 1:
                LOG.info("Retro TV first frame (%d bytes)", len(jpeg))

        try:
            if self._running is False and not self._director:
                try:
                    self._send(ws, "Page.stopScreencast")
                except Exception:
                    pass
            ws.close()
        except Exception:
            pass
        self._ws = None
        LOG.info("Retro TV WS thread stopped (frames=%d)", self._frame_count)
