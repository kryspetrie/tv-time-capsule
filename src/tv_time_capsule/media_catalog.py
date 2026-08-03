"""Read/write per-device show/movie catalogs on removable media.

Mirrors the pattern from MusicBox's ``json_media_tracks_adapter.py``:
stable UUIDs, relative paths, atomic writes, and corrupt-catalog protection.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any

from .media_catalog_paths import (
    catalog_device_dir,
    movies_catalog_path,
    shows_catalog_path,
)

logger = logging.getLogger(__name__)

# UUID namespace for stable generation (DNS namespace per RFC 4122)
_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


# ── Catalog entry dataclasses ────────────────────────────────────────────────


@dataclass
class ShowCatalogEntry:
    """Metadata for one show stored on media."""

    uuid: str
    name: str
    relative_path: str
    seasons: dict[int, dict] = field(default_factory=dict)
    thumbnail_relative: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "uuid": self.uuid,
            "name": self.name,
            "relative_path": self.relative_path,
        }
        if self.seasons:
            # Convert int keys to strings for JSON
            d["seasons"] = {str(k): v for k, v in self.seasons.items()}
        if self.thumbnail_relative:
            d["thumbnail_relative"] = self.thumbnail_relative
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShowCatalogEntry":
        seasons_raw = data.get("seasons", {})
        seasons: dict[int, dict] = {}
        if isinstance(seasons_raw, dict):
            for k, v in seasons_raw.items():
                try:
                    seasons[int(k)] = v
                except (ValueError, TypeError):
                    continue
        return cls(
            uuid=data["uuid"],
            name=data["name"],
            relative_path=data["relative_path"],
            seasons=seasons,
            thumbnail_relative=data.get("thumbnail_relative"),
        )


@dataclass
class MovieCatalogEntry:
    """Metadata for one movie stored on media."""

    uuid: str
    title: str
    relative_path: str
    thumbnail_relative: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "uuid": self.uuid,
            "title": self.title,
            "relative_path": self.relative_path,
        }
        if self.thumbnail_relative:
            d["thumbnail_relative"] = self.thumbnail_relative
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MovieCatalogEntry":
        return cls(
            uuid=data["uuid"],
            title=data["title"],
            relative_path=data["relative_path"],
            thumbnail_relative=data.get("thumbnail_relative"),
        )


# ── UUID generation ──────────────────────────────────────────────────────────


def generate_show_uuid(show_name: str, relative_path: str) -> str:
    """Generate a stable UUID for a show from its name and relative path.

    Uses UUIDv5 so the same show on the same media always gets the same UUID,
    even across different devices or rescans.
    """
    return str(uuid.uuid5(_UUID_NAMESPACE, f"show:{show_name}:{relative_path}"))


def generate_movie_uuid(title: str, relative_path: str) -> str:
    """Generate a stable UUID for a movie from its title and relative path."""
    return str(uuid.uuid5(_UUID_NAMESPACE, f"movie:{title}:{relative_path}"))


# ── Write catalogs ───────────────────────────────────────────────────────────


def write_shows_catalog(
    media_root: pathlib.Path,
    device_name: str,
    entries: list[ShowCatalogEntry],
) -> None:
    """Atomically write the shows catalog to media."""
    path = shows_catalog_path(media_root, device_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "device_name": device_name,
        "shows": [e.to_dict() for e in entries],
    }
    _atomic_write(path, payload)


def write_movies_catalog(
    media_root: pathlib.Path,
    device_name: str,
    entries: list[MovieCatalogEntry],
) -> None:
    """Atomically write the movies catalog to media."""
    path = movies_catalog_path(media_root, device_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "device_name": device_name,
        "movies": [e.to_dict() for e in entries],
    }
    _atomic_write(path, payload)


# ── Read catalogs ────────────────────────────────────────────────────────────


def read_shows_catalog(
    media_root: pathlib.Path,
    device_name: str,
) -> list[ShowCatalogEntry] | None:
    """Read the shows catalog from media.

    Returns:
        List of entries, or ``None`` if the catalog is absent or corrupt.
    """
    path = shows_catalog_path(media_root, device_name)
    return _read_catalog(path, "shows", ShowCatalogEntry.from_dict)


def read_movies_catalog(
    media_root: pathlib.Path,
    device_name: str,
) -> list[MovieCatalogEntry] | None:
    """Read the movies catalog from media.

    Returns:
        List of entries, or ``None`` if the catalog is absent or corrupt.
    """
    path = movies_catalog_path(media_root, device_name)
    return _read_catalog(path, "movies", MovieCatalogEntry.from_dict)


# ── Writable probe ───────────────────────────────────────────────────────────


def catalog_is_writable(media_root: pathlib.Path, device_name: str) -> bool:
    """Check whether the catalog directory is writable without creating it."""
    device_dir = catalog_device_dir(media_root, device_name)
    if device_dir.exists():
        try:
            probe = device_dir / ".writetest"
            probe.write_text("ok")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False
    # Directory doesn't exist — check if parent is writable
    parent = device_dir.parent
    if not parent.exists():
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = parent / ".writetest"
            probe.write_text("ok")
            probe.unlink(missing_ok=True)
            return True
        except OSError:
            return False
    try:
        probe = parent / ".writetest"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


# ── Internal helpers ─────────────────────────────────────────────────────────


def _read_catalog(
    path: pathlib.Path,
    key: str,
    entry_parser,
) -> list | None:
    """Read a catalog file. Returns ``None`` if absent or corrupt."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Corrupt catalog at %s — treating as absent", path)
        return None
    entries = raw.get(key, [])
    result = []
    for entry_data in entries:
        try:
            result.append(entry_parser(entry_data))
        except (KeyError, ValueError, TypeError):
            logger.warning("Skipping invalid entry in %s: %s", path, entry_data)
            continue
    return result


def _atomic_write(path: pathlib.Path, payload: dict[str, Any]) -> None:
    """Write JSON payload atomically: temp file → fsync → rename."""
    json_str = json.dumps(payload, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f"{path.name}.",
        suffix=".tmp",
    )
    tmp_path = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json_str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
