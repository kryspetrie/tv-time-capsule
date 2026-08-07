"""Tests for YouTube pillarbox crop disk cache."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tv_time_capsule.youtube_crop_cache import (
    CROP_CACHE_TTL_S,
    CROP_CACHE_VERSION,
    load_pillarbox_crop,
    load_pillarbox_crop_entry,
    prune_pillarbox_crop_cache,
    save_pillarbox_crop,
)


class PillarboxCropCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_roundtrip_crop(self):
        crop = (48, 0, 544, 480)
        save_pillarbox_crop(
            "dQw4w9WgXcQ",
            crop,
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        got, hit = load_pillarbox_crop(
            "dQw4w9WgXcQ",
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0 + 86400,
        )
        self.assertTrue(hit)
        self.assertEqual(got, crop)

    def test_roundtrip_no_crop(self):
        save_pillarbox_crop(
            "abcdefghijk",
            None,
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        got, hit = load_pillarbox_crop(
            "abcdefghijk",
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        self.assertTrue(hit)
        self.assertIsNone(got)

    def test_expires_after_ttl(self):
        save_pillarbox_crop(
            "dQw4w9WgXcQ",
            (40, 0, 240, 240),
            width=320,
            height=240,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        got, hit = load_pillarbox_crop(
            "dQw4w9WgXcQ",
            width=320,
            height=240,
            cache_dir=self.cache_dir,
            now=1_000_000.0 + CROP_CACHE_TTL_S + 1,
        )
        self.assertFalse(hit)
        self.assertIsNone(got)
        self.assertFalse((self.cache_dir / "dQw4w9WgXcQ.json").exists())

    def test_size_mismatch_is_miss(self):
        save_pillarbox_crop(
            "dQw4w9WgXcQ",
            (40, 0, 240, 240),
            width=320,
            height=240,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        got, hit = load_pillarbox_crop(
            "dQw4w9WgXcQ",
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        self.assertFalse(hit)
        self.assertIsNone(got)

    def test_old_cache_version_is_miss(self):
        path = self.cache_dir / "dQw4w9WgXcQ.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"youtube_id":"dQw4w9WgXcQ","version":1,'
            '"width":640,"height":480,"crop":null,"fetched_at":1000000.0}\n',
            encoding="utf-8",
        )
        got, hit = load_pillarbox_crop(
            "dQw4w9WgXcQ",
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        self.assertFalse(hit)
        self.assertIsNone(got)
        self.assertEqual(CROP_CACHE_VERSION, 5)

    def test_apply_false_keeps_geometry(self):
        crop = (48, 0, 544, 480)
        save_pillarbox_crop(
            "dQw4w9WgXcQ",
            crop,
            width=640,
            height=480,
            apply=False,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        got, hit = load_pillarbox_crop(
            "dQw4w9WgXcQ",
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        self.assertTrue(hit)
        self.assertIsNone(got)
        entry = load_pillarbox_crop_entry(
            "dQw4w9WgXcQ",
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.crop, crop)
        self.assertFalse(entry.apply)

    def test_prune_removes_stale(self):
        save_pillarbox_crop(
            "oldvideo12a",
            None,
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0,
        )
        save_pillarbox_crop(
            "newvideo12b",
            (10, 0, 100, 100),
            width=640,
            height=480,
            cache_dir=self.cache_dir,
            now=1_000_000.0 + CROP_CACHE_TTL_S - 100,
        )
        removed = prune_pillarbox_crop_cache(
            cache_dir=self.cache_dir,
            now=1_000_000.0 + CROP_CACHE_TTL_S + 1,
        )
        self.assertGreaterEqual(removed, 1)
        self.assertFalse((self.cache_dir / "oldvideo12a.json").exists())
        self.assertTrue((self.cache_dir / "newvideo12b.json").exists())


if __name__ == "__main__":
    unittest.main()
