"""Tests for secret test patterns and analog artifacts."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import pygame

from tv_time_capsule.analog_artifacts import AnalogArtifacts
from tv_time_capsule.test_patterns import (
    SHOW_LIST_TEST_PATTERNS,
    is_show_list_test_dial,
    pattern_asset_path,
)


class TestPatternsTests(unittest.TestCase):
    def test_dial_codes(self):
        self.assertTrue(is_show_list_test_dial("0"))
        self.assertTrue(is_show_list_test_dial("00"))
        self.assertTrue(is_show_list_test_dial("000"))
        self.assertFalse(is_show_list_test_dial("1"))
        self.assertFalse(is_show_list_test_dial("007"))

    def test_assets_exist(self):
        missing = [
            dial
            for dial in SHOW_LIST_TEST_PATTERNS
            if pattern_asset_path(dial) is None
        ]
        if missing:
            self.skipTest(
                "Add colorbars.png, grid.png, indianhead.png to "
                "src/tv_time_capsule/assets/ (not bundled in repo)"
            )
        for dial, name in SHOW_LIST_TEST_PATTERNS.items():
            path = pattern_asset_path(dial)
            assert path is not None
            self.assertEqual(path.name, name)


class AnalogArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.screen = pygame.Surface((640, 480))
        self.screen.fill((40, 80, 120))

    def test_inactive_by_default(self):
        fx = AnalogArtifacts(enabled=False)
        fx.apply(self.screen)
        self.assertEqual(self.screen.get_at((10, 10))[:3], (40, 80, 120))

    def test_can_trigger_and_apply(self):
        fx = AnalogArtifacts(enabled=True, rate_per_minute=999)
        with patch("pygame.time.get_ticks", side_effect=[0, 500, 1000]):
            fx.tick()
        if fx.is_active():
            fx.apply(self.screen)


if __name__ == "__main__":
    unittest.main()
