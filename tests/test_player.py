"""Unit tests for player helpers (no ffmpeg required)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tv_time_capsule.player import (
    EmbeddedPlayer,
    build_ffmpeg_decode_cmd,
    resolve_hwaccel,
)


class PlayerHelperTests(unittest.TestCase):
    def test_build_ffmpeg_decode_cmd(self):
        cmd = build_ffmpeg_decode_cmd(
            "/usr/bin/ffmpeg",
            "/media/show/ep.mp4",
            640,
            480,
            resume_pos=10.0,
            hwaccel="v4l2m2m",
        )
        self.assertEqual(cmd[0], "/usr/bin/ffmpeg")
        self.assertIn("-ss", cmd)
        self.assertIn("10.0", cmd)
        self.assertIn("-hwaccel", cmd)
        self.assertIn("v4l2m2m", cmd)
        self.assertIn("-pix_fmt", cmd)
        self.assertIn("rgb24", cmd)

    @patch("tv_time_capsule.player.is_pi", return_value=False)
    def test_resolve_hwaccel_off_on_desktop(self, _pi):
        self.assertIsNone(
            resolve_hwaccel("auto", "/usr/bin/ffmpeg", "/media/ep.mp4")
        )

    @patch("tv_time_capsule.player.get_video_codec", return_value="h264")
    @patch("tv_time_capsule.player.probe_hwaccel", return_value="v4l2m2m")
    @patch("tv_time_capsule.player.is_pi", return_value=True)
    def test_resolve_hwaccel_auto_h264(self, _pi, _probe, _codec):
        self.assertEqual(
            resolve_hwaccel("auto", "/usr/bin/ffmpeg", "/media/ep.mp4"),
            "v4l2m2m",
        )

    def test_check_stall_no_frames_after_grace(self):
        player = EmbeddedPlayer(640, 480)
        player.running = True
        player._playback_started_at = 0.0
        player._last_frame_at = 0.0
        with patch("tv_time_capsule.player.time") as mock_time:
            mock_time.monotonic.return_value = 15.0
            self.assertTrue(player.check_stall())

    def test_check_stall_recent_frame(self):
        player = EmbeddedPlayer(640, 480)
        player.running = True
        player._playback_started_at = 0.0
        player._last_frame_at = 10.0
        with patch("tv_time_capsule.player.time") as mock_time:
            mock_time.monotonic.return_value = 15.0
            self.assertFalse(player.check_stall())


if __name__ == "__main__":
    unittest.main()
