"""Helpers for per-device on-media Vintage TV catalog paths.

Mirrors the pattern from MusicBox's ``media_catalog_paths.py``:
``.tv-time-capsule/{device_name}/shows.json`` and ``movies.json``
live alongside the media files on each removable / network root.
"""

from __future__ import annotations

import pathlib
import re

CATALOG_DIR_NAME = ".tv-time-capsule"
SHOWS_FILENAME = "shows.json"
MOVIES_FILENAME = "movies.json"

_SAFE_DEVICE_SEGMENT = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_device_name(device_name: str) -> str:
    """Return a filesystem-safe device segment for ``.tv-time-capsule/{name}/``."""
    name = (device_name or "").strip()
    cleaned = _SAFE_DEVICE_SEGMENT.sub("-", name).strip("-_")
    return cleaned[:32] or "vintage-tv"


def catalog_device_dir(media_root: pathlib.Path, device_name: str) -> pathlib.Path:
    """Return ``{media_root}/.tv-time-capsule/{device_name}``."""
    return pathlib.Path(media_root) / CATALOG_DIR_NAME / sanitize_device_name(device_name)


def shows_catalog_path(media_root: pathlib.Path, device_name: str) -> pathlib.Path:
    """Return ``{media_root}/.tv-time-capsule/{device_name}/shows.json``."""
    return catalog_device_dir(media_root, device_name) / SHOWS_FILENAME


def movies_catalog_path(media_root: pathlib.Path, device_name: str) -> pathlib.Path:
    """Return ``{media_root}/.tv-time-capsule/{device_name}/movies.json``."""
    return catalog_device_dir(media_root, device_name) / MOVIES_FILENAME


def to_relative_path(file_path: pathlib.Path, media_root: pathlib.Path) -> str | None:
    """Return a posix-relative path under *media_root*, or ``None`` if outside."""
    try:
        rel = file_path.resolve().relative_to(pathlib.Path(media_root).resolve())
    except (OSError, ValueError):
        return None
    if not rel.parts or rel.parts[0] == CATALOG_DIR_NAME:
        return None
    return rel.as_posix()


def resolve_relative_path(media_root: pathlib.Path, relative_path: str) -> pathlib.Path:
    """Resolve a stored relative path against the current media root."""
    rel = pathlib.PurePosixPath(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"Invalid relative path: {relative_path}")
    return (pathlib.Path(media_root) / pathlib.Path(*rel.parts)).resolve()
