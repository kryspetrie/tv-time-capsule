"""Disk cache for YouTube pillarbox crop decisions (per video id).

Stored under ``~/.local/share/tv-time-capsule/youtube/crops/`` with a 30-day
TTL.

Payload (v9)::

    {
      "youtube_id": "...",
      "version": 9,
      "crop_norm": [x, y, w, h] | null,   # fractions of width/height (0..1)
      "apply": true | false,              # user/auto preference to use crop
      "fetched_at": ...
    }

``crop_norm`` is viewport-independent; load denormalizes to the requested
width/height. Older cache versions are treated as misses and re-probed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import STATE_DIR
from .youtube_crop import denormalize_crop_rect, normalize_crop_rect

LOG = logging.getLogger(__name__)

CROP_CACHE_TTL_S = 30 * 24 * 60 * 60
# Bump when detection semantics change so stale decisions are re-probed.
CROP_CACHE_VERSION = 9
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class PillarboxCropEntry:
    """Cached crop geometry plus whether it should be applied."""

    crop: tuple[int, int, int, int] | None
    apply: bool

    @property
    def applied_crop(self) -> tuple[int, int, int, int] | None:
        return self.crop if self.apply and self.crop is not None else None


def crop_cache_dir() -> Path:
    return Path(STATE_DIR) / "youtube" / "crops"


def _normalize_id(youtube_id: str | None) -> str | None:
    if not youtube_id:
        return None
    text = str(youtube_id).strip()
    if text.startswith("youtube:"):
        text = text[8:].strip()
    if _YT_ID_RE.match(text):
        return text
    return None


def _cache_path(youtube_id: str, *, cache_dir: Path) -> Path:
    return cache_dir / f"{youtube_id}.json"


def _read_payload(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _parse_crop_norm(raw: Any) -> tuple[tuple[float, float, float, float] | None, bool]:
    """Return ``(crop_norm, True)`` or ``(None, False)`` if the payload is invalid.

    ``crop_norm`` itself may be ``None`` when the video was decided full-bleed.
    """
    if raw is None:
        return None, True
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None, False
    try:
        x, y, w, h = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None, False
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        return None, False
    return (x, y, w, h), True


def load_pillarbox_crop(
    youtube_id: str | None,
    *,
    width: int,
    height: int,
    cache_dir: Path | None = None,
    now: float | None = None,
    ttl_s: float = CROP_CACHE_TTL_S,
) -> tuple[tuple[int, int, int, int] | None, bool]:
    """Load the *applied* crop for playback.

    Returns ``(crop, True)`` on hit (``crop`` may be ``None`` when zoom is off
    or no pillarbox was detected), or ``(None, False)`` on miss.
    """
    entry = load_pillarbox_crop_entry(
        youtube_id,
        width=width,
        height=height,
        cache_dir=cache_dir,
        now=now,
        ttl_s=ttl_s,
    )
    if entry is None:
        return None, False
    return entry.applied_crop, True


def load_pillarbox_crop_entry(
    youtube_id: str | None,
    *,
    width: int,
    height: int,
    cache_dir: Path | None = None,
    now: float | None = None,
    ttl_s: float = CROP_CACHE_TTL_S,
) -> PillarboxCropEntry | None:
    """Load full crop cache entry, or ``None`` on miss / stale / mismatch."""
    yid = _normalize_id(youtube_id)
    if not yid:
        return None
    cdir = cache_dir or crop_cache_dir()
    path = _cache_path(yid, cache_dir=cdir)
    payload = _read_payload(path)
    if payload is None:
        return None

    try:
        fetched = float(payload.get("fetched_at") or 0)
    except (TypeError, ValueError):
        fetched = 0.0
    stamp = time.time() if now is None else float(now)
    if fetched <= 0 or (stamp - fetched) >= ttl_s:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    try:
        version = int(payload.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != CROP_CACHE_VERSION:
        return None

    if "crop_norm" not in payload:
        return None
    crop_norm, ok = _parse_crop_norm(payload.get("crop_norm"))
    if not ok:
        return None
    crop = denormalize_crop_rect(crop_norm, int(width), int(height))
    apply = bool(payload.get("apply", crop is not None))
    return PillarboxCropEntry(crop=crop, apply=apply)


def save_pillarbox_crop(
    youtube_id: str | None,
    crop: tuple[int, int, int, int] | None,
    *,
    width: int,
    height: int,
    apply: bool | None = None,
    cache_dir: Path | None = None,
    now: float | None = None,
    ttl_s: float = CROP_CACHE_TTL_S,
) -> None:
    """Persist a crop decision.

    ``width``/``height`` convert pixel ``crop`` to normalized fractions for
    storage. ``apply`` defaults to True when ``crop`` is set, False when ``crop``
    is ``None``. Pass ``apply`` explicitly when the user toggles zoom off while
    keeping detected geometry for later re-enable.
    """
    yid = _normalize_id(youtube_id)
    if not yid:
        return
    cdir = cache_dir or crop_cache_dir()
    stamp = time.time() if now is None else float(now)
    if apply is None:
        apply = crop is not None
    crop_norm = normalize_crop_rect(crop, int(width), int(height))
    payload = {
        "youtube_id": yid,
        "version": CROP_CACHE_VERSION,
        "crop_norm": list(crop_norm) if crop_norm is not None else None,
        "apply": bool(apply),
        "fetched_at": stamp,
    }
    try:
        _write_payload(_cache_path(yid, cache_dir=cdir), payload)
    except OSError as exc:
        LOG.debug("YouTube crop cache write failed id=%s: %s", yid, exc)
        return
    prune_pillarbox_crop_cache(cache_dir=cdir, now=stamp, ttl_s=ttl_s)


def prune_pillarbox_crop_cache(
    *,
    cache_dir: Path | None = None,
    now: float | None = None,
    ttl_s: float = CROP_CACHE_TTL_S,
) -> int:
    """Delete expired crop cache files. Returns number removed."""
    cdir = cache_dir or crop_cache_dir()
    if not cdir.is_dir():
        return 0
    stamp = time.time() if now is None else float(now)
    removed = 0
    try:
        entries = list(cdir.glob("*.json"))
    except OSError:
        return 0
    for path in entries:
        payload = _read_payload(path)
        stale = True
        if payload is not None:
            try:
                fetched = float(payload.get("fetched_at") or 0)
            except (TypeError, ValueError):
                fetched = 0.0
            stale = fetched <= 0 or (stamp - fetched) >= ttl_s
        if stale:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass
    return removed
