"""Shared Chromium discovery and Chrome DevTools Protocol helpers.

Used by Weather Channel, MyRetroTVs decade screencasts, and YouTube
catalog/playback.

Policy: use a **system-installed** Chrome/Chromium only. Install it with
``scripts/install-system-deps.sh`` (or ``install-pi.sh`` / ``install.sh``).
We do not vendor or download browser builds at runtime — that path differed
by CPU (x86 zip vs ARM apt) and was hard to support.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

LOG = logging.getLogger(__name__)

# Prefer Chromium (matches apt/brew package name); Chrome is an acceptable stand-in.
_CANDIDATE_NAMES = (
    "chromium",
    "chromium-browser",
    "google-chrome-stable",
    "google-chrome",
)

_CANDIDATE_PATHS = (
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/google-chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def find_chrome() -> str | None:
    """Return path to a system Chrome/Chromium binary, or None."""
    for name in _CANDIDATE_NAMES:
        path = shutil.which(name)
        if path:
            return path
    for path in _CANDIDATE_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def ensure_chromium(*, log_label: str = "screencast") -> str | None:
    """Return a system Chrome/Chromium path, or None with an install hint."""
    system = find_chrome()
    if system is not None:
        return system

    if sys.platform == "darwin":
        hint = (
            "brew install --cask chromium   "
            "(or re-run ./scripts/install-system-deps.sh)"
        )
    else:
        hint = (
            "sudo apt install -y chromium   "
            "(or re-run ./scripts/install-system-deps.sh / ./install-pi.sh)"
        )
    LOG.warning(
        "No system Chromium/Chrome found for %s. Install with: %s",
        log_label,
        hint,
    )
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
