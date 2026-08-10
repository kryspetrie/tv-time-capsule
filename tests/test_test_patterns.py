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
            "PLAYING",
            "WEATHER",
            "RETRO_TV",
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

    def test_dial_000_opens_secret_directory(self):
        app = self._app("SHOW_LIST")
        with patch.object(app, "_animate_channel_snow_burst"):
            for digit in (0, 0, 0):
                app._append_dial_digit(digit)
            with patch(
                "pygame.time.get_ticks", return_value=app.channel_timer + CHANNEL_PENDING_MS
            ):
                app._tick_dial_timeout()
        self.assertTrue(app._hidden_channels_guide)
        self.assertEqual(app.channel_error, "")
        app._process_browse_action("back")
        self.assertFalse(app._hidden_channels_guide)

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
        fx = AnalogArtifacts(enabled=True, rate_per_minute=60)
        with patch("pygame.time.get_ticks", side_effect=[0, 0, 10, 10, 500, 500]):
            fx.tick()  # schedules first
            fx.tick()  # may trigger
        if fx.is_active():
            fx.apply(self.screen)

    def test_interval_scheduler_triggers_near_rate(self):
        fx = AnalogArtifacts(enabled=True, rate_per_minute=60)
        with patch("random.uniform", return_value=0.0):
            fx._next_at = 0
            with patch("pygame.time.get_ticks", return_value=0):
                fx.tick()
            self.assertGreater(fx._active_until, 0)
            first_until = fx._active_until
            fx._active_until = 0  # glitch finished
            self.assertEqual(fx._next_at, 1000)  # mean 60/min → 1000ms
            with patch("pygame.time.get_ticks", return_value=1000):
                fx.tick()
            self.assertGreater(fx._active_until, first_until)

    def test_clamp_artifact_rate(self):
        from tv_time_capsule.analog_artifacts import clamp_artifact_rate

        self.assertEqual(clamp_artifact_rate(-1), 0.0)
        self.assertEqual(clamp_artifact_rate(100), 60.0)
        self.assertEqual(clamp_artifact_rate(12), 12.0)


class AnalogArtifactsSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _app(self):
        from tv_time_capsule.app import TVTimeCapsule

        return TVTimeCapsule(
            ["./media"],
            fullscreen=False,
            admin=False,
            analog_artifacts=True,
            analog_artifact_rate=30,
        )

    def test_cli_rate_auto_enables(self):
        from tv_time_capsule.app import TVTimeCapsule

        app = TVTimeCapsule(
            ["./media"],
            fullscreen=False,
            admin=False,
            analog_artifacts=None,
            analog_artifact_rate=30,
        )
        self.assertTrue(app._analog_artifacts.enabled)
        self.assertEqual(app._analog_artifacts.rate_per_minute, 30.0)

    def test_cli_no_artifacts_wins_over_rate(self):
        from tv_time_capsule.app import TVTimeCapsule

        app = TVTimeCapsule(
            ["./media"],
            fullscreen=False,
            admin=False,
            analog_artifacts=False,
            analog_artifact_rate=30,
        )
        self.assertFalse(app._analog_artifacts.enabled)
        self.assertEqual(app._analog_artifacts.rate_per_minute, 30.0)

    def test_cli_rate_clamped(self):
        from tv_time_capsule.app import TVTimeCapsule

        app = TVTimeCapsule(
            ["./media"],
            fullscreen=False,
            admin=False,
            analog_artifact_rate=999,
        )
        self.assertEqual(app._analog_artifacts.rate_per_minute, 60.0)

    def test_allowed_surfaces(self):
        app = self._app()
        for view_name in (
            "SHOW_LIST",
            "MOVIE_LIST",
            "EPISODE_SELECT",
            "SEASON_SELECT",
            "LIBRARY_SELECT",
            "WEATHER",
        ):
            with self.subTest(view=view_name):
                app.view = getattr(app, view_name)
                app._show_list_test_pattern = None
                app._hidden_channels_guide = False
                self.assertTrue(app._analog_artifacts_allowed())

    def test_denied_on_playback_retro_and_easter_eggs(self):
        app = self._app()
        app.view = app.PLAYING
        self.assertFalse(app._analog_artifacts_allowed())
        app.view = app.RETRO_TV
        self.assertFalse(app._analog_artifacts_allowed())
        app.view = app.SHOW_LIST
        app._show_list_test_pattern = "001"
        self.assertFalse(app._analog_artifacts_allowed())
        app._show_list_test_pattern = None
        app._hidden_channels_guide = True
        self.assertFalse(app._analog_artifacts_allowed())


if __name__ == "__main__":
    unittest.main()
