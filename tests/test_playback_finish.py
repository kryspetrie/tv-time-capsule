"""Tests for natural episode end / return to browse."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.app import TVTimeCapsule
from tv_time_capsule.keymap import digit_for_key


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


class PlaybackFinishTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))

    def _playing_app(self) -> TVTimeCapsule:
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._autoplay_mode = "off"
        app._kids_mode_active = False
        app.shows = {
            "Reading Rainbow": {
                "has_seasons": True,
                "seasons": {
                    1: {
                        "episodes": [
                            {"number": 1, "name": "Ep1", "path": "/tmp/e1.mp4"},
                        ]
                    }
                },
            }
        }
        app.show_names = ["Reading Rainbow"]
        app.cur_show = "Reading Rainbow"
        app.cur_season = 1
        app.view = app.PLAYING
        app.playing_show = "Reading Rainbow"
        app.playing_season = 1
        app.playing_episodes = app.shows["Reading Rainbow"]["seasons"][1]["episodes"]
        app.playing_index = 0
        app.playing_episode = app.playing_episodes[0]
        app._playback_browse_view = app.EPISODE_SELECT
        app._playback_browse_cursor = 0
        app.player = FakePlayer()
        app._play_input_grace_until = 0
        return app

    def test_spurious_quit_after_finish_does_not_close_app(self):
        app = self._playing_app()
        app.player.finished = True

        pygame.event.post(pygame.event.Event(pygame.QUIT))
        app._handle_episode_finished()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                app._request_quit()

        self.assertTrue(app.running)
        self.assertNotEqual(app.view, app.PLAYING)

    def test_digit_0_stops_playback_like_back(self):
        app = self._playing_app()
        self.assertEqual(digit_for_key(app.keymap, pygame.K_0), 0)
        self.assertEqual(digit_for_key(app.keymap, pygame.K_KP0), 0)

        # Esc / back still stops immediately; dial 0 commits via the dial buffer.
        with patch.object(app, "_exit_playback_display"):
            kept_playing = app._process_playback_action("back")
        self.assertFalse(kept_playing)
        self.assertIsNone(app.player)
        self.assertNotEqual(app.view, app.PLAYING)

    def test_other_digits_do_not_stop_playback(self):
        app = self._playing_app()
        self.assertEqual(digit_for_key(app.keymap, pygame.K_1), 1)
        self.assertIsNone(app._key_to_playback_action(pygame.K_1))
        app._append_dial_digit(1)
        self.assertEqual(app.channel_digits, "1")
        self.assertEqual(app.view, app.PLAYING)
        self.assertIsNotNone(app.player)

    def test_digit_0_clears_stall_and_stops(self):
        app = self._playing_app()
        app._playback_stalled = True
        app._stall_auto_retry_done = True
        action = "back"
        # Stall overlay uses back / Esc to exit.
        app._playback_stalled = False
        app._stall_auto_retry_done = False
        with patch.object(app, "_exit_playback_display"):
            app._process_playback_action("back")
        self.assertIsNone(app.player)


if __name__ == "__main__":
    unittest.main()
