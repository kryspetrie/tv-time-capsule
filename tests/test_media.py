"""Unit tests for media discovery helpers."""

from __future__ import annotations

import unittest

from tv_time_capsule.media import (
    folder_season_info,
    parse_episode_name,
    parse_episode_number,
    parse_season_episode,
)


class MediaParseTests(unittest.TestCase):
    def test_parse_season_episode(self):
        self.assertEqual(parse_season_episode("s01e03 - Dance.mp4"), (1, 3))
        self.assertEqual(parse_season_episode("S02E11.mkv"), (2, 11))
        self.assertEqual(parse_season_episode("plain.mp4"), (None, None))

    def test_parse_episode_number(self):
        self.assertEqual(parse_episode_number("s01e05.mp4"), 5)
        self.assertEqual(parse_episode_number("03-intro.mp4"), 3)

    def test_parse_episode_name(self):
        self.assertEqual(parse_episode_name("s01e01 - Dancing.mp4"), "Dancing")
        self.assertEqual(parse_episode_name("02 - Swim.mp4"), "Swim")

    def test_folder_season_info(self):
        self.assertEqual(folder_season_info("s01", 1), (1, None))
        self.assertEqual(folder_season_info("Season 2", 1), (2, None))
        self.assertEqual(folder_season_info("Action", 3), (3, "Action"))


if __name__ == "__main__":
    unittest.main()
