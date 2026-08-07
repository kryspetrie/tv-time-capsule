"""Tests for YouTube virtual-show catalog helpers (no live network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tv_time_capsule import config as config_mod
from tv_time_capsule.youtube_catalog import (
    expand_youtube_shows,
    extract_playlists_from_yt_initial,
    extract_videos_from_yt_initial,
    is_youtube_episode,
    load_youtube_shows,
    merge_youtube_channel_numbers,
    normalize_channel_ref,
    sanitize_display_title,
    show_from_cache_payload,
    youtube_id_from_episode,
)


class SanitizeTitleTests(unittest.TestCase):
    def test_strips_emoji_and_symbols(self):
        self.assertEqual(
            sanitize_display_title("Hello 🎵 Kids ★ Learn!"),
            "Hello Kids Learn!",
        )

    def test_maps_curly_quotes_and_dashes(self):
        self.assertEqual(
            sanitize_display_title("It\u2019s a \u201ctest\u201d \u2014 really\u2026"),
            'It\'s a "test" - really...',
        )

    def test_decomposes_accents(self):
        self.assertEqual(sanitize_display_title("Café résumé"), "Cafe resume")

    def test_episode_dict_sanitizes(self):
        from tv_time_capsule.youtube_catalog import _episode_dict

        ep = _episode_dict(
            number=1, name="Song 🎤 Time!", youtube_id="dQw4w9WgXcQ"
        )
        self.assertEqual(ep["name"], "Song Time!")



class YoutubeEpisodeRoutingTests(unittest.TestCase):
    def test_is_youtube_episode_by_id(self):
        self.assertTrue(is_youtube_episode({"youtube_id": "dQw4w9WgXcQ", "path": "x"}))

    def test_is_youtube_episode_by_path(self):
        self.assertTrue(is_youtube_episode({"path": "youtube:dQw4w9WgXcQ"}))
        self.assertFalse(is_youtube_episode({"path": "/media/s01e01.mp4"}))
        self.assertFalse(is_youtube_episode(None))

    def test_youtube_id_from_episode(self):
        self.assertEqual(
            youtube_id_from_episode({"youtube_id": "dQw4w9WgXcQ"}),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            youtube_id_from_episode({"path": "youtube:dQw4w9WgXcQ"}),
            "dQw4w9WgXcQ",
        )
        self.assertIsNone(youtube_id_from_episode({"path": "/tmp/x.mp4"}))


class YoutubeConfigTests(unittest.TestCase):
    def test_parse_youtube_channels(self):
        parsed = config_mod._parse_youtube_channels(
            [
                {"handle": "veritasium", "title": "Veritasium", "channel": 90},
                {"url": "https://www.youtube.com/@kurzgesagt", "channel": "bad"},
                {
                    "url": "https://www.youtube.com/@90sProject",
                    "title": "90s Project",
                    "playlists_as_shows": True,
                },
                {
                    "url": "https://www.youtube.com/@other",
                    "playlists_as_shows": True,
                    "include_all_videos": True,
                },
                {"title": "missing id"},
                "skip-me",
            ]
        )
        self.assertEqual(len(parsed), 4)
        self.assertEqual(parsed[0]["handle"], "@veritasium")
        self.assertEqual(parsed[0]["channel"], 90)
        self.assertTrue(parsed[2]["playlists_as_shows"])
        self.assertFalse(parsed[2]["include_all_videos"])
        self.assertTrue(parsed[3]["include_all_videos"])

    def test_parse_youtube_channel_title_rules(self):
        parsed = config_mod._parse_youtube_channels(
            [
                {
                    "url": "https://www.youtube.com/@BillNyeTheScienceGuyHD/",
                    "title": "Bill Nye the Science Guy",
                    "strip_title_prefix": True,
                    "title_deletions": [
                        {
                            "pattern": r"(?i)\s*[-–—]\s*4K UPSCALED\s*$",
                            "scope": "episode",
                        }
                    ],
                    "title_substitutions": [
                        [r"(?i)\bS(\d+)E(\d+)\b", r"\1x\2"],
                    ],
                }
            ]
        )
        self.assertEqual(len(parsed), 1)
        rules = parsed[0]["title_rules"]
        self.assertEqual(len(rules), 3)
        self.assertIn(r"Bill\ Nye\ the\ Science\ Guy", rules[0]["pattern"])
        self.assertIn("4K UPSCALED", rules[1]["pattern"])
        self.assertEqual(rules[1]["replace"], "")
        self.assertEqual(rules[2]["replace"], r"\1x\2")
        self.assertTrue(parsed[0]["strip_title_prefix"])

    def test_parse_title_rules_object_on_entry(self):
        parsed = config_mod._parse_youtube_channels(
            [
                {
                    "url": "https://www.youtube.com/@example",
                    "title": "Example",
                    "title_rules": {
                        "deletions": [r"(?i)^Example\s*-\s*"],
                        "substitutions": [[r"\s+", " "]],
                    },
                }
            ]
        )
        self.assertEqual(len(parsed[0]["title_rules"]), 2)

    def test_default_90s_project_unrolls_playlists(self):
        defaults = config_mod._default_youtube_channels()
        nineties = next(e for e in defaults if e.get("title") == "90s Project")
        self.assertTrue(nineties.get("playlists_as_shows"))

    def test_parse_config_includes_youtube(self):
        cfg = config_mod.parse_config(
            {"youtube_channels": [{"handle": "@test", "channel": 5}]}
        )
        self.assertEqual(cfg["youtube_channels"][0]["handle"], "@test")
        self.assertEqual(cfg["youtube_channels"][0]["channel"], 5)

    def test_normalize_channel_ref(self):
        self.assertEqual(
            normalize_channel_ref({"handle": "@veritasium"}),
            "https://www.youtube.com/@veritasium",
        )
        self.assertEqual(
            normalize_channel_ref({"url": "UCxxxxxxxxxxxxxxxxxxxxxx"}),
            "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
        )

    def test_normalize_playlist_url(self):
        from tv_time_capsule.youtube_catalog import playlist_id_from_url

        watch = (
            "https://www.youtube.com/watch?v=yzPeIKhMUOU"
            "&list=PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ"
        )
        self.assertEqual(
            playlist_id_from_url(watch),
            "PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ",
        )
        self.assertEqual(
            normalize_channel_ref({"url": watch}),
            "https://www.youtube.com/playlist?list=PL8SFNbbOmAYNMcH8uywT24j5YXJTC2WTZ",
        )

    def test_empty_youtube_channels_explicit(self):
        cfg = config_mod.parse_config({"youtube_channels": []})
        self.assertEqual(cfg["youtube_channels"], [])


class YoutubeCacheRoundTripTests(unittest.TestCase):
    def test_show_from_cache_payload_labels(self):
        payload = {
            "title": "Channel Name",
            "thumbnail": "https://example.com/a.jpg",
            "seasons": {
                "0": {
                    "label": "All Videos",
                    "episodes": [
                        {
                            "number": 1,
                            "name": "First",
                            "youtube_id": "dQw4w9WgXcQ",
                            "duration": 42,
                        }
                    ],
                },
                "1": {
                    "label": "Best Of",
                    "episodes": [
                        {"name": "Clip", "youtube_id": "aaaaaaaaaaa"}
                    ],
                },
            },
        }
        show = show_from_cache_payload(
            payload, entry={"title": "Override", "handle": "@h", "channel": 90}
        )
        self.assertIsNotNone(show)
        assert show is not None
        self.assertEqual(show["source"], "youtube")
        self.assertEqual(show["channel_number"], 90)
        self.assertEqual(show["seasons"][0]["label"], "All Videos")
        self.assertEqual(show["seasons"][1]["label"], "Best Of")
        ep0 = show["seasons"][0]["episodes"][0]
        self.assertEqual(ep0["path"], "youtube:dQw4w9WgXcQ")
        self.assertEqual(ep0["youtube_id"], "dQw4w9WgXcQ")
        self.assertEqual(ep0["duration"], 42)

    def test_episode_codes_set_numbers_and_strip_titles(self):
        from tv_time_capsule.config import _parse_youtube_channels

        entry = _parse_youtube_channels(
            [
                {
                    "url": "https://www.youtube.com/@BillNyeTheScienceGuyHD/",
                    "title": "Bill Nye the Science Guy",
                    "strip_title_prefix": True,
                }
            ]
        )[0]
        show = show_from_cache_payload(
            {
                "title": "Bill Nye",
                "seasons": {
                    "1": {
                        "label": "Season 1",
                        "episodes": [
                            {
                                "number": 1,
                                "name": "Bill Nye the Science Guy - S01E03 - Dinosaurs",
                                "youtube_id": "aaaAAAAAAAA",
                            },
                            {
                                "number": 2,
                                "name": "Bill Nye the Science Guy - S01E01 - Flight",
                                "youtube_id": "bbbBBBBBBBB",
                            },
                            {
                                "number": 3,
                                "name": "Bonus Clip",
                                "youtube_id": "cccCCCCCCCC",
                            },
                            {
                                "number": 4,
                                "name": "Engine | Season 1 Episode 22",
                                "youtube_id": "dddDDDDDDDD",
                            },
                        ],
                    }
                },
            },
            entry=entry,
        )
        assert show is not None
        eps = show["seasons"][1]["episodes"]
        by_id = {e["youtube_id"]: e for e in eps}
        self.assertEqual(by_id["bbbBBBBBBBB"]["number"], 1)
        self.assertEqual(by_id["bbbBBBBBBBB"]["name"], "Flight")
        self.assertEqual(by_id["aaaAAAAAAAA"]["number"], 3)
        self.assertEqual(by_id["aaaAAAAAAAA"]["name"], "Dinosaurs")
        self.assertEqual(by_id["dddDDDDDDDD"]["number"], 22)
        self.assertEqual(by_id["dddDDDDDDDD"]["name"], "Engine")
        # Untitled bonus fills the next free slot (2).
        self.assertEqual(by_id["cccCCCCCCCC"]["number"], 2)
        self.assertEqual([e["number"] for e in eps], [1, 2, 3, 22])

    def test_dedupe_prefers_separated_parts_over_composite(self):
        show = show_from_cache_payload(
            {
                "title": "Animorphs",
                "seasons": {
                    "1": {
                        "label": "Animorphs",
                        "episodes": [
                            {
                                "number": 1,
                                "name": "My Name is Jake Part 1 | Full Episode",
                                "youtube_id": "aaaAAAAAAAA",
                            },
                            {
                                "number": 2,
                                "name": "My Name is Jake Part 2 | Full Episode",
                                "youtube_id": "bbbBBBBBBBB",
                            },
                            {
                                "number": 3,
                                "name": "Underground | Full Episode",
                                "youtube_id": "cccCCCCCCCC",
                            },
                            {
                                "number": 4,
                                "name": (
                                    "Episode 1-3 | My Name Is Jake Pt. 1&2 | "
                                    "Underground | Full Episode"
                                ),
                                "youtube_id": "dddDDDDDDDD",
                            },
                            {
                                "number": 5,
                                "name": "On the Run | Full Episode",
                                "youtube_id": "eeeEEEEEEEE",
                            },
                            {
                                "number": 6,
                                "name": (
                                    "Teens Transform into Animals | "
                                    "Full Episodes 4-6"
                                ),
                                "youtube_id": "fffFFFFFFFF",
                            },
                        ],
                    }
                },
            },
            entry={"title": "Animorphs"},
        )
        assert show is not None
        eps = show["seasons"][1]["episodes"]
        names = [e["name"] for e in eps]
        ids = {e["youtube_id"] for e in eps}
        self.assertIn("My Name is Jake P1", names)
        self.assertIn("My Name is Jake P2", names)
        self.assertIn("Underground", names)
        self.assertIn("On the Run", names)
        self.assertNotIn("dddDDDDDDDD", ids)
        self.assertNotIn("fffFFFFFFFF", ids)
        self.assertTrue(
            all("P1/P2" not in n and "1&2" not in n for n in names)
        )

    def test_expand_playlists_as_shows(self):
        show = show_from_cache_payload(
            {
                "title": "90s Project",
                "thumbnail": "https://example.com/ch.jpg",
                "seasons": {
                    "0": {
                        "label": "All Videos",
                        "episodes": [
                            {"name": "Upload", "youtube_id": "dQw4w9WgXcQ"}
                        ],
                    },
                    "1": {
                        "label": "Full House",
                        "playlist_id": "PLfullhouse",
                        "episodes": [
                            {"name": "E1", "youtube_id": "aaaaaaaaaaa"}
                        ],
                        "thumbnail": "https://example.com/fh.jpg",
                    },
                    "2": {
                        "label": "Friends",
                        "playlist_id": "PLfriends",
                        "episodes": [
                            {"name": "Pilot", "youtube_id": "bbbbbbbbbbb"}
                        ],
                    },
                },
            },
            entry={"title": "90s Project", "playlists_as_shows": True},
        )
        self.assertIsNotNone(show)
        expanded = expand_youtube_shows(
            "90s Project",
            show,
            {"title": "90s Project", "playlists_as_shows": True},
        )
        self.assertNotIn("90s Project", expanded)
        self.assertIn("Full House", expanded)
        self.assertIn("Friends", expanded)
        fh = expanded["Full House"]
        self.assertEqual(fh["source"], "youtube")
        self.assertFalse(fh["has_seasons"])
        self.assertEqual(fh["youtube_playlist_id"], "PLfullhouse")
        self.assertEqual(len(fh["seasons"][1]["episodes"]), 1)
        self.assertEqual(fh["youtube_parent_title"], "90s Project")

    def test_expand_keeps_all_videos_when_requested(self):
        show = show_from_cache_payload(
            {
                "seasons": {
                    "0": {
                        "label": "All Videos",
                        "episodes": [{"name": "U", "youtube_id": "dQw4w9WgXcQ"}],
                    },
                    "1": {
                        "label": "Best Of",
                        "episodes": [{"name": "C", "youtube_id": "aaaaaaaaaaa"}],
                    },
                }
            },
            entry={"title": "Demo"},
        )
        expanded = expand_youtube_shows(
            "Demo",
            show,
            {
                "title": "Demo",
                "playlists_as_shows": True,
                "include_all_videos": True,
            },
        )
        self.assertIn("Demo", expanded)
        self.assertIn("Best Of", expanded)
        self.assertFalse(expanded["Demo"]["has_seasons"])
        self.assertIn(0, expanded["Demo"]["seasons"])

    def test_load_youtube_shows_from_cache_no_scrape(self):
        with tempfile.TemporaryDirectory() as tmp:
            cdir = Path(tmp)
            entry = {"handle": "@demo", "title": "Demo Show", "channel": 12}
            # cache key matches cache_key_for_entry
            from tv_time_capsule.youtube_catalog import cache_key_for_entry

            key = cache_key_for_entry(entry)
            payload = {
                "fetched_at": 9_999_999_999.0,  # far future → fresh
                "title": "Demo Show",
                "seasons": {
                    "0": {
                        "label": "All Videos",
                        "episodes": [
                            {"number": 1, "name": "Vid", "youtube_id": "dQw4w9WgXcQ"}
                        ],
                    }
                },
            }
            (cdir / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")

            def boom(_url):
                raise AssertionError("scrape should not run for fresh cache")

            shows = load_youtube_shows(
                {"youtube_channels": [entry]},
                cache_dir=cdir,
                scrape_fn=boom,
            )
            self.assertIn("Demo Show", shows)
            self.assertEqual(shows["Demo Show"]["source"], "youtube")
            self.assertEqual(shows["Demo Show"]["channel_number"], 12)

    def test_merge_youtube_channel_numbers(self):
        shows = {
            "Local": {"has_seasons": True},
            "YT": {"source": "youtube", "channel_number": 90},
        }
        merged = merge_youtube_channel_numbers(
            {"order": ["YT"], "numbers": {"Local": 1}},
            shows,
        )
        self.assertEqual(merged["numbers"]["YT"], 90)
        self.assertEqual(merged["numbers"]["Local"], 1)


class YoutubeYtInitialParseTests(unittest.TestCase):
    def test_extract_videos_classic(self):
        data = {
            "contents": {
                "videoRenderer": {
                    "videoId": "dQw4w9WgXcQ",
                    "title": {"simpleText": "Never Gonna"},
                    "lengthText": {"simpleText": "3:32"},
                    "thumbnail": {
                        "thumbnails": [{"url": "https://i.ytimg.com/vi/x/default.jpg"}]
                    },
                }
            }
        }
        videos = extract_videos_from_yt_initial(data)
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["youtube_id"], "dQw4w9WgXcQ")
        self.assertEqual(videos[0]["name"], "Never Gonna")
        self.assertEqual(videos[0]["duration"], 212)

    def test_extract_lockup_videos(self):
        data = {
            "contents": {
                "richItemRenderer": {
                    "content": {
                        "lockupViewModel": {
                            "contentId": "dQw4w9WgXcQ",
                            "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
                            "metadata": {
                                "lockupMetadataViewModel": {
                                    "title": {"content": "Never Gonna"}
                                }
                            },
                            "contentImage": {
                                "thumbnailViewModel": {
                                    "image": {
                                        "sources": [
                                            {
                                                "url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
                                            }
                                        ]
                                    },
                                    "overlays": [
                                        {
                                            "thumbnailBottomOverlayViewModel": {
                                                "badges": [
                                                    {
                                                        "thumbnailBadgeViewModel": {
                                                            "text": "3:32"
                                                        }
                                                    }
                                                ]
                                            }
                                        }
                                    ],
                                }
                            },
                        }
                    }
                }
            }
        }
        videos = extract_videos_from_yt_initial(data)
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["youtube_id"], "dQw4w9WgXcQ")
        self.assertEqual(videos[0]["name"], "Never Gonna")
        self.assertEqual(videos[0]["duration"], 212)

    def test_extract_playlists(self):
        data = {
            "a": {
                "gridPlaylistRenderer": {
                    "playlistId": "PLtest123",
                    "title": {"runs": [{"text": "Favorites"}]},
                }
            }
        }
        playlists = extract_playlists_from_yt_initial(data)
        self.assertEqual(playlists[0]["playlist_id"], "PLtest123")
        self.assertEqual(playlists[0]["title"], "Favorites")


if __name__ == "__main__":
    unittest.main()
