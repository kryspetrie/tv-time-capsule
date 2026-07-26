"""Random analog-TV glitches: static, line tear, vertical roll.

Fun tweak for the show browser — see docs/usage/fun-tweaks-and-easter-eggs.md.
"""

from __future__ import annotations

import random

import pygame

GLITCH_DURATION_MS = 360
TICK_INTERVAL_MS = 250


class AnalogArtifacts:
    """Occasional brief signal defects over the current frame."""

    def __init__(self, *, enabled: bool = False, rate_per_minute: float = 12.0):
        self.enabled = bool(enabled)
        self._rate = max(0.0, float(rate_per_minute))
        self._active_until = 0
        self._started_at = 0
        self._last_check = 0
        self._static = False
        self._tear = False
        self._roll = False
        self._tear_offset = 0
        self._roll_speed = 0

    def configure(self, *, enabled: bool | None = None, rate_per_minute: float | None = None) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if rate_per_minute is not None:
            self._rate = max(0.0, float(rate_per_minute))

    @property
    def rate_per_minute(self) -> float:
        return self._rate

    def is_active(self) -> bool:
        return self.enabled and pygame.time.get_ticks() < self._active_until

    def tick(self) -> None:
        if not self.enabled or self._rate <= 0:
            return
        now = pygame.time.get_ticks()
        if now < self._active_until:
            return
        if now - self._last_check < TICK_INTERVAL_MS:
            return
        self._last_check = now
        if random.random() >= self._rate * (TICK_INTERVAL_MS / 60000.0):
            return
        self._trigger(now)

    def _trigger(self, now: int) -> None:
        self._started_at = now
        self._active_until = now + GLITCH_DURATION_MS
        pick = random.choice(("static", "tear", "roll"))
        self._static = pick in ("static", "tear")
        self._tear = pick == "tear"
        self._roll = pick == "roll"
        self._tear_offset = random.randint(16, 48)
        self._roll_speed = random.randint(48, 120)

    def apply(self, screen: pygame.Surface) -> None:
        if not self.is_active():
            return

        elapsed = pygame.time.get_ticks() - self._started_at
        if self._roll:
            self._apply_roll(screen, elapsed)
        if self._tear:
            self._apply_tear(screen)
        if self._static:
            self._apply_static(screen)

    def _apply_static(self, screen: pygame.Surface) -> None:
        """Dense white speckle overlay."""
        width, height = screen.get_size()
        w = max(1, width // 2)
        h = max(1, height // 2)
        tiny = pygame.Surface((w, h), pygame.SRCALPHA)
        for row in range(h):
            for col in range(w):
                if random.random() > 0.35:
                    continue
                alpha = random.randint(90, 220)
                tiny.set_at((col, row), (255, 255, 255, alpha))
        noise = pygame.transform.scale(tiny, (width, height))
        screen.blit(noise, (0, 0))

    def _apply_tear(self, screen: pygame.Surface) -> None:
        width, height = screen.get_size()
        snap = screen.copy()
        offset = self._tear_offset
        for y in range(height):
            line_off = offset if y % 2 == 0 else -offset
            screen.blit(snap, (line_off, y), (0, y, width, 1))

    def _apply_roll(self, screen: pygame.Surface, elapsed: int) -> None:
        width, height = screen.get_size()
        snap = screen.copy()
        shift = int((elapsed / 1000.0) * self._roll_speed) % height
        screen.blit(snap, (0, shift))
        screen.blit(snap, (0, shift - height))
        bar_h = max(10, height // 12)
        bar_y = (shift + height // 3) % height
        bar = pygame.Surface((width, bar_h), pygame.SRCALPHA)
        bar.fill((255, 255, 255, 140))
        screen.blit(bar, (0, bar_y))
        static_band = pygame.Surface((width, bar_h // 2), pygame.SRCALPHA)
        for x in range(0, width, 2):
            if random.random() < 0.5:
                pygame.draw.line(static_band, (255, 255, 255, 180), (x, 0), (x, bar_h // 2))
        screen.blit(static_band, (0, bar_y))
