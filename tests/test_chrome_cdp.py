"""Tests for Chromium discovery helpers and single-instance lease."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tv_time_capsule import chrome_cdp as mod
from tv_time_capsule.chrome_cdp import (
    acquire_chromium,
    current_chromium_owner,
    ensure_chromium,
    find_chrome,
    release_chromium,
    shutdown_app_chromium,
)


class ChromiumDiscoveryTests(unittest.TestCase):
    def test_find_chrome_uses_path(self):
        with patch(
            "tv_time_capsule.chrome_cdp.shutil.which",
            side_effect=lambda n: "/usr/bin/chromium" if n == "chromium" else None,
        ):
            self.assertEqual(find_chrome(), "/usr/bin/chromium")

    def test_find_chrome_checks_usr_bin(self):
        with (
            patch("tv_time_capsule.chrome_cdp.shutil.which", return_value=None),
            patch(
                "tv_time_capsule.chrome_cdp.os.path.isfile",
                side_effect=lambda p: p == "/usr/bin/chromium",
            ),
            patch("tv_time_capsule.chrome_cdp.os.access", return_value=True),
        ):
            self.assertEqual(find_chrome(), "/usr/bin/chromium")

    def test_ensure_chromium_returns_system_binary(self):
        with patch(
            "tv_time_capsule.chrome_cdp.find_chrome",
            return_value="/usr/bin/chromium",
        ):
            self.assertEqual(ensure_chromium(log_label="test"), "/usr/bin/chromium")

    def test_ensure_chromium_without_system_chrome_returns_none(self):
        with patch("tv_time_capsule.chrome_cdp.find_chrome", return_value=None):
            self.assertIsNone(ensure_chromium(log_label="test"))

    def test_no_runtime_download_helpers(self):
        self.assertFalse(hasattr(mod, "chromium_download_url"))
        self.assertFalse(hasattr(mod, "chromium_platform_key"))
        self.assertFalse(hasattr(mod, "cache_dir"))


class ChromiumLeaseTests(unittest.TestCase):
    def setUp(self):
        shutdown_app_chromium()

    def tearDown(self):
        shutdown_app_chromium()

    def test_acquire_sets_owner(self):
        with patch("tv_time_capsule.chrome_cdp.kill_all_app_chromium"):
            acquire_chromium("weather", ports=9224)
            self.assertEqual(current_chromium_owner(), "weather")
            release_chromium("weather", kill=False)
            self.assertIsNone(current_chromium_owner())

    def test_acquire_displaces_previous_owner(self):
        displaced = MagicMock()
        with patch("tv_time_capsule.chrome_cdp.kill_all_app_chromium") as kill:
            acquire_chromium("weather", ports=9224, on_displace=displaced)
            acquire_chromium("youtube", ports=9227)
            displaced.assert_called_once()
            self.assertEqual(current_chromium_owner(), "youtube")
            # Force-reap on every acquire (single-instance guarantee).
            self.assertGreaterEqual(kill.call_count, 2)

    def test_stale_release_does_not_clear_new_owner(self):
        with patch("tv_time_capsule.chrome_cdp.kill_all_app_chromium"):
            acquire_chromium("weather", ports=9224)
            acquire_chromium("retro", ports=9225)
            release_chromium("weather", kill=False)  # stale
            self.assertEqual(current_chromium_owner(), "retro")


if __name__ == "__main__":
    unittest.main()
