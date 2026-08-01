"""Tests for kids-mode allowlist filtering and tagging."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.app import TVTimeCapsule
from tv_time_capsule.config import _parse_kids_mode


class KidsAllowlistParseTests(unittest.TestCase):
    def test_absent_allowlist_means_legacy_full_library(self):
        km = _parse_kids_mode({"default_enabled": False})
        self.assertNotIn("allowlist", km)

    def test_present_allowlist_is_normalized(self):
        km = _parse_kids_mode(
            {
                "allowlist": {
                    "shows": ["Bluey", 12],
                    "movies": ["Toy Story"],
                }
            }
        )
        self.assertEqual(km["allowlist"]["shows"], ["Bluey", "12"])
        self.assertEqual(km["allowlist"]["movies"], ["Toy Story"])

    def test_empty_or_invalid_allowlist_still_present(self):
        km = _parse_kids_mode({"allowlist": {}})
        self.assertEqual(km["allowlist"]["shows"], [])
        self.assertEqual(km["allowlist"]["movies"], [])

        km_bad = _parse_kids_mode({"allowlist": "oops"})
        self.assertEqual(km_bad["allowlist"]["shows"], [])
        self.assertEqual(km_bad["allowlist"]["movies"], [])


class KidsAllowlistAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _app(self) -> TVTimeCapsule:
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.show_names = ["Bluey", "Nova", "Sesame Street"]
        app.shows = {
            name: {"has_seasons": False, "seasons": {1: {"episodes": []}}}
            for name in app.show_names
        }
        app.movie_names = ["Alpha Movie", "Zulu Movie"]
        app.movies = {
            key: {"title": key, "path": f"/tmp/{key}.mp4"} for key in app.movie_names
        }
        app._kids_mode_active = False
        app._kids_allowlist = None
        return app

    def test_absent_allowlist_shows_full_library_in_kids_mode(self):
        app = self._app()
        app._kids_mode_active = True
        app._kids_allowlist = None
        self.assertEqual(app._browse_show_names(), app.show_names)
        self.assertEqual(app._browse_movie_names(), app.movie_names)

    def test_present_allowlist_filters_only_in_kids_mode(self):
        app = self._app()
        app._kids_allowlist = {
            "shows": ["Bluey"],
            "movies": ["Zulu Movie"],
        }
        app._kids_mode_active = False
        self.assertEqual(app._browse_show_names(), app.show_names)
        self.assertEqual(app._browse_movie_names(), app.movie_names)

        app._kids_mode_active = True
        self.assertEqual(app._browse_show_names(), ["Bluey"])
        self.assertEqual(app._browse_movie_names(), ["Zulu Movie"])

    def test_empty_allowlist_hides_everything_in_kids_mode(self):
        app = self._app()
        app._kids_mode_active = True
        app._kids_allowlist = {"shows": [], "movies": []}
        self.assertEqual(app._browse_show_names(), [])
        self.assertEqual(app._browse_movie_names(), [])

    def test_toggle_tag_creates_and_persists_allowlist(self):
        app = self._app()
        app.view = app.SHOW_LIST
        app.cursor = 0
        saved = {}

        def capture_save(cfg):
            saved.clear()
            saved.update(cfg.get("kids_mode") or {})

        with patch("tv_time_capsule.app.save_config", side_effect=capture_save):
            self.assertIsNone(app._kids_allowlist)
            app._toggle_kids_tag_current()
            self.assertEqual(app._kids_allowlist["shows"], ["Bluey"])
            self.assertTrue(app._title_kids_tagged(show="Bluey"))
            self.assertEqual(saved["allowlist"]["shows"], ["Bluey"])

            app._toggle_kids_tag_current()
            self.assertEqual(app._kids_allowlist["shows"], [])
            self.assertFalse(app._title_kids_tagged(show="Bluey"))
            self.assertEqual(saved["allowlist"]["shows"], [])

    def test_toggle_tag_ignored_in_kids_mode(self):
        app = self._app()
        app._kids_mode_active = True
        app.view = app.SHOW_LIST
        app.cursor = 0
        with patch("tv_time_capsule.app.save_config") as save:
            app._toggle_kids_tag_current()
            save.assert_not_called()
        self.assertIsNone(app._kids_allowlist)

    def test_load_allowlist_from_config(self):
        app = self._app()
        app.config["kids_mode"] = {
            "allowlist": {"shows": ["Nova"], "movies": ["Alpha Movie"]}
        }
        app._load_kids_allowlist()
        self.assertEqual(app._kids_allowlist["shows"], ["Nova"])
        self.assertEqual(app._kids_allowlist["movies"], ["Alpha Movie"])


if __name__ == "__main__":
    unittest.main()
