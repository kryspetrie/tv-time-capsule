"""Hidden / easter-egg channel directory (000 guide + specials).

Shared by dial routing, the channel-000 guide screen, and in-app help.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HiddenChannel:
    """One dial code in the secret-channels lineup."""

    dial: str
    title: str
    # Optional one-line subtitle (only Weather needs this today).
    description: str = ""


# Order shown on channel 000 and in help.
HIDDEN_CHANNELS: tuple[HiddenChannel, ...] = (
    HiddenChannel(
        "000",
        "Secret directory",
        "This guide - list of easter-egg channels",
    ),
    HiddenChannel("001", "SMPTE Color Bars"),
    HiddenChannel("002", "Grid Test Pattern"),
    HiddenChannel("003", "RCA Indian Head"),
    HiddenChannel(
        "004",
        "Weather Channel",
        "weather.com/retro",
    ),
    HiddenChannel("1950-2009", "Retro TV by Decade"),
)


def hidden_channels_for_guide() -> tuple[HiddenChannel, ...]:
    """Channels listed on the 000 guide (excludes 000 itself)."""
    return tuple(ch for ch in HIDDEN_CHANNELS if ch.dial != "000")


def format_hidden_help_rows() -> list[tuple[str, str | None]]:
    """Label/detail rows for the in-app help browser."""
    rows: list[tuple[str, str | None]] = [
        ("SECRET CHANNELS", None),
        ("directory", "press 000"),
    ]
    for ch in hidden_channels_for_guide():
        if ch.description:
            rows.append((ch.dial, f"{ch.title} - {ch.description}"))
        else:
            rows.append((ch.dial, ch.title))
    rows.append(("hint", "parent browse only | Esc / 0 back"))
    return rows
