"""YouTube channel catalogs as virtual shows (Chrome scrape + disk cache).

No Google API key: short-lived headless Chrome reads ``ytInitialData`` from
channel ``/videos`` and ``/playlists`` tabs. Results are cached under
``~/.local/share/tv-time-capsule/youtube/`` (24h TTL by default).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .chrome_cdp import ensure_chromium, kill_port_process, wait_for_page_ws
from .config import STATE_DIR
from .youtube_titles import (
    DEFAULT_YOUTUBE_TITLE_RULES,
    apply_episode_codes,
    apply_youtube_title_rules,
    episode_base_key,
    episode_coverage_keys,
    episode_range_span,
    extract_episode_code,
    infer_implicit_part_one_titles,
    is_composite_episode_title,
)
from .youtube_playlists import match_playlist_groups, parse_playlist_selectors

try:
    import websocket  # type: ignore[import-untyped]
except ImportError:
    websocket = None  # type: ignore[assignment]

LOG = logging.getLogger(__name__)

# Active title-normalization rules (set from config via set_youtube_title_rules).
_TITLE_RULES: list[dict[str, Any]] = list(DEFAULT_YOUTUBE_TITLE_RULES)


def set_youtube_title_rules(rules: list[dict[str, Any]] | None) -> None:
    """Install title regex rules (None / empty → built-in defaults)."""
    global _TITLE_RULES
    if rules is None:
        _TITLE_RULES = list(DEFAULT_YOUTUBE_TITLE_RULES)
    else:
        _TITLE_RULES = list(rules)

CDP_PORT = 9226
CACHE_TTL_S = 24 * 60 * 60
MAX_UPLOADS = 100
MAX_PLAYLISTS = 40
MAX_PLAYLIST_VIDEOS = 80

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Common punctuation YouTube uses that we can map before ASCII filtering.
_TITLE_CHAR_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u2032": "'",
        "\u2033": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2022": "*",
        "\u00b7": "*",
        "\u2026": "...",
        "\u00a0": " ",
        "\u200b": "",
        "\u200c": "",
        "\u200d": "",
        "\ufeff": "",
        "\u00ae": "",
        "\u00a9": "",
        "\u2122": "",
    }
)


def sanitize_display_title(
    text: str | None,
    *,
    kind: str | None = "all",
    extra_rules: list[dict[str, Any]] | None = None,
) -> str:
    """Remove characters the bundled VCR OSD font cannot render.

    Keeps printable ASCII after normalizing curly quotes / dashes and
    decomposing accented letters (``é`` → ``e``). Collapses whitespace.
    When ``kind`` is ``episode``, ``playlist``, or ``all``, also applies
    global YouTube title regex rules, then optional per-entry ``extra_rules``.
    Pass ``kind=None`` to skip rules (e.g. user-chosen config titles).
    """
    if text is None:
        return ""
    raw = str(text).translate(_TITLE_CHAR_MAP)
    raw = unicodedata.normalize("NFKD", raw)
    cleaned = "".join(
        ch for ch in raw if 32 <= ord(ch) <= 126  # printable ASCII
    )
    cleaned = re.sub(r" +", " ", cleaned).strip()
    if kind is None:
        return cleaned
    cleaned = apply_youtube_title_rules(cleaned, _TITLE_RULES, kind=kind)
    if extra_rules:
        cleaned = apply_youtube_title_rules(cleaned, extra_rules, kind=kind)
    return cleaned


def _entry_extra_title_rules(entry: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    if not entry:
        return None
    rules = entry.get("title_rules")
    if not isinstance(rules, list) or not rules:
        return None
    return rules

def youtube_cache_dir() -> Path:
    return Path(STATE_DIR) / "youtube"


def is_youtube_episode(episode: dict | None) -> bool:
    """True when an episode dict is a YouTube video (not a local file)."""
    if not isinstance(episode, dict):
        return False
    if episode.get("youtube_id"):
        return True
    path = str(episode.get("path") or "")
    return path.startswith("youtube:")


def youtube_id_from_episode(episode: dict | None) -> str | None:
    """Extract the 11-char video id from an episode dict."""
    if not isinstance(episode, dict):
        return None
    yid = episode.get("youtube_id")
    if yid and _YT_ID_RE.match(str(yid)):
        return str(yid)
    path = str(episode.get("path") or "")
    if path.startswith("youtube:"):
        candidate = path[8:].strip()
        if _YT_ID_RE.match(candidate):
            return candidate
    return None


def playlist_id_from_url(url: str) -> str | None:
    """Extract a playlist id from a watch or playlist URL."""
    text = (url or "").strip()
    if not text:
        return None
    if text.startswith("PL") and "/" not in text and "?" not in text:
        return text
    parsed = urlparse(text if "://" in text else f"https://www.youtube.com/{text}")
    qs = parse_qs(parsed.query)
    vals = qs.get("list") or []
    if vals and vals[0]:
        return str(vals[0])
    # /playlist/PL… path form (rare)
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) >= 2 and parts[0] == "playlist" and parts[1].startswith("PL"):
        return parts[1]
    return None


def normalize_channel_ref(entry: dict[str, Any]) -> str | None:
    """Return a canonical channel or playlist URL from a config entry."""
    url = (entry.get("url") or "").strip()
    handle = (entry.get("handle") or "").strip()
    if url:
        pid = playlist_id_from_url(url)
        if pid:
            return f"https://www.youtube.com/playlist?list={pid}"
        if url.startswith("/"):
            return f"https://www.youtube.com{url}".rstrip("/")
        if url.startswith("UC") and "/" not in url:
            return f"https://www.youtube.com/channel/{url}"
        if "youtube.com" in url or "youtu.be" in url:
            return url.split("?")[0].rstrip("/")
        if url.startswith("@"):
            return f"https://www.youtube.com/{url}".rstrip("/")
        return url.rstrip("/")
    if handle:
        if handle.startswith("UC") and "/" not in handle:
            return f"https://www.youtube.com/channel/{handle}"
        if not handle.startswith("@"):
            handle = f"@{handle}"
        return f"https://www.youtube.com/{handle}"
    return None


def cache_key_for_entry(entry: dict[str, Any]) -> str:
    """Stable filesystem-safe key for a channel/playlist config entry."""
    url = (entry.get("url") or "").strip()
    pid = playlist_id_from_url(url) if url else None
    if pid:
        key = f"playlist_{pid}"
    else:
        ref = normalize_channel_ref(entry) or "unknown"
        parsed = urlparse(ref)
        path = (parsed.path or "").strip("/") or "channel"
        key = path.replace("/", "_")
    key = re.sub(r"[^A-Za-z0-9_.@-]+", "_", key)
    return key[:120] or "channel"


def _episode_dict(
    *,
    number: int,
    name: str,
    youtube_id: str,
    thumbnail: str | None = None,
    duration: int | None = None,
    extra_rules: list[dict[str, Any]] | None = None,
    playlist_order: int | None = None,
) -> dict[str, Any]:
    # Pull season/episode from the raw upload title before display rules may
    # strip those markers (e.g. Arthur "Season 3, Episode 2b, …").
    raw_season, raw_ep = extract_episode_code(name)
    clean_name = (
        sanitize_display_title(name, kind="episode", extra_rules=extra_rules)
        or youtube_id
    )
    clean_name, season, parsed_ep = apply_episode_codes(clean_name)
    if season is None:
        season = raw_season
    if parsed_ep is None:
        parsed_ep = raw_ep
    if not clean_name:
        clean_name = youtube_id
    ep_num = int(parsed_ep) if parsed_ep is not None else int(number)
    ep: dict[str, Any] = {
        "number": ep_num,
        "name": clean_name,
        "youtube_id": youtube_id,
        "path": f"youtube:{youtube_id}",
    }
    if playlist_order is not None:
        ep["_order"] = int(playlist_order)
    if parsed_ep is not None:
        ep["_from_title"] = True
    if thumbnail:
        ep["thumbnail"] = thumbnail
    if duration is not None and duration > 0:
        ep["duration"] = int(duration)
    return ep


def _dedupe_season_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer separate part uploads over compilations; drop duplicate titles/ids.

    Compilation / multi-part uploads (e.g. ``My Name Is Jake P1/P2 | Underground``)
    are removed when the season already has the separated episodes. Exact title
    and youtube_id duplicates keep the earliest playlist entry, preferring
    non-composite titles.
    """
    if len(episodes) <= 1:
        return list(episodes)

    ordered = sorted(
        episodes,
        key=lambda e: (
            int(e.get("_order") or 10**9),
            str(e.get("youtube_id") or ""),
        ),
    )

    atomics = [e for e in ordered if not is_composite_episode_title(str(e.get("name") or ""))]
    composites = [e for e in ordered if is_composite_episode_title(str(e.get("name") or ""))]

    atomic_bases: set[str] = set()
    for ep in atomics:
        atomic_bases |= episode_coverage_keys(str(ep.get("name") or ""))

    kept_composites: list[dict[str, Any]] = []
    for ep in composites:
        name = str(ep.get("name") or "")
        bases = episode_coverage_keys(name)
        if bases and all(b in atomic_bases for b in bases):
            continue
        # Pure leftover ranges ("116-118") when the season already has real eps.
        if re.fullmatch(r"\d{1,3}\s*[-–—]\s*\d{1,3}", name.strip()) and atomics:
            continue
        # "Full Episodes 4-6" style packs when separated episodes already exist.
        span = episode_range_span(name)
        if span and atomics and (span[1] - span[0] + 1) <= len(atomics):
            continue
        kept_composites.append(ep)

    candidates = atomics + kept_composites
    # Prefer non-composites, then earlier playlist order.
    candidates.sort(
        key=lambda e: (
            1 if is_composite_episode_title(str(e.get("name") or "")) else 0,
            int(e.get("_order") or 10**9),
            str(e.get("youtube_id") or ""),
        )
    )

    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict[str, Any]] = []
    for ep in candidates:
        yid = str(ep.get("youtube_id") or "")
        if yid and yid in seen_ids:
            continue
        title_key = episode_base_key(str(ep.get("name") or ""))
        # Full normalized name (with part suffix) for exact dupes like two "P1"s.
        full_key = re.sub(
            r"\s+",
            " ",
            re.sub(r"[^a-z0-9]+", " ", str(ep.get("name") or "").lower()),
        ).strip()
        if full_key and full_key in seen_titles:
            continue
        # Also collapse bare title vs same title with no extra info.
        if title_key and title_key in seen_titles and not re.search(
            r"(?i)\bP\d+\b", str(ep.get("name") or "")
        ):
            # Second unmarked copy of a base already kept.
            continue
        if yid:
            seen_ids.add(yid)
        if full_key:
            seen_titles.add(full_key)
        if title_key:
            seen_titles.add(title_key)
        out.append(ep)

    out.sort(
        key=lambda e: (
            int(e.get("_order") or 10**9),
            str(e.get("youtube_id") or ""),
        )
    )
    return out


def _finalize_season_episodes(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe composites, align numbers with title codes, fill from playlist order."""
    if not episodes:
        return []

    ordered = _dedupe_season_episodes(episodes)
    infer_implicit_part_one_titles(ordered)

    used: set[int] = set()
    for ep in ordered:
        if ep.pop("_from_title", False):
            try:
                n = int(ep.get("number"))
            except (TypeError, ValueError):
                n = 0
            if n >= 1 and n not in used:
                ep["number"] = n
                used.add(n)
                continue
        ep["number"] = None

    next_n = 1
    for ep in ordered:
        if ep.get("number") is not None:
            continue
        while next_n in used:
            next_n += 1
        ep["number"] = next_n
        used.add(next_n)
        next_n += 1

    for ep in ordered:
        ep.pop("_order", None)

    ordered.sort(
        key=lambda e: (int(e.get("number") or 0), str(e.get("youtube_id") or ""))
    )
    return ordered


def show_from_cache_payload(
    payload: dict[str, Any],
    *,
    entry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a media-library show dict from a cache JSON payload."""
    if not isinstance(payload, dict):
        return None
    seasons_raw = payload.get("seasons")
    if not isinstance(seasons_raw, dict) or not seasons_raw:
        return None

    entry = entry or {}
    extra = _entry_extra_title_rules(entry)

    seasons: dict[int, dict[str, Any]] = {}
    for key, sdata in seasons_raw.items():
        try:
            snum = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(sdata, dict):
            continue
        eps_in = sdata.get("episodes") or []
        if not isinstance(eps_in, list):
            continue
        episodes: list[dict[str, Any]] = []
        for i, ep in enumerate(eps_in, start=1):
            if not isinstance(ep, dict):
                continue
            yid = ep.get("youtube_id") or youtube_id_from_episode(ep)
            if not yid:
                continue
            episodes.append(
                _episode_dict(
                    number=int(ep.get("number") or i),
                    name=str(ep.get("name") or yid),
                    youtube_id=yid,
                    thumbnail=ep.get("thumbnail"),
                    duration=ep.get("duration"),
                    extra_rules=extra,
                    playlist_order=i,
                )
            )
        episodes = _finalize_season_episodes(episodes)
        if not episodes:
            continue
        raw_label = str(
            sdata.get("label") or (f"Season {snum}" if snum else "All Videos")
        )
        seasons[snum] = {
            "label": sanitize_display_title(
                raw_label, kind="playlist", extra_rules=extra
            )
            or (f"Season {snum}" if snum else "All Videos"),
            "episodes": episodes,
            "thumbnail": sdata.get("thumbnail") or payload.get("thumbnail"),
        }
        if sdata.get("playlist_id"):
            seasons[snum]["playlist_id"] = str(sdata["playlist_id"])

    if not seasons:
        return None

    handle = (entry.get("handle") or payload.get("handle") or "").strip() or None
    show: dict[str, Any] = {
        "source": "youtube",
        "has_seasons": len(seasons) > 1,
        "seasons": seasons,
        "thumbnail": payload.get("thumbnail"),
    }
    if handle:
        show["youtube_handle"] = handle
    if entry.get("url"):
        show["youtube_url"] = entry["url"]
    if entry.get("channel") is not None:
        show["channel_number"] = int(entry["channel"])
    cache_id = payload.get("channel_id") or payload.get("cache_key")
    if cache_id:
        show["youtube_channel_id"] = str(cache_id)
    return show


def _unique_show_name(base: str, used: set[str], *, suffix: str | None = None) -> str:
    """Pick a show title that does not collide with ``used``."""
    name = (base or "YouTube").strip() or "YouTube"
    if name not in used:
        return name
    if suffix:
        alt = f"{name} ({suffix})"
        if alt not in used:
            return alt
        name = alt
    n = 2
    while f"{name} {n}" in used:
        n += 1
    return f"{name} {n}"


def _filter_channel_seasons(
    show: dict[str, Any],
    entry: dict[str, Any],
    *,
    extra_rules: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Apply ``include_playlists`` / ``include_all_videos`` to a channel show."""
    seasons = show.get("seasons") or {}
    if not isinstance(seasons, dict):
        return show

    include_all = entry.get("include_all_videos")
    selectors = entry.get("include_playlists")
    if not selectors and include_all is None:
        return show

    playlist_seasons = {
        int(k): v
        for k, v in seasons.items()
        if int(k) != 0 and isinstance(v, dict) and (v.get("episodes") or [])
    }
    all_videos = seasons.get(0)

    keep_all = True if include_all is None else bool(include_all)
    new_seasons: dict[int, dict[str, Any]] = {}
    if (
        keep_all
        and isinstance(all_videos, dict)
        and (all_videos.get("episodes") or [])
    ):
        new_seasons[0] = all_videos

    if selectors:
        groups = match_playlist_groups(
            playlist_seasons,
            selectors,
            sanitize_label=lambda lab: sanitize_display_title(
                lab, kind="playlist", extra_rules=extra_rules
            ),
        )
        # Flatten groups into seasons on the single channel show.
        # Prefer captured season numbers; avoid colliding with 0.
        for _title, grouped in groups:
            for sn, sdata in grouped.items():
                dest = int(sn)
                while dest in new_seasons:
                    dest += 1
                new_seasons[dest] = sdata
    else:
        new_seasons.update(playlist_seasons)

    if not new_seasons:
        return show
    out = dict(show)
    out["seasons"] = new_seasons
    out["has_seasons"] = len([k for k in new_seasons if int(k) != 0]) > 1 or (
        0 in new_seasons and len(new_seasons) > 1
    )
    return out


def expand_youtube_shows(
    channel_title: str,
    show: dict[str, Any],
    entry: dict[str, Any] | None = None,
    *,
    used_names: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Turn one channel show into one or more library shows.

    When ``entry["playlists_as_shows"]`` is true, playlists become distinct shows
    (optionally limited/grouped via ``playlist_shows``). The parent All Videos
    show is kept only when ``include_all_videos`` is true.

    When not unrolling, ``include_playlists`` can limit which playlists become
    seasons on the single channel show.
    """
    entry = entry or {}
    used = set(used_names or ())
    extra = _entry_extra_title_rules(entry)
    show = _filter_channel_seasons(show, entry, extra_rules=extra)

    if not entry.get("playlists_as_shows"):
        name = _unique_show_name(channel_title, used)
        single = dict(show)
        seasons_n = single.get("seasons") or {}
        if isinstance(seasons_n, dict):
            single["has_seasons"] = len(seasons_n) > 1
        return {name: single}

    seasons = show.get("seasons") or {}
    if not isinstance(seasons, dict):
        name = _unique_show_name(channel_title, used)
        return {name: show}

    playlist_seasons = {
        int(k): v
        for k, v in seasons.items()
        if int(k) != 0 and isinstance(v, dict) and (v.get("episodes") or [])
    }
    if not playlist_seasons:
        # Nothing to unroll yet — keep the channel show as-is.
        name = _unique_show_name(channel_title, used)
        return {name: show}

    out: dict[str, dict[str, Any]] = {}
    parent_title = (
        sanitize_display_title(channel_title, kind=None) or channel_title or "YouTube"
    )
    include_all = bool(entry.get("include_all_videos", False))
    all_videos = seasons.get(0)
    if (
        include_all
        and isinstance(all_videos, dict)
        and (all_videos.get("episodes") or [])
    ):
        parent = dict(show)
        parent["seasons"] = {0: all_videos}
        parent["has_seasons"] = False
        parent["youtube_playlists_as_shows"] = True
        name = _unique_show_name(parent_title, used)
        used.add(name)
        out[name] = parent

    selectors = entry.get("playlist_shows")
    # When unrolling with an include_playlists filter already applied, seasons
    # are pre-filtered; playlist_shows further groups. If only include_playlists
    # was used, treat each remaining playlist as its own show.
    groups = match_playlist_groups(
        playlist_seasons,
        selectors,
        sanitize_label=lambda lab: sanitize_display_title(
            lab, kind="playlist", extra_rules=extra
        ),
    )

    for show_title, grouped_seasons in groups:
        name = _unique_show_name(show_title, used, suffix=parent_title)
        used.add(name)
        multi = len(grouped_seasons) > 1
        if multi:
            built_seasons = {
                int(sn): {
                    "label": str(sdata.get("label") or f"Season {sn}"),
                    "episodes": list(sdata.get("episodes") or []),
                    "thumbnail": sdata.get("thumbnail") or show.get("thumbnail"),
                    **(
                        {"playlist_id": str(sdata["playlist_id"])}
                        if sdata.get("playlist_id")
                        else {}
                    ),
                }
                for sn, sdata in grouped_seasons.items()
            }
            pl_show: dict[str, Any] = {
                "source": "youtube",
                "has_seasons": True,
                "seasons": built_seasons,
                "thumbnail": next(
                    (
                        s.get("thumbnail")
                        for s in built_seasons.values()
                        if s.get("thumbnail")
                    ),
                    show.get("thumbnail"),
                ),
                "youtube_playlists_as_shows": True,
                "youtube_parent_title": parent_title,
            }
        else:
            sn, sdata = next(iter(grouped_seasons.items()))
            pl_label = str(sdata.get("label") or show_title)
            pl_show = {
                "source": "youtube",
                "has_seasons": False,
                "seasons": {
                    1: {
                        "label": pl_label,
                        "episodes": list(sdata.get("episodes") or []),
                        "thumbnail": sdata.get("thumbnail") or show.get("thumbnail"),
                    }
                },
                "thumbnail": sdata.get("thumbnail") or show.get("thumbnail"),
                "youtube_playlists_as_shows": True,
                "youtube_parent_title": parent_title,
            }
            if sdata.get("playlist_id"):
                pl_show["youtube_playlist_id"] = str(sdata["playlist_id"])
                pl_show["seasons"][1]["playlist_id"] = str(sdata["playlist_id"])

        if show.get("youtube_handle"):
            pl_show["youtube_handle"] = show["youtube_handle"]
        if show.get("youtube_url"):
            pl_show["youtube_url"] = show["youtube_url"]
        if show.get("youtube_channel_id"):
            pl_show["youtube_channel_id"] = show["youtube_channel_id"]
        out[name] = pl_show

    return out


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _cache_fresh(payload: dict[str, Any], *, ttl_s: float = CACHE_TTL_S) -> bool:
    try:
        fetched = float(payload.get("fetched_at") or 0)
    except (TypeError, ValueError):
        return False
    return fetched > 0 and (time.time() - fetched) < ttl_s


def _walk_find_keys(obj: Any, key: str, out: list[Any], *, limit: int = 500) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj[key])
            if len(out) >= limit:
                return
        for v in obj.values():
            _walk_find_keys(v, key, out, limit=limit)
    elif isinstance(obj, list):
        for item in obj:
            _walk_find_keys(item, key, out, limit=limit)


def _text_runs(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        if "simpleText" in obj:
            return str(obj["simpleText"])
        runs = obj.get("runs")
        if isinstance(runs, list):
            return "".join(str(r.get("text") or "") for r in runs if isinstance(r, dict))
        return ""
    return str(obj)


def _thumb_from_renderer(renderer: dict) -> str | None:
    thumbs = renderer.get("thumbnail") or {}
    if isinstance(thumbs, dict):
        entries = thumbs.get("thumbnails") or []
        if isinstance(entries, list) and entries:
            url = entries[-1].get("url") if isinstance(entries[-1], dict) else None
            if url:
                return str(url)
    return None


def _parse_duration_text(text: str) -> int | None:
    text = (text or "").strip()
    if not text or not re.match(r"^[\d:]+$", text):
        return None
    parts = [int(p) for p in text.split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 1:
        return parts[0]
    return None


def _video_from_renderer(renderer: dict) -> dict[str, Any] | None:
    vid = renderer.get("videoId")
    if not vid or not _YT_ID_RE.match(str(vid)):
        return None
    title = _text_runs(renderer.get("title")) or str(vid)
    length = _text_runs(renderer.get("lengthText"))
    duration = _parse_duration_text(length)
    return {
        "youtube_id": str(vid),
        "name": sanitize_display_title(title, kind="episode") or str(vid),
        "thumbnail": _thumb_from_renderer(renderer)
        or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        "duration": duration,
    }


def _lockup_title(lvm: dict) -> str:
    md = (lvm.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = md.get("title")
    if isinstance(title, dict):
        return str(title.get("content") or "").strip()
    return _text_runs(title).strip()


def _lockup_duration(lvm: dict) -> int | None:
    badges: list[Any] = []
    _walk_find_keys(lvm.get("contentImage") or {}, "thumbnailBadgeViewModel", badges, limit=20)
    for badge in badges:
        if not isinstance(badge, dict):
            continue
        dur = _parse_duration_text(str(badge.get("text") or ""))
        if dur is not None:
            return dur
    return None


def _lockup_thumbnail(lvm: dict) -> str | None:
    sources: list[Any] = []
    _walk_find_keys(lvm.get("contentImage") or {}, "sources", sources, limit=10)
    for src_list in sources:
        if isinstance(src_list, list) and src_list:
            last = src_list[-1]
            if isinstance(last, dict) and last.get("url"):
                return str(last["url"])
    return None


def _video_from_lockup(lvm: dict) -> dict[str, Any] | None:
    """Parse modern channel/playlist grid items (``lockupViewModel``)."""
    ctype = str(lvm.get("contentType") or "")
    if ctype and ctype != "LOCKUP_CONTENT_TYPE_VIDEO":
        return None
    vid = lvm.get("contentId")
    if not vid or not _YT_ID_RE.match(str(vid)):
        return None
    title = _lockup_title(lvm) or str(vid)
    thumb = _lockup_thumbnail(lvm) or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    return {
        "youtube_id": str(vid),
        "name": sanitize_display_title(title, kind="episode") or str(vid),
        "thumbnail": thumb,
        "duration": _lockup_duration(lvm),
    }


def _playlist_from_lockup(lvm: dict) -> dict[str, Any] | None:
    if str(lvm.get("contentType") or "") != "LOCKUP_CONTENT_TYPE_PLAYLIST":
        return None
    pid = lvm.get("contentId")
    if not pid or not isinstance(pid, str):
        return None
    if pid.startswith("RD") or pid.startswith("LL") or pid.startswith("WL"):
        return None
    title = sanitize_display_title(_lockup_title(lvm), kind="playlist") or pid
    return {
        "playlist_id": pid,
        "title": title,
        "thumbnail": _lockup_thumbnail(lvm),
    }


def extract_videos_from_yt_initial(data: dict) -> list[dict[str, Any]]:
    """Pull video items from ytInitialData (classic renderers + lockupViewModel)."""
    found: list[Any] = []
    _walk_find_keys(data, "videoRenderer", found, limit=400)
    _walk_find_keys(data, "gridVideoRenderer", found, limit=400)
    _walk_find_keys(data, "playlistVideoRenderer", found, limit=400)

    seen: set[str] = set()
    videos: list[dict[str, Any]] = []
    for renderer in found:
        if not isinstance(renderer, dict):
            continue
        parsed = _video_from_renderer(renderer)
        if parsed is None:
            continue
        yid = parsed["youtube_id"]
        if yid in seen:
            continue
        seen.add(yid)
        videos.append(parsed)

    lockups: list[Any] = []
    _walk_find_keys(data, "lockupViewModel", lockups, limit=400)
    for lvm in lockups:
        if not isinstance(lvm, dict):
            continue
        parsed = _video_from_lockup(lvm)
        if parsed is None:
            continue
        yid = parsed["youtube_id"]
        if yid in seen:
            continue
        seen.add(yid)
        videos.append(parsed)
    return videos


def extract_playlists_from_yt_initial(data: dict) -> list[dict[str, Any]]:
    """Pull public playlists (id + title) from channel playlists tab data."""
    found: list[Any] = []
    _walk_find_keys(data, "gridPlaylistRenderer", found, limit=200)
    _walk_find_keys(data, "playlistRenderer", found, limit=200)

    seen: set[str] = set()
    playlists: list[dict[str, Any]] = []
    for renderer in found:
        if not isinstance(renderer, dict):
            continue
        pid = renderer.get("playlistId")
        if not pid or not isinstance(pid, str):
            continue
        if pid in seen:
            continue
        if pid.startswith("RD") or pid.startswith("LL") or pid.startswith("WL"):
            continue
        title = sanitize_display_title(
            _text_runs(renderer.get("title")),
            kind="playlist",
        ) or pid
        seen.add(pid)
        playlists.append(
            {
                "playlist_id": pid,
                "title": title,
                "thumbnail": _thumb_from_renderer(renderer),
            }
        )

    lockups: list[Any] = []
    _walk_find_keys(data, "lockupViewModel", lockups, limit=200)
    for lvm in lockups:
        if not isinstance(lvm, dict):
            continue
        parsed = _playlist_from_lockup(lvm)
        if parsed is None:
            continue
        pid = parsed["playlist_id"]
        if pid in seen:
            continue
        seen.add(pid)
        playlists.append(parsed)
    return playlists


def extract_channel_meta(data: dict) -> dict[str, str | None]:
    """Best-effort channel title / avatar / id from page data."""
    title = None
    channel_id = None
    thumbnail = None

    metas: list[Any] = []
    _walk_find_keys(data, "channelMetadataRenderer", metas, limit=5)
    for meta in metas:
        if not isinstance(meta, dict):
            continue
        title = title or meta.get("title")
        channel_id = channel_id or meta.get("externalId")
        avatars = (meta.get("avatar") or {}).get("thumbnails") or []
        if isinstance(avatars, list) and avatars and isinstance(avatars[-1], dict):
            thumbnail = thumbnail or avatars[-1].get("url")

    headers: list[Any] = []
    _walk_find_keys(data, "c4TabbedHeaderRenderer", headers, limit=5)
    for hdr in headers:
        if not isinstance(hdr, dict):
            continue
        title = title or hdr.get("title")
        channel_id = channel_id or hdr.get("channelId")
        avatars = (hdr.get("avatar") or {}).get("thumbnails") or []
        if isinstance(avatars, list) and avatars and isinstance(avatars[-1], dict):
            thumbnail = thumbnail or avatars[-1].get("url")

    return {
        "title": str(title).strip() if title else None,
        "channel_id": str(channel_id).strip() if channel_id else None,
        "thumbnail": str(thumbnail) if thumbnail else None,
    }


_JS_YT_INITIAL = r"""
(() => {
  try {
    if (window.ytInitialData) return JSON.stringify(window.ytInitialData);
  } catch (e) {}
  const scripts = document.querySelectorAll('script');
  for (const s of scripts) {
    const t = s.textContent || '';
    const m = t.match(/ytInitialData\s*=\s*(\{[\s\S]*?\});\s*(?:var|window|<\/)/);
    if (m) {
      try { return m[1]; } catch (e) {}
    }
    const idx = t.indexOf('ytInitialData');
    if (idx >= 0) {
      const eq = t.indexOf('=', idx);
      if (eq > 0) {
        let i = eq + 1;
        while (i < t.length && /\s/.test(t[i])) i++;
        if (t[i] === '{') {
          let depth = 0;
          const start = i;
          for (; i < t.length; i++) {
            const c = t[i];
            if (c === '{') depth++;
            else if (c === '}') {
              depth--;
              if (depth === 0) {
                return t.slice(start, i + 1);
              }
            }
          }
        }
      }
    }
  }
  return null;
})()
""".strip()


def _cdp_eval_json(ws, expression: str, *, timeout: float = 8.0) -> Any:
    """Send Runtime.evaluate and return the JSON-decoded value (or None)."""
    cmd_id = int(time.time() * 1000) % 1_000_000_000
    ws.send(
        json.dumps(
            {
                "id": cmd_id,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": False,
                },
            }
        )
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = ws.recv()
        except Exception:
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if msg.get("id") != cmd_id:
            continue
        result = (msg.get("result") or {}).get("result") or {}
        val = result.get("value")
        if val is None:
            return None
        if isinstance(val, (dict, list)):
            return val
        if isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return val
        return val
    return None


def _scrape_page_yt_data(ws, url: str, *, settle_s: float = 2.5) -> dict | None:
    ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": url}}))
    time.sleep(settle_s)
    data = _cdp_eval_json(ws, _JS_YT_INITIAL, timeout=10.0)
    return data if isinstance(data, dict) else None


def extract_playlist_title(data: dict) -> str | None:
    """Best-effort playlist title from playlist page ytInitialData."""
    found: list[Any] = []
    _walk_find_keys(data, "playlistSidebarPrimaryInfoRenderer", found, limit=5)
    for block in found:
        if isinstance(block, dict):
            title = _text_runs(block.get("title"))
            if title:
                return title
    found = []
    _walk_find_keys(data, "playlistMetadataRenderer", found, limit=5)
    for block in found:
        if isinstance(block, dict) and block.get("title"):
            return str(block["title"]).strip() or None
    return None


def _episodes_from_videos(videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "number": i,
            "name": sanitize_display_title(v["name"], kind="episode") or v["youtube_id"],
            "youtube_id": v["youtube_id"],
            "thumbnail": v.get("thumbnail"),
            "duration": v.get("duration"),
        }
        for i, v in enumerate(videos, start=1)
    ]


def _build_catalog_from_ws(
    ws,
    channel_url: str,
    *,
    include_channel_playlists: bool = True,
) -> dict[str, Any] | None:
    """Scrape one channel/playlist using an already-open CDP WebSocket."""
    base = channel_url.rstrip("/")
    playlist_only = playlist_id_from_url(base)

    if playlist_only:
        pl_url = f"https://www.youtube.com/playlist?list={quote(playlist_only)}"
        pl_data = _scrape_page_yt_data(ws, pl_url, settle_s=2.5)
        if not pl_data:
            LOG.warning("YouTube catalog: no ytInitialData for playlist %s", playlist_only)
            return None
        videos = extract_videos_from_yt_initial(pl_data)[:MAX_PLAYLIST_VIDEOS]
        if not videos:
            LOG.warning("YouTube catalog: empty playlist %s", playlist_only)
            return None
        pl_title = sanitize_display_title(
            extract_playlist_title(pl_data) or playlist_only,
            kind="playlist",
        ) or playlist_only
        return {
            "fetched_at": time.time(),
            "channel_url": pl_url,
            "playlist_id": playlist_only,
            "title": pl_title,
            "channel_id": playlist_only,
            "thumbnail": videos[0].get("thumbnail"),
            "playlists_fetched": True,
            "seasons": {
                "0": {
                    "label": pl_title,
                    "episodes": _episodes_from_videos(videos),
                    "thumbnail": videos[0].get("thumbnail"),
                }
            },
        }

    videos_url = f"{base}/videos"
    videos_data = _scrape_page_yt_data(ws, videos_url, settle_s=2.5)
    if not videos_data:
        LOG.warning("YouTube catalog: no ytInitialData on /videos for %s", base)
        return None

    meta = extract_channel_meta(videos_data)
    uploads = extract_videos_from_yt_initial(videos_data)[:MAX_UPLOADS]

    seasons: dict[str, Any] = {}
    if uploads:
        seasons["0"] = {
            "label": "All Videos",
            "episodes": _episodes_from_videos(uploads),
            "thumbnail": meta.get("thumbnail"),
        }

    if include_channel_playlists:
        playlists_url = f"{base}/playlists"
        playlists: list[dict[str, Any]] = []
        playlists_data = _scrape_page_yt_data(ws, playlists_url, settle_s=2.0)
        if playlists_data:
            playlists = extract_playlists_from_yt_initial(playlists_data)[:MAX_PLAYLISTS]

        season_idx = 1 if uploads else 0
        for pl in playlists:
            pid = pl["playlist_id"]
            pl_url = f"https://www.youtube.com/playlist?list={quote(pid)}"
            pl_data = _scrape_page_yt_data(ws, pl_url, settle_s=1.8)
            pl_videos = (
                extract_videos_from_yt_initial(pl_data)[:MAX_PLAYLIST_VIDEOS]
                if pl_data
                else []
            )
            if not pl_videos:
                continue
            seasons[str(season_idx)] = {
                "label": sanitize_display_title(pl["title"], kind="playlist")
                or pl["playlist_id"],
                "episodes": _episodes_from_videos(pl_videos),
                "thumbnail": pl.get("thumbnail") or meta.get("thumbnail"),
                "playlist_id": pid,
            }
            season_idx += 1

    if not seasons:
        LOG.warning("YouTube catalog: empty uploads for %s", base)
        return None

    return {
        "fetched_at": time.time(),
        "channel_url": base,
        "title": sanitize_display_title(meta.get("title"), kind=None)
        or meta.get("title"),
        "channel_id": meta.get("channel_id"),
        "thumbnail": meta.get("thumbnail"),
        "seasons": seasons,
        "playlists_fetched": bool(include_channel_playlists),
    }


def _open_catalog_chrome(*, port: int = CDP_PORT):
    """Start Chrome + CDP websocket for catalog scraping. Returns (chrome, ws, user_data) or None."""
    if websocket is None:
        LOG.warning("websocket-client not installed — cannot scrape YouTube catalog")
        return None

    chrome_bin = ensure_chromium(log_label="youtube-catalog")
    if chrome_bin is None:
        LOG.warning("Chrome/Chromium not available for YouTube catalog")
        return None

    kill_port_process(port)
    user_data = tempfile.mkdtemp(prefix="ttc-yt-catalog-")
    try:
        chrome = subprocess.Popen(
            [
                chrome_bin,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={user_data}",
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--mute-audio",
                "--window-size=1280,720",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ws_url = wait_for_page_ws(port, chrome=chrome, timeout=15.0)
        if not ws_url:
            LOG.warning("YouTube catalog: CDP page not ready")
            chrome.terminate()
            return None
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
        ws.settimeout(2.0)
        return chrome, ws, user_data
    except Exception as exc:
        LOG.warning("YouTube catalog Chrome start failed: %s", exc)
        try:
            import shutil

            shutil.rmtree(user_data, ignore_errors=True)
        except Exception:
            pass
        return None


def _close_catalog_chrome(chrome, ws, user_data: str | None, *, port: int = CDP_PORT) -> None:
    if ws is not None:
        try:
            ws.close()
        except Exception:
            pass
    if chrome is not None:
        try:
            chrome.terminate()
            chrome.wait(timeout=5)
        except Exception:
            try:
                chrome.kill()
            except Exception:
                pass
    kill_port_process(port)
    if user_data:
        try:
            import shutil

            shutil.rmtree(user_data, ignore_errors=True)
        except Exception:
            pass


def scrape_channel_catalog(
    channel_url: str,
    *,
    port: int = CDP_PORT,
    include_channel_playlists: bool = True,
) -> dict[str, Any] | None:
    """Launch Chrome, scrape uploads + playlists (or a single playlist URL)."""
    opened = _open_catalog_chrome(port=port)
    if opened is None:
        return None
    chrome, ws, user_data = opened
    try:
        return _build_catalog_from_ws(
            ws, channel_url, include_channel_playlists=include_channel_playlists
        )
    except Exception as exc:
        LOG.warning("YouTube catalog scrape failed: %s", exc)
        return None
    finally:
        _close_catalog_chrome(chrome, ws, user_data, port=port)


def stub_youtube_show(entry: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Placeholder show so the browse list is immediate while catalog scrapes."""
    ref = normalize_channel_ref(entry)
    if not ref:
        return None
    title = sanitize_display_title(
        (entry.get("title") or "").strip()
        or (entry.get("handle") or "").strip().lstrip("@")
        or cache_key_for_entry(entry),
        kind=None,
    ) or cache_key_for_entry(entry)
    show: dict[str, Any] = {
        "source": "youtube",
        "has_seasons": True,
        "youtube_loading": True,
        "seasons": {
            0: {"label": "Loading...", "episodes": []},
        },
        "thumbnail": None,
    }
    if entry.get("handle"):
        show["youtube_handle"] = entry["handle"]
    if entry.get("url"):
        show["youtube_url"] = entry["url"]
    if entry.get("channel") is not None:
        try:
            show["channel_number"] = int(entry["channel"])
        except (TypeError, ValueError):
            pass
    return title, show


def load_channel_show(
    entry: dict[str, Any],
    *,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    scrape_fn=None,
    allow_scrape: bool = True,
) -> tuple[str, dict[str, Any]] | None:
    """Load one YouTube channel as (show_name, show_dict), using cache when fresh."""
    ref = normalize_channel_ref(entry)
    if not ref:
        return None

    cdir = cache_dir or youtube_cache_dir()
    key = cache_key_for_entry(entry)
    cache_path = cdir / f"{key}.json"
    payload = _read_cache(cache_path)

    need_scrape = force_refresh or payload is None or not _cache_fresh(payload)
    if need_scrape and allow_scrape:
        scraper = scrape_fn or scrape_channel_catalog
        fresh = scraper(ref)
        if fresh:
            fresh["cache_key"] = key
            if entry.get("handle"):
                fresh["handle"] = entry["handle"]
            _write_cache(cache_path, fresh)
            payload = fresh
        elif payload is None:
            LOG.warning("YouTube channel unavailable and no cache: %s", ref)
            return None
        else:
            LOG.info("YouTube scrape failed — using stale cache for %s", key)
    elif need_scrape and not allow_scrape and payload is None:
        return None

    if payload is None:
        return None
    show = show_from_cache_payload(payload, entry=entry)
    if show is None:
        return None

    if (entry.get("title") or "").strip():
        title = sanitize_display_title(entry.get("title"), kind=None) or key
    else:
        title = (
            sanitize_display_title(
                str(payload.get("title") or "").strip() or key,
                kind="playlist",
                extra_rules=_entry_extra_title_rules(entry),
            )
            or key
        )
    return title, show


def load_channel_shows(
    entry: dict[str, Any],
    *,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    scrape_fn=None,
    allow_scrape: bool = True,
    used_names: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load one config entry as one or more shows (playlist unroll when enabled)."""
    loaded = load_channel_show(
        entry,
        force_refresh=force_refresh,
        cache_dir=cache_dir,
        scrape_fn=scrape_fn,
        allow_scrape=allow_scrape,
    )
    if loaded is None:
        return {}
    title, show = loaded
    return expand_youtube_shows(title, show, entry, used_names=used_names)


def load_youtube_shows(
    cfg: dict[str, Any] | None,
    *,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    scrape_fn=None,
    allow_scrape: bool = True,
    include_stubs: bool = False,
    include_channel_playlists: bool = True,
) -> dict[str, dict[str, Any]]:
    """Return show_name → show dict for all configured YouTube channels.

    When ``allow_scrape`` is False, only disk cache is used (fast; for startup).
    Missing channels can be filled with loading stubs when ``include_stubs``.
    When scraping is allowed, one Chrome session scrapes every channel that needs
    a refresh (batched) unless a custom ``scrape_fn`` is provided.
    Entries with ``playlists_as_shows`` expand each playlist into its own show.
    """
    channels = (cfg or {}).get("youtube_channels") or []
    if not isinstance(channels, list) or not channels:
        return {}

    cdir = cache_dir or youtube_cache_dir()
    entries = [e for e in channels if isinstance(e, dict)]

    shows: dict[str, dict[str, Any]] = {}
    need_refresh: list[dict[str, Any]] = []

    def _merge(batch: dict[str, dict[str, Any]]) -> None:
        for name, show in batch.items():
            shows[name] = show

    for entry in entries:
        used = set(shows.keys())
        if allow_scrape and scrape_fn is None:
            key = cache_key_for_entry(entry)
            payload = _read_cache(cdir / f"{key}.json")
            if force_refresh or payload is None or not _cache_fresh(payload):
                need_refresh.append(entry)
                if payload is not None:
                    _merge(
                        load_channel_shows(
                            entry,
                            force_refresh=False,
                            cache_dir=cdir,
                            allow_scrape=False,
                            used_names=used,
                        )
                    )
                continue
            _merge(
                load_channel_shows(
                    entry,
                    force_refresh=False,
                    cache_dir=cdir,
                    allow_scrape=False,
                    used_names=used,
                )
            )
            continue

        _merge(
            load_channel_shows(
                entry,
                force_refresh=force_refresh,
                cache_dir=cdir,
                scrape_fn=scrape_fn,
                allow_scrape=allow_scrape,
                used_names=used,
            )
        )

    if need_refresh and allow_scrape and scrape_fn is None:
        opened = _open_catalog_chrome()
        if opened is not None:
            chrome, ws, user_data = opened
            try:
                for entry in need_refresh:
                    ref = normalize_channel_ref(entry)
                    if not ref:
                        continue
                    key = cache_key_for_entry(entry)
                    try:
                        fresh = _build_catalog_from_ws(
                            ws,
                            ref,
                            include_channel_playlists=include_channel_playlists,
                        )
                    except Exception as exc:
                        LOG.warning("YouTube scrape failed for %s: %s", ref, exc)
                        fresh = None
                    if fresh:
                        fresh["cache_key"] = key
                        if entry.get("handle"):
                            fresh["handle"] = entry["handle"]
                        _write_cache(cdir / f"{key}.json", fresh)
                        show = show_from_cache_payload(fresh, entry=entry)
                        if show:
                            if (entry.get("title") or "").strip():
                                title = (
                                    sanitize_display_title(entry.get("title"), kind=None)
                                    or key
                                )
                            else:
                                title = (
                                    sanitize_display_title(
                                        str(fresh.get("title") or "").strip() or key,
                                        kind="playlist",
                                        extra_rules=_entry_extra_title_rules(entry),
                                    )
                                    or key
                                )
                            _merge(
                                expand_youtube_shows(
                                    title, show, entry, used_names=set(shows.keys())
                                )
                            )
                    else:
                        LOG.warning(
                            "YouTube channel unavailable%s: %s",
                            "" if any(
                                isinstance(s, dict) and s.get("source") == "youtube"
                                for s in shows.values()
                            )
                            else " and no cache",
                            ref,
                        )
            finally:
                _close_catalog_chrome(chrome, ws, user_data)
        else:
            LOG.warning("YouTube catalog Chrome unavailable — using cache/stubs only")

    if include_stubs:
        for entry in entries:
            stub = stub_youtube_show(entry)
            if stub is None:
                continue
            name, show = stub
            # Only add a loading placeholder when nothing from this entry landed yet.
            parent = sanitize_display_title(
                (entry.get("title") or "").strip()
                or (entry.get("handle") or "").strip().lstrip("@")
                or name,
                kind=None,
            ) or name
            already = any(
                isinstance(s, dict)
                and s.get("source") == "youtube"
                and (
                    s.get("youtube_parent_title") == parent
                    or n == parent
                    or s.get("youtube_url") == entry.get("url")
                    or s.get("youtube_handle") == entry.get("handle")
                )
                for n, s in shows.items()
            )
            if not already and name not in shows:
                shows[name] = show

    return shows


def merge_youtube_channel_numbers(
    channels_cfg: dict[str, Any] | None,
    shows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Copy of channels config with YouTube ``channel_number`` merged into numbers."""
    cfg = dict(channels_cfg or {})
    numbers = dict(cfg.get("numbers") or {})
    for name, show in shows.items():
        if not isinstance(show, dict):
            continue
        if show.get("source") != "youtube":
            continue
        num = show.get("channel_number")
        if num is None:
            continue
        try:
            numbers[name] = int(num)
        except (TypeError, ValueError):
            continue
    cfg["numbers"] = numbers
    return cfg