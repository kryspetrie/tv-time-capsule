"""Playlist include/group selectors for YouTube channel expansion."""

from __future__ import annotations

import re
from typing import Any


def _exact_pattern(text: str) -> str:
    return rf"(?i)^{re.escape(text.strip())}$"


def parse_playlist_selectors(raw: Any) -> list[dict[str, Any]]:
    """Parse ``playlist_shows`` / ``include_playlists`` config lists.

    Accepted items:

    * ``"Bobby's World"`` — case-insensitive exact title match → one show/season
    * ``{"match": "(?i)^Season\\\\s+(\\\\d+)$"}`` — regex; digit capture → season #
    * ``{"title": "Ghostwriter", "match": "(?i)^Ghostwriter\\\\s+Season\\\\s+(\\\\d+)$"}``
    * ``{"title": "Ghostwriter", "playlists": ["Ghostwriter Season 1", ...]}``
    * ``{"title": "X", "playlists": [{"match": "...", "season": 2}, ...]}``

    Stored form is JSON-serializable (pattern strings, not compiled regexes).
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            try:
                re.compile(_exact_pattern(text))
            except re.error:
                continue
            out.append(
                {
                    "title": text,
                    "patterns": [{"match": _exact_pattern(text), "season": None}],
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        title_s = str(title).strip() if title is not None else ""
        patterns: list[dict[str, Any]] = []

        playlists = item.get("playlists")
        if isinstance(playlists, list) and playlists:
            for pl in playlists:
                if isinstance(pl, str):
                    pat = _exact_pattern(pl)
                    try:
                        re.compile(pat)
                    except re.error:
                        continue
                    patterns.append({"match": pat, "season": None})
                elif isinstance(pl, dict):
                    m = pl.get("match") or pl.get("pattern")
                    if not m:
                        name = pl.get("title") or pl.get("name")
                        if name:
                            m = _exact_pattern(str(name))
                    if not m:
                        continue
                    try:
                        re.compile(str(m))
                    except re.error:
                        continue
                    season = pl.get("season")
                    try:
                        season_i = int(season) if season is not None else None
                    except (TypeError, ValueError):
                        season_i = None
                    if season_i is not None and season_i < 1:
                        season_i = None
                    patterns.append({"match": str(m), "season": season_i})
        else:
            match = item.get("match") or item.get("pattern")
            if match:
                try:
                    re.compile(str(match))
                except re.error:
                    continue
                season = item.get("season")
                try:
                    season_i = int(season) if season is not None else None
                except (TypeError, ValueError):
                    season_i = None
                if season_i is not None and season_i < 1:
                    season_i = None
                patterns.append({"match": str(match), "season": season_i})
            elif title_s:
                pat = _exact_pattern(title_s)
                try:
                    re.compile(pat)
                except re.error:
                    continue
                patterns.append({"match": pat, "season": None})

        if not patterns:
            continue
        out.append({"title": title_s or None, "patterns": patterns})
    return out


def _labels_for_match(raw_label: str, sanitized: str) -> list[str]:
    labels = []
    for lab in (raw_label, sanitized):
        lab = (lab or "").strip()
        if lab and lab not in labels:
            labels.append(lab)
    return labels


def _match_season(
    patterns: list[dict[str, Any]],
    labels: list[str],
) -> tuple[bool, int | None]:
    """Return (matched, season_number_or_None)."""
    for pat in patterns:
        match = pat.get("match") or ""
        if not match:
            continue
        try:
            cre = re.compile(str(match))
        except re.error:
            continue
        forced = pat.get("season")
        for lab in labels:
            m = cre.search(lab)
            if not m:
                continue
            if forced is not None:
                try:
                    return True, int(forced)
                except (TypeError, ValueError):
                    return True, None
            if m.lastindex:
                try:
                    return True, int(m.group(1))
                except (TypeError, ValueError):
                    return True, None
            return True, None
    return False, None


def match_playlist_groups(
    playlist_seasons: dict[int, dict[str, Any]],
    selectors: list[dict[str, Any]] | None,
    *,
    sanitize_label,
) -> list[tuple[str, dict[int, dict[str, Any]]]]:
    """Group playlist seasons according to selectors.

    When ``selectors`` is None/empty, each playlist is its own group (title =
    sanitized label, single season 1).

    Returns list of ``(show_title, {season_num: season_dict})``.
    """
    items: list[tuple[int, dict[str, Any], str, str]] = []
    for snum in sorted(playlist_seasons.keys()):
        sdata = playlist_seasons[snum]
        if not isinstance(sdata, dict) or not (sdata.get("episodes") or []):
            continue
        raw = str(sdata.get("label") or f"Playlist {snum}")
        clean = sanitize_label(raw) or raw
        items.append((snum, sdata, raw, clean))

    if not selectors:
        return [
            (
                clean,
                {
                    1: {
                        **sdata,
                        "label": clean,
                    }
                },
            )
            for _snum, sdata, _raw, clean in items
        ]

    claimed: set[int] = set()
    groups: list[tuple[str, dict[int, dict[str, Any]]]] = []

    for sel in selectors:
        patterns = sel.get("patterns") or []
        title_override = sel.get("title")
        matched: list[tuple[int, dict[str, Any], str, int | None]] = []
        for snum, sdata, raw, clean in items:
            if snum in claimed:
                continue
            labels = _labels_for_match(raw, clean)
            ok, season_n = _match_season(patterns, labels)
            if not ok:
                continue
            matched.append((snum, sdata, clean, season_n))
        if not matched:
            continue
        for snum, _sdata, _clean, _sn in matched:
            claimed.add(snum)

        used_seasons: set[int] = set()
        assigned: list[tuple[int, dict[str, Any], str]] = []
        auto = 1
        for snum, sdata, clean, season_n in sorted(
            matched, key=lambda t: (t[3] is None, t[3] or 0, t[0])
        ):
            if season_n is not None and season_n not in used_seasons:
                sn = season_n
            else:
                while auto in used_seasons:
                    auto += 1
                sn = auto
                auto += 1
            used_seasons.add(sn)
            if len(matched) > 1:
                label = f"Season {sn}"
            else:
                label = title_override or clean
            assigned.append(
                (
                    sn,
                    {
                        **sdata,
                        "label": label,
                    },
                    clean,
                )
            )

        if title_override:
            show_title = title_override
        elif len(matched) == 1:
            show_title = matched[0][2]
        else:
            show_title = matched[0][2]
            base = re.sub(
                r"(?i)\s*[-–—:|]?\s*Season\s+\d+\s*$",
                "",
                matched[0][2],
            ).strip()
            if base and all(
                re.sub(r"(?i)\s*[-–—:|]?\s*Season\s+\d+\s*$", "", m[2]).strip()
                == base
                for m in matched
            ):
                show_title = base

        seasons = {sn: sdata for sn, sdata, _clean in assigned}
        groups.append((show_title, seasons))

    return groups
