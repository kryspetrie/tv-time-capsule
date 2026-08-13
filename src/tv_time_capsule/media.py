"""Media discovery, filename parsing, and thumbnail lookup."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .config import VIDEO_EXTENSIONS
from .media_catalog import (
    MovieCatalogEntry,
    ShowCatalogEntry,
    catalog_is_writable,
    generate_movie_uuid,
    generate_show_uuid,
    read_movies_catalog,
    read_shows_catalog,
    write_movies_catalog,
    write_shows_catalog,
)
from .media_catalog_paths import sanitize_device_name, to_relative_path
from .metadata import (
    find_folder_poster,
    resolve_episode_art,
    resolve_episode_title,
    resolve_show_thumbnail,
)

logger = logging.getLogger(__name__)


def is_media_present(
    media_root: str | Path,
    device_name: str = "vintage-tv",
) -> bool:
    """Return True only when it is safe to import/prune against this root.

    Never creates ``.tv-time-capsule/`` during the probe — that would leave
    a host-side catalog folder under an empty leftover mount point after
    unplug, which then looks "present" and can wipe the library.

    Rules:
    - Directory must exist and be readable.
    - If a catalog file (shows.json or movies.json) exists, media is present.
    - If video files or subdirectories exist, media is present.
    - An empty ``.tv-time-capsule/{device}/`` directory on a stale mount
      point is treated as **absent**.
    - A first-time empty but writable root is treated as present (initial
      setup).
    """
    root = Path(media_root).expanduser()
    if not root.is_dir():
        return False
    try:
        if not os.access(root, os.R_OK):
            return False
    except OSError:
        return False

    # Catalog files indicate media was previously present here.
    catalog_dir = root / ".tv-time-capsule" / sanitize_device_name(device_name)
    if (catalog_dir / "shows.json").is_file() or (catalog_dir / "movies.json").is_file():
        return True

    # Quick scan for any video files or non-hidden subdirectories.
    try:
        entries = os.listdir(root)
    except OSError:
        return False

    for entry in entries:
        if entry.startswith("."):
            continue
        entry_path = root / entry
        if entry_path.is_dir():
            return True
        if entry_path.is_file() and entry_path.suffix.lower() in VIDEO_EXTENSIONS:
            return True

    # Empty ``.tv-time-capsule/{device}/`` on a stale mount → absent.
    if catalog_dir.is_dir():
        return False

    # First-time empty but writable root: present for initial setup.
    try:
        return bool(os.access(root, os.W_OK))
    except OSError:
        return False


def directory_signature(media_root: str | Path) -> tuple[int, int, float]:
    """Return ``(file_count, total_size_bytes, max_mtime)`` for video files.

    Used to skip expensive rescans when nothing changed on disk.
    Excludes ``.tv-time-capsule/`` and dotfiles from the signature.
    """
    root = Path(media_root)
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
            path = Path(r) / name
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


def parse_season_episode(filename):
    name = Path(filename).stem
    m = re.search(r"[sS](\d+)[.\s]*[eE](\d+)", name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def parse_episode_number(filename):
    se = parse_season_episode(filename)
    if se[0] is not None and se[1] is not None:
        return se[1]
    name = Path(filename).stem
    m = re.search(r"^(\d+)", name)
    if m:
        return int(m.group(1))
    return None


def parse_episode_name(filename):
    name = Path(filename).stem
    name = re.sub(r"^[sS]\d+[.\s]*[eE]\d+\s*[-.]?\s*", "", name)
    name = re.sub(r"^\d+\s*[-.]?\s*", "", name)
    name = name.strip(" .-_")
    return name if name else None


def folder_season_info(folder_name: str, next_auto: int) -> tuple[int, str | None]:
    """Map a season subfolder to (season_number, menu_label).

    Returns a display label when the folder name is not a conventional season
    pattern (e.g. ``Action`` → label ``Action``; ``s01`` → label ``None``).
    """
    se = parse_season_episode(folder_name)
    if se[0] is not None:
        return se[0], None

    m = re.match(r"^[sS](\d+)$", folder_name)
    if m:
        return int(m.group(1)), None

    m = re.match(r"^season\s*(\d+)$", folder_name, re.I)
    if m:
        return int(m.group(1)), None

    if re.fullmatch(r"\d+", folder_name):
        return int(folder_name), None

    m = re.search(r"(\d+)", folder_name)
    if m:
        return int(m.group(1)), None

    return next_auto, folder_name


def find_thumbnail(dir_path, names, video_stem=None):
    img_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    for name in names:
        for ext in img_exts:
            p = os.path.join(dir_path, name + ext)
            if os.path.isfile(p):
                return p
    return None


def find_video_thumbnail(video_path):
    stem = Path(video_path).stem
    dir_path = os.path.dirname(video_path)
    t = find_thumbnail(dir_path, [stem])
    if t:
        return t
    se = parse_season_episode(video_path)
    if se[0] is not None:
        t = find_thumbnail(dir_path, [f"s{se[0]:02d}e{se[1]:02d}"])
        if t:
            return t
    return None


def discover_shows(media_paths):
    """Scan one or more media root directories and merge results.

    If two paths contain shows with the same name, episodes are merged.
    """
    if isinstance(media_paths, str):
        media_paths = [media_paths]

    shows = {}
    for media_root in media_paths:
        if not os.path.isdir(media_root):
            continue

        for entry in sorted(os.listdir(media_root)):
            show_dir = os.path.join(media_root, entry)
            if not os.path.isdir(show_dir):
                continue

            video_files = []
            for root, dirs, files in os.walk(show_dir):
                for f in sorted(files):
                    if Path(f).suffix.lower() in VIDEO_EXTENSIONS:
                        video_files.append(os.path.join(root, f))

            if not video_files:
                continue

            subdir_videos = [v for v in video_files if os.path.dirname(v) != show_dir]
            has_season_folders = len(subdir_videos) == len(video_files)

            show_thumb = find_thumbnail(show_dir, ["thumbnail", "show", entry])
            if not show_thumb:
                show_thumb = resolve_show_thumbnail(show_dir, entry)

            if has_season_folders:
                seasons = {}
                for root, dirs, files in os.walk(show_dir):
                    for d in sorted(dirs):
                        season_dir = os.path.join(root, d)
                        season_num, season_label = folder_season_info(
                            d, len(seasons) + 1
                        )

                        s_videos = [
                            os.path.join(season_dir, f)
                            for f in sorted(os.listdir(season_dir))
                            if Path(f).suffix.lower() in VIDEO_EXTENSIONS
                        ]
                        if not s_videos:
                            continue

                        season_thumb = find_thumbnail(show_dir, [f"s{season_num:02d}", d])
                        if not season_thumb:
                            season_thumb = find_folder_poster(season_dir)
                        episodes = _parse_episodes(s_videos, season_num, season_dir)
                        season_entry: dict = {
                            "episodes": episodes,
                            "thumbnail": season_thumb,
                        }
                        if season_label:
                            season_entry["label"] = season_label
                        seasons[season_num] = season_entry

                if not seasons:
                    seasons[1] = {
                        "episodes": _parse_episodes(video_files, 1, show_dir),
                        "thumbnail": find_thumbnail(show_dir, ["s01"]),
                    }

                new_show = {
                    "has_seasons": len(seasons) > 1,
                    "seasons": seasons,
                    "thumbnail": show_thumb,
                }
            else:
                grouped = _group_by_season(video_files)
                seasons = {}
                for s_num in sorted(grouped.keys()):
                    s_videos = grouped[s_num]
                    s_dir = os.path.dirname(s_videos[0]) if s_num == 0 else show_dir
                    actual_num = s_num if s_num != 0 else 1
                    episodes = _parse_episodes(s_videos, actual_num, s_dir)
                    seasons[actual_num] = {
                        "episodes": episodes,
                        "thumbnail": find_thumbnail(show_dir, [f"s{actual_num:02d}"]),
                    }

                has_multiple_seasons = len(seasons) > 1
                new_show = {
                    "has_seasons": has_multiple_seasons,
                    "seasons": seasons,
                    "thumbnail": show_thumb,
                }

            # Merge with existing show of the same name
            if entry in shows:
                existing = shows[entry]
                for snum, sdata in new_show["seasons"].items():
                    if snum in existing["seasons"]:
                        existing_paths = {
                            e["path"] for e in existing["seasons"][snum]["episodes"]
                        }
                        for ep in sdata["episodes"]:
                            if ep["path"] not in existing_paths:
                                existing["seasons"][snum]["episodes"].append(ep)
                        existing["seasons"][snum]["episodes"].sort(
                            key=lambda e: e["number"]
                        )
                    else:
                        existing["seasons"][snum] = sdata
                if not existing.get("thumbnail") and new_show.get("thumbnail"):
                    existing["thumbnail"] = new_show["thumbnail"]
                existing["has_seasons"] = (
                    existing["has_seasons"] or new_show["has_seasons"]
                )
            else:
                shows[entry] = new_show

    return shows


def _group_by_season(video_files):
    with_season = {}
    without_season = []

    for vf in video_files:
        se = parse_season_episode(vf)
        if se[0] is not None:
            s_num = se[0]
            with_season.setdefault(s_num, []).append(vf)
        else:
            without_season.append(vf)

    result = {}
    for s_num in sorted(with_season.keys()):
        result[s_num] = with_season[s_num]
    if without_season:
        existing = set(result.keys())
        target = 1 if 1 not in existing else 0
        result[target] = without_season
    return result


def _parse_episodes(video_files, season_num, base_dir):
    episodes = []
    for i, vf in enumerate(sorted(video_files)):
        ep_num = parse_episode_number(os.path.basename(vf))
        if ep_num is None:
            ep_num = i + 1

        existing_nums = [e["number"] for e in episodes]
        if ep_num in existing_nums:
            ep_num = max(existing_nums) + 1

        thumbnail = find_video_thumbnail(vf)
        if not thumbnail:
            thumbnail = resolve_episode_art(vf)
        name = resolve_episode_title(
            vf, parse_episode_name(os.path.basename(vf))
        )

        episodes.append(
            {
                "number": ep_num,
                "name": name,
                "path": vf,
                "thumbnail": thumbnail,
            }
        )

    episodes.sort(key=lambda e: e["number"])
    return episodes


def _find_library_subdir(media_root: str, name: str) -> str | None:
    """Return path to ``name`` subfolder if present (case-insensitive)."""
    if not os.path.isdir(media_root):
        return None
    want = name.lower()
    for entry in os.listdir(media_root):
        if entry.lower() == want:
            path = os.path.join(media_root, entry)
            if os.path.isdir(path):
                return path
    return None


def _movie_display_title(video_path: str) -> str:
    base = os.path.basename(video_path)
    parsed = parse_episode_name(base)
    title = resolve_episode_title(video_path, parsed)
    if title:
        return title
    stem = Path(base).stem
    return stem if stem else base


def discover_movies(media_paths: list[str] | str) -> list[dict]:
    """Recursively collect videos under movie roots into a flat sorted list."""
    if isinstance(media_paths, str):
        media_paths = [media_paths]

    by_path: dict[str, dict] = {}
    for movies_root in media_paths:
        if not os.path.isdir(movies_root):
            continue
        for root, _dirs, files in os.walk(movies_root):
            for fname in sorted(files):
                if Path(fname).suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                vf = os.path.join(root, fname)
                if vf in by_path:
                    continue
                title = _movie_display_title(vf)
                thumb = find_video_thumbnail(vf)
                if not thumb:
                    thumb = resolve_episode_art(vf)
                by_path[vf] = {
                    "title": title,
                    "path": vf,
                    "thumbnail": thumb,
                }

    movies = sorted(by_path.values(), key=lambda m: m["title"].lower())
    return movies


def _movies_to_catalog(movies: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """Build unique display keys and a title-keyed movie map."""
    catalog: dict[str, dict] = {}
    names: list[str] = []
    title_counts: dict[str, int] = {}

    for movie in movies:
        base_title = movie["title"]
        title_counts[base_title] = title_counts.get(base_title, 0) + 1

    title_seen: dict[str, int] = {}
    for movie in movies:
        base_title = movie["title"]
        if title_counts[base_title] > 1:
            title_seen[base_title] = title_seen.get(base_title, 0) + 1
            key = f"{base_title} ({title_seen[base_title]})"
        else:
            key = base_title
        entry = dict(movie)
        entry["key"] = key
        catalog[key] = entry
        names.append(key)

    return catalog, names


def discover_library(
    media_paths: list[str] | str,
    *,
    device_name: str = "vintage-tv",
    read_only: bool = False,
) -> dict:
    """Discover shows and movies, inferring split vs legacy layout.

    When on-media catalogs (``.tv-time-capsule/{device}/shows.json`` etc.)
    exist, stable UUIDs are preserved across rescans.  New items receive
    freshly generated UUIDs.  Updated catalogs are written back atomically.

    Returns:
        layout: split | shows_only | movies_only | legacy
        shows: show dict (discover_shows format)
        movies: title-keyed movie entries
        movie_names: sorted browse order for movies
        show_uuids: {show_name: uuid} — stable across rescans
        movie_uuids: {movie_key: uuid} — stable across rescans
    """
    if isinstance(media_paths, str):
        media_paths = [media_paths]

    show_scan_paths: list[str] = []
    movie_scan_paths: list[str] = []
    has_shows_dir = False
    has_movies_dir = False

    # ── Load existing catalogs from each media root ──────────────────────
    show_uuid_by_rel: dict[str, str] = {}  # relative_path → uuid
    movie_uuid_by_rel: dict[str, str] = {}
    catalog_writable: dict[str, bool] = {}
    catalog_corrupt: dict[str, bool] = {}  # True → corrupt, don't overwrite

    for media_root in media_paths:
        if not os.path.isdir(media_root):
            continue
        root_path = Path(media_root)

        # Load shows catalog
        show_entries = read_shows_catalog(root_path, device_name)
        if show_entries is not None:
            for entry in show_entries:
                show_uuid_by_rel[entry.relative_path] = entry.uuid
        else:
            # Check if catalog file exists but is corrupt (vs absent)
            from .media_catalog_paths import shows_catalog_path
            if shows_catalog_path(root_path, device_name).exists():
                catalog_corrupt[media_root] = True
                logger.error(
                    "Shows catalog at %s is corrupt — will not overwrite to prevent data loss",
                    shows_catalog_path(root_path, device_name),
                )

        # Load movies catalog
        movie_entries = read_movies_catalog(root_path, device_name)
        if movie_entries is not None:
            for entry in movie_entries:
                movie_uuid_by_rel[entry.relative_path] = entry.uuid
        else:
            from .media_catalog_paths import movies_catalog_path
            if movies_catalog_path(root_path, device_name).exists():
                catalog_corrupt[media_root] = True
                logger.error(
                    "Movies catalog at %s is corrupt — will not overwrite to prevent data loss",
                    movies_catalog_path(root_path, device_name),
                )

        # Check writability for later
        from .media_catalog import catalog_is_writable
        catalog_writable[media_root] = catalog_is_writable(
            root_path, device_name, read_only=read_only
        )

        shows_sub = _find_library_subdir(media_root, "shows")
        movies_sub = _find_library_subdir(media_root, "movies")
        if shows_sub:
            has_shows_dir = True
            show_scan_paths.append(shows_sub)
        if movies_sub:
            has_movies_dir = True
            movie_scan_paths.append(movies_sub)
        if not shows_sub and not movies_sub:
            show_scan_paths.append(media_root)

    if has_shows_dir and has_movies_dir:
        layout = "split"
    elif has_movies_dir:
        layout = "movies_only"
    elif has_shows_dir:
        layout = "shows_only"
    else:
        layout = "legacy"

    shows = discover_shows(show_scan_paths) if show_scan_paths else {}
    movie_list = discover_movies(movie_scan_paths) if movie_scan_paths else []
    movies, movie_names = _movies_to_catalog(movie_list)

    # ── Assign stable UUIDs ─────────────────────────────────────────────
    show_uuids: dict[str, str] = {}
    movie_uuids: dict[str, str] = {}

    for show_name, show_data in shows.items():
        # Determine the relative path for this show
        rel = _show_relative_path(show_name, show_data, media_paths)
        if rel and rel in show_uuid_by_rel:
            show_uuids[show_name] = show_uuid_by_rel[rel]
        else:
            show_uuids[show_name] = generate_show_uuid(show_name, rel or show_name)

    for movie_key, movie_data in movies.items():
        rel = _movie_relative_path(movie_data, media_paths)
        if rel and rel in movie_uuid_by_rel:
            movie_uuids[movie_key] = movie_uuid_by_rel[rel]
        else:
            movie_uuids[movie_key] = generate_movie_uuid(movie_key, rel or movie_key)

    # ── Write updated catalogs back ─────────────────────────────────────
    _write_catalogs_back(
        media_paths, device_name, shows, movies, show_uuids, movie_uuids,
        catalog_writable, catalog_corrupt,
    )

    return {
        "layout": layout,
        "shows": shows,
        "movies": movies,
        "movie_names": movie_names,
        "show_uuids": show_uuids,
        "movie_uuids": movie_uuids,
    }


def _show_relative_path(
    show_name: str,
    show_data: dict,
    media_paths: list[str],
) -> str | None:
    """Compute a stable relative path for a show within its media root."""
    # Find the first episode path to determine the media root
    for season_data in show_data.get("seasons", {}).values():
        for ep in season_data.get("episodes", []):
            ep_path = ep.get("path", "")
            if ep_path:
                for mp in media_paths:
                    root = Path(mp)
                    try:
                        rel = to_relative_path(Path(ep_path), root)
                        if rel is not None:
                            # Extract the show directory from the episode path
                            # e.g. "shows/Bluey/s01/s01e01.mp4" → "shows/Bluey"
                            show_dir = str(Path(rel).parent.parent)
                            return show_dir
                    except (OSError, ValueError):
                        continue
    return None


def _movie_relative_path(
    movie_data: dict,
    media_paths: list[str],
) -> str | None:
    """Compute a stable relative path for a movie within its media root."""
    movie_path = movie_data.get("path", "")
    if not movie_path:
        return None
    for mp in media_paths:
        root = Path(mp)
        try:
            rel = to_relative_path(Path(movie_path), root)
            if rel is not None:
                return rel
        except (OSError, ValueError):
            continue
    return None


def _write_catalogs_back(
    media_paths: list[str],
    device_name: str,
    shows: dict,
    movies: dict,
    show_uuids: dict[str, str],
    movie_uuids: dict[str, str],
    catalog_writable: dict[str, bool],
    catalog_corrupt: dict[str, bool],
) -> None:
    """Write updated catalogs to each writable media root.

    Skips roots where the catalog is corrupt to prevent overwriting
    a damaged file that might be recoverable.
    """
    # Group shows and movies by media root
    for media_root in media_paths:
        if not catalog_writable.get(media_root):
            continue
        if catalog_corrupt.get(media_root):
            logger.warning(
                "Skipping catalog write to %s — catalog is corrupt, "
                "preserve the file for manual recovery",
                media_root,
            )
            continue
        root_path = Path(media_root)

        # Collect shows that belong to this root
        show_entries: list[ShowCatalogEntry] = []
        for show_name, show_data in shows.items():
            rel = _show_relative_path(show_name, show_data, [media_root])
            if rel is None:
                continue
            uuid_str = show_uuids.get(show_name, "")
            # Build season summary
            seasons: dict[int, dict] = {}
            for snum, sdata in show_data.get("seasons", {}).items():
                seasons[int(snum)] = {
                    "episode_count": len(sdata.get("episodes", [])),
                }
            # Compute thumbnail relative path
            thumb_rel = None
            thumb = show_data.get("thumbnail")
            if thumb:
                try:
                    thumb_rel = to_relative_path(Path(thumb), root_path)
                except (OSError, ValueError):
                    pass
            show_entries.append(ShowCatalogEntry(
                uuid=uuid_str,
                name=show_name,
                relative_path=rel,
                seasons=seasons,
                thumbnail_relative=thumb_rel,
            ))

        if show_entries:
            try:
                write_shows_catalog(root_path, device_name, show_entries)
            except OSError:
                logger.warning("Failed to write shows catalog to %s", media_root)

        # Collect movies that belong to this root
        movie_entries: list[MovieCatalogEntry] = []
        for movie_key, movie_data in movies.items():
            rel = _movie_relative_path(movie_data, [media_root])
            if rel is None:
                continue
            uuid_str = movie_uuids.get(movie_key, "")
            thumb_rel = None
            thumb = movie_data.get("thumbnail")
            if thumb:
                try:
                    thumb_rel = to_relative_path(Path(thumb), root_path)
                except (OSError, ValueError):
                    pass
            movie_entries.append(MovieCatalogEntry(
                uuid=uuid_str,
                title=movie_data.get("title", movie_key),
                relative_path=rel,
                thumbnail_relative=thumb_rel,
            ))

        if movie_entries:
            try:
                write_movies_catalog(root_path, device_name, movie_entries)
            except OSError:
                logger.warning("Failed to write movies catalog to %s", media_root)
