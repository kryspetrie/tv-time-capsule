"""Forever offline YouTube file cache (yt-dlp).

Distinct from :mod:`playback_cache` (remote NFS/SMB copy) and the short-lived
catalog/crop caches under ``youtube/``. Default layout matches the local media
library::

    {cache_dir}/{Show}/s{NN}/S{SS}E{EE} - {Title} [{youtube_id}].mp4

With ``layout: flat``::

    {cache_dir}/{Show}/S{SS}E{EE} - {Title} [{youtube_id}].mp4

A root ``.manifest.json`` maps video ids to relative paths. Completed files are
never deleted when ``max_bytes`` is null (forever cache).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal

from .config import DEFAULT_MEDIA_ROOT, STATE_DIR
from .youtube_catalog import youtube_id_from_episode

LOG = logging.getLogger(__name__)

MANIFEST_NAME = ".manifest.json"
MANIFEST_VERSION = 1
# Prefer SD (~480p) for the 640×480 UI — smaller downloads, no wasted HD.
DEFAULT_FORMAT = (
    "bv*[height<=480]+ba/b[height<=480]/"
    "bv*[height<=360]+ba/b[height<=360]/"
    "bv*[height<=720]+ba/b[height<=720]/b"
)
DEFAULT_IDLE_SECONDS = 30
PART_SUFFIX = ".part"

# Permanent yt-dlp failures — skip retries and show UNAVAILABLE in the UI.
# Do NOT include vague "This video is not available" — that often means the
# default android/VR client failed while web/tv (and live Chrome) still work.
_UNAVAILABLE_MARKERS = (
    "private video",
    "has been removed",
    "video has been removed",
    "account associated with this video has been terminated",
    "violating youtube's community guidelines",
    "who has blocked it on copyright grounds",
    "live stream recording is not available",
    "this live event",
    "members-only content",
)

# Account / IP blocks — pause background fills (and stop retry storms).
_RATE_LIMIT_MARKERS = (
    "sign in to confirm you're not a bot",
    "confirm you're not a bot",
    "not a bot",
    "http error 429",
    "too many requests",
    "rate-limited",
    "rate limited",
    "has blocked you from",
    "cookies-from-browser",
)

DEFAULT_IDLE_GAP_SECONDS = 60
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 1800  # 30 minutes
MAX_RATE_LIMIT_COOLDOWN_SECONDS = 6 * 3600  # 6 hours cap when escalating

# Prefer browser-like clients first; default android VR often false-negatives.
_PLAYER_CLIENT_STRATEGIES: tuple[str, ...] = (
    "web,tv,android,ios",
    "web,tv",
    "tv,web",
    "android,ios,web",
)

PlaybackBackend = Literal["file", "live", "blocked"]

_UNSAFE_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")


class YoutubeDlMissingError(RuntimeError):
    """Raised when youtube.cache is enabled but yt-dlp is not installed."""


def require_yt_dlp():
    """Import yt_dlp or raise a clear operator-facing error."""
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise YoutubeDlMissingError(
            "youtube.cache.enabled requires yt-dlp. "
            "Install with: poetry add yt-dlp  (or pip install yt-dlp)"
        ) from exc
    return yt_dlp


def _detect_js_runtimes() -> dict[str, Any]:
    """Return yt-dlp ``js_runtimes`` when node/deno is on PATH."""
    runtimes: dict[str, Any] = {}
    for name in ("node", "deno"):
        path = shutil.which(name)
        if path:
            runtimes[name] = {"path": path}
    return runtimes


def sanitize_cache_filename(name: str, *, max_len: int = 120) -> str:
    """Strip path separators and unsafe characters for episode filenames."""
    text = str(name or "").replace("\n", " ").replace("\r", " ")
    text = _UNSAFE_FS.sub("", text)
    text = text.replace(":", "")  # belt-and-suspenders for Windows/NAS
    text = _WS.sub(" ", text).strip(" .")
    if not text:
        text = "episode"
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")
    return text or "episode"


def sanitize_show_dirname(name: str, *, max_len: int = 80) -> str:
    """Sanitize a show folder name under the cache root."""
    return sanitize_cache_filename(name, max_len=max_len)


def season_dirname(season: int) -> str:
    """Return library-style ``s{NN}`` season folder (matches media discovery)."""
    try:
        num = int(season)
    except (TypeError, ValueError):
        num = 0
    return f"s{num:02d}"


def episode_filename(
    title: str,
    youtube_id: str,
    *,
    season: int = 1,
    episode: int = 1,
) -> str:
    """``S{SS}E{EE} - {Title} [{youtube_id}].mp4`` (library-parsable)."""
    try:
        s_num = int(season)
    except (TypeError, ValueError):
        s_num = 0
    try:
        e_num = int(episode)
    except (TypeError, ValueError):
        e_num = 1
    if e_num < 1:
        e_num = 1
    yid = str(youtube_id or "").strip()
    base = sanitize_cache_filename(title)
    code = f"S{s_num:02d}E{e_num:02d}"
    if yid:
        return f"{code} - {base} [{yid}].mp4"
    return f"{code} - {base}.mp4"


def relative_episode_path(
    show: str,
    season: int,
    title: str,
    youtube_id: str,
    *,
    episode: int = 1,
    layout: str = "season_folders",
) -> str:
    """Build the relative path under the cache directory.

    ``layout``:
      - ``season_folders`` — ``Show/s01/S01E01 - Title [id].mp4`` (default)
      - ``flat`` — ``Show/S01E01 - Title [id].mp4``
    """
    show_dir = sanitize_show_dirname(show)
    name = episode_filename(
        title, youtube_id, season=season, episode=episode
    )
    layout_key = (layout or "season_folders").strip().lower()
    if layout_key == "flat":
        return f"{show_dir}/{name}"
    return f"{show_dir}/{season_dirname(season)}/{name}"


def _dir_is_writable(path: Path) -> bool:
    """True when ``path`` exists (or can be created) and accepts writes."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".tvtc-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def state_fallback_cache_dir() -> Path:
    """Writable fallback when no media path can host the offline tree."""
    return Path(STATE_DIR) / "youtube-offline"


def default_cache_dir(media_paths: list[str] | None = None) -> Path:
    """Prefer the first writable ``media_paths`` entry; else state dir fallback."""
    tried: list[str] = []
    for path in media_paths or []:
        text = str(path or "").strip()
        if not text:
            continue
        candidate = Path(os.path.expanduser(text))
        tried.append(str(candidate))
        if _dir_is_writable(candidate):
            return candidate.resolve()
    fallback = state_fallback_cache_dir()
    if not _dir_is_writable(fallback):
        LOG.warning(
            "YouTube offline cache fallback is not writable (%s); downloads will fail",
            fallback,
        )
        return fallback.resolve()
    if tried:
        LOG.warning(
            "YouTube offline cache: media path(s) unavailable %s — using %s",
            tried,
            fallback,
        )
    else:
        # No media_paths configured; still avoid a non-existent DEFAULT_MEDIA_ROOT.
        default_media = Path(os.path.expanduser(DEFAULT_MEDIA_ROOT))
        if _dir_is_writable(default_media):
            return default_media.resolve()
        LOG.warning(
            "YouTube offline cache: %s unavailable — using %s",
            default_media,
            fallback,
        )
    return fallback.resolve()


def resolve_cache_dir(
    cache_cfg: dict[str, Any] | None,
    *,
    media_paths: list[str] | None = None,
) -> Path:
    raw = (cache_cfg or {}).get("directory")
    if raw:
        explicit = Path(os.path.expanduser(str(raw)))
        if _dir_is_writable(explicit):
            return explicit.resolve()
        LOG.warning(
            "YouTube offline cache.directory %s is not writable — falling back",
            explicit,
        )
    return default_cache_dir(media_paths)


def is_idle_for_youtube_cache(
    view: int,
    *,
    screensaver_active: bool = False,
    playing: int = 5,
    weather: int = 13,
    retro_tv: int = 14,
) -> bool:
    """True when the current view allows background downloads.

    Browse/menus/config/screensaver are allowed. Actively watching
    PLAYING, Weather, or Retro TV is not. The app also requires
    ``idle_seconds`` without UI input (or an active screensaver) before
    starting background fills; priority cache-now bypasses that wait.
    """
    if screensaver_active:
        return True
    return view not in (playing, weather, retro_tv)


def resolve_playback_backend(
    playback_mode: str,
    *,
    file_present: bool,
) -> PlaybackBackend:
    """Map ``playback_mode`` + cache hit to file / live / blocked."""
    mode = (playback_mode or "prefer_cache").strip().lower()
    if mode == "live":
        return "live"
    if file_present:
        return "file"
    if mode == "cached_only":
        return "blocked"
    # prefer_cache (default) and unknown → live Chrome on cache miss
    return "live"


class YoutubeOfflineCache:
    """Disk layout + idle yt-dlp worker for configured channels.

    Adapter for :class:`tv_time_capsule.playback.ports.EpisodeOfflineCache`.
    Default config enables fills and ``prefer_cache`` playback (live Chrome on miss).
    """

    def __init__(self, config: dict[str, Any]):
        yt = config.get("youtube") or {}
        if not isinstance(yt, dict):
            yt = {}
        cache_cfg = yt.get("cache") or {}
        if not isinstance(cache_cfg, dict):
            cache_cfg = {}

        self.playback_mode = str(yt.get("playback_mode") or "prefer_cache").strip().lower()
        if self.playback_mode not in ("live", "prefer_cache", "cached_only"):
            self.playback_mode = "prefer_cache"

        self.enabled = bool(cache_cfg.get("enabled", True))
        self.download_when_idle = bool(cache_cfg.get("download_when_idle", True))
        try:
            self.idle_seconds = max(5, int(cache_cfg.get("idle_seconds", DEFAULT_IDLE_SECONDS)))
        except (TypeError, ValueError):
            self.idle_seconds = DEFAULT_IDLE_SECONDS
        self.format = str(cache_cfg.get("format") or DEFAULT_FORMAT)
        layout = str(cache_cfg.get("layout") or "season_folders").strip().lower()
        if layout not in ("season_folders", "flat"):
            layout = "season_folders"
        self.layout = layout
        try:
            self.batch_size = max(1, min(8, int(cache_cfg.get("batch_size", 1))))
        except (TypeError, ValueError):
            self.batch_size = 1
        try:
            self.idle_gap_seconds = max(
                5, int(cache_cfg.get("idle_gap_seconds", DEFAULT_IDLE_GAP_SECONDS))
            )
        except (TypeError, ValueError):
            self.idle_gap_seconds = DEFAULT_IDLE_GAP_SECONDS
        try:
            self.rate_limit_cooldown_seconds = max(
                60,
                int(
                    cache_cfg.get(
                        "rate_limit_cooldown_seconds",
                        DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
                    )
                ),
            )
        except (TypeError, ValueError):
            self.rate_limit_cooldown_seconds = DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        self.exclude_unavailable = bool(
            cache_cfg.get(
                "exclude_unavailable",
                cache_cfg.get("excludeUnavailable", False),
            )
        )
        raw_max = cache_cfg.get("max_bytes", None)
        if raw_max is None:
            self.max_bytes: int | None = None
        else:
            try:
                self.max_bytes = max(0, int(raw_max))
            except (TypeError, ValueError):
                self.max_bytes = None

        media_paths = config.get("media_paths") or []
        if not isinstance(media_paths, list):
            media_paths = []
        self.cache_dir = resolve_cache_dir(
            cache_cfg, media_paths=[str(p) for p in media_paths]
        )
        self._manifest_path = self.cache_dir / MANIFEST_NAME
        self._lock = threading.RLock()
        self._manifest: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "videos": {},
            "skipped": {},
        }
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # start paused until idle
        self._want_idle = False
        # Hard stop for idle + priority (Retro TV / Weather owning the pipe).
        self._suspended = False
        # Ordered priority jobs (one per show). Each job has a FIFO ``boost``
        # lane (explicit cache-now picks) then ``rest`` (remaining show/season fill).
        self._priority_jobs: list[dict[str, Any]] = []
        self._priority_ids: set[str] = set()
        self._priority_inflight: list[tuple[str, int, int, str, str]] = []
        self._prio_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._active_download: str | None = None
        # yid -> download percent 0–100, or None while queued/unknown
        self._active_progress: dict[str, float | None] = {}
        self._shows_provider: Callable[[], dict[str, dict[str, Any]]] | None = None
        self._last_error: str | None = None
        self._rate_limited_until = 0.0
        self._rate_limit_strikes = 0
        self._rate_limit_logged_until = 0.0

        if self.enabled:
            self._ensure_dir()
            self._load_manifest()

    def _ensure_dir(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Media root may be unmounted until later (USB / NAS).
            LOG.warning(
                "YouTube offline cache directory unavailable (%s): %s",
                self.cache_dir,
                exc,
            )

    def _load_manifest(self) -> None:
        if not self._manifest_path.is_file():
            self._manifest = {
                "version": MANIFEST_VERSION,
                "videos": {},
                "skipped": {},
            }
            return
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("YouTube offline manifest read failed: %s", exc)
            self._manifest = {
                "version": MANIFEST_VERSION,
                "videos": {},
                "skipped": {},
            }
            return
        videos = data.get("videos") if isinstance(data, dict) else None
        if not isinstance(videos, dict):
            videos = {}
        skipped = data.get("skipped") if isinstance(data, dict) else None
        if not isinstance(skipped, dict):
            skipped = {}
        self._manifest = {
            "version": MANIFEST_VERSION,
            "videos": dict(videos),
            "skipped": dict(skipped),
        }
        if self._scrub_false_unavailable_skips():
            try:
                self._write_manifest()
            except OSError as exc:
                LOG.debug("Could not rewrite scrubbed offline manifest: %s", exc)

    def _scrub_false_unavailable_skips(self) -> bool:
        """Drop skipped ids that were false 'not available' from the wrong client."""
        skipped = self._manifest.get("skipped") or {}
        if not isinstance(skipped, dict) or not skipped:
            return False
        drop: list[str] = []
        for yid, entry in skipped.items():
            err = ""
            if isinstance(entry, dict):
                err = str(entry.get("error") or entry.get("reason") or "")
            else:
                err = str(entry)
            low = err.lower()
            # Old false-positive wording from android VR / default client.
            if "not available" in low or "video unavailable" in low:
                if not self._error_is_unavailable(err):
                    drop.append(str(yid))
        for yid in drop:
            skipped.pop(yid, None)
        if drop:
            LOG.info(
                "Cleared %d false YouTube offline UNAVAILABLE skip(s); will retry",
                len(drop),
            )
            self._manifest["skipped"] = skipped
            return True
        return False

    def _write_manifest(self) -> None:
        self._ensure_dir()
        tmp = self._manifest_path.with_suffix(".json.tmp")
        payload = json.dumps(self._manifest, indent=2, sort_keys=True) + "\n"
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._manifest_path)

    def reload_manifest(self) -> None:
        with self._lock:
            self._load_manifest()

    def upsert_manifest(
        self,
        youtube_id: str,
        relpath: str,
        *,
        show: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        title: str | None = None,
    ) -> None:
        yid = str(youtube_id or "").strip()
        if not yid:
            return
        entry: dict[str, Any] = {"relpath": relpath.replace("\\", "/")}
        if show is not None:
            entry["show"] = show
        if season is not None:
            entry["season"] = int(season)
        if episode is not None:
            entry["episode"] = int(episode)
        if title is not None:
            entry["title"] = title
        with self._lock:
            videos = self._manifest.setdefault("videos", {})
            videos[yid] = entry
            self._write_manifest()

    def mark_unavailable(self, youtube_id: str, *, error: str = "") -> None:
        """Record a permanent-looking failure so idle fills skip this id.

        Manual priority cache (Y) can clear the skip and retry.
        """
        yid = str(youtube_id or "").strip()
        if not yid:
            return
        with self._lock:
            skipped = self._manifest.setdefault("skipped", {})
            skipped[yid] = {
                "reason": "unavailable",
                "error": (error or "")[:400],
                "at": int(time.time()),
            }
            # Drop any stale success entry without a file.
            videos = self._manifest.get("videos") or {}
            if yid in videos and not self.cached_path(yid):
                videos.pop(yid, None)
            self._write_manifest()
        LOG.warning("YouTube offline marked unavailable id=%s: %s", yid, error)

    def clear_unavailable(self, youtube_id: str | None) -> bool:
        """Remove a permanent skip so a manual retry can download again."""
        yid = str(youtube_id or "").strip()
        if not yid:
            return False
        with self._lock:
            skipped = self._manifest.get("skipped") or {}
            if not isinstance(skipped, dict) or yid not in skipped:
                return False
            skipped.pop(yid, None)
            self._manifest["skipped"] = skipped
            self._write_manifest()
        LOG.info("YouTube offline cleared UNAVAILABLE skip id=%s (manual retry)", yid)
        return True

    def is_unavailable(self, youtube_id: str | None) -> bool:
        yid = str(youtube_id or "").strip()
        if not yid:
            return False
        with self._lock:
            skipped = self._manifest.get("skipped") or {}
            return yid in skipped

    def episode_is_excluded(self, episode: dict | None) -> bool:
        """True when ``exclude_unavailable`` hides this episode from the library."""
        if not self.enabled or not self.exclude_unavailable:
            return False
        if not isinstance(episode, dict):
            return False
        yid = youtube_id_from_episode(episode)
        return bool(yid and self.is_unavailable(yid))

    def filter_episodes(self, episodes: list | None) -> list:
        """Drop unavailable episodes when ``exclude_unavailable`` is enabled."""
        eps = list(episodes or [])
        if not self.enabled or not self.exclude_unavailable:
            return eps
        return [ep for ep in eps if not self.episode_is_excluded(ep)]

    @staticmethod
    def _normalize_error_text(message: str) -> str:
        """Lowercase and flatten curly quotes so marker matching is reliable."""
        text = (message or "").lower()
        return (
            text.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
        )

    @staticmethod
    def _error_is_unavailable(message: str) -> bool:
        text = YoutubeOfflineCache._normalize_error_text(message)
        return any(marker in text for marker in _UNAVAILABLE_MARKERS)

    @staticmethod
    def _error_is_rate_limit(message: str) -> bool:
        text = YoutubeOfflineCache._normalize_error_text(message)
        return any(marker in text for marker in _RATE_LIMIT_MARKERS)

    def is_rate_limited(self) -> bool:
        return time.time() < float(self._rate_limited_until or 0.0)

    def rate_limit_remaining_seconds(self) -> int:
        left = float(self._rate_limited_until or 0.0) - time.time()
        return max(0, int(left))

    def trip_rate_limit(self, error: str = "") -> None:
        """Pause all cache downloads after a bot / 429 style block.

        Escalates cooldown on repeated trips while already limited. Idle and
        priority jobs wait until the cooldown expires (no further requests).
        """
        now = time.time()
        base = int(self.rate_limit_cooldown_seconds)
        if self.is_rate_limited():
            self._rate_limit_strikes = min(8, int(self._rate_limit_strikes) + 1)
        else:
            self._rate_limit_strikes = 1
        cooldown = min(
            MAX_RATE_LIMIT_COOLDOWN_SECONDS,
            base * (2 ** max(0, self._rate_limit_strikes - 1)),
        )
        until = now + cooldown
        # Only extend; never shorten an active cooldown.
        self._rate_limited_until = max(float(self._rate_limited_until or 0.0), until)
        self._last_error = (error or "")[:400] or self._last_error
        if now >= float(self._rate_limit_logged_until or 0.0):
            LOG.warning(
                "YouTube offline rate-limited — pausing ALL cache downloads for %ds "
                "(strike=%d). Queued priority jobs resume after cooldown. %s",
                int(self._rate_limited_until - now),
                self._rate_limit_strikes,
                (error or "")[:200],
            )
            # Avoid spamming the same warning every failed id.
            self._rate_limit_logged_until = now + min(300, cooldown)

    def clear_rate_limit(self) -> None:
        if self._rate_limited_until or self._rate_limit_strikes:
            LOG.info("YouTube offline rate-limit cleared after successful download")
        self._rate_limited_until = 0.0
        self._rate_limit_strikes = 0
        self._rate_limit_logged_until = 0.0

    def cached_path(self, youtube_id: str | None) -> Path | None:
        """Absolute path of a completed cache file, or None."""
        yid = str(youtube_id or "").strip()
        if not yid or not self.enabled:
            return None
        with self._lock:
            entry = (self._manifest.get("videos") or {}).get(yid)
            rel = None
            if isinstance(entry, dict):
                rel = entry.get("relpath")
            elif isinstance(entry, str):
                rel = entry
        if not rel:
            # Fall back to scanning known layout via glob is expensive; try
            # common discover by walking once is avoided — rely on manifest.
            return None
        path = (self.cache_dir / str(rel)).resolve()
        try:
            path.relative_to(self.cache_dir.resolve())
        except ValueError:
            return None
        if path.is_file() and path.suffix.lower() in (".mp4", ".mkv", ".webm", ".m4a"):
            # Ignore incomplete .part siblings
            if path.name.endswith(PART_SUFFIX):
                return None
            return path
        return None

    def is_cached(self, youtube_id: str | None) -> bool:
        return self.cached_path(youtube_id) is not None

    def backend_for_episode(self, episode: dict | None) -> PlaybackBackend:
        yid = youtube_id_from_episode(episode) if episode else None
        hit = self.is_cached(yid) if self.enabled else False
        return resolve_playback_backend(self.playback_mode, file_present=hit)

    def can_start_episode(self, episode: dict | None) -> bool:
        return self.backend_for_episode(episode) != "blocked"

    def cache_marker_for_episode(self, episode: dict | None) -> str | None:
        """Episode-row status: CACHED / CACHING… / UNAVAILABLE / NOT CACHED."""
        if not self.enabled:
            return None
        yid = youtube_id_from_episode(episode) if episode else None
        if not yid:
            return None
        if self.is_cached(yid):
            return "CACHED"
        if self.is_unavailable(yid):
            return "UNAVAILABLE"
        if self.is_priority_or_active(yid):
            pct = self.download_progress_percent(yid)
            if pct is not None:
                return f"CACHING {pct}%"
            return "CACHING..."
        return "NOT CACHED"

    def download_progress_percent(self, youtube_id: str | None) -> int | None:
        """In-flight download percent 0–100, or None if unknown / not active."""
        yid = str(youtube_id or "").strip()
        if not yid:
            return None
        with self._lock:
            if yid not in self._active_progress:
                return None
            raw = self._active_progress.get(yid)
        if raw is None:
            return None
        return int(max(0, min(100, round(raw))))

    def is_priority_or_active(self, youtube_id: str | None) -> bool:
        if not youtube_id:
            return False
        with self._prio_lock:
            if youtube_id in self._priority_ids:
                return True
        with self._lock:
            return youtube_id in self._active_progress

    def absolute_path_for(
        self,
        show: str,
        season: int,
        title: str,
        youtube_id: str,
        *,
        episode: int = 1,
    ) -> Path:
        rel = relative_episode_path(
            show,
            season,
            title,
            youtube_id,
            episode=episode,
            layout=self.layout,
        )
        return self.cache_dir / rel

    def _usage_bytes(self) -> int:
        total = 0
        if not self.cache_dir.is_dir():
            return 0
        for root, _dirs, files in os.walk(self.cache_dir):
            for name in files:
                if name.endswith(PART_SUFFIX) or name.startswith("."):
                    continue
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
        return total

    def _under_byte_budget(self, extra: int = 0) -> bool:
        if self.max_bytes is None:
            return True
        return self._usage_bytes() + max(0, extra) <= self.max_bytes

    def download_video(
        self,
        youtube_id: str,
        *,
        show: str,
        season: int,
        title: str,
        episode: int = 1,
        cancel_event: threading.Event | None = None,
    ) -> Path | None:
        """Download one video via yt-dlp. Returns final path or None.

        Writes to ``{dest}.part.%(ext)s``, then atomically renames to ``dest``
        and updates the manifest only after a successful rename.
        """
        yid = str(youtube_id or "").strip()
        if not yid:
            return None
        existing = self.cached_path(yid)
        if existing is not None:
            return existing
        if self.is_rate_limited():
            return None
        if not self._under_byte_budget():
            LOG.warning("YouTube offline cache at max_bytes; skipping %s", yid)
            return None

        yt_dlp = require_yt_dlp()
        dest = self.absolute_path_for(
            show, season, title, yid, episode=episode
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._cleanup_partials(dest)

        # Intermediate: ``Title [id].mp4.part.mp4`` (merge_output_format).
        part_tmpl = str(dest) + PART_SUFFIX + ".%(ext)s"
        url = f"https://www.youtube.com/watch?v={yid}"
        cancel = cancel_event or self._cancel

        def _hook(d: dict[str, Any]) -> None:
            if cancel.is_set() or self._pause.is_set() or self._suspended:
                raise yt_dlp.utils.DownloadCancelled("idle cancelled")
            # Yield in-flight idle downloads when a priority queue is active.
            # Also yield non-boost priority downloads when boosts are waiting
            # (e.g. Show A rest was downloading; user bumped Episode 5).
            with self._prio_lock:
                priority_ids = set(self._priority_ids)
                boost_ids = self._boost_ids_locked()
            if priority_ids and yid not in priority_ids:
                raise yt_dlp.utils.DownloadCancelled("yielded to priority cache")
            if boost_ids and yid not in boost_ids:
                raise yt_dlp.utils.DownloadCancelled("yielded to priority boost")
            status = str(d.get("status") or "")
            if status == "downloading":
                pct: float | None = None
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                done = d.get("downloaded_bytes")
                try:
                    if total and done is not None and float(total) > 0:
                        pct = 100.0 * float(done) / float(total)
                except (TypeError, ValueError):
                    pct = None
                if pct is None:
                    raw = str(d.get("_percent_str") or "").strip().rstrip("%")
                    try:
                        pct = float(raw) if raw else None
                    except ValueError:
                        pct = None
                with self._lock:
                    self._active_progress[yid] = pct
                    self._active_download = yid
            elif status == "finished":
                with self._lock:
                    self._active_progress[yid] = 100.0
                    self._active_download = yid

        js_runtimes = _detect_js_runtimes()
        last_error = ""
        download_ok = False

        with self._lock:
            self._active_download = yid
            self._active_progress[yid] = None
        try:
            for clients in _PLAYER_CLIENT_STRATEGIES:
                if cancel.is_set() or self._pause.is_set() or self._suspended:
                    break
                self._cleanup_partials(dest)
                ydl_opts: dict[str, Any] = {
                    "format": self.format,
                    "outtmpl": part_tmpl,
                    "merge_output_format": "mp4",
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                    "retries": 3,
                    "fragment_retries": 3,
                    "concurrent_fragment_downloads": 1,
                    "progress_hooks": [_hook],
                    "extractor_args": {
                        "youtube": {"player_client": clients.split(",")}
                    },
                }
                if js_runtimes:
                    ydl_opts["js_runtimes"] = js_runtimes
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    download_ok = True
                    break
                except Exception as exc:
                    # Honour cancel / pause / priority yield without retrying clients.
                    if isinstance(exc, yt_dlp.utils.DownloadCancelled):
                        last_error = str(exc)
                        break
                    last_error = str(exc)
                    if self._error_is_rate_limit(last_error):
                        LOG.info(
                            "YouTube offline rate-limit hit id=%s client=%s",
                            yid,
                            clients,
                        )
                        break
                    if self._error_is_unavailable(last_error):
                        LOG.info(
                            "YouTube offline unavailable id=%s: %s",
                            yid,
                            last_error,
                        )
                        break
                    LOG.info(
                        "YouTube offline client=%s failed id=%s: %s",
                        clients,
                        yid,
                        exc,
                    )
                    continue

            if not download_ok:
                self._last_error = last_error
                if last_error and self._error_is_rate_limit(last_error):
                    self.trip_rate_limit(last_error)
                elif last_error and self._error_is_unavailable(last_error):
                    self.mark_unavailable(yid, error=last_error)
                elif last_error:
                    LOG.info(
                        "YouTube offline download stopped id=%s: %s",
                        yid,
                        last_error,
                    )
                self._cleanup_partials(dest)
                return None
        finally:
            with self._lock:
                self._active_progress.pop(yid, None)
                if self._active_download == yid:
                    self._active_download = (
                        next(iter(self._active_progress), None)
                        if self._active_progress
                        else None
                    )

        # Successful yt-dlp return: keep the file even if idle ended mid-finalize.
        self.clear_rate_limit()
        produced = self._find_produced_file(dest)
        if produced is None:
            LOG.warning("YouTube offline download produced no file id=%s", yid)
            self._cleanup_partials(dest)
            return None

        try:
            if dest.exists() and dest.resolve() != produced.resolve():
                dest.unlink()
            if produced.resolve() != dest.resolve():
                produced.replace(dest)
        except OSError as exc:
            LOG.warning("YouTube offline rename failed: %s", exc)
            self._cleanup_partials(dest)
            return None

        if not dest.is_file():
            self._cleanup_partials(dest)
            return None

        rel = str(dest.relative_to(self.cache_dir)).replace("\\", "/")
        self.upsert_manifest(
            yid,
            rel,
            show=show,
            season=season,
            title=title,
            episode=episode,
        )
        LOG.info("YouTube offline cached id=%s path=%s", yid, dest)
        return dest

    def _iter_related_files(self, dest: Path) -> list[Path]:
        """List files related to ``dest`` without glob (ids contain ``[]``)."""
        parent = dest.parent
        if not parent.is_dir():
            return []
        prefix = dest.name + PART_SUFFIX  # e.g. title [id].mp4.part
        stem_prefix = dest.stem  # title [id]
        out: list[Path] = []
        try:
            for path in parent.iterdir():
                if not path.is_file():
                    continue
                name = path.name
                if name == dest.name or name.startswith(prefix):
                    out.append(path)
                    continue
                if PART_SUFFIX in name and stem_prefix in name:
                    out.append(path)
                    continue
                # Fallback: same youtube id bracket tag
                tag = f"[{dest.stem.rsplit('[', 1)[-1]}" if "[" in dest.stem else ""
                if tag and tag in name and name.endswith((".mp4", ".mkv", ".webm", ".m4a", ".ytdl")):
                    out.append(path)
        except OSError:
            return []
        return out

    def _find_produced_file(self, dest: Path) -> Path | None:
        """Locate yt-dlp output for ``dest`` (``.part.*`` intermediates)."""
        if dest.is_file():
            return dest
        prefix = dest.name + PART_SUFFIX
        candidates: list[Path] = []
        for path in self._iter_related_files(dest):
            if path == dest:
                return path
            if path.name.startswith(prefix) and path.suffix.lower() != ".ytdl":
                candidates.append(path)
        if not candidates:
            # Exact known name: dest.mp4.part.mp4
            alt = Path(str(dest) + PART_SUFFIX + ".mp4")
            if alt.is_file():
                return alt
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    def _cleanup_partials(self, dest: Path) -> None:
        for path in self._iter_related_files(dest):
            if path == dest and path.is_file():
                # Never delete a completed final file from cleanup.
                continue
            name = path.name
            if PART_SUFFIX not in name and not name.endswith(".ytdl"):
                continue
            try:
                path.unlink()
            except OSError:
                pass

    def show_cache_progress(
        self, show: dict[str, Any] | None
    ) -> tuple[int, int, int | None]:
        """Return ``(cached, total, percent)`` for a YouTube show.

        ``percent`` is 0–100, or ``None`` when there are no episodes yet.
        """
        if not isinstance(show, dict) or show.get("source") != "youtube":
            return 0, 0, None
        total = 0
        cached = 0
        for season_data in (show.get("seasons") or {}).values():
            if not isinstance(season_data, dict):
                continue
            for ep in season_data.get("episodes") or []:
                if not isinstance(ep, dict):
                    continue
                yid = youtube_id_from_episode(ep)
                if not yid:
                    continue
                if self.is_unavailable(yid):
                    continue
                total += 1
                if self.is_cached(yid):
                    cached += 1
        if total <= 0:
            return 0, 0, None
        return cached, total, int(round(100.0 * cached / total))

    def iter_missing_episodes(
        self,
        shows: dict[str, dict[str, Any]],
        *,
        include_unavailable: bool = False,
    ) -> list[tuple[str, int, int, str, str]]:
        """Return missing episodes ordered by show name descending.

        Within each show: seasons descending, then episode numbers descending
        (newest-looking catalog numbers first).

        Idle fills leave ``include_unavailable`` false. Manual Y retries pass
        true so previously skipped ids can be re-queued.
        """
        by_show: dict[str, list[tuple[int, int, str, str]]] = {}
        for show_name, show in (shows or {}).items():
            if not isinstance(show, dict) or show.get("source") != "youtube":
                continue
            seasons = show.get("seasons") or {}
            bucket: list[tuple[int, int, str, str]] = []
            for season_key, season_data in seasons.items():
                try:
                    season_num = int(season_key)
                except (TypeError, ValueError):
                    continue
                if not isinstance(season_data, dict):
                    continue
                for ep in season_data.get("episodes") or []:
                    if not isinstance(ep, dict):
                        continue
                    yid = youtube_id_from_episode(ep)
                    if not yid:
                        continue
                    if self.is_cached(yid):
                        continue
                    if self.is_unavailable(yid) and not include_unavailable:
                        continue
                    title = str(ep.get("name") or yid)
                    try:
                        ep_num = int(ep.get("number") or 1)
                    except (TypeError, ValueError):
                        ep_num = 1
                    if ep_num < 1:
                        ep_num = 1
                    bucket.append((season_num, ep_num, title, yid))
            if bucket:
                # Season desc, episode desc within the show.
                bucket.sort(key=lambda t: (t[0], t[1]), reverse=True)
                by_show[str(show_name)] = bucket

        missing: list[tuple[str, int, int, str, str]] = []
        # Shows Z→A so later alphabet titles fill first.
        for show_name in sorted(by_show.keys(), reverse=True):
            for season_num, ep_num, title, yid in by_show[show_name]:
                missing.append((show_name, season_num, ep_num, title, yid))
        return missing

    def missing_items_for_show(
        self,
        show_name: str,
        show: dict[str, Any] | None,
        *,
        retry_unavailable: bool = False,
    ) -> list[tuple[str, int, int, str, str]]:
        """Missing episodes for one show (season/episode ascending for watch order)."""
        if not isinstance(show, dict) or show.get("source") != "youtube":
            return []
        items = self.iter_missing_episodes(
            {str(show_name): show},
            include_unavailable=retry_unavailable,
        )
        # Priority fills play/watch order: earliest season/episode first.
        items.sort(key=lambda t: (t[1], t[2]))
        return items

    def missing_items_for_season(
        self,
        show_name: str,
        season_num: int,
        show: dict[str, Any] | None,
        *,
        retry_unavailable: bool = False,
    ) -> list[tuple[str, int, int, str, str]]:
        if not isinstance(show, dict) or show.get("source") != "youtube":
            return []
        seasons = show.get("seasons") or {}
        season_data = seasons.get(season_num)
        if season_data is None:
            season_data = seasons.get(str(season_num))
        if not isinstance(season_data, dict):
            return []
        slim = {
            str(show_name): {
                "source": "youtube",
                "seasons": {int(season_num): season_data},
            }
        }
        items = self.iter_missing_episodes(
            slim, include_unavailable=retry_unavailable
        )
        items.sort(key=lambda t: (t[1], t[2]))
        return items

    def missing_items_for_episode(
        self,
        show_name: str,
        season_num: int,
        episode: dict[str, Any] | None,
        *,
        retry_unavailable: bool = False,
    ) -> list[tuple[str, int, int, str, str]]:
        if not isinstance(episode, dict):
            return []
        yid = youtube_id_from_episode(episode)
        if not yid or self.is_cached(yid):
            return []
        if self.is_unavailable(yid) and not retry_unavailable:
            return []
        title = str(episode.get("name") or yid)
        try:
            ep_num = int(episode.get("number") or 1)
        except (TypeError, ValueError):
            ep_num = 1
        if ep_num < 1:
            ep_num = 1
        return [(str(show_name), int(season_num), ep_num, title, yid)]

    def _new_priority_job(self, show: str) -> dict[str, Any]:
        return {"show": str(show), "boost": [], "rest": []}

    def _flatten_priority_locked(
        self,
    ) -> list[tuple[str, int, int, str, str]]:
        flat: list[tuple[str, int, int, str, str]] = []
        for job in self._priority_jobs:
            flat.extend(job.get("boost") or [])
            flat.extend(job.get("rest") or [])
        return flat

    def _rebuild_priority_ids_locked(self) -> None:
        ids = {t[4] for t in self._flatten_priority_locked()}
        ids.update(t[4] for t in self._priority_inflight)
        self._priority_ids = ids

    def _boost_ids_locked(self) -> set[str]:
        return {
            t[4]
            for job in self._priority_jobs
            for t in (job.get("boost") or [])
        }

    def _find_job_locked(self, show: str) -> dict[str, Any] | None:
        name = str(show)
        for job in self._priority_jobs:
            if job.get("show") == name:
                return job
        return None

    def _remove_yids_from_jobs_locked(self, yids: set[str]) -> None:
        if not yids:
            return
        for job in self._priority_jobs:
            job["boost"] = [t for t in (job.get("boost") or []) if t[4] not in yids]
            job["rest"] = [t for t in (job.get("rest") or []) if t[4] not in yids]
        self._priority_jobs = [
            j
            for j in self._priority_jobs
            if (j.get("boost") or j.get("rest"))
        ]

    def is_caching_show(self, show_name: str) -> bool:
        name = str(show_name)
        with self._prio_lock:
            if any(j.get("show") == name for j in self._priority_jobs):
                return True
            return any(t[0] == name for t in self._priority_inflight)

    def has_priority(self) -> bool:
        with self._prio_lock:
            return bool(self._priority_ids)

    def priority_count(self) -> int:
        with self._prio_lock:
            return len(self._priority_ids)

    def request_priority(
        self,
        items: list[tuple[str, int, int, str, str]],
        *,
        bump: bool = False,
        front: bool = False,
        retry_unavailable: bool = False,
    ) -> int:
        """Queue missing episodes for immediate download; preempts idle fills.

        Jobs are one-per-show and FIFO across shows. Within a show:

        - ``bump=False`` (Y on show): append to ``rest`` (bulk fill).
        - ``bump=True`` (Y on season/episode): append to ``boost`` — end of the
          explicit Y line, still ahead of that show's ``rest``.
        - ``front=True`` (play on uncached): insert at the head of ``boost`` and
          move this show's job to the front of the job queue.
        - ``retry_unavailable=True`` (Y): clear permanent skips and re-queue.

        Returns how many items were newly queued or moved into the boost lane.
        """
        if not self.enabled or not items:
            return 0
        candidates: list[tuple[str, int, int, str, str]] = []
        for item in items:
            yid = item[4]
            if not yid or self.is_cached(yid):
                continue
            if self.is_unavailable(yid):
                if not retry_unavailable:
                    continue
                self.clear_unavailable(yid)
            candidates.append(item)
        if not candidates:
            return 0
        show = str(candidates[0][0])
        candidates = [c for c in candidates if str(c[0]) == show]
        yids = {c[4] for c in candidates}
        changed = 0
        with self._prio_lock:
            job = self._find_job_locked(show)
            job_index: int | None = None
            if job is not None:
                job_index = self._priority_jobs.index(job)

            if bump:
                before_boost = set()
                if job is not None:
                    before_boost = {t[4] for t in (job.get("boost") or [])}
                # Pull out of rest/other jobs, then place onto boost.
                self._remove_yids_from_jobs_locked(yids)
                job = self._find_job_locked(show)
                if job is None:
                    job = self._new_priority_job(show)
                    if job_index is None:
                        self._priority_jobs.append(job)
                    else:
                        insert_at = min(job_index, len(self._priority_jobs))
                        self._priority_jobs.insert(insert_at, job)
                if front:
                    # Preserve candidate order at the head: [new..., old boost...]
                    job["boost"] = list(candidates) + list(job.get("boost") or [])
                else:
                    for item in candidates:
                        job["boost"].append(item)
                for item in candidates:
                    if item[4] not in before_boost:
                        changed += 1
                # Re-bumping an already-boosted id still counts as a useful
                # reorder when ``front`` moves it to the head.
                if front and changed == 0 and candidates:
                    changed = 1
            else:
                if job is None:
                    job = self._new_priority_job(show)
                    self._priority_jobs.append(job)
                already = {t[4] for t in self._flatten_priority_locked()}
                already |= {t[4] for t in self._priority_inflight}
                for item in candidates:
                    if item[4] in already:
                        continue
                    job["rest"].append(item)
                    already.add(item[4])
                    changed += 1

            # Prefer this show when play/front-bump asks for top-of-queue.
            if front and job is not None and self._priority_jobs:
                self._priority_jobs = [
                    j for j in self._priority_jobs if j is not job
                ]
                self._priority_jobs.insert(0, job)

            self._rebuild_priority_ids_locked()

        if changed:
            LOG.info(
                "YouTube priority cache %s%s show=%s +%d queued=%d first=%s",
                "bump" if bump else "queue",
                "-front" if front else "",
                show,
                changed,
                self.priority_count(),
                candidates[0][4],
            )
            self._refresh_pause()
            self.start_worker()
        return changed

    def _pop_priority_batch(self) -> list[tuple[str, int, int, str, str]]:
        with self._prio_lock:
            flat = self._flatten_priority_locked()
            if not flat:
                return []
            batch = flat[: self.batch_size]
            batch_yids = {t[4] for t in batch}
            # Consume from jobs in order (boost then rest).
            need = list(batch)
            need_yids = {t[4] for t in need}
            for job in self._priority_jobs:
                new_boost = []
                for t in job.get("boost") or []:
                    if t[4] in need_yids:
                        need_yids.discard(t[4])
                    else:
                        new_boost.append(t)
                job["boost"] = new_boost
                new_rest = []
                for t in job.get("rest") or []:
                    if t[4] in need_yids:
                        need_yids.discard(t[4])
                    else:
                        new_rest.append(t)
                job["rest"] = new_rest
            self._priority_jobs = [
                j
                for j in self._priority_jobs
                if (j.get("boost") or j.get("rest"))
            ]
            self._priority_inflight = list(batch)
            self._rebuild_priority_ids_locked()
            # Ensure inflight ids stay protected even if rebuild raced.
            self._priority_ids |= batch_yids
            return list(batch)

    def _clear_finished_priority_ids(
        self, batch: list[tuple[str, int, int, str, str]]
    ) -> None:
        with self._prio_lock:
            self._priority_inflight = []
            self._rebuild_priority_ids_locked()

    def _download_one(
        self,
        item: tuple[str, int, int, str, str],
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        show, season, ep_num, title, yid = item
        path = self.download_video(
            yid,
            show=show,
            season=season,
            title=title,
            episode=ep_num,
            cancel_event=cancel_event,
        )
        return path is not None

    def download_batch(
        self,
        items: list[tuple[str, int, int, str, str]],
        *,
        progress: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        stop_on_rate_limit: bool = True,
    ) -> tuple[int, int]:
        """Download up to ``batch_size`` episodes concurrently. Returns (ok, failed)."""
        if not items:
            return 0, 0
        cancel = cancel_event or self._cancel
        workers = max(1, min(self.batch_size, len(items)))
        ok = failed = 0
        if workers == 1:
            for item in items:
                if cancel.is_set():
                    break
                if stop_on_rate_limit and self.is_rate_limited():
                    break
                show, season, ep_num, title, yid = item
                if progress:
                    progress(
                        f"Downloading {show} S{season:02d}E{ep_num:02d} {title} [{yid}]"
                    )
                if self._download_one(item, cancel_event=cancel):
                    ok += 1
                else:
                    failed += 1
                    if stop_on_rate_limit and self.is_rate_limited():
                        break
            return ok, failed

        from concurrent.futures import ThreadPoolExecutor, as_completed

        if progress:
            progress(f"Downloading batch of {len(items)} (workers={workers})")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._download_one, item, cancel_event=cancel): item
                for item in items
            }
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    success = bool(fut.result())
                except Exception as exc:
                    LOG.info("YouTube batch item failed %s: %s", item[4], exc)
                    success = False
                if success:
                    ok += 1
                else:
                    failed += 1
        return ok, failed

    def sync_all(
        self,
        shows: dict[str, dict[str, Any]],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[int, int]:
        """Download all missing episodes (CLI). Returns (ok, failed)."""
        if not self.enabled:
            raise RuntimeError("youtube.cache.enabled is false")
        require_yt_dlp()
        self._cancel.clear()
        self._pause.clear()
        ok = failed = 0
        missing = self.iter_missing_episodes(shows)
        idx = 0
        while idx < len(missing) and not self._cancel.is_set():
            batch = missing[idx : idx + self.batch_size]
            idx += len(batch)
            b_ok, b_fail = self.download_batch(
                batch, progress=progress, cancel_event=self._cancel
            )
            ok += b_ok
            failed += b_fail
        return ok, failed

    def set_shows_provider(
        self, provider: Callable[[], dict[str, dict[str, Any]]]
    ) -> None:
        self._shows_provider = provider

    def _refresh_pause(self) -> None:
        """Run when idle-allowed or a priority queue is waiting / in flight."""
        if self._suspended:
            self._pause.set()
            return
        if self._want_idle or self.has_priority():
            self._pause.clear()
        else:
            self._pause.set()

    def set_idle(self, idle: bool) -> None:
        """Allow or pause background idle downloads.

        Priority cache-now requests keep the worker running even when not idle.
        Leaving idle sets ``_pause`` (unless priority is pending) so in-flight
        idle progress hooks abort; the worker stays alive for the next run.
        """
        self._want_idle = bool(idle)
        self._refresh_pause()

    def set_suspended(self, suspended: bool) -> None:
        """Hard-pause idle and priority downloads (Retro TV owns yt-dlp/network)."""
        was = self._suspended
        self._suspended = bool(suspended)
        self._refresh_pause()
        if self._suspended and not was:
            LOG.info("YouTube offline cache suspended (channel overlay active)")
        elif was and not self._suspended:
            LOG.info("YouTube offline cache resumed")

    def start_worker(self) -> None:
        """Start the download worker (idle fills and/or priority cache-now)."""
        if not self.enabled:
            return
        if self._worker is not None and self._worker.is_alive():
            return
        try:
            require_yt_dlp()
        except YoutubeDlMissingError as exc:
            LOG.error("%s", exc)
            self._last_error = str(exc)
            return
        self._cancel.clear()
        self._refresh_pause()
        self._worker = threading.Thread(
            target=self._idle_loop, daemon=True, name="youtube-offline-cache"
        )
        self._worker.start()

    def start_idle_worker(self) -> None:
        """Backward-compatible alias for :meth:`start_worker`."""
        self.start_worker()

    def shutdown(self) -> None:
        self._want_idle = False
        with self._prio_lock:
            self._priority_jobs.clear()
            self._priority_ids = set()
            self._priority_inflight = []
        self._pause.set()
        self._cancel.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=5.0)
        self._worker = None

    def _idle_loop(self) -> None:
        LOG.info(
            "YouTube offline cache worker started dir=%s mode=%s gap=%ds cooldown=%ds",
            self.cache_dir,
            self.playback_mode,
            self.idle_gap_seconds,
            self.rate_limit_cooldown_seconds,
        )
        while not self._cancel.is_set():
            # Retro TV / overlays: do not start idle or priority downloads.
            if self._suspended:
                time.sleep(0.5)
                continue

            # Bot / 429 cooldown: do not request anything until it expires.
            if self.is_rate_limited():
                left = self.rate_limit_remaining_seconds()
                time.sleep(min(30.0, max(1.0, float(left))))
                continue

            # Priority always runs (even when browse is not idle) — no idle gap.
            batch = self._pop_priority_batch()
            if batch:
                LOG.info(
                    "YouTube priority batch size=%d first=%s show=%s",
                    len(batch),
                    batch[0][4],
                    batch[0][0],
                )
                self.download_batch(batch, cancel_event=self._cancel)
                self._clear_finished_priority_ids(batch)
                self._refresh_pause()
                time.sleep(0.05)
                continue

            if self._pause.is_set():
                time.sleep(0.5)
                continue
            if not self.download_when_idle:
                time.sleep(1.0)
                continue
            provider = self._shows_provider
            if provider is None:
                time.sleep(1.0)
                continue
            try:
                shows = provider() or {}
            except Exception as exc:
                LOG.debug("YouTube offline shows provider failed: %s", exc)
                time.sleep(2.0)
                continue
            missing = self.iter_missing_episodes(shows)
            if not missing:
                time.sleep(5.0)
                continue
            if self._pause.is_set() or self._cancel.is_set() or self.has_priority():
                continue
            if self.is_rate_limited():
                continue
            batch = missing[: self.batch_size]
            LOG.info(
                "YouTube offline idle batch size=%d first=%s show=%s",
                len(batch),
                batch[0][4],
                batch[0][0],
            )
            self.download_batch(batch, cancel_event=self._cancel)
            # Pace background fills so we do not hammer YouTube continuously.
            # Priority cache-now skips this gap (handled in the branch above).
            gap = float(self.idle_gap_seconds)
            if self.is_rate_limited():
                gap = max(gap, float(self.rate_limit_remaining_seconds()))
            slept = 0.0
            while slept < gap and not self._cancel.is_set():
                if self.has_priority() and not self.is_rate_limited():
                    break
                step = min(1.0, gap - slept)
                time.sleep(step)
                slept += step
        LOG.info("YouTube offline cache worker stopped")
