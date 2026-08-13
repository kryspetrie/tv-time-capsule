"""Sidecar NFO parsing and poster/thumbnail discovery."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

IMG_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# Jellyfin / Kodi style sidecar names
SHOW_NFO_NAMES = ("tvshow.nfo", "movie.nfo")
POSTER_NAMES = ("poster", "folder", "cover", "thumb")


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1].lower()
    return tag.lower()


def parse_nfo(path: str | os.PathLike) -> dict:
    """Parse a sidecar NFO file.

    Returns title, plot, thumb, year, years, network, studio when present.
    """
    result: dict[str, str] = {}
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except (ET.ParseError, OSError, FileNotFoundError):
        return result

    for elem in root.iter():
        key = _local_tag(elem.tag)
        text = (elem.text or "").strip()
        if not text:
            continue
        if key in ("title", "name", "localtitle") and "title" not in result:
            result["title"] = text
        elif key == "plot" and "plot" not in result:
            result["plot"] = text
        elif key in ("thumb", "poster", "fanart") and "thumb" not in result:
            result["thumb"] = text
        elif key in ("year", "premiered", "aired") and "year" not in result:
            # premiered/aired often YYYY-MM-DD — keep year digits.
            digits = "".join(ch for ch in text if ch.isdigit())
            result["year"] = digits[:4] if len(digits) >= 4 else text
        elif key in ("ended", "endyear") and "ended" not in result:
            digits = "".join(ch for ch in text if ch.isdigit())
            result["ended"] = digits[:4] if len(digits) >= 4 else text
        elif key in ("studio", "network", "company") and "network" not in result:
            result["network"] = text
    start = result.get("year") or ""
    end = result.get("ended") or ""
    if start and end and end != start:
        result["years"] = f"{start}-{end}"
    elif start:
        result["years"] = start
    return result


def resolve_show_guide_nfo(show_dir: str, show_name: str) -> dict[str, str]:
    """NFO fields useful for TV Guide (plot / years / network)."""
    nfo_path = find_nfo_file(show_dir, (show_name,))
    if not nfo_path:
        return {}
    return parse_nfo(nfo_path)


def resolve_movie_guide_nfo(movie_dir: str, movie_name: str = "") -> dict[str, str]:
    """NFO fields for a movie folder or sibling ``.nfo``."""
    extra = (movie_name,) if movie_name else ()
    nfo_path = find_nfo_file(movie_dir, extra)
    if not nfo_path:
        # Sibling of the video when movie_dir is the file's parent.
        for entry in sorted(os.listdir(movie_dir)):
            if entry.lower().endswith(".nfo"):
                nfo_path = os.path.join(movie_dir, entry)
                break
    if not nfo_path:
        return {}
    return parse_nfo(nfo_path)


def find_nfo_file(directory: str, extra_names: tuple[str, ...] = ()) -> str | None:
    """Return the first existing NFO path in ``directory``."""
    names = list(SHOW_NFO_NAMES) + [f"{n}.nfo" for n in extra_names]
    seen: set[str] = set()
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    for entry in sorted(os.listdir(directory)):
        if entry.lower().endswith(".nfo"):
            return os.path.join(directory, entry)
    return None


def find_folder_poster(directory: str) -> str | None:
    """Find poster.jpg / folder.jpg / cover.jpg in a directory."""
    for name in POSTER_NAMES:
        for ext in IMG_EXTENSIONS:
            path = os.path.join(directory, name + ext)
            if os.path.isfile(path):
                return path
    return None


def resolve_nfo_thumb(directory: str, thumb_ref: str) -> str | None:
    """Resolve a relative or absolute thumb path from an NFO tag."""
    ref = thumb_ref.strip()
    if not ref:
        return None
    if os.path.isabs(ref) and os.path.isfile(ref):
        return ref
    candidate = os.path.join(directory, ref)
    if os.path.isfile(candidate):
        return candidate
    stem = Path(ref).stem
    for ext in IMG_EXTENSIONS:
        path = os.path.join(directory, stem + ext)
        if os.path.isfile(path):
            return path
    return None


def resolve_show_thumbnail(show_dir: str, show_name: str) -> str | None:
    """Poster for a show folder: folder art, then NFO thumb."""
    poster = find_folder_poster(show_dir)
    if poster:
        return poster
    nfo_path = find_nfo_file(show_dir, (show_name,))
    if not nfo_path:
        return None
    meta = parse_nfo(nfo_path)
    thumb = meta.get("thumb")
    if thumb:
        resolved = resolve_nfo_thumb(show_dir, thumb)
        if resolved:
            return resolved
    return None


def resolve_show_title(show_dir: str, show_name: str) -> str | None:
    nfo_path = find_nfo_file(show_dir, (show_name,))
    if not nfo_path:
        return None
    return parse_nfo(nfo_path).get("title")


def resolve_episode_art(video_path: str) -> str | None:
    """Episode thumbnail from sidecar NFO or sibling poster names."""
    directory = os.path.dirname(video_path)
    stem = Path(video_path).stem
    nfo_path = os.path.join(directory, stem + ".nfo")
    if os.path.isfile(nfo_path):
        meta = parse_nfo(nfo_path)
        thumb = meta.get("thumb")
        if thumb:
            resolved = resolve_nfo_thumb(directory, thumb)
            if resolved:
                return resolved
    return find_folder_poster(directory)


def resolve_episode_title(video_path: str, fallback: str | None) -> str | None:
    nfo_path = os.path.join(os.path.dirname(video_path), Path(video_path).stem + ".nfo")
    if os.path.isfile(nfo_path):
        title = parse_nfo(nfo_path).get("title")
        if title:
            return title
    return fallback
