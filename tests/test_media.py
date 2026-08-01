"""Unit tests for media discovery helpers."""

from __future__ import annotations

import os
import tempfile
import unittest

from tv_time_capsule.media import (
    discover_library,
    discover_movies,
    folder_season_info,
    parse_episode_name,
    parse_episode_number,
    parse_season_episode,
)


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00")


class MediaParseTests(unittest.TestCase):
    def test_parse_season_episode(self):
        self.assertEqual(parse_season_episode("s01e03 - Dance.mp4"), (1, 3))
        self.assertEqual(parse_season_episode("S02E11.mkv"), (2, 11))
        self.assertEqual(parse_season_episode("plain.mp4"), (None, None))

    def test_parse_episode_number(self):
        self.assertEqual(parse_episode_number("s01e05.mp4"), 5)
        self.assertEqual(parse_episode_number("03-intro.mp4"), 3)

    def test_parse_episode_name(self):
        self.assertEqual(parse_episode_name("s01e01 - Dancing.mp4"), "Dancing")
        self.assertEqual(parse_episode_name("02 - Swim.mp4"), "Swim")

    def test_folder_season_info(self):
        self.assertEqual(folder_season_info("s01", 1), (1, None))
        self.assertEqual(folder_season_info("Season 2", 1), (2, None))
        self.assertEqual(folder_season_info("Action", 3), (3, "Action"))


class MediaDiscoveryTests(unittest.TestCase):
    def test_discover_movies_flat_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "Zulu.mp4"))
            _touch(os.path.join(tmp, "Alpha.mp4"))
            _touch(os.path.join(tmp, "nested", "Middle.mp4"))
            movies = discover_movies([tmp])
            titles = [m["title"] for m in movies]
            self.assertEqual(titles, ["Alpha", "Middle", "Zulu"])

    def test_discover_library_split_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "split")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Big Hero", discovery["movies"])

    def test_discover_library_shows_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "shows_only")
            self.assertIn("Bluey", discovery["shows"])
            self.assertEqual(discovery["movies"], {})

    def test_discover_library_movies_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "movies_only")
            self.assertEqual(discovery["shows"], {})
            self.assertIn("Big Hero", discovery["movies"])

    def test_discover_library_legacy_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "Bluey", "s01", "s01e01.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "legacy")
            self.assertIn("Bluey", discovery["shows"])


if __name__ == "__main__":
    unittest.main()
