"""Screensaver idle timer must ignore background YouTube cache work."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pygame

from tv_time_capsule.app import TVTimeCapsule


class ScreensaverIdleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def _app(self) -> TVTimeCapsule:
        app = TVTimeCapsule.__new__(TVTimeCapsule)
        app.PLAYING = TVTimeCapsule.PLAYING
        app.WEATHER = TVTimeCapsule.WEATHER
        app.RETRO_TV = TVTimeCapsule.RETRO_TV
        app.SHOW_LIST = TVTimeCapsule.SHOW_LIST
        app.view = TVTimeCapsule.SHOW_LIST
        app._screensaver_active = False
        app._screensaver_enabled = True
        app._screensaver_timeout_ms = 30_000
        app._last_activity_ms = 0
        app._yt_offline_idle = False
        yt = MagicMock()
        yt.enabled = True
        yt.download_when_idle = True
        yt.idle_seconds = 10
        app._yt_offline = yt
        return app

    def test_keyboard_repeat_does_not_touch_activity(self):
        app = self._app()
        app._last_activity_ms = 1000
        with patch("pygame.time.get_ticks", return_value=9999):
            app._note_keyboard_input(repeat=True)
        self.assertEqual(app._last_activity_ms, 1000)
        self.assertFalse(app._screensaver_active)

    def test_keyboard_press_resets_activity(self):
        app = self._app()
        app._last_activity_ms = 1000
        app._screensaver_active = True
        with patch("pygame.time.get_ticks", return_value=9999):
            app._note_keyboard_input(repeat=False)
        self.assertEqual(app._last_activity_ms, 9999)
        self.assertFalse(app._screensaver_active)

    def test_offline_idle_waits_for_inactivity(self):
        app = self._app()
        app._last_activity_ms = 100_000
        with patch("pygame.time.get_ticks", return_value=105_000):
            # Only 5s idle; need 10s.
            app._tick_youtube_offline_idle()
        app._yt_offline.set_idle.assert_not_called()
        self.assertFalse(app._yt_offline_idle)

        with patch("pygame.time.get_ticks", return_value=111_000):
            app._tick_youtube_offline_idle()
        app._yt_offline.set_idle.assert_called_once_with(True)
        self.assertTrue(app._yt_offline_idle)

    def test_offline_idle_tick_does_not_reset_activity(self):
        app = self._app()
        app._last_activity_ms = 50_000
        with patch("pygame.time.get_ticks", return_value=80_000):
            app._tick_youtube_offline_idle()
        self.assertEqual(app._last_activity_ms, 50_000)

    def test_offline_idle_on_screensaver_without_waiting(self):
        app = self._app()
        app._screensaver_active = True
        app._last_activity_ms = 80_000  # "recent" relative to now
        with patch("pygame.time.get_ticks", return_value=81_000):
            app._tick_youtube_offline_idle()
        app._yt_offline.set_idle.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
