# Media Management Research: MusicBox → Vintage TV

**Date:** 2026-07-31
**Context:** Cross-project analysis of media management patterns

---

## MusicBox Architecture Overview

MusicBox has a sophisticated media management system built around one central
principle: **store library metadata on the media itself, not just on the device.**

### 1. On-Media Catalog (the key innovation)

MusicBox writes a per-device track catalog to the media under
`.musicbox/{device_name}/tracks.json`. This catalog:

- Stores **relative paths** (not absolute), so it survives remounting at different paths
- Contains **stable track UUIDs** that persist across rescans
- Travels with the media — unplug a USB drive, plug it into another Pi, and the catalog is there
- Is **device-isolated**: different MusicBox devices get different subdirectories, so two
  devices can share the same media without conflict

```python
# From media_catalog_paths.py
def media_tracks_path(media_root, device_name):
    return media_root / ".musicbox" / sanitize_device_name(device_name) / "tracks.json"
```

### 2. Composite Library Adapter

The `CompositeLibraryAdapter` merges two separate data sources at runtime:

| Source | Location | Contents |
|---|---|---|
| **Device library** (`JsonLibraryAdapter`) | On the Pi (`library.json`) | Playlists, network library tracks |
| **Media tracks** (`JsonMediaTracksAdapter`) | On the media (`.musicbox/...`) | Tracks from removable/USB media |

This separation means playlists survive media changes, and when media is absent,
tracks are "unloaded" from memory but **never deleted**.

### 3. Sync Service — Graceful Media Presence Handling

The `LibrarySyncService` is the most relevant piece. Key behaviors:

- **Media presence detection** — Before importing or pruning, it verifies media is
  *actually* present (not a stale mount point). It checks: directory exists, is
  readable, contains audio files or a catalog. Critically, an empty
  `.musicbox/{device}/` directory on a stale mount point is treated as **absent**.
- **Directory signature** — Tracks `(file_count, total_size, max_mtime)` to skip
  expensive rescans when nothing changed.
- **Corrupt catalog protection** — If `tracks.json` is corrupt JSON, it **refuses to
  write** (fail closed) rather than re-importing everything with new IDs.
- **Atomic writes** — Write to temp file → `fsync` → `os.replace()` to prevent
  corruption on power loss.
- **Card binding reconciliation** — When media returns, it reconciles NFC card
  assignments between device and media, with device-side playlists winning conflicts.

### 4. Network Library — Remote Catalogs

For network shares (SFTP, SMB), MusicBox can optionally write the same
`.musicbox/{device}/tracks.json` catalog to the remote share. This gives network
media the same stable-ID benefits as local media.

---

## What Vintage TV Currently Does

| Aspect | Current Approach | Problem |
|---|---|---|
| **Show/movie identity** | Folder name / filename string | Rename a folder → lose watch progress, channel assignments, kids allowlist entries |
| **Watch state** | `state.json` keyed by show name string | Fragile; no stable identity |
| **Channel assignments** | `config.json` keyed by show name | Stale entries accumulate when media changes |
| **Kids allowlist** | `config.json` keyed by show/movie name | Same staleness problem |
| **Rescan** | Full rebuild from disk via `discover_library()` | No presence detection; empty mount point = "no media" |
| **Metadata location** | All in-memory or in `~/.local/share/` | Nothing travels with the media |

---

## Recommended Adoptions (Prioritized)

### High Value, Moderate Effort

**1. On-media `.tv-time-capsule/{device}/` catalog**

This is the single most impactful change. Store a `shows.json` and `movies.json`
on each media root:

```
/media/usb/.tv-time-capsule/living-room-tv/
    shows.json     # {show_uuid: {name, relative_path, seasons, thumbnail_rel}}
    movies.json    # {movie_uuid: {title, relative_path, thumbnail_rel}}
```

Benefits:
- Stable UUIDs for every show and movie
- Survives remounting at different paths (relative paths)
- Survives media reorganization (the catalog is on the media)
- Multiple devices can share media without conflict

**2. Stable show/movie UUIDs**

Generate a UUID per show (based on folder path hash or random) and per movie.
Store these in the on-media catalog. Then change watch state, channel assignments,
and kids allowlist to reference UUIDs instead of names:

```python
# state.json — current
{"The Simpsons": {"s01": {"watched": [1,2,3]}}}

# state.json — proposed
{"shows": {"uuid-1234": {"s01": {"watched": [1,2,3]}}}}
```

This means renaming "The Simpsons" to "Simpsons, The" preserves all watch progress.

**3. Media presence detection**

Adopt musicbox's approach: before pruning shows/movies during rescan, verify the
media root is actually present (not a stale mount point). Check that the directory
is readable and either contains media files or a `.tv-time-capsule/` catalog. An
empty directory on a stale mount should be treated as **absent**, not as "empty
library."

### Lower Priority / Future

**4. Composite adapter pattern** — Separate device state (config, watch progress,
playlists) from media state (show metadata). This is already partially done
(state.json vs in-memory discovery) but could be formalized.

**5. Signature-based rescan skip** — Track `(file_count, total_size, max_mtime)`
per media root to skip expensive `os.walk` when nothing changed. The current
project already has `_rescan_interval_seconds` but always does a full walk.

**6. Corrupt catalog protection** — If the on-media JSON is corrupt, refuse to
overwrite it and log an error rather than re-importing everything with new IDs.

**7. Config cruft cleanup** — When rescanning, detect channel assignments and kids
allowlist entries that reference shows/movies no longer present, and offer to clean
them up (or at least warn in the admin UI).

---

## Key MusicBox Files Referenced

| File | Purpose |
|---|---|
| `src/musicbox/infrastructure/adapter/media_catalog_paths.py` | Path helpers for `.musicbox/{device}/` |
| `src/musicbox/infrastructure/adapter/json_media_tracks_adapter.py` | On-media track catalog read/write |
| `src/musicbox/infrastructure/adapter/json_library_adapter.py` | Device-side library persistence |
| `src/musicbox/infrastructure/adapter/composite_library_adapter.py` | Merges device + media libraries |
| `src/musicbox/application/library_sync_service.py` | Sync logic: import, prune, presence detection |
| `src/musicbox/domain/model/media_library.py` | Immutable aggregate root |
| `src/musicbox/domain/port/media_library_port.py` | Abstract interface |
| `src/musicbox/infrastructure/network/remote_media_catalog.py` | Network share catalog support |
| `tests/unit/application/test_library_sync_service.py` | Sync service tests |
| `tests/unit/infrastructure/test_composite_library_adapter.py` | Composite adapter tests |
| `tests/unit/infrastructure/test_json_library_adapter.py` | Library adapter tests |
| `tests/unit/infrastructure/test_json_media_tracks_adapter.py` | Media tracks adapter tests |
