"""Tests for config file loading and auto-creation."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import tv_time_capsule.config as config_mod
from tv_time_capsule.config import _parse_kids_mode, _parse_playback


class ConfigAutoCreateTests(unittest.TestCase):
    def setUp(self):
        self._orig_active = config_mod._active_config_path

    def tearDown(self):
        config_mod._active_config_path = self._orig_active

    def test_load_config_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with patch.object(config_mod, "config_search_paths", return_value=[cfg_path]):
                with patch.object(config_mod, "_config_create_path", return_value=cfg_path):
                    config_mod._active_config_path = None
                    self.assertFalse(os.path.isfile(cfg_path))
                    cfg = config_mod.load_config()
                    self.assertTrue(os.path.isfile(cfg_path))
                    self.assertEqual(cfg_path, config_mod.config_file())
                    with open(cfg_path, encoding="utf-8") as f:
                        on_disk = json.load(f)
                    self.assertEqual(on_disk["media_paths"], cfg["media_paths"])

    def test_load_config_uses_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = os.path.join(tmp, "config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"media_paths": ["/custom/path"]}, f)
            env = {"TV_TIME_CAPSULE_CONFIG": cfg_path}
            with patch.dict(os.environ, env, clear=False):
                with patch.object(config_mod, "dev_repo_root", return_value=None):
                    config_mod._active_config_path = None
                    cfg = config_mod.load_config()
                    self.assertEqual(cfg["media_paths"], ["/custom/path"])


class PlaybackConfigTests(unittest.TestCase):
    def test_now_playing_splash_defaults(self):
        pb = _parse_playback({})
        self.assertTrue(pb["now_playing_splash"])
        self.assertEqual(pb["now_playing_splash_seconds"], 1.5)

    def test_now_playing_splash_can_disable(self):
        pb = _parse_playback(
            {"now_playing_splash": False, "now_playing_splash_seconds": 3}
        )
        self.assertFalse(pb["now_playing_splash"])
        self.assertEqual(pb["now_playing_splash_seconds"], 3.0)

    def test_default_config_ui_and_admin(self):
        cfg = config_mod.parse_config({})
        self.assertFalse(cfg["kids_mode"]["default_enabled"])
        self.assertTrue(cfg["cache"]["enabled"])
        self.assertTrue(cfg["cache"]["prefetch_next"])
        self.assertFalse(cfg["cache"]["cache_before_playing"])
        self.assertEqual(cfg["network"]["mdns_hostname"], "vintage-tv")
        self.assertEqual(cfg["network"]["admin_port"], 8765)
        self.assertTrue(cfg["ui"]["channel_snow"])
        self.assertTrue(cfg["ui"]["shutdown_collapse"])
        self.assertTrue(cfg["ui"]["analog_artifacts"])
        self.assertTrue(cfg["ui"]["footer_hints"])
        self.assertEqual(cfg["ui"]["safe_zone"]["top"], 10)
        self.assertTrue(cfg["screensaver"]["enabled"])
        self.assertEqual(cfg["screensaver"]["timeout_seconds"], 30)
        self.assertTrue(cfg["admin"]["enabled"])
        self.assertEqual(cfg["weather"]["zip"], "02108")
        self.assertEqual(cfg["weather"]["name"], "Boston")
        self.assertIsNone(cfg["weather"]["latitude"])
        self.assertIsNone(cfg["retro_tv"]["filters"])
        self.assertIsNone(cfg["retro_tv"]["volume"])
        self.assertGreaterEqual(len(cfg["youtube_channels"]), 10)
        self.assertTrue(
            any(c.get("title") == "Ms Rachel" for c in cfg["youtube_channels"])
        )


class WeatherConfigTests(unittest.TestCase):
    def test_parse_weather_zip(self):
        w = config_mod._parse_weather({"zip": " 90210 "})
        self.assertEqual(w["zip"], "90210")
        self.assertIsNone(w["latitude"])

    def test_parse_weather_coords(self):
        w = config_mod._parse_weather({"latitude": "40.7", "longitude": -74.0, "name": "NYC"})
        self.assertEqual(w["latitude"], 40.7)
        self.assertEqual(w["longitude"], -74.0)
        self.assertEqual(w["name"], "NYC")

    def test_parse_weather_partial_coords_cleared(self):
        w = config_mod._parse_weather({"latitude": 40.0})
        self.assertIsNone(w["latitude"])
        self.assertIsNone(w["longitude"])

    def test_kids_mode_enabled_persisted_field(self):
        km = _parse_kids_mode({"default_enabled": False, "enabled": True})
        self.assertTrue(km["enabled"])
        km_default = _parse_kids_mode({"default_enabled": True})
        self.assertIsNone(km_default["enabled"])


class RetroTvConfigTests(unittest.TestCase):
    def test_parse_filters_dict(self):
        r = config_mod._parse_retro_tv(
            {"filters": {"box_c": True, "box_a": 0}, "volume": 75}
        )
        self.assertEqual(r["filters"]["box_c"], True)
        self.assertEqual(r["filters"]["box_a"], False)
        self.assertEqual(r["volume"], 75)

    def test_parse_filters_bare_letter(self):
        r = config_mod._parse_retro_tv({"filters": {"m": True}})
        self.assertEqual(r["filters"], {"box_m": True})

    def test_parse_filters_list(self):
        r = config_mod._parse_retro_tv({"filters": ["box_m", "n"]})
        self.assertEqual(r["filters"], {"box_m": True, "box_n": True})

    def test_parse_filters_null(self):
        r = config_mod._parse_retro_tv({})
        self.assertIsNone(r["filters"])
        self.assertIsNone(r["volume"])

    def test_volume_clamped(self):
        self.assertEqual(config_mod._parse_retro_tv({"volume": 150})["volume"], 100)
        self.assertEqual(config_mod._parse_retro_tv({"volume": -5})["volume"], 0)


if __name__ == "__main__":
    unittest.main()
