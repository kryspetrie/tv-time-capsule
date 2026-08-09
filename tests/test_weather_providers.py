"""Tests for weather provider resolution, menu, and ws4kp URLs."""

from __future__ import annotations

import unittest

from tv_time_capsule.config import parse_config
from tv_time_capsule.screencast_adapt import initial_screencast_params
from tv_time_capsule.weather.adapters.presenter_ws4kp import (
    build_ws4kp_url,
    ws4kp_screencast_cfg,
)
from tv_time_capsule.weather.menu import WeatherMenu
from tv_time_capsule.weather.resolve import resolve_provider
from tv_time_capsule.weather.ui.icons import icon_from_nws_token, icon_from_wmo


class WeatherProviderResolveTests(unittest.TestCase):
    def test_parse_defaults(self):
        cfg = parse_config({})
        self.assertEqual(cfg["weather"]["provider"], "native")
        self.assertEqual(cfg["weather"]["native"]["alert_style"], "marquee")

    def test_auto_resolves_native(self):
        self.assertEqual(
            resolve_provider({"provider": "auto"}, force_weak_arm=True), "native"
        )
        self.assertEqual(
            resolve_provider({"provider": "auto"}, force_weak_arm=False), "native"
        )

    def test_explicit(self):
        self.assertEqual(resolve_provider({"provider": "ws4kp"}), "ws4kp")
        self.assertEqual(resolve_provider({"provider": "native"}), "native")
        self.assertEqual(resolve_provider({"provider": "twc"}), "twc")


class WeatherMenuTests(unittest.TestCase):
    def test_open_focuses_current(self):
        menu = WeatherMenu()
        menu.open("ws4kp")
        self.assertTrue(menu.is_open)
        self.assertEqual(menu.rows()[menu.cursor][0], "ws4kp")

    def test_select_emits_provider(self):
        menu = WeatherMenu()
        menu.open("auto")
        menu.handle("down")
        menu.handle("down")
        cmds = menu.handle("select")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0].kind, "set_provider")
        self.assertEqual(cmds[0].provider, "ws4kp")
        self.assertFalse(menu.is_open)

    def test_back_closes(self):
        menu = WeatherMenu()
        menu.open("native")
        cmds = menu.handle("back")
        self.assertEqual(cmds[0].kind, "close")
        self.assertFalse(menu.is_open)


class Ws4kpUrlTests(unittest.TestCase):
    def test_kiosk_permalink(self):
        url = build_ws4kp_url(
            "https://weatherstar.netbymatt.com",
            {"latitude": 42.36, "longitude": -71.06, "name": "Boston"},
        )
        self.assertIn("kiosk=true", url)
        self.assertIn("settings-mediaPlaying-boolean=true", url)
        self.assertIn("latLon=", url)
        self.assertIn("Boston", url)


class Ws4kpScreencastCfgTests(unittest.TestCase):
    def test_defaults_to_four_fps_fixed(self):
        cfg = ws4kp_screencast_cfg(
            {"mode": "auto", "min_fps": 1, "max_fps": 15, "target_fps": None}
        )
        self.assertEqual(cfg["mode"], "fixed")
        self.assertEqual(cfg["target_fps"], 4.0)
        params = initial_screencast_params(cfg, canvas_w=640, canvas_h=480)
        self.assertAlmostEqual(params.effective_fps, 4.0, places=1)

    def test_override(self):
        cfg = ws4kp_screencast_cfg({"ws4kp_target_fps": 2})
        self.assertEqual(cfg["target_fps"], 2.0)


class WeatherAnnouncementTests(unittest.TestCase):
    def test_page_mapping(self):
        from tv_time_capsule.weather.adapters.announcements import (
            PAGE_ANNOUNCEMENTS,
            discover_announcements,
        )

        self.assertEqual(PAGE_ANNOUNCEMENTS["current"], "current.mp3")
        self.assertNotIn("hourly", PAGE_ANNOUNCEMENTS)
        clips = discover_announcements()
        # Bundled assets may be present after fetch-weather-music.sh.
        self.assertNotIn("hourly", clips)
        for page in ("current", "daily", "regional", "alerts"):
            if page in clips:
                self.assertTrue(clips[page].name.endswith(".mp3"))


class WeatherHourlyPruneTests(unittest.TestCase):
    def test_drops_elapsed_hours(self):
        from tv_time_capsule.weather.adapters.forecast_nws import upcoming_hourly
        from tv_time_capsule.weather.models import HourlyPeriod

        now = 1_700_000_000.0
        hours = [
            HourlyPeriod(time_label="2PM", start_epoch=now - 7200),
            HourlyPeriod(time_label="3PM", start_epoch=now - 1800),
            HourlyPeriod(time_label="4PM", start_epoch=now + 1800),
        ]
        labels = [h.time_label for h in upcoming_hourly(hours, now=now)]
        self.assertEqual(labels, ["3PM", "4PM"])

    def test_drops_untimed_when_timed_exist(self):
        from tv_time_capsule.weather.adapters.forecast_nws import upcoming_hourly
        from tv_time_capsule.weather.models import HourlyPeriod

        now = 1_700_000_000.0
        hours = [
            HourlyPeriod(time_label="STALE", start_epoch=0),
            HourlyPeriod(time_label="3PM", start_epoch=now - 1800),
        ]
        labels = [h.time_label for h in upcoming_hourly(hours, now=now)]
        self.assertEqual(labels, ["3PM"])


class WeatherForecastCacheTests(unittest.TestCase):
    def test_disk_roundtrip(self):
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock

        from tv_time_capsule.weather.adapters import forecast_cache as fc
        from tv_time_capsule.weather.models import Location, WeatherSnapshot

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(fc, "_CACHE_DIR", Path(tmp)):
                store = fc.DiskForecastStore()
                loc = Location(42.36, -71.06, name="Boston", context="MA")
                snap = WeatherSnapshot(
                    location=loc,
                    hourly=[],
                    daily=[],
                    fetched_at=time.time(),
                    source="nws",
                )
                store.save(loc, snap)
                loaded = store.load(loc, max_age_s=3600)
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.location.name, "Boston")
                self.assertIn("disk", loaded.source)


class WeatherIconTests(unittest.TestCase):
    def test_wmo(self):
        self.assertEqual(icon_from_wmo(0), "clear-day")
        self.assertEqual(icon_from_wmo(61), "rain")
        self.assertEqual(icon_from_wmo(95), "thunder")

    def test_nws_token(self):
        self.assertEqual(
            icon_from_nws_token("https://api.weather.gov/icons/land/day/skc"),
            "clear-day",
        )
        self.assertIn(icon_from_nws_token("rain_showers"), ("rain", "unknown"))


class WeatherTextTests(unittest.TestCase):
    def test_abbreviate_thunderstorms(self):
        from tv_time_capsule.weather.ui.text import abbreviate_condition

        full = "Chance of Showers & Thunderstorms"
        # Fits → keep full wording.
        self.assertEqual(abbreviate_condition(full, max_len=40), full)
        # Too long → compress.
        self.assertEqual(
            abbreviate_condition(full, max_len=14),
            "Shwrs & ThdSt",
        )

    def test_rain_chance_skips_noise(self):
        from tv_time_capsule.weather.ui.text import rain_chance_label, rain_summary

        self.assertEqual(rain_chance_label(4), "")
        self.assertEqual(rain_chance_label(40), "40%")
        self.assertEqual(rain_summary(45, 0.16), "45%\n.16in")
        self.assertEqual(rain_summary(45, None), "45%")
        self.assertEqual(rain_summary(4, 0.16), ".16in")

    def test_ascii_safe_strips_missing_glyphs(self):
        from tv_time_capsule.weather.ui.text import ascii_safe

        self.assertEqual(ascii_safe("ALERT — foo · bar"), "ALERT - foo - bar")

    def test_location_city_state(self):
        from tv_time_capsule.weather.models import Location

        self.assertEqual(
            Location(42.0, -71.0, name="Boston", context="MA").display_name(),
            "Boston, MA",
        )
        self.assertEqual(
            Location(
                42.0,
                -71.0,
                name="Boston",
                context="Massachusetts, United States",
            ).display_name(),
            "Boston, MA",
        )
        self.assertEqual(
            Location(
                51.5,
                -0.1,
                name="London",
                context="England, United Kingdom",
            ).display_name(),
            "London, UK",
        )
        long_name = Location(
            0.0,
            0.0,
            name="Martha's Vineyard Township",
            context="Massachusetts, United States",
        ).display_name()
        self.assertTrue(long_name.endswith(", MA"))
        self.assertLessEqual(len(long_name), 28)

    def test_more_abbreviations(self):
        from tv_time_capsule.weather.ui.text import abbreviate_condition

        self.assertEqual(abbreviate_condition("Heavy Rain", max_len=20), "Heavy Rain")
        self.assertEqual(abbreviate_condition("Heavy Rain", max_len=8), "Hvy Rain")
        self.assertEqual(
            abbreviate_condition("Rain Showers", max_len=10), "Rain Shwrs"
        )
        self.assertEqual(
            abbreviate_condition("Severe Thunderstorms", max_len=10),
            "Sev ThdSt",
        )

    def test_fit_condition_prefers_full(self):
        from tv_time_capsule.weather.ui.text import fit_condition

        self.assertEqual(
            fit_condition("Partly Cloudy", fits=lambda s: len(s) <= 20),
            "Partly Cloudy",
        )
        self.assertEqual(
            fit_condition("Partly Cloudy", fits=lambda s: len(s) <= 10),
            "Ptly Cldy",
        )


class WeatherMapsConfigTests(unittest.TestCase):
    def test_maps_defaults(self):
        cfg = parse_config({})
        maps = cfg["weather"]["maps"]
        self.assertTrue(maps["enabled"])
        self.assertIsNone(maps["region"])
        self.assertIsNone(maps["station"])
        self.assertEqual(maps["ttl_seconds"], 300)

    def test_nws_ridge_loop_url_and_region(self):
        from tv_time_capsule.weather.adapters.radar_image import (
            build_ridge_loop_url,
            build_ridge_standard_url,
            normalize_station,
            resolve_radar_region,
        )

        self.assertEqual(normalize_station("cle"), "KCLE")
        self.assertEqual(
            build_ridge_standard_url("KCLE", frame=0),
            "https://radar.weather.gov/ridge/standard/KCLE_0.gif",
        )
        self.assertEqual(
            build_ridge_loop_url("NORTHEAST"),
            "https://radar.weather.gov/ridge/standard/NORTHEAST_loop.gif",
        )
        # Boston → NORTHEAST mosaic
        self.assertEqual(resolve_radar_region(42.36, -71.06), "NORTHEAST")
        # Chicago → central Great Lakes
        self.assertEqual(resolve_radar_region(41.88, -87.63), "CENTGRLAKES")
        self.assertEqual(
            resolve_radar_region(41.88, -87.63, override="southeast"),
            "SOUTHEAST",
        )


if __name__ == "__main__":
    unittest.main()
