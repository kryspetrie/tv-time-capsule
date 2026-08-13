"""Tests for home_menu config tokens and defaults."""

from __future__ import annotations

import unittest

from tv_time_capsule.config import parse_config
from tv_time_capsule.home_menu import (
    DEFAULT_HOME_MENU_TOKENS,
    decade_slug_for_token,
    normalize_home_token,
    parse_home_menu,
    year_digits_for_decade_slug,
)


class HomeMenuParseTests(unittest.TestCase):
    def test_defaults_include_weather(self):
        from tv_time_capsule.home_menu import DEFAULT_KIDS_HOME_MENU_TOKENS

        hm = parse_home_menu(None)
        self.assertEqual(hm["parent"], list(DEFAULT_HOME_MENU_TOKENS))
        self.assertEqual(hm["kids"], list(DEFAULT_KIDS_HOME_MENU_TOKENS))
        self.assertIn("weather", hm["parent"])
        self.assertNotIn("weather", hm["kids"])
        self.assertEqual(hm["kids"], ["shows", "movies"])

    def test_parse_config_defaults(self):
        cfg = parse_config({})
        self.assertEqual(
            cfg["home_menu"]["parent"], ["continue", "shows", "movies", "weather", "tvguide"]
        )
        self.assertEqual(cfg["home_menu"]["kids"], ["shows", "movies"])

    def test_custom_lists_and_aliases(self):
        hm = parse_home_menu(
            {
                "parent": ["shows", "weather", "1990s", "retro:80", "004"],
                "kids": ["movies", "weather"],
            }
        )
        self.assertEqual(
            hm["parent"], ["shows", "weather", "1990s", "1980s"]
        )
        # 004 normalizes to weather; duplicate dropped
        self.assertEqual(hm["kids"], ["movies", "weather"])

    def test_normalize_tokens(self):
        self.assertEqual(normalize_home_token("SHOWS"), "shows")
        self.assertEqual(normalize_home_token("004"), "weather")
        self.assertEqual(normalize_home_token("000"), "directory")
        self.assertEqual(normalize_home_token("90s"), "1990s")
        self.assertIsNone(normalize_home_token("nope"))

    def test_decade_helpers(self):
        self.assertEqual(decade_slug_for_token("1990s"), "90")
        self.assertEqual(year_digits_for_decade_slug("90"), "1990")
        self.assertEqual(decade_slug_for_token("2000s"), "00")


if __name__ == "__main__":
    unittest.main()
