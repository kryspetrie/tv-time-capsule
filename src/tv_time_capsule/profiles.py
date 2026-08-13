"""Named user profiles (parent / kids / guest) and watch-state paths."""

from __future__ import annotations

import json
import os
import shutil
from typing import Any

from .config import STATE_DIR, STATE_FILE

PROFILE_IDS = ("parent", "kids", "guest")


def state_path_for_profile(profile_id: str) -> str:
    pid = normalize_profile_id(profile_id)
    return os.path.join(STATE_DIR, f"state-{pid}.json")


def normalize_profile_id(raw: Any) -> str:
    text = str(raw or "parent").strip().lower()
    return text if text in PROFILE_IDS else "parent"


def migrate_legacy_state_file(profile_id: str = "parent") -> None:
    """Move classic ``state.json`` to ``state-parent.json`` once."""
    dest = state_path_for_profile(profile_id)
    if os.path.isfile(dest):
        return
    if not os.path.isfile(STATE_FILE):
        return
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        shutil.copy2(STATE_FILE, dest)
    except OSError:
        return


def load_profile_state(profile_id: str) -> dict[str, Any]:
    from .state import load_state, set_active_state_file

    migrate_legacy_state_file("parent")
    path = state_path_for_profile(profile_id)
    set_active_state_file(path)
    return load_state()


def save_profile_state(profile_id: str, state: dict[str, Any]) -> None:
    from .state import save_state, set_active_state_file

    path = state_path_for_profile(profile_id)
    set_active_state_file(path)
    save_state(state)

def parse_profiles(raw: dict | None) -> dict[str, Any]:
    block = raw if isinstance(raw, dict) else {}
    active = normalize_profile_id(block.get("active", "parent"))
    out: dict[str, Any] = {"active": active}
    for pid in PROFILE_IDS:
        entry = block.get(pid)
        if not isinstance(entry, dict):
            entry = {}
        label_default = {"parent": "Parent", "kids": "Kids", "guest": "Guest"}[pid]
        pin_raw = entry.get("pin")
        pin: str | None
        if pin_raw is None or pin_raw == "":
            pin = None
        else:
            digits = "".join(ch for ch in str(pin_raw) if ch.isdigit())
            pin = digits[:4] if digits else None
        fav = entry.get("favorites")
        if not isinstance(fav, dict):
            fav = {}
        shows = [str(x) for x in (fav.get("shows") or []) if str(x).strip()]
        movies = [str(x) for x in (fav.get("movies") or []) if str(x).strip()]
        try:
            volume = int(entry.get("volume", block.get("volume", 100)))
        except (TypeError, ValueError):
            volume = 100
        volume = max(0, min(100, volume))
        allowlist = entry.get("allowlist")
        if not isinstance(allowlist, dict):
            allowlist = None
        out[pid] = {
            "label": str(entry.get("label") or label_default),
            "pin": pin,
            "favorites": {"shows": shows, "movies": movies},
            "volume": volume,
            "allowlist": allowlist,
        }
    return out


def profile_pin(profiles: dict[str, Any], profile_id: str) -> str | None:
    entry = profiles.get(normalize_profile_id(profile_id)) or {}
    pin = entry.get("pin")
    return str(pin) if pin else None


def copy_allowlist(
    profiles: dict[str, Any],
    *,
    src: str,
    dest: str,
    kids_mode_allowlist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy allowlist into dest profile; returns updated profiles dict."""
    src_id = normalize_profile_id(src)
    dest_id = normalize_profile_id(dest)
    src_entry = dict(profiles.get(src_id) or {})
    allow = src_entry.get("allowlist")
    if not isinstance(allow, dict) and src_id == "parent" and kids_mode_allowlist:
        allow = kids_mode_allowlist
    if not isinstance(allow, dict):
        allow = {"shows": [], "movies": []}
    shows = [str(x) for x in (allow.get("shows") or [])]
    movies = [str(x) for x in (allow.get("movies") or [])]
    dest_entry = dict(profiles.get(dest_id) or {})
    dest_entry["allowlist"] = {"shows": shows, "movies": movies}
    updated = dict(profiles)
    updated[dest_id] = dest_entry
    return updated
