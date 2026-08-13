"""Tests for Chromium discovery helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tv_time_capsule.chrome_cdp import ensure_chromium, find_chrome


class ChromiumDiscoveryTests(unittest.TestCase):
    def test_find_chrome_uses_path(self):
        with patch("tv_time_capsule.chrome_cdp.shutil.which", side_effect=lambda n: "/usr/bin/chromium" if n == "chromium" else None):
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
        import tv_time_capsule.chrome_cdp as mod

        self.assertFalse(hasattr(mod, "chromium_download_url"))
        self.assertFalse(hasattr(mod, "chromium_platform_key"))
        self.assertFalse(hasattr(mod, "cache_dir"))


if __name__ == "__main__":
    unittest.main()
