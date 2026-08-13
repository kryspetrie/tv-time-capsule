"""Tests for classic TV Guide helpers."""

from __future__ import annotations

import os
import random
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from tv_time_capsule.tv_guide import (
    PREVIEWS_PER_CYCLE,
    build_guide_rows,
    draw_tv_guide,
    guide_page_size,
    pick_random_preview_idx,
    resolve_top_mode,
    resolve_top_slot,
    top_slot_count,
)
from tv_time_capsule.weather.models import CurrentConditions


class TvGuideTests(unittest.TestCase):
    def test_build_rows_preserves_list_order(self):
        """Shows then movies, in browse order — not merge-sorted by channel."""
        rows = build_guide_rows(
            show_names=["Zed", "Alpha"],
            movie_names=["Film"],
            show_channels={"Zed": 5, "Alpha": 2},
            movie_channels={"Film": 2},
            shows={"Zed": {}, "Alpha": {}},
            movies={"Film": {"title": "Film"}},
        )
        self.assertEqual([r["name"] for r in rows], ["Zed", "Alpha", "Film"])
        self.assertEqual([r["channel"] for r in rows], [5, 2, 2])
        self.assertEqual([r["kind"] for r in rows], ["show", "show", "movie"])

    def test_resolve_top_mode_weather_every_five_shows(self):
        """5 previews, then weather, then branding — repeating."""
        self.assertEqual(PREVIEWS_PER_CYCLE, 5)
        self.assertEqual(top_slot_count(), PREVIEWS_PER_CYCLE + 2)
        modes = [resolve_top_mode(slot) for slot in range(top_slot_count() * 2)]
        self.assertEqual(
            modes[:7],
            [
                "preview",
                "preview",
                "preview",
                "preview",
                "preview",
                "weather",
                "branding",
            ],
        )
        self.assertEqual(modes[7:14], modes[:7])

    def test_pick_random_preview_avoids_repeat(self):
        rng = random.Random(0)
        seen = {
            pick_random_preview_idx(8, avoid=3, rng=rng) for _ in range(40)
        }
        self.assertNotIn(3, seen)
        self.assertTrue(seen)

    def test_resolve_top_slot_random_preview(self):
        rng = random.Random(1)
        mode, idx = resolve_top_slot(0, row_count=10, avoid=None, rng=rng)
        self.assertEqual(mode, "preview")
        self.assertGreaterEqual(idx, 0)
        self.assertLess(idx, 10)
        self.assertEqual(resolve_top_slot(5, row_count=10, rng=rng)[0], "weather")
        self.assertEqual(resolve_top_slot(6, row_count=10, rng=rng)[0], "branding")

    def test_draw_tv_guide_modes(self):
        pygame.init()
        screen = pygame.display.set_mode((640, 480))
        fonts = {
            "xl": pygame.font.Font(None, 48),
            "lg": pygame.font.Font(None, 40),
            "md": pygame.font.Font(None, 28),
            "sm": pygame.font.Font(None, 20),
            "title": pygame.font.Font(None, 20),
            "ch": pygame.font.Font(None, 20),
            "sub": pygame.font.Font(None, 18),
        }
        rows = build_guide_rows(
            show_names=["Bluey"],
            movie_names=[],
            show_channels={"Bluey": 3},
            movie_channels={},
            shows={"Bluey": {}},
            movies={},
        )
        weather = CurrentConditions(
            temperature_f=72.0,
            humidity_pct=40.0,
            condition_text="Partly Cloudy",
            icon_id="partly-cloudy-day",
        )

        def load_image(*_a, **_k):
            return None

        for mode in ("preview", "weather", "branding"):
            page = draw_tv_guide(
                screen,
                rows=rows,
                scroll_offset=0,
                scroll_pixel=0.0,
                top_mode=mode,
                preview_idx=0,
                fonts=fonts,
                load_image=load_image,
                weather=weather,
                now_ms=1000,
            )
            self.assertGreaterEqual(page, 1)

    def test_page_size_positive(self):
        pygame.init()
        font = pygame.font.Font(None, 28)
        self.assertGreaterEqual(
            guide_page_size(screen_h=480, top_h=160, font_title=font), 1
        )


if __name__ == "__main__":
    unittest.main()
