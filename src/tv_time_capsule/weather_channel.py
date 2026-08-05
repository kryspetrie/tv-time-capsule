"""Weather Channel via Chrome DevTools Protocol screencast.

Launches a headless Chrome instance pointed at https://weather.com/retro/ and
captures frames via ``Page.startScreencast``.  Audio works because we use the
"new" headless mode (``--headless=new``) which runs the full browser stack.

If no system Chrome/Chromium is found, a portable Chromium is downloaded
automatically to the user cache directory.

WebSocket I/O runs in a dedicated background thread (create + recv + ack in
the same thread).  The main thread only reads the latest JPEG via
:meth:`get_frame`.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import pygame

try:
    import websocket  # type: ignore[import-untyped]
except ImportError:
    websocket = None  # type: ignore[assignment]

LOG = logging.getLogger(__name__)

CDP_PORT = 9224
WEATHER_URL = "https://weather.com/retro/"

# Playwright-published Chromium builds.
_CHROMIUM_REVISIONS: dict[str, str] = {
    "linux": "1097",
    "mac": "1097",
    "mac_arm": "1097",
}
_CHROMIUM_HOST = "https://playwright.azureedge.net/builds/chromium"


# ── Chromium helpers ────────────────────────────────────────────────────


def _cache_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "tv-time-capsule" / "chromium"


def _chromium_platform_key() -> str | None:
    if sys.platform == "linux":
        return "linux"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        return "mac_arm" if machine in ("arm64", "aarch64") else "mac"
    return None


def _chromium_download_url() -> str | None:
    key = _chromium_platform_key()
    if key is None:
        return None
    rev = _CHROMIUM_REVISIONS.get(key)
    if rev is None:
        return None
    return f"{_CHROMIUM_HOST}/{rev}/chromium-{key}.zip"


def _find_chrome() -> str | None:
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
    ):
        path = shutil.which(name)
        if path:
            return path
    mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if os.path.exists(mac_path):
        return mac_path
    return None


def _ensure_chromium() -> str | None:
    system = _find_chrome()
    if system is not None:
        return system

    cache = _cache_dir()
    key = _chromium_platform_key()
    if key is None:
        LOG.warning("Unsupported platform for Chromium download")
        return None

    if sys.platform == "darwin":
        chrome_bin = (
            cache / "chrome-mac" / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
        )
    elif sys.platform == "linux":
        chrome_bin = cache / "chrome-linux" / "chrome"
    else:
        return None

    if chrome_bin.is_file():
        _ensure_executable(chrome_bin)
        return str(chrome_bin)

    url = _chromium_download_url()
    if url is None:
        return None

    LOG.info("Downloading Chromium for weather channel...")
    try:
        cache.mkdir(parents=True, exist_ok=True)
        zip_path = cache / "chromium.zip"
        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(cache)
        zip_path.unlink()
    except Exception as exc:
        LOG.warning("Failed to download Chromium: %s", exc)
        return None

    if chrome_bin.is_file():
        _ensure_executable(chrome_bin)
        LOG.info("Chromium ready at %s", chrome_bin)
        return str(chrome_bin)

    return None


def _kill_port_process(port: int) -> None:
    import signal

    try:
        if sys.platform == "darwin" or sys.platform.startswith("linux"):
            out = subprocess.check_output(
                ["lsof", "-ti", f"tcp:{port}"], stderr=subprocess.DEVNULL
            )
            for pid_s in out.decode().strip().split("\n"):
                pid_s = pid_s.strip()
                if pid_s:
                    try:
                        os.kill(int(pid_s), signal.SIGTERM)
                    except Exception:
                        pass
    except Exception:
        pass


def _ensure_executable(path: Path) -> None:
    if sys.platform == "win32":
        return
    try:
        st = path.stat()
        path.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass


# ── WeatherChannel ──────────────────────────────────────────────────────


class WeatherChannel:
    """Headless Chrome CDP screencast → pygame surfaces.

    A background thread owns the WebSocket (connect, send, recv, ack).
    :meth:`get_frame` only reads the latest JPEG from shared state — never
    blocks the UI event loop.
    """

    def __init__(self, width: int, height: int) -> None:
        self._width = max(width, 320)
        self._height = max(height, 240)
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

        chrome_path = _ensure_chromium()
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
        _kill_port_process(CDP_PORT)
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
                    f"--window-size={self._width},{self._height}",
                    WEATHER_URL,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            LOG.warning("Failed to launch Chrome: %s", exc)
            self._cleanup_user_data()
            return False

        ws_url = self._wait_for_page_ws(timeout=12.0)
        if ws_url is None:
            LOG.warning("No CDP page target found for weather channel")
            return False

        self._running = True
        self._available = True
        self._frame_count = 0
        self._start_time = time.time()
        self._error = None
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

    def _wait_for_page_ws(self, timeout: float) -> str | None:
        """Poll CDP /json until a weather.com page target appears."""
        deadline = time.time() + timeout
        last_err: str | None = None
        while time.time() < deadline:
            if self._chrome is not None and self._chrome.poll() is not None:
                LOG.warning("Chrome exited early (code %s)", self._chrome.returncode)
                return None
            try:
                resp = urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=1
                )
                targets = json.loads(resp.read())
            except Exception as exc:
                last_err = str(exc)
                time.sleep(0.25)
                continue

            # Prefer the weather page; fall back to any page target.
            page_urls: list[tuple[str, str]] = []
            for target in targets:
                if target.get("type") != "page":
                    continue
                url = target.get("url") or ""
                ws = target.get("webSocketDebuggerUrl")
                if not ws:
                    continue
                if "weather.com" in url:
                    return ws
                page_urls.append((url, ws))
            if page_urls:
                # Page still navigating to weather.com — wait a bit more
                # unless we're near the deadline.
                if time.time() + 1.5 >= deadline:
                    return page_urls[0][1]
            time.sleep(0.25)

        if last_err:
            LOG.warning("CDP /json poll failed: %s", last_err)
        return None

    def _next_id(self) -> int:
        self._cmd_id += 1
        return self._cmd_id

    def _send(self, ws, method: str, params: dict | None = None) -> None:
        msg: dict = {"id": self._next_id(), "method": method}
        if params:
            msg["params"] = params
        ws.send(json.dumps(msg))

    def _ws_thread(self, ws_url: str) -> None:
        """Create the WebSocket, start screencast, and pump frames."""
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
        # Confirmed safe for full frames on websocket-client 1.9.x.
        ws.settimeout(1.0)

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
            LOG.info("Weather screencast started")
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

        while self._running:
            try:
                data = ws.recv()
            except Exception as exc:
                # Timeout → loop to re-check _running.
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

            if msg.get("method") != "Page.screencastFrame":
                continue

            params = msg.get("params") or {}
            data_b64 = params.get("data") or ""
            session_id = params.get("sessionId", 0)

            # Always ack so Chrome keeps streaming.
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

            with self._lock:
                self._latest_jpeg = jpeg
                self._frame_count += 1
                count = self._frame_count

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
