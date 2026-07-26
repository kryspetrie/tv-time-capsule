"""Font compatibility layer for pygame (incl. Python 3.14+ freetype fallback)."""

from __future__ import annotations

import os
from pathlib import Path

import pygame

# pygame.font broken on Python 3.14+ (circular import). Use _freetype fallback.
USE_FREETYPE = False

# VCR OSD Mono for that vintage CRT look (bundled package asset)
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FONT_FILE = str(_ASSETS_DIR / "vcr_osd_mono.ttf")


class FTFontWrapper:
    """Wraps pygame._freetype.Font to match pygame.font.Font's render() API."""

    def __init__(self, name, size, freetype_mod):
        self._font = freetype_mod.Font(name, size)
        self._size = size

    def render(self, text, antialias, color):
        surf, _rect = self._font.render(text, color)
        return surf

    def size(self, text):
        r = self._font.get_rect(text)
        # get_sized_height() gives the full line height (ascent+descent),
        # not just the tight glyph bounding box that get_rect returns.
        line_h = self._font.get_sized_height()
        return (r.width, max(r.height, line_h))

    def get_linesize(self):
        return self._font.get_sized_height()

    def get_height(self):
        return self._font.get_sized_height()


def make_font(size):
    """Return a font object with a unified .render() -> Surface API.

    Uses VCR OSD Mono if available, falls back to pygame default.
    """
    font_path = FONT_FILE if os.path.isfile(FONT_FILE) else None
    if USE_FREETYPE:
        return FTFontWrapper(font_path, size, pygame._freetype)
    return pygame.font.Font(font_path, size)


def enable_freetype_fallback() -> None:
    """Switch font creation to pygame._freetype after a failed pygame.font probe."""
    global USE_FREETYPE
    USE_FREETYPE = True
    pygame._freetype.init()
