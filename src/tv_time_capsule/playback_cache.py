"""Background local cache for remote media playback."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from typing import Any

from .config import STATE_DIR
from .mounts import is_mounted, mountpoints_from_config

LOG = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
CHUNK_SIZE = 1024 * 1024  # 1 MiB


class CacheCopyCancelled(Exception):
    """Raised when a cache copy is cancelled before completion."""


def remote_mount_roots(config: dict[str, Any]) -> list[str]:
    """Paths considered remote for caching (longest match first)."""
    roots: set[str] = set()
    for mp in mountpoints_from_config(config.get("mounts")):
        roots.add(os.path.abspath(mp))
    for p in config.get("media_paths") or []:
        expanded = os.path.abspath(os.path.expanduser(str(p)))
        if expanded and is_mounted(expanded):
            roots.add(expanded)
    return sorted(roots, key=len, reverse=True)


def is_remote_path(path: str, config: dict[str, Any]) -> bool:
    """Return True when ``path`` lives on a configured remote mount."""
    if not path:
        return False
    abspath = os.path.abspath(path)
    for root in remote_mount_roots(config):
        if abspath == root or abspath.startswith(root + os.sep):
            return True
    return False


def cache_key(source_path: str) -> str:
    """Stable cache key from path, size, and mtime."""
    st = os.stat(source_path)
    payload = f"{os.path.abspath(source_path)}\0{st.st_size}\0{st.st_mtime_ns}"
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


class PlaybackCache:
    """Copy remote episodes to local disk for smoother playback."""

    def __init__(self, config: dict[str, Any]):
        cache_cfg = config.get("cache") or {}
        self.enabled = bool(cache_cfg.get("enabled", True))
        self.prefetch_next = bool(cache_cfg.get("prefetch_next", True))
        self.cache_before_playing = bool(cache_cfg.get("cache_before_playing", False))
        raw_dir = cache_cfg.get("directory")
        if raw_dir:
            self.cache_dir = os.path.abspath(os.path.expanduser(str(raw_dir)))
        else:
            self.cache_dir = os.path.join(STATE_DIR, "playback-cache")
        try:
            self.max_bytes = int(cache_cfg.get("max_bytes", DEFAULT_MAX_BYTES))
        except (TypeError, ValueError):
            self.max_bytes = DEFAULT_MAX_BYTES
        self._config = config
        self._lock = threading.Lock()
        self._copy_serial = threading.Lock()
        self._active: dict[str, threading.Thread] = {}
        self._completed: dict[str, str] = {}
        self._progress: dict[str, dict[str, int | bool]] = {}
        self._cancel_requested: set[str] = set()

    def should_cache_before_play(self, source_path: str) -> bool:
        """Return True when playback should wait for a full local copy first."""
        if not self.cache_before_playing or not self.enabled or not source_path:
            return False
        if not is_remote_path(source_path, self._config):
            return False
        if not os.path.isfile(source_path):
            return False
        return self.get_cached_path(source_path) is None

    def _meta_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def _data_path(self, key: str, ext: str) -> str:
        return os.path.join(self.cache_dir, f"{key}{ext}")

    def _load_meta(self, key: str) -> dict | None:
        path = self._meta_path(key)
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _validate_meta(self, source_path: str, meta: dict) -> bool:
        if meta.get("source") != os.path.abspath(source_path):
            return False
        try:
            st = os.stat(source_path)
        except OSError:
            return False
        if meta.get("size") != st.st_size or meta.get("mtime_ns") != st.st_mtime_ns:
            return False
        data_path = meta.get("path")
        if not data_path or not os.path.isfile(data_path):
            return False
        try:
            return os.path.getsize(data_path) == st.st_size
        except OSError:
            return False

    def get_cached_path(self, source_path: str) -> str | None:
        """Return a completed cache file path, or None."""
        if not self.enabled or not source_path or not os.path.isfile(source_path):
            return None
        with self._lock:
            cached = self._completed.get(source_path)
            if cached and os.path.isfile(cached):
                return cached
        key = cache_key(source_path)
        meta = self._load_meta(key)
        if meta and self._validate_meta(source_path, meta):
            path = meta["path"]
            with self._lock:
                self._completed[source_path] = path
            self._touch(key)
            return path
        return None

    def resolve_playback_path(self, source_path: str) -> str:
        """Prefer a local cache copy when ready."""
        cached = self.get_cached_path(source_path)
        return cached or source_path

    def is_playing_from_cache(self, playback_path: str, source_path: str) -> bool:
        if not playback_path or not source_path:
            return False
        return os.path.abspath(playback_path) != os.path.abspath(source_path)

    def is_copy_active(self, source_path: str) -> bool:
        with self._lock:
            return source_path in self._active

    def get_copy_progress(self, source_path: str) -> tuple[int, int] | None:
        """Return ``(bytes_done, total_bytes)`` while copying."""
        with self._lock:
            prog = self._progress.get(source_path)
            if not prog:
                return None
            total = int(prog.get("total_bytes") or 0)
            done = int(prog.get("bytes_done") or 0)
            if total <= 0:
                return None
            return done, total

    def cancel_cache(self, source_path: str) -> None:
        """Request cancellation of an in-flight cache copy."""
        with self._lock:
            self._cancel_requested.add(source_path)
            prog = self._progress.get(source_path)
            if prog is not None:
                prog["cancelled"] = True

    def schedule_cache(self, source_path: str) -> None:
        """Start a background copy when ``source_path`` is on a remote mount."""
        if not self.enabled or not source_path:
            return
        if not is_remote_path(source_path, self._config):
            return
        if not os.path.isfile(source_path):
            return
        if self.get_cached_path(source_path):
            return
        with self._lock:
            if source_path in self._active:
                return
            thread = threading.Thread(
                target=self._copy_worker,
                args=(source_path,),
                name=f"playback-cache:{os.path.basename(source_path)}",
                daemon=True,
            )
            self._active[source_path] = thread
            thread.start()

    def cache_ready_for_hot_swap(
        self, source_path: str, current_playback_path: str
    ) -> bool:
        """True when a cache finished while playback still reads from the remote file."""
        if not source_path or self.is_playing_from_cache(
            current_playback_path, source_path
        ):
            return False
        return self.get_cached_path(source_path) is not None

    def _touch(self, key: str) -> None:
        try:
            os.utime(self._meta_path(key), None)
        except OSError:
            pass

    def _evict_if_needed(self, needed_bytes: int) -> None:
        if not os.path.isdir(self.cache_dir):
            return
        entries: list[tuple[float, int, str, str, str]] = []
        for name in os.listdir(self.cache_dir):
            if not name.endswith(".json"):
                continue
            key = name[:-5]
            meta = self._load_meta(key)
            if not meta or not meta.get("path"):
                continue
            data_path = meta["path"]
            try:
                size = os.path.getsize(data_path)
                atime = os.path.getatime(self._meta_path(key))
            except OSError:
                continue
            entries.append((atime, size, key, data_path, self._meta_path(key)))
        total = sum(entry[1] for entry in entries)
        entries.sort(key=lambda entry: entry[0])
        while total + needed_bytes > self.max_bytes and entries:
            _, size, _key, data_path, meta_path = entries.pop(0)
            for path in (data_path, meta_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            part = data_path + ".part"
            try:
                os.unlink(part)
            except OSError:
                pass
            total -= size
            with self._lock:
                for src, cached in list(self._completed.items()):
                    if cached == data_path:
                        del self._completed[src]

    def _progress_state(self, source_path: str) -> dict[str, int | bool]:
        with self._lock:
            prog = self._progress.get(source_path)
            if prog is None:
                prog = {
                    "bytes_done": 0,
                    "total_bytes": 0,
                    "cancelled": source_path in self._cancel_requested,
                }
                self._progress[source_path] = prog
            return prog

    def _clear_progress(self, source_path: str) -> None:
        with self._lock:
            self._progress.pop(source_path, None)
            self._cancel_requested.discard(source_path)

    def _run_copy(self, source_path: str) -> str:
        part = ""
        prog = self._progress_state(source_path)
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            key = cache_key(source_path)
            ext = os.path.splitext(source_path)[1] or ".bin"
            dest = self._data_path(key, ext)
            part = dest + ".part"
            st = os.stat(source_path)
            prog["total_bytes"] = st.st_size
            prog["bytes_done"] = 0
            self._evict_if_needed(st.st_size)
            with open(source_path, "rb") as src, open(part, "wb") as dst:
                while True:
                    if prog.get("cancelled"):
                        raise CacheCopyCancelled()
                    chunk = src.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
                    prog["bytes_done"] = int(prog.get("bytes_done") or 0) + len(chunk)
            os.replace(part, dest)
            meta = {
                "source": os.path.abspath(source_path),
                "path": dest,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
            }
            with open(self._meta_path(key), "w", encoding="utf-8") as f:
                json.dump(meta, f)
            with self._lock:
                self._completed[source_path] = dest
            LOG.info("cached remote episode %s -> %s", source_path, dest)
            return dest
        except CacheCopyCancelled:
            LOG.info("playback cache cancelled for %s", source_path)
            if part:
                try:
                    os.unlink(part)
                except OSError:
                    pass
            raise
        except Exception as exc:
            LOG.warning("playback cache failed for %s: %s", source_path, exc)
            if part:
                try:
                    os.unlink(part)
                except OSError:
                    pass
            raise
        finally:
            self._clear_progress(source_path)

    def _copy_worker(self, source_path: str) -> None:
        with self._copy_serial:
            try:
                self._run_copy(source_path)
            except (CacheCopyCancelled, Exception):
                pass
            finally:
                with self._lock:
                    self._active.pop(source_path, None)

    def shutdown(self) -> None:
        """Best-effort wait for in-flight copies on exit."""
        with self._lock:
            threads = list(self._active.values())
        for thread in threads:
            thread.join(timeout=0.5)
