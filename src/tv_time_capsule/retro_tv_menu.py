"""Retro TV overlay menu: Change Channel + Channel Setup (filters).

Pure stage machine + pygame draw helper. Side effects (advance clip, Chrome
filter toggles, persist) stay in the app.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

import pygame

from .config import C


class MenuStage(str, Enum):
    CLOSED = "closed"
    ROOT = "root"
    SETUP = "setup"


@dataclass(frozen=True)
class MenuCommand:
    """Side-effect request produced by :meth:`RetroTvMenu.handle`."""

    kind: str  # close | change_channel | select_all | select_none | toggle_filter
    filter_id: str | None = None


ROOT_ROWS: tuple[tuple[str, str, bool | None], ...] = (
    ("change", "Change Channel", None),
    ("setup", "Channel Setup", None),
)


def setup_rows(
    filters: Sequence[dict[str, Any]] | None,
) -> list[tuple[str, str, bool | None]]:
    """Build Channel Setup rows from a MyRetroTVs filter snapshot."""
    rows: list[tuple[str, str, bool | None]] = [
        ("all", "Select All", None),
        ("none", "Select None", None),
    ]
    for item in filters or ():
        rows.append(
            (str(item["id"]), str(item["name"]), bool(item.get("on")))
        )
    return rows


class RetroTvMenu:
    """Two-level Decades menu (root → optional Channel Setup)."""

    def __init__(self) -> None:
        self.stage: MenuStage = MenuStage.CLOSED
        self.cursor: int = 0

    @property
    def is_open(self) -> bool:
        return self.stage is not MenuStage.CLOSED

    def open(self) -> None:
        """Open at root with Change Channel focused."""
        self.stage = MenuStage.ROOT
        self.cursor = 0

    def close(self) -> None:
        self.stage = MenuStage.CLOSED
        self.cursor = 0

    def rows(
        self, filters: Sequence[dict[str, Any]] | None = None
    ) -> list[tuple[str, str, bool | None]]:
        if self.stage is MenuStage.SETUP:
            return setup_rows(filters)
        if self.stage is MenuStage.ROOT:
            return list(ROOT_ROWS)
        return []

    def handle(
        self,
        action: str,
        filters: Sequence[dict[str, Any]] | None = None,
    ) -> list[MenuCommand]:
        """Apply a navigation action; return side-effect commands for the app."""
        if not self.is_open or not action:
            return []

        rows = self.rows(filters)
        if action == "back":
            if self.stage is MenuStage.SETUP:
                self.stage = MenuStage.ROOT
                self.cursor = 1  # Channel Setup
                return []
            self.close()
            return [MenuCommand("close")]

        if not rows:
            return []

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

        kind, _label, _on = rows[self.cursor % n]
        if self.stage is MenuStage.ROOT:
            if kind == "change":
                self.close()
                return [MenuCommand("change_channel")]
            if kind == "setup":
                self.stage = MenuStage.SETUP
                self.cursor = 0
                return []
            return []

        # Setup stage
        if kind == "all":
            return [MenuCommand("select_all")]
        if kind == "none":
            return [MenuCommand("select_none")]
        return [MenuCommand("toggle_filter", filter_id=kind)]


def draw_retro_tv_menu(
    screen: pygame.Surface,
    *,
    font_md: pygame.font.Font,
    font_sm: pygame.font.Font,
    dim_color: tuple[int, int, int],
    menu: RetroTvMenu,
    filters: Sequence[dict[str, Any]] | None = None,
) -> None:
    """Draw the Retro TV overlay for the current menu stage."""
    if not menu.is_open:
        return
    rows = menu.rows(filters)
    if not rows:
        return
    if menu.cursor >= len(rows):
        menu.cursor = max(0, len(rows) - 1)

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

    title_text = (
        "CHANNEL SETUP" if menu.stage is MenuStage.SETUP else "RETRO TV"
    )
    title = font_md.render(title_text, True, C.BRIGHT)
    screen.blit(title, title.get_rect(centerx=sw // 2, top=box_y + 14))

    first = 0
    if len(rows) > visible:
        first = max(
            0,
            min(menu.cursor - visible // 2, len(rows) - visible),
        )

    list_top = box_y + header_h
    for i in range(first, min(first + visible, len(rows))):
        kind, label, on = rows[i]
        y = list_top + (i - first) * line_h
        focused = i == menu.cursor
        if focused:
            pygame.draw.rect(
                screen,
                C.CYAN,
                (box_x + 8, y - 2, box_w - 16, line_h),
                border_radius=4,
            )
        if menu.stage is MenuStage.ROOT or kind in ("all", "none"):
            mark = "*" if focused else " "
            text = f" {mark} {label}"
            color = C.BLACK if focused else C.GREEN
        else:
            mark = "X" if on else " "
            text = f"[{mark}] {label}"
            color = C.BLACK if focused else (C.GREEN if on else C.WHITE)
        surf = font_sm.render(text, True, color)
        screen.blit(surf, (box_x + 20, y))

    if menu.stage is MenuStage.SETUP:
        hint_text = "enter toggle  |  esc back"
    else:
        hint_text = "enter select  |  esc close"
    hint = font_sm.render(hint_text, True, dim_color)
    screen.blit(
        hint, hint.get_rect(centerx=sw // 2, bottom=box_y + box_h - 12)
    )
