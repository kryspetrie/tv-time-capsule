"""Smoke tests for the local admin HTTP API."""

from __future__ import annotations

import json
import os
import threading
import unittest
import urllib.request
from typing import Any
from unittest.mock import patch

from tv_time_capsule.web_admin import (
    AdminHandler,
    _AdminHTTPServer,
    _clear_admin_pid,
    _read_admin_pid,
    _write_admin_pid,
    create_admin_httpd,
    stop_previous_admin_server,
    verify_admin_reachable,
)
from tv_time_capsule.fonts import FTFontWrapper


class _MockContext:
    def admin_status(self) -> dict[str, Any]:
        return {"shows": 2, "playing": False}

    def admin_shows(self) -> list[str]:
        return ["Alpha", "Beta"]

    def admin_channels(self) -> dict[str, Any]:
        return {"order": ["Alpha"], "numbers": {"Alpha": 1}, "shows": self.admin_shows()}

    def admin_save_channels(self, order: list[str], numbers: dict[str, int]) -> None:
        self.saved = (order, numbers)

    def admin_request_rescan(self) -> tuple[bool, str]:
        return True, "queued"

    def admin_watch_summary(self) -> dict[str, Any]:
        return {"Alpha": {"s01": {"ep": 1}}}

    def admin_keymap(self) -> dict[str, Any]:
        return {
            "keyboard": [
                {"action": "up", "label": "Up", "key": "up"},
                {"action": "reset", "label": "Reset watch status", "key": "r"},
            ],
            "gamepad": [
                {"action": "select", "label": "Select / pause", "binding": "button-0"},
            ],
        }

    def admin_library(self) -> dict[str, Any]:
        return {"shows": 2, "episodes": 5, "tree": [], "media_paths": ["/media"]}

    def admin_config_get(self) -> dict[str, Any]:
        return {"path": "/tmp/config.json", "config": {"media_paths": ["/media"]}}

    def admin_config_save(self, raw: dict) -> tuple[bool, str]:
        self.saved_config = raw
        return True, "saved"

    def admin_config_reload(self) -> tuple[bool, str]:
        return True, "reloaded"

    def admin_settings(self) -> dict[str, Any]:
        return {
            "channel_snow": False,
            "shutdown_collapse": False,
            "cli_overrides": {},
        }

    def admin_update_settings(self, patch: dict) -> tuple[bool, str]:
        self.settings_patch = patch
        return True, "updated"

    def admin_verify_path(self, path: str) -> dict[str, Any]:
        return {"ok": True, "path": path, "message": "ok"}

    def admin_verify_mount(self, index: int) -> dict[str, Any]:
        return {"ok": True, "index": index, "message": "mounted"}

    def admin_scan_library(
        self, paths: list[str] | None = None, *, apply: bool = False
    ) -> dict[str, Any]:
        return {"ok": True, "shows": 1, "episodes": 3, "applied": apply, "tree": []}

    def admin_update_paths(self, patch: dict) -> tuple[bool, str]:
        self.paths_patch = patch
        return True, "paths updated"


class WebAdminTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _MockContext()
        self.httpd = _AdminHTTPServer(("127.0.0.1", 0), AdminHandler, self.ctx)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=3
        ) as resp:
            return json.loads(resp.read().decode())

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())

    def test_status_ok(self):
        data = self._get("/api/status")
        self.assertEqual(data["shows"], 2)

    def test_save_channels(self):
        out = self._post(
            "/api/channels",
            {"order": ["Beta", "Alpha"], "numbers": {"Beta": 2}},
        )
        self.assertTrue(out["ok"])
        self.assertEqual(self.ctx.saved[0], ["Beta", "Alpha"])

    def test_rescan(self):
        out = self._post("/api/rescan", {})
        self.assertTrue(out["ok"])

    def test_keymap(self):
        data = self._get("/api/keymap")
        self.assertIn("keyboard", data)
        self.assertEqual(data["keyboard"][0]["key"], "up")
        self.assertIn("gamepad", data)

    def test_library(self):
        data = self._get("/api/library")
        self.assertEqual(data["shows"], 2)

    def test_settings_get_and_post(self):
        data = self._get("/api/settings")
        self.assertIn("channel_snow", data)
        out = self._post("/api/settings", {"channel_snow": True})
        self.assertTrue(out["ok"])

    def test_config_get(self):
        data = self._get("/api/config")
        self.assertIn("config", data)

    def test_paths_verify(self):
        out = self._post("/api/paths/verify", {"path": "/media"})
        self.assertTrue(out["ok"])

    def test_library_scan(self):
        out = self._post("/api/library/scan", {"paths": ["/media"], "apply": False})
        self.assertTrue(out["ok"])

    def test_dual_stack_localhost(self):
        httpd = create_admin_httpd("0.0.0.0", 0, self.ctx)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            ok, host = verify_admin_reachable(port)
            self.assertTrue(ok, "admin should be reachable via 127.0.0.1 or ::1")
            self.assertIn(host, ("127.0.0.1", "::1", "localhost"))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class AdminLifecycleTests(unittest.TestCase):
    def tearDown(self):
        _clear_admin_pid()

    @patch("tv_time_capsule.web_admin._pids_listening_on_port", return_value=[])
    @patch("tv_time_capsule.web_admin._terminate_pid")
    @patch("tv_time_capsule.web_admin._pid_is_running", return_value=True)
    def test_stop_previous_admin_server_uses_pid_file(
        self, _running, terminate, _port_pids
    ):
        _write_admin_pid()
        stop_previous_admin_server(8765)
        terminate.assert_called_once()
        self.assertIsNone(_read_admin_pid())

    def test_ft_font_wrapper_exposes_get_height(self):
        self.assertTrue(hasattr(FTFontWrapper, "get_height"))


if __name__ == "__main__":
    unittest.main()
