"""App-level tests for home_menu rows, Esc hierarchy, and playback dial."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.app import TVTimeCapsule
from tv_time_capsule.config import CHANNEL_TIMEOUT_MS


class FakePlayer:
    finished = False
    paused = False
    filepath = "/tmp/fake.mp4"
    time_pos = 10.0
    duration = 100.0

    def is_finished(self) -> bool:
        return self.finished

    def is_playing(self) -> bool:
        return True

    def stop(self) -> None:
        pass

    def update_time(self) -> None:
        pass

    def pause(self) -> None:
        self.paused = not self.paused

    def seek(self, _delta) -> None:
        pass

    def adjust_volume(self, _delta) -> None:
        pass

    def check_stall(self) -> bool:
        return False


class HomeNavTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _app(self) -> TVTimeCapsule:
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app._channel_fx.configure(snow=False, shutdown=False, audio=False)
        app.library_layout = "legacy"
        app.show_names = ["Alpha", "Bravo"]
        app.shows = {
            "Alpha": {
                "has_seasons": False,
                "seasons": {
                    1: {
                        "episodes": [
                            {"number": 1, "name": "E1", "path": "/tmp/a1.mp4"},
                            {"number": 2, "name": "E2", "path": "/tmp/a2.mp4"},
                        ]
                    }
                },
            },
            "Bravo": {
                "has_seasons": True,
                "seasons": {
                    1: {"episodes": [{"number": 1, "name": "B1", "path": "/tmp/b1.mp4"}]},
                    2: {"episodes": [{"number": 1, "name": "B2", "path": "/tmp/b2.mp4"}]},
                },
            },
        }
        app.movie_names = []
        app.movies = {}
        app._channel_show = {1: "Alpha", 2: "Bravo"}
        app.config["home_menu"] = {
            "parent": ["shows", "movies", "weather", "1990s"],
            "kids": ["shows", "movies", "weather"],
        }
        app.config["features"] = {
            "weather": True,
            "retro_tv": True,
            "youtube": True,
        }
        return app

    def test_resolved_home_rows_default_weather_and_decade(self):
        app = self._app()
        rows = app._resolved_home_rows()
        kinds = [r["kind"] for r in rows]
        self.assertIn("shows", kinds)
        self.assertIn("weather", kinds)
        self.assertIn("retro", kinds)
        self.assertNotIn("movies", kinds)  # empty movie library + legacy layout
        self.assertTrue(app._uses_home_menu())

    def test_weather_omitted_when_feature_disabled(self):
        app = self._app()
        app.config["features"]["weather"] = False
        app.config["home_menu"]["parent"] = ["shows", "weather"]
        kinds = [r["kind"] for r in app._resolved_home_rows()]
        self.assertEqual(kinds, ["shows"])
        self.assertFalse(app._uses_home_menu())

    def test_kids_home_includes_weather_not_decade_unless_pinned(self):
        app = self._app()
        app._kids_mode_active = True
        kinds = [r["kind"] for r in app._resolved_home_rows()]
        self.assertIn("shows", kinds)
        self.assertIn("weather", kinds)
        self.assertNotIn("retro", kinds)

    def test_activate_home_weather_row(self):
        app = self._app()
        weather = next(r for r in app._resolved_home_rows() if r["kind"] == "weather")
        with patch.object(app, "_enter_weather_channel") as enter:
            app._activate_home_row(weather)
        enter.assert_called_once()

    def test_activate_home_retro_row(self):
        app = self._app()
        retro = next(r for r in app._resolved_home_rows() if r["kind"] == "retro")
        with patch.object(app, "_enter_retro_tv") as enter:
            app._activate_home_row(retro)
        enter.assert_called_once_with("90", year_digits="1990")

    def test_go_back_from_show_list_to_home(self):
        app = self._app()
        app.view = app.SHOW_LIST
        app.cursor = 0
        self.assertTrue(app.go_back())
        self.assertEqual(app.view, app.LIBRARY_SELECT)

    def test_esc_hierarchy_quit_only_at_home(self):
        app = self._app()
        app.view = app.SHOW_LIST
        with patch.object(app, "_enter_confirm_exit") as quit_dlg:
            app._process_browse_action("back")
        quit_dlg.assert_not_called()
        self.assertEqual(app.view, app.LIBRARY_SELECT)

        with patch.object(app, "_enter_confirm_exit") as quit_dlg:
            app._process_browse_action("back")
        quit_dlg.assert_called_once()

    def test_secret_dial_allowed_on_playing(self):
        app = self._app()
        app.view = app.PLAYING
        self.assertTrue(app._secret_dial_allowed())
        app._kids_mode_active = True
        self.assertFalse(app._secret_dial_allowed())

    def test_playback_dial_0_exits_to_episode_list(self):
        app = self._app()
        app.view = app.PLAYING
        app.playing_show = "Alpha"
        app.playing_season = 1
        app.cur_show = "Alpha"
        app.cur_season = 1
        app.playing_episodes = app.shows["Alpha"]["seasons"][1]["episodes"]
        app.playing_index = 0
        app.playing_episode = app.playing_episodes[0]
        app.player = FakePlayer()
        app._autoplay_countdown = 5
        with patch.object(app, "_exit_playback_display"):
            app.channel_digits = "0"
            app.channel_timer = 1
            with patch(
                "pygame.time.get_ticks", return_value=1 + CHANNEL_TIMEOUT_MS
            ):
                app._tick_dial_timeout()
        self.assertEqual(app.view, app.EPISODE_SELECT)
        self.assertIsNone(app.player)

    def test_playback_channel_switch_opens_nested_list(self):
        app = self._app()
        app.view = app.PLAYING
        app.playing_show = "Alpha"
        app.playing_season = 1
        app.cur_show = "Alpha"
        app.cur_season = 1
        app.playing_episodes = app.shows["Alpha"]["seasons"][1]["episodes"]
        app.playing_index = 0
        app.playing_episode = app.playing_episodes[0]
        app.player = FakePlayer()
        app._playing_is_movie = False
        app._autoplay_countdown = 0  # skip splash
        with patch.object(app, "_exit_playback_display"):
            app._playback_channel_switch(2)
        # Bravo uses season browser
        self.assertEqual(app.view, app.SEASON_SELECT)
        self.assertEqual(app.cur_show, "Bravo")

    def test_playback_channel_switch_cancel_keeps_playing(self):
        app = self._app()
        app.view = app.PLAYING
        app.playing_show = "Alpha"
        app.playing_season = 1
        app.cur_show = "Alpha"
        app.cur_season = 1
        app.playing_episodes = app.shows["Alpha"]["seasons"][1]["episodes"]
        app.playing_index = 0
        app.playing_episode = app.playing_episodes[0]
        app.player = FakePlayer()
        app._autoplay_countdown = 5
        with patch.object(app, "_run_channel_switch_countdown", return_value=False):
            app._playback_channel_switch(2)
        self.assertEqual(app.view, app.PLAYING)
        self.assertIsNotNone(app.player)

    def test_open_show_nested_list_skips_season_when_single(self):
        app = self._app()
        app._open_show_nested_list("Alpha")
        self.assertEqual(app.view, app.EPISODE_SELECT)
        self.assertEqual(app.cur_season, 1)


class PlaybackDialCommitTests(unittest.TestCase):
    """Update playback digit semantics: dial buffer, not instant back on 0."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _playing_app(self) -> TVTimeCapsule:
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app.shows = {
            "Show": {
                "seasons": {
                    1: {"episodes": [{"number": 1, "name": "E1", "path": "/tmp/e.mp4"}]}
                }
            }
        }
        app.show_names = ["Show"]
        app.cur_show = "Show"
        app.cur_season = 1
        app.view = app.PLAYING
        app.playing_show = "Show"
        app.playing_season = 1
        app.playing_episodes = app.shows["Show"]["seasons"][1]["episodes"]
        app.playing_index = 0
        app.playing_episode = app.playing_episodes[0]
        app.player = FakePlayer()
        return app

    def test_commit_dial_0_stops_playback(self):
        app = self._playing_app()
        with patch.object(app, "_exit_playback_display"):
            app.channel_digits = "0"
            app._commit_dial_digits(immediate=True)
        self.assertEqual(app.view, app.EPISODE_SELECT)
        self.assertIsNone(app.player)

    def test_digit_1_is_not_playback_back_action(self):
        app = self._playing_app()
        self.assertIsNone(app._key_to_playback_action(pygame.K_1))
        app._append_dial_digit(1)
        self.assertEqual(app.channel_digits, "1")
        self.assertEqual(app.view, app.PLAYING)
        self.assertIsNotNone(app.player)


if __name__ == "__main__":
    unittest.main()
