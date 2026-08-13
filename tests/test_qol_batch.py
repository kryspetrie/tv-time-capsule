"""Tests for browse QoL, profiles, breadcrumb, favorites, dial 005."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from tv_time_capsule import state
from tv_time_capsule.breadcrumb import read_breadcrumb, write_breadcrumb
from tv_time_capsule.channels import build_channel_lineup
from tv_time_capsule.config import parse_config
from tv_time_capsule.home_menu import normalize_home_token
from tv_time_capsule.profiles import (
    copy_allowlist,
    migrate_legacy_state_file,
    parse_profiles,
    profile_pin,
    state_path_for_profile,
)


class HomeTokenNormalizeTests(unittest.TestCase):
    def test_new_tokens(self):
        self.assertEqual(normalize_home_token("continue"), "continue")
        self.assertEqual(normalize_home_token("favorites"), "favorites")
        self.assertEqual(normalize_home_token("recent"), "recent")
        self.assertEqual(normalize_home_token("tvguide"), "tvguide")
        self.assertEqual(normalize_home_token("005"), "tvguide")
        self.assertEqual(normalize_home_token("guide"), "directory")


class FavoritesConfigTests(unittest.TestCase):
    def test_parse_favorites(self):
        cfg = parse_config({"favorites": {"shows": ["Bluey"], "movies": ["Toy Story"]}})
        self.assertEqual(cfg["favorites"]["shows"], ["Bluey"])
        self.assertEqual(cfg["favorites"]["movies"], ["Toy Story"])

    def test_favorites_prefer_low_channels(self):
        ordered, show_to_ch, _ = build_channel_lineup(
            ["Zoo", "Alpha", "Beta"],
            None,
            favorite_names=["Zoo", "Beta"],
        )
        self.assertEqual(ordered[:2], ["Zoo", "Beta"])
        self.assertEqual(show_to_ch["Zoo"], 1)
        self.assertEqual(show_to_ch["Beta"], 2)
        self.assertEqual(show_to_ch["Alpha"], 3)


class ContinueRecentStateTests(unittest.TestCase):
    @patch.object(state, "save_state")
    def test_list_continue_and_recent(self, _save):
        s = {}
        state.set_episode_position(s, "Bluey", 1, 2, 40.0, duration=120.0)
        state.mark_episode_watched(s, "Puffin Rock", 1, 1)
        cont = state.list_continue_watching(s, known_shows={"Bluey", "Puffin Rock"})
        self.assertEqual(len(cont), 1)
        self.assertEqual(cont[0]["name"], "Bluey")
        recent = state.list_recently_watched(s, known_shows={"Bluey", "Puffin Rock"})
        names = [i["name"] for i in recent]
        self.assertIn("Bluey", names)
        self.assertIn("Puffin Rock", names)


class ProfilesTests(unittest.TestCase):
    def test_parse_and_pin(self):
        profiles = parse_profiles(
            {"active": "kids", "kids": {"pin": "1234", "label": "Kids"}}
        )
        self.assertEqual(profiles["active"], "kids")
        self.assertEqual(profile_pin(profiles, "kids"), "1234")
        self.assertIsNone(profile_pin(profiles, "parent"))

    def test_migrate_legacy_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = os.path.join(tmp, "state.json")
            with open(legacy, "w", encoding="utf-8") as fh:
                json.dump({"Bluey": {"s1": {"watched": [1]}}}, fh)
            with patch("tv_time_capsule.profiles.STATE_DIR", tmp), patch(
                "tv_time_capsule.profiles.STATE_FILE", legacy
            ):
                migrate_legacy_state_file("parent")
                dest = state_path_for_profile("parent")
                self.assertTrue(os.path.isfile(dest))
                with open(dest, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.assertIn("Bluey", data)

    def test_copy_allowlist(self):
        profiles = parse_profiles({})
        km = {"shows": ["Bluey"], "movies": []}
        updated = copy_allowlist(
            profiles, src="parent", dest="kids", kids_mode_allowlist=km
        )
        self.assertEqual(updated["kids"]["allowlist"]["shows"], ["Bluey"])


class BreadcrumbTests(unittest.TestCase):
    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("tv_time_capsule.breadcrumb.STATE_DIR", tmp), patch(
                "tv_time_capsule.breadcrumb.BREADCRUMB_FILE",
                os.path.join(tmp, "breadcrumb.json"),
            ):
                write_breadcrumb(view=0, show="Bluey", kids_mode=False, profile="parent")
                data = read_breadcrumb()
                self.assertEqual(data.get("show"), "Bluey")
                self.assertEqual(data.get("profile"), "parent")
                self.assertIn("ts", data)


class PlaybackHardeningConfigTests(unittest.TestCase):
    def test_volume_stall_read_only_pause_osd(self):
        cfg = parse_config(
            {
                "playback": {"volume": 42, "stall_auto_skip": False},
                "media": {"read_only": True},
                "ui": {"pause_cc_osd": True},
                "kids_mode": {"pin": "9999"},
            }
        )
        self.assertEqual(cfg["playback"]["volume"], 42)
        self.assertFalse(cfg["playback"]["stall_auto_skip"])
        self.assertTrue(cfg["media"]["read_only"])
        self.assertTrue(cfg["ui"]["pause_cc_osd"])
        self.assertEqual(cfg["kids_mode"]["pin"], "9999")


if __name__ == "__main__":
    unittest.main()
