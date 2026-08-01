"""Letter buckets and alphabet-menu helpers for show/movie browse lists."""

from __future__ import annotations

# Fixed digit → letter band for the alphabet jump menu (stable muscle memory).
LETTER_BANDS: dict[str, tuple[str, ...]] = {
    "1": tuple("ABC"),
    "2": tuple("DEF"),
    "3": tuple("GHI"),
    "4": tuple("JKL"),
    "5": tuple("MNO"),
    "6": tuple("PQR"),
    "7": tuple("STU"),
    "8": tuple("VWX"),
    "9": tuple("YZ#"),
}


def letter_bucket(title: str) -> str:
    """First letter bucket for sorting/jump (A-Z or # for non-letters)."""
    text = (title or "").strip()
    if not text:
        return "#"
    ch = text[0].upper()
    if ch.isalpha():
        return ch
    return "#"


def present_letters(titles: list[str]) -> list[str]:
    """Distinct letter buckets present in *titles*, A–Z then #."""
    seen: set[str] = set()
    for name in titles:
        seen.add(letter_bucket(name))
    letters = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c in seen]
    if "#" in seen:
        letters.append("#")
    return letters


def index_of_letter(titles: list[str], letter: str) -> int | None:
    """Index of the first title in *letter* bucket, or None."""
    target = (letter or "#").upper()
    if target != "#" and not target.isalpha():
        target = "#"
    for i, name in enumerate(titles):
        if letter_bucket(name) == target:
            return i
    return None


def first_letter_in_band(titles: list[str], digit: str) -> str | None:
    """First present letter in the fixed band for digit ``1``–``9``."""
    band = LETTER_BANDS.get(str(digit))
    if not band:
        return None
    present = set(present_letters(titles))
    for letter in band:
        if letter in present:
            return letter
    return None


def band_has_titles(titles: list[str], digit: str) -> bool:
    return first_letter_in_band(titles, digit) is not None


def jump_to_letter(
    movie_names: list[str],
    cursor: int,
    direction: int,
) -> int:
    """Move cursor to the first title in the next/previous letter bucket.

    ``direction`` is +1 (down) or -1 (up). Clamps at list ends.
    Kept for compatibility with older tests / call sites.
    """
    if not movie_names:
        return 0
    cursor = max(0, min(len(movie_names) - 1, cursor))
    if direction not in (-1, 1):
        return cursor

    buckets = present_letters(movie_names)
    # present_letters is A-Z order; browse order of first-seen may differ — use first-seen order
    seen: list[str] = []
    for name in movie_names:
        bucket = letter_bucket(name)
        if bucket not in seen:
            seen.append(bucket)
    buckets = seen
    if not buckets:
        return cursor

    current = letter_bucket(movie_names[cursor])
    try:
        bi = buckets.index(current)
    except ValueError:
        bi = 0

    target_bi = bi + direction
    if target_bi < 0 or target_bi >= len(buckets):
        return cursor

    target_bucket = buckets[target_bi]
    idx = index_of_letter(movie_names, target_bucket)
    return idx if idx is not None else cursor
