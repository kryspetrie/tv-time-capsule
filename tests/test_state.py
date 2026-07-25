"""Unit tests for watch-state persistence logic."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tv_time_capsule import state


class StateTests(unittest.TestCase):
    @patch.object(state, "save_state")
    def test_set_and_get_resume_ep(self, _save):
        s = {}
        state.set_resume_ep(s, "Bluey", 1, 3)
        self.assertEqual(state.get_resume_ep(s, "Bluey", 1), 3)

    @patch.object(state, "save_state")
    def test_episode_position_near_end_counts_completed(self, _save):
        s = {}
        result = state.set_episode_position(s, "Bluey", 1, 2, 118.0, duration=120.0)
        self.assertEqual(result, "completed")
        self.assertEqual(state.get_resume_ep(s, "Bluey", 1), 2)
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
        s = {"Bluey": {"s01": {"ep": 3, "pos_ep": 3, "pos": 30.0}}}
        changed = state.reset_episode_progress(s, "Bluey", 1, 3)
        self.assertTrue(changed)
        self.assertEqual(state.get_resume_ep(s, "Bluey", 1), 2)
        self.assertEqual(state.get_episode_position(s, "Bluey", 1), (None, 0.0))

    @patch.object(state, "save_state")
    def test_clear_resume_ep_entire_show(self, _save):
        s = {"Bluey": {"s01": {"ep": 2}, "s02": {"ep": 1}}}
        self.assertTrue(state.clear_resume_ep(s, "Bluey", season=None))
        self.assertNotIn("Bluey", s)

    def test_watch_summary_excludes_keymap(self):
        raw = {
            "keymap": {"up": 1073741906},
            "Bluey": {"s01": {"ep": 2}},
            "note": "ignored",
        }
        summary = state.watch_summary(raw)
        self.assertNotIn("keymap", summary)
        self.assertNotIn("note", summary)
        self.assertEqual(summary["Bluey"]["s01"]["ep"], 2)


if __name__ == "__main__":
    unittest.main()
