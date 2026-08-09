"""METAR helpers — used only when required (obs gap / alert enrichment)."""

from __future__ import annotations

import logging
import re
import urllib.request

LOG = logging.getLogger(__name__)

_UA = "tv-time-capsule/weather"


def fetch_metar_raw(station_id: str, *, timeout: float = 8.0) -> str | None:
    """Fetch latest METAR text for an ICAO station (e.g. KBOS). Optional path."""
    sid = (station_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{4}", sid):
        return None
    url = f"https://aviationweather.gov/api/data/metar?ids={sid}&format=raw"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
        return text or None
    except Exception as exc:
        LOG.info("METAR fetch failed for %s: %s", sid, exc)
        return None
