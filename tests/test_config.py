"""Tests for config file loading and auto-creation."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import tv_time_capsule.config as config_mod
from tv_time_capsule.config import _parse_playback


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
        self.assertTrue(cfg["ui"]["channel_snow"])
        self.assertTrue(cfg["ui"]["shutdown_collapse"])
        self.assertTrue(cfg["ui"]["analog_artifacts"])
        self.assertEqual(cfg["ui"]["safe_zone"]["top"], 10)
        self.assertTrue(cfg["screensaver"]["enabled"])
        self.assertEqual(cfg["screensaver"]["timeout_seconds"], 30)
        self.assertTrue(cfg["admin"]["enabled"])


if __name__ == "__main__":
    unittest.main()
