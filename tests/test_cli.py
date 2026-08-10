"""CLI argument parsing tests."""

from __future__ import annotations

import unittest

from tv_time_capsule.cli import build_parser


class CliParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_boolean_flags_default_to_none(self):
        args = self.parser.parse_args([])
        self.assertIsNone(args.channel_snow)
        self.assertIsNone(args.shutdown_collapse)
        self.assertIsNone(args.analog_artifacts)
        self.assertIsNone(args.screensaver)
        self.assertIsNone(args.admin)
        self.assertIsNone(args.youtube_idle_cache)

    def test_boolean_flags_enable(self):
        args = self.parser.parse_args(
            [
                "--channel-snow",
                "--shutdown-collapse",
                "--analog-artifacts",
                "--screensaver",
                "--admin",
                "--youtube-idle-cache",
            ]
        )
        self.assertTrue(args.channel_snow)
        self.assertTrue(args.shutdown_collapse)
        self.assertTrue(args.analog_artifacts)
        self.assertTrue(args.screensaver)
        self.assertTrue(args.admin)
        self.assertTrue(args.youtube_idle_cache)

    def test_boolean_flags_disable(self):
        args = self.parser.parse_args(
            [
                "--no-channel-snow",
                "--no-shutdown-collapse",
                "--no-analog-artifacts",
                "--no-screensaver",
                "--no-admin",
                "--no-youtube-idle-cache",
            ]
        )
        self.assertFalse(args.channel_snow)
        self.assertFalse(args.shutdown_collapse)
        self.assertFalse(args.analog_artifacts)
        self.assertFalse(args.screensaver)
        self.assertFalse(args.admin)
        self.assertFalse(args.youtube_idle_cache)

    def test_scale_choices(self):
        self.assertIsNone(self.parser.parse_args([]).scale)
        for n in (2, 3, 4, 5, 6):
            with self.subTest(scale=n):
                args = self.parser.parse_args(["--scale", str(n)])
                self.assertEqual(args.scale, n)

    def test_scale_rejects_out_of_range(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--scale", "1"])
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--scale", "7"])

    def test_youtube_cache_sync_flag(self):
        args = self.parser.parse_args(["--youtube-cache-sync"])
        self.assertTrue(args.youtube_cache_sync)
        self.assertFalse(self.parser.parse_args([]).youtube_cache_sync)


if __name__ == "__main__":
    unittest.main()
