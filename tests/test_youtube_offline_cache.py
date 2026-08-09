"""Tests for forever YouTube offline cache helpers."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tv_time_capsule.config import DEFAULT_MEDIA_ROOT, parse_config
from tv_time_capsule.youtube_offline_cache import (
    YoutubeOfflineCache,
    default_cache_dir,
    episode_filename,
    is_idle_for_youtube_cache,
    relative_episode_path,
    resolve_cache_dir,
    resolve_playback_backend,
    sanitize_cache_filename,
)


class CacheDirResolveTests(unittest.TestCase):
    def test_null_directory_uses_first_media_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {"cache": {"enabled": True, "directory": None}},
                }
            )
            cache = YoutubeOfflineCache(cfg)
            self.assertEqual(cache.cache_dir, Path(tmp).resolve())

    def test_explicit_directory_wins(self):
        with tempfile.TemporaryDirectory() as media, tempfile.TemporaryDirectory() as cache_root:
            resolved = resolve_cache_dir(
                {"directory": cache_root},
                media_paths=[media],
            )
            self.assertEqual(resolved, Path(cache_root).resolve())

    def test_unwritable_media_falls_back_to_state_dir(self):
        from tv_time_capsule.youtube_offline_cache import state_fallback_cache_dir

        resolved = default_cache_dir(["/media/usb-does-not-exist-tvtc"])
        self.assertEqual(resolved, state_fallback_cache_dir().resolve())

    def test_default_cache_dir_falls_back_when_default_media_missing(self):
        from tv_time_capsule.youtube_offline_cache import state_fallback_cache_dir

        # Empty media_paths: prefer DEFAULT_MEDIA_ROOT only if writable.
        resolved = default_cache_dir([])
        if Path(DEFAULT_MEDIA_ROOT).exists() and os.access(DEFAULT_MEDIA_ROOT, os.W_OK):
            self.assertEqual(resolved, Path(DEFAULT_MEDIA_ROOT).resolve())
        else:
            self.assertEqual(resolved, state_fallback_cache_dir().resolve())


class SanitizeAndPathTests(unittest.TestCase):
    def test_sanitize_strips_separators(self):
        self.assertEqual(sanitize_cache_filename("A/B:C"), "ABC")
        self.assertNotIn("/", sanitize_cache_filename("foo/bar"))
        self.assertNotIn(":", sanitize_cache_filename("Season: 1"))

    def test_sanitize_unicode(self):
        name = sanitize_cache_filename("Café — épisode 1")
        self.assertIn("Café", name)
        self.assertTrue(len(name) > 0)

    def test_path_builder(self):
        rel = relative_episode_path("Bluey", 1, "Magic Xylophone", "abcdefghijk")
        self.assertEqual(
            rel,
            "Bluey/s01/S01E01 - Magic Xylophone [abcdefghijk].mp4",
        )

    def test_path_builder_flat(self):
        rel = relative_episode_path(
            "Bluey",
            1,
            "Magic Xylophone",
            "abcdefghijk",
            episode=3,
            layout="flat",
        )
        self.assertEqual(
            rel,
            "Bluey/S01E03 - Magic Xylophone [abcdefghijk].mp4",
        )

    def test_episode_filename_includes_code_and_id(self):
        self.assertEqual(
            episode_filename("Hello", "dQw4w9WgXcQ", season=2, episode=5),
            "S02E05 - Hello [dQw4w9WgXcQ].mp4",
        )


class PlaybackBackendTests(unittest.TestCase):
    def test_prefer_cache_hit(self):
        self.assertEqual(
            resolve_playback_backend("prefer_cache", file_present=True), "file"
        )

    def test_prefer_cache_miss(self):
        self.assertEqual(
            resolve_playback_backend("prefer_cache", file_present=False), "live"
        )

    def test_cached_only_miss(self):
        self.assertEqual(
            resolve_playback_backend("cached_only", file_present=False), "blocked"
        )

    def test_cached_only_hit(self):
        self.assertEqual(
            resolve_playback_backend("cached_only", file_present=True), "file"
        )

    def test_live_ignores_hit(self):
        self.assertEqual(
            resolve_playback_backend("live", file_present=True), "live"
        )


class IdleGateTests(unittest.TestCase):
    def test_not_idle_when_playing(self):
        self.assertFalse(is_idle_for_youtube_cache(5, screensaver_active=False))

    def test_not_idle_weather_or_retro(self):
        self.assertFalse(is_idle_for_youtube_cache(13))
        self.assertFalse(is_idle_for_youtube_cache(14))

    def test_idle_on_browse(self):
        self.assertTrue(is_idle_for_youtube_cache(0))
        self.assertTrue(is_idle_for_youtube_cache(2))

    def test_idle_on_menus_and_config(self):
        # Key config, confirm exit, safe zone, gamepad — not watching.
        for view in (3, 4, 6, 7, 11, 12):
            self.assertTrue(is_idle_for_youtube_cache(view), msg=f"view={view}")

    def test_idle_on_screensaver(self):
        self.assertTrue(is_idle_for_youtube_cache(5, screensaver_active=True))


class ManifestTests(unittest.TestCase):
    def test_manifest_upsert_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "youtube": {
                    "playback_mode": "prefer_cache",
                    "cache": {"enabled": True, "directory": tmp},
                }
            }
            cache = YoutubeOfflineCache(cfg)
            rel = relative_episode_path("Show", 2, "Ep", "abcdefghijk", episode=4)
            dest = Path(tmp) / rel
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"fake")
            cache.upsert_manifest(
                "abcdefghijk",
                rel,
                show="Show",
                season=2,
                episode=4,
                title="Ep",
            )
            cache2 = YoutubeOfflineCache(cfg)
            self.assertTrue(cache2.is_cached("abcdefghijk"))
            self.assertEqual(cache2.cached_path("abcdefghijk"), dest.resolve())
            data = json.loads((Path(tmp) / ".manifest.json").read_text())
            self.assertIn("abcdefghijk", data["videos"])


class ConfigYoutubeTests(unittest.TestCase):
    def test_defaults(self):
        cfg = parse_config({})
        yt = cfg["youtube"]
        self.assertEqual(yt["playback_mode"], "prefer_cache")
        self.assertTrue(yt["cache"]["enabled"])
        self.assertIsNone(yt["cache"]["max_bytes"])
        self.assertTrue(yt["cache"]["download_when_idle"])
        self.assertEqual(yt["cache"]["idle_seconds"], 30)
        self.assertEqual(yt["cache"]["idle_gap_seconds"], 60)
        self.assertEqual(yt["cache"]["rate_limit_cooldown_seconds"], 1800)
        self.assertFalse(yt["cache"]["exclude_unavailable"])
        self.assertEqual(yt["cache"]["batch_size"], 1)
        self.assertEqual(yt["cache"]["layout"], "season_folders")

    def test_parse_modes_and_null_max(self):
        cfg = parse_config(
            {
                "youtube": {
                    "playback_mode": "cached_only",
                    "cache": {
                        "enabled": True,
                        "max_bytes": None,
                        "idle_seconds": 10,
                        "batch_size": 4,
                    },
                }
            }
        )
        self.assertEqual(cfg["youtube"]["playback_mode"], "cached_only")
        self.assertTrue(cfg["youtube"]["cache"]["enabled"])
        self.assertIsNone(cfg["youtube"]["cache"]["max_bytes"])
        self.assertEqual(cfg["youtube"]["cache"]["idle_seconds"], 10)
        self.assertEqual(cfg["youtube"]["cache"]["batch_size"], 4)

    def test_missing_ytdlp_error_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "youtube": {
                    "playback_mode": "prefer_cache",
                    "cache": {"enabled": True, "directory": tmp},
                }
            }
            cache = YoutubeOfflineCache(cfg)
            with patch.dict("sys.modules", {"yt_dlp": None}):
                # Force re-import failure path inside require_yt_dlp
                import tv_time_capsule.youtube_offline_cache as mod

                with patch.object(
                    mod,
                    "require_yt_dlp",
                    side_effect=mod.YoutubeDlMissingError("missing"),
                ):
                    with self.assertRaises(mod.YoutubeDlMissingError):
                        cache.download_video(
                            "abcdefghijk",
                            show="S",
                            season=1,
                            title="T",
                        )


class BackendRoutingIntegrationTests(unittest.TestCase):
    def test_cache_object_routing_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            yid = "abcdefghijk"
            rel = relative_episode_path("Show", 1, "Ep", yid)
            dest = Path(tmp) / rel
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"x")

            for mode, expect_hit, expect_miss in (
                ("prefer_cache", "file", "live"),
                ("cached_only", "file", "blocked"),
                ("live", "live", "live"),
            ):
                cfg = {
                    "youtube": {
                        "playback_mode": mode,
                        "cache": {"enabled": True, "directory": tmp},
                    }
                }
                cache = YoutubeOfflineCache(cfg)
                cache.upsert_manifest(yid, rel)
                ep = {"youtube_id": yid, "path": f"youtube:{yid}", "name": "Ep"}
                self.assertEqual(cache.backend_for_episode(ep), expect_hit, mode)
                cache2 = YoutubeOfflineCache(
                    {
                        "youtube": {
                            "playback_mode": mode,
                            "cache": {
                                "enabled": True,
                                "directory": str(Path(tmp) / "empty"),
                            },
                        }
                    }
                )
                Path(tmp, "empty").mkdir(exist_ok=True)
                self.assertEqual(cache2.backend_for_episode(ep), expect_miss, mode)


class ShowProgressAndOrderTests(unittest.TestCase):
    def test_show_cache_progress_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "youtube": {
                    "playback_mode": "cached_only",
                    "cache": {"enabled": True, "directory": tmp},
                }
            }
            cache = YoutubeOfflineCache(cfg)
            yids = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"]
            show = {
                "source": "youtube",
                "seasons": {
                    1: {
                        "episodes": [
                            {"number": i + 1, "name": f"E{i}", "youtube_id": yid}
                            for i, yid in enumerate(yids)
                        ]
                    }
                },
            }
            # Cache first two
            for yid in yids[:2]:
                rel = relative_episode_path("Zed", 1, "T", yid, episode=1)
                path = Path(tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
                cache.upsert_manifest(yid, rel)
            cached, total, pct = cache.show_cache_progress(show)
            self.assertEqual((cached, total, pct), (2, 4, 50))

    def test_missing_shows_descending(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "youtube": {
                    "playback_mode": "cached_only",
                    "cache": {"enabled": True, "directory": tmp},
                }
            }
            cache = YoutubeOfflineCache(cfg)
            shows = {
                "Alpha": {
                    "source": "youtube",
                    "seasons": {
                        1: {
                            "episodes": [
                                {
                                    "number": 1,
                                    "name": "A1",
                                    "youtube_id": "aaaaaaaaaaa",
                                },
                                {
                                    "number": 2,
                                    "name": "A2",
                                    "youtube_id": "bbbbbbbbbbb",
                                },
                            ]
                        }
                    },
                },
                "Zulu": {
                    "source": "youtube",
                    "seasons": {
                        2: {
                            "episodes": [
                                {
                                    "number": 1,
                                    "name": "Z1",
                                    "youtube_id": "ccccccccccc",
                                },
                                {
                                    "number": 3,
                                    "name": "Z3",
                                    "youtube_id": "ddddddddddd",
                                },
                            ]
                        }
                    },
                },
            }
            missing = cache.iter_missing_episodes(shows)
            # Zulu before Alpha; within Zulu episode 3 before 1
            self.assertEqual(missing[0][0], "Zulu")
            self.assertEqual(missing[0][2], 3)
            self.assertEqual(missing[1][0], "Zulu")
            self.assertEqual(missing[1][2], 1)
            self.assertEqual(missing[2][0], "Alpha")
            self.assertEqual(missing[2][2], 2)
            self.assertEqual(missing[3][0], "Alpha")
            self.assertEqual(missing[3][2], 1)


class PriorityCacheTests(unittest.TestCase):
    def _cache(self, tmp: str) -> YoutubeOfflineCache:
        cfg = parse_config(
            {
                "media_paths": [tmp],
                "youtube": {
                    "playback_mode": "cached_only",
                    "cache": {"enabled": True, "directory": tmp},
                },
            }
        )
        return YoutubeOfflineCache(cfg)

    def test_request_priority_preempts_idle_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._cache(tmp)
            cache.set_idle(False)
            self.assertTrue(cache._pause.is_set())
            items = [
                ("Wishbone", 1, 3, "Ep", "aaaaaaaaaaa"),
                ("Wishbone", 1, 2, "Ep2", "bbbbbbbbbbb"),
            ]
            with patch.object(cache, "start_worker"):
                added = cache.request_priority(items, bump=True)
            self.assertEqual(added, 2)
            self.assertTrue(cache.has_priority())
            self.assertFalse(cache._pause.is_set())
            self.assertEqual(
                cache.cache_marker_for_episode(
                    {"youtube_id": "aaaaaaaaaaa", "name": "Ep", "number": 3}
                ),
                "CACHING...",
            )
            self.assertTrue(cache.is_caching_show("Wishbone"))

            cache._active_progress["aaaaaaaaaaa"] = 42.4
            self.assertEqual(
                cache.cache_marker_for_episode(
                    {"youtube_id": "aaaaaaaaaaa", "name": "Ep", "number": 3}
                ),
                "CACHING 42%",
            )
            cache.shutdown()

    def test_priority_jobs_queue_across_shows(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._cache(tmp)
            with patch.object(cache, "start_worker"):
                cache.request_priority(
                    [
                        ("Alpha", 1, 1, "A1", "aaaaaaaaaaa"),
                        ("Alpha", 1, 2, "A2", "bbbbbbbbbbb"),
                    ],
                    bump=False,
                )
                cache.request_priority(
                    [("Beta", 1, 2, "B2", "ccccccccccc")],
                    bump=True,
                )
            with cache._prio_lock:
                shows = [j["show"] for j in cache._priority_jobs]
                flat = cache._flatten_priority_locked()
            self.assertEqual(shows, ["Alpha", "Beta"])
            self.assertEqual([t[4] for t in flat], ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"])
            cache.shutdown()

    def test_episode_bump_fifo_within_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._cache(tmp)
            with patch.object(cache, "start_worker"):
                cache.request_priority(
                    [
                        ("Wishbone", 1, 1, "E1", "id111111111"),
                        ("Wishbone", 1, 2, "E2", "id222222222"),
                        ("Wishbone", 1, 5, "E5", "id555555555"),
                        ("Wishbone", 1, 6, "E6", "id666666666"),
                    ],
                    bump=False,
                )
                # User wants Ep5 then Ep6 next.
                cache.request_priority(
                    [("Wishbone", 1, 5, "E5", "id555555555")],
                    bump=True,
                )
                cache.request_priority(
                    [("Wishbone", 1, 6, "E6", "id666666666")],
                    bump=True,
                )
            with cache._prio_lock:
                job = cache._priority_jobs[0]
                boost = [t[4] for t in job["boost"]]
                rest = [t[4] for t in job["rest"]]
                flat = [t[4] for t in cache._flatten_priority_locked()]
            self.assertEqual(boost, ["id555555555", "id666666666"])
            self.assertEqual(rest, ["id111111111", "id222222222"])
            self.assertEqual(
                flat,
                ["id555555555", "id666666666", "id111111111", "id222222222"],
            )
            cache.shutdown()

    def test_pop_priority_drains_boost_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._cache(tmp)
            cache.batch_size = 1
            with patch.object(cache, "start_worker"):
                cache.request_priority(
                    [
                        ("Wishbone", 1, 1, "E1", "id111111111"),
                        ("Wishbone", 1, 5, "E5", "id555555555"),
                    ],
                    bump=False,
                )
                cache.request_priority(
                    [("Wishbone", 1, 5, "E5", "id555555555")],
                    bump=True,
                )
            batch = cache._pop_priority_batch()
            self.assertEqual(batch[0][4], "id555555555")
            cache._clear_finished_priority_ids(batch)
            batch2 = cache._pop_priority_batch()
            self.assertEqual(batch2[0][4], "id111111111")
            cache.shutdown()

    def test_front_boost_moves_show_and_episode_to_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = self._cache(tmp)
            with patch.object(cache, "start_worker"):
                cache.request_priority(
                    [("Alpha", 1, 1, "A1", "aaaaaaaaaaa")],
                    bump=False,
                )
                cache.request_priority(
                    [("Beta", 1, 1, "B1", "bbbbbbbbbbb")],
                    bump=False,
                )
                cache.request_priority(
                    [("Beta", 1, 2, "B2", "ccccccccccc")],
                    bump=True,
                    front=True,
                )
            with cache._prio_lock:
                shows = [j["show"] for j in cache._priority_jobs]
                flat = [t[4] for t in cache._flatten_priority_locked()]
            self.assertEqual(shows[0], "Beta")
            self.assertEqual(flat[0], "ccccccccccc")
            cache.shutdown()

    def test_unavailable_skipped_from_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {
                        "cache": {"enabled": True, "directory": tmp},
                    },
                }
            )
            cache = YoutubeOfflineCache(cfg)
            # Vague "not available" is NOT permanent (wrong yt-dlp client).
            self.assertFalse(
                cache._error_is_unavailable(
                    "ERROR: [youtube] 2ptL3fim9Uw: This video is not available"
                )
            )
            cache.mark_unavailable(
                "2ptL3fim9Uw",
                error="ERROR: [youtube] Private video. Sign in if you've been granted access",
            )
            self.assertTrue(cache.is_unavailable("2ptL3fim9Uw"))
            self.assertEqual(
                cache.cache_marker_for_episode(
                    {"youtube_id": "2ptL3fim9Uw", "name": "Gone", "number": 1}
                ),
                "UNAVAILABLE",
            )
            shows = {
                "Wishbone": {
                    "source": "youtube",
                    "seasons": {
                        1: {
                            "episodes": [
                                {
                                    "number": 1,
                                    "name": "Gone",
                                    "youtube_id": "2ptL3fim9Uw",
                                },
                                {
                                    "number": 2,
                                    "name": "Ok",
                                    "youtube_id": "aaaaaaaaaaa",
                                },
                            ]
                        }
                    },
                }
            }
            missing = cache.iter_missing_episodes(shows)
            self.assertEqual(len(missing), 1)
            self.assertEqual(missing[0][4], "aaaaaaaaaaa")
            self.assertTrue(
                cache._error_is_unavailable(
                    "ERROR: Private video. Sign in if you've been granted access"
                )
            )

    def test_scrub_false_unavailable_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / ".manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "videos": {},
                        "skipped": {
                            "2ptL3fim9Uw": {
                                "reason": "unavailable",
                                "error": "ERROR: [youtube] 2ptL3fim9Uw: This video is not available",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {"cache": {"enabled": True, "directory": tmp}},
                }
            )
            cache = YoutubeOfflineCache(cfg)
            self.assertFalse(cache.is_unavailable("2ptL3fim9Uw"))

    def test_live_stream_unavailable_is_permanent(self):
        msg = (
            "ERROR: [youtube] RVKWbU06vXg: This live stream recording is not available."
        )
        self.assertTrue(YoutubeOfflineCache._error_is_unavailable(msg))
        self.assertFalse(YoutubeOfflineCache._error_is_rate_limit(msg))

    def test_y_retry_clears_unavailable_and_queues(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {"cache": {"enabled": True, "directory": tmp}},
                }
            )
            cache = YoutubeOfflineCache(cfg)
            yid = "RVKWbU06vXg"
            cache.mark_unavailable(
                yid,
                error="ERROR: [youtube] This live stream recording is not available.",
            )
            self.assertTrue(cache.is_unavailable(yid))
            items = cache.missing_items_for_episode(
                "Show",
                1,
                {"number": 1, "name": "Live", "youtube_id": yid},
                retry_unavailable=True,
            )
            self.assertEqual(len(items), 1)
            added = cache.request_priority(
                items, bump=True, retry_unavailable=True
            )
            self.assertEqual(added, 1)
            self.assertFalse(cache.is_unavailable(yid))
            self.assertTrue(cache.is_priority_or_active(yid))
            cache.shutdown()

    def test_exclude_unavailable_filters_and_camel_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {
                        "cache": {
                            "enabled": True,
                            "directory": tmp,
                            "excludeUnavailable": True,
                        },
                    },
                }
            )
            self.assertTrue(cfg["youtube"]["cache"]["exclude_unavailable"])
            cache = YoutubeOfflineCache(cfg)
            self.assertTrue(cache.exclude_unavailable)
            good = {"number": 1, "name": "Ok", "youtube_id": "aaaaaaaaaaa"}
            bad = {"number": 2, "name": "Gone", "youtube_id": "bbbbbbbbbbb"}
            cache.mark_unavailable(bad["youtube_id"], error="private video")
            filtered = cache.filter_episodes([good, bad])
            self.assertEqual(filtered, [good])
            cache.exclude_unavailable = False
            self.assertEqual(cache.filter_episodes([good, bad]), [good, bad])
            cache.shutdown()

    def test_bot_check_is_rate_limit_with_curly_apostrophe(self):
        msg = (
            "ERROR: [youtube] EKZBpRRqjxA: Sign in to confirm you\u2019re not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication."
        )
        self.assertTrue(YoutubeOfflineCache._error_is_rate_limit(msg))
        self.assertFalse(YoutubeOfflineCache._error_is_unavailable(msg))

    def test_set_suspended_pauses_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {"cache": {"enabled": True, "directory": tmp}},
                }
            )
            cache = YoutubeOfflineCache(cfg)
            cache._want_idle = True
            cache._refresh_pause()
            self.assertFalse(cache._pause.is_set())
            cache.set_suspended(True)
            self.assertTrue(cache._suspended)
            self.assertTrue(cache._pause.is_set())
            cache.set_suspended(False)
            self.assertFalse(cache._suspended)
            self.assertFalse(cache._pause.is_set())
            cache.shutdown()

    def test_rate_limit_cooldown_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = parse_config(
                {
                    "media_paths": [tmp],
                    "youtube": {
                        "cache": {
                            "enabled": True,
                            "directory": tmp,
                            "idle_gap_seconds": 45,
                            "rate_limit_cooldown_seconds": 120,
                        },
                    },
                }
            )
            self.assertEqual(cfg["youtube"]["cache"]["idle_gap_seconds"], 45)
            self.assertEqual(
                cfg["youtube"]["cache"]["rate_limit_cooldown_seconds"], 120
            )
            cache = YoutubeOfflineCache(cfg)
            self.assertEqual(cache.idle_gap_seconds, 45)
            self.assertEqual(cache.rate_limit_cooldown_seconds, 120)
            self.assertFalse(cache.is_rate_limited())
            cache.trip_rate_limit("Sign in to confirm you're not a bot")
            self.assertTrue(cache.is_rate_limited())
            self.assertGreaterEqual(cache.rate_limit_remaining_seconds(), 100)
            # Second trip while limited escalates.
            first_until = cache._rate_limited_until
            cache.trip_rate_limit("HTTP Error 429: Too Many Requests")
            self.assertGreaterEqual(cache._rate_limited_until, first_until)
            self.assertEqual(cache._rate_limit_strikes, 2)
            # download_video must no-op while limited (no yt-dlp call).
            self.assertIsNone(
                cache.download_video(
                    "aaaaaaaaaaa",
                    show="Show",
                    season=1,
                    title="Ep",
                    episode=1,
                )
            )
            cache.clear_rate_limit()
            self.assertFalse(cache.is_rate_limited())


if __name__ == "__main__":
    unittest.main()
