"""Persisted watch state (completed episodes + in-episode resume positions)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from .config import STATE_DIR, STATE_FILE

# Don't treat a tiny scrub as "in progress"
MIN_RESUME_SECONDS = 5.0
# If the viewer stops this close to the end, count the episode as finished
END_COMPLETE_SECONDS = 10.0


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _season_entry(state: dict, show: str, season: int) -> dict[str, Any]:
    if show not in state or not isinstance(state[show], dict):
        state[show] = {}
    key = f"s{int(season):02d}"
    entry = state[show].get(key)
    if not isinstance(entry, dict):
        entry = {}
        state[show][key] = entry
    return entry


def _watched_numbers(entry: dict) -> set[int]:
    """Episode numbers marked watched for a season entry."""
    raw = entry.get("watched")
    if isinstance(raw, list):
        out: set[int] = set()
        for item in raw:
            try:
                num = int(item)
            except (TypeError, ValueError):
                continue
            if num >= 1:
                out.add(num)
        return out

    # Legacy: single ``ep`` meant episodes 1..ep were completed in order.
    try:
        legacy = int(entry.get("ep", 0) or 0)
    except (TypeError, ValueError):
        legacy = 0
    if legacy > 0:
        return set(range(1, legacy + 1))
    return set()


def _write_watched(entry: dict, watched: set[int]) -> None:
    if watched:
        entry["watched"] = sorted(watched)
    else:
        entry.pop("watched", None)
    entry.pop("ep", None)


def get_watched_episodes(state, show, season) -> set[int]:
    """Return the set of individually completed episode numbers."""
    entry = state.get(show, {}).get(f"s{int(season):02d}", {})
    if not isinstance(entry, dict):
        return set()
    return _watched_numbers(entry)


def is_episode_watched(state, show, season, ep_num) -> bool:
    try:
        ep_num = int(ep_num)
    except (TypeError, ValueError):
        return False
    return ep_num in get_watched_episodes(state, show, season)


def mark_episode_watched(state, show, season, ep_num) -> None:
    """Mark one episode as fully watched."""
    ep_num = int(ep_num)
    entry = _season_entry(state, show, season)
    watched = _watched_numbers(entry)
    watched.add(ep_num)
    _write_watched(entry, watched)
    entry["ts"] = datetime.now().isoformat()
    try:
        if entry.get("pos_ep") is not None and int(entry["pos_ep"]) == ep_num:
            entry.pop("pos_ep", None)
            entry.pop("pos", None)
    except (TypeError, ValueError):
        pass
    save_state(state)


def get_resume_ep(state, show, season):
    """Highest watched episode number in the season (0 = none).

    Kept for compatibility; prefer ``get_watched_episodes`` / ``is_episode_watched``.
    """
    watched = get_watched_episodes(state, show, season)
    return max(watched) if watched else 0


def set_resume_ep(state, show, season, ep):
    """Record that a single episode is completed."""
    mark_episode_watched(state, show, season, int(ep))


def get_episode_position(state, show, season) -> tuple[int | None, float]:
    """Return (episode_number, seconds) for an in-progress episode, or (None, 0)."""
    entry = state.get(show, {}).get(f"s{season:02d}", {})
    if not isinstance(entry, dict):
        return None, 0.0
    pos_ep = entry.get("pos_ep")
    pos = entry.get("pos")
    if pos_ep is None or pos is None:
        return None, 0.0
    try:
        ep_num = int(pos_ep)
        seconds = float(pos)
    except (TypeError, ValueError):
        return None, 0.0
    if ep_num < 1 or seconds < MIN_RESUME_SECONDS:
        return None, 0.0
    return ep_num, seconds


def set_episode_position(state, show, season, ep, seconds, duration=None):
    """Save or clear an in-episode bookmark.

    Returns one of: ``"saved"``, ``"completed"``, ``"cleared"``, ``"ignored"``.
    """
    try:
        ep_num = int(ep)
        seconds = float(seconds or 0)
    except (TypeError, ValueError):
        return "ignored"

    dur = None
    if duration is not None:
        try:
            dur = float(duration)
        except (TypeError, ValueError):
            dur = None

    # Near the end → treat as finished instead of bookmarking.
    if dur and dur > 0 and seconds >= max(dur - END_COMPLETE_SECONDS, dur * 0.92):
        mark_episode_watched(state, show, season, ep_num)
        return "completed"

    # Too early → drop any bookmark for this episode.
    if seconds < MIN_RESUME_SECONDS:
        cleared = clear_episode_position(state, show, season, ep=ep_num)
        return "cleared" if cleared else "ignored"

    entry = _season_entry(state, show, season)
    entry["pos_ep"] = ep_num
    entry["pos"] = round(seconds, 1)
    entry["ts"] = datetime.now().isoformat()
    save_state(state)
    return "saved"


def clear_episode_position(state, show, season, ep=None) -> bool:
    """Clear in-progress bookmark for a season (optionally only one episode)."""
    show_state = state.get(show)
    if not isinstance(show_state, dict):
        return False
    key = f"s{int(season):02d}"
    entry = show_state.get(key)
    if not isinstance(entry, dict):
        return False
    if ep is not None:
        try:
            if int(entry.get("pos_ep", -1)) != int(ep):
                return False
        except (TypeError, ValueError):
            return False
    if "pos_ep" not in entry and "pos" not in entry:
        return False
    entry.pop("pos_ep", None)
    entry.pop("pos", None)
    save_state(state)
    return True


def reset_episode_progress(state, show, season, ep_num) -> bool:
    """Clear bookmark and watched flag for a single episode."""
    try:
        ep_num = int(ep_num)
        season = int(season)
    except (TypeError, ValueError):
        return False

    show_state = state.get(show)
    if not isinstance(show_state, dict):
        return False

    key = f"s{season:02d}"
    entry = show_state.get(key)
    if not isinstance(entry, dict):
        return False

    changed = False
    try:
        if entry.get("pos_ep") is not None and int(entry["pos_ep"]) == ep_num:
            entry.pop("pos_ep", None)
            entry.pop("pos", None)
            changed = True
    except (TypeError, ValueError):
        pass

    watched = _watched_numbers(entry)
    if ep_num in watched:
        watched.discard(ep_num)
        _write_watched(entry, watched)
        entry["ts"] = datetime.now().isoformat()
        changed = True

    if not entry or all(k == "ts" for k in entry):
        if key in show_state:
            show_state.pop(key, None)
            changed = True
        if not show_state and show in state:
            state.pop(show, None)
            changed = True

    if changed:
        save_state(state)
    return changed


def clear_resume_ep(state, show, season=None):
    """Clear watched/resume progress for a season, or every season of a show.

    Returns True if anything was removed.
    """
    show_state = state.get(show)
    if not isinstance(show_state, dict):
        return False

    changed = False
    if season is None:
        keys = [k for k in list(show_state) if isinstance(k, str) and k.startswith("s")]
        for key in keys:
            del show_state[key]
            changed = True
        if not show_state:
            del state[show]
            changed = True
    else:
        key = f"s{int(season):02d}"
        if key in show_state:
            del show_state[key]
            changed = True
            if not show_state:
                del state[show]

    if changed:
        save_state(state)
    return changed


def watch_summary(state: dict | None = None) -> dict:
    """Return watch progress only — excludes legacy ``keymap`` and other non-show keys."""
    raw = dict(state if state is not None else load_state())
    raw.pop("keymap", None)
    return {
        show: data
        for show, data in raw.items()
        if isinstance(data, dict)
    }
