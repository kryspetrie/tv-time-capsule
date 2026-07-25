"""Unit tests for channel lineup helpers."""

from __future__ import annotations

import unittest

from tv_time_capsule.channels import build_channel_lineup, show_at_channel


class ChannelLineupTests(unittest.TestCase):
    def test_alphabetical_when_no_config(self):
        ordered, show_to_ch, ch_to_show = build_channel_lineup(
            ["Zoo", "Alpha", "Beta"], None
        )
        self.assertEqual(ordered, ["Alpha", "Beta", "Zoo"])
        self.assertEqual(show_to_ch["Alpha"], 1)
        self.assertEqual(show_to_ch["Zoo"], 3)
        self.assertEqual(ch_to_show[1], "Alpha")

    def test_custom_order_and_numbers(self):
        cfg = {
            "order": ["Bluey", "Mister Rogers", "Movies"],
            "numbers": {"Bluey": 1, "Movies": 9},
        }
        shows = ["Movies", "Bluey", "Other", "Mister Rogers"]
        ordered, show_to_ch, ch_to_show = build_channel_lineup(shows, cfg)
        self.assertEqual(ordered[:3], ["Bluey", "Mister Rogers", "Movies"])
        self.assertEqual(ordered[3], "Other")
        self.assertEqual(show_to_ch["Bluey"], 1)
        self.assertEqual(show_to_ch["Mister Rogers"], 2)
        self.assertEqual(show_to_ch["Movies"], 9)
        self.assertEqual(show_to_ch["Other"], 4)
        self.assertEqual(show_at_channel(ch_to_show, 9), "Movies")
        self.assertIsNone(show_at_channel(ch_to_show, 3))

    def test_unknown_order_entries_skipped(self):
        ordered, _, _ = build_channel_lineup(
            ["Alpha"],
            {"order": ["Missing", "Alpha"]},
        )
        self.assertEqual(ordered, ["Alpha"])

    def test_empty_library(self):
        ordered, show_to_ch, ch_to_show = build_channel_lineup([], {})
        self.assertEqual(ordered, [])
        self.assertEqual(show_to_ch, {})
        self.assertEqual(ch_to_show, {})


if __name__ == "__main__":
    unittest.main()
