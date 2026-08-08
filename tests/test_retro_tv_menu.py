"""Tests for Retro TV two-level menu stage machine."""

from __future__ import annotations

import unittest

from tv_time_capsule.retro_tv_menu import (
    MenuCommand,
    MenuStage,
    RetroTvMenu,
    setup_rows,
)


_FILTERS = [
    {"id": "box_c", "name": "Cartoons", "on": True},
    {"id": "box_s", "name": "Comedy", "on": False},
]


class RetroTvMenuTests(unittest.TestCase):
    def test_open_focuses_change_channel(self):
        menu = RetroTvMenu()
        menu.open()
        self.assertTrue(menu.is_open)
        self.assertEqual(menu.stage, MenuStage.ROOT)
        self.assertEqual(menu.cursor, 0)
        self.assertEqual(menu.rows()[0][0], "change")

    def test_select_change_channel_closes_and_commands(self):
        menu = RetroTvMenu()
        menu.open()
        cmds = menu.handle("select")
        self.assertEqual(cmds, [MenuCommand("change_channel")])
        self.assertFalse(menu.is_open)

    def test_open_setup_then_esc_returns_to_root(self):
        menu = RetroTvMenu()
        menu.open()
        menu.handle("down")
        cmds = menu.handle("select")
        self.assertEqual(cmds, [])
        self.assertEqual(menu.stage, MenuStage.SETUP)
        self.assertEqual(menu.cursor, 0)
        cmds = menu.handle("back", _FILTERS)
        self.assertEqual(cmds, [])
        self.assertEqual(menu.stage, MenuStage.ROOT)
        self.assertEqual(menu.cursor, 1)

    def test_esc_from_root_closes(self):
        menu = RetroTvMenu()
        menu.open()
        cmds = menu.handle("back")
        self.assertEqual(cmds, [MenuCommand("close")])
        self.assertFalse(menu.is_open)

    def test_setup_toggle_and_all_none(self):
        menu = RetroTvMenu()
        menu.open()
        menu.handle("down")
        menu.handle("select")
        self.assertEqual(menu.stage, MenuStage.SETUP)
        # cursor 0 = Select All
        self.assertEqual(menu.handle("select", _FILTERS), [MenuCommand("select_all")])
        menu.handle("down", _FILTERS)
        self.assertEqual(
            menu.handle("select", _FILTERS), [MenuCommand("select_none")]
        )
        menu.handle("down", _FILTERS)  # box_c
        self.assertEqual(
            menu.handle("select", _FILTERS),
            [MenuCommand("toggle_filter", filter_id="box_c")],
        )

    def test_setup_rows_include_filters(self):
        rows = setup_rows(_FILTERS)
        self.assertEqual(rows[0][0], "all")
        self.assertEqual(rows[1][0], "none")
        self.assertEqual(rows[2], ("box_c", "Cartoons", True))
        self.assertEqual(rows[3], ("box_s", "Comedy", False))


if __name__ == "__main__":
    unittest.main()
