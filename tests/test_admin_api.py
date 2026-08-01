"""Tests for admin API helpers."""

from __future__ import annotations

import os
import tempfile
import unittest

from tv_time_capsule.admin_api import (
    effective_media_paths,
    library_summary,
    library_tree_from_shows,
    verify_media_path,
)


class AdminApiTests(unittest.TestCase):
    def test_library_tree_and_summary(self):
        shows = {
            "Bluey": {
                "seasons": {
                    1: {
                        "label": "Season 1",
                        "episodes": [
                            {"number": 1, "name": "Magic", "path": "/x/s01e01.mp4"},
                            {"number": 2, "name": "Sleep", "path": "/x/s01e02.mp4"},
                        ],
                    }
                }
            }
        }
        summary = library_summary(shows)
        self.assertEqual(summary["shows"], 1)
        self.assertEqual(summary["episodes"], 2)
        self.assertEqual(summary["movies"], 0)
        tree = library_tree_from_shows(shows)
        self.assertEqual(tree[0]["name"], "Bluey")
        self.assertEqual(tree[0]["seasons"][0]["label"], "Season 1")
        self.assertEqual(len(tree[0]["seasons"][0]["episodes"]), 2)

    def test_verify_media_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "file.txt"), "w", encoding="utf-8").close()
            ok = verify_media_path(tmp)
            self.assertTrue(ok["ok"])
            self.assertIn("entries", ok)

        missing = verify_media_path("/no/such/path/for/tv-time-capsule")
        self.assertFalse(missing["ok"])

    def test_effective_media_paths_dedupes(self):
        cfg = {
            "media_paths": ["/a", "/b"],
            "mounts": [{"mountpoint": "/b"}, {"mountpoint": "/c"}],
        }
        paths = effective_media_paths(cfg)
        self.assertEqual(paths, ["/a", "/b", "/c"])


if __name__ == "__main__":
    unittest.main()
