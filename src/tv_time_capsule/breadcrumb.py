"""Crash / session breadcrumb for Pi debugging (no secrets)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from .config import STATE_DIR

BREADCRUMB_FILE = os.path.join(STATE_DIR, "breadcrumb.json")


def write_breadcrumb(**fields: Any) -> None:
    """Atomically replace breadcrumb.json with the given fields."""
    payload = {k: v for k, v in fields.items() if v is not None}
    payload["ts"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(STATE_DIR, exist_ok=True)
    data = json.dumps(payload, indent=2, default=str)
    fd, tmp = tempfile.mkstemp(prefix="breadcrumb-", suffix=".json", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.write("\n")
        os.replace(tmp, BREADCRUMB_FILE)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def read_breadcrumb() -> dict[str, Any]:
    if not os.path.isfile(BREADCRUMB_FILE):
        return {}
    try:
        with open(BREADCRUMB_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
