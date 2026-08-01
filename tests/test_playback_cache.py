"""Tests for remote playback background cache."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tv_time_capsule.playback_cache import (
    CHUNK_SIZE,
    PlaybackCache,
    cache_key,
    is_remote_path,
)


class RemotePathTests(unittest.TestCase):
    def test_remote_under_configured_mount(self):
        config = {
            "mounts": [{"mountpoint": "/mnt/nas/shows"}],
            "media_paths": ["/media/usb"],
        }
        self.assertTrue(
            is_remote_path("/mnt/nas/shows/Bluey/S01/E01.mp4", config)
        )
        self.assertFalse(
            is_remote_path("/media/usb/Bluey/S01/E01.mp4", config)
        )

    def test_remote_root_file(self):
        config = {"mounts": [{"mountpoint": "/mnt/nas"}], "media_paths": []}
        self.assertTrue(is_remote_path("/mnt/nas/file.mp4", config))


class PlaybackCacheTests(unittest.TestCase):
    def test_resolve_uses_source_when_cache_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "remote", "ep.mp4")
            os.makedirs(os.path.dirname(source), exist_ok=True)
            with open(source, "wb") as f:
                f.write(b"remote video bytes")
            config = {
                "mounts": [{"mountpoint": os.path.join(tmp, "remote")}],
                "media_paths": [],
                "cache": {
                    "enabled": True,
                    "directory": os.path.join(tmp, "cache"),
                    "max_bytes": 1024 * 1024,
                },
            }
            cache = PlaybackCache(config)
            self.assertEqual(cache.resolve_playback_path(source), source)

    def test_background_copy_and_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote_root = os.path.join(tmp, "remote")
            source = os.path.join(remote_root, "ep.mp4")
            os.makedirs(remote_root, exist_ok=True)
            payload = b"x" * 4096
            with open(source, "wb") as f:
                f.write(payload)
            cache_dir = os.path.join(tmp, "cache")
            config = {
                "mounts": [{"mountpoint": remote_root}],
                "media_paths": [],
                "cache": {
                    "enabled": True,
                    "directory": cache_dir,
                    "max_bytes": 1024 * 1024,
                },
            }
            cache = PlaybackCache(config)
            cache.schedule_cache(source)
            deadline = time.time() + 5.0
            resolved = source
            while time.time() < deadline:
                resolved = cache.resolve_playback_path(source)
                if resolved != source:
                    break
                time.sleep(0.05)
            self.assertNotEqual(resolved, source)
            self.assertTrue(os.path.isfile(resolved))
            with open(resolved, "rb") as f:
                self.assertEqual(f.read(), payload)

    def test_cache_key_changes_when_file_changes(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"a")
            path = f.name
        try:
            key_a = cache_key(path)
            with open(path, "wb") as out:
                out.write(b"ab")
            key_b = cache_key(path)
            self.assertNotEqual(key_a, key_b)
        finally:
            os.unlink(path)

    def test_eviction_enforces_max_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote_root = os.path.join(tmp, "remote")
            os.makedirs(remote_root, exist_ok=True)
            cache_dir = os.path.join(tmp, "cache")
            config = {
                "mounts": [{"mountpoint": remote_root}],
                "media_paths": [],
                "cache": {
                    "enabled": True,
                    "directory": cache_dir,
                    "max_bytes": 5000,
                },
            }
            cache = PlaybackCache(config)
            paths = []
            for i in range(3):
                path = os.path.join(remote_root, f"ep{i}.mp4")
                with open(path, "wb") as f:
                    f.write(bytes([i]) * 3000)
                paths.append(path)
                cache.schedule_cache(path)
            deadline = time.time() + 10.0
            while time.time() < deadline:
                with cache._lock:
                    if not cache._active:
                        break
                time.sleep(0.05)
            cached_files = [
                name
                for name in os.listdir(cache_dir)
                if name.endswith(".mp4") and not name.endswith(".part")
            ]
            total = sum(
                os.path.getsize(os.path.join(cache_dir, name))
                for name in cached_files
            )
            self.assertLessEqual(total, 5000)
            self.assertGreaterEqual(len(cached_files), 1)

    def test_disabled_cache_skips_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote_root = os.path.join(tmp, "remote")
            source = os.path.join(remote_root, "ep.mp4")
            os.makedirs(remote_root, exist_ok=True)
            with open(source, "wb") as f:
                f.write(b"data")
            config = {
                "mounts": [{"mountpoint": remote_root}],
                "media_paths": [],
                "cache": {"enabled": False, "directory": os.path.join(tmp, "cache")},
            }
            cache = PlaybackCache(config)
            cache.schedule_cache(source)
            with cache._lock:
                self.assertEqual(len(cache._active), 0)

    def test_should_cache_before_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote_root = os.path.join(tmp, "remote")
            source = os.path.join(remote_root, "ep.mp4")
            os.makedirs(remote_root, exist_ok=True)
            with open(source, "wb") as f:
                f.write(b"data")
            config = {
                "mounts": [{"mountpoint": remote_root}],
                "media_paths": [],
                "cache": {
                    "enabled": True,
                    "cache_before_playing": True,
                    "directory": os.path.join(tmp, "cache"),
                },
            }
            cache = PlaybackCache(config)
            self.assertTrue(cache.should_cache_before_play(source))
            self.assertFalse(
                cache.should_cache_before_play(os.path.join(tmp, "local.mp4"))
            )

    def test_copy_progress_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote_root = os.path.join(tmp, "remote")
            source = os.path.join(remote_root, "ep.mp4")
            os.makedirs(remote_root, exist_ok=True)
            payload = b"x" * (CHUNK_SIZE * 4)
            with open(source, "wb") as f:
                f.write(payload)
            config = {
                "mounts": [{"mountpoint": remote_root}],
                "media_paths": [],
                "cache": {
                    "enabled": True,
                    "directory": os.path.join(tmp, "cache"),
                    "max_bytes": 1024 * 1024,
                },
            }
            cache = PlaybackCache(config)
            saw_partial = False
            with patch("tv_time_capsule.playback_cache.CHUNK_SIZE", 512):
                worker = threading.Thread(target=cache._run_copy, args=(source,))
                worker.start()
                while worker.is_alive():
                    prog = cache.get_copy_progress(source)
                    if prog and prog[0] < prog[1]:
                        saw_partial = True
                    time.sleep(0.001)
                worker.join()
            self.assertTrue(cache.get_cached_path(source))
            self.assertTrue(saw_partial)

    def test_cancel_cache_aborts_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote_root = os.path.join(tmp, "remote")
            source = os.path.join(remote_root, "ep.mp4")
            os.makedirs(remote_root, exist_ok=True)
            with open(source, "wb") as f:
                f.write(b"x" * (CHUNK_SIZE * 8))
            config = {
                "mounts": [{"mountpoint": remote_root}],
                "media_paths": [],
                "cache": {
                    "enabled": True,
                    "directory": os.path.join(tmp, "cache"),
                    "max_bytes": 1024 * 1024,
                },
            }
            cache = PlaybackCache(config)
            cache.schedule_cache(source)
            cache.cancel_cache(source)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                with cache._lock:
                    if not cache._active:
                        break
                time.sleep(0.05)
            self.assertIsNone(cache.get_cached_path(source))


if __name__ == "__main__":
    unittest.main()
