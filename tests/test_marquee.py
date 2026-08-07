"""Unit tests for list/header marquee scroll helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.app import TVTimeCapsule
from tv_time_capsule.config import MARQUEE_END_PAUSE_MS, MARQUEE_SPEED_PX_S


class MarqueeSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def _app(self):
        app = TVTimeCapsule.__new__(TVTimeCapsule)
        app.config = {"ui": {"marquee_scroll": "always"}}
        app._marquee_sync_start = 0
        app._marquee_sync_max = 200
        app._marquee_seen_max = 0
        app._marquee_page = None
        app._marquee_key = None
        app._marquee_start = 0
        app._header_marquee_key = None
        app._header_marquee_start = 0
        app.view = TVTimeCapsule.SHOW_LIST
        app.cursor = 0
        app._kids_mode_active = False
        app._kids_browse_style = "card"
        return app

    def test_same_speed_short_finishes_first(self):
        app = self._app()
        # After enough time for 100px at MARQUEE_SPEED, short is done; long still moving.
        t = MARQUEE_END_PAUSE_MS + int(100 / MARQUEE_SPEED_PX_S * 1000) + 50
        with patch("pygame.time.get_ticks", return_value=t):
            short = app._marquee_offset_synced(100)
            long = app._marquee_offset_synced(200)
        self.assertEqual(short, 100)
        self.assertGreater(long, 100)
        self.assertLess(long, 200)

    def test_short_holds_at_end_until_long_done(self):
        app = self._app()
        scroll_ms = int(200 / MARQUEE_SPEED_PX_S * 1000)
        t = MARQUEE_END_PAUSE_MS + scroll_ms - 10
        with patch("pygame.time.get_ticks", return_value=t):
            short = app._marquee_offset_synced(50)
            long = app._marquee_offset_synced(200)
        self.assertEqual(short, 50)
        self.assertGreaterEqual(long, 190)

    def test_begin_frame_promotes_max(self):
        app = self._app()
        app._marquee_page = ("locked",)
        app._marquee_page_key = lambda: ("locked",)
        app._marquee_seen_max = 320
        app._marquee_sync_max = 1
        app._marquee_begin_frame()
        self.assertEqual(app._marquee_sync_max, 320)
        self.assertEqual(app._marquee_seen_max, 0)

    def test_begin_frame_resets_on_page_change(self):
        app = self._app()
        app._marquee_page = ("old",)
        app._marquee_page_key = lambda: ("new",)
        app._marquee_sync_start = 0
        app._marquee_sync_max = 400
        app._marquee_seen_max = 400
        with patch("pygame.time.get_ticks", return_value=12_000):
            app._marquee_begin_frame()
        self.assertEqual(app._marquee_page, ("new",))
        self.assertEqual(app._marquee_sync_start, 12_000)
        self.assertEqual(app._marquee_sync_max, 1)
        self.assertEqual(app._marquee_seen_max, 0)
        # Fresh page holds at the start of the title.
        with patch("pygame.time.get_ticks", return_value=12_100):
            self.assertEqual(app._marquee_offset_synced(200), 0)

    def test_selected_mode(self):
        app = self._app()
        app.config = {"ui": {"marquee_scroll": "selected"}}
        self.assertEqual(app._marquee_scroll_mode(), "selected")


if __name__ == "__main__":
    unittest.main()
