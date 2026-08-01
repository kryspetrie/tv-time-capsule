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

    def test_boolean_flags_enable(self):
        args = self.parser.parse_args(
            [
                "--channel-snow",
                "--shutdown-collapse",
                "--analog-artifacts",
                "--screensaver",
                "--admin",
            ]
        )
        self.assertTrue(args.channel_snow)
        self.assertTrue(args.shutdown_collapse)
        self.assertTrue(args.analog_artifacts)
        self.assertTrue(args.screensaver)
        self.assertTrue(args.admin)

    def test_boolean_flags_disable(self):
        args = self.parser.parse_args(
            [
                "--no-channel-snow",
                "--no-shutdown-collapse",
                "--no-analog-artifacts",
                "--no-screensaver",
                "--no-admin",
            ]
        )
        self.assertFalse(args.channel_snow)
        self.assertFalse(args.shutdown_collapse)
        self.assertFalse(args.analog_artifacts)
        self.assertFalse(args.screensaver)
        self.assertFalse(args.admin)


if __name__ == "__main__":
    unittest.main()
