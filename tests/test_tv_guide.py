"""Tests for classic TV Guide helpers."""

from __future__ import annotations

import os
import random
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from tv_time_capsule.tv_guide import (
    PAGE_DWELL_MS,
    PAGE_SCROLL_MS,
    PREVIEWS_PER_CYCLE,
    build_guide_rows,
    draw_tv_guide,
    guide_list_cycle_ms,
    guide_page_size,
    guide_scroll_offset_after_steps,
    next_guide_scroll_offset,
    pick_random_preview_idx,
    pick_random_scroll_offset,
    resolve_top_mode,
    resolve_top_slot,
    resolve_virtual_guide_list,
    resolve_virtual_guide_top,
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
        self.assertEqual(
            [r["name"] for r in rows],
            ["SHOWS", "Zed", "Alpha", "MOVIES", "Film"],
        )
        self.assertEqual(
            [r["channel"] for r in rows],
            [None, 5, 2, None, 2],
        )
        self.assertEqual(
            [r["kind"] for r in rows],
            ["section", "show", "show", "section", "movie"],
        )

    def test_build_rows_no_section_when_only_shows(self):
        rows = build_guide_rows(
            show_names=["Zed", "Alpha"],
            movie_names=[],
            show_channels={"Zed": 5, "Alpha": 2},
            movie_channels={},
            shows={"Zed": {}, "Alpha": {}},
            movies={},
        )
        self.assertEqual([r["name"] for r in rows], ["Zed", "Alpha"])
        self.assertEqual([r["kind"] for r in rows], ["show", "show"])

    def test_pick_random_preview_skips_sections(self):
        rows = build_guide_rows(
            show_names=["A", "B"],
            movie_names=["Film"],
            show_channels={"A": 1, "B": 2},
            movie_channels={"Film": 3},
            shows={"A": {}, "B": {}},
            movies={"Film": {"title": "Film"}},
        )
        rng = random.Random(0)
        for _ in range(30):
            idx = pick_random_preview_idx(rows, avoid=None, rng=rng)
            self.assertIn(rows[idx]["kind"], ("show", "movie"))

    def test_pick_random_scroll_offset_varies(self):
        rows = build_guide_rows(
            show_names=[f"S{i}" for i in range(8)],
            movie_names=["Film"],
            show_channels={f"S{i}": i + 1 for i in range(8)},
            movie_channels={"Film": 99},
            shows={f"S{i}": {} for i in range(8)},
            movies={"Film": {"title": "Film"}},
        )
        rng = random.Random(2)
        seen = {pick_random_scroll_offset(rows, rng=rng) for _ in range(40)}
        self.assertGreater(len(seen), 1)
        self.assertTrue(all(0 <= i < len(rows) for i in seen))
        self.assertEqual(pick_random_scroll_offset([], rng=rng), 0)
        self.assertEqual(pick_random_scroll_offset(1, rng=rng), 0)

    def test_virtual_guide_list_advances_with_elapsed_time(self):
        rows = build_guide_rows(
            show_names=[f"S{i}" for i in range(20)],
            movie_names=[],
            show_channels={f"S{i}": i + 1 for i in range(20)},
            movie_channels={},
            shows={f"S{i}": {} for i in range(20)},
            movies={},
        )
        page = 5
        cycle = guide_list_cycle_ms()
        self.assertEqual(cycle, PAGE_DWELL_MS + PAGE_SCROLL_MS)

        offset0, phase0, t0, _to0, _d0 = resolve_virtual_guide_list(
            origin_offset=0,
            elapsed_ms=0,
            rows=rows,
            page=page,
        )
        self.assertEqual(offset0, 0)
        self.assertEqual(phase0, "dwell")
        self.assertEqual(t0, 0.0)

        # After one full cycle, should be one page ahead.
        expected = next_guide_scroll_offset(0, rows, page)[0]
        offset1, phase1, _t1, _to1, _d1 = resolve_virtual_guide_list(
            origin_offset=0,
            elapsed_ms=cycle,
            rows=rows,
            page=page,
        )
        self.assertEqual(offset1, expected)
        self.assertEqual(phase1, "dwell")

        # Mid-scroll within the second cycle.
        mid = PAGE_DWELL_MS + PAGE_SCROLL_MS // 2
        offset_s, phase_s, t_s, to_s, delta_s = resolve_virtual_guide_list(
            origin_offset=0,
            elapsed_ms=mid,
            rows=rows,
            page=page,
        )
        self.assertEqual(offset_s, 0)
        self.assertEqual(phase_s, "scroll")
        self.assertGreater(t_s, 0.0)
        self.assertLess(t_s, 1.0)
        self.assertEqual(to_s, expected)
        self.assertEqual(delta_s, page)

        # Long absence uses cycle detection (still lands on a valid offset).
        far = guide_scroll_offset_after_steps(0, 10_000, rows, page)
        offset_f, phase_f, _tf, _tof, _df = resolve_virtual_guide_list(
            origin_offset=0,
            elapsed_ms=10_000 * cycle,
            rows=rows,
            page=page,
        )
        self.assertEqual(offset_f, far)
        self.assertEqual(phase_f, "dwell")
        self.assertGreaterEqual(offset_f, 0)
        self.assertLess(offset_f, len(rows))

    def test_virtual_guide_top_is_deterministic(self):
        rows = build_guide_rows(
            show_names=["A", "B", "C"],
            movie_names=["Film"],
            show_channels={"A": 1, "B": 2, "C": 3},
            movie_channels={"Film": 4},
            shows={"A": {}, "B": {}, "C": {}},
            movies={"Film": {"title": "Film"}},
        )
        a = resolve_virtual_guide_top(elapsed_ms=25_000, rows=rows, seed=42)
        b = resolve_virtual_guide_top(elapsed_ms=25_000, rows=rows, seed=42)
        self.assertEqual(a, b)
        self.assertIn(a[1], ("preview", "weather", "branding"))

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

        rows = build_guide_rows(
            show_names=["A"],
            movie_names=["Film"],
            show_channels={"A": 1},
            movie_channels={"Film": 2},
            shows={"A": {}},
            movies={"Film": {"title": "Film"}},
        )
        mode, idx = resolve_top_slot(0, rows=rows, avoid=None, rng=rng)
        self.assertEqual(mode, "preview")
        self.assertIn(rows[idx]["kind"], ("show", "movie"))

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
                weather_status="ready",
                now_ms=1000,
            )
            self.assertGreaterEqual(page, 1)

        # Empty weather uses status label (not stuck on Fetching).
        page = draw_tv_guide(
            screen,
            rows=rows,
            scroll_offset=0,
            scroll_pixel=0.0,
            top_mode="weather",
            preview_idx=0,
            fonts=fonts,
            load_image=load_image,
            weather=None,
            weather_status="unavailable",
            now_ms=1000,
        )
        self.assertGreaterEqual(page, 1)

    def test_wrap_scroll_draws_without_blank(self):
        pygame.init()
        screen = pygame.display.set_mode((640, 480))
        fonts = {
            "lg": pygame.font.Font(None, 40),
            "md": pygame.font.Font(None, 28),
            "sm": pygame.font.Font(None, 20),
            "title": pygame.font.Font(None, 20),
            "ch": pygame.font.Font(None, 20),
            "sub": pygame.font.Font(None, 18),
        }
        rows = build_guide_rows(
            show_names=[f"Show {i}" for i in range(12)],
            movie_names=[],
            show_channels={f"Show {i}": i + 1 for i in range(12)},
            movie_channels={},
            shows={f"Show {i}": {} for i in range(12)},
            movies={},
        )

        def load_image(*_a, **_k):
            return None

        # Mid wrap-anim: offset near end + pixel scroll past end.
        page = draw_tv_guide(
            screen,
            rows=rows,
            scroll_offset=10,
            scroll_pixel=200.0,
            top_mode="branding",
            preview_idx=0,
            fonts=fonts,
            load_image=load_image,
            weather=None,
            weather_status="unavailable",
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
