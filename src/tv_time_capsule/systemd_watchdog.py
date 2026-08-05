"""systemd watchdog integration for TV Time Capsule.

This module provides optional integration with systemd's watchdog feature.
When enabled, the application will periodically notify systemd that it's
still alive. If notifications stop (app hangs), systemd will automatically
restart the service.

Usage
-----
In cli.py, after creating the app:

    from tv_time_capsule.systemd_watchdog import start_watchdog_thread
    start_watchdog_thread()

Requirements
------------
- sdnotify package: pip install sdnotify
- WatchdogSec set in tv-time-capsule.service

Fallback
--------
If sdnotify is not available or not running under systemd,
the watchdog thread will log a warning and skip initialization.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_watchdog_thread: threading.Thread | None = None
_watchdog_stop = threading.Event()


def _notify_watchdog(interval_sec: float) -> None:
    """Notify systemd watchdog at regular intervals.

    Parameters
    ----------
    interval_sec : float
        How often to notify (should be < WatchdogSec / 2)
    """
    try:
        from sdnotify import SystemdNotifier

        notifier = SystemdNotifier()

        # Send initial READY notification
        notifier.notify("READY=1")
        logger.info("systemd watchdog initialized (interval: %.1fs)", interval_sec)

        while not _watchdog_stop.is_set():
            # Send WATCHDOG=1 to reset the timer
            notifier.notify("WATCHDOG=1")
            _watchdog_stop.wait(timeout=interval_sec)

        # Send stopping notification
        notifier.notify("STOPPING=1")
        logger.info("systemd watchdog stopped")

    except ImportError:
        logger.warning(
            "sdnotify not installed - watchdog disabled. "
            "Install with: pip install sdnotify"
        )
    except Exception as e:
        logger.warning("systemd watchdog error (running outside systemd?): %s", e)


def start_watchdog_thread(interval_sec: float = 10.0) -> None:
    """Start the systemd watchdog notification thread.

    Parameters
    ----------
    interval_sec : float
        Notification interval in seconds. Should be less than half
        of the WatchdogSec value in the systemd service file.
        Default: 10 seconds (for WatchdogSec=20)
    """
    global _watchdog_thread

    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        logger.debug("systemd watchdog thread already running")
        return

    _watchdog_stop.clear()
    _watchdog_thread = threading.Thread(
        target=_notify_watchdog,
        args=(interval_sec,),
        name="systemd-watchdog",
        daemon=True,
    )
    _watchdog_thread.start()
    logger.debug("systemd watchdog thread started")


def stop_watchdog_thread() -> None:
    """Stop the systemd watchdog notification thread."""
    global _watchdog_thread

    if _watchdog_thread is None:
        return

    _watchdog_stop.set()
    _watchdog_thread.join(timeout=5.0)
    _watchdog_thread = None
    logger.debug("systemd watchdog thread stopped")


def notify_status(message: str) -> None:
    """Send a status message to systemd journal.

    Parameters
    ----------
    message : str
        Status message to log
    """
    try:
        from sdnotify import SystemdNotifier

        notifier = SystemdNotifier()
        notifier.notify(f"STATUS={message}")
        logger.debug("systemd status: %s", message)
    except Exception:
        pass  # Silently fail if not running under systemd
