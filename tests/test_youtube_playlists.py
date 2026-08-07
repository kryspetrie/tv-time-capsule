"""Tests for YouTube playlist include/group selectors."""

from __future__ import annotations

import unittest

from tv_time_capsule.youtube_playlists import match_playlist_groups, parse_playlist_selectors
from tv_time_capsule.youtube_catalog import expand_youtube_shows, show_from_cache_payload


class PlaylistSelectorTests(unittest.TestCase):
    def test_parse_exact_and_group(self):
        sels = parse_playlist_selectors(
            [
                "Bobby's World",
                {
                    "title": "Ghostwriter",
                    "match": r"(?i)^Ghostwriter\s+Season\s+(\d+)$",
                },
            ]
        )
        self.assertEqual(len(sels), 2)
        self.assertEqual(sels[0]["title"], "Bobby's World")
        self.assertEqual(sels[1]["title"], "Ghostwriter")

    def test_match_ghostwriter_seasons(self):
        seasons = {
            1: {"label": "Bobby's World", "episodes": [{"youtube_id": "aaaaaaaaaaa"}]},
            2: {
                "label": "Ghostwriter Season 1",
                "episodes": [{"youtube_id": "bbbbbbbbbbb"}],
                "playlist_id": "PLg1",
            },
            3: {
                "label": "Ghostwriter Season 2",
                "episodes": [{"youtube_id": "ccccccccccc"}],
                "playlist_id": "PLg2",
            },
            4: {"label": "Favorites", "episodes": [{"youtube_id": "ddddddddddd"}]},
        }
        sels = parse_playlist_selectors(
            [
                "Bobby's World",
                {
                    "title": "Ghostwriter",
                    "match": r"(?i)^Ghostwriter\s+Season\s+(\d+)$",
                },
            ]
        )
        groups = match_playlist_groups(
            seasons, sels, sanitize_label=lambda s: s
        )
        titles = {t for t, _ in groups}
        self.assertEqual(titles, {"Bobby's World", "Ghostwriter"})
        gw = dict(groups)["Ghostwriter"]
        self.assertEqual(set(gw.keys()), {1, 2})
        self.assertEqual(gw[1]["label"], "Season 1")
        self.assertEqual(gw[2]["label"], "Season 2")

    def test_expand_playlist_shows_groups(self):
        show = show_from_cache_payload(
            {
                "title": "90s Project",
                "seasons": {
                    "0": {
                        "label": "All Videos",
                        "episodes": [{"name": "U", "youtube_id": "dQw4w9WgXcQ"}],
                    },
                    "1": {
                        "label": "Ghostwriter Season 1",
                        "playlist_id": "PLg1",
                        "episodes": [{"name": "E1", "youtube_id": "aaaaaaaaaaa"}],
                    },
                    "2": {
                        "label": "Ghostwriter Season 3",
                        "playlist_id": "PLg3",
                        "episodes": [{"name": "E3", "youtube_id": "bbbbbbbbbbb"}],
                    },
                    "3": {
                        "label": "Wishbone",
                        "playlist_id": "PLw",
                        "episodes": [{"name": "W1", "youtube_id": "ccccccccccc"}],
                    },
                    "4": {
                        "label": "Favorites",
                        "episodes": [{"name": "F", "youtube_id": "ddddddddddd"}],
                    },
                },
            },
            entry={"title": "90s Project"},
        )
        entry = {
            "title": "90s Project",
            "playlists_as_shows": True,
            "playlist_shows": parse_playlist_selectors(
                [
                    "Wishbone",
                    {
                        "title": "Ghostwriter",
                        "match": r"(?i)^Ghostwriter\s+Season\s+(\d+)$",
                    },
                ]
            ),
        }
        expanded = expand_youtube_shows("90s Project", show, entry)
        self.assertIn("Ghostwriter", expanded)
        self.assertIn("Wishbone", expanded)
        self.assertNotIn("Favorites", expanded)
        self.assertNotIn("90s Project", expanded)
        gw = expanded["Ghostwriter"]
        self.assertTrue(gw["has_seasons"])
        self.assertEqual(set(gw["seasons"].keys()), {1, 3})

    def test_include_playlists_filters_channel_seasons(self):
        show = show_from_cache_payload(
            {
                "title": "Bill Nye",
                "seasons": {
                    "0": {
                        "label": "All Videos",
                        "episodes": [{"name": "U", "youtube_id": "dQw4w9WgXcQ"}],
                    },
                    "1": {
                        "label": "Season 2",
                        "episodes": [{"name": "A", "youtube_id": "aaaaaaaaaaa"}],
                    },
                    "2": {
                        "label": "Season 1",
                        "episodes": [{"name": "B", "youtube_id": "bbbbbbbbbbb"}],
                    },
                    "3": {
                        "label": "Bill Nye The Science Guy",
                        "episodes": [{"name": "C", "youtube_id": "ccccccccccc"}],
                    },
                },
            },
            entry={"title": "Bill Nye"},
        )
        entry = {
            "title": "Bill Nye",
            "include_all_videos": False,
            "include_playlists": parse_playlist_selectors(
                [{"match": r"(?i)^Season\s+(\d+)$"}]
            ),
        }
        expanded = expand_youtube_shows("Bill Nye", show, entry)
        self.assertEqual(list(expanded.keys()), ["Bill Nye"])
        seasons = expanded["Bill Nye"]["seasons"]
        self.assertEqual(set(seasons.keys()), {1, 2})
        self.assertNotIn(0, seasons)


if __name__ == "__main__":
    unittest.main()
