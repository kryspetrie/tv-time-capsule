"""Tests for Decades temp cache and embed URL parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tv_time_capsule.config import parse_config
from tv_time_capsule.retro_tv_cache import MAX_SLOTS, RetroTvTempCache
from tv_time_capsule.retro_tv_channel import youtube_id_from_embed_url


class YoutubeEmbedIdTests(unittest.TestCase):
    def test_embed_path(self):
        self.assertEqual(
            youtube_id_from_embed_url("https://www.youtube.com/embed/abcdefghijk"),
            "abcdefghijk",
        )

    def test_nocookie_embed(self):
        self.assertEqual(
            youtube_id_from_embed_url(
                "https://www.youtube-nocookie.com/embed/AbCdEfGhIjK?autoplay=1"
            ),
            "AbCdEfGhIjK",
        )

    def test_watch_query(self):
        self.assertEqual(
            youtube_id_from_embed_url("https://www.youtube.com/watch?v=ABCDEFGHIJK&t=1"),
            "ABCDEFGHIJK",
        )

    def test_shorts_and_youtu_be(self):
        self.assertEqual(
            youtube_id_from_embed_url("https://www.youtube.com/shorts/ABCDEFGHIJK"),
            "ABCDEFGHIJK",
        )
        self.assertEqual(
            youtube_id_from_embed_url("https://youtu.be/ABCDEFGHIJK?t=9"),
            "ABCDEFGHIJK",
        )

    def test_invalid(self):
        self.assertIsNone(youtube_id_from_embed_url("https://example.com/"))
        self.assertIsNone(youtube_id_from_embed_url(None))


class RetroTvConfigTests(unittest.TestCase):
    def test_default_live(self):
        cfg = parse_config({})
        self.assertEqual(cfg["retro_tv"]["playback_mode"], "live")
        self.assertIsNone(cfg["retro_tv"]["cache_directory"])

    def test_cached_mode(self):
        cfg = parse_config(
            {"retro_tv": {"playback_mode": "cached", "cache_directory": "/tmp/rtv"}}
        )
        self.assertEqual(cfg["retro_tv"]["playback_mode"], "cached")
        self.assertEqual(cfg["retro_tv"]["cache_directory"], "/tmp/rtv")

    def test_invalid_mode_falls_back(self):
        cfg = parse_config({"retro_tv": {"playback_mode": "weird"}})
        self.assertEqual(cfg["retro_tv"]["playback_mode"], "live")


class RetroTvTempCacheTests(unittest.TestCase):
    def test_retain_evicts_to_two_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"retro_tv": {"cache_directory": tmp}}
            cache = RetroTvTempCache(cfg, decade="90")
            paths = []
            for i, yid in enumerate(("aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc")):
                p = cache.cache_dir / f"{yid}.mp4"
                p.write_bytes(b"x" * (10 + i))
                with cache._lock:
                    cache._slots[yid] = p
                    cache._slots.move_to_end(yid)
                paths.append(p)
            cache.retain({"bbbbbbbbbbb", "ccccccccccc"})
            self.assertFalse(paths[0].exists())
            self.assertTrue(paths[1].exists())
            self.assertTrue(paths[2].exists())
            self.assertEqual(len(cache._slots), 2)
            self.assertEqual(MAX_SLOTS, 2)

    def test_wipe_removes_decade_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"retro_tv": {"cache_directory": tmp}}
            cache = RetroTvTempCache(cfg, decade="80")
            f = cache.cache_dir / "ddddddddddd.mp4"
            f.write_bytes(b"data")
            cache.wipe()
            self.assertFalse(cache.cache_dir.exists())

    def test_download_registers_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"retro_tv": {"cache_directory": tmp}}
            cache = RetroTvTempCache(cfg, decade="70")
            dest = cache.cache_dir / "eeeeeeeeeee.mp4"

            class FakeYDL:
                def __init__(self, opts):
                    self.opts = opts

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def download(self, urls):
                    part = Path(str(dest) + ".part.mp4")
                    part.write_bytes(b"video")

            fake_mod = MagicMock()
            fake_mod.YoutubeDL = FakeYDL
            fake_mod.utils.DownloadCancelled = type("DownloadCancelled", (Exception,), {})

            with patch(
                "tv_time_capsule.retro_tv_cache.require_yt_dlp", return_value=fake_mod
            ):
                with patch(
                    "tv_time_capsule.retro_tv_cache._detect_js_runtimes", return_value={}
                ):
                    with patch(
                        "tv_time_capsule.retro_tv_cache._PLAYER_CLIENT_STRATEGIES",
                        ("web",),
                    ):
                        path = cache.download("eeeeeeeeeee")
            self.assertIsNotNone(path)
            self.assertTrue(path.is_file())
            self.assertEqual(cache.path_for("eeeeeeeeeee"), path)

    def test_download_keeps_playing_slot(self):
        """Prefetch must not delete the currently playing clip when it finishes."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"retro_tv": {"cache_directory": tmp}}
            cache = RetroTvTempCache(cfg, decade="90")
            playing = "aaaaaaaaaaa"
            nxt = "bbbbbbbbbbb"
            play_path = cache.cache_dir / f"{playing}.mp4"
            play_path.write_bytes(b"playing")
            with cache._lock:
                cache._slots[playing] = play_path

            dest = cache.cache_dir / f"{nxt}.mp4"

            class FakeYDL:
                def __init__(self, opts):
                    self.opts = opts

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def download(self, urls):
                    part = Path(str(dest) + ".part.mp4")
                    part.write_bytes(b"next")

            fake_mod = MagicMock()
            fake_mod.YoutubeDL = FakeYDL
            fake_mod.utils.DownloadCancelled = type("DownloadCancelled", (Exception,), {})

            with patch(
                "tv_time_capsule.retro_tv_cache.require_yt_dlp", return_value=fake_mod
            ):
                with patch(
                    "tv_time_capsule.retro_tv_cache._detect_js_runtimes", return_value={}
                ):
                    with patch(
                        "tv_time_capsule.retro_tv_cache._PLAYER_CLIENT_STRATEGIES",
                        ("web",),
                    ):
                        # Old bug: keep={new only} deleted *playing* at MAX_SLOTS.
                        path = cache.download(nxt, keep={playing})
            self.assertIsNotNone(path)
            self.assertTrue(play_path.is_file())
            self.assertTrue(path.is_file())
            self.assertEqual(set(cache._slots), {playing, nxt})


if __name__ == "__main__":
    unittest.main()
