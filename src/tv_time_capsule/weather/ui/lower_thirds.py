"""Persistent lower-thirds bar: time | marquee/location | logo."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pygame

from ..models import Alert
from . import theme as T
from .text import ascii_safe

_LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "retro-weather.png"


def bar_height(screen_h: int) -> int:
    return max(52, min(88, screen_h // 9))


@lru_cache(maxsize=1)
def _load_logo() -> pygame.Surface | None:
    if not _LOGO_PATH.is_file():
        return None
    try:
        return pygame.image.load(str(_LOGO_PATH)).convert_alpha()
    except Exception:
        return None


def logo_size_for_bar(bar_h: int) -> tuple[int, int]:
    """Logo is intentionally a bit taller than the bar so it overhangs upward."""
    logo = _load_logo()
    if logo is None:
        return (0, 0)
    lw, lh = logo.get_size()
    # ~20% taller than the bar → sits on the bottom edge and spills over the top.
    target_h = max(44, int(bar_h * 1.22))
    scale = target_h / max(1, lh)
    return (max(1, int(lw * scale)), max(1, int(lh * scale)))


def _fmt_clock() -> str:
    try:
        return datetime.now().strftime("%-I:%M %p")
    except ValueError:
        return datetime.now().strftime("%I:%M %p").lstrip("0")


class LowerThirds:
    """Bottom bar with clock, scrolling alerts (or location), and logo."""

    def __init__(self) -> None:
        self._alert_text = ""
        self._alert_surf: pygame.Surface | None = None
        self._x = 0.0
        self._last_key = ""

    def set_alerts(self, alerts: list[Alert], font: pygame.font.Font) -> None:
        if not alerts:
            if self._alert_text:
                self._alert_text = ""
                self._alert_surf = None
                self._last_key = ""
            return
        key = "|".join(f"{a.severity}:{a.headline}" for a in alerts)
        if key == self._last_key and self._alert_surf is not None:
            return
        self._last_key = key
        self._alert_text = ascii_safe(
            "   *   ".join(
                f"ALERT - {a.severity}: {a.headline}" for a in alerts
            )
            + "   *   "
        )
        self._alert_surf = font.render(self._alert_text, True, T.TEXT)
        self._x = 0.0

    def draw(
        self,
        screen: pygame.Surface,
        fonts: dict[str, pygame.font.Font],
        *,
        dt_ms: float,
        location_line: str | None = None,
        show_alerts: bool = True,
    ) -> int:
        """Draw the bar. Returns the Y coordinate of the top of the bar."""
        sw, sh = screen.get_size()
        h = bar_height(sh)
        y = sh - h
        pygame.draw.rect(screen, T.BG_PANEL, (0, y, sw, h))
        pygame.draw.line(screen, T.CYAN, (0, y), (sw, y), 2)

        clock = fonts["md"].render(_fmt_clock(), True, T.ACCENT)
        clock_x = 14
        screen.blit(clock, (clock_x, y + (h - clock.get_height()) // 2))
        left_edge = clock_x + clock.get_width() + 16

        logo = _load_logo()
        lw, lh = logo_size_for_bar(h)
        right_edge = sw - 12
        if logo is not None and lw > 0:
            right_edge = sw - lw - 12
            right_edge -= 12

        mid_left = left_edge
        mid_right = max(mid_left + 40, right_edge)
        mid_w = mid_right - mid_left
        mid_y = y + 4
        mid_h = h - 8

        use_alerts = show_alerts and self._alert_surf is not None and self._alert_text
        if use_alerts:
            pygame.draw.rect(screen, (90, 16, 16), (mid_left, mid_y, mid_w, mid_h))
            self._x -= dt_ms * 0.09
            surf = self._alert_surf
            assert surf is not None
            w = surf.get_width()
            if w > 0:
                while self._x < -w:
                    self._x += w
                clip = screen.get_clip()
                screen.set_clip(pygame.Rect(mid_left, mid_y, mid_w, mid_h))
                tx = mid_left + int(self._x)
                ty = mid_y + (mid_h - surf.get_height()) // 2
                screen.blit(surf, (tx, ty))
                screen.blit(surf, (tx + w, ty))
                screen.set_clip(clip)
        elif location_line:
            loc = fonts["md"].render(ascii_safe(location_line), True, T.CYAN)
            screen.blit(
                loc,
                loc.get_rect(centerx=(mid_left + mid_right) // 2, centery=y + h // 2),
            )

        # Draw logo last so it sits on the bottom edge and overhangs the bar top.
        if logo is not None and lw > 0:
            scaled = pygame.transform.smoothscale(logo, (lw, lh))
            logo_x = sw - lw - 12
            logo_y = sh - lh - 4
            screen.blit(scaled, (logo_x, logo_y))

        return y
