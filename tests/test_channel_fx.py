"""Tests for channel-change snow and shutdown effects."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pygame

from tv_time_capsule.channel_fx import (
    SNOW_FRAME_COUNT,
    ChannelChangeFX,
    draw_tv_shutdown,
)


class ChannelFxTests(unittest.TestCase):
    def setUp(self):
        self.screen = pygame.Surface((640, 480))
        self.snapshot = pygame.Surface((640, 480))
        self.snapshot.fill((40, 80, 120))

    def test_off_by_default(self):
        fx = ChannelChangeFX()
        self.assertFalse(fx.snow_enabled)
        self.assertFalse(fx.shutdown_enabled)

    def test_snow_only(self):
        fx = ChannelChangeFX(snow=True)
        self.assertTrue(fx.snow_enabled)
        self.assertFalse(fx.shutdown_enabled)

    def test_shutdown_only(self):
        fx = ChannelChangeFX(shutdown=True)
        self.assertFalse(fx.snow_enabled)
        self.assertTrue(fx.shutdown_enabled)

    def test_trigger_noop_when_off(self):
        fx = ChannelChangeFX(snow=False)
        fx.trigger()
        self.assertFalse(fx.is_active())

    def test_snow_defaults_audio_on(self):
        fx = ChannelChangeFX(snow=True)
        self.assertTrue(fx.audio_enabled)

    def test_snow_audio_can_be_disabled(self):
        fx = ChannelChangeFX(snow=True, audio=False)
        self.assertFalse(fx.audio_enabled)

    def test_trigger_plays_quiet_static(self):
        fx = ChannelChangeFX(snow=True)
        with patch.object(fx, "_ensure_sound") as ensure:
            with patch.object(fx, "_sound") as sound:
                fx.trigger()
                ensure.assert_called_once()
                sound.play.assert_called_once()

    def test_snow_triggers_and_draws(self):
        fx = ChannelChangeFX(snow=True, audio=False)
        fx.trigger()
        self.assertTrue(fx.is_active())
        with patch("pygame.time.get_ticks", return_value=0):
            fx.draw(self.screen)

    def test_snow_is_grayscale(self):
        fx = ChannelChangeFX(snow=True, audio=False)
        snow = fx._snow_frames[0]
        for x, y in ((10, 10), (100, 200), (300, 400)):
            r, g, b = snow.get_at((x, y))[:3]
            self.assertEqual(r, g)
            self.assertEqual(g, b)

    def test_snow_frames_precached_on_enable(self):
        fx = ChannelChangeFX(snow=True, audio=False)
        self.assertIsNotNone(fx._snow_frames)
        self.assertEqual(len(fx._snow_frames), SNOW_FRAME_COUNT)

    def test_snow_noise_matches_screen_size(self):
        fx = ChannelChangeFX(snow=True, audio=False)
        snow = fx._snow_frames[0]
        self.assertEqual(snow.get_size(), (640, 480))

    def test_draw_uses_precached_frames(self):
        fx = ChannelChangeFX(snow=True, audio=False)
        with patch.object(fx, "_build_snow_frame") as build:
            fx.trigger()
            with patch("pygame.time.get_ticks", side_effect=[0, 0, 16, 16]):
                fx.draw(self.screen)
                fx.draw(self.screen)
            build.assert_not_called()

    def test_shutdown_draw_phases(self):
        draw_tv_shutdown(self.screen, self.snapshot, 0.2)
        draw_tv_shutdown(self.screen, self.snapshot, 0.5)
        draw_tv_shutdown(self.screen, self.snapshot, 0.9)
        draw_tv_shutdown(self.screen, self.snapshot, 1.0)

    def test_shutdown_draw_centered_in_safe_zone_viewport(self):
        screen = pygame.Surface((704, 528))
        snapshot = pygame.Surface((704, 528))
        snapshot.fill((0, 0, 0))
        ui = pygame.Surface((640, 480))
        ui.fill((40, 80, 120))
        snapshot.blit(ui, (32, 24))
        draw_tv_shutdown(screen, snapshot, 0.5, viewport=(32, 24, 640, 480))
        # Collapse band should land inside the UI viewport, not at y=0.
        band_color = screen.get_at((320, 240))[:3]
        self.assertNotEqual(band_color, (0, 0, 0))
        margin_color = screen.get_at((10, 10))[:3]
        self.assertEqual(margin_color, (0, 0, 0))

    def test_shutdown_skipped_when_off(self):
        fx = ChannelChangeFX(shutdown=False)
        with patch("pygame.display.flip") as flip:
            fx.play_shutdown(self.screen, self.snapshot)
        flip.assert_not_called()


if __name__ == "__main__":
    unittest.main()
