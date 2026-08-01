"""Integration tests for dial digit buffering and timeouts in the app."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.app import TVTimeCapsule
from tv_time_capsule.config import CHANNEL_PENDING_MS, CHANNEL_TIMEOUT_MS
from tv_time_capsule.test_patterns import pattern_asset_path


class DialTimingAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _app(self) -> TVTimeCapsule:
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app._kids_allowlist = None
        app._letter_menu_open = False
        app.view = app.SHOW_LIST
        app.show_names = [f"Show {i:02d}" for i in range(12)]
        app.shows = {
            name: {"has_seasons": False, "seasons": {1: {"episodes": []}}}
            for name in app.show_names
        }
        app.cursor = 0
        app._channel_fx.configure(snow=False, shutdown=False, audio=False)
        return app

    def test_page_down_waits_for_short_delay(self):
        app = self._app()
        ticks = iter([1000, 1100, 1100 + CHANNEL_PENDING_MS - 1, 1100 + CHANNEL_PENDING_MS])
        with patch("pygame.time.get_ticks", side_effect=lambda: next(ticks)):
            app._append_dial_digit(0)
            app._append_dial_digit(2)
            self.assertEqual(app.channel_digits, "02")
            self.assertEqual(app.cursor, 0)

            app._tick_dial_timeout()
            self.assertEqual(app.channel_digits, "02")
            self.assertEqual(app.cursor, 0)

            app._tick_dial_timeout()
            self.assertEqual(app.channel_digits, "")
            self.assertEqual(app.cursor, 5)

    def test_page_up_waits_for_short_delay(self):
        app = self._app()
        app.cursor = 7
        ticks = iter([2000, 2050, 2050 + CHANNEL_PENDING_MS])
        with patch("pygame.time.get_ticks", side_effect=lambda: next(ticks)):
            app._append_dial_digit(0)
            app._append_dial_digit(1)
            self.assertEqual(app.channel_digits, "01")
            app._tick_dial_timeout()
            self.assertEqual(app.channel_digits, "")
            self.assertEqual(app.cursor, 2)

    def test_fast_001_opens_test_pattern_before_letter_menu(self):
        if pattern_asset_path("001") is None:
            self.skipTest("test pattern assets not present")
        app = self._app()
        with patch.object(app, "_animate_channel_snow_burst"):
            app._append_dial_digit(0)
            app._append_dial_digit(0)
            self.assertEqual(app.channel_digits, "00")
            self.assertFalse(app._letter_menu_open)
            app._append_dial_digit(1)
        self.assertEqual(app._show_list_test_pattern, "001")
        self.assertFalse(app._letter_menu_open)
        self.assertEqual(app.channel_error, "")

    def test_00_timeout_opens_letter_menu(self):
        app = self._app()
        ticks = iter([3000, 3100, 3100 + CHANNEL_TIMEOUT_MS])
        with patch("pygame.time.get_ticks", side_effect=lambda: next(ticks)):
            app._append_dial_digit(0)
            app._append_dial_digit(0)
            self.assertEqual(app.channel_digits, "00")
            app._tick_dial_timeout()
        self.assertTrue(app._letter_menu_open)
        self.assertEqual(app.channel_digits, "")

    def test_0_timeout_acts_as_back(self):
        app = self._app()
        app.view = app.SEASON_SELECT
        app.cur_show = app.show_names[0]
        called = []

        def capture_back(action):
            called.append(action)

        ticks = iter([4000, 4000 + CHANNEL_TIMEOUT_MS])
        with patch("pygame.time.get_ticks", side_effect=lambda: next(ticks)):
            with patch.object(app, "_process_browse_action", side_effect=capture_back):
                app._append_dial_digit(0)
                self.assertEqual(app.channel_digits, "0")
                app._tick_dial_timeout()
        self.assertEqual(called, ["back"])
        self.assertEqual(app.channel_digits, "")

    def test_03_commits_invalid_immediately(self):
        app = self._app()
        app._append_dial_digit(0)
        app._append_dial_digit(3)
        self.assertEqual(app.channel_digits, "")
        self.assertIn("03", app.channel_error)


class LetterMenuAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _app(self) -> TVTimeCapsule:
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app.view = app.SHOW_LIST
        app.show_names = ["Alpha", "Beta", "Zebra"]
        app.shows = {
            name: {"has_seasons": False, "seasons": {1: {"episodes": []}}}
            for name in app.show_names
        }
        app.cursor = 0
        return app

    def test_open_jump_and_close_letter_menu(self):
        app = self._app()
        app._open_letter_menu()
        self.assertTrue(app._letter_menu_open)

        app._process_letter_menu_action("down")
        app._process_letter_menu_action("select")
        self.assertFalse(app._letter_menu_open)
        self.assertEqual(app.cursor, 1)  # Beta

        app.cursor = 0
        app._open_letter_menu()
        app._process_letter_menu_action("right")
        app._process_letter_menu_action("right")
        self.assertEqual(app._letter_menu_cursor, 2)
        app._process_letter_menu_action("left")
        self.assertEqual(app._letter_menu_cursor, 1)
        app._process_letter_menu_action("back")
        self.assertFalse(app._letter_menu_open)

        app.cursor = 0
        app._open_letter_menu()
        app._process_letter_menu_digit(9)  # Y-Z/# → Zebra
        self.assertFalse(app._letter_menu_open)
        self.assertEqual(app.cursor, 2)

        app._open_letter_menu()
        app._process_letter_menu_digit(0)
        self.assertFalse(app._letter_menu_open)

    def test_letter_menu_blocked_in_kids_mode(self):
        app = self._app()
        app._kids_mode_active = True
        app._open_letter_menu()
        self.assertFalse(app._letter_menu_open)
        self.assertEqual(app.channel_error, "Not Available")

    def test_letter_menu_blocked_on_season_list(self):
        app = self._app()
        app.view = app.SEASON_SELECT
        app._open_letter_menu()
        self.assertFalse(app._letter_menu_open)
        self.assertEqual(app.channel_error, "Not Available")


if __name__ == "__main__":
    unittest.main()
