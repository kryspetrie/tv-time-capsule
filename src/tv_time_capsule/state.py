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


def get_resume_ep(state, show, season):
    """Highest fully-completed episode number in the season (0 = none)."""
    entry = state.get(show, {}).get(f"s{season:02d}", {})
    if not isinstance(entry, dict):
        return 0
    try:
        return int(entry.get("ep", 0) or 0)
    except (TypeError, ValueError):
        return 0


def set_resume_ep(state, show, season, ep):
    """Record that episodes up through ``ep`` are completed."""
    entry = _season_entry(state, show, season)
    entry["ep"] = int(ep)
    entry["ts"] = datetime.now().isoformat()
    # Completing an episode clears any mid-play bookmark on it (or earlier).
    pos_ep = entry.get("pos_ep")
    try:
        pos_ep_i = int(pos_ep) if pos_ep is not None else None
    except (TypeError, ValueError):
        pos_ep_i = None
    if pos_ep_i is not None and pos_ep_i <= int(ep):
        entry.pop("pos_ep", None)
        entry.pop("pos", None)
    save_state(state)


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
        prev = get_resume_ep(state, show, season)
        set_resume_ep(state, show, season, max(prev, ep_num))
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
