"""Home / library picker rows: shows, movies, and pinned special channels."""

from __future__ import annotations

from typing import Any

# Parent default: Continue + library + Weather + TV Guide.
DEFAULT_HOME_MENU_TOKENS: tuple[str, ...] = (
    "continue",
    "shows",
    "movies",
    "weather",
    "tvguide",
)

# Kids default: Shows / Movies only — drives the full-bleed dual-tile home UI
# with cycling poster art (not the parent text stack).
DEFAULT_KIDS_HOME_MENU_TOKENS: tuple[str, ...] = (
    "shows",
    "movies",
)

_DECADE_TOKEN_TO_SLUG: dict[str, str] = {
    "1950s": "50",
    "1960s": "60",
    "1970s": "70",
    "1980s": "80",
    "1990s": "90",
    "2000s": "00",
}

_DECADE_SLUG_TO_LABEL: dict[str, str] = {
    "50": "1950s",
    "60": "1960s",
    "70": "1970s",
    "80": "1980s",
    "90": "1990s",
    "00": "2000s",
}

_DECADE_SLUG_TO_YEAR_DIGITS: dict[str, str] = {
    "50": "1950",
    "60": "1960",
    "70": "1970",
    "80": "1980",
    "90": "1990",
    "00": "2000",
}

def normalize_home_token(raw: str) -> str | None:
    """Normalize a config token, or return None if unknown."""
    tok = str(raw or "").strip().lower()
    if not tok:
        return None
    if tok in ("show", "shows"):
        return "shows"
    if tok in ("movie", "movies"):
        return "movies"
    if tok in ("continue", "continue_watching", "resume"):
        return "continue"
    if tok in ("favorite", "favorites", "favourites", "favs"):
        return "favorites"
    if tok in ("recent", "recently", "recently_watched"):
        return "recent"
    if tok in ("tvguide", "tv_guide", "005"):
        return "tvguide"
    if tok in ("weather", "004"):
        return "weather"
    if tok in ("directory", "000", "guide"):
        return "directory"
    if tok in ("001", "002", "003"):
        return tok
    # Accept "1990s", "90s", "retro:90", "retro_90"
    if tok in _DECADE_TOKEN_TO_SLUG:
        return tok
    for label, slug in _DECADE_TOKEN_TO_SLUG.items():
        if tok in (slug, f"{slug}s", f"retro:{slug}", f"retro_{slug}", label.lower()):
            return label
    if tok.startswith("retro:"):
        slug = tok.split(":", 1)[1].strip()
        return _DECADE_SLUG_TO_LABEL.get(slug)
    if tok.startswith("retro_"):
        slug = tok.split("_", 1)[1].strip()
        return _DECADE_SLUG_TO_LABEL.get(slug)
    return None


def parse_home_menu_list(raw: Any, *, kids: bool = False) -> list[str]:
    """Parse a parent/kids token list; invalid entries dropped."""
    defaults = (
        list(DEFAULT_KIDS_HOME_MENU_TOKENS)
        if kids
        else list(DEFAULT_HOME_MENU_TOKENS)
    )
    if not isinstance(raw, list):
        return defaults
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tok = normalize_home_token(str(item))
        if tok is None or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out if out else defaults


def parse_home_menu(raw: dict | None) -> dict[str, list[str]]:
    """Normalize ``home_menu`` config."""
    block = raw if isinstance(raw, dict) else {}
    parent = block.get("parent")
    kids = block.get("kids")
    return {
        "parent": parse_home_menu_list(
            parent if parent is not None else list(DEFAULT_HOME_MENU_TOKENS),
            kids=False,
        ),
        "kids": parse_home_menu_list(
            kids if kids is not None else list(DEFAULT_KIDS_HOME_MENU_TOKENS),
            kids=True,
        ),
    }


def decade_slug_for_token(token: str) -> str | None:
    return _DECADE_TOKEN_TO_SLUG.get(token)


def year_digits_for_decade_slug(slug: str) -> str:
    return _DECADE_SLUG_TO_YEAR_DIGITS.get(slug, "1990")


def label_for_decade_slug(slug: str) -> str:
    return _DECADE_SLUG_TO_LABEL.get(slug, slug)
