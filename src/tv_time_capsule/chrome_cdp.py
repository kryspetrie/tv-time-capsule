"""Shared Chromium discovery and Chrome DevTools Protocol helpers.

Used by Weather Channel, MyRetroTVs decade screencasts, and YouTube
catalog/playback.

Policy: use a **system-installed** Chrome/Chromium only. Install it with
``scripts/install-system-deps.sh`` (or ``install-pi.sh`` / ``install.sh``).
We do not vendor or download browser builds at runtime — that path differed
by CPU (x86 zip vs ARM apt) and was hard to support.

**Single-instance rule:** at most one Chromium process owned by this app.
Call :func:`acquire_chromium` before every launch and :func:`release_chromium`
on teardown. Acquire forcibly displaces any prior owner and reaps orphans.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

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

# CDP ports used by this app (weather / retro / yt-catalog / yt-play).
APP_CDP_PORTS: tuple[int, ...] = (9224, 9225, 9226, 9227)

# Isolated profile dirs — never touch the user's normal Chrome profile.
# Matched via pgrep in kill_all_app_chromium().

_lease_lock = threading.RLock()
_lease = None  # ChromiumLease | None — exclusive app-wide Chrome slot


@dataclass
class ChromiumLease:
    """Exclusive ownership of the app's single Chromium slot."""

    owner: str
    ports: tuple[int, ...]
    proc: subprocess.Popen | None = None
    on_displace: Callable[[], None] | None = field(default=None, repr=False)


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
    """SIGTERM (then SIGKILL) any process listening on *port* (Chrome CDP)."""
    try:
        if not (sys.platform == "darwin" or sys.platform.startswith("linux")):
            return
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"], stderr=subprocess.DEVNULL
        )
        pids: list[int] = []
        for pid_s in out.decode().strip().split("\n"):
            pid_s = pid_s.strip()
            if not pid_s:
                continue
            try:
                pids.append(int(pid_s))
            except ValueError:
                continue
        _signal_pids(pids)
    except Exception:
        pass


def _signal_pids(pids: Sequence[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
    if pids:
        time.sleep(0.15)
    for pid in pids:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _ttc_chromium_pids() -> list[int]:
    """PIDs whose argv includes a ``ttc-*`` user-data-dir (this app only)."""
    pids: list[int] = []
    try:
        # pgrep -f matches full cmdline; restrict to our profile prefixes.
        out = subprocess.check_output(
            [
                "pgrep",
                "-f",
                r"--user-data-dir=\S*ttc-(weather|retro|yt-play|yt-catalog)-",
            ],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return pids
    for line in out.decode().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            pids.append(int(line.split()[0]))
        except ValueError:
            continue
    return pids


def kill_all_app_chromium(*, keep_ports: Sequence[int] | None = None) -> None:
    """Kill every Chromium instance owned by this app (all CDP ports + orphans)."""
    keep = {int(p) for p in (keep_ports or ())}
    for port in APP_CDP_PORTS:
        if port in keep:
            continue
        kill_port_process(port)
    # Orphans may have dropped the listening port but still play audio.
    _signal_pids(_ttc_chromium_pids())


def current_chromium_owner() -> str | None:
    with _lease_lock:
        return _lease.owner if _lease is not None else None


def acquire_chromium(
    owner: str,
    *,
    ports: int | Sequence[int],
    on_displace: Callable[[], None] | None = None,
) -> None:
    """Claim the exclusive Chromium slot for *owner*.

    Any previous owner is soft-stopped via its ``on_displace`` callback (best
    effort), then **all** app Chromium processes are force-reaped so at most
    one new instance can be launched afterward.
    """
    global _lease
    if isinstance(ports, int):
        port_tuple = (int(ports),)
    else:
        port_tuple = tuple(int(p) for p in ports)
    if not port_tuple:
        raise ValueError("acquire_chromium requires at least one CDP port")

    displace_cb: Callable[[], None] | None = None
    prev_owner: str | None = None
    with _lease_lock:
        prev = _lease
        if prev is not None and prev.owner != owner:
            displace_cb = prev.on_displace
            prev_owner = prev.owner
            LOG.info(
                "Chromium lease: displacing %r for %r",
                prev.owner,
                owner,
            )
        _lease = ChromiumLease(
            owner=owner, ports=port_tuple, on_displace=on_displace, proc=None
        )

    if displace_cb is not None:
        try:
            displace_cb()
        except Exception:
            LOG.exception(
                "Chromium displace callback failed for previous owner %r",
                prev_owner,
            )

    # Hard guarantee — even if the soft stop failed or left orphans.
    kill_all_app_chromium()
    # Target port(s) included above; brief settle before the caller binds.
    time.sleep(0.2)


def register_chromium_process(owner: str, proc: subprocess.Popen | None) -> None:
    """Record the live Popen for the current lease (optional bookkeeping)."""
    with _lease_lock:
        if _lease is None or _lease.owner != owner:
            return
        _lease.proc = proc


def release_chromium(owner: str, *, kill: bool = True) -> None:
    """Release the lease if *owner* holds it; optionally kill app Chromiums."""
    global _lease
    should_kill = False
    with _lease_lock:
        if _lease is None:
            should_kill = kill
        elif _lease.owner != owner:
            # Stale release from a displaced owner — do not clear the new lease.
            LOG.debug(
                "Chromium release ignored for %r (held by %r)",
                owner,
                _lease.owner,
            )
            return
        else:
            _lease = None
            should_kill = kill
    if should_kill:
        kill_all_app_chromium()


def shutdown_app_chromium() -> None:
    """App exit: drop the lease and kill every ttc Chromium."""
    global _lease
    with _lease_lock:
        _lease = None
    kill_all_app_chromium()


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
