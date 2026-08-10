"""Unit tests for watch-state persistence logic."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tv_time_capsule import state


class StateTests(unittest.TestCase):
    @patch.object(state, "save_state")
    def test_mark_and_query_watched_episode(self, _save):
        s = {}
        state.mark_episode_watched(s, "Bluey", 1, 3)
        self.assertTrue(state.is_episode_watched(s, "Bluey", 1, 3))
        self.assertFalse(state.is_episode_watched(s, "Bluey", 1, 1))
        self.assertEqual(state.get_watched_episodes(s, "Bluey", 1), {3})

    @patch.object(state, "save_state")
    def test_out_of_order_watched_episodes(self, _save):
        s = {}
        state.mark_episode_watched(s, "Bluey", 1, 5)
        state.mark_episode_watched(s, "Bluey", 1, 2)
        self.assertEqual(state.get_watched_episodes(s, "Bluey", 1), {2, 5})

    @patch.object(state, "save_state")
    def test_episode_position_near_end_counts_completed(self, _save):
        s = {}
        result = state.set_episode_position(s, "Bluey", 1, 2, 118.0, duration=120.0)
        self.assertEqual(result, "completed")
        self.assertTrue(state.is_episode_watched(s, "Bluey", 1, 2))
        self.assertEqual(state.get_episode_position(s, "Bluey", 1), (None, 0.0))

    @patch.object(state, "save_state")
    def test_episode_position_bookmark(self, _save):
        s = {}
        result = state.set_episode_position(s, "Bluey", 1, 2, 45.0, duration=120.0)
        self.assertEqual(result, "saved")
        ep, secs = state.get_episode_position(s, "Bluey", 1)
        self.assertEqual(ep, 2)
        self.assertAlmostEqual(secs, 45.0)

    @patch.object(state, "save_state")
    def test_reset_episode_progress(self, _save):
        s = {"Bluey": {"s01": {"watched": [2, 3], "pos_ep": 3, "pos": 30.0}}}
        changed = state.reset_episode_progress(s, "Bluey", 1, 3)
        self.assertTrue(changed)
        self.assertFalse(state.is_episode_watched(s, "Bluey", 1, 3))
        self.assertTrue(state.is_episode_watched(s, "Bluey", 1, 2))
        self.assertEqual(state.get_episode_position(s, "Bluey", 1), (None, 0.0))

    @patch.object(state, "save_state")
    def test_reset_episode_does_not_clear_other_watched(self, _save):
        s = {"Bluey": {"s01": {"watched": [1, 3]}}}
        changed = state.reset_episode_progress(s, "Bluey", 1, 1)
        self.assertTrue(changed)
        self.assertFalse(state.is_episode_watched(s, "Bluey", 1, 1))
        self.assertTrue(state.is_episode_watched(s, "Bluey", 1, 3))

    @patch.object(state, "save_state")
    def test_reset_episode_clears_bookmark_only_for_next_up(self, _save):
        s = {"Bluey": {"s01": {"watched": [2], "pos_ep": 3, "pos": 45.0}}}
        changed = state.reset_episode_progress(s, "Bluey", 1, 3)
        self.assertTrue(changed)
        self.assertTrue(state.is_episode_watched(s, "Bluey", 1, 2))
        self.assertEqual(state.get_episode_position(s, "Bluey", 1), (None, 0.0))

    @patch.object(state, "save_state")
    def test_legacy_ep_field_migrates_on_read(self, _save):
        s = {"Bluey": {"s01": {"ep": 3}}}
        self.assertEqual(state.get_watched_episodes(s, "Bluey", 1), {1, 2, 3})
        state.mark_episode_watched(s, "Bluey", 1, 5)
        entry = s["Bluey"]["s01"]
        self.assertNotIn("ep", entry)
        self.assertEqual(set(entry["watched"]), {1, 2, 3, 5})

    @patch.object(state, "save_state")
    def test_clear_resume_ep_entire_show(self, _save):
        s = {"Bluey": {"s01": {"watched": [2]}, "s02": {"watched": [1]}}}
        self.assertTrue(state.clear_resume_ep(s, "Bluey", season=None))
        self.assertNotIn("Bluey", s)

    def test_watch_summary_excludes_keymap(self):
        raw = {
            "keymap": {"up": 1073741906},
            "Bluey": {"s01": {"watched": [2]}},
            "note": "ignored",
        }
        summary = state.watch_summary(raw)
        self.assertNotIn("keymap", summary)
        self.assertNotIn("note", summary)
        self.assertEqual(summary["Bluey"]["s01"]["watched"], [2])

    @patch.object(state, "save_state")
    def test_youtube_watched_by_id(self, _save):
        s = {}
        ep = {"number": 1, "youtube_id": "dQw4w9WgXcQ", "path": "youtube:dQw4w9WgXcQ"}
        state.mark_episode_watched(s, "Ghostwriter", 1, 1, episode=ep)
        entry = s["Ghostwriter"]["s01"]
        self.assertEqual(entry["watched_ids"], ["dQw4w9WgXcQ"])
        self.assertNotIn("watched", entry)
        self.assertTrue(
            state.is_episode_watched(s, "Ghostwriter", 1, 1, episode=ep)
        )
        # Same video, different episode number after reorder.
        reordered = {"number": 5, "youtube_id": "dQw4w9WgXcQ"}
        self.assertTrue(
            state.is_episode_watched(s, "Ghostwriter", 1, 5, episode=reordered)
        )
        episodes = [
            {"number": 1, "youtube_id": "aaaaaaaaaaa"},
            {"number": 2, "youtube_id": "dQw4w9WgXcQ"},
        ]
        self.assertEqual(
            state.get_watched_episodes(s, "Ghostwriter", 1, episodes=episodes),
            {2},
        )

    @patch.object(state, "save_state")
    def test_youtube_resume_follows_id_after_reorder(self, _save):
        s = {}
        ep = {"number": 1, "youtube_id": "dQw4w9WgXcQ"}
        result = state.set_episode_position(
            s, "Ghostwriter", 1, 1, 45.0, duration=120.0, episode=ep
        )
        self.assertEqual(result, "saved")
        entry = s["Ghostwriter"]["s01"]
        self.assertEqual(entry["pos_id"], "dQw4w9WgXcQ")
        self.assertEqual(entry["pos_ep"], 1)
        reordered = [
            {"number": 1, "youtube_id": "bbbbbbbbbbb"},
            {"number": 3, "youtube_id": "dQw4w9WgXcQ"},
        ]
        pos_ep, secs = state.get_episode_position(
            s, "Ghostwriter", 1, episodes=reordered
        )
        self.assertEqual(pos_ep, 3)
        self.assertAlmostEqual(secs, 45.0)
        self.assertTrue(state.season_has_in_progress(s, "Ghostwriter", 1))

    @patch.object(state, "save_state")
    def test_youtube_near_end_marks_watched_id(self, _save):
        s = {}
        ep = {"number": 2, "youtube_id": "dQw4w9WgXcQ"}
        result = state.set_episode_position(
            s, "Ghostwriter", 1, 2, 118.0, duration=120.0, episode=ep
        )
        self.assertEqual(result, "completed")
        self.assertEqual(s["Ghostwriter"]["s01"]["watched_ids"], ["dQw4w9WgXcQ"])
        self.assertEqual(
            state.get_episode_position(s, "Ghostwriter", 1, episodes=[ep]),
            (None, 0.0),
        )

    @patch.object(state, "save_state")
    def test_youtube_reset_clears_id(self, _save):
        s = {
            "Ghostwriter": {
                "s01": {
                    "watched_ids": ["dQw4w9WgXcQ", "aaaaaaaaaaa"],
                    "pos_id": "dQw4w9WgXcQ",
                    "pos_ep": 1,
                    "pos": 30.0,
                }
            }
        }
        ep = {"number": 1, "youtube_id": "dQw4w9WgXcQ"}
        changed = state.reset_episode_progress(
            s, "Ghostwriter", 1, 1, episode=ep
        )
        self.assertTrue(changed)
        entry = s["Ghostwriter"]["s01"]
        self.assertEqual(entry["watched_ids"], ["aaaaaaaaaaa"])
        self.assertNotIn("pos_id", entry)
        self.assertNotIn("pos", entry)

    @patch.object(state, "save_state")
    def test_clear_resume_positions_keeps_watched(self, _save):
        s = {}
        state.mark_episode_watched(s, "Bluey", 1, 2)
        state.set_episode_position(s, "Bluey", 1, 3, 40.0, duration=120.0)
        self.assertTrue(state.clear_resume_positions(s, "Bluey", season=None))
        self.assertTrue(state.is_episode_watched(s, "Bluey", 1, 2))
        self.assertEqual(state.get_episode_position(s, "Bluey", 1), (None, 0.0))


if __name__ == "__main__":
    unittest.main()
