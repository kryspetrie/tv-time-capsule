"""Structured logging for playback and recovery events."""

from __future__ import annotations

import logging
import sys
from collections import deque
from threading import Lock

LOG = logging.getLogger("tv_time_capsule")

_ring_lock = Lock()
_ring_buffer: deque[str] = deque(maxlen=500)


class RingBufferHandler(logging.Handler):
    """Keep recent log lines for the web admin tail view."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        with _ring_lock:
            _ring_buffer.append(line)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure stderr logging for CLI / systemd journal."""
    root = logging.getLogger()
    fmt = logging.Formatter("%(levelname)s tv-time-capsule: %(message)s")
    if not root.handlers:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(fmt)
        root.addHandler(stderr_handler)
    if not any(isinstance(h, RingBufferHandler) for h in root.handlers):
        ring_handler = RingBufferHandler()
        ring_handler.setFormatter(fmt)
        root.addHandler(ring_handler)
    root.setLevel(level)
    LOG.setLevel(level)


def log_tail(limit: int = 100) -> list[str]:
    with _ring_lock:
        items = list(_ring_buffer)
    if limit <= 0:
        return items
    return items[-limit:]
