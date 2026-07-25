"""Bouncing VHS logo screensaver."""

from __future__ import annotations

import random
from pathlib import Path

import pygame

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VHS_LOGO_PATH = _ASSETS_DIR / "vhs.bmp"
LOGO_SCALE = 2.0

DEFAULT_TIMEOUT_S = 300
MIN_TIMEOUT_S = 10


def parse_screensaver_config(raw: dict | None) -> dict:
    """Normalize ``screensaver`` settings from config JSON."""
    ss = raw or {}
    if not isinstance(ss, dict):
        ss = {}
    enabled = bool(ss.get("enabled", False))
    try:
        timeout = int(ss.get("timeout_seconds", DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_S
    timeout = max(MIN_TIMEOUT_S, timeout)
    return {"enabled": enabled, "timeout_seconds": timeout}


class VHSScreensaver:
    """DVD-style bouncing logo with multiply tint on each wall bounce."""

    def __init__(self, screen_w: int, screen_h: int, logo_path: Path | None = None):
        path = logo_path or VHS_LOGO_PATH
        if not path.is_file():
            raise FileNotFoundError(f"VHS screensaver asset not found: {path}")

        base = pygame.image.load(str(path)).convert_alpha()
        if LOGO_SCALE != 1.0:
            w, h = base.get_size()
            size = (max(1, int(w * LOGO_SCALE)), max(1, int(h * LOGO_SCALE)))
            base = pygame.transform.scale(base, size)
        max_w = int(screen_w * 0.42)
        if base.get_width() > max_w:
            scale = max_w / base.get_width()
            size = (max(1, int(base.get_width() * scale)), max(1, int(base.get_height() * scale)))
            base = pygame.transform.scale(base, size)

        self.base = base
        self.w, self.h = base.get_size()
        self.screen_w = screen_w
        self.screen_h = screen_h

        speed = random.uniform(110.0, 170.0)
        angle = random.uniform(0.35, 1.15)
        sign_x = random.choice((-1, 1))
        sign_y = random.choice((-1, 1))
        self.vx = sign_x * speed * random.uniform(0.75, 1.0)
        self.vy = sign_y * speed * random.uniform(0.75, 1.0)
        if abs(self.vx) < 40:
            self.vx = sign_x * 40.0
        if abs(self.vy) < 40:
            self.vy = sign_y * 40.0

        self.x = float(random.randint(0, max(0, screen_w - self.w)))
        self.y = float(random.randint(0, max(0, screen_h - self.h)))
        self.color = (255, 255, 255)
        self.sprite = self._tint(self.color)

    def _tint(self, color: tuple[int, int, int]) -> pygame.Surface:
        surf = self.base.copy()
        surf.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
        return surf

    def randomize_color(self) -> None:
        self.color = (
            random.randint(64, 255),
            random.randint(64, 255),
            random.randint(64, 255),
        )
        self.sprite = self._tint(self.color)

    def update(self, dt: float) -> bool:
        """Advance position. Returns True if the logo bounced off an edge."""
        bounced = False
        self.x += self.vx * dt
        self.y += self.vy * dt

        if self.x <= 0:
            self.x = 0.0
            self.vx = abs(self.vx)
            bounced = True
        elif self.x + self.w >= self.screen_w:
            self.x = float(self.screen_w - self.w)
            self.vx = -abs(self.vx)
            bounced = True

        if self.y <= 0:
            self.y = 0.0
            self.vy = abs(self.vy)
            bounced = True
        elif self.y + self.h >= self.screen_h:
            self.y = float(self.screen_h - self.h)
            self.vy = -abs(self.vy)
            bounced = True

        return bounced

    def draw(self, target: pygame.Surface) -> None:
        target.fill((0, 0, 0))
        target.blit(self.sprite, (int(self.x), int(self.y)))
