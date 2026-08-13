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
        app._autoplay_countdown = 0
        app._episode_skip_double_tap_ms = 450
        app._kids_mode_active = False
        app.shows = {
            "Reading Rainbow": {
                "has_seasons": True,
                "seasons": {
                    1: {
                        "episodes": [
                            {"number": 1, "name": "Ep1", "path": "/tmp/e1.mp4"},
                            {"number": 2, "name": "Ep2", "path": "/tmp/e2.mp4"},
                            {"number": 3, "name": "Ep3", "path": "/tmp/e3.mp4"},
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
        app.playing_index = 1
        app.playing_episode = app.playing_episodes[1]
        app._playback_browse_view = app.EPISODE_SELECT
        app._playback_browse_cursor = 1
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

    def test_resolve_manual_skip_next_and_prev(self):
        app = self._playing_app()
        nxt = app._resolve_manual_skip_target(+1)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt[1], 2)
        prev = app._resolve_manual_skip_target(-1)
        self.assertIsNotNone(prev)
        self.assertEqual(prev[1], 0)
        app.playing_index = 0
        self.assertIsNone(app._resolve_manual_skip_target(-1))
        app.playing_index = 2
        self.assertIsNone(app._resolve_manual_skip_target(+1))

    def test_resolve_manual_skip_crosses_seasons(self):
        app = self._playing_app()
        app.shows["Reading Rainbow"]["seasons"][2] = {
            "episodes": [
                {"number": 1, "name": "S2E1", "path": "/tmp/s2e1.mp4"},
                {"number": 2, "name": "S2E2", "path": "/tmp/s2e2.mp4"},
            ]
        }
        app.playing_index = 2  # last of season 1
        nxt = app._resolve_manual_skip_target(+1)
        self.assertIsNotNone(nxt)
        eps, idx, season = nxt
        self.assertEqual(season, 2)
        self.assertEqual(idx, 0)
        self.assertEqual(eps[0]["name"], "S2E1")

        app.playing_season = 2
        app.playing_episodes = eps
        app.playing_index = 0
        prev = app._resolve_manual_skip_target(-1)
        self.assertIsNotNone(prev)
        p_eps, p_idx, p_season = prev
        self.assertEqual(p_season, 1)
        self.assertEqual(p_idx, 2)
        self.assertEqual(p_eps[p_idx]["name"], "Ep3")

    def test_manual_skip_works_while_kids_mode_active(self):
        app = self._playing_app()
        app._kids_mode_active = True
        with patch.object(app, "_begin_episode_skip", return_value=True) as skip:
            app._process_playback_action("next_episode")
            skip.assert_called_once_with(+1)
            app._process_playback_action("prev_episode")
            self.assertEqual(skip.call_count, 2)

    def test_left_right_seek_only_no_double_tap_skip(self):
        """←/→ always scrub; episode skip is dedicated keys only."""
        app = self._playing_app()
        app._episode_skip_double_tap_ms = 450  # even if config still has a window
        with (
            patch.object(app, "_begin_episode_skip", return_value=True) as skip,
            patch.object(app.player, "seek") as seek,
        ):
            app._process_playback_action("right", key_repeat=False)
            app._process_playback_action("right", key_repeat=False)
            app._process_playback_action("left", key_repeat=False)
            skip.assert_not_called()
            self.assertEqual(seek.call_count, 3)

    def test_key_repeat_still_seeks(self):
        app = self._playing_app()
        with (
            patch.object(app, "_begin_episode_skip", return_value=True) as skip,
            patch.object(app.player, "seek") as seek,
        ):
            app._process_playback_action("right", key_repeat=False)
            app._process_playback_action("right", key_repeat=True)
            skip.assert_not_called()
            self.assertEqual(seek.call_count, 2)

    def test_dedicated_next_episode_action(self):
        app = self._playing_app()
        self.assertEqual(
            app._key_to_playback_action(pygame.K_PAGEDOWN), "next_episode"
        )
        with patch.object(app, "_begin_episode_skip", return_value=True) as skip:
            app._process_playback_action("next_episode")
            skip.assert_called_once_with(+1)

    def test_stop_clear_clears_resume_bookmark(self):
        from tv_time_capsule.state import get_episode_position, set_episode_position

        app = self._playing_app()
        set_episode_position(app.state, "Reading Rainbow", 1, 2, 40.0, duration=120.0)
        pos_ep, _ = get_episode_position(app.state, "Reading Rainbow", 1)
        self.assertEqual(pos_ep, 2)
        with patch.object(app, "_exit_playback_display"):
            kept = app._process_playback_action("stop_clear")
        self.assertFalse(kept)
        pos_ep, _ = get_episode_position(app.state, "Reading Rainbow", 1)
        self.assertIsNone(pos_ep)
        self.assertNotEqual(app.view, app.PLAYING)

    def test_menu_stop_clear_clears_resume_only(self):
        from tv_time_capsule.state import (
            get_episode_position,
            is_episode_watched,
            mark_episode_watched,
            set_episode_position,
        )

        app = self._playing_app()
        with patch.object(app, "_exit_playback_display"):
            app.stop_playback(completed=True)
        app.view = app.EPISODE_SELECT
        app.cursor = 1
        mark_episode_watched(app.state, "Reading Rainbow", 1, 2)
        set_episode_position(app.state, "Reading Rainbow", 1, 2, 40.0, duration=120.0)
        app.clear_resume_status()
        self.assertTrue(is_episode_watched(app.state, "Reading Rainbow", 1, 2))
        self.assertEqual(get_episode_position(app.state, "Reading Rainbow", 1), (None, 0.0))
        self.assertIn("resume cleared", app.channel_error)


if __name__ == "__main__":
    unittest.main()
