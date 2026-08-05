"""Channel dial timing: channels, delayed 01/02 page flips, 00x specials."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .retro_tv_channel import decade_slug_from_digits


class DialKind(Enum):
    BACK = auto()
    PAGE_UP = auto()
    PAGE_DOWN = auto()
    LETTER_MENU = auto()
    HIDDEN_GUIDE = auto()
    TEST_PATTERN = auto()
    WEATHER = auto()
    RETRO_TV = auto()
    CHANNEL = auto()
    INVALID = auto()


@dataclass(frozen=True)
class DialResult:
    kind: DialKind
    digits: str
    channel: int | None = None
    decade: str | None = None


def classify_dial(digits: str) -> DialResult:
    """Classify a committed dial string (exact text, never int()-coerced)."""
    if not digits:
        return DialResult(DialKind.INVALID, digits)

    if digits == "0":
        return DialResult(DialKind.BACK, digits)

    if digits == "00":
        return DialResult(DialKind.LETTER_MENU, digits)

    if digits == "000":
        return DialResult(DialKind.HIDDEN_GUIDE, digits)

    if digits == "01":
        return DialResult(DialKind.PAGE_UP, digits)

    if digits == "02":
        return DialResult(DialKind.PAGE_DOWN, digits)

    if len(digits) == 2 and digits[0] == "0" and digits[1] in "3456789":
        return DialResult(DialKind.INVALID, digits)

    if digits in ("001", "002", "003"):
        return DialResult(DialKind.TEST_PATTERN, digits)

    if digits == "004":
        return DialResult(DialKind.WEATHER, digits)

    if digits.startswith("0"):
        return DialResult(DialKind.INVALID, digits)

    decade = decade_slug_from_digits(digits)
    if decade is not None:
        return DialResult(DialKind.RETRO_TV, digits, decade=decade)

    if digits.isdigit() and not digits.startswith("0"):
        return DialResult(DialKind.CHANNEL, digits, channel=int(digits))

    return DialResult(DialKind.INVALID, digits)


def dial_needs_more_input(digits: str) -> bool:
    """True while the buffer is waiting for timeout or another digit."""
    return digits in ("0", "00", "01", "02") or (
        bool(digits)
        and not digits.startswith("0")
        and digits.isdigit()
    )


def page_cursor(
    cursor: int,
    total: int,
    page_size: int,
    direction: int,
) -> int:
    """Move *cursor* by one full page, preserving row within the page when possible."""
    if total <= 0 or page_size <= 0:
        return 0
    cursor = max(0, min(total - 1, cursor))
    first = (cursor // page_size) * page_size
    row = cursor - first
    new_first = first + direction * page_size
    if new_first < 0:
        new_first = 0
    max_first = ((total - 1) // page_size) * page_size
    if new_first > max_first:
        new_first = max_first
    return min(total - 1, new_first + row)
