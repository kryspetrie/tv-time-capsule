"""Helpers for the web admin: library tree, path probes, scans."""

from __future__ import annotations

import os
from typing import Any

from .media import discover_shows
from .mounts import is_mounted, mount_one, mountpoints_from_config


def library_tree_from_shows(shows: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize the cached discovery result as a hierarchical tree."""
    tree: list[dict[str, Any]] = []
    for name in sorted(shows.keys()):
        show = shows[name]
        seasons_out: list[dict[str, Any]] = []
        for s_num, s_data in sorted(show["seasons"].items()):
            episodes = []
            for ep in s_data.get("episodes") or []:
                episodes.append(
                    {
                        "number": ep.get("number"),
                        "name": ep.get("name"),
                        "file": os.path.basename(ep.get("path") or ""),
                    }
                )
            season_node: dict[str, Any] = {
                "number": s_num,
                "episodes": episodes,
            }
            if s_data.get("label"):
                season_node["label"] = s_data["label"]
            seasons_out.append(season_node)
        tree.append({"name": name, "seasons": seasons_out})
    return tree


def library_summary(shows: dict[str, Any]) -> dict[str, int]:
    episodes = sum(
        len(season.get("episodes") or [])
        for show in shows.values()
        for season in show.get("seasons", {}).values()
    )
    return {"shows": len(shows), "episodes": episodes}


def verify_media_path(path: str) -> dict[str, Any]:
    """Check whether a local media root exists and is readable."""
    expanded = os.path.expanduser(os.path.expandvars(str(path).strip()))
    if not expanded:
        return {"ok": False, "path": path, "error": "empty path"}
    if not os.path.exists(expanded):
        return {"ok": False, "path": expanded, "error": "not found"}
    if not os.path.isdir(expanded):
        return {"ok": False, "path": expanded, "error": "not a directory"}
    if not os.access(expanded, os.R_OK):
        return {"ok": False, "path": expanded, "error": "not readable"}
    try:
        entries = os.listdir(expanded)
    except OSError as exc:
        return {"ok": False, "path": expanded, "error": str(exc)}
    return {
        "ok": True,
        "path": expanded,
        "entries": len(entries),
        "message": f"{len(entries)} item(s) at top level",
    }


def verify_mount_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Try to mount (or confirm) one configured remote share."""
    mountpoint = entry.get("mountpoint") or ""
    label = str(mountpoint or entry.get("source") or "mount")
    if is_mounted(str(mountpoint)):
        readable = os.path.isdir(mountpoint) and os.access(mountpoint, os.R_OK)
        return {
            "ok": readable,
            "mountpoint": mountpoint,
            "message": "already mounted" if readable else "mounted but not readable",
        }
    ok, message = mount_one(entry)
    if ok and is_mounted(str(mountpoint)):
        return {"ok": True, "mountpoint": mountpoint, "message": message or "mounted"}
    return {"ok": False, "mountpoint": mountpoint, "error": message or f"{label} failed"}


def scan_paths(paths: list[str]) -> dict[str, Any]:
    """Discover shows under paths and return summary + tree."""
    clean = [p for p in paths if p]
    shows = discover_shows(clean)
    summary = library_summary(shows)
    return {
        "ok": bool(shows),
        "paths": clean,
        **summary,
        "tree": library_tree_from_shows(shows),
        "message": (
            f"Found {summary['shows']} show(s), {summary['episodes']} episode(s)"
            if shows
            else "No shows found"
        ),
    }


def effective_media_paths(config: dict[str, Any]) -> list[str]:
    """Configured media paths plus mountpoints (deduped)."""
    paths: list[str] = []
    for path in list(config.get("media_paths") or []) + mountpoints_from_config(
        config.get("mounts")
    ):
        if path and path not in paths:
            paths.append(path)
    return paths
