"""Tests for YouTube crop normalization, detection, and ffmpeg helpers."""

from __future__ import annotations

import os
import unittest

import numpy as np
import pygame

from tv_time_capsule.youtube_crop import (
    _consensus_crop,
    denormalize_crop_rect,
    detect_letterbox_rect,
    ffmpeg_crop_filter,
    normalize_crop_rect,
)
from tv_time_capsule.youtube_crop_cache import CROP_CACHE_VERSION


def _rgb_surface(
    width: int,
    height: int,
    *,
    matte: tuple[int, int, int],
    content: tuple[int, int, int, int],
    picture: tuple[int, int, int] = (180, 90, 40),
    noise: int = 40,
) -> pygame.Surface:
    """Build a frame with a flat matte and a noisy picture rectangle."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :] = np.asarray(matte, dtype=np.uint8)
    x, y, cw, ch = content
    rng = np.random.default_rng(0)
    patch = np.clip(
        np.asarray(picture, dtype=np.int16)
        + rng.integers(-noise, noise + 1, size=(ch, cw, 3)),
        0,
        255,
    ).astype(np.uint8)
    arr[y : y + ch, x : x + cw] = patch
    # pygame surfarray is width-major
    return pygame.surfarray.make_surface(arr.transpose(1, 0, 2))


class YouTubeCropHelpersTests(unittest.TestCase):
    def test_normalize_denormalize_roundtrip(self):
        crop = (48, 0, 544, 480)
        norm = normalize_crop_rect(crop, 640, 480)
        self.assertIsNotNone(norm)
        self.assertAlmostEqual(norm[0], 48 / 640)
        self.assertAlmostEqual(norm[1], 0.0)
        self.assertAlmostEqual(norm[2], 544 / 640)
        self.assertAlmostEqual(norm[3], 1.0)
        got = denormalize_crop_rect(norm, 640, 480)
        self.assertEqual(got, crop)

    def test_denormalize_scales_to_different_viewport(self):
        norm = normalize_crop_rect((48, 0, 544, 480), 640, 480)
        self.assertIsNotNone(norm)
        got = denormalize_crop_rect(norm, 1280, 960)
        self.assertEqual(got, (96, 0, 1088, 960))

    def test_ffmpeg_crop_filter_apply_false_no_crop(self):
        norm = (0.075, 0.0, 0.85, 1.0)
        vf = ffmpeg_crop_filter(norm, 640, 480, apply=False)
        self.assertNotIn("crop=", vf)
        self.assertIn("scale=640:480", vf)
        self.assertIn("pad=640:480", vf)

    def test_ffmpeg_crop_filter_apply_true_contains_crop(self):
        norm = normalize_crop_rect((48, 0, 544, 480), 640, 480)
        self.assertIsNotNone(norm)
        vf = ffmpeg_crop_filter(norm, 640, 480, apply=True, cover=True)
        self.assertIn("crop=iw*", vf)
        self.assertIn("scale=640:480", vf)
        self.assertIn("force_original_aspect_ratio=increase", vf)

    def test_ffmpeg_crop_filter_none_norm_fit_only(self):
        vf = ffmpeg_crop_filter(None, 320, 240, apply=True)
        self.assertNotIn("crop=", vf)
        self.assertIn("scale=320:240", vf)

    def test_crop_cache_version_bumped_for_detector(self):
        self.assertGreaterEqual(CROP_CACHE_VERSION, 9)


class YouTubeCropDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        pygame.display.set_mode((32, 32))

    def test_classic_black_pillarbox(self):
        # 16:9 frame with 4:3 content and black side bars.
        w, h = 640, 360
        # 4:3 into 640x360 → content height 360, width 480, x=80
        surf = _rgb_surface(
            w, h, matte=(0, 0, 0), content=(80, 0, 480, 360)
        )
        crop = detect_letterbox_rect(surf)
        self.assertIsNotNone(crop)
        x, y, cw, ch = crop
        self.assertGreaterEqual(x, 60)
        self.assertLessEqual(x + cw, w - 60)
        self.assertLessEqual(abs(cw / float(ch) - 4 / 3), 0.25)

    def test_arthur_like_windowbox_blue_matte(self):
        # 4:3 upload with 16:9 picture and blue side+top/bottom mattes.
        w, h = 640, 480
        # ~16:9 content: 560x315 centered → x=40, y=82
        surf = _rgb_surface(
            w,
            h,
            matte=(20, 40, 120),
            content=(40, 82, 560, 315),
            picture=(200, 160, 80),
        )
        crop = detect_letterbox_rect(surf)
        self.assertIsNotNone(crop)
        x, y, cw, ch = crop
        self.assertGreaterEqual(x, 20)
        self.assertGreaterEqual(y, 40)
        self.assertLessEqual(x + cw, w - 20)
        self.assertLessEqual(y + ch, h - 40)
        aspect = cw / float(ch)
        self.assertGreater(aspect, 1.45)
        self.assertLess(aspect, 1.95)

    def test_full_bleed_no_crop(self):
        w, h = 640, 480
        surf = _rgb_surface(
            w, h, matte=(10, 10, 10), content=(0, 0, w, h), picture=(90, 120, 60)
        )
        self.assertIsNone(detect_letterbox_rect(surf))

    def test_consensus_requires_two_windowbox_samples(self):
        # 0.84 / 0.50 = 1.68 → windowbox (needs ≥2 agreeing samples)
        wide = (0.08, 0.25, 0.84, 0.50)
        self.assertIsNone(_consensus_crop([wide]))
        got = _consensus_crop([wide, wide, (0.09, 0.26, 0.82, 0.48)])
        self.assertIsNotNone(got)

    def test_consensus_accepts_single_pillarbox(self):
        pillar = (0.12, 0.0, 0.76, 1.0)  # ~4:3
        self.assertEqual(_consensus_crop([pillar]), pillar)

    def test_consensus_prefers_larger_fill_over_tight_cluster(self):
        # Three agreeing "false windowboxes" vs two fuller pillarboxes —
        # prefer the fuller picture (Bill Nye dark-studio case).
        tight = (0.09, 0.17, 0.60, 0.82)  # fill ~0.49
        full = (0.09, 0.0, 0.82, 1.0)  # fill ~0.82
        got = _consensus_crop([tight, tight, tight, full, full])
        self.assertIsNotNone(got)
        self.assertGreater(got[2] * got[3], 0.70)

    def test_dark_studio_keeps_full_height_pillarbox(self):
        """Black side bars + dark picture interior must not become a windowbox."""
        w, h = 568, 360
        # Near-black pillarboxes; dark blue "studio" fill that is still noisy.
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:, :] = (0, 0, 0)
        rng = np.random.default_rng(1)
        x0, cw = 52, 464  # ~4:3 into 568x360
        studio = np.clip(
            np.asarray((12, 18, 40), dtype=np.int16)
            + rng.integers(-10, 25, size=(h, cw, 3)),
            0,
            255,
        ).astype(np.uint8)
        # Bright subject in the center so contours latch onto the person.
        studio[80:280, 120:340] = np.clip(
            np.asarray((160, 140, 100), dtype=np.int16)
            + rng.integers(-30, 30, size=(200, 220, 3)),
            0,
            255,
        ).astype(np.uint8)
        arr[:, x0 : x0 + cw] = studio
        surf = pygame.surfarray.make_surface(arr.transpose(1, 0, 2))
        crop = detect_letterbox_rect(surf)
        self.assertIsNotNone(crop)
        x, y, rw, rh = crop
        # Must keep essentially full height (not carve top/bottom from studio).
        self.assertLessEqual(y, 8)
        self.assertGreaterEqual(y + rh, h - 8)
        self.assertGreaterEqual(x, 30)
        self.assertLessEqual(x + rw, w - 30)
        # Side bars should be roughly centered (not subject-hugging).
        self.assertLess(abs(x - (w - x - rw)) / float(w), 0.12)
        self.assertGreater(rw / float(w), 0.70)

    def test_asymmetric_subject_contour_snaps_to_pillarbox(self):
        """OpenCV subject blob with uneven leftover sides → symmetric 4:3."""
        from tv_time_capsule.youtube_crop import _relax_false_windowbox

        w, h = 568, 360
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        rng = np.random.default_rng(2)
        # True content 52..516; bright blob only on the left half of content.
        arr[:, 52:516] = np.clip(
            np.asarray((20, 25, 45), dtype=np.int16)
            + rng.integers(-8, 20, size=(h, 464, 3)),
            0,
            255,
        ).astype(np.uint8)
        arr[70:300, 80:280] = np.clip(
            np.asarray((200, 180, 120), dtype=np.int16)
            + rng.integers(-40, 40, size=(230, 200, 3)),
            0,
            255,
        ).astype(np.uint8)
        # Fake OpenCV result hugging the bright subject (asymmetric bars).
        fake = (80, 70, 200, 230)
        got = _relax_false_windowbox(arr, fake, matte_rgb=(0.0, 0.0, 0.0))
        gx, gy, gw, gh = got
        self.assertLessEqual(gy, 2)
        self.assertGreaterEqual(gy + gh, h - 2)
        self.assertLess(abs(gx - (w - gx - gw)) / float(w), 0.08)


if __name__ == "__main__":
    unittest.main()
