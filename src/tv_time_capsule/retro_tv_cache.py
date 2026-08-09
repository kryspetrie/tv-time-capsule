"""Temporary 2-slot YouTube cache for MyRetroTVs decade streams.

Distinct from :mod:`youtube_offline_cache` (forever show tree). Clips live under
a session directory and are wiped when leaving Decades. At most two completed
(or in-flight) files are retained.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import STATE_DIR
from .youtube_offline_cache import (
    DEFAULT_FORMAT,
    PART_SUFFIX,
    _PLAYER_CLIENT_STRATEGIES,
    _detect_js_runtimes,
    require_yt_dlp,
)

LOG = logging.getLogger(__name__)

MAX_SLOTS = 2


def default_retro_tv_cache_dir() -> Path:
    return Path(STATE_DIR) / "retro-tv-cache"


def resolve_retro_tv_cache_dir(config: dict[str, Any] | None) -> Path:
    retro = (config or {}).get("retro_tv") or {}
    raw = retro.get("cache_directory") if isinstance(retro, dict) else None
    if raw:
        path = Path(os.path.expanduser(str(raw))).resolve()
        return path
    return default_retro_tv_cache_dir()


class RetroTvTempCache:
    """Rolling pair of yt-dlp files for one Decades session.

    Adapter for :class:`tv_time_capsule.playback.ports.RollingClipCache`.
    Used when ``retro_tv.playback_mode`` is ``cached`` (the default).
    """

    def __init__(
        self,
        config: dict[str, Any] | None,
        *,
        decade: str,
    ) -> None:
        self.decade = str(decade or "xx")
        root = resolve_retro_tv_cache_dir(config)
        self.cache_dir = root / self.decade
        retro = (config or {}).get("retro_tv") or {}
        fmt = None
        if isinstance(retro, dict):
            fmt = retro.get("cache_format")
        yt = (config or {}).get("youtube") or {}
        yt_cache = yt.get("cache") if isinstance(yt, dict) else None
        if not fmt and isinstance(yt_cache, dict):
            fmt = yt_cache.get("format")
        self.format = str(fmt or DEFAULT_FORMAT)
        self._lock = threading.Lock()
        self._download_lock = threading.Lock()
        self._slots: OrderedDict[str, Path] = OrderedDict()
        self._cancel = threading.Event()
        self._inflight: str | None = None
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, youtube_id: str | None) -> Path | None:
        yid = str(youtube_id or "").strip()
        if not yid:
            return None
        with self._lock:
            path = self._slots.get(yid)
        if path is not None and path.is_file() and path.stat().st_size > 0:
            return path
        candidate = self.cache_dir / f"{yid}.mp4"
        if candidate.is_file() and candidate.stat().st_size > 0:
            with self._lock:
                self._slots[yid] = candidate
                self._slots.move_to_end(yid)
            return candidate
        return None

    def is_cached(self, youtube_id: str | None) -> bool:
        return self.path_for(youtube_id) is not None

    def cancel(self) -> None:
        self._cancel.set()

    def download(
        self,
        youtube_id: str,
        *,
        keep: Iterable[str] | None = None,
    ) -> Path | None:
        """Download *youtube_id* into a slot; evict oldest if over capacity.

        *keep* lists ids that must not be deleted when trimming (e.g. the clip
        currently playing). Downloads are serialized so prefetch + advance
        cannot race yt-dlp partial files.
        """
        yid = str(youtube_id or "").strip()
        if not yid:
            return None
        preserve = {str(x).strip() for x in (keep or ()) if str(x).strip()}
        preserve.add(yid)

        # Fast path without taking the download lock.
        existing = self.path_for(yid)
        if existing is not None:
            with self._lock:
                if yid in self._slots:
                    self._slots.move_to_end(yid)
            return existing
        if self._cancel.is_set():
            return None

        with self._download_lock:
            # Another thread may have finished while we waited.
            existing = self.path_for(yid)
            if existing is not None:
                with self._lock:
                    if yid in self._slots:
                        self._slots.move_to_end(yid)
                return existing
            if self._cancel.is_set():
                return None
            return self._download_unlocked(yid, preserve=preserve)

    def _download_unlocked(
        self, yid: str, *, preserve: set[str]
    ) -> Path | None:
        yt_dlp = require_yt_dlp()
        dest = self.cache_dir / f"{yid}.mp4"
        self._cleanup_partials(dest)
        part_tmpl = str(dest) + PART_SUFFIX + ".%(ext)s"
        url = f"https://www.youtube.com/watch?v={yid}"
        js_runtimes = _detect_js_runtimes()
        last_error = ""
        download_ok = False

        with self._lock:
            self._inflight = yid
        try:
            for clients in _PLAYER_CLIENT_STRATEGIES:
                if self._cancel.is_set():
                    break
                self._cleanup_partials(dest)
                ydl_opts: dict[str, Any] = {
                    "format": self.format,
                    "outtmpl": part_tmpl,
                    "merge_output_format": "mp4",
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                    "retries": 3,
                    "fragment_retries": 3,
                    "concurrent_fragment_downloads": 1,
                    "extractor_args": {
                        "youtube": {"player_client": clients.split(",")}
                    },
                }
                if js_runtimes:
                    ydl_opts["js_runtimes"] = js_runtimes

                def _hook(d: dict[str, Any]) -> None:
                    if self._cancel.is_set():
                        raise yt_dlp.utils.DownloadCancelled("retro tv cancelled")

                ydl_opts["progress_hooks"] = [_hook]
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    download_ok = True
                    break
                except Exception as exc:
                    if isinstance(exc, yt_dlp.utils.DownloadCancelled):
                        last_error = str(exc)
                        break
                    last_error = str(exc)
                    LOG.info(
                        "Retro TV cache client=%s failed id=%s: %s",
                        clients,
                        yid,
                        exc,
                    )
                    continue

            if not download_ok:
                self._cleanup_partials(dest)
                if last_error:
                    LOG.warning(
                        "Retro TV cache download failed id=%s: %s", yid, last_error
                    )
                return None

            produced = self._find_produced_file(dest)
            if produced is None:
                LOG.warning("Retro TV cache missing file for id=%s", yid)
                self._cleanup_partials(dest)
                return None
            try:
                if dest.exists() and dest.resolve() != produced.resolve():
                    dest.unlink()
                if produced.resolve() != dest.resolve():
                    produced.replace(dest)
            except OSError as exc:
                LOG.warning("Retro TV cache rename failed id=%s: %s", yid, exc)
                self._cleanup_partials(dest)
                return None
            if not dest.is_file() or dest.stat().st_size <= 0:
                self._cleanup_partials(dest)
                return None
            with self._lock:
                self._slots[yid] = dest
                self._slots.move_to_end(yid)
                # Preserve the new clip *and* any ids the caller still needs
                # (currently playing). Never keep={yid} alone — that deleted
                # the on-screen file when prefetch finished.
                self._evict_locked(keep=preserve)
            LOG.info("Retro TV cached id=%s path=%s", yid, dest)
            return dest
        finally:
            with self._lock:
                if self._inflight == yid:
                    self._inflight = None

    def retain(self, keep_ids: set[str] | list[str]) -> None:
        """Delete slots not in *keep_ids* (max still enforced)."""
        keep = {str(x).strip() for x in keep_ids if str(x).strip()}
        with self._lock:
            self._evict_locked(keep=keep, force_only_keep=True)

    def wipe(self) -> None:
        """Cancel downloads and remove this decade's temp directory."""
        self._cancel.set()
        with self._lock:
            self._slots.clear()
            self._inflight = None
        try:
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir, ignore_errors=True)
        except Exception:
            LOG.exception("Retro TV cache wipe failed dir=%s", self.cache_dir)

    def _evict_locked(
        self,
        *,
        keep: set[str],
        force_only_keep: bool = False,
    ) -> None:
        if force_only_keep:
            for yid in list(self._slots.keys()):
                if yid not in keep:
                    self._delete_slot_locked(yid)
        while len(self._slots) > MAX_SLOTS:
            victim = None
            for yid in self._slots:
                if yid not in keep:
                    victim = yid
                    break
            if victim is None:
                # Everything is protected; drop the oldest anyway for capacity.
                victim = next(iter(self._slots))
            self._delete_slot_locked(victim)

    def _delete_slot_locked(self, yid: str) -> None:
        path = self._slots.pop(yid, None)
        if path is None:
            return
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
        self._cleanup_partials(path)

    @staticmethod
    def _cleanup_partials(dest: Path) -> None:
        parent = dest.parent
        if not parent.is_dir():
            return
        prefix = dest.name + PART_SUFFIX
        try:
            for child in parent.iterdir():
                if not child.is_file():
                    continue
                if child.name == dest.name or child.name.startswith(prefix):
                    if child.name == dest.name:
                        continue
                    try:
                        child.unlink()
                    except OSError:
                        pass
        except OSError:
            return

    @staticmethod
    def _find_produced_file(dest: Path) -> Path | None:
        if dest.is_file():
            return dest
        parent = dest.parent
        if not parent.is_dir():
            return None
        prefix = dest.name + PART_SUFFIX
        candidates: list[Path] = []
        try:
            for path in parent.iterdir():
                if not path.is_file():
                    continue
                if path.name.startswith(prefix):
                    candidates.append(path)
        except OSError:
            return None
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
        return candidates[0]
