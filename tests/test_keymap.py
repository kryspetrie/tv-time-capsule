"""Tests for key display names and multi-key bindings."""

from __future__ import annotations

import unittest

import pygame

from tv_time_capsule.keymap import (
    DEFAULT_KEYMAP,
    KEY_ACTIONS,
    action_for_key,
    add_binding,
    config_name_to_key_code,
    digit_for_key,
    format_action_keys,
    key_code_to_config_name,
    key_display_name,
    keymap_for_display,
    load_keymap,
    remove_binding,
    serialize_keymap,
)


class KeymapDisplayTests(unittest.TestCase):
    def test_arrow_keys(self):
        self.assertEqual(key_display_name(pygame.K_UP), "<up>")
        self.assertEqual(key_display_name(pygame.K_DOWN), "<down>")
        self.assertEqual(key_display_name(pygame.K_LEFT), "<left-arrow>")
        self.assertEqual(key_display_name(pygame.K_RIGHT), "<right-arrow>")

    def test_config_names(self):
        self.assertEqual(key_code_to_config_name(pygame.K_ESCAPE), "escape")
        self.assertEqual(key_code_to_config_name(pygame.K_SPACE), "space")
        self.assertEqual(config_name_to_key_code("escape"), pygame.K_ESCAPE)
        self.assertEqual(config_name_to_key_code("esc"), pygame.K_ESCAPE)
        self.assertEqual(config_name_to_key_code("q"), pygame.K_q)

    def test_keymap_for_display(self):
        rows = keymap_for_display(DEFAULT_KEYMAP)
        self.assertEqual(len(rows), len(KEY_ACTIONS))
        up_row = next(r for r in rows if r["action"] == "up")
        self.assertEqual(up_row["key"], "up")

    def test_select_aliases(self):
        km = load_keymap({})
        self.assertIn(pygame.K_RETURN, km["select"])
        self.assertIn(pygame.K_KP_ENTER, km["select"])
        self.assertIn(pygame.K_SPACE, km["select"])
        self.assertEqual(format_action_keys(km, "select"), "enter / space")

    def test_load_legacy_single_int(self):
        km = load_keymap({"keymap": {"select": pygame.K_RETURN}})
        self.assertEqual(km["select"], [pygame.K_RETURN])

    def test_load_string_names(self):
        km = load_keymap({"keymap": {"quit": ["q", "escape"]}})
        self.assertIn(pygame.K_q, km["quit"])
        self.assertIn(pygame.K_ESCAPE, km["quit"])

    def test_add_binding_replaces_defaults(self):
        km = load_keymap({})
        self.assertGreater(len(km["select"]), 1)
        add_binding(km, "select", pygame.K_SPACE)
        self.assertEqual(km["select"], [pygame.K_SPACE])

    def test_config_override_replaces_not_merges(self):
        km = load_keymap({"keymap": {"select": ["space"]}})
        self.assertEqual(km["select"], [pygame.K_SPACE])
        self.assertIsNone(action_for_key(km, pygame.K_RETURN))
        self.assertIsNone(action_for_key(km, pygame.K_KP_ENTER))
        self.assertEqual(action_for_key(km, pygame.K_SPACE), "select")
        # Unlisted actions still use defaults.
        self.assertEqual(action_for_key(km, pygame.K_ESCAPE), "back")

    def test_add_binding_moves_key_from_other_action(self):
        km = load_keymap({})
        add_binding(km, "quit", pygame.K_ESCAPE)
        self.assertEqual(km["quit"], [pygame.K_ESCAPE])
        self.assertNotIn(pygame.K_ESCAPE, km["back"])
        self.assertEqual(km["back"], [])

    def test_remove_binding_keeps_at_least_one(self):
        km = load_keymap({"keymap": {"quit": ["q", "escape"]}})
        remove_binding(km, "quit", pygame.K_ESCAPE)
        self.assertEqual(km["quit"], [pygame.K_q])
        remove_binding(km, "quit", pygame.K_q)
        self.assertEqual(km["quit"], [pygame.K_q])

    def test_serialize_human_readable(self):
        km = load_keymap({})
        self.assertEqual(serialize_keymap(km), {})
        add_binding(km, "quit", pygame.K_ESCAPE)
        saved = serialize_keymap(km)
        self.assertEqual(saved["quit"], ["escape"])
        self.assertEqual(saved.get("back"), [])

    def test_digit_bindings(self):
        km = load_keymap({})
        self.assertEqual(digit_for_key(km, pygame.K_3), 3)
        self.assertEqual(digit_for_key(km, pygame.K_KP3), 3)
        self.assertIsNone(digit_for_key(km, pygame.K_a))

    def test_action_for_key(self):
        km = load_keymap({})
        self.assertEqual(action_for_key(km, pygame.K_h), "help")

    def test_letter_menu_and_kids_tag_defaults(self):
        km = load_keymap({})
        self.assertEqual(action_for_key(km, pygame.K_l), "letter_menu")
        self.assertEqual(action_for_key(km, pygame.K_k), "kids_tag_toggle")
        self.assertEqual(action_for_key(km, pygame.K_F5), "footer_hints_toggle")
        self.assertIn(pygame.K_l, DEFAULT_KEYMAP["letter_menu"])
        self.assertIn(pygame.K_k, DEFAULT_KEYMAP["kids_tag_toggle"])


if __name__ == "__main__":
    unittest.main()
