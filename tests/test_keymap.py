"""Tests for key display names."""

from __future__ import annotations

import unittest

import pygame

from tv_time_capsule.keymap import DEFAULT_KEYMAP, key_display_name, keymap_for_display


class KeymapDisplayTests(unittest.TestCase):
    def test_arrow_keys(self):
        self.assertEqual(key_display_name(pygame.K_UP), "<up>")
        self.assertEqual(key_display_name(pygame.K_DOWN), "<down>")
        self.assertEqual(key_display_name(pygame.K_LEFT), "<left-arrow>")
        self.assertEqual(key_display_name(pygame.K_RIGHT), "<right-arrow>")

    def test_common_keys(self):
        self.assertEqual(key_display_name(pygame.K_ESCAPE), "<escape>")
        self.assertEqual(key_display_name(pygame.K_r), "r")

    def test_keymap_for_display(self):
        rows = keymap_for_display(DEFAULT_KEYMAP)
        self.assertEqual(len(rows), 7)
        up_row = next(r for r in rows if r["action"] == "up")
        self.assertEqual(up_row["key"], "<up>")


if __name__ == "__main__":
    unittest.main()
