"""Tests for features flags and weather screencast adapt."""

from __future__ import annotations

import unittest

from tv_time_capsule.config import parse_config
from tv_time_capsule.screencast_adapt import (
    ScreencastAdaptState,
    ScreencastParams,
    initial_screencast_params,
    observe_frame_latency,
    observe_present_stats,
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

    def test_low_present_fps_steps_nth_up(self):
        cfg = {"mode": "auto", "min_fps": 1, "max_fps": 15, "jpeg_quality": 80}
        params = ScreencastParams(1, 80, 640, 480, 15.0)
        state = ScreencastAdaptState(params=params)
        saw_restart = False
        for _ in range(12):
            # UI stuck ~3 FPS while CDP targets 15.
            state, restart = observe_present_stats(
                state, 3.0, 40.0, cfg, canvas_w=640, canvas_h=480
            )
            if restart:
                saw_restart = True
                break
        self.assertTrue(saw_restart)
        self.assertGreater(state.params.every_nth_frame, 1)

    def test_high_blit_ms_steps_down(self):
        cfg = {"mode": "auto", "min_fps": 1, "max_fps": 15, "jpeg_quality": 80}
        params = ScreencastParams(2, 80, 640, 480, 7.5)
        state = ScreencastAdaptState(params=params)
        saw_restart = False
        for _ in range(12):
            state, restart = observe_present_stats(
                state, 8.0, 300.0, cfg, canvas_w=640, canvas_h=480
            )
            if restart:
                saw_restart = True
                break
        self.assertTrue(saw_restart)
        self.assertTrue(
            state.params.every_nth_frame > 2 or state.params.quality < 80
        )

    def test_healthy_present_and_latency_can_step_up(self):
        cfg = {"mode": "auto", "min_fps": 1, "max_fps": 15, "jpeg_quality": 80}
        params = ScreencastParams(4, 60, 640, 480, 3.75)
        state = ScreencastAdaptState(
            params=params,
            samples=10,
            ema_latency_ms=40.0,
            present_samples=10,
            ema_present_fps=8.0,
            ema_blit_ms=40.0,
        )
        # One more healthy present sample with headroom → lower nth.
        state, restart = observe_present_stats(
            state, 9.0, 35.0, cfg, canvas_w=640, canvas_h=480
        )
        self.assertTrue(restart)
        self.assertLess(state.params.every_nth_frame, 4)

    def test_latency_step_up_blocked_when_present_stressed(self):
        cfg = {"mode": "auto", "min_fps": 1, "max_fps": 15, "jpeg_quality": 80}
        params = ScreencastParams(3, 80, 640, 480, 5.0)
        state = ScreencastAdaptState(
            params=params,
            samples=8,
            ema_latency_ms=40.0,
            present_samples=10,
            ema_present_fps=1.5,
            ema_blit_ms=50.0,
        )
        state2, restart = observe_frame_latency(
            state, 40.0, cfg, canvas_w=640, canvas_h=480
        )
        self.assertFalse(restart)
        self.assertEqual(state2.params.every_nth_frame, 3)

    def test_fixed_mode_ignores_present_stats(self):
        cfg = {"mode": "fixed", "target_fps": 2, "min_fps": 1, "max_fps": 15}
        params = initial_screencast_params(cfg, canvas_w=640, canvas_h=480)
        state = ScreencastAdaptState(params=params, present_samples=20)
        state2, restart = observe_present_stats(
            state, 1.0, 400.0, cfg, canvas_w=640, canvas_h=480
        )
        self.assertFalse(restart)
        self.assertEqual(state2.params.every_nth_frame, params.every_nth_frame)

    def test_load_stress_steps_down(self):
        cfg = {"mode": "auto", "min_fps": 1, "max_fps": 15, "jpeg_quality": 80}
        params = ScreencastParams(1, 80, 640, 480, 15.0)
        state = ScreencastAdaptState(params=params)
        saw_restart = False
        for _ in range(12):
            state, restart = observe_present_stats(
                state,
                20.0,
                30.0,
                cfg,
                canvas_w=640,
                canvas_h=480,
                load_per_cpu=2.0,
            )
            if restart:
                saw_restart = True
                break
        self.assertTrue(saw_restart)
        self.assertGreater(state.params.every_nth_frame, 1)


if __name__ == "__main__":
    unittest.main()
