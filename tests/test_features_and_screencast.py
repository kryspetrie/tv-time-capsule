"""Tests for features flags and weather screencast adapt."""

from __future__ import annotations

import unittest

from tv_time_capsule.config import parse_config
from tv_time_capsule.screencast_adapt import (
    ScreencastAdaptState,
    ScreencastParams,
    initial_screencast_params,
    observe_frame_latency,
)


class FeaturesConfigTests(unittest.TestCase):
    def test_defaults_all_on(self):
        cfg = parse_config({})
        self.assertTrue(cfg["features"]["weather"])
        self.assertTrue(cfg["features"]["retro_tv"])
        self.assertTrue(cfg["features"]["youtube"])

    def test_parse_false(self):
        cfg = parse_config(
            {"features": {"youtube": False, "weather": False, "retro_tv": False}}
        )
        self.assertFalse(cfg["features"]["youtube"])
        self.assertFalse(cfg["features"]["weather"])
        self.assertFalse(cfg["features"]["retro_tv"])


class WeatherScreencastConfigTests(unittest.TestCase):
    def test_defaults(self):
        cfg = parse_config({})
        sc = cfg["weather"]["screencast"]
        self.assertEqual(sc["mode"], "auto")
        self.assertEqual(sc["min_fps"], 1.0)
        self.assertEqual(sc["max_fps"], 15.0)
        self.assertIsNone(sc["target_fps"])

    def test_fixed_target_clamped(self):
        cfg = parse_config(
            {
                "weather": {
                    "screencast": {
                        "mode": "fixed",
                        "target_fps": 100,
                        "min_fps": 1,
                        "max_fps": 5,
                    }
                }
            }
        )
        self.assertEqual(cfg["weather"]["screencast"]["target_fps"], 5.0)


class ScreencastAdaptTests(unittest.TestCase):
    def test_controller_step_down_on_high_latency(self):
        cfg = {"mode": "auto", "min_fps": 1, "max_fps": 15, "jpeg_quality": 80}
        params = ScreencastParams(1, 80, 640, 480, 15.0)
        state = ScreencastAdaptState(params=params, samples=8, ema_latency_ms=100)
        state, restart = observe_frame_latency(
            state, 400, cfg, canvas_w=640, canvas_h=480
        )
        self.assertTrue(restart)
        self.assertGreater(state.params.every_nth_frame, 1)

    def test_controller_respects_min_fps_floor(self):
        cfg = {"mode": "auto", "min_fps": 5, "max_fps": 15, "jpeg_quality": 80}
        # Force many step-downs
        params = ScreencastParams(1, 80, 640, 480, 15.0)
        state = ScreencastAdaptState(params=params)
        for _ in range(40):
            state, _ = observe_frame_latency(
                state, 500, cfg, canvas_w=640, canvas_h=480
            )
        self.assertGreaterEqual(state.params.effective_fps, 5.0 - 0.5)

    def test_fixed_mode_no_adapt(self):
        cfg = {"mode": "fixed", "target_fps": 2, "min_fps": 1, "max_fps": 15}
        params = initial_screencast_params(cfg, canvas_w=640, canvas_h=480)
        state = ScreencastAdaptState(params=params, samples=20)
        state2, restart = observe_frame_latency(
            state, 999, cfg, canvas_w=640, canvas_h=480
        )
        self.assertFalse(restart)
        self.assertEqual(state2.params.every_nth_frame, params.every_nth_frame)


if __name__ == "__main__":
    unittest.main()
