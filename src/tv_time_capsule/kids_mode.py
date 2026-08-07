"""Kid-friendly browse mode: auto-play helpers."""

from __future__ import annotations

from typing import Callable


def kids_resume_season(
    state: dict,
    show: str,
    seasons: list[int],
    *,
    season_has_in_progress: Callable[..., bool],
) -> int:
    """Pick the season to resume for kid mode (in-progress, then recent, then first)."""
    if not seasons:
        return 1

    for season in reversed(seasons):
        if season_has_in_progress(state, show, season):
            return season

    best_season = seasons[0]
    best_ts = ""
    show_state = state.get(show, {})
    if isinstance(show_state, dict):
        for season in seasons:
            entry = show_state.get(f"s{season:02d}", {})
            if not isinstance(entry, dict):
                continue
            ts = str(entry.get("ts") or "")
            if ts > best_ts:
                best_ts = ts
                best_season = season

    return best_season
