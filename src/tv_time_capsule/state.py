"""Persisted watch state (completed episodes + in-episode resume positions)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from .config import STATE_DIR, STATE_FILE

# Don't treat a tiny scrub as "in progress"
MIN_RESUME_SECONDS = 5.0
# If the viewer stops this close to the end, count the episode as finished
END_COMPLETE_SECONDS = 10.0

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_active_state_file: str = STATE_FILE


def set_active_state_file(path: str | None) -> None:
    """Point load/save at a profile-specific state file."""
    global _active_state_file
    _active_state_file = path or STATE_FILE


def active_state_file() -> str:
    return _active_state_file


def load_state():
    path = _active_state_file
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state):
    path = _active_state_file
    os.makedirs(os.path.dirname(path) or STATE_DIR, exist_ok=True)
    with open(path, "w") as f:
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


def _normalize_youtube_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("youtube:"):
        text = text[8:].strip()
    if _YT_ID_RE.match(text):
        return text
    return None


def youtube_id_from_episode(episode: dict | None) -> str | None:
    """Best-effort YouTube video id from an episode dict."""
    if not isinstance(episode, dict):
        return None
    yid = _normalize_youtube_id(episode.get("youtube_id"))
    if yid:
        return yid
    return _normalize_youtube_id(episode.get("path"))


def _watched_numbers(entry: dict) -> set[int]:
    """Episode numbers marked watched for a season entry (local / legacy)."""
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


def _watched_ids(entry: dict) -> set[str]:
    """YouTube video ids marked watched for a season entry."""
    raw = entry.get("watched_ids")
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        yid = _normalize_youtube_id(item)
        if yid:
            out.add(yid)
    return out


def _write_watched(entry: dict, watched: set[int]) -> None:
    if watched:
        entry["watched"] = sorted(watched)
    else:
        entry.pop("watched", None)
    entry.pop("ep", None)


def _write_watched_ids(entry: dict, watched_ids: set[str]) -> None:
    if watched_ids:
        entry["watched_ids"] = sorted(watched_ids)
    else:
        entry.pop("watched_ids", None)


def get_watched_episodes(
    state,
    show,
    season,
    episodes: list[dict] | None = None,
) -> set[int]:
    """Return episode numbers that are watched in the current catalog.

    For YouTube episodes (with ``youtube_id``), completion is keyed by video id
    (``watched_ids``). Local media still uses numeric ``watched``. When
    ``episodes`` is provided, ids are mapped to whatever number those videos
    currently have so playlist reordering does not lose progress.
    """
    entry = state.get(show, {}).get(f"s{int(season):02d}", {})
    if not isinstance(entry, dict):
        return set()
    numbers = _watched_numbers(entry)
    ids = _watched_ids(entry)
    if not episodes:
        return numbers
    out: set[int] = set()
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        try:
            num = int(ep.get("number"))
        except (TypeError, ValueError):
            continue
        if num < 1:
            continue
        yid = youtube_id_from_episode(ep)
        if yid:
            if yid in ids or num in numbers:
                out.add(num)
        elif num in numbers:
            out.add(num)
    return out


def is_episode_watched(
    state,
    show,
    season,
    ep_num,
    *,
    youtube_id: str | None = None,
    episode: dict | None = None,
) -> bool:
    yid = _normalize_youtube_id(youtube_id) or youtube_id_from_episode(episode)
    entry = state.get(show, {}).get(f"s{int(season):02d}", {})
    if not isinstance(entry, dict):
        return False
    if yid:
        if yid in _watched_ids(entry):
            return True
        # Legacy: previously stored by episode number before youtube_id tracking.
        try:
            return int(ep_num) in _watched_numbers(entry)
        except (TypeError, ValueError):
            return False
    try:
        ep_num = int(ep_num)
    except (TypeError, ValueError):
        return False
    return ep_num in _watched_numbers(entry)


def mark_episode_watched(
    state,
    show,
    season,
    ep_num,
    *,
    youtube_id: str | None = None,
    episode: dict | None = None,
) -> None:
    """Mark one episode as fully watched."""
    yid = _normalize_youtube_id(youtube_id) or youtube_id_from_episode(episode)
    entry = _season_entry(state, show, season)
    if yid:
        watched_ids = _watched_ids(entry)
        watched_ids.add(yid)
        _write_watched_ids(entry, watched_ids)
        # Drop legacy numeric entry for this slot if present.
        try:
            num = int(ep_num)
        except (TypeError, ValueError):
            num = None
        if num is not None:
            watched = _watched_numbers(entry)
            if num in watched:
                watched.discard(num)
                _write_watched(entry, watched)
        # Clear matching resume bookmark.
        if _normalize_youtube_id(entry.get("pos_id")) == yid:
            entry.pop("pos_id", None)
            entry.pop("pos_ep", None)
            entry.pop("pos", None)
        elif num is not None:
            try:
                if entry.get("pos_ep") is not None and int(entry["pos_ep"]) == num:
                    entry.pop("pos_ep", None)
                    entry.pop("pos", None)
                    entry.pop("pos_id", None)
            except (TypeError, ValueError):
                pass
    else:
        ep_num = int(ep_num)
        watched = _watched_numbers(entry)
        watched.add(ep_num)
        _write_watched(entry, watched)
        try:
            if entry.get("pos_ep") is not None and int(entry["pos_ep"]) == ep_num:
                entry.pop("pos_ep", None)
                entry.pop("pos", None)
                entry.pop("pos_id", None)
        except (TypeError, ValueError):
            pass
    entry["ts"] = datetime.now().isoformat()
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


def season_has_in_progress(state, show, season) -> bool:
    """True when a season has a resume bookmark (by episode number or YouTube id)."""
    entry = state.get(show, {}).get(f"s{int(season):02d}", {})
    if not isinstance(entry, dict):
        return False
    pos = entry.get("pos")
    try:
        seconds = float(pos)
    except (TypeError, ValueError):
        return False
    if seconds < MIN_RESUME_SECONDS:
        return False
    if _normalize_youtube_id(entry.get("pos_id")):
        return True
    try:
        return entry.get("pos_ep") is not None and int(entry["pos_ep"]) >= 1
    except (TypeError, ValueError):
        return False


def get_episode_position(
    state,
    show,
    season,
    episodes: list[dict] | None = None,
) -> tuple[int | None, float]:
    """Return (episode_number, seconds) for an in-progress episode, or (None, 0).

    YouTube bookmarks are stored as ``pos_id``; when ``episodes`` is provided,
    that id is resolved to the video's current episode number.
    """
    entry = state.get(show, {}).get(f"s{season:02d}", {})
    if not isinstance(entry, dict):
        return None, 0.0
    pos = entry.get("pos")
    if pos is None:
        return None, 0.0
    try:
        seconds = float(pos)
    except (TypeError, ValueError):
        return None, 0.0
    if seconds < MIN_RESUME_SECONDS:
        return None, 0.0

    pos_id = _normalize_youtube_id(entry.get("pos_id"))
    if pos_id:
        if not episodes:
            return None, 0.0
        for ep in episodes:
            if youtube_id_from_episode(ep) == pos_id:
                try:
                    return int(ep["number"]), seconds
                except (TypeError, ValueError, KeyError):
                    return None, 0.0
        return None, 0.0

    pos_ep = entry.get("pos_ep")
    if pos_ep is None:
        return None, 0.0
    try:
        ep_num = int(pos_ep)
    except (TypeError, ValueError):
        return None, 0.0
    if ep_num < 1:
        return None, 0.0
    return ep_num, seconds


def set_episode_position(
    state,
    show,
    season,
    ep,
    seconds,
    duration=None,
    *,
    youtube_id: str | None = None,
    episode: dict | None = None,
):
    """Save or clear an in-episode bookmark.

    Returns one of: ``"saved"``, ``"completed"``, ``"cleared"``, ``"ignored"``.
    """
    yid = _normalize_youtube_id(youtube_id) or youtube_id_from_episode(episode)
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
        mark_episode_watched(
            state, show, season, ep_num, youtube_id=yid, episode=episode
        )
        return "completed"

    # Too early → drop any bookmark for this episode.
    if seconds < MIN_RESUME_SECONDS:
        cleared = clear_episode_position(
            state, show, season, ep=ep_num, youtube_id=yid
        )
        return "cleared" if cleared else "ignored"

    entry = _season_entry(state, show, season)
    entry["pos"] = round(seconds, 1)
    entry["ts"] = datetime.now().isoformat()
    if yid:
        entry["pos_id"] = yid
        entry["pos_ep"] = ep_num  # convenience for UIs that only know numbers
    else:
        entry["pos_ep"] = ep_num
        entry.pop("pos_id", None)
    save_state(state)
    return "saved"


def clear_episode_position(
    state,
    show,
    season,
    ep=None,
    *,
    youtube_id: str | None = None,
) -> bool:
    """Clear in-progress bookmark for a season (optionally only one episode)."""
    show_state = state.get(show)
    if not isinstance(show_state, dict):
        return False
    key = f"s{int(season):02d}"
    entry = show_state.get(key)
    if not isinstance(entry, dict):
        return False
    yid = _normalize_youtube_id(youtube_id)
    if yid is not None or ep is not None:
        matched = False
        if yid is not None and _normalize_youtube_id(entry.get("pos_id")) == yid:
            matched = True
        if ep is not None:
            try:
                if int(entry.get("pos_ep", -1)) == int(ep):
                    matched = True
            except (TypeError, ValueError):
                pass
        if not matched:
            return False
    if "pos_ep" not in entry and "pos" not in entry and "pos_id" not in entry:
        return False
    entry.pop("pos_ep", None)
    entry.pop("pos_id", None)
    entry.pop("pos", None)
    save_state(state)
    return True


def clear_resume_positions(state, show, season=None) -> bool:
    """Clear in-progress bookmarks only (keep watched flags).

    When ``season`` is None, clears resume bookmarks for every season of ``show``.
    """
    show_state = state.get(show)
    if not isinstance(show_state, dict):
        return False

    changed = False
    if season is None:
        seasons = [
            int(k[1:])
            for k in show_state
            if isinstance(k, str) and len(k) >= 2 and k.startswith("s") and k[1:].isdigit()
        ]
        for s in seasons:
            if clear_episode_position(state, show, s):
                changed = True
        return changed

    return clear_episode_position(state, show, season)


def reset_episode_progress(
    state,
    show,
    season,
    ep_num,
    *,
    youtube_id: str | None = None,
    episode: dict | None = None,
) -> bool:
    """Clear bookmark and watched flag for a single episode."""
    yid = _normalize_youtube_id(youtube_id) or youtube_id_from_episode(episode)
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
    if yid and _normalize_youtube_id(entry.get("pos_id")) == yid:
        entry.pop("pos_id", None)
        entry.pop("pos_ep", None)
        entry.pop("pos", None)
        changed = True
    else:
        try:
            if entry.get("pos_ep") is not None and int(entry["pos_ep"]) == ep_num:
                entry.pop("pos_ep", None)
                entry.pop("pos", None)
                entry.pop("pos_id", None)
                changed = True
        except (TypeError, ValueError):
            pass

    if yid:
        watched_ids = _watched_ids(entry)
        if yid in watched_ids:
            watched_ids.discard(yid)
            _write_watched_ids(entry, watched_ids)
            entry["ts"] = datetime.now().isoformat()
            changed = True
        # Also clear legacy numeric mark for this slot.
        watched = _watched_numbers(entry)
        if ep_num in watched:
            watched.discard(ep_num)
            _write_watched(entry, watched)
            entry["ts"] = datetime.now().isoformat()
            changed = True
    else:
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
    raw = state if state is not None else load_state()
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in ("keymap",) or not isinstance(value, dict):
            continue
        if any(isinstance(k, str) and k.startswith("s") for k in value):
            out[key] = value
    return out


def _parse_ts(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def iter_season_entries(state: dict) -> list[tuple[str, int, dict[str, Any]]]:
    """Yield (show_name, season_num, entry) for every season dict in state."""
    out: list[tuple[str, int, dict[str, Any]]] = []
    if not isinstance(state, dict):
        return out
    for show, seasons in state.items():
        if not isinstance(show, str) or show.startswith("_"):
            continue
        if not isinstance(seasons, dict):
            continue
        for key, entry in seasons.items():
            if not isinstance(key, str) or not key.startswith("s") or not key[1:].isdigit():
                continue
            if not isinstance(entry, dict):
                continue
            out.append((show, int(key[1:]), entry))
    return out


def list_continue_watching(
    state: dict,
    *,
    known_shows: set[str] | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    """In-progress titles sorted by newest ``ts`` first."""
    items: list[dict[str, Any]] = []
    for show, season, entry in iter_season_entries(state):
        if known_shows is not None and show not in known_shows:
            continue
        try:
            seconds = float(entry.get("pos") or 0)
        except (TypeError, ValueError):
            continue
        if seconds < MIN_RESUME_SECONDS:
            continue
        ep_num = entry.get("pos_ep")
        try:
            ep_i = int(ep_num) if ep_num is not None else None
        except (TypeError, ValueError):
            ep_i = None
        if ep_i is None and not _normalize_youtube_id(entry.get("pos_id")):
            continue
        items.append(
            {
                "kind": "show",
                "name": show,
                "season": season,
                "episode": ep_i,
                "pos": seconds,
                "pos_id": _normalize_youtube_id(entry.get("pos_id")),
                "ts": entry.get("ts"),
                "ts_sort": _parse_ts(entry.get("ts")),
            }
        )
    items.sort(key=lambda x: x["ts_sort"], reverse=True)
    return items[: max(1, int(limit))]


def list_recently_watched(
    state: dict,
    *,
    known_shows: set[str] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Recently touched seasons (resume or completed) by ``ts``."""
    items: list[dict[str, Any]] = []
    for show, season, entry in iter_season_entries(state):
        if known_shows is not None and show not in known_shows:
            continue
        ts = entry.get("ts")
        if not ts:
            continue
        watched = _watched_numbers(entry) or _watched_ids(entry)
        try:
            seconds = float(entry.get("pos") or 0)
        except (TypeError, ValueError):
            seconds = 0.0
        in_progress = seconds >= MIN_RESUME_SECONDS and (
            entry.get("pos_ep") is not None or _normalize_youtube_id(entry.get("pos_id"))
        )
        if not watched and not in_progress:
            continue
        ep_num = entry.get("pos_ep")
        try:
            ep_i = int(ep_num) if ep_num is not None else None
        except (TypeError, ValueError):
            ep_i = None
        items.append(
            {
                "kind": "show",
                "name": show,
                "season": season,
                "episode": ep_i,
                "pos": seconds if in_progress else 0.0,
                "pos_id": _normalize_youtube_id(entry.get("pos_id")),
                "ts": ts,
                "ts_sort": _parse_ts(ts),
                "in_progress": in_progress,
            }
        )
    # Dedupe by show (keep newest)
    best: dict[str, dict[str, Any]] = {}
    for item in sorted(items, key=lambda x: x["ts_sort"], reverse=True):
        best.setdefault(item["name"], item)
    out = list(best.values())
    out.sort(key=lambda x: x["ts_sort"], reverse=True)
    return out[: max(1, int(limit))]

