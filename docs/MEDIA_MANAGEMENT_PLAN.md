# Media Management Development Plan

**Date:** 2026-07-31
**Based on:** [MEDIA_MANAGEMENT_RESEARCH.md](./MEDIA_MANAGEMENT_RESEARCH.md)
**Reference:** MusicBox `src/musicbox/infrastructure/adapter/` and `tests/unit/`

---

## Overview

This plan implements seven steps to make Vintage TV's media management robust
against removable media, network shares, and configuration drift. Each step
builds on the previous one and is validated by tests before proceeding.

**Core principle:** Store library metadata on the media itself, not just on the
device. Use stable UUIDs for identity. Never delete state when media is merely
absent.

---

## Step 1: On-Media Catalog Infrastructure

### Goal
Create `.tv-time-capsule/{device}/shows.json` and `movies.json` on each media
root, storing relative paths and stable metadata.

### Files to Create
- `src/tv_time_capsule/media_catalog_paths.py` — Path helpers (mirrors musicbox's `media_catalog_paths.py`)
- `src/tv_time_capsule/media_catalog.py` — Read/write on-media catalogs (mirrors `json_media_tracks_adapter.py`)
- `tests/test_media_catalog.py` — Unit tests

### Implementation

#### 1a. `media_catalog_paths.py`

```python
"""Helpers for per-device on-media Vintage TV catalog paths."""

import pathlib
import re

CATALOG_DIR_NAME = ".tv-time-capsule"
SHOWS_FILENAME = "shows.json"
MOVIES_FILENAME = "movies.json"

_SAFE_DEVICE_SEGMENT = re.compile(r"[^a-zA-Z0-9_-]+")


def sanitize_device_name(device_name: str) -> str:
    """Return a filesystem-safe device segment for .tv-time-capsule/{name}/."""
    name = (device_name or "").strip()
    cleaned = _SAFE_DEVICE_SEGMENT.sub("-", name).strip("-_")
    return cleaned[:32] or "vintage-tv"


def catalog_device_dir(media_root: pathlib.Path, device_name: str) -> pathlib.Path:
    """Return {media_root}/.tv-time-capsule/{device_name}."""
    return pathlib.Path(media_root) / CATALOG_DIR_NAME / sanitize_device_name(device_name)


def shows_catalog_path(media_root: pathlib.Path, device_name: str) -> pathlib.Path:
    """Return {media_root}/.tv-time-capsule/{device_name}/shows.json."""
    return catalog_device_dir(media_root, device_name) / SHOWS_FILENAME


def movies_catalog_path(media_root: pathlib.Path, device_name: str) -> pathlib.Path:
    """Return {media_root}/.tv-time-capsule/{device_name}/movies.json."""
    return catalog_device_dir(media_root, device_name) / MOVIES_FILENAME


def to_relative_path(file_path: pathlib.Path, media_root: pathlib.Path) -> str | None:
    """Return a posix-relative path under media_root, or None if outside."""
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
```

#### 1b. `media_catalog.py`

```python
"""Read/write per-device show/movie catalogs on removable media."""

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
    resolve_relative_path,
    shows_catalog_path,
    to_relative_path,
)

logger = logging.getLogger(__name__)


@dataclass
class ShowCatalogEntry:
    """Metadata for one show stored on media."""
    uuid: str
    name: str
    relative_path: str
    seasons: dict[int, dict] = field(default_factory=dict)
    thumbnail_relative: str | None = None

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "relative_path": self.relative_path,
            "seasons": self.seasons,
            "thumbnail_relative": self.thumbnail_relative,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ShowCatalogEntry":
        return cls(
            uuid=data["uuid"],
            name=data["name"],
            relative_path=data["relative_path"],
            seasons=data.get("seasons", {}),
            thumbnail_relative=data.get("thumbnail_relative"),
        )


@dataclass
class MovieCatalogEntry:
    """Metadata for one movie stored on media."""
    uuid: str
    title: str
    relative_path: str
    thumbnail_relative: str | None = None

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "title": self.title,
            "relative_path": self.relative_path,
            "thumbnail_relative": self.thumbnail_relative,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MovieCatalogEntry":
        return cls(
            uuid=data["uuid"],
            title=data["title"],
            relative_path=data["relative_path"],
            thumbnail_relative=data.get("thumbnail_relative"),
        )


def generate_show_uuid(show_name: str, relative_path: str) -> str:
    """Generate a stable UUID for a show from its name and relative path."""
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
    return str(uuid.uuid5(namespace, f"{show_name}:{relative_path}"))


def generate_movie_uuid(title: str, relative_path: str) -> str:
    """Generate a stable UUID for a movie from its title and relative path."""
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(namespace, f"{title}:{relative_path}"))


def write_shows_catalog(
    media_root: pathlib.Path,
    device_name: str,
    entries: list[ShowCatalogEntry],
) -> None:
    """Atomically write the shows catalog to media."""
    path = shows_catalog_path(media_root, device_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
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
    payload = {
        "device_name": device_name,
        "movies": [e.to_dict() for e in entries],
    }
    _atomic_write(path, payload)


def read_shows_catalog(
    media_root: pathlib.Path,
    device_name: str,
) -> list[ShowCatalogEntry] | None:
    """Read the shows catalog from media. Returns None if absent or corrupt."""
    path = shows_catalog_path(media_root, device_name)
    return _read_catalog(path, "shows", ShowCatalogEntry.from_dict)


def read_movies_catalog(
    media_root: pathlib.Path,
    device_name: str,
) -> list[MovieCatalogEntry] | None:
    """Read the movies catalog from media. Returns None if absent or corrupt."""
    path = movies_catalog_path(media_root, device_name)
    return _read_catalog(path, "movies", MovieCatalogEntry.from_dict)


def catalog_is_writable(media_root: pathlib.Path, device_name: str) -> bool:
    """Check if the catalog directory is writable without creating it."""
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


def _read_catalog(
    path: pathlib.Path,
    key: str,
    entry_parser,
) -> list | None:
    """Read a catalog file. Returns None if absent or corrupt."""
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


def _atomic_write(path: pathlib.Path, payload: dict) -> None:
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
```

#### 1c. Tests (`tests/test_media_catalog.py`)

Tests to write (mirroring musicbox patterns):
- `test_write_and_read_shows_catalog` — round-trip
- `test_write_and_read_movies_catalog` — round-trip
- `test_catalog_absent_returns_none` — no file → None
- `test_corrupt_catalog_returns_none` — bad JSON → None
- `test_atomic_write_does_not_corrupt_on_crash` — partial write → old data preserved
- `test_relative_path_round_trip` — path survives remount
- `test_stable_uuid_same_input` — same name+path → same UUID
- `test_stable_uuid_different_input` — different name+path → different UUID
- `test_device_isolation` — two device names → separate catalogs
- `test_catalog_writable_true` — writable directory
- `test_catalog_writable_false` — read-only directory

---

## Step 2: Stable Show/Movie UUIDs

### Goal
Integrate UUIDs into the discovery pipeline. Shows and movies get stable UUIDs
from the on-media catalog. New items get generated UUIDs. The catalog is written
back after discovery.

### Files to Modify
- `src/tv_time_capsule/media.py` — `discover_library()` returns UUIDs
- `src/tv_time_capsule/app.py` — Store UUID maps, use for state lookups
- `src/tv_time_capsule/state.py` — Accept UUID-based lookups (with name fallback)
- `tests/test_media.py` — Add UUID tests

### Implementation

#### 2a. Modify `discover_library()` signature

Add optional `catalog_config` parameter:
```python
def discover_library(
    media_paths: list[str] | str,
    *,
    device_name: str = "vintage-tv",
    load_catalogs: bool = True,
) -> dict:
```

When `load_catalogs=True`, for each media root:
1. Read existing `shows.json` / `movies.json` catalogs
2. During discovery, match discovered shows/movies to catalog entries by relative path
3. Preserve existing UUIDs; generate new ones for new items
4. Return `show_uuids: dict[str, str]` (name → uuid) and `movie_uuids: dict[str, str]` (key → uuid)
5. Write updated catalogs back

#### 2b. Add UUID maps to App

```python
self.show_uuids: dict[str, str] = {}   # show_name → uuid
self.movie_uuids: dict[str, str] = {}  # movie_key → uuid
self._uuid_to_show: dict[str, str] = {}  # uuid → show_name
self._uuid_to_movie: dict[str, str] = {}  # uuid → movie_key
```

#### 2c. Update state.py for UUID-based lookups

Add parallel functions that accept UUIDs:
```python
def get_watched_episodes_by_uuid(state, show_uuid, season) -> set[int]
def is_episode_watched_by_uuid(state, show_uuid, season, ep_num) -> bool
def mark_episode_watched_by_uuid(state, show_uuid, season, ep_num) -> None
```

The state.json format evolves to:
```json
{
  "shows": {
    "uuid-1234": {"name": "Bluey", "s01": {"watched": [1,2,3]}}
  }
}
```

With automatic migration from the old name-keyed format on load.

#### 2d. Tests

- `test_discover_library_preserves_uuids` — rescan keeps same UUIDs
- `test_discover_library_generates_new_uuids` — new shows get UUIDs
- `test_state_migrates_name_keys_to_uuid` — old state.json → new format
- `test_state_uuid_fallback_to_name` — unknown UUID → name lookup
- `test_catalog_written_after_discovery` — shows.json created on media

---

## Step 3: Media Presence Detection

### Goal
When media is absent (unplugged USB, unmounted network share), don't treat it as
"empty library." Preserve in-memory state and don't prune.

### Files to Modify
- `src/tv_time_capsule/media.py` — Add `is_media_present()` function
- `src/tv_time_capsule/app.py` — `_rescan_library()` checks presence before pruning
- `tests/test_media.py` — Presence detection tests

### Implementation

#### 3a. `is_media_present()` in `media.py`

```python
def is_media_present(media_root: str | pathlib.Path, device_name: str = "vintage-tv") -> bool:
    """Return True only when it is safe to import/prune against this root.

    Never creates .tv-time-capsule/ during the probe.
    """
    root = pathlib.Path(media_root).expanduser()
    if not root.is_dir():
        return False
    try:
        if not os.access(root, os.R_OK):
            return False
    except OSError:
        return False

    # Check for catalog or media files
    catalog_dir = root / ".tv-time-capsule" / sanitize_device_name(device_name)
    if (catalog_dir / "shows.json").is_file() or (catalog_dir / "movies.json").is_file():
        return True

    # Quick scan for any video files (shallow, not full walk)
    for entry in os.listdir(root):
        entry_path = root / entry
        if entry_path.is_dir() and not entry.startswith("."):
            return True
        if entry_path.is_file() and entry_path.suffix.lower() in VIDEO_EXTENSIONS:
            return True

    # Empty .tv-time-capsule/{device}/ on stale mount → absent
    if catalog_dir.is_dir():
        return False

    # First-time empty but writable root: present for initial setup
    try:
        return bool(os.access(root, os.W_OK))
    except OSError:
        return False
```

#### 3b. Modify `_rescan_library()` in `app.py`

```python
def _rescan_library(self) -> bool:
    if self.view == self.PLAYING:
        return False

    # Check each media path for presence
    any_present = False
    for mp in self.media_paths:
        if is_media_present(mp, self._device_name):
            any_present = True
            break

    if not any_present:
        logger.info("No media present — skipping rescan, preserving state")
        return False

    # ... existing rescan logic ...
```

#### 3c. Tests

- `test_media_present_with_files` — directory with video files → True
- `test_media_present_with_catalog` — directory with catalog → True
- `test_media_absent_empty_dir` — empty directory → False
- `test_media_absent_stale_mount` — empty .tv-time-capsule/ dir → False
- `test_media_absent_nonexistent` — path doesn't exist → False
- `test_rescan_preserves_state_when_media_absent` — integration test

---

## Step 4: Composite Adapter Pattern

### Goal
Formally separate device state (config, watch progress) from media state (show
metadata). This is a refactoring step that makes the architecture cleaner and
easier to test.

### Files to Create/Modify
- `src/tv_time_capsule/library.py` — New `Library` dataclass (immutable aggregate)
- `src/tv_time_capsule/app.py` — Use `Library` instead of raw dicts
- `tests/test_library.py` — Unit tests

### Implementation

#### 4a. `Library` dataclass

```python
@dataclass(frozen=True)
class Library:
    """Immutable aggregate root for the media library."""
    shows: dict[str, dict]        # show_name → show data
    movies: dict[str, dict]       # movie_key → movie data
    show_names: tuple[str, ...]   # ordered browse names
    movie_names: tuple[str, ...]  # ordered browse names
    show_uuids: dict[str, str]    # show_name → uuid
    movie_uuids: dict[str, str]   # movie_key → uuid
    layout: str                   # "split", "shows_only", "movies_only", "legacy"

    @property
    def has_shows(self) -> bool: ...
    @property
    def has_movies(self) -> bool: ...
    def get_show_by_uuid(self, uuid: str) -> dict | None: ...
    def get_movie_by_uuid(self, uuid: str) -> dict | None: ...
```

#### 4b. Refactor App to use Library

Replace `self.shows`, `self.movies`, `self.show_names`, `self.movie_names`,
`self.library_layout` with a single `self.library: Library`.

#### 4c. Tests

- `test_library_immutable` — mutations return new instances
- `test_library_uuid_lookup` — get_show_by_uuid works
- `test_library_empty` — empty library has correct defaults

---

## Step 5: Signature-Based Rescan Skip

### Goal
Skip expensive `os.walk` when nothing changed on disk. Track a directory
signature per media root.

### Files to Modify
- `src/tv_time_capsule/media.py` — Add `directory_signature()` function
- `src/tv_time_capsule/app.py` — Cache signatures, skip rescan when unchanged
- `tests/test_media.py` — Signature tests

### Implementation

#### 5a. `directory_signature()`

```python
def directory_signature(media_root: str | pathlib.Path) -> tuple[int, int, float]:
    """Return (file_count, total_size_bytes, max_mtime) for video files."""
    root = pathlib.Path(media_root)
    if not root.is_dir():
        return (0, 0, 0.0)

    count = 0
    total_size = 0
    max_mtime = 0.0
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".tv-time-capsule"]
        for name in files:
            if name.startswith("."):
                continue
            path = pathlib.Path(r) / name
            if path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            count += 1
            total_size += stat.st_size
            max_mtime = max(max_mtime, stat.st_mtime)
    return (count, total_size, max_mtime)
```

#### 5b. Cache signatures in App

```python
self._media_signatures: dict[str, tuple[int, int, float]] = {}
```

In `_rescan_library()`, compare current signature to cached. Skip if unchanged
(unless `force=True`).

#### 5c. Tests

- `test_signature_empty_dir` — returns (0, 0, 0.0)
- `test_signature_with_files` — correct count/size/mtime
- `test_signature_unchanged_after_noop` — same after no changes
- `test_signature_changed_after_file_added` — different after adding file
- `test_signature_ignores_dotfiles` — .hidden files excluded
- `test_signature_ignores_catalog_dir` — .tv-time-capsule excluded

---

## Step 6: Corrupt Catalog Protection

### Goal
If the on-media catalog JSON is corrupt, refuse to overwrite it. Log an error
and continue with in-memory discovery only.

### Files to Modify
- `src/tv_time_capsule/media_catalog.py` — Already returns None for corrupt catalogs (from Step 1)
- `src/tv_time_capsule/media.py` — `discover_library()` handles corrupt catalogs gracefully
- `tests/test_media_catalog.py` — Already tested in Step 1

### Implementation

This is largely already handled by Step 1's design. The key addition is:

#### 6a. In `discover_library()`, when catalog is corrupt:

```python
if catalog is None and catalog_path.exists():
    logger.error(
        "Media catalog at %s is corrupt — using in-memory discovery only. "
        "Catalog will not be overwritten to prevent data loss.",
        catalog_path,
    )
    # Don't write back — preserve the corrupt file for manual recovery
    write_back = False
```

#### 6b. Tests

- `test_corrupt_catalog_not_overwritten` — bad JSON → file preserved
- `test_discover_library_survives_corrupt_catalog` — discovery still works

---

## Step 7: Config Cruft Cleanup

### Goal
Detect and clean up stale channel assignments and kids allowlist entries that
reference shows/movies no longer present in the library.

### Files to Modify
- `src/tv_time_capsule/config.py` — Add `clean_stale_entries()` function
- `src/tv_time_capsule/app.py` — Call cleanup after rescan
- `src/tv_time_capsule/admin_api.py` — Expose cleanup via admin API
- `tests/test_config.py` — Cleanup tests

### Implementation

#### 7a. `clean_stale_entries()` in `config.py`

```python
def clean_stale_entries(
    config: dict,
    known_shows: set[str],
    known_movies: set[str],
    *,
    dry_run: bool = False,
) -> dict:
    """Return a report of stale channel/kids entries and optionally remove them.

    Returns:
        {"stale_channels": [...], "stale_kids_shows": [...], "stale_kids_movies": [...]}
    """
    report = {"stale_channels": [], "stale_kids_shows": [], "stale_kids_movies": []}

    channels = config.get("channels", {})
    order = list(channels.get("order", []))
    numbers = dict(channels.get("numbers", {}))
    for name in list(order):
        if name not in known_shows:
            report["stale_channels"].append(name)
            if not dry_run:
                order.remove(name)
    for name in list(numbers):
        if name not in known_shows:
            if name not in report["stale_channels"]:
                report["stale_channels"].append(name)
            if not dry_run:
                del numbers[name]

    kids = config.get("kids_mode", {})
    allowlist = kids.get("allowlist", {})
    if isinstance(allowlist, dict):
        for name in list(allowlist.get("shows", [])):
            if name not in known_shows:
                report["stale_kids_shows"].append(name)
                if not dry_run:
                    allowlist["shows"].remove(name)
        for name in list(allowlist.get("movies", [])):
            if name not in known_movies:
                report["stale_kids_movies"].append(name)
                if not dry_run:
                    allowlist["movies"].remove(name)

    return report
```

#### 7b. Integration in `_rescan_library()`

After successful rescan, call `clean_stale_entries()` and log a warning if
stale entries were found. Optionally auto-clean (configurable).

#### 7c. Admin API endpoint

Add `POST /api/admin/cleanup` that runs `clean_stale_entries(dry_run=False)` and
returns the report.

#### 7d. Tests

- `test_clean_stale_channels` — stale channel order entries removed
- `test_clean_stale_channel_numbers` — stale channel number entries removed
- `test_clean_stale_kids_shows` — stale kids allowlist shows removed
- `test_clean_stale_kids_movies` — stale kids allowlist movies removed
- `test_clean_dry_run_preserves` — dry_run=True doesn't modify config
- `test_clean_keeps_valid_entries` — valid entries preserved

---

## Execution Order & Retro Cadence

| Step | Description | Dependencies | Estimated Tests |
|---|---|---|---|
| 1 | On-media catalog infrastructure | None | ~11 |
| 2 | Stable show/movie UUIDs | Step 1 | ~5 |
| 3 | Media presence detection | Step 1 | ~6 |
| 4 | Composite adapter pattern | Step 2 | ~3 |
| 5 | Signature-based rescan skip | Step 3 | ~6 |
| 6 | Corrupt catalog protection | Step 1 (mostly done) | ~2 |
| 7 | Config cruft cleanup | Step 2 | ~6 |

**Total estimated new tests: ~39**

After each step:
1. Run all existing tests to confirm no regressions
2. Run new tests for the step
3. Retro: review what was learned, update subsequent steps if needed
4. Commit

---

## Retro Template

After each step, answer:
1. **What worked well?** — Patterns that proved effective
2. **What surprised us?** — Unexpected interactions or edge cases
3. **What needs updating?** — Changes to remaining steps based on learnings
4. **Test coverage gaps?** — Anything we should add tests for
