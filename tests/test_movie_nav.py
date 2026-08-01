"""Tests for movie list letter-jump navigation."""

from __future__ import annotations

import os
import unittest

import pygame

from tv_time_capsule.app import TVTimeCapsule, FOOTER_BAR_H
from tv_time_capsule.config import C
from tv_time_capsule.movie_nav import jump_to_letter, letter_bucket


class MovieNavTests(unittest.TestCase):
    def test_letter_bucket(self):
        self.assertEqual(letter_bucket("Alpha"), "A")
        self.assertEqual(letter_bucket("beta"), "B")
        self.assertEqual(letter_bucket("123 Start"), "#")
        self.assertEqual(letter_bucket(""), "#")
        self.assertEqual(letter_bucket("  Zulu"), "Z")

    def test_jump_to_next_letter(self):
        titles = ["Alpha", "Apple", "Beta", "Zulu"]
        self.assertEqual(jump_to_letter(titles, 0, 1), 2)
        self.assertEqual(jump_to_letter(titles, 1, 1), 2)
        self.assertEqual(jump_to_letter(titles, 2, 1), 3)

    def test_jump_to_previous_letter(self):
        titles = ["Alpha", "Beta", "Zulu"]
        self.assertEqual(jump_to_letter(titles, 2, -1), 1)
        self.assertEqual(jump_to_letter(titles, 1, -1), 0)

    def test_jump_clamps_at_ends(self):
        titles = ["Alpha", "Beta"]
        self.assertEqual(jump_to_letter(titles, 0, -1), 0)
        self.assertEqual(jump_to_letter(titles, 1, 1), 1)

    def test_hash_bucket_grouped(self):
        titles = ["Alpha", "123 Movie", "456 Other", "Beta"]
        self.assertEqual(jump_to_letter(titles, 0, 1), 1)
        self.assertEqual(jump_to_letter(titles, 2, 1), 3)

    def test_movie_browser_footer_shows_clock_and_help(self):
        """Movie browser status bar shows clock (left) and help (right)."""
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.view = app.MOVIE_LIST
        if not app.movie_names:
            app.movie_names = ["Test Movie"]
            app.movies = {"Test Movie": {"title": "Test Movie"}}
        app._footer_hints_enabled = True
        app._kids_mode_active = False

        with app._ui_layout(letterbox=False):
            app.draw_movie_browser()
            buf = app.screen
            fy = buf.get_height() - FOOTER_BAR_H + FOOTER_BAR_H // 2
            bar_color = C.BG_FOOTER
            text_cols = [
                x
                for x in range(buf.get_width())
                if buf.get_at((x, fy))[:3] != bar_color[:3]
            ]
            self.assertTrue(text_cols, "expected footer text")
            left = min(text_cols)
            right = max(text_cols)
            self.assertLess(left, buf.get_width() // 3)
            self.assertGreater(right, (2 * buf.get_width()) // 3)

    def test_footer_hints_hidden_when_disabled(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._footer_hints_enabled = False
        layout = app._show_browser_layout(48, kids=False)
        self.assertEqual(layout["footer_h"], 0)

        with app._ui_layout(letterbox=False):
            app.screen.fill(C.BG)
            app._draw_footer()
            fy = app.sh - FOOTER_BAR_H
            self.assertEqual(app.screen.get_at((10, fy))[:3], C.BG[:3])

    def test_help_starts_on_context_page(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.view = app.EPISODE_SELECT
        titles = [title for title, _ in app._help_pages()]
        self.assertIn("Episodes", titles)
        self.assertEqual(titles[app._help_page_index_for_view()], "Episodes")
        app.view = app.MOVIE_LIST
        self.assertEqual(titles[app._help_page_index_for_view()], "Movies")

    def test_help_defaults_to_last_input_device(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        self.assertEqual(app._help_input_device(), "keyboard")
        app._gamepad_count = 1
        app._note_gamepad_input()
        self.assertEqual(app._help_input_device(), "gamepad")
        app._note_keyboard_input()
        self.assertEqual(app._help_input_device(), "keyboard")

    def test_help_pages_switch_keyboard_vs_gamepad_bindings(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._gamepad_count = 1
        kb_pages = dict(app._help_pages(device="keyboard"))
        pad_pages = dict(app._help_pages(device="gamepad"))
        kb_overview = dict(kb_pages["Overview"])
        pad_overview = dict(pad_pages["Overview"])
        self.assertNotEqual(kb_overview["open this help"], pad_overview["open this help"])
        self.assertIn("keyboard only", pad_overview["kids / parent mode"])
        self.assertIn("channel / index", kb_overview)
        self.assertIn("channel / page codes", pad_overview)

if __name__ == "__main__":
    unittest.main()
