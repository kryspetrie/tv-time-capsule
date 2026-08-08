"""Pending autoplay after Enter queues an uncached YouTube episode."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pygame

from tv_time_capsule.app import TVTimeCapsule


class PendingCachePlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    def _app(self) -> TVTimeCapsule:
        app = TVTimeCapsule.__new__(TVTimeCapsule)
        app.SHOW_LIST = TVTimeCapsule.SHOW_LIST
        app.EPISODE_SELECT = TVTimeCapsule.EPISODE_SELECT
        app.PLAYING = TVTimeCapsule.PLAYING
        app.WEATHER = TVTimeCapsule.WEATHER
        app.RETRO_TV = TVTimeCapsule.RETRO_TV
        app.KEY_CONFIG = TVTimeCapsule.KEY_CONFIG
        app.KEY_CAPTURE = TVTimeCapsule.KEY_CAPTURE
        app.GAMEPAD_CONFIG = TVTimeCapsule.GAMEPAD_CONFIG
        app.GAMEPAD_CAPTURE = TVTimeCapsule.GAMEPAD_CAPTURE
        app.SAFE_ZONE_EDIT = TVTimeCapsule.SAFE_ZONE_EDIT
        app.CONFIRM_EXIT = TVTimeCapsule.CONFIRM_EXIT
        app.view = TVTimeCapsule.EPISODE_SELECT
        app._screensaver_active = False
        app._pending_cache_play = None
        app.channel_error = ""
        app.channel_error_time = 0
        app.shows = {
            "Ms Rachel": {
                "seasons": {
                    1: {
                        "episodes": [
                            {
                                "number": 1,
                                "title": "A",
                                "path": "https://youtu.be/aaaaaaaaaaa",
                                "youtube_id": "aaaaaaaaaaa",
                            },
                            {
                                "number": 2,
                                "title": "B",
                                "path": "https://youtu.be/bbbbbbbbbbb",
                                "youtube_id": "bbbbbbbbbbb",
                            },
                        ]
                    }
                }
            }
        }
        app.state = {}
        app.cur_show = "Ms Rachel"
        app.cur_season = 1
        app.cursor = 0
        app._playing_is_movie = False
        app.cur_movie = None
        app.playing_show = None
        app.playing_season = None
        app.playing_episodes = []
        app.playing_index = 0
        yt = MagicMock()
        yt.enabled = True
        yt.playback_mode = "cached_only"
        yt.backend_for_episode.return_value = "blocked"
        yt.missing_items_for_episode.return_value = [
            ("Ms Rachel", 1, 1, "A", "aaaaaaaaaaa")
        ]
        yt.request_priority.return_value = 1
        yt.is_priority_or_active.return_value = True
        yt.is_cached.return_value = False
        yt.is_unavailable.return_value = False
        app._yt_offline = yt
        return app

    def test_enter_sets_pending_target(self):
        app = self._app()
        ep = app.shows["Ms Rachel"]["seasons"][1]["episodes"][0]
        self.assertTrue(
            app._priority_cache_episode_on_play_block("Ms Rachel", 1, ep)
        )
        self.assertEqual(
            app._pending_cache_play,
            {
                "show": "Ms Rachel",
                "season": 1,
                "youtube_id": "aaaaaaaaaaa",
                "episode_number": 1,
            },
        )
        app._yt_offline.request_priority.assert_called_once()
        kwargs = app._yt_offline.request_priority.call_args.kwargs
        self.assertTrue(kwargs.get("bump"))
        self.assertTrue(kwargs.get("front"))

    def test_enter_on_other_episode_replaces_pending(self):
        app = self._app()
        eps = app.shows["Ms Rachel"]["seasons"][1]["episodes"]
        app._priority_cache_episode_on_play_block("Ms Rachel", 1, eps[0])
        app._yt_offline.missing_items_for_episode.return_value = [
            ("Ms Rachel", 1, 2, "B", "bbbbbbbbbbb")
        ]
        app._priority_cache_episode_on_play_block("Ms Rachel", 1, eps[1])
        self.assertEqual(app._pending_cache_play["youtube_id"], "bbbbbbbbbbb")

    def test_tick_autoplays_when_cached(self):
        app = self._app()
        app._pending_cache_play = {
            "show": "Ms Rachel",
            "season": 1,
            "youtube_id": "aaaaaaaaaaa",
            "episode_number": 1,
        }
        app._yt_offline.is_cached.return_value = True
        with patch.object(app, "_start_pending_cached_episode", return_value=True) as start:
            with patch("pygame.time.get_ticks", return_value=1234):
                app._tick_pending_cache_play()
        start.assert_called_once()
        self.assertIsNone(app._pending_cache_play)
        self.assertEqual(app.channel_error, "Playing")

    def test_tick_waits_until_cached(self):
        app = self._app()
        pending = {
            "show": "Ms Rachel",
            "season": 1,
            "youtube_id": "aaaaaaaaaaa",
            "episode_number": 1,
        }
        app._pending_cache_play = pending
        app._yt_offline.is_cached.return_value = False
        with patch.object(app, "_start_pending_cached_episode") as start:
            app._tick_pending_cache_play()
        start.assert_not_called()
        self.assertEqual(app._pending_cache_play, pending)

    def test_tick_skips_while_playing(self):
        app = self._app()
        app.view = TVTimeCapsule.PLAYING
        app._pending_cache_play = {
            "show": "Ms Rachel",
            "season": 1,
            "youtube_id": "aaaaaaaaaaa",
            "episode_number": 1,
        }
        app._yt_offline.is_cached.return_value = True
        with patch.object(app, "_start_pending_cached_episode") as start:
            app._tick_pending_cache_play()
        start.assert_not_called()
        self.assertIsNotNone(app._pending_cache_play)

    def test_tick_defers_while_screensaver_active(self):
        app = self._app()
        app._screensaver_active = True
        app._pending_cache_play = {
            "show": "Ms Rachel",
            "season": 1,
            "youtube_id": "aaaaaaaaaaa",
            "episode_number": 1,
        }
        app._yt_offline.is_cached.return_value = True
        with patch.object(app, "_start_pending_cached_episode") as start:
            app._tick_pending_cache_play()
        start.assert_not_called()
        self.assertIsNotNone(app._pending_cache_play)

    def test_tick_clears_unavailable(self):
        app = self._app()
        app._pending_cache_play = {
            "show": "Ms Rachel",
            "season": 1,
            "youtube_id": "aaaaaaaaaaa",
            "episode_number": 1,
        }
        app._yt_offline.is_unavailable.return_value = True
        with patch("pygame.time.get_ticks", return_value=99):
            app._tick_pending_cache_play()
        self.assertIsNone(app._pending_cache_play)
        self.assertEqual(app.channel_error, "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
