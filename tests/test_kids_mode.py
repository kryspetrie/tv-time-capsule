"""Tests for kid-friendly mode helpers."""

from __future__ import annotations

import os
import unittest
import unittest.mock

import pygame

from tv_time_capsule.app import TVTimeCapsule
from tv_time_capsule.config import _parse_kids_mode
from tv_time_capsule.kids_mode import kids_resume_season
from tv_time_capsule.state import get_episode_position, set_episode_position


class KidsModeTests(unittest.TestCase):
    def test_kids_resume_season_prefers_in_progress(self):
        state = {}
        set_episode_position(state, "Bluey", 2, 3, 42.0)
        season = kids_resume_season(
            state,
            "Bluey",
            [1, 2, 3],
            get_episode_position=get_episode_position,
        )
        self.assertEqual(season, 2)

    def test_kids_resume_season_defaults_to_first(self):
        state = {}
        season = kids_resume_season(
            state,
            "Bluey",
            [1, 2],
            get_episode_position=get_episode_position,
        )
        self.assertEqual(season, 1)

    def test_quit_blocked_in_kids_mode(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app.running = True
        self.assertFalse(app._quit_allowed())
        app._request_quit()
        self.assertTrue(app.running)
        app._kids_mode_active = False
        self.assertTrue(app._quit_allowed())
        app._request_quit()
        self.assertFalse(app.running)

    def test_playback_return_restores_show_list_not_library_picker(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_interleave = False
        app.library_layout = "split"
        app.view = app.SHOW_LIST
        app.cursor = 1
        app._remember_playback_browse_state()
        app.view = app.PLAYING
        self.assertEqual(app._playback_return_view(), app.SHOW_LIST)
        self.assertNotEqual(app._playback_return_view(), app.LIBRARY_SELECT)

    def test_kids_mode_enabled_persisted(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        saved = {}

        def capture_save(cfg):
            saved.update(cfg.get("kids_mode") or {})

        with unittest.mock.patch(
            "tv_time_capsule.app.save_config", side_effect=capture_save
        ):
            app._toggle_kids_mode()
        self.assertTrue(saved.get("enabled"))


class KidsLibrarySelectorTests(unittest.TestCase):
    def test_show_and_movie_thumbnail_paths(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.shows = {
            "Bluey": {"thumbnail": __file__},
            "NoArt": {"thumbnail": "/nonexistent/thumb.png"},
        }
        app.show_names = ["Bluey", "NoArt"]
        app.movies = {"Movie A": {"thumbnail": __file__}}
        app.movie_names = ["Movie A"]

        show_paths = app._show_thumbnail_paths()
        movie_paths = app._movie_thumbnail_paths()
        self.assertEqual(show_paths, [__file__])
        self.assertEqual(movie_paths, [__file__])

    def test_library_thumb_paths_stay_in_catalog(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        show_thumb = "/tmp/show-only.png"
        movie_thumb = "/tmp/movie-only.png"
        app_paths = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app_paths.shows = {"Bluey": {"thumbnail": show_thumb}}
        app_paths.show_names = ["Bluey"]
        app_paths.movies = {"Movie A": {"thumbnail": movie_thumb}}
        app_paths.movie_names = ["Movie A"]

        with unittest.mock.patch("tv_time_capsule.app.os.path.isfile", return_value=True):
            show_paths = app_paths._show_thumbnail_paths()
            movie_paths = app_paths._movie_thumbnail_paths()

        self.assertEqual(show_paths, [show_thumb])
        self.assertEqual(movie_paths, [movie_thumb])

    def test_library_thumb_slot_layout(self):
        slots, cell_w, cell_h = TVTimeCapsule._library_thumb_slot_layout(900, 200, 4)
        self.assertGreaterEqual(slots, 1)
        self.assertAlmostEqual(cell_w / cell_h, 4 / 3, places=2)

    def test_library_select_channel_jump(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app.library_layout = "split"
        app.view = app.LIBRARY_SELECT
        app.show_names = ["Bluey"]
        app.movie_names = ["Movie A"]
        app.shows = {"Bluey": {"seasons": {1: {"episodes": []}}}}
        app.movies = {"Movie A": {"path": "/tmp/m.mp4", "title": "Movie A"}}
        app._channel_fx.configure(snow=False, shutdown=False, audio=False)

        with unittest.mock.patch.object(app, "_channel_tune", side_effect=lambda fn: fn()):
            self.assertTrue(app.jump_to_channel(2))

        self.assertEqual(app.view, app.MOVIE_LIST)
        self.assertEqual(app.cursor, 0)

    def test_library_thumb_window(self):
        paths = ["a", "b", "c", "d", "e"]
        window = TVTimeCapsule._library_thumb_window(paths, 2, 4)
        self.assertEqual(window, ["c", "d", "e", "a"])

        short = TVTimeCapsule._library_thumb_window(["only"], 0, 4)
        self.assertEqual(short, ["only"])

    def test_kids_library_selector_draws(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app.library_layout = "split"
        app.view = app.LIBRARY_SELECT
        app.shows = {
            "Bluey": {"thumbnail": __file__},
            "Show2": {"thumbnail": __file__},
            "Show3": {"thumbnail": __file__},
        }
        app.show_names = ["Bluey", "Show2", "Show3"]
        app.movies = {
            "Movie A": {"thumbnail": __file__},
            "Movie B": {"thumbnail": __file__},
        }
        app.movie_names = ["Movie A", "Movie B"]
        for _ in range(30):
            app._draw_kids_library_selector()
            app._library_shows_thumb_idx += 1
            app._library_movies_thumb_idx += 1


    def test_kids_movie_list_up_down(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_allowlist = None
        app.view = app.MOVIE_LIST
        app.movie_names = ["Alpha", "Bravo", "Charlie"]
        app.movies = {k: {"title": k, "path": f"/tmp/{k}.mp4"} for k in app.movie_names}
        app.cursor = 0
        app._process_browse_action("down")
        self.assertEqual(app.cursor, 1)
        app._process_browse_action("up")
        self.assertEqual(app.cursor, 0)

    def test_parent_movie_list_up_down(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app.view = app.MOVIE_LIST
        app.movie_names = ["Alpha", "Bravo", "Charlie"]
        app.movies = {k: {"title": k, "path": f"/tmp/{k}.mp4"} for k in app.movie_names}
        app.cursor = 0
        app._process_browse_action("down")
        self.assertEqual(app.cursor, 1)
        app._process_browse_action("down")
        self.assertEqual(app.cursor, 2)
        app._process_browse_action("up")
        self.assertEqual(app.cursor, 1)

    def test_spurious_quit_grace(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app._arm_quit_grace(5000)
        app._handle_quit_event("browse")
        self.assertTrue(app.running)
        app._ignore_quit_until_ms = 0
        app._handle_quit_event("browse")
        self.assertFalse(app.running)


class KidsViewToggleTests(unittest.TestCase):
    def test_browse_style_defaults_to_card(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        self.assertEqual(app._kids_browse_style, "card")

    def test_browse_style_compact_legacy_alias(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.config["kids_mode"] = {"browse_style": "compact"}
        app._load_kids_mode_config()
        self.assertEqual(app._kids_browse_style, "card")

    def test_browse_style_full(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.config["kids_mode"] = {"browse_style": "full"}
        app._load_kids_mode_config()
        self.assertEqual(app._kids_browse_style, "full")

    def test_browse_style_invalid_falls_back_to_card(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.config["kids_mode"] = {"browse_style": "garbage"}
        app._load_kids_mode_config()
        self.assertEqual(app._kids_browse_style, "card")

    def test_toggle_kids_view_cycles_card_to_full(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "card"
        saved = {}

        def capture_save(cfg):
            saved.update(cfg.get("kids_mode") or {})

        with unittest.mock.patch(
            "tv_time_capsule.app.save_config", side_effect=capture_save
        ):
            app._toggle_kids_view()
        self.assertEqual(app._kids_browse_style, "full")
        self.assertEqual(saved.get("browse_style"), "full")

    def test_toggle_kids_view_cycles_full_to_card(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "full"
        saved = {}

        def capture_save(cfg):
            saved.update(cfg.get("kids_mode") or {})

        with unittest.mock.patch(
            "tv_time_capsule.app.save_config", side_effect=capture_save
        ):
            app._toggle_kids_view()
        self.assertEqual(app._kids_browse_style, "card")
        self.assertEqual(saved.get("browse_style"), "card")

    def test_toggle_kids_view_ignored_in_parent_mode(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = False
        app._kids_browse_style = "card"
        app._toggle_kids_view()
        self.assertEqual(app._kids_browse_style, "card")

    def test_full_card_page_size_is_one(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "full"
        app.view = app.SHOW_LIST
        self.assertEqual(app._stack_page_size_for_view(), 1)

    def test_card_view_page_size_is_kids_stack_visible(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "card"
        app.view = app.SHOW_LIST
        self.assertEqual(app._stack_page_size_for_view(), 3)

    def test_full_card_cursor_moves_one_at_a_time(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "full"
        app._kids_allowlist = None
        app.view = app.SHOW_LIST
        app.show_names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
        app.shows = {k: {"seasons": {1: {"episodes": []}}} for k in app.show_names}
        app.cursor = 0
        app._process_browse_action("down")
        self.assertEqual(app.cursor, 1)
        app._process_browse_action("down")
        self.assertEqual(app.cursor, 2)
        app._process_browse_action("up")
        self.assertEqual(app.cursor, 1)

    def test_full_card_draws_without_crashing(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "full"
        app.view = app.SHOW_LIST
        app.show_names = ["Bluey", "Sesame Street"]
        app.shows = {
            "Bluey": {"thumbnail": __file__, "seasons": {1: {"episodes": []}}},
            "Sesame Street": {"thumbnail": __file__, "seasons": {1: {"episodes": []}}},
        }
        app.cursor = 0
        app.draw_kids_full_card()
        app.cursor = 1
        app.draw_kids_full_card()

    def test_full_card_movie_draws_without_crashing(self):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((800, 600))
        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app._kids_mode_active = True
        app._kids_browse_style = "full"
        app.view = app.MOVIE_LIST
        app.movie_names = ["Movie A", "Movie B"]
        app.movies = {
            "Movie A": {"title": "Movie A", "thumbnail": __file__, "path": "/tmp/a.mp4"},
            "Movie B": {"title": "Movie B", "thumbnail": __file__, "path": "/tmp/b.mp4"},
        }
        app.cursor = 0
        app.draw_kids_full_card()
        app.cursor = 1
        app.draw_kids_full_card()


if __name__ == "__main__":
    unittest.main()
