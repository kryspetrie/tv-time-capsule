"""YouTube playlist/episode title normalization via configurable regex rules."""

from __future__ import annotations

import re
from typing import Any


# Default substitutions tuned against the kids/classic channel catalog
# (scraped Aug 2026). Applied after ASCII sanitization.
# ``scope``: episode | playlist | all.
DEFAULT_YOUTUBE_TITLE_RULES: list[dict[str, Any]] = [
    # --- Trailing brand / channel pipes (episodes + playlists) ---
    # After emoji/OSD sanitization, Scholastic titles often keep a plain trailing
    # "Scholastic Classic" (no "|"), e.g. "Goosebumps Scholastic Classic".
    {
        "pattern": r"(?i)\s*(?:\|\s*)?Scholastic Classic\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*PBS KIDS(?:\s*#Shorts|\s*Games\s*#Shorts)?\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*SciShow Kids(?:\s+Compilation)?\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*A SciShow Kids Playlist\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Thomas\s*&\s*Friends\b",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Thomas the Tank Engine\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Bluey\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Sesame Street\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Sesame Street (?:Songs|Full Episodes?)\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*(?:FOUR|THREE|TWO)\s+Sesame Street Full Episodes\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Reading Rainbow\b.*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Mister Rogers['’]? Neighborhood\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Ms\.?\s*Rachel\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Ms\.?\s*Moni\s*$",
        "replace": "",
        "scope": "episode",
    },
    # --- Episode fluff segments ---
    {
        "pattern": r"(?i)\s*\|\s*Full Episodes?\b",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Halloween Full Episodes?\b",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Throwback Full Episode\b",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*[-–—]\s*Full Episode\s*#\d+\b",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s+Full Episodes?\s*$",
        "replace": "",
        "scope": "episode",
    },
    # --- Leading season / episode codes (display-only; numbers still parsed from raw) ---
    # "Season 3, Episode 2b, Title" / "Show Season 3 - Episode 2 - Title"
    {
        "pattern": (
            r"(?i)^(?:(?:[\w'&.]+(?:\s+[\w'&.]+){0,4})\s+)?"
            r"Season\s+\d{1,2}\s*[,:\-–—]\s*Episode\s+\d{1,3}[ab]?\s*[,:\-–—]?\s*"
        ),
        "replace": "",
        "scope": "episode",
    },
    # Broken leftover: "Season 3 - b - Title" (or with a short show prefix)
    {
        "pattern": (
            r"(?i)^(?:(?:[\w'&.]+(?:\s+[\w'&.]+){0,4})\s+)?"
            r"Season\s+\d{1,2}\s*[-–—,:]\s*[ab]\s*[-–—,:]?\s*"
        ),
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)^S\d{1,2}\s*[.\-_ ]?\s*E\d{1,3}[ab]?\s*[-–—,:]?\s*",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)^Episode\s*#?\s*[\d\-]+[ab]?\s*[|:]\s*",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Season\s*\d+\s*$",
        "replace": "",
        "scope": "episode",
    },
    # --- Leading "FULL EPISODE |" wrappers (optional short show prefix) ---
    {
        "pattern": (
            r"(?i)^(?:(?:[\w'&.]+(?:\s+[\w'&.]+){0,4})\s+)?"
            r"FULL\s+EPISODES?\s*[|:]\s*"
        ),
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": (
            r"(?i)^(?:(?:[\w'&.]+(?:\s+[\w'&.]+){0,4})\s+)?"
            r"full\s+episode\s*[|:]*\s*\"([^\"]+)\"\s*$"
        ),
        "replace": r"\1",
        "scope": "episode",
    },
    {
        "pattern": (
            r"(?i)^(?:(?:[\w'&.]+(?:\s+[\w'&.]+){0,4})\s+)?"
            r"full\s+episode\s*[|:]\s*"
        ),
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\(?\s*Itunes?Rip\s*\)?\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*\d+\+?\s*Minutes!?\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*\d+\s*HOURS?\b[^|]*",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*NGSS(?:\s+Standards?)?(?:\s+Grades?\s*[\d\-–—]+)?\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*NGSS(?:\s+Standards?)?(?:\s+Grades?\s*[\d\-–—]+)?\s*\|",
        "replace": " |",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Teens Transform into Animals\s*",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Battling Aliens with Animal Powers\s*",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*The Magic School Bus\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Science for Kids\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Clifford(?:'s Puppy Days| the Big Red Dog)?\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Lessons for Kids\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Goosebumps\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Animorphs\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*New Compilation\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Educational Videos for Kids\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|?\s*@Kidzuko\b",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Official Trailer\b.*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Netflix\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*NEW MUSIC VIDEO\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Kids Cartoons?\b",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Classic 90s Cartoon\b",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Kabillion\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Compilation\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\|\s*Song\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*\(Official (?:Visualizer|Music Video)\)\s*.*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*[-–—]\s*(?:Best Quality\s*[-–—]\s*)?4K UPSCALED\s*$",
        "replace": "",
        "scope": "episode",
    },
    {
        "pattern": r"(?i)\s*[-–—]\s*Best Quality\s*$",
        "replace": "",
        "scope": "episode",
    },
    # --- Playlist naming cleanup ---
    {
        "pattern": r"(?i)\s*[-–—]\s*Official Channel\s*$",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)\s*\(Official\)\s*$",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)\s*[-–—]\s*(?:4K(?:\s*UPSCALE)?|UPSCALE|480p|720p|1080p|2160p|HD)\b.*$",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)^Bill Nye The Science Guy\s*[-–—]\s*",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)^Bill Nye The Science Guy\s+",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)\s*\|\s*Brand New(?:\s+Original(?:\s+Series)?)?\b.*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\bBRAND NEW(?:\s+SERIES|\s+BLUEY|\s+Original(?:\s+Series)?)?\b[:\s|!]*",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"(?i)\s*\|\s*Bluey\b.*$",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)\s*\|\s*CLASSIC FULL EPISODES\s*$",
        "replace": "",
        "scope": "playlist",
    },
    {
        "pattern": r"(?i)\s*!\s*Full Episodes!?\s*$",
        "replace": "",
        "scope": "playlist",
    },
    # --- Compact Beakman-style codes already short; trim extra spaces around x ---
    {
        "pattern": r"(?i)\b(\d+)\s*x\s*(\d+)\b",
        "replace": r"\1x\2",
        "scope": "episode",
    },
    # --- Trailing separators / empty pipes left by earlier rules ---
    {
        "pattern": r"\s*\|\s*$",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"^\s*\|\s*",
        "replace": "",
        "scope": "all",
    },
    {
        "pattern": r"\s*\|\s*\|\s*",
        "replace": " | ",
        "scope": "all",
    },
    {
        "pattern": r"\s{2,}",
        "replace": " ",
        "scope": "all",
    },
]


def show_name_prefix_rule(
    name: str,
    *,
    scope: str = "all",
) -> dict[str, Any] | None:
    """Build a rule that strips a leading ``Name -`` / ``Name |`` / ``Name:`` prefix.

    Matches the common per-channel cleanup ``s/^Name of Show\\s*[-–—|:]\\s*//i``.
    """
    cleaned = (name or "").strip()
    if not cleaned:
        return None
    scope_l = (scope or "all").strip().lower()
    if scope_l not in ("all", "episode", "playlist"):
        scope_l = "all"
    return {
        "pattern": rf"(?i)^{re.escape(cleaned)}\s*[-–—|:]\s*",
        "replace": "",
        "scope": scope_l,
    }


def _normalize_scope(raw: Any) -> str:
    scope = str(raw or "all").strip().lower()
    if scope not in ("all", "episode", "playlist"):
        return "all"
    return scope


def _compile_rule(
    pattern: str,
    replace: str = "",
    *,
    scope: str = "all",
) -> dict[str, Any] | None:
    """Validate a Python regex and return a normalized rule dict."""
    if not pattern or not isinstance(pattern, str):
        return None
    pattern = pattern.strip()
    if not pattern:
        return None
    try:
        re.compile(pattern)
    except re.error:
        return None
    if replace is None:
        replace = ""
    return {
        "pattern": pattern,
        "replace": str(replace),
        "scope": _normalize_scope(scope),
    }


def _parse_deletion_item(item: Any) -> dict[str, Any] | None:
    """A deletion is a pattern string or ``{pattern, scope?}``."""
    if isinstance(item, str):
        return _compile_rule(item, "")
    if isinstance(item, dict):
        pattern = item.get("pattern") or item.get("match") or item.get("delete")
        if not pattern:
            return None
        return _compile_rule(str(pattern), "", scope=item.get("scope", "all"))
    return None


def _parse_substitution_item(item: Any) -> dict[str, Any] | None:
    """A substitution is ``[pattern, replace]`` or ``{pattern, replace, scope?}``."""
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return _compile_rule(str(item[0]), str(item[1] if item[1] is not None else ""))
    if isinstance(item, dict):
        pattern = item.get("pattern") or item.get("match") or item.get("from")
        if not pattern:
            return None
        replace = item.get("replace")
        if replace is None:
            replace = item.get("to", "")
        return _compile_rule(str(pattern), str(replace), scope=item.get("scope", "all"))
    return None


def _parse_title_rules(raw: Any) -> list[dict[str, Any]]:
    """Normalize title rules from several config shapes.

    Accepted forms (all patterns are full Python regexes; use ``(?i)`` etc.):

    * **List of rules** — dicts ``{pattern, replace, scope?}``, bare deletion
      strings, or substitution pairs ``[pattern, replace]``.
    * **Object** — ``{deletions: [...], substitutions: [...], rules?: [...]}``
      where deletions remove matches and substitutions are find/replace pairs.
      ``delete`` / ``subs`` are accepted as aliases.
    """
    if raw is None:
        return []

    if isinstance(raw, dict):
        # Single rule object {pattern, replace} (no deletions/substitutions keys).
        if (
            ("pattern" in raw or "match" in raw)
            and "deletions" not in raw
            and "delete" not in raw
            and "substitutions" not in raw
            and "subs" not in raw
            and "rules" not in raw
        ):
            rule = _parse_substitution_item(raw)
            return [rule] if rule else []

        out: list[dict[str, Any]] = []
        deletions = raw.get("deletions")
        if deletions is None:
            deletions = raw.get("delete")
        if isinstance(deletions, list):
            for item in deletions:
                rule = _parse_deletion_item(item)
                if rule:
                    out.append(rule)
        elif deletions is not None:
            rule = _parse_deletion_item(deletions)
            if rule:
                out.append(rule)

        substitutions = raw.get("substitutions")
        if substitutions is None:
            substitutions = raw.get("subs")
        if isinstance(substitutions, list):
            for item in substitutions:
                rule = _parse_substitution_item(item)
                if rule:
                    out.append(rule)
        elif substitutions is not None:
            rule = _parse_substitution_item(substitutions)
            if rule:
                out.append(rule)

        nested = raw.get("rules")
        if nested is not None:
            out.extend(_parse_title_rules(nested))
        return out

    if not isinstance(raw, list):
        return []

    out = []
    for item in raw:
        if isinstance(item, str):
            rule = _parse_deletion_item(item)
            if rule:
                out.append(rule)
            continue
        if isinstance(item, (list, tuple)):
            rule = _parse_substitution_item(item)
            if rule:
                out.append(rule)
            continue
        if isinstance(item, dict):
            if any(
                k in item
                for k in ("deletions", "delete", "substitutions", "subs", "rules")
            ):
                out.extend(_parse_title_rules(item))
            else:
                # Full rule or substitution-shaped dict.
                replace = item.get("replace")
                if replace is None and "to" not in item and not item.get("pattern"):
                    rule = _parse_deletion_item(item)
                else:
                    rule = _parse_substitution_item(item)
                    if rule is None:
                        rule = _parse_deletion_item(item)
                if rule:
                    out.append(rule)
    return out


def apply_youtube_title_rules(
    text: str,
    rules: list[dict[str, Any]] | None,
    *,
    kind: str = "all",
) -> str:
    """Apply regex substitutions; ``kind`` is episode, playlist, or all."""
    if not text:
        return ""
    if not rules:
        return text
    kind_l = (kind or "all").strip().lower()
    result = text
    for rule in rules:
        scope = str(rule.get("scope") or "all").lower()
        if scope not in ("all", kind_l) and kind_l != "all":
            continue
        pattern = rule.get("pattern") or ""
        if not pattern:
            continue
        replace = rule.get("replace", "")
        try:
            result = re.sub(pattern, str(replace), result)
        except re.error:
            continue
    result = re.sub(r"\s{2,}", " ", result).strip(" -|\t")
    return result


# Season/episode markers commonly embedded in YouTube upload titles.
# Optional ``a``/``b`` suffixes (Arthur half-episodes: "Episode 2b", "S01E05A").
_EPISODE_CODE_PATTERNS: list[re.Pattern[str]] = [
    # S01E02, S1E2, S01.E02, S01_E02, S01E02b
    re.compile(
        r"(?i)(?<![A-Za-z0-9])S(\d{1,2})\s*[.\-_ ]?\s*E(\d{1,3})(?:[ab])?(?![A-Za-z0-9])"
    ),
    # 1x02, 01x2, 1×02
    re.compile(
        r"(?i)(?<![A-Za-z0-9])(\d{1,2})\s*[xX×]\s*(\d{1,3})(?![A-Za-z0-9])"
    ),
    # Season 7 Episode 22 / Season 7, Episode 22 / Season 7 - Episode 22b
    re.compile(
        r"(?i)Season\s*(\d{1,2})\s*[,:\-–—]?\s*Episode\s*#?\s*(\d{1,3})(?:[ab])?\b"
    ),
    # Season 7 Ep. 22 / Season 7 Ep 22a
    re.compile(
        r"(?i)Season\s*(\d{1,2})\s+Ep\.?\s*#?\s*(\d{1,3})(?:[ab])?\b"
    ),
]

# Episode-only markers (no season) — used when SxE-style patterns did not match.
# Do not treat "Episode 1-3" ranges as a single episode number.
# Include optional a/b so "Episode 2b" does not leave a stray "b".
_EPISODE_ONLY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bEpisode\s*#?\s*(\d{1,3})(?:[ab])?(?!\s*[-–—]\s*\d)"),
    re.compile(r"(?i)\bEp\.?\s*#?\s*(\d{1,3})(?:[ab])?(?!\s*[-–—]\s*\d)"),
]

# Broken leftover from partial strips: "Season 3 - b - Title"
_SEASON_LETTER_ORPHAN = re.compile(
    r"(?i)Season\s*(\d{1,2})\s*[-–—,:]\s*[ab]\b\s*[-–—,:]?\s*"
)

# "1 - Title" / "12 – Title" at the start of a title.
_LEADING_EPISODE_NUM = re.compile(r"^(\d{1,3})\s*[-–—]\s+")

# Multi-part / range markers used for composite detection.
_MULTI_PART_MARK = re.compile(r"(?i)\bP\d+(?:/P\d+)+|\bP\d+-P\d+\b")
_PART_SUFFIX = re.compile(r"(?i)\s*P\d+(?:/P\d+|-P\d+)*\s*$")
_EPISODE_RANGE_MARK = re.compile(
    r"(?i)(?:\b(?:full\s+)?episodes?\s*)?(\d{1,3})\s*[-–—]\s*(\d{1,3})\b"
)
_RANGE_ONLY_TITLE = re.compile(r"^\d{1,3}\s*[-–—]\s*\d{1,3}$")


def extract_episode_code(title: str) -> tuple[int | None, int | None]:
    """Parse ``(season, episode)`` from title markers like ``S01E02`` / ``1x02``.

    Returns ``(None, None)`` when no recognizable code is present. Season may be
    ``None`` when only an episode marker (e.g. ``Episode 22`` or ``1 -``) is found.
    Optional ``a``/``b`` suffixes on episode numbers are accepted and ignored for
    the numeric episode value (Arthur-style half-episodes).
    """
    text = str(title or "")
    if not text:
        return None, None
    for cre in _EPISODE_CODE_PATTERNS:
        m = cre.search(text)
        if not m:
            continue
        try:
            season = int(m.group(1))
            episode = int(m.group(2))
        except (TypeError, ValueError, IndexError):
            continue
        if season < 0 or episode < 1:
            continue
        return season, episode
    for cre in _EPISODE_ONLY_PATTERNS:
        m = cre.search(text)
        if not m:
            continue
        try:
            episode = int(m.group(1))
        except (TypeError, ValueError, IndexError):
            continue
        if episode < 1:
            continue
        return None, episode
    m = _SEASON_LETTER_ORPHAN.search(text)
    if m:
        try:
            season = int(m.group(1))
        except (TypeError, ValueError):
            season = -1
        if season >= 0:
            return season, None
    m = _LEADING_EPISODE_NUM.match(text)
    if m:
        try:
            episode = int(m.group(1))
        except (TypeError, ValueError):
            episode = 0
        if episode >= 1:
            return None, episode
    return None, None


def _tidy_after_code_strip(text: str) -> str:
    # Collapse leftover separator runs left by removed codes (e.g. "A - S01E02 - B").
    text = re.sub(r"(?:\s*[-–—|:,;.]+\s*)+", " - ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"^\s*[-–—|,:;.]+\s*", "", text)
    text = re.sub(r"\s*[-–—|,:;.]+\s*$", "", text)
    return text.strip(" -–—|,:;.")


def strip_episode_codes(title: str) -> str:
    """Remove SxE / NxN / Season-Episode / leading ``N -`` markers from a title."""
    text = str(title or "")
    if not text:
        return ""
    for cre in _EPISODE_CODE_PATTERNS:
        text = cre.sub(" ", text)
    for cre in _EPISODE_ONLY_PATTERNS:
        text = cre.sub(" ", text)
    text = _SEASON_LETTER_ORPHAN.sub(" ", text)
    text = _LEADING_EPISODE_NUM.sub("", text)
    return _tidy_after_code_strip(text)


def shorten_part_markers(title: str) -> str:
    """Shorten ``Part 1`` / ``Pt. 1`` / ``Pt 1&2`` style markers to ``P1`` / ``P1&2``."""
    text = str(title or "")
    if not text:
        return ""

    def _pair(m: re.Match[str]) -> str:
        a, sep, b = m.group(1), m.group(2), m.group(3)
        if sep.lower() in ("to", "-", "–", "—"):
            return f"P{a}-P{b}"
        return f"P{a}/P{b}"

    # Part 1 & 2 / Part 1 and Part 2 / Pt 1&2 / Part 1 to 3 / Part 1-3
    # Also "Pt - 1&2" (dash between Pt and the numbers).
    text = re.sub(
        r"(?i)\bParts?\s*[-–—]?\s*(\d+)\s*(&|and|to|[-–—])\s*(?:Parts?\s*)?(\d+)\b",
        _pair,
        text,
    )
    text = re.sub(
        r"(?i)\bPts?\.?\s*[-–—]?\s*(\d+)\s*(&|and|to|[-–—])\s*(?:Pts?\.?\s*)?(\d+)\b",
        _pair,
        text,
    )
    # Single: Part 1 / Pt1 / Pt.1 / Pt 1 / Pt - 1
    text = re.sub(r"(?i)\bParts?\s*[-–—]?\s*(\d+)\b", r"P\1", text)
    text = re.sub(r"(?i)\bPts?\.?\s*[-–—]?\s*(\d+)\b", r"P\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def apply_episode_codes(title: str) -> tuple[str, int | None, int | None]:
    """Return ``(cleaned_title, season, episode)`` from embedded episode codes.

    Also shortens Part/Pt markers (``Part 1`` → ``P1``) on the display title.
    """
    season, episode = extract_episode_code(title)
    if season is not None or episode is not None:
        text = strip_episode_codes(title)
    else:
        text = str(title or "").strip()
    text = shorten_part_markers(text)
    return text, season, episode


def _normalize_title_key(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def episode_base_key(name: str) -> str:
    """Normalized title with trailing ``P1`` / ``P1/P2`` markers removed."""
    text = str(name or "").strip()
    text = _PART_SUFFIX.sub("", text)
    text = _tidy_after_code_strip(text)
    return _normalize_title_key(text)


def episode_coverage_keys(name: str) -> set[str]:
    """Base title keys this display name appears to cover (pipe-separated)."""
    text = str(name or "").strip()
    if not text:
        return set()
    parts = [p.strip() for p in re.split(r"\s*\|\s*", text) if p.strip()]
    keys: set[str] = set()
    for part in parts:
        # Skip pure ranges / leftover show codes.
        if _RANGE_ONLY_TITLE.match(part.strip()):
            continue
        if re.match(r"(?i)^animorphs\s+\d", part):
            continue
        key = episode_base_key(part)
        if key and len(key) >= 3:
            keys.add(key)
    if not keys:
        key = episode_base_key(text)
        if key:
            keys.add(key)
    return keys


def is_composite_episode_title(name: str) -> bool:
    """True for multi-part packs, multi-episode joins, or episode-number ranges."""
    text = str(name or "").strip()
    if not text:
        return False
    if _MULTI_PART_MARK.search(text):
        return True
    if _RANGE_ONLY_TITLE.match(text):
        return True
    m = _EPISODE_RANGE_MARK.search(text)
    if m:
        try:
            a, b = int(m.group(1)), int(m.group(2))
        except (TypeError, ValueError):
            a, b = 0, 0
        if 1 <= a < b <= a + 30:
            return True
    segments = [p.strip() for p in re.split(r"\s*\|\s*", text) if p.strip()]
    real = [
        s
        for s in segments
        if not _RANGE_ONLY_TITLE.match(s)
        and not re.match(r"(?i)^animorphs\s+\d", s)
    ]
    if len(real) >= 2:
        if any(_MULTI_PART_MARK.search(s) for s in real):
            return True
        part_segs = [s for s in real if re.search(r"(?i)\bP\d+\b", s)]
        if len(part_segs) >= 2:
            return True
        # "Title P1 | Underground" — part + short companion title (not a long blurb).
        if len(real) == 2 and len(part_segs) == 1:
            other = real[0] if real[1] in part_segs else real[1]
            words = episode_base_key(other).split()
            if 1 <= len(words) <= 4:
                return True
    return False


def episode_part_number(name: str) -> int | None:
    """Return a trailing ``Pn`` part number, or ``None`` if unmarked / multi-part."""
    text = str(name or "").strip()
    if not text or _MULTI_PART_MARK.search(text):
        return None
    m = re.search(r"(?i)\s*P(\d+)\s*$", text)
    if not m:
        return None
    try:
        num = int(m.group(1))
    except (TypeError, ValueError):
        return None
    return num if num >= 1 else None


def infer_implicit_part_one_titles(episodes: list[dict]) -> None:
    """Rename bare ``Title`` → ``Title P1`` when ``Title P2``+ exists and no ``P1``.

    Mutates episode dicts in place (``name`` only).
    """
    by_base: dict[str, list[dict]] = {}
    for ep in episodes:
        if not isinstance(ep, dict):
            continue
        name = str(ep.get("name") or "")
        if is_composite_episode_title(name):
            continue
        base = episode_base_key(name)
        if not base:
            continue
        by_base.setdefault(base, []).append(ep)

    for _base, group in by_base.items():
        bare: list[dict] = []
        part_nums: set[int] = set()
        for ep in group:
            pn = episode_part_number(str(ep.get("name") or ""))
            if pn is None:
                bare.append(ep)
            else:
                part_nums.add(pn)
        if not bare or 1 in part_nums:
            continue
        if not any(p >= 2 for p in part_nums):
            continue
        bare.sort(
            key=lambda e: (
                int(e.get("_order") or 10**9),
                str(e.get("youtube_id") or ""),
            )
        )
        ep = bare[0]
        name = str(ep.get("name") or "").strip()
        if name and not re.search(r"(?i)\s*P\d+\s*$", name):
            ep["name"] = f"{name} P1"


def episode_range_span(name: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` for an embedded episode-number range, if any."""
    text = str(name or "").strip()
    m = _EPISODE_RANGE_MARK.search(text)
    if not m:
        return None
    try:
        a, b = int(m.group(1)), int(m.group(2))
    except (TypeError, ValueError):
        return None
    if 1 <= a < b <= a + 30:
        return a, b
    return None
