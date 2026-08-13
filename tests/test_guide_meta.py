"""Tests for TV Guide metadata enrichment helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tv_time_capsule.guide_meta import (
    enrich_title,
    pick_concise_blurb,
    reset_guide_meta_state_for_tests,
    sanitize_guide_text,
    set_guide_meta_fetch_hook_for_tests,
    soft_truncate,
)
from tv_time_capsule.metadata import parse_nfo
from tv_time_capsule.tv_guide import draw_tv_guide, guide_page_size


class GuideMetaSanitizeTests(unittest.TestCase):
    def test_strip_links_and_html(self):
        raw = 'A show. Visit https://example.com/x and <b>more</b> [here](http://x).'
        cleaned = sanitize_guide_text(raw)
        self.assertNotIn("http", cleaned)
        self.assertNotIn("<", cleaned)
        self.assertIn("A show.", cleaned)
        self.assertIn("more", cleaned)
        self.assertIn("here", cleaned)

    def test_pick_prefers_shorter_fitting_sentence(self):
        long = (
            "This is an extremely long first sentence that goes on and on about "
            "production history cast members filming locations network notes and "
            "other trivia that would never fit in a half-screen CRT panel at all."
        )
        short = "A concise kids adventure about two sisters."
        picked = pick_concise_blurb([long + " " + short, short], max_chars=120)
        self.assertEqual(picked, short)

    def test_pick_scroll_blurb_two_sentences(self):
        from tv_time_capsule.guide_meta import pick_scroll_blurb

        text = (
            "A concise kids adventure about two sisters. "
            "They explore the backyard every afternoon. "
            "Extra trivia that should not appear in the blurb."
        )
        picked = pick_scroll_blurb([text], max_sentence_chars=120)
        self.assertIn("concise kids adventure", picked.lower())
        self.assertIn("explore the backyard", picked.lower())
        self.assertNotIn("Extra trivia", picked)

    def test_soft_truncate_word_boundary(self):
        text = "Alpha beta gamma delta epsilon"
        out = soft_truncate(text, 18)
        self.assertTrue(out.endswith("..."))
        self.assertLessEqual(len(out), 18)

    def test_sanitize_vcr_safe_no_fancy_punctuation(self):
        raw = "1988–1993 · NBC — “quotes” …"
        cleaned = sanitize_guide_text(raw)
        self.assertIn("1988-1993", cleaned)
        self.assertIn("NBC", cleaned)
        self.assertIn("quotes", cleaned)
        for bad in ("\u2013", "\u2014", "\u00b7", "\u2026", "\u201c", "\u201d"):
            self.assertNotIn(bad, cleaned)
        self.assertTrue(cleaned.isascii())

    def test_cache_skips_network_on_second_request(self):
        def hook(source, **kwargs):
            if source == "omdb":
                return {"plot": "Cached plot sentence about the show here.", "years": "1990"}
            return {"plot": "Wiki plot.", "years": "1990", "network": "CBS"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("tv_time_capsule.guide_meta._CACHE_DIR", Path(tmp)):
                reset_guide_meta_state_for_tests()
                set_guide_meta_fetch_hook_for_tests(hook)
                from tv_time_capsule import guide_meta as gm

                meta1 = gm.enrich_title("Demo", "show", omdb_api_key="k")
                gm._save_disk("show", "Demo", meta1)
                gm._memory.clear()
                hit = gm.peek_guide_meta("show", "Demo")
                self.assertIsNotNone(hit)
                self.assertEqual(hit.blurb, meta1.blurb)
                # Request path must not enqueue when disk cache exists.
                again = gm.request_guide_meta("show", "Demo", omdb_api_key="k")
                self.assertIsNotNone(again)
                self.assertEqual(len(gm._queue), 0)


class GuideMetaEnrichTests(unittest.TestCase):
    def setUp(self):
        reset_guide_meta_state_for_tests()

    def tearDown(self):
        reset_guide_meta_state_for_tests()

    def test_nfo_then_omdb_then_wiki_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "tvshow.nfo").write_text(
                """<?xml version="1.0"?>
                <tvshow>
                  <title>Demo</title>
                  <plot>Local NFO plot that is long enough to count as a sentence.</plot>
                  <year>1988</year>
                  <ended>1993</ended>
                  <studio>NBC</studio>
                </tvshow>""",
                encoding="utf-8",
            )

            def hook(source, **kwargs):
                if source == "omdb":
                    return {
                        "plot": "Short OMDb blurb about the series.",
                        "years": "1988-1993",
                    }
                return {
                    "plot": "Wikipedia extract with a medium length description of Demo.",
                    "short": "American TV series",
                    "years": "1988-1993",
                    "network": "NBC",
                }

            set_guide_meta_fetch_hook_for_tests(hook)
            meta = enrich_title(
                "Demo",
                "show",
                nfo_dir=tmp,
                omdb_api_key="test",
                max_blurb_chars=80,
            )
            self.assertTrue(meta.ok)
            self.assertEqual(meta.years, "1988-1993")
            self.assertEqual(meta.network, "NBC")
            self.assertTrue(meta.blurb)
            # Per-sentence cap; blurb may include a second sentence.
            for sent in meta.blurb.split(". "):
                self.assertLessEqual(len(sent.strip(".")), 80)

    def test_parse_nfo_years_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            nfo = Path(tmp) / "tvshow.nfo"
            nfo.write_text(
                "<tvshow><year>1999</year><ended>2005</ended>"
                "<studio>Cartoon Network</studio><plot>Hi.</plot></tvshow>",
                encoding="utf-8",
            )
            meta = parse_nfo(nfo)
            self.assertEqual(meta["years"], "1999-2005")
            self.assertEqual(meta["network"], "Cartoon Network")


class GuideUiMetaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os

        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        import pygame

        pygame.init()
        pygame.font.init()

    def test_top_slot_duration_longer_with_blurb_scroll(self):
        import pygame

        from tv_time_capsule.tv_guide import (
            TOP_SLOT_MS,
            TOP_SLOT_PREVIEW_MS,
            top_slot_duration_ms,
        )

        fonts = {
            "md": pygame.font.SysFont("DejaVu Sans", 18),
            "sm": pygame.font.SysFont("DejaVu Sans", 14),
        }
        long_blurb = (
            "First sentence about the series that goes on for a while to wrap. "
            "Second sentence continues the synopsis with more detail for scrolling."
        )
        rows = [{"kind": "show", "name": "Demo", "channel": 1, "blurb": long_blurb}]
        ms = top_slot_duration_ms(
            top_mode="preview",
            rows=rows,
            preview_idx=0,
            fonts=fonts,
            screen_w=640,
            screen_h=480,
        )
        self.assertGreaterEqual(ms, TOP_SLOT_PREVIEW_MS)
        weather_ms = top_slot_duration_ms(
            top_mode="weather",
            rows=rows,
            preview_idx=0,
            fonts=fonts,
            screen_w=640,
            screen_h=480,
        )
        self.assertEqual(weather_ms, TOP_SLOT_MS)

    def test_top_half_when_blurb_present(self):
        import pygame

        screen = pygame.Surface((640, 480))
        fonts = {
            "xl": pygame.font.SysFont("DejaVu Sans", 28),
            "lg": pygame.font.SysFont("DejaVu Sans", 22),
            "md": pygame.font.SysFont("DejaVu Sans", 18),
            "sm": pygame.font.SysFont("DejaVu Sans", 14),
            "title": pygame.font.SysFont("DejaVu Sans", 14),
            "ch": pygame.font.SysFont("DejaVu Sans", 14),
            "sub": pygame.font.SysFont("DejaVu Sans", 12),
        }
        rows = [
            {
                "kind": "show",
                "name": "Demo",
                "channel": 1,
                "blurb": "A short description that expands the top panel.",
                "years": "1988-1993",
                "network": "NBC",
            }
        ]

        def load_image(*_a, **_k):
            return None

        page = draw_tv_guide(
            screen,
            rows=rows,
            scroll_offset=0,
            scroll_pixel=0.0,
            top_mode="preview",
            preview_idx=0,
            fonts=fonts,
            load_image=load_image,
            weather=None,
            now_ms=0,
        )
        page_third = guide_page_size(
            screen_h=480, top_h=480 // 3, font_title=fonts["title"], font_sub=fonts["sub"]
        )
        page_half = guide_page_size(
            screen_h=480, top_h=480 // 2, font_title=fonts["title"], font_sub=fonts["sub"]
        )
        self.assertEqual(page, page_half)
        self.assertLess(page_half, page_third)


if __name__ == "__main__":
    unittest.main()
