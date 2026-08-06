"""Shared Chromium discovery and Chrome DevTools Protocol helpers.

Used by Weather Channel, MyRetroTVs decade screencasts, and YouTube
catalog/playback.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

LOG = logging.getLogger(__name__)

# Playwright-published Chromium builds.
_CHROMIUM_REVISIONS: dict[str, str] = {
    "linux": "1097",
    "mac": "1097",
    "mac_arm": "1097",
}
_CHROMIUM_HOST = "https://playwright.azureedge.net/builds/chromium"


def cache_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "tv-time-capsule" / "chromium"


def chromium_platform_key() -> str | None:
    if sys.platform == "linux":
        return "linux"
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        return "mac_arm" if machine in ("arm64", "aarch64") else "mac"
    return None


def chromium_download_url() -> str | None:
    key = chromium_platform_key()
    if key is None:
        return None
    rev = _CHROMIUM_REVISIONS.get(key)
    if rev is None:
        return None
    return f"{_CHROMIUM_HOST}/{rev}/chromium-{key}.zip"


def find_chrome() -> str | None:
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


def ensure_executable(path: Path) -> None:
    if sys.platform == "win32":
        return
    try:
        st = path.stat()
        path.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass


def ensure_chromium(*, log_label: str = "screencast") -> str | None:
    """Return a Chrome/Chromium binary path, downloading if needed."""
    system = find_chrome()
    if system is not None:
        return system

    cache = cache_dir()
    key = chromium_platform_key()
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
        ensure_executable(chrome_bin)
        return str(chrome_bin)

    url = chromium_download_url()
    if url is None:
        return None

    LOG.info("Downloading Chromium for %s...", log_label)
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
        ensure_executable(chrome_bin)
        LOG.info("Chromium ready at %s", chrome_bin)
        return str(chrome_bin)

    return None


def kill_port_process(port: int) -> None:
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


def wait_for_page_ws(
    port: int,
    *,
    chrome: subprocess.Popen | None = None,
    timeout: float = 12.0,
) -> str | None:
    """Poll CDP /json until a page target with a WebSocket URL appears."""
    deadline = time.time() + timeout
    last_err: str | None = None
    while time.time() < deadline:
        if chrome is not None and chrome.poll() is not None:
            LOG.warning("Chrome exited early (code %s)", chrome.returncode)
            return None
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=1
            )
            targets = json.loads(resp.read())
        except Exception as exc:
            last_err = str(exc)
            time.sleep(0.25)
            continue

        for target in targets:
            if target.get("type") != "page":
                continue
            ws = target.get("webSocketDebuggerUrl")
            if ws:
                return ws
        time.sleep(0.25)

    if last_err:
        LOG.warning("CDP /json poll failed: %s", last_err)
    return None
