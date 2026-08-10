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

    def test_disk_ignores_unknown_keys(self):
        import json
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock

        from tv_time_capsule.weather.adapters import forecast_cache as fc
        from tv_time_capsule.weather.models import Location

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(fc, "_CACHE_DIR", Path(tmp)):
                loc = Location(42.36, -71.06, name="Boston", context="MA")
                path = fc._cache_path(loc)
                path.write_text(
                    json.dumps(
                        {
                            "location": {
                                "latitude": 42.36,
                                "longitude": -71.06,
                                "name": "Boston",
                                "context": "MA",
                                "geocode": "",
                                "future_field": "x",
                            },
                            "current": {
                                "temperature_f": 70.0,
                                "unknown_tomorrow": True,
                            },
                            "hourly": [
                                {
                                    "time_label": "3PM",
                                    "temperature_f": 71.0,
                                    "extra": 1,
                                }
                            ],
                            "daily": [],
                            "regional": [],
                            "alerts": [],
                            "radar_station": "",
                            "fetched_at": time.time(),
                            "source": "nws",
                        }
                    ),
                    encoding="utf-8",
                )
                loaded = fc.DiskForecastStore().load(loc, max_age_s=3600)
                self.assertIsNotNone(loaded)
                assert loaded is not None
                self.assertEqual(loaded.current.temperature_f, 70.0)
                self.assertEqual(loaded.hourly[0].time_label, "3PM")


class WeatherIsoEpochTests(unittest.TestCase):
    def test_naive_open_meteo_uses_utc_offset(self):
        from datetime import datetime, timedelta, timezone

        from tv_time_capsule.weather.adapters.forecast_nws import _iso_to_epoch

        # Eastern Daylight (−4h): 14:00 local → 18:00 UTC
        epoch = _iso_to_epoch("2024-07-01T14:00", utc_offset_seconds=-4 * 3600)
        expected = datetime(
            2024, 7, 1, 14, 0, tzinfo=timezone(timedelta(hours=-4))
        ).timestamp()
        self.assertAlmostEqual(epoch, expected, places=0)

    def test_offset_iso_unchanged(self):
        from datetime import datetime

        from tv_time_capsule.weather.adapters.forecast_nws import _iso_to_epoch

        epoch = _iso_to_epoch("2024-07-01T14:00:00-04:00")
        expected = datetime.fromisoformat("2024-07-01T14:00:00-04:00").timestamp()
        self.assertAlmostEqual(epoch, expected, places=0)


class WeatherPageSecondsTests(unittest.TestCase):
    def test_parse_page_seconds(self):
        from tv_time_capsule.weather.adapters.presenter_native import (
            _parse_page_seconds,
        )

        self.assertEqual(_parse_page_seconds(None), 14.0)
        self.assertEqual(_parse_page_seconds("abc"), 14.0)
        self.assertEqual(_parse_page_seconds(-5), 3.0)
        self.assertEqual(_parse_page_seconds(999), 120.0)
        self.assertEqual(_parse_page_seconds(20), 20.0)


class WeatherNativeConfigTests(unittest.TestCase):
    def test_refresh_overrides_and_announcements(self):
        from tv_time_capsule.config import parse_config

        cfg = parse_config(
            {
                "weather": {
                    "music": {"announcements_enabled": False},
                    "native": {
                        "forecast_refresh_seconds": 240,
                        "alert_refresh_seconds": 120,
                        "forecast_loop_min_gap_seconds": 60,
                    },
                }
            }
        )
        native = cfg["weather"]["native"]
        self.assertEqual(native["forecast_refresh_seconds"], 240.0)
        self.assertEqual(native["alert_refresh_seconds"], 120.0)
        self.assertEqual(native["forecast_loop_min_gap_seconds"], 60.0)
        self.assertFalse(cfg["weather"]["music"]["announcements_enabled"])
        self.assertTrue(cfg["weather"]["music"]["enabled"])

    def test_refresh_omitted_keeps_defaults_absent(self):
        from tv_time_capsule.config import parse_config

        native = parse_config({})["weather"]["native"]
        self.assertNotIn("forecast_refresh_seconds", native)
        self.assertNotIn("alert_refresh_seconds", native)

    def test_presenter_uses_refresh_overrides(self):
        from tv_time_capsule.weather.adapters.presenter_native import (
            NativePygamePresenter,
        )

        p = NativePygamePresenter(
            640,
            480,
            weather_cfg={
                "native": {
                    "forecast_refresh_seconds": 240,
                    "alert_refresh_seconds": 60,
                }
            },
        )
        self.assertEqual(p._forecast_refresh_s, 240.0)
        self.assertEqual(p._alert_refresh_s, 60.0)
        self.assertEqual(
            NativePygamePresenter(640, 480)._forecast_refresh_s, 90.0
        )


class WeatherAlertFeedTests(unittest.TestCase):
    def test_queue_orders_emergency_school_weather(self):
        from tv_time_capsule.weather.adapters.alert_feeds import queue_alerts
        from tv_time_capsule.weather.models import Alert

        merged = queue_alerts(
            [
                [
                    Alert(
                        severity="Moderate",
                        headline="Winter Weather Advisory",
                        category="weather",
                        source="nws",
                    )
                ],
                [
                    Alert(
                        severity="Severe",
                        headline="Lincoln Schools: Closed",
                        category="school",
                        source="flashalert",
                    )
                ],
                [
                    Alert(
                        severity="Extreme",
                        headline="Civil Emergency Message",
                        category="emergency",
                        source="nws",
                    )
                ],
            ]
        )
        self.assertEqual(
            [a.category for a in merged],
            ["emergency", "school", "weather"],
        )

    def test_flashalert_xml_school_and_emergency(self):
        from tv_time_capsule.weather.adapters.alert_feeds import parse_flashalert_xml

        xml = b"""<?xml version="1.0"?>
        <flashnews updated="2026-01-01 08:00:00">
          <emergency>
            <emergency_category name="Area Schools">
              <emergency_report schoolrelated="1" operating_code="1" testing="0">
                <orgname>Lincoln USD</orgname>
                <detail>Closed</detail>
              </emergency_report>
              <emergency_report schoolrelated="1" operating_code="5" testing="0">
                <orgname>Roosevelt HS</orgname>
                <detail></detail>
              </emergency_report>
            </emergency_category>
            <emergency_category name="City Offices">
              <emergency_report schoolrelated="0" operating_code="1" testing="0">
                <orgname>City Hall</orgname>
                <detail>Closed to public</detail>
              </emergency_report>
            </emergency_category>
          </emergency>
        </flashnews>
        """
        alerts = parse_flashalert_xml(xml)
        self.assertEqual(len(alerts), 3)
        schools = [a for a in alerts if a.category == "school"]
        emerg = [a for a in alerts if a.category == "emergency"]
        self.assertEqual(len(schools), 2)
        self.assertEqual(len(emerg), 1)
        self.assertIn("Lincoln", schools[0].headline)
        self.assertIn("City Hall", emerg[0].headline)

    def test_rss_parse_and_build_client(self):
        from tv_time_capsule.weather.adapters.alert_feeds import (
            build_alert_client,
            parse_rss_atom,
        )
        from tv_time_capsule.config import parse_config

        rss = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><title>District 12 Closed</title><description>Snow day</description></item>
        </channel></rss>
        """
        items = parse_rss_atom(rss, category="school", source="rss")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].category, "school")

        cfg = parse_config(
            {
                "weather": {
                    "alerts": {
                        "feeds": [
                            {"type": "nws", "enabled": True},
                            {
                                "type": "flashalert",
                                "enabled": True,
                                "path": "/tmp/closings.xml",
                            },
                        ]
                    }
                }
            }
        )
        self.assertEqual(len(cfg["weather"]["alerts"]["feeds"]), 2)
        client = build_alert_client(cfg["weather"])
        self.assertEqual(type(client).__name__, "QueuedAlertClient")

    def test_nws_civil_event_categorized_emergency(self):
        from tv_time_capsule.weather.adapters.alert_feeds import (
            nws_alert_category,
            parse_nws_alert_features,
        )

        self.assertEqual(nws_alert_category("Tornado Warning"), "weather")
        self.assertEqual(nws_alert_category("Civil Emergency Message"), "emergency")
        self.assertEqual(nws_alert_category("Child Abduction Emergency"), "emergency")
        rows = parse_nws_alert_features(
            {
                "features": [
                    {
                        "properties": {
                            "severity": "Severe",
                            "event": "Civil Emergency Message",
                            "headline": "Local emergency",
                        }
                    }
                ]
            }
        )
        self.assertEqual(rows[0].category, "emergency")


class WeatherLowerThirdsTests(unittest.TestCase):
    def test_alerts_prefer_marquee_over_location(self):
        """Alerts fill the mid band; location is only a fallback."""
        import pygame

        from tv_time_capsule.weather.models import Alert
        from tv_time_capsule.weather.ui.lower_thirds import LowerThirds

        pygame.display.init()
        pygame.font.init()
        try:
            pygame.display.set_mode((640, 480))
            screen = pygame.Surface((640, 480))
            fonts = {
                "sm": pygame.font.Font(None, 28),
                "md": pygame.font.Font(None, 36),
            }
            bar = LowerThirds()
            bar.set_alerts(
                [
                    Alert(
                        severity="Severe",
                        headline="Tornado Watch",
                        event="Tornado Watch",
                        category="weather",
                    )
                ],
                fonts["sm"],
            )
            self.assertIn("WEATHER", bar._alert_text)
            bar.draw(
                screen,
                fonts,
                dt_ms=16.0,
                location_line="Boston, MA",
                show_alerts=True,
            )
            # Red alert panel is drawn in the mid band (not cyan location text alone).
            self.assertTrue(
                any(
                    screen.get_at((x, 450))[0] >= 80
                    and screen.get_at((x, 450))[0] > screen.get_at((x, 450))[1]
                    for x in range(180, 260, 10)
                )
            )
        finally:
            pygame.display.quit()


class WeatherRadarFitTests(unittest.TestCase):
    def test_smooth_fit_scales_once(self):
        import pygame

        from tv_time_capsule.weather.adapters.radar_image import _smooth_fit_frames

        pygame.display.init()
        try:
            pygame.display.set_mode((64, 48))
            src = pygame.Surface((200, 100))
            frames, durs = _smooth_fit_frames([src], [200], (100, 80))
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].get_size(), (100, 50))
            self.assertEqual(durs, [200])
        finally:
            pygame.display.quit()


class WeatherDailyEnrichTests(unittest.TestCase):
    def test_enrich_matches_by_date_iso(self):
        from tv_time_capsule.weather.adapters.forecast_nws import OpenMeteoForecastClient
        from tv_time_capsule.weather.models import (
            CurrentConditions,
            DayForecast,
            Location,
            WeatherSnapshot,
        )

        loc = Location(42.36, -71.06, name="Boston")
        snap = WeatherSnapshot(
            location=loc,
            current=CurrentConditions(temperature_f=70.0),
            daily=[
                DayForecast(
                    weekday="Today",
                    high_f=80.0,
                    date_iso="2024-07-02",
                    precip_pct=None,
                    precip_in=None,
                ),
                DayForecast(
                    weekday="Wed",
                    high_f=78.0,
                    date_iso="2024-07-03",
                    precip_pct=None,
                ),
            ],
            source="nws",
        )
        om_daily = [
            DayForecast(
                weekday="Tue",
                date_iso="2024-07-02",
                precip_pct=40.0,
                precip_in=0.17,
            ),
            DayForecast(
                weekday="Wed",
                date_iso="2024-07-03",
                precip_pct=10.0,
                precip_in=0.0,
            ),
        ]
        client = OpenMeteoForecastClient()
        # Call the merge loop indirectly by patching _forecast_json / _parse_bundle.
        from unittest import mock

        with mock.patch.object(
            client,
            "_forecast_json",
            return_value={"ok": True},
        ), mock.patch.object(
            client,
            "_parse_bundle",
            return_value=(
                CurrentConditions(temperature_f=71.0),
                [],
                om_daily,
            ),
        ):
            out = client.enrich(loc, snap)
        self.assertEqual(out.daily[0].precip_pct, 40.0)
        self.assertEqual(out.daily[0].precip_in, 0.17)
        self.assertEqual(out.daily[1].precip_pct, 10.0)


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
