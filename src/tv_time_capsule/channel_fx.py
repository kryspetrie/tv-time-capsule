"""CRT snow burst on channel changes and optional TV shutdown collapse.

Fun tweak — see docs/usage/fun-tweaks-and-easter-eggs.md. Snow frames are
pre-generated and cached when the effect is enabled (~320ms at 60fps).
"""

from __future__ import annotations

import array
import random

import pygame

from .config import SCREEN_H, SCREEN_W

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is a declared dependency
    np = None  # type: ignore[misc, assignment]

FX_DURATION_MS = 320
SHUTDOWN_DURATION_MS = 500
SHUTDOWN_BLACK_HOLD = 0.06
SNOW_SAMPLE_RATE = 22050
SNOW_AUDIO_VOLUME = 0.12
SNOW_FPS = 60
SNOW_FRAME_MS = max(1, 1000 // SNOW_FPS)
SNOW_FRAME_COUNT = max(1, (FX_DURATION_MS + SNOW_FRAME_MS - 1) // SNOW_FRAME_MS)


def _build_snow_noise_buffer() -> bytes:
    """~320 ms of quiet white noise for channel-tuning static."""
    n_samples = int(SNOW_SAMPLE_RATE * FX_DURATION_MS / 1000)
    samples = array.array(
        "h",
        (random.randint(-8000, 8000) for _ in range(n_samples)),
    )
    return samples.tobytes()


class ChannelChangeFX:
    """Fine B&W snow overlay and/or CRT shutdown animation."""

    def __init__(
        self,
        *,
        snow: bool = False,
        shutdown: bool = False,
        audio: bool | None = None,
    ):
        self.snow_enabled = bool(snow)
        self.shutdown_enabled = bool(shutdown)
        self._audio = bool(snow if audio is None else audio)
        self._active_start = 0
        self._active_until = 0
        self._snow_frames: list[pygame.Surface] | None = None
        self._sound: pygame.mixer.Sound | None = None
        if self.snow_enabled:
            self._precache_snow_frames()
        if self.snow_enabled and self._audio:
            self._init_sound()

    def _init_sound(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(
                    frequency=SNOW_SAMPLE_RATE, size=-16, channels=1, buffer=512
                )
            self._sound = pygame.mixer.Sound(buffer=_build_snow_noise_buffer())
            self._sound.set_volume(SNOW_AUDIO_VOLUME)
        except pygame.error:
            self._sound = None

    def _ensure_sound(self) -> None:
        if self._sound is None and self._audio:
            self._init_sound()

    def configure(
        self,
        *,
        snow: bool | None = None,
        shutdown: bool | None = None,
        audio: bool | None = None,
    ) -> None:
        if snow is not None:
            self.snow_enabled = bool(snow)
            if self.snow_enabled:
                self._precache_snow_frames()
            else:
                self._snow_frames = None
        if shutdown is not None:
            self.shutdown_enabled = bool(shutdown)
        if audio is not None:
            self._audio = bool(audio)
        if self.snow_enabled and self._audio:
            self._ensure_sound()

    @property
    def audio_enabled(self) -> bool:
        return self._audio

    def is_active(self) -> bool:
        return self.snow_enabled and pygame.time.get_ticks() < self._active_until

    def trigger(self) -> None:
        if not self.snow_enabled:
            return
        now = pygame.time.get_ticks()
        self._active_start = now
        self._active_until = now + FX_DURATION_MS
        if self._audio:
            self._ensure_sound()
            if self._sound is not None:
                self._sound.play()

    def _precache_snow_frames(self) -> None:
        """Pre-generate every static frame for one channel-tune burst."""
        self._snow_frames = [
            self._build_snow_frame() for _ in range(SNOW_FRAME_COUNT)
        ]

    def _build_snow_frame(self) -> pygame.Surface:
        """Dense B&W grain — half-res noise, nearest-neighbor upscale."""
        w = max(1, SCREEN_W // 2)
        h = max(1, SCREEN_H // 2)
        if np is not None:
            gray = np.random.randint(0, 256, (h, w), dtype=np.uint8)
            rgb = np.dstack((gray, gray, gray))
            tiny = pygame.image.frombuffer(rgb.tobytes(), (w, h), "RGB")
            return pygame.transform.scale(tiny, (SCREEN_W, SCREEN_H))
        tiny = pygame.Surface((w, h))
        for row in range(h):
            for col in range(w):
                shade = random.randint(0, 255)
                tiny.set_at((col, row), (shade, shade, shade))
        return pygame.transform.scale(tiny, (SCREEN_W, SCREEN_H))

    def _snow_frame_index(self) -> int:
        if not self._snow_frames:
            return 0
        elapsed = max(0, pygame.time.get_ticks() - self._active_start)
        return min(len(self._snow_frames) - 1, elapsed // SNOW_FRAME_MS)

    def draw(self, screen: pygame.Surface) -> None:
        if not self.is_active() or not self._snow_frames:
            return
        screen.blit(self._snow_frames[self._snow_frame_index()], (0, 0))

    def play_shutdown(self, screen: pygame.Surface, snapshot: pygame.Surface) -> None:
        """Classic CRT vertical collapse (~0.5s) before power-off."""
        if not self.shutdown_enabled:
            return
        clock = pygame.time.Clock()
        start = pygame.time.get_ticks()
        while True:
            elapsed = pygame.time.get_ticks() - start
            if elapsed >= SHUTDOWN_DURATION_MS:
                break
            progress = elapsed / SHUTDOWN_DURATION_MS
            draw_tv_shutdown(screen, snapshot, progress)
            pygame.display.flip()
            clock.tick(60)
        screen.fill((0, 0, 0))
        pygame.display.flip()


def _blur_surface(surf: pygame.Surface) -> pygame.Surface:
    """Light blur via downscale + smoothscale."""
    w, h = surf.get_size()
    small = pygame.transform.smoothscale(surf, (max(4, w // 4), max(3, h // 4)))
    return pygame.transform.smoothscale(small, (w, h))


def _ease_in_quad(t: float) -> float:
    """Slow start, accelerating finish (0..1 in, 0..1 out)."""
    t = max(0.0, min(1.0, t))
    return t * t


def draw_tv_shutdown(
    screen: pygame.Surface, snapshot: pygame.Surface, progress: float
) -> None:
    """Draw one frame of the CRT power-off collapse (progress 0..1)."""
    progress = max(0.0, min(1.0, progress))
    center_y = SCREEN_H // 2
    screen.fill((0, 0, 0))

    if progress < SHUTDOWN_BLACK_HOLD:
        return

    timeline = (progress - SHUTDOWN_BLACK_HOLD) / (1.0 - SHUTDOWN_BLACK_HOLD)
    collapse_end = 0.78

    if timeline < collapse_end:
        phase = _ease_in_quad(timeline / collapse_end)
        half_h = max(1, int((SCREEN_H * 0.5) * (1.0 - phase)))
        top_y = center_y - half_h
        band_h = max(1, half_h * 2)

        squashed = pygame.transform.smoothscale(snapshot, (SCREEN_W, band_h))
        squashed = _blur_surface(squashed)
        screen.blit(squashed, (0, top_y))

        bot_y = top_y + band_h
        top_inset = int(phase * SCREEN_W * 0.12)
        bot_inset = int(phase * SCREEN_W * 0.04)
        trap = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        points = [
            (top_inset, top_y),
            (SCREEN_W - top_inset, top_y),
            (SCREEN_W - bot_inset, bot_y),
            (bot_inset, bot_y),
        ]
        white_strength = int(80 + 175 * phase)
        pygame.draw.polygon(trap, (255, 255, 255, min(255, white_strength)), points)
        screen.blit(trap, (0, 0))
    else:
        fade = (timeline - collapse_end) / (1.0 - collapse_end)
        fade = _ease_in_quad(fade)
        line_h = max(1, int(3 * (1.0 - fade)))
        alpha = int(255 * (1.0 - fade))
        line = pygame.Surface((SCREEN_W, line_h), pygame.SRCALPHA)
        line.fill((255, 255, 255, alpha))
        screen.blit(line, (0, center_y - line_h // 2))
