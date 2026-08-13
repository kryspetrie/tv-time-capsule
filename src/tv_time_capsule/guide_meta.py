"""TV Guide title enrichment: NFO → OMDb → Wikipedia/Wikidata + disk cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .fonts import vcr_safe_text
from .log import LOG
from .metadata import resolve_movie_guide_nfo, resolve_show_guide_nfo

_UA = "TV-Time-Capsule/1.0 (guide-meta; https://github.com/local/tv-time-capsule)"
_CACHE_DIR = Path.home() / ".cache" / "tv-time-capsule" / "guide-meta"
_TTL_OK_S = 30 * 24 * 3600
_TTL_MISS_S = 7 * 24 * 3600
_HTTP_TIMEOUT_S = 12.0
# Rough half-screen blurb budget beside a 4:3 thumb (~3–5 wrapped lines).
DEFAULT_MAX_BLURB_CHARS = 280
_MIN_SENTENCE_CHARS = 40

_lock = threading.Lock()
_memory: dict[str, "GuideMeta"] = {}
_inflight: set[str] = set()
_queue: list[tuple[str, str, str | None]] = []  # kind, name, nfo_dir
_worker_started = False
_meta_epoch = 0  # bumped when a fetch finishes so UI can re-merge
_fetch_hook: Callable[..., dict[str, Any]] | None = None  # tests


@dataclass
class GuideMeta:
    blurb: str = ""
    years: str = ""
    network: str = ""
    source: str = ""
    fetched_at: float = 0.0
    ok: bool = False

    def subtitle(self, *, kind: str = "show") -> str:
        parts: list[str] = []
        if self.years:
            parts.append(self.years)
        if self.network:
            parts.append(self.network)
        if parts:
            return " - ".join(parts)
        return "Movie" if kind == "movie" else "Show"


def _norm_name(name: str) -> str:
    return " ".join(str(name or "").strip().split()).casefold()


def _slug(kind: str, name: str) -> str:
    # v2: blurbs store up to two sentences for top-panel scroll.
    raw = f"v2:{kind}:{_norm_name(name)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    safe = re.sub(r"[^a-z0-9]+", "-", _norm_name(name))[:48] or "x"
    return f"{kind}-{safe}-{digest}"


def _cache_path(kind: str, name: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR / f"{_slug(kind, name)}.json"


def _meta_key(kind: str, name: str) -> str:
    return f"{kind}\0{_norm_name(name)}"


def sanitize_guide_text(text: str) -> str:
    """Strip links, markup, and characters the VCR OSD font cannot draw."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"www\.\S+", " ", s)
    s = re.sub(r"\[\[[^|\]]*\|([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'{2,}", "", s)
    s = s.replace("\u00a0", " ")
    s = vcr_safe_text(s)
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if ch in " .,;:!?()'\"%-/&":
            out.append(ch)
        elif 32 <= o < 127:
            out.append(ch)
    cleaned = re.sub(r"\s+", " ", "".join(out)).strip()
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    return cleaned


def split_sentences(text: str) -> list[str]:
    cleaned = sanitize_guide_text(text)
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [p.strip() for p in parts if p.strip()]


def soft_truncate(text: str, max_chars: int) -> str:
    text = sanitize_guide_text(text)
    if len(text) <= max_chars:
        return text
    cut = text[: max(1, max_chars - 1)].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(".,;: ") + "..."


def pick_concise_blurb(
    candidates: list[str],
    *,
    max_chars: int = DEFAULT_MAX_BLURB_CHARS,
) -> str:
    """Prefer the shortest real sentence that fits the panel budget."""
    sentences: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        for sent in split_sentences(raw):
            key = sent.lower()
            if key in seen:
                continue
            seen.add(key)
            sentences.append(sent)
        # Very short standalone descriptions (Wikidata) count too.
        whole = sanitize_guide_text(raw)
        if whole and len(whole) < max_chars and whole.lower() not in seen:
            # Only if it isn't already covered as a sentence.
            if whole not in sentences:
                seen.add(whole.lower())
                sentences.append(whole)

    fitting = [
        s
        for s in sentences
        if _MIN_SENTENCE_CHARS <= len(s) <= max_chars
    ]
    if fitting:
        return min(fitting, key=len)

    short_ok = [s for s in sentences if 20 <= len(s) <= max_chars]
    if short_ok:
        return min(short_ok, key=len)

    if sentences:
        return soft_truncate(min(sentences, key=len), max_chars)
    return ""


def pick_scroll_blurb(
    candidates: list[str],
    *,
    max_sentence_chars: int = DEFAULT_MAX_BLURB_CHARS,
    max_sentences: int = 2,
) -> str:
    """First up-to-*max_sentences* from the best discovered description.

    Prefers a plot whose opening sentence is concise enough for the CRT panel;
    still returns chronological sentence 1 then 2 (soft-truncated if needed).
    """
    fitting: list[list[str]] = []
    fallback: list[str] | None = None
    for raw in candidates:
        sents = split_sentences(raw)
        if not sents:
            continue
        if fallback is None:
            fallback = sents
        if _MIN_SENTENCE_CHARS <= len(sents[0]) <= max_sentence_chars:
            fitting.append(sents)

    chosen = min(fitting, key=lambda s: len(s[0])) if fitting else fallback
    if not chosen:
        return pick_concise_blurb(candidates, max_chars=max_sentence_chars)

    parts: list[str] = []
    for sent in chosen[: max(1, int(max_sentences))]:
        if len(sent) > max_sentence_chars:
            parts.append(soft_truncate(sent, max_sentence_chars))
        else:
            parts.append(sent)
    return " ".join(p for p in parts if p).strip()


def _http_json(url: str, *, timeout: float = _HTTP_TIMEOUT_S) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _years_from_omdb(year_field: str) -> str:
    text = sanitize_guide_text(year_field).replace("–", "-")
    m = re.match(r"^(\d{4})\s*-\s*(\d{4}|)$", text)
    if m:
        a, b = m.group(1), m.group(2)
        return f"{a}-{b}" if b else a
    m = re.search(r"(\d{4})", text)
    return m.group(1) if m else text


def _fetch_omdb(name: str, kind: str, api_key: str) -> dict[str, str]:
    otype = "movie" if kind == "movie" else "series"
    qs = urllib.parse.urlencode(
        {"apikey": api_key, "t": name, "type": otype, "plot": "short"}
    )
    url = f"http://www.omdbapi.com/?{qs}"
    try:
        data = _http_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        LOG.debug("OMDb fetch failed for %s", name, exc_info=True)
        return {}
    if not isinstance(data, dict) or str(data.get("Response")) == "False":
        return {}
    out: dict[str, str] = {}
    plot = data.get("Plot")
    if plot and str(plot).strip() and str(plot).strip().upper() != "N/A":
        out["plot"] = str(plot).strip()
    year = data.get("Year")
    if year and str(year).strip().upper() != "N/A":
        out["years"] = _years_from_omdb(str(year))
    # Free OMDb rarely has network; Country is a weak fallback — skip.
    return out


def _wiki_search_titles(name: str, kind: str) -> list[str]:
    if kind == "movie":
        suffixes = [" (film)", " (movie)", ""]
    else:
        suffixes = [
            " (TV series)",
            " (web series)",
            " (TV program)",
            "",
        ]
    titles: list[str] = []
    for suffix in suffixes:
        query = f"{name}{suffix}".strip()
        qs = urllib.parse.urlencode(
            {
                "action": "opensearch",
                "search": query,
                "limit": "3",
                "namespace": "0",
                "format": "json",
            }
        )
        url = f"https://en.wikipedia.org/w/api.php?{qs}"
        try:
            data = _http_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            for t in data[1]:
                if t and t not in titles:
                    titles.append(str(t))
        if titles:
            break
    return titles


def _wikidata_years_network(qid: str) -> dict[str, str]:
    if not qid or not re.match(r"^Q\d+$", qid):
        return {}
    qs = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "ids": qid,
            "props": "claims|labels",
            "languages": "en",
            "format": "json",
        }
    )
    url = f"https://www.wikidata.org/w/api.php?{qs}"
    try:
        data = _http_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return {}
    entity = ((data or {}).get("entities") or {}).get(qid) or {}
    claims = entity.get("claims") or {}

    def _year_from_claim(prop: str) -> str | None:
        rows = claims.get(prop) or []
        if not rows:
            return None
        try:
            val = rows[0]["mainsnak"]["datavalue"]["value"]["time"]
        except (KeyError, IndexError, TypeError):
            return None
        # +1988-01-01T00:00:00Z
        m = re.search(r"(\d{4})", str(val))
        return m.group(1) if m else None

    start = _year_from_claim("P580") or _year_from_claim("P577")
    end = _year_from_claim("P582")
    out: dict[str, str] = {}
    if start and end and end != start:
        out["years"] = f"{start}-{end}"
    elif start:
        out["years"] = start

    # P449 original network — need label of referenced entity.
    nets = claims.get("P449") or []
    if nets:
        try:
            net_id = nets[0]["mainsnak"]["datavalue"]["value"]["id"]
        except (KeyError, IndexError, TypeError):
            net_id = None
        if net_id:
            qs2 = urllib.parse.urlencode(
                {
                    "action": "wbgetentities",
                    "ids": net_id,
                    "props": "labels",
                    "languages": "en",
                    "format": "json",
                }
            )
            try:
                lab = _http_json(f"https://www.wikidata.org/w/api.php?{qs2}")
                label = (
                    ((lab or {}).get("entities") or {})
                    .get(net_id, {})
                    .get("labels", {})
                    .get("en", {})
                    .get("value")
                )
                if label:
                    out["network"] = sanitize_guide_text(str(label))
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                json.JSONDecodeError,
                OSError,
            ):
                pass
    return out


def _fetch_wikipedia(name: str, kind: str) -> dict[str, str]:
    out: dict[str, str] = {}
    titles = _wiki_search_titles(name, kind)
    for title in titles[:3]:
        enc = urllib.parse.quote(title.replace(" ", "_"), safe="")
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{enc}"
        try:
            data = _http_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("type") == "disambiguation":
            continue
        extract = data.get("extract") or ""
        desc = data.get("description") or ""
        if extract:
            out["plot"] = str(extract)
        if desc:
            out["short"] = str(desc)
        qid = data.get("wikibase_item")
        if qid:
            wd = _wikidata_years_network(str(qid))
            out.update({k: v for k, v in wd.items() if v})
        if out.get("plot") or out.get("short"):
            break
    return out


def _load_disk(kind: str, name: str) -> GuideMeta | None:
    path = _cache_path(kind, name)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    meta = GuideMeta(
        blurb=sanitize_guide_text(str(raw.get("blurb") or "")),
        years=sanitize_guide_text(str(raw.get("years") or "")),
        network=sanitize_guide_text(str(raw.get("network") or "")),
        source=str(raw.get("source") or ""),
        fetched_at=float(raw.get("fetched_at") or 0),
        ok=bool(raw.get("ok")),
    )
    age = time.time() - meta.fetched_at
    ttl = _TTL_OK_S if meta.ok else _TTL_MISS_S
    if age > ttl:
        return None
    return meta


def _save_disk(kind: str, name: str, meta: GuideMeta) -> None:
    path = _cache_path(kind, name)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(meta), indent=0), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        LOG.warning("guide-meta cache write failed path=%s", path, exc_info=True)


def _fields_complete(years: str, network: str, plots: list[str]) -> bool:
    return bool(years and network and plots)


def enrich_title(
    name: str,
    kind: str,
    *,
    nfo_dir: str | None = None,
    omdb_api_key: str | None = None,
    max_blurb_chars: int = DEFAULT_MAX_BLURB_CHARS,
) -> GuideMeta:
    """Run NFO → OMDb → Wikipedia and pick a concise blurb.

    Skips later network sources once blurb candidates, years, and network are
    already filled. Callers must check the disk/memory cache before invoking.
    """
    kind = "movie" if kind == "movie" else "show"
    plots: list[str] = []
    years = ""
    network = ""
    sources: list[str] = []

    if nfo_dir and os.path.isdir(nfo_dir):
        if kind == "movie":
            nfo = resolve_movie_guide_nfo(nfo_dir, name)
        else:
            nfo = resolve_show_guide_nfo(nfo_dir, name)
        if nfo.get("plot"):
            plots.append(nfo["plot"])
            sources.append("nfo")
        if nfo.get("years") and not years:
            years = nfo["years"]
        elif nfo.get("year") and not years:
            years = nfo["year"]
        if nfo.get("network") and not network:
            network = sanitize_guide_text(nfo["network"])

    key = (omdb_api_key or "").strip() or (os.environ.get("OMDB_API_KEY") or "").strip()
    if key and not _fields_complete(years, network, plots):
        if _fetch_hook is not None:
            omdb = _fetch_hook("omdb", name=name, kind=kind, api_key=key)
        else:
            omdb = _fetch_omdb(name, kind, key)
        if omdb.get("plot"):
            plots.append(omdb["plot"])
            sources.append("omdb")
        if omdb.get("years") and not years:
            years = omdb["years"]
        if omdb.get("network") and not network:
            network = sanitize_guide_text(omdb["network"])

    if not _fields_complete(years, network, plots):
        if _fetch_hook is not None:
            wiki = _fetch_hook("wikipedia", name=name, kind=kind)
        else:
            wiki = _fetch_wikipedia(name, kind)
        if wiki.get("plot"):
            plots.append(wiki["plot"])
            sources.append("wikipedia")
        if wiki.get("short"):
            plots.append(wiki["short"])
            if "wikipedia" not in sources:
                sources.append("wikipedia")
        if wiki.get("years") and not years:
            years = wiki["years"]
        if wiki.get("network") and not network:
            network = sanitize_guide_text(wiki["network"])

    blurb = pick_scroll_blurb(plots, max_sentence_chars=max_blurb_chars)
    ok = bool(blurb or years or network)
    return GuideMeta(
        blurb=sanitize_guide_text(blurb),
        years=sanitize_guide_text(years),
        network=sanitize_guide_text(network),
        source="+".join(sources) if sources else "",
        fetched_at=time.time(),
        ok=ok,
    )


def _nfo_dir_for_show(show_data: dict[str, Any] | None) -> str | None:
    if not show_data:
        return None
    for season in (show_data.get("seasons") or {}).values():
        for ep in season.get("episodes") or []:
            path = ep.get("path")
            if not path:
                continue
            p = Path(path)
            for candidate in (p.parent, p.parent.parent, p.parent.parent.parent):
                try:
                    if candidate.is_dir():
                        return str(candidate)
                except OSError:
                    continue
    thumb = show_data.get("thumbnail")
    if thumb:
        parent = Path(str(thumb)).parent
        if parent.is_dir():
            return str(parent)
    return None


def _nfo_dir_for_movie(movie_data: dict[str, Any] | None) -> str | None:
    if not movie_data:
        return None
    path = movie_data.get("path")
    if path:
        parent = Path(str(path)).parent
        if parent.is_dir():
            return str(parent)
    thumb = movie_data.get("thumbnail")
    if thumb:
        parent = Path(str(thumb)).parent
        if parent.is_dir():
            return str(parent)
    return None


def resolve_nfo_dir_for_row(
    row: dict[str, Any],
    *,
    shows: dict[str, Any] | None = None,
    movies: dict[str, Any] | None = None,
) -> str | None:
    kind = row.get("kind") or "show"
    if kind == "movie":
        key = row.get("key")
        return _nfo_dir_for_movie((movies or {}).get(key) if key else None)
    name = row.get("name")
    return _nfo_dir_for_show((shows or {}).get(name) if name else None)


def peek_guide_meta(kind: str, name: str) -> GuideMeta | None:
    key = _meta_key(kind, name)
    with _lock:
        hit = _memory.get(key)
    if hit is not None:
        return hit
    disk = _load_disk(kind, name)
    if disk is not None:
        with _lock:
            _memory[key] = disk
        return disk
    return None


def _ensure_worker(omdb_api_key: str | None) -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True

    def _run() -> None:
        global _meta_epoch
        while True:
            item = None
            with _lock:
                if _queue:
                    item = _queue.pop(0)
            if item is None:
                time.sleep(0.25)
                continue
            kind, name, nfo_dir = item
            key = _meta_key(kind, name)
            try:
                # Any unexpired cache entry (hit or negative) skips the network.
                existing = peek_guide_meta(kind, name)
                if existing is not None:
                    continue
                meta = enrich_title(
                    name,
                    kind,
                    nfo_dir=nfo_dir,
                    omdb_api_key=omdb_api_key,
                )
                _save_disk(kind, name, meta)
                with _lock:
                    _memory[key] = meta
                    _meta_epoch += 1
            except Exception:
                LOG.debug("guide-meta enrich failed name=%s", name, exc_info=True)
                miss = GuideMeta(fetched_at=time.time(), ok=False, source="error")
                _save_disk(kind, name, miss)
                with _lock:
                    _memory[key] = miss
                    _meta_epoch += 1
            finally:
                with _lock:
                    _inflight.discard(key)
            # Be polite to Wikipedia / OMDb.
            time.sleep(0.35)

    threading.Thread(target=_run, daemon=True, name="tv-guide-meta").start()


def request_guide_meta(
    kind: str,
    name: str,
    *,
    nfo_dir: str | None = None,
    omdb_api_key: str | None = None,
    enabled: bool = True,
) -> GuideMeta | None:
    """Return cached meta; enqueue background fetch when missing."""
    if not enabled or not name:
        return None
    kind = "movie" if kind == "movie" else "show"
    hit = peek_guide_meta(kind, name)
    if hit is not None:
        return hit
    key = _meta_key(kind, name)
    _ensure_worker(omdb_api_key)
    with _lock:
        if key not in _inflight:
            _inflight.add(key)
            _queue.append((kind, name, nfo_dir))
    return None


def merge_guide_meta_into_rows(
    rows: list[dict[str, Any]],
    *,
    shows: dict[str, Any] | None = None,
    movies: dict[str, Any] | None = None,
    omdb_api_key: str | None = None,
    enabled: bool = True,
) -> None:
    """Update row blurb/years/network from cache; queue missing titles."""
    if not enabled:
        return
    for row in rows:
        if (row.get("kind") or "") == "section":
            continue
        kind = "movie" if row.get("kind") == "movie" else "show"
        name = str(row.get("name") or "")
        if not name:
            continue
        nfo_dir = row.get("nfo_dir") or resolve_nfo_dir_for_row(
            row, shows=shows, movies=movies
        )
        meta = request_guide_meta(
            kind,
            name,
            nfo_dir=str(nfo_dir) if nfo_dir else None,
            omdb_api_key=omdb_api_key,
            enabled=True,
        )
        if meta is None:
            continue
        if meta.blurb:
            row["blurb"] = vcr_safe_text(meta.blurb)
        if meta.years:
            row["years"] = vcr_safe_text(meta.years)
        if meta.network:
            row["network"] = vcr_safe_text(meta.network)
        row["meta_subtitle"] = vcr_safe_text(meta.subtitle(kind=kind))


def tv_guide_meta_enabled(config: dict[str, Any] | None) -> bool:
    guide = (config or {}).get("tv_guide") or {}
    if not isinstance(guide, dict):
        return True
    return bool(guide.get("meta_enabled", True))


def tv_guide_omdb_key(config: dict[str, Any] | None) -> str | None:
    guide = (config or {}).get("tv_guide") or {}
    if isinstance(guide, dict):
        key = guide.get("omdb_api_key")
        if key is not None and str(key).strip():
            return str(key).strip()
    env = (os.environ.get("OMDB_API_KEY") or "").strip()
    return env or None


def guide_meta_epoch() -> int:
    with _lock:
        return int(_meta_epoch)


def reset_guide_meta_state_for_tests() -> None:
    """Clear in-memory queue/cache (unit tests only)."""
    global _worker_started, _fetch_hook, _meta_epoch
    with _lock:
        _memory.clear()
        _inflight.clear()
        _queue.clear()
        _worker_started = False
        _meta_epoch = 0
    _fetch_hook = None


def set_guide_meta_fetch_hook_for_tests(
    hook: Callable[..., dict[str, Any]] | None,
) -> None:
    global _fetch_hook
    _fetch_hook = hook
