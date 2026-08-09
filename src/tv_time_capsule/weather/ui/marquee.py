"""Lower-thirds alert marquee."""

from __future__ import annotations

import pygame

from ..models import Alert
from . import theme as T


class AlertMarquee:
    def __init__(self) -> None:
        self._text = ""
        self._x = 0.0
        self._surf: pygame.Surface | None = None

    def set_alerts(self, alerts: list[Alert], font: pygame.font.Font) -> None:
        if not alerts:
            self._text = ""
            self._surf = None
            return
        parts = [f"{a.severity}: {a.headline}" for a in alerts]
        self._text = "   •   ".join(parts) + "   •   "
        self._surf = font.render(self._text, True, T.TEXT)
        self._x = 0.0

    def draw(self, screen: pygame.Surface, *, dt_ms: float) -> None:
        if self._surf is None or not self._text:
            return
        sw, sh = screen.get_size()
        band_h = max(28, sh // 14)
        y = sh - band_h
        pygame.draw.rect(screen, (80, 0, 0), (0, y, sw, band_h))
        pygame.draw.line(screen, T.ALERT, (0, y), (sw, y), 2)
        self._x -= dt_ms * 0.08
        w = self._surf.get_width()
        if w <= 0:
            return
        while self._x < -w:
            self._x += w
        x = int(self._x)
        screen.blit(self._surf, (x, y + (band_h - self._surf.get_height()) // 2))
        screen.blit(self._surf, (x + w, y + (band_h - self._surf.get_height()) // 2))
