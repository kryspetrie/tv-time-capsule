"""Custom channel lineup: show order and display channel numbers."""

from __future__ import annotations

from typing import Any


def build_channel_lineup(
    show_names: list[str] | set[str],
    channels_cfg: dict[str, Any] | None,
    *,
    favorite_names: list[str] | set[str] | None = None,
) -> tuple[list[str], dict[str, int], dict[int, str]]:
    """Build browse order and channel maps from config.

    Rules:
    - Favorite shows (when provided) appear first among unnumbered lineup order
      preferences, then ``order``, then remaining alphabetical.
    - Shows listed in ``order`` appear next (unknown names are skipped).
    - Remaining shows append in stable alphabetical order.
    - Each show gets a display channel: explicit ``numbers`` entry, else
      1-based index in the ordered lineup.

    Returns:
        (ordered_names, show_to_channel, channel_to_show)
    """
    known = sorted(set(show_names))
    if not known:
        return [], {}, {}

    cfg = channels_cfg or {}
    order_raw = cfg.get("order") or []
    numbers_raw = cfg.get("numbers") or {}

    order_list = [str(n) for n in order_raw] if isinstance(order_raw, list) else []
    numbers: dict[str, int] = {}
    if isinstance(numbers_raw, dict):
        for name, num in numbers_raw.items():
            try:
                numbers[str(name)] = int(num)
            except (TypeError, ValueError):
                continue

    favs = [str(n) for n in (favorite_names or []) if str(n) in known]

    ordered: list[str] = []
    seen: set[str] = set()
    for name in favs:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    for name in order_list:
        if name in known and name not in seen:
            ordered.append(name)
            seen.add(name)

    for name in known:
        if name not in seen:
            ordered.append(name)

    show_to_channel: dict[str, int] = {}
    channel_to_show: dict[int, str] = {}

    for idx, name in enumerate(ordered):
        ch = numbers.get(name, idx + 1)
        show_to_channel[name] = ch
        if ch not in channel_to_show:
            channel_to_show[ch] = name

    return ordered, show_to_channel, channel_to_show


def show_at_channel(channel_to_show: dict[int, str], channel_num: int) -> str | None:
    """Resolve a typed channel number to a show name."""
    try:
        ch = int(channel_num)
    except (TypeError, ValueError):
        return None
    if ch < 1:
        return None
    return channel_to_show.get(ch)
