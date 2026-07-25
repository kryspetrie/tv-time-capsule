"""Media discovery, filename parsing, and thumbnail lookup."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .config import VIDEO_EXTENSIONS


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
                    "has_seasons": True,
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
        name = parse_episode_name(os.path.basename(vf))

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
