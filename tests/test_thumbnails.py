"""Tests for synthetic / extracted show thumbnails."""

from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from tv_time_capsule import thumbnails as thumbs


class SyntheticThumbnailTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig_gen = thumbs.GENERATED_THUMB_DIR
        self._orig_custom = thumbs.CUSTOM_THUMB_DIR
        thumbs.GENERATED_THUMB_DIR = os.path.join(self._tmp.name, "gen")
        thumbs.CUSTOM_THUMB_DIR = os.path.join(self._tmp.name, "custom")

    def tearDown(self):
        thumbs.GENERATED_THUMB_DIR = self._orig_gen
        thumbs.CUSTOM_THUMB_DIR = self._orig_custom

    def test_ensure_weather_creates_png(self):
        # Prefer bundled assets/weather.png when present.
        bundled = thumbs.weather_asset_path()
        path = thumbs.ensure_weather_thumbnail()
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        if bundled:
            self.assertEqual(path, bundled)
        else:
            again = thumbs.ensure_weather_thumbnail()
            self.assertEqual(path, again)

    def test_library_thumb_grid_fills_area(self):
        from tv_time_capsule.app import TVTimeCapsule

        cols, rows, cw, ch = TVTimeCapsule._library_thumb_grid_layout(400, 300)
        self.assertEqual((cols, rows), (2, 2))
        self.assertEqual(cw, (400 - 8) // 2)
        self.assertEqual(ch, (300 - 8) // 2)

    def test_ensure_show_falls_back_to_synthetic(self):
        show = {"seasons": {}}
        path = thumbs.ensure_show_thumbnail("Mystery Science", show)
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(show.get("thumbnail"), path)

    def test_save_surface_as_custom(self):
        surf = pygame.Surface((80, 60))
        surf.fill((10, 20, 30))
        path = thumbs.save_surface_as_thumbnail(surf, "Bluey", kind="show")
        self.assertIsNotNone(path)
        self.assertTrue(os.path.isfile(path))
        show = {}
        resolved = thumbs.ensure_show_thumbnail("Bluey", show)
        self.assertEqual(resolved, path)


class SetThumbnailConfirmTests(unittest.TestCase):
    def test_confirm_flow_saves_show_poster(self):
        pygame.init()
        pygame.display.set_mode((640, 480))
        from tv_time_capsule.app import TVTimeCapsule

        app = TVTimeCapsule(["./media"], fullscreen=False, admin=False)
        app.shows = {"Bluey": {"seasons": {}}}
        app.playing_show = "Bluey"
        app._playing_is_movie = False
        frame = pygame.Surface((120, 90))
        frame.fill((200, 40, 40))

        class _FakePlayer:
            paused = False

            def get_frame(self):
                return frame

            def pause(self):
                self.paused = True

        app.player = _FakePlayer()
        # Prefer the last on-screen (cropped) blit when capturing a poster.
        app._last_displayed_video_frame = frame
        orig = thumbs.CUSTOM_THUMB_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                thumbs.CUSTOM_THUMB_DIR = os.path.join(tmp, "custom")
                app._begin_set_thumbnail_confirm()
                self.assertTrue(app._set_thumb_confirm)
                self.assertTrue(app.player.paused)
                app._set_thumb_yes = True
                app._activate_set_thumbnail_confirm()
                self.assertFalse(app._set_thumb_confirm)
                self.assertTrue(os.path.isfile(app.shows["Bluey"]["thumbnail"]))
        finally:
            thumbs.CUSTOM_THUMB_DIR = orig


if __name__ == "__main__":
    unittest.main()
