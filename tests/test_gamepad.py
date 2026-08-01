"""Tests for configurable gamepad bindings."""

from __future__ import annotations

import unittest

import pygame

from tv_time_capsule.gamepad import (
    DEFAULT_GAMEPAD_BINDINGS,
    GamepadHandler,
    add_gamepad_binding,
    binding_display_name,
    build_gamepad_lookup,
    load_gamepad_bindings,
    remove_gamepad_binding,
    serialize_gamepad_bindings,
)


class GamepadBindingTests(unittest.TestCase):
    def test_default_bindings(self):
        bindings = load_gamepad_bindings({})
        self.assertIn("button-0", bindings["select"])
        self.assertIn("hat-up", bindings["up"])

    def test_load_custom_bindings(self):
        bindings = load_gamepad_bindings(
            {"gamepad": {"bindings": {"select": ["button-3"]}}}
        )
        self.assertEqual(bindings["select"], ["button-3"])

    def test_serialize_human_readable(self):
        bindings = load_gamepad_bindings({})
        self.assertEqual(serialize_gamepad_bindings(bindings), {})
        add_gamepad_binding(bindings, "select", "button-3")
        saved = serialize_gamepad_bindings(bindings)
        self.assertEqual(saved["select"], ["button-3"])

    def test_add_moves_token_between_actions(self):
        bindings = load_gamepad_bindings({})
        add_gamepad_binding(bindings, "back", "button-0")
        self.assertEqual(bindings["back"], ["button-0"])
        self.assertNotIn("button-0", bindings["select"])

    def test_remove_keeps_at_least_one(self):
        bindings = load_gamepad_bindings(
            {"gamepad": {"bindings": {"back": ["button-1", "button-6"]}}}
        )
        remove_gamepad_binding(bindings, "back", "button-6")
        self.assertEqual(bindings["back"], ["button-1"])
        remove_gamepad_binding(bindings, "back", "button-1")
        self.assertEqual(bindings["back"], ["button-1"])

    def test_binding_display_name(self):
        self.assertIn("D-pad", binding_display_name("hat-up"))
        self.assertIn("Button 5", binding_display_name("button-5"))

    def test_event_to_action_uses_lookup(self):
        bindings = dict(DEFAULT_GAMEPAD_BINDINGS)
        bindings["select"] = ["button-3"]
        handler = GamepadHandler(enabled=True, bindings=bindings)
        lookup = build_gamepad_lookup(bindings)
        self.assertEqual(lookup["button-3"], "select")
        event = pygame.event.Event(pygame.JOYBUTTONDOWN, button=3, joy=0)
        self.assertEqual(handler.event_to_action(event), "select")


if __name__ == "__main__":
    unittest.main()
