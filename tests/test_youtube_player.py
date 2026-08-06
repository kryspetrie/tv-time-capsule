"""Unit tests for YouTube player helpers (letterbox detection, pause freeze)."""

from __future__ import annotations

import unittest

import pygame

from tv_time_capsule.youtube_player import (
    YouTubePlayer,
    detect_letterbox_rect,
    scale_uniform,
)


class LetterboxDetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def _frame(self, w, h, *, top=0, bottom=0, left=0, right=0, fill=(180, 40, 40)):
        surf = pygame.Surface((w, h))
        surf.fill((0, 0, 0))
        rect = pygame.Rect(left, top, w - left - right, h - top - bottom)
        surf.fill(fill, rect)
        return surf

    def test_letterbox_only_ignored(self):
        # True 16:9 in a 4:3 frame — keep top/bottom bars; do not crop.
        surf = self._frame(320, 240, top=30, bottom=30)
        self.assertIsNone(
            detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        )

    def test_detects_pillarbox(self):
        surf = self._frame(320, 240, left=40, right=40)
        rect = detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        self.assertIsNotNone(rect)
        x, y, cw, ch = rect
        self.assertGreater(x, 10)
        self.assertLess(cw, 280)

    def test_windowbox_crops_all_sides(self):
        surf = self._frame(320, 240, top=20, bottom=20, left=40, right=40)
        rect = detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        self.assertIsNotNone(rect)
        x, y, cw, ch = rect
        self.assertGreater(x, 10)
        self.assertGreater(y, 5)
        self.assertLess(cw, 280)
        self.assertLess(ch, 220)

    def test_full_bleed_returns_none(self):
        surf = self._frame(320, 240)
        self.assertIsNone(detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02))


class ScaleUniformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def test_fit_preserves_aspect_with_letterbox(self):
        # 16:9 source into 4:3 target → black bars top/bottom, no X/Y stretch.
        src = pygame.Surface((320, 180))
        src.fill((200, 40, 40))
        out = scale_uniform(src, 320, 240, mode="fit")
        self.assertEqual(out.get_size(), (320, 240))
        # Corners should stay black (letterbox).
        self.assertEqual(out.get_at((160, 2))[:3], (0, 0, 0))
        self.assertEqual(out.get_at((160, 237))[:3], (0, 0, 0))
        # Midline should be content red.
        self.assertEqual(out.get_at((160, 120))[:3], (200, 40, 40))

    def test_cover_fills_without_anisotropicscale(self):
        src = pygame.Surface((200, 200))
        src.fill((40, 180, 40))
        out = scale_uniform(src, 320, 240, mode="cover")
        self.assertEqual(out.get_size(), (320, 240))
        # Full bleed green — cover zoomed uniformly then cropped.
        self.assertEqual(out.get_at((10, 10))[:3], (40, 180, 40))
        self.assertEqual(out.get_at((310, 230))[:3], (40, 180, 40))


class YouTubePauseWatchdogTests(unittest.TestCase):
    def test_watchdog_hard_pauses(self):
        player = YouTubePlayer(640, 480)
        js = player._js_watchdog(want_paused=True)
        self.assertIn("wantPaused = true", js)
        self.assertIn("pauseVideo", js)
        self.assertIn("video.pause()", js)
        # Must not monkey-patch or call the media play method — that breaks YT.
        self.assertNotIn("ttc-paused", js)
        self.assertNotIn("video.play =", js)
        self.assertNotIn("video.play(", js)
        self.assertNotIn("playVideo", js)

    def test_watchdog_does_not_auto_resume(self):
        player = YouTubePlayer(640, 480)
        js = player._js_watchdog(want_paused=False)
        self.assertIn("wantPaused = false", js)
        self.assertIn("100vh", js)
        # Resume is a one-shot via _js_set_paused; watchdog must not hammer play.
        self.assertNotIn("playVideo", js)
        self.assertNotIn("video.play(", js)

    def test_set_paused_uses_api_not_html5_play(self):
        js = YouTubePlayer._js_set_paused(False)
        self.assertIn("playVideo", js)
        self.assertNotIn("video.play(", js)
        js_pause = YouTubePlayer._js_set_paused(True)
        self.assertIn("pauseVideo", js_pause)
        self.assertIn("video.pause()", js_pause)

    def test_seek_prefers_seekTo(self):
        js = YouTubePlayer._js_seek(42.5)
        self.assertIn("seekTo(42.500, true)", js)
        # Direct currentTime only as fallback after seekTo attempt.
        self.assertLess(js.index("seekTo"), js.index("currentTime"))

    def test_viewport_matches_canvas(self):
        player = YouTubePlayer(640, 480)
        self.assertFalse(hasattr(player, "_page_height"))
        self.assertEqual(player.width, 640)
        self.assertEqual(player.height, 480)


if __name__ == "__main__":
    unittest.main()
