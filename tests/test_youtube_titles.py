"""Tests for YouTube title regex normalization."""

from __future__ import annotations

import unittest

from tv_time_capsule.youtube_titles import (
    DEFAULT_YOUTUBE_TITLE_RULES,
    apply_youtube_title_rules,
)
from tv_time_capsule.youtube_catalog import sanitize_display_title, set_youtube_title_rules


class YoutubeTitleRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        set_youtube_title_rules(DEFAULT_YOUTUBE_TITLE_RULES)

    def test_scholastic_episode_shortens(self):
        raw = (
            "Camp Nightmare | Werewolf Skin | Full Episodes | "
            "Goosebumps | Scholastic Classic"
        )
        out = sanitize_display_title(raw, kind="episode")
        self.assertEqual(out, "Camp Nightmare | Werewolf Skin")

    def test_magic_school_bus_pair(self):
        raw = (
            "Makes a Rainbow | Gets a Bright Idea | Full Episodes | "
            "The Magic School Bus | Scholastic Classic"
        )
        out = sanitize_display_title(raw, kind="episode")
        self.assertEqual(out, "Makes a Rainbow | Gets a Bright Idea")

    def test_animorphs_strips_marketing(self):
        raw = (
            "The Escape | Teens Transform into Animals | "
            "Full Episode | Animorphs | Scholastic Classic"
        )
        out = sanitize_display_title(raw, kind="episode")
        self.assertEqual(out, "The Escape")

    def test_thomas_minutes_suffix(self):
        raw = "Thomas Gets Lost!!! | Thomas & Friends | 90 Minutes!"
        out = sanitize_display_title(raw, kind="episode")
        self.assertNotIn("Minutes", out)
        self.assertNotIn("Thomas & Friends", out)

    def test_scishow_ngss(self):
        raw = "Science at the Beach! | NGSS Grades 1-3 | SciShow Kids"
        out = sanitize_display_title(raw, kind="episode")
        self.assertEqual(out, "Science at the Beach!")

    def test_playlist_official_channel(self):
        raw = "Bluey - Official Channel"
        out = sanitize_display_title(raw, kind="playlist")
        self.assertEqual(out, "Bluey")

    def test_bill_nye_season_playlist(self):
        raw = "Bill Nye The Science Guy - Season 5 - 480p"
        out = sanitize_display_title(raw, kind="playlist")
        self.assertEqual(out, "Season 5")

    def test_pbs_kids_suffix(self):
        raw = "Daniel Tiger's Neighborhood | PBS KIDS"
        out = sanitize_display_title(raw, kind="playlist")
        self.assertEqual(out, "Daniel Tiger's Neighborhood")

    def test_scholastic_trailing_without_pipe(self):
        raw = "Goosebumps Scholastic Classic"
        out = sanitize_display_title(raw, kind="playlist")
        self.assertEqual(out, "Goosebumps")

    def test_scholastic_emoji_playlist_sanitizes(self):
        raw = "🦁 Animorphs 🐎 Scholastic Classic"
        out = sanitize_display_title(raw, kind="playlist")
        self.assertEqual(out, "Animorphs")

    def test_config_title_skips_rules(self):
        raw = "Arthur | Scholastic Classic"
        out = sanitize_display_title(raw, kind=None)
        self.assertIn("Scholastic Classic", out)

    def test_empty_rules_noop(self):
        self.assertEqual(
            apply_youtube_title_rules("Hello | World", [], kind="episode"),
            "Hello | World",
        )

    def test_per_entry_rules_after_global(self):
        raw = "Bill Nye the Science Guy - S02E16 - Communication - 4K UPSCALED"
        out = sanitize_display_title(
            raw,
            kind="episode",
            extra_rules=[
                {
                    "pattern": r"(?i)^Bill Nye the Science Guy\s*[-–—:]\s*",
                    "replace": "",
                    "scope": "all",
                },
                {
                    "pattern": r"(?i)\s*[-–—]\s*(?:Best Quality\s*[-–—]\s*)?4K UPSCALED\s*$",
                    "replace": "",
                    "scope": "episode",
                },
            ],
        )
        self.assertEqual(out, "S02E16 - Communication")

    def test_strip_title_prefix_helper(self):
        from tv_time_capsule.youtube_titles import show_name_prefix_rule

        rule = show_name_prefix_rule("Arthur")
        self.assertIsNotNone(rule)
        out = apply_youtube_title_rules(
            "Arthur - Lend Me Your Ear/The Butler Did It",
            [rule],
            kind="episode",
        )
        self.assertEqual(out, "Lend Me Your Ear/The Butler Did It")
        out = apply_youtube_title_rules(
            "Arthur | It's a No Brainer",
            [rule],
            kind="episode",
        )
        self.assertEqual(out, "It's a No Brainer")

    def test_global_season_and_full_episode_prefixes(self):
        from tv_time_capsule.youtube_catalog import sanitize_display_title

        self.assertEqual(
            sanitize_display_title(
                "Arthur Season 3, Episode 2b, I'd Rather Read it Myself",
                kind="episode",
            ),
            "I'd Rather Read it Myself",
        )
        self.assertEqual(
            sanitize_display_title(
                "Season 5, Episode 5A, The Lousy week",
                kind="episode",
            ),
            "The Lousy week",
        )
        self.assertEqual(
            sanitize_display_title(
                "Arthur FULL EPISODE | Through the Looking Glasses",
                kind="episode",
            ),
            "Through the Looking Glasses",
        )
        self.assertEqual(
            sanitize_display_title(
                'Arthur full episode "Framed"',
                kind="episode",
            ),
            "Framed",
        )
        self.assertEqual(
            sanitize_display_title(
                "Fernlets By Fern (1/2) ItunesRip",
                kind="episode",
            ),
            "Fernlets By Fern (1/2)",
        )
        self.assertEqual(
            sanitize_display_title(
                "Something | Season 4",
                kind="episode",
            ),
            "Something",
        )

    def test_arthur_season_stripped_from_display(self):
        from tv_time_capsule.config import parse_config
        from tv_time_capsule.youtube_catalog import (
            _episode_dict,
            _entry_extra_title_rules,
            set_youtube_title_rules,
        )
        from tv_time_capsule.youtube_titles import DEFAULT_YOUTUBE_TITLE_RULES

        set_youtube_title_rules(list(DEFAULT_YOUTUBE_TITLE_RULES))
        cfg = parse_config(
            {
                "youtube_channels": [
                    {
                        "url": (
                            "https://www.youtube.com/watch?v=cRe1cta5nZk"
                            "&list=PLBSUN2PpOgePQlEtu-ZSMcHJf1zDA8a_M"
                        ),
                        "title": "Arthur",
                        "strip_title_prefix": True,
                    }
                ]
            }
        )
        arthur = cfg["youtube_channels"][0]
        extra = _entry_extra_title_rules(arthur)
        ep = _episode_dict(
            number=9,
            name="Arthur Season 3, Episode 2b, I'd Rather Read it Myself",
            youtube_id="AAAAAAAAAAA",
            extra_rules=extra,
        )
        self.assertEqual(ep["name"], "I'd Rather Read it Myself")
        self.assertEqual(ep["number"], 2)
        ep2 = _episode_dict(
            number=9,
            name="Arthur Season 3 - b - I'd Rather Read it Myself",
            youtube_id="AAAAAAAAAAA",
            extra_rules=extra,
        )
        self.assertEqual(ep2["name"], "I'd Rather Read it Myself")
        ep3 = _episode_dict(
            number=9,
            name="Arthur FULL EPISODE | Through the Looking Glasses",
            youtube_id="AAAAAAAAAAA",
            extra_rules=extra,
        )
        self.assertEqual(ep3["name"], "Through the Looking Glasses")
        ep4 = _episode_dict(
            number=9,
            name='Arthur full episode "Framed"',
            youtube_id="AAAAAAAAAAA",
            extra_rules=extra,
        )
        self.assertEqual(ep4["name"], "Framed")
        ep5 = _episode_dict(
            number=9,
            name="Arthur | It's a No Brainer; The Shore Thing",
            youtube_id="AAAAAAAAAAA",
            extra_rules=extra,
        )
        self.assertEqual(ep5["name"], "It's a No Brainer; The Shore Thing")

    def test_bare_pattern_string_rules(self):
        from tv_time_capsule.youtube_titles import _parse_title_rules

        rules = _parse_title_rules([r"(?i)^Foo\s*-\s*"])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["replace"], "")
        self.assertEqual(
            apply_youtube_title_rules("Foo - Bar", rules, kind="episode"),
            "Bar",
        )

    def test_deletions_and_substitutions_object(self):
        from tv_time_capsule.youtube_titles import _parse_title_rules

        rules = _parse_title_rules(
            {
                "deletions": [
                    r"(?i)^Show Name\s*-\s*",
                    {"pattern": r"(?i)\s*\|\s*PBS KIDS\s*$", "scope": "all"},
                ],
                "substitutions": [
                    [r"(?i)\b(\d+)\s*x\s*(\d+)\b", r"\1x\2"],
                ],
            }
        )
        self.assertEqual(len(rules), 3)
        out = apply_youtube_title_rules(
            "Show Name - 4 x 05 Hello | PBS KIDS",
            rules,
            kind="episode",
        )
        self.assertEqual(out, "4x05 Hello")

    def test_substitution_pairs_in_list(self):
        from tv_time_capsule.youtube_titles import _parse_title_rules

        rules = _parse_title_rules([[r"(?i)foo", "bar"], r"(?i)\s*!+$"])
        self.assertEqual(
            apply_youtube_title_rules("Foo!!!", rules, kind="episode"),
            "bar",
        )

    def test_scishow_compilation_suffix(self):
        raw = (
            "Think Like an Engineer: Solving Problems from Start to Finish | "
            "SciShow Kids Compilation"
        )
        out = sanitize_display_title(raw, kind="episode")
        self.assertEqual(out, "Think Like an Engineer: Solving Problems from Start to Finish")

    def test_bill_nye_quality_suffix_global(self):
        raw = (
            "Bill Nye The Science Guy - S02E16 - Communication - "
            "Best Quality - 4K UPSCALED"
        )
        # Global quality strip + leading show name needs per-entry / strip_title_prefix
        out = sanitize_display_title(raw, kind="episode")
        self.assertNotIn("4K", out)
        self.assertNotIn("Best Quality", out)

    def test_mister_rogers_brand_pipe(self):
        raw = (
            "Friendship in the Neighborhood of Make-Believe | Compilation | "
            "Mister Rogers' Neighborhood"
        )
        out = sanitize_display_title(raw, kind="episode")
        self.assertEqual(out, "Friendship in the Neighborhood of Make-Believe")


class EpisodeCodeTests(unittest.TestCase):
    def test_extract_sxxexx(self):
        from tv_time_capsule.youtube_titles import extract_episode_code

        self.assertEqual(extract_episode_code("S02E16 - Communication"), (2, 16))
        self.assertEqual(extract_episode_code("s1e2 Flight"), (1, 2))
        self.assertEqual(extract_episode_code("Show - S01E01- Flight"), (1, 1))

    def test_extract_nxnn(self):
        from tv_time_capsule.youtube_titles import extract_episode_code

        self.assertEqual(extract_episode_code("Pilot 1x02 The Beginning"), (1, 2))
        self.assertEqual(extract_episode_code("1x02"), (1, 2))

    def test_extract_season_episode_words(self):
        from tv_time_capsule.youtube_titles import extract_episode_code

        self.assertEqual(
            extract_episode_code("Best Dressed Engine | Season 7 Episode 22"),
            (7, 22),
        )

    def test_extract_ab_episode_suffix(self):
        from tv_time_capsule.youtube_titles import apply_episode_codes, extract_episode_code

        self.assertEqual(
            extract_episode_code(
                "Arthur Season 3, Episode 2b, I'd Rather Read it Myself"
            ),
            (3, 2),
        )
        self.assertEqual(
            extract_episode_code("S05E5A The Lousy Week"),
            (5, 5),
        )
        cleaned, season, ep = apply_episode_codes(
            "Arthur Season 3, Episode 2b, I'd Rather Read it Myself"
        )
        self.assertEqual(
            cleaned.replace(" - ", " "),
            "Arthur I'd Rather Read it Myself",
        )
        self.assertEqual((season, ep), (3, 2))
        # Orphan letter left by older partial strips
        cleaned, season, ep = apply_episode_codes(
            "Arthur Season 3 - b - I'd Rather Read it Myself"
        )
        self.assertEqual(
            cleaned.replace(" - ", " "),
            "Arthur I'd Rather Read it Myself",
        )
        self.assertEqual(season, 3)

    def test_strip_leaves_title(self):
        from tv_time_capsule.youtube_titles import apply_episode_codes

        cleaned, season, ep = apply_episode_codes("S02E16 - Communication")
        self.assertEqual(cleaned, "Communication")
        self.assertEqual((season, ep), (2, 16))

        cleaned, season, ep = apply_episode_codes(
            "Best Dressed Engine | Season 7 Episode 22"
        )
        self.assertEqual(cleaned, "Best Dressed Engine")
        self.assertEqual((season, ep), (7, 22))

    def test_no_code_unchanged(self):
        from tv_time_capsule.youtube_titles import apply_episode_codes

        cleaned, season, ep = apply_episode_codes("Makes a Rainbow")
        self.assertEqual(cleaned, "Makes a Rainbow")
        self.assertEqual((season, ep), (None, None))

    def test_leading_number_dash(self):
        from tv_time_capsule.youtube_titles import apply_episode_codes

        cleaned, season, ep = apply_episode_codes("1 - The Pilot")
        self.assertEqual(cleaned, "The Pilot")
        self.assertEqual((season, ep), (None, 1))

        cleaned, season, ep = apply_episode_codes("12 – Second Chance")
        self.assertEqual(cleaned, "Second Chance")
        self.assertEqual((season, ep), (None, 12))

    def test_shorten_part_markers(self):
        from tv_time_capsule.youtube_titles import apply_episode_codes, shorten_part_markers

        self.assertEqual(shorten_part_markers("My Name is Jake Part 1"), "My Name is Jake P1")
        self.assertEqual(shorten_part_markers("The Capture Pt 2"), "The Capture P2")
        self.assertEqual(shorten_part_markers("swim by me pt.1"), "swim by me P1")
        self.assertEqual(shorten_part_markers("Pt 1&2 Special"), "P1/P2 Special")
        self.assertEqual(shorten_part_markers("Chillogy Part 1 to 3"), "Chillogy P1-P3")
        self.assertEqual(
            shorten_part_markers("Father's Day - Part 1 & Part 2"),
            "Father's Day - P1/P2",
        )
        self.assertEqual(
            shorten_part_markers("My Name Is Jake Pt - 1&2"),
            "My Name Is Jake P1/P2",
        )

        cleaned, _s, _e = apply_episode_codes("2 - Face Off Part 3")
        self.assertEqual(cleaned, "Face Off P3")
        self.assertEqual(_e, 2)

    def test_composite_detection(self):
        from tv_time_capsule.youtube_titles import (
            episode_coverage_keys,
            is_composite_episode_title,
        )

        self.assertTrue(
            is_composite_episode_title("My Name Is Jake P1/P2 | Underground")
        )
        self.assertTrue(is_composite_episode_title("Teens Transform 4-6"))
        self.assertTrue(is_composite_episode_title("116-118"))
        self.assertFalse(is_composite_episode_title("My Name is Jake P1"))
        self.assertFalse(
            is_composite_episode_title(
                "Battling Aliens with Animal Powers | The Capture P1"
            )
        )
        self.assertEqual(
            episode_coverage_keys("My Name Is Jake P1/P2 | Underground"),
            {"my name is jake", "underground"},
        )

    def test_infer_implicit_part_one(self):
        from tv_time_capsule.youtube_titles import infer_implicit_part_one_titles

        eps = [
            {"name": "The Leader", "youtube_id": "a", "_order": 1},
            {"name": "The Leader P2", "youtube_id": "b", "_order": 2},
            {"name": "Face Off", "youtube_id": "c", "_order": 3},
            {"name": "Face Off P2", "youtube_id": "d", "_order": 4},
            {"name": "Face Off P3", "youtube_id": "e", "_order": 5},
            {"name": "Underground", "youtube_id": "f", "_order": 6},
            {"name": "My Name is Jake P1", "youtube_id": "g", "_order": 7},
            {"name": "My Name is Jake P2", "youtube_id": "h", "_order": 8},
        ]
        infer_implicit_part_one_titles(eps)
        by_id = {e["youtube_id"]: e["name"] for e in eps}
        self.assertEqual(by_id["a"], "The Leader P1")
        self.assertEqual(by_id["c"], "Face Off P1")
        self.assertEqual(by_id["f"], "Underground")
        self.assertEqual(by_id["g"], "My Name is Jake P1")


if __name__ == "__main__":
    unittest.main()
