"""Persistent Retro Weather channel bug (corner logo)."""

from __future__ import annotations

from pathlib import Path

import pygame


_LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "retro-weather.png"
# False = not loaded yet; None = missing file; Surface = ready.
_logo_cache: pygame.Surface | None | bool = False


def _load_logo() -> pygame.Surface | None:
    """Load the channel logo; retry convert_alpha until the display is ready."""
    global _logo_cache
    if isinstance(_logo_cache, pygame.Surface):
        return _logo_cache
    if _logo_cache is None:
        return None
    if not _LOGO_PATH.is_file():
        _logo_cache = None
        return None
    try:
        surf = pygame.image.load(str(_LOGO_PATH))
        if pygame.display.get_init() and pygame.display.get_surface() is not None:
            try:
                surf = surf.convert_alpha()
            except Exception:
                return surf
            _logo_cache = surf
            return surf
        return surf
    except Exception:
        return None


def draw_retro_weather_bug(
    screen: pygame.Surface,
    font: pygame.font.Font | None = None,
    *,
    margin: int = 12,
) -> None:
    """Draw the ``retro-weather.png`` logo in the lower-right corner."""
    del font  # kept for call-site compatibility
    logo = _load_logo()
    if logo is None:
        return
    sw, sh = screen.get_size()
    # Keep a square-ish bug; don't dominate short screens.
    target = max(64, min(120, sw // 7, sh // 5))
    lw, lh = logo.get_size()
    scale = target / max(lw, lh)
    size = (max(1, int(lw * scale)), max(1, int(lh * scale)))
    if size != (lw, lh):
        logo = pygame.transform.smoothscale(logo, size)
    x = sw - size[0] - margin
    y = sh - size[1] - margin
    screen.blit(logo, (x, y))
