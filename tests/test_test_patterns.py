"""Tests for secret test patterns and analog artifacts."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.analog_artifacts import AnalogArtifacts
from tv_time_capsule.config import CHANNEL_PENDING_MS
from tv_time_capsule.test_patterns import (
    SHOW_LIST_TEST_PATTERNS,
    is_show_list_test_dial,
    pattern_asset_path,
)


class TestPatternsTests(unittest.TestCase):
    def test_dial_codes(self):
        self.assertTrue(is_show_list_test_dial("001"))
        self.assertTrue(is_show_list_test_dial("002"))
        self.assertTrue(is_show_list_test_dial("003"))
        self.assertFalse(is_show_list_test_dial("0"))
        self.assertFalse(is_show_list_test_dial("00"))
        self.assertFalse(is_show_list_test_dial("000"))
        self.assertFalse(is_show_list_test_dial("1"))
        self.assertFalse(is_show_list_test_dial("007"))

    def test_assets_exist(self):
        missing = [
            dial
            for dial in SHOW_LIST_TEST_PATTERNS
            if pattern_asset_path(dial) is None
        ]
        if missing:
            self.skipTest(
                "Add colorbars.png, grid.png, indianhead.png to "
                "src/tv_time_capsule/assets/ (not bundled in repo)"
            )
        for dial, name in SHOW_LIST_TEST_PATTERNS.items():
            path = pattern_asset_path(dial)
            assert path is not None
            self.assertEqual(path.name, name)


class TestPatternDialViewsTests(unittest.TestCase):
    """Easter egg dials should work on every parent browse screen."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _app(self, view_name: str):
        from tv_time_capsule.app import TVTimeCapsule

        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app.view = getattr(app, view_name)
        return app

    def test_dial_works_on_all_parent_browse_views(self):
        if pattern_asset_path("001") is None:
            self.skipTest("test pattern assets not present")
        for view_name in (
            "SHOW_LIST",
            "MOVIE_LIST",
            "LIBRARY_SELECT",
            "SEASON_SELECT",
            "EPISODE_SELECT",
        ):
            with self.subTest(view=view_name):
                app = self._app(view_name)
                with patch.object(app, "_animate_channel_snow_burst"):
                    for digit in (0, 0, 1):
                        app._append_dial_digit(digit)
                    # 00x dials now have a short hold; tick the timeout to commit.
                    with patch("pygame.time.get_ticks", return_value=app.channel_timer + CHANNEL_PENDING_MS):
                        app._tick_dial_timeout()
                self.assertEqual(app._show_list_test_pattern, "001")
                self.assertEqual(app.channel_error, "")
                app._process_browse_action("back")
                self.assertIsNone(app._show_list_test_pattern)

    def test_kids_mode_does_not_show_patterns(self):
        app = self._app("SHOW_LIST")
        app._kids_mode_active = True
        for digit in (0, 0, 1):
            app._append_dial_digit(digit)
        self.assertIsNone(app._show_list_test_pattern)


class AnalogArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.screen = pygame.Surface((640, 480))
        self.screen.fill((40, 80, 120))

    def test_inactive_by_default(self):
        fx = AnalogArtifacts(enabled=False)
        fx.apply(self.screen)
        self.assertEqual(self.screen.get_at((10, 10))[:3], (40, 80, 120))

    def test_can_trigger_and_apply(self):
        fx = AnalogArtifacts(enabled=True, rate_per_minute=999)
        with patch("pygame.time.get_ticks", side_effect=[0, 500, 1000]):
            fx.tick()
        if fx.is_active():
            fx.apply(self.screen)


if __name__ == "__main__":
    unittest.main()
