"""Secret show-list test patterns (channels 0, 00, 000).

Place your own ``colorbars.png``, ``grid.png``, and ``indianhead.png`` in
``src/tv_time_capsule/assets/``. The app never generates or overwrites them.
"""

from __future__ import annotations

from pathlib import Path

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Dial string on the show browser → bundled PNG filename.
SHOW_LIST_TEST_PATTERNS: dict[str, str] = {
    "0": "colorbars.png",
    "00": "grid.png",
    "000": "indianhead.png",
}


def pattern_asset_path(dial: str) -> Path | None:
    """Return the asset path for a secret dial code, or None."""
    name = SHOW_LIST_TEST_PATTERNS.get(dial)
    if not name:
        return None
    path = _ASSETS_DIR / name
    return path if path.is_file() else None


def is_show_list_test_dial(dial: str) -> bool:
    return dial in SHOW_LIST_TEST_PATTERNS
