"""Weather Channel overlay menu: pick presentation provider.

Pure stage machine + pygame draw helper. Persist / session restart stay in the app.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from ..config import C
from .resolve import ProviderId, normalize_provider

PROVIDER_ROWS: tuple[tuple[ProviderId, str], ...] = (
    ("auto", "Auto"),
    ("twc", "Weather.com"),
    ("ws4kp", "WS4KP"),
    ("native", "Native (Retro Weather)"),
)


@dataclass(frozen=True)
class WeatherMenuCommand:
    """Side-effect request produced by :meth:`WeatherMenu.handle`."""

    kind: str  # close | set_provider
    provider: ProviderId | None = None


class WeatherMenu:
    """Single-level Weather provider picker."""

    def __init__(self) -> None:
        self.open_: bool = False
        self.cursor: int = 0

    @property
    def is_open(self) -> bool:
        return self.open_

    def open(self, current: ProviderId | str | None = None) -> None:
        """Open with the current config provider focused."""
        self.open_ = True
        choice = normalize_provider(current)
        for i, (pid, _label) in enumerate(PROVIDER_ROWS):
            if pid == choice:
                self.cursor = i
                return
        self.cursor = 0

    def close(self) -> None:
        self.open_ = False
        self.cursor = 0

    def rows(self) -> list[tuple[ProviderId, str]]:
        return list(PROVIDER_ROWS)

    def handle(self, action: str) -> list[WeatherMenuCommand]:
        """Apply a navigation action; return side-effect commands for the app."""
        if not self.is_open or not action:
            return []

        rows = self.rows()
        if action == "back":
            self.close()
            return [WeatherMenuCommand("close")]

        n = len(rows)
        if self.cursor >= n:
            self.cursor = max(0, n - 1)

        if action == "up":
            self.cursor = (self.cursor - 1) % n
            return []
        if action == "down":
            self.cursor = (self.cursor + 1) % n
            return []
        if action != "select":
            return []

        pid, _label = rows[self.cursor % n]
        self.close()
        return [WeatherMenuCommand("set_provider", provider=pid)]


def draw_weather_menu(
    screen: pygame.Surface,
    *,
    font_md: pygame.font.Font,
    font_sm: pygame.font.Font,
    dim_color: tuple[int, int, int],
    menu: WeatherMenu,
    current: ProviderId | str | None = None,
) -> None:
    """Draw the Weather provider overlay when open."""
    if not menu.is_open:
        return
    rows = menu.rows()
    if not rows:
        return
    if menu.cursor >= len(rows):
        menu.cursor = max(0, len(rows) - 1)

    current_id = normalize_provider(current)
    sw, sh = screen.get_size()
    overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    screen.blit(overlay, (0, 0))

    box_w = min(420, sw - 40)
    line_h = font_sm.get_linesize() + 6
    header_h = 56
    visible = min(len(rows), max(6, (sh - 100) // line_h))
    box_h = min(sh - 40, header_h + visible * line_h + 48)
    box_x = (sw - box_w) // 2
    box_y = (sh - box_h) // 2
    pygame.draw.rect(
        screen, C.BG_CARD, (box_x, box_y, box_w, box_h), border_radius=10
    )
    pygame.draw.rect(
        screen, C.CYAN, (box_x, box_y, box_w, box_h), 2, border_radius=10
    )

    title = font_md.render("WEATHER PROVIDER", True, C.BRIGHT)
    screen.blit(title, title.get_rect(centerx=sw // 2, top=box_y + 14))

    list_top = box_y + header_h
    for i, (pid, label) in enumerate(rows):
        y = list_top + i * line_h
        focused = i == menu.cursor
        if focused:
            pygame.draw.rect(
                screen,
                C.CYAN,
                (box_x + 8, y - 2, box_w - 16, line_h),
                border_radius=4,
            )
        mark = "X" if pid == current_id else " "
        text = f"[{mark}] {label}"
        color = C.BLACK if focused else (C.GREEN if pid == current_id else C.WHITE)
        surf = font_sm.render(text, True, color)
        screen.blit(surf, (box_x + 20, y))

    hint = font_sm.render("enter select  |  esc back", True, dim_color)
    screen.blit(
        hint,
        hint.get_rect(centerx=sw // 2, bottom=box_y + box_h - 12),
    )


__all__ = [
    "PROVIDER_ROWS",
    "WeatherMenu",
    "WeatherMenuCommand",
    "draw_weather_menu",
]
