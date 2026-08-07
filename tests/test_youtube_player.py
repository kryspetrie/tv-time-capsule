"""Unit tests for YouTube player helpers (letterbox detection, pause freeze)."""

from __future__ import annotations

import io
import unittest
from unittest import mock

import pygame

from tv_time_capsule.youtube_player import (
    YouTubePlayer,
    detect_letterbox_rect,
    is_near_solid_frame,
    sample_side_matte,
    scale_uniform,
)


class LetterboxDetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def _frame(
        self,
        w,
        h,
        *,
        top=0,
        bottom=0,
        left=0,
        right=0,
        fill=(180, 40, 40),
        bar=(0, 0, 0),
    ):
        surf = pygame.Surface((w, h))
        surf.fill(bar)
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

    def test_detects_colored_pillarbox(self):
        # Blue side mattes with red content — common on some uploads.
        surf = self._frame(
            320, 240, left=48, right=48, fill=(200, 40, 40), bar=(20, 40, 160)
        )
        matte = sample_side_matte(surf, min_probe_px=4)
        self.assertIsNotNone(matte)
        self.assertGreater(matte[2], matte[0])  # bluish
        rect = detect_letterbox_rect(
            surf, min_bar_px=4, min_bar_frac=0.02, matte_rgb=matte
        )
        self.assertIsNotNone(rect)
        x, _y, cw, _ch = rect
        self.assertGreater(x, 20)
        self.assertLess(cw, 250)

    def test_mismatched_side_colors_ignored(self):
        surf = pygame.Surface((320, 240))
        surf.fill((200, 40, 40))
        surf.fill((10, 10, 200), pygame.Rect(0, 0, 40, 240))
        surf.fill((200, 10, 10), pygame.Rect(280, 0, 40, 240))
        self.assertIsNone(sample_side_matte(surf, min_probe_px=4))

    def test_windowbox_crops_all_sides(self):
        # Mild windowbox with ~4:3 content — still accepted.
        surf = self._frame(320, 240, top=20, bottom=20, left=40, right=40)
        rect = detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        self.assertIsNotNone(rect)
        x, y, cw, ch = rect
        self.assertGreater(x, 10)
        self.assertGreater(y, 5)
        self.assertLess(cw, 280)
        self.assertLess(ch, 220)

    def test_widescreen_windowbox_accepted(self):
        # True 16:9 picture windowboxed into 640x480 (Arthur / PBS uploads).
        surf = self._frame(640, 480, top=92, bottom=92, left=57, right=57)
        rect = detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        self.assertIsNotNone(rect)
        _x, _y, cw, ch = rect
        self.assertAlmostEqual(cw / ch, 16 / 9, delta=0.15)
        self.assertGreater(cw, 480)
        self.assertGreater(ch, 250)

    def test_extreme_windowbox_rejected(self):
        # Animorphs title-card false positive: tiny ~16:9 slice of the frame.
        surf = self._frame(640, 480, top=184, bottom=69, left=125, right=132)
        self.assertIsNone(
            detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        )

    def test_true_43_windowbox_accepted(self):
        # E-03 body: 4:3 picture centered in 640x480 with equal bars.
        surf = self._frame(640, 480, top=62, bottom=62, left=76, right=76)
        rect = detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02)
        self.assertIsNotNone(rect)
        x, y, cw, ch = rect
        self.assertAlmostEqual(cw / ch, 4 / 3, delta=0.12)
        self.assertGreater(x, 40)
        self.assertGreater(y, 30)

    def test_full_bleed_returns_none(self):
        surf = self._frame(320, 240)
        self.assertIsNone(detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02))

    def test_solid_black_is_near_solid(self):
        surf = pygame.Surface((320, 240))
        surf.fill((0, 0, 0))
        self.assertTrue(is_near_solid_frame(surf))
        self.assertIsNone(detect_letterbox_rect(surf, min_bar_px=4, min_bar_frac=0.02))

    def test_solid_color_is_near_solid(self):
        surf = pygame.Surface((320, 240))
        surf.fill((12, 12, 40))
        self.assertTrue(is_near_solid_frame(surf))

    def test_pillarbox_is_not_near_solid(self):
        surf = self._frame(320, 240, left=40, right=40)
        self.assertFalse(is_near_solid_frame(surf))


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

    def test_watchdog_injects_persistent_stylesheet(self):
        player = YouTubePlayer(640, 480)
        js = player._js_watchdog(want_paused=False)
        self.assertIn("ttc-yt-chrome-hide", js)
        self.assertIn("ytp-autohide", js)
        self.assertIn("ytp-chrome-bottom", js)
        self.assertNotIn("video.play(", js)

    def test_play_url_uses_watch_page(self):
        url = YouTubePlayer._play_url("dQw4w9WgXcQ")
        self.assertIn("youtube.com/watch?v=dQw4w9WgXcQ", url)
        self.assertIn("autoplay=1", url)
        self.assertIn("mute=1", url)
        self.assertNotIn("/embed/", url)

    def test_watchdog_detects_error_152(self):
        player = YouTubePlayer(640, 480)
        js = player._js_watchdog(want_paused=False)
        self.assertIn("152", js)
        self.assertIn("153", js)
        self.assertIn("watch on youtube", js)
        # Empty error-node text must not trip a false positive.
        self.assertIn("if (!text) continue", js)

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

    def test_watchdog_detects_error_overlay(self):
        player = YouTubePlayer(640, 480)
        js = player._js_watchdog(want_paused=False)
        self.assertIn("error: false", js)
        self.assertIn("ytp-error", js)
        self.assertIn("wrong", js)

    def test_viewport_matches_canvas(self):
        player = YouTubePlayer(640, 480)
        self.assertFalse(hasattr(player, "_page_height"))
        self.assertEqual(player.width, 640)
        self.assertEqual(player.height, 480)


class CropProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def setUp(self):
        self._save_patch = mock.patch(
            "tv_time_capsule.youtube_player.save_pillarbox_crop"
        )
        self._save_patch.start()
        self.addCleanup(self._save_patch.stop)

    def _jpeg(self, surf: pygame.Surface) -> bytes:
        bio = io.BytesIO()
        pygame.image.save(surf, bio, "JPEG")
        return bio.getvalue()

    def _pillarbox_jpeg(self, w=320, h=240, left=40, right=40) -> bytes:
        surf = pygame.Surface((w, h))
        surf.fill((0, 0, 0))
        surf.fill((180, 40, 40), pygame.Rect(left, 0, w - left - right, h))
        return self._jpeg(surf)

    def test_get_frame_held_until_display_ready(self):
        player = YouTubePlayer(320, 240)
        player._display_ready = False
        player._latest_jpeg = self._pillarbox_jpeg()
        self.assertIsNone(player.get_frame())
        player._display_ready = True
        self.assertIsNotNone(player.get_frame())

    def test_probe_locks_pillarbox_before_finish(self):
        player = YouTubePlayer(320, 240)
        player._crop_probe_active = True
        player._hold_display_for_crop = True
        player._display_ready = False
        player._crop_probe_region = "start"
        player._frame_count = 10
        jpeg = self._pillarbox_jpeg()
        mono = [0.0]

        def fake_mono():
            mono[0] += 0.2
            return mono[0]

        with mock.patch("tv_time_capsule.youtube_player.time.monotonic", fake_mono):
            for _ in range(3):
                player._maybe_update_letterbox(jpeg)

        # During the hold, samples accumulate but do not lock yet.
        self.assertFalse(player._letterbox_locked)
        self.assertEqual(len(player._crop_probe_start_samples), 3)

        player._latest_jpeg = jpeg
        player._finish_crop_probe()
        self.assertTrue(player._letterbox_locked)
        self.assertIsNotNone(player._content_crop)
        self.assertGreater(player._content_crop[0], 10)
        self.assertTrue(player._display_ready)
        self.assertFalse(player._hold_display_for_crop)
        frame = player.get_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.get_size(), (320, 240))

    def test_solid_frames_skipped_during_probe(self):
        player = YouTubePlayer(320, 240)
        player._crop_probe_active = True
        player._hold_display_for_crop = True
        player._display_ready = False
        player._crop_probe_region = "start"
        player._frame_count = 10
        solid = pygame.Surface((320, 240))
        solid.fill((0, 0, 0))
        bio = io.BytesIO()
        pygame.image.save(solid, bio, "JPEG")
        solid_jpeg = bio.getvalue()
        pillar = self._pillarbox_jpeg()
        mono = [0.0]

        def fake_mono():
            mono[0] += 0.2
            return mono[0]

        with mock.patch("tv_time_capsule.youtube_player.time.monotonic", fake_mono):
            for _ in range(5):
                player._maybe_update_letterbox(solid_jpeg)
            self.assertEqual(player._crop_probe_start_samples, [])
            for _ in range(3):
                player._maybe_update_letterbox(pillar)

        self.assertEqual(len(player._crop_probe_start_samples), 3)
        self.assertTrue(all(s[0][0] >= 0 for s in player._crop_probe_start_samples))

    def test_toggle_content_zoom_persists(self):
        player = YouTubePlayer(320, 240)
        player._youtube_id = "dQw4w9WgXcQ"
        crop = (40, 0, 240, 240)
        player._detected_crop = crop
        player._content_crop = crop
        with mock.patch(
            "tv_time_capsule.youtube_player.save_pillarbox_crop"
        ) as save:
            self.assertFalse(player.toggle_content_zoom())
            self.assertIsNone(player._content_crop)
            save.assert_called()
            kwargs = save.call_args
            self.assertEqual(kwargs[0][1], crop)
            self.assertFalse(kwargs[1]["apply"])
            self.assertTrue(player.toggle_content_zoom())
            self.assertEqual(player._content_crop, crop)
            self.assertTrue(save.call_args[1]["apply"])

    def test_finish_probe_force_locks_without_samples(self):
        player = YouTubePlayer(320, 240)
        player._crop_probe_active = True
        player._hold_display_for_crop = True
        player._display_ready = False
        player._finish_crop_probe()
        self.assertTrue(player._letterbox_locked)
        self.assertTrue(player._display_ready)
        self.assertIsNone(player._content_crop)

    def test_start_end_agree_keeps_crop(self):
        player = YouTubePlayer(320, 240)
        crop = (40, 0, 240, 240)
        player._crop_probe_start_samples = [(crop, None), (crop, None)]
        player._crop_probe_end_samples = [(crop, None), ((42, 0, 238, 240), None)]
        merged = player._probe_samples_for_commit()
        self.assertEqual(len(merged), 4)
        player._letterbox_samples = merged
        self.assertTrue(
            player._commit_letterbox_from_samples(
                None, min_samples=3, min_agree=2, force=True
            )
        )
        self.assertIsNotNone(player._content_crop)

    def test_content_pillarbox_overrides_fullbleed_start(self):
        # Animorphs-style: opener is full-bleed, body is pillarboxed.
        player = YouTubePlayer(320, 240)
        crop = (40, 0, 240, 240)
        player._crop_probe_start_samples = [
            ((-1, -1, -1, -1), None),
            ((-1, -1, -1, -1), None),
        ]
        player._crop_probe_mid_samples = [(crop, None), (crop, None)]
        player._crop_probe_end_samples = [
            (crop, None),
            ((42, 0, 238, 240), None),
        ]
        merged = player._probe_samples_for_commit()
        self.assertEqual(len(merged), 4)
        player._hold_display_for_crop = True
        player._display_ready = False
        player._youtube_id = "2ptL3fim9Uw"
        player._finish_crop_probe()
        self.assertTrue(player._letterbox_locked)
        self.assertIsNotNone(player._content_crop)
        self.assertGreater(player._content_crop[0], 10)

    def test_finish_crop_probe_can_park_prepared(self):
        player = YouTubePlayer(320, 240)
        crop = (40, 0, 240, 240)
        player.running = True
        player._crop_probe_start_samples = [(crop, None), (crop, None), (crop, None)]
        player._hold_display_for_crop = True
        player._display_ready = False
        player._youtube_id = "preloadTestId"
        with mock.patch(
            "tv_time_capsule.youtube_player.save_pillarbox_crop"
        ):
            player._finish_crop_probe(release=False)
        self.assertTrue(player.is_prepared)
        self.assertTrue(player._hold_display_for_crop)
        self.assertFalse(player._display_ready)
        with mock.patch.object(player, "_release_display_hold") as release:
            self.assertTrue(player.begin_playback(resume_pos=0))
            release.assert_called_once()
        self.assertFalse(player.is_prepared)

    def test_only_start_pillarbox_still_crops(self):
        player = YouTubePlayer(320, 240)
        crop = (40, 0, 240, 240)
        player._crop_probe_start_samples = [(crop, None), (crop, None), (crop, None)]
        player._crop_probe_mid_samples = []
        player._crop_probe_end_samples = []
        merged = player._probe_samples_for_commit()
        self.assertEqual(len(merged), 3)
        player._letterbox_samples = merged
        self.assertTrue(
            player._commit_letterbox_from_samples(
                None, min_samples=3, min_agree=2, force=True
            )
        )
        self.assertIsNotNone(player._content_crop)


class PlayerStateTests(unittest.TestCase):
    def test_ad_does_not_shrink_duration_or_finish(self):
        player = YouTubePlayer(320, 240)
        player._youtube_id = "abcdefghijk"
        player._apply_player_state({"t": 100.0, "d": 600.0, "ended": False})
        self.assertEqual(player.duration, 600.0)
        self.assertEqual(player._content_duration, 600.0)
        self.assertAlmostEqual(player.time_pos, 100.0)

        player._apply_player_state(
            {"t": 2.0, "d": 15.0, "ended": True, "ad": True}
        )
        self.assertTrue(player._in_ad)
        self.assertEqual(player.duration, 600.0)
        self.assertAlmostEqual(player.time_pos, 100.0)
        self.assertFalse(player.finished)

    def test_postroll_ad_near_end_marks_finished(self):
        player = YouTubePlayer(320, 240)
        player._youtube_id = "abcdefghijk"
        player._apply_player_state({"t": 595.0, "d": 600.0})
        player._apply_player_state({"t": 1.0, "d": 20.0, "ad": True})
        self.assertTrue(player.finished)
        self.assertAlmostEqual(player.time_pos, 600.0)

    def test_related_video_marks_finished(self):
        player = YouTubePlayer(320, 240)
        player._youtube_id = "abcdefghijk"
        player._apply_player_state({"t": 50.0, "d": 600.0})
        player._apply_player_state(
            {"t": 0.0, "d": 30.0, "videoId": "otherVideo1"}
        )
        self.assertTrue(player.finished)

    def test_short_duration_ignored_after_content(self):
        player = YouTubePlayer(320, 240)
        player._youtube_id = "abcdefghijk"
        player._apply_player_state({"t": 200.0, "d": 900.0})
        player._apply_player_state({"t": 205.0, "d": 15.0, "ad": False})
        self.assertEqual(player.duration, 900.0)
        self.assertAlmostEqual(player.time_pos, 205.0)

    def test_ended_early_ignored(self):
        player = YouTubePlayer(320, 240)
        player._youtube_id = "abcdefghijk"
        player._apply_player_state({"t": 40.0, "d": 900.0})
        player._apply_player_state({"t": 40.0, "d": 900.0, "ended": True})
        self.assertFalse(player.finished)

    def test_preroll_wait_ticks_ads_reason(self):
        player = YouTubePlayer(320, 240)
        player.running = True
        reasons: list[str] = []
        player._on_wait = reasons.append
        # One ad tick, then clear.
        states = [True, True, False, False, False]

        def _flip():
            player._in_ad = states.pop(0) if states else False

        original_sleep = __import__("time").sleep

        def fake_sleep(_dt):
            _flip()

        with mock.patch("tv_time_capsule.youtube_player.time.sleep", fake_sleep):
            player._in_ad = True
            player._wait_for_preroll_ads(clear_s=0.0, timeout=2.0)
        self.assertIn("ads", reasons)
        self.assertFalse(player.waiting_for_ad)


if __name__ == "__main__":
    unittest.main()
