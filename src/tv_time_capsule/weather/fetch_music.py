"""Download Weather background music + RetroCast announcements into assets.

Sources:
- netbymatt/ws4kp-music (AI companion tracks for ws4kp)
- weather.com/retro public assets (music loop + voiceovers / alert tone)

Classic copyrighted Weather Channel airchecks (TWC Classics, etc.) are not fetched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/netbymatt/ws4kp-music/contents"
RAW_BASE = "https://raw.githubusercontent.com/netbymatt/ws4kp-music/main"
TWC_RETRO = "https://weather.com/retro"
TWC_SOUND_BASE = f"{TWC_RETRO}/assets/sound"
TWC_MUSIC_BASE = f"{TWC_SOUND_BASE}/music"
# Known RetroCast assets (Nuxt public). Discovery may find more later.
TWC_KNOWN_MUSIC = ("neon-office-glide.mp3",)
TWC_KNOWN_ANNOUNCEMENTS: tuple[tuple[str, str], ...] = (
    # (relative under /assets/sound/, dest filename)
    ("alert-tone.mp3", "alert-tone.mp3"),
    ("voiceovers/current.mp3", "current.mp3"),
    ("voiceovers/extended.mp3", "extended.mp3"),
    ("voiceovers/local.mp3", "local.mp3"),
    ("voiceovers/radar.mp3", "radar.mp3"),
    ("voiceovers/regional.mp3", "regional.mp3"),
)
USER_AGENT = "tv-time-capsule-weather-music/1.0"
_MUSIC_PATH_RE = re.compile(
    r"(?:assets/)?sound/music/([A-Za-z0-9._-]+\.mp3)", re.IGNORECASE
)
_VOICE_PATH_RE = re.compile(
    r"(?:assets/)?sound/(alert-tone\.mp3|voiceovers/[A-Za-z0-9._-]+\.mp3)",
    re.IGNORECASE,
)


def default_music_dest() -> Path:
    """Installed package music dir when importable, else checkout assets path."""
    try:
        from .adapters.music_pygame import bundled_music_dir

        return bundled_music_dir()
    except Exception:
        return Path(__file__).resolve().parent / "assets" / "music"


def default_announcements_dest() -> Path:
    try:
        from .adapters.announcements import bundled_announcements_dir

        return bundled_announcements_dir()
    except Exception:
        return Path(__file__).resolve().parent / "assets" / "announcements"


def _http_get(url: str, *, timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def list_ws4kp_mp3s(*, include_holiday: bool) -> list[tuple[str, str]]:
    """Return (filename, download_url) pairs from ws4kp-music."""
    raw = _http_get(GITHUB_API)
    entries = json.loads(raw.decode("utf-8"))
    out: list[tuple[str, str]] = []
    for item in entries:
        name = str(item.get("name") or "")
        kind = str(item.get("type") or "")
        if kind == "file" and name.lower().endswith(".mp3"):
            url = item.get("download_url") or f"{RAW_BASE}/{urllib.parse.quote(name)}"
            out.append((name, str(url)))
        elif kind == "dir" and name == "Holiday" and include_holiday:
            holiday = json.loads(
                _http_get(f"{GITHUB_API}/Holiday").decode("utf-8")
            )
            for h in holiday:
                hname = str(h.get("name") or "")
                if h.get("type") == "file" and hname.lower().endswith(".mp3"):
                    url = h.get("download_url") or (
                        f"{RAW_BASE}/Holiday/{urllib.parse.quote(hname)}"
                    )
                    out.append((f"Holiday - {hname}", str(url)))
    out.sort(key=lambda t: t[0].lower())
    return out


def _twc_js_bodies() -> list[str]:
    bodies: list[str] = []
    try:
        html = _http_get(f"{TWC_RETRO}/", timeout=30).decode("utf-8", "replace")
    except Exception:
        return bodies
    bodies.append(html)
    js_paths = sorted(set(re.findall(r"/retro/_nuxt/[^\"'\s]+\.js", html)))
    for js_path in js_paths[:40]:
        try:
            bodies.append(
                _http_get(f"https://weather.com{js_path}", timeout=30).decode(
                    "utf-8", "replace"
                )
            )
        except Exception:
            continue
    return bodies


def list_twc_retro_music() -> list[tuple[str, str]]:
    """Return (filename, url) for weather.com/retro music assets."""
    names: set[str] = set(TWC_KNOWN_MUSIC)
    for body in _twc_js_bodies():
        for m in _MUSIC_PATH_RE.finditer(body):
            names.add(m.group(1))
    out: list[tuple[str, str]] = []
    for name in sorted(names, key=str.lower):
        dest_name = f"TWC - {name}"
        url = f"{TWC_MUSIC_BASE}/{urllib.parse.quote(name)}"
        out.append((dest_name, url))
    return out


def list_twc_retro_announcements() -> list[tuple[str, str]]:
    """Return (filename, url) for RetroCast voiceovers + alert tone."""
    rels: set[str] = {rel for rel, _dest in TWC_KNOWN_ANNOUNCEMENTS}
    for body in _twc_js_bodies():
        for m in _VOICE_PATH_RE.finditer(body):
            rels.add(m.group(1).replace("\\", "/"))
    # Prefer stable dest names (basename).
    out: list[tuple[str, str]] = []
    for rel in sorted(rels, key=str.lower):
        dest = Path(rel).name
        url = f"{TWC_SOUND_BASE}/{urllib.parse.quote(rel, safe='/')}"
        out.append((dest, url))
    return out


def download_file(
    url: str,
    dest: Path,
    *,
    force: bool,
    min_bytes: int = 20_000,
) -> str:
    if dest.is_file() and dest.stat().st_size > 0 and not force:
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        data = _http_get(url)
        if len(data) < min_bytes:
            raise RuntimeError(f"download too small ({len(data)} bytes): {url}")
        tmp.write_bytes(data)
        tmp.replace(dest)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return "get"


def _download_all(
    tracks: list[tuple[str, str]],
    dest: Path,
    *,
    force: bool,
    label: str,
    min_bytes: int = 20_000,
) -> tuple[int, int, int]:
    if not tracks:
        print(f"  ({label}: nothing to download)")
        return 0, 0, 0
    print(f"  {label}: {len(tracks)} file(s) → {dest}")
    got = skipped = failed = 0
    for name, url in tracks:
        path = dest / name
        try:
            status = download_file(url, path, force=force, min_bytes=min_bytes)
        except Exception as exc:
            print(f"  fail {name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if status == "skip":
            print(f"  skip {name}")
            skipped += 1
        else:
            print(f"  get  {name}")
            got += 1
    return got, skipped, failed


def run(
    music_dest: Path,
    announcements_dest: Path,
    *,
    force: bool = False,
    include_holiday: bool = False,
    source: str = "all",
) -> int:
    print(f"Weather music → {music_dest}")
    print(f"Announcements → {announcements_dest}")
    got = skipped = failed = 0

    if source in ("all", "ws4kp"):
        try:
            tracks = list_ws4kp_mp3s(include_holiday=include_holiday)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Failed to list ws4kp-music: {exc}", file=sys.stderr)
            failed += 1
            tracks = []
        g, s, f = _download_all(
            tracks, music_dest, force=force, label="ws4kp-music", min_bytes=50_000
        )
        got += g
        skipped += s
        failed += f

    if source in ("all", "twc"):
        try:
            tracks = list_twc_retro_music()
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Failed to list weather.com/retro music: {exc}", file=sys.stderr)
            failed += 1
            tracks = []
        g, s, f = _download_all(
            tracks,
            music_dest,
            force=force,
            label="weather.com/retro music",
            min_bytes=50_000,
        )
        got += g
        skipped += s
        failed += f

        try:
            clips = list_twc_retro_announcements()
        except (urllib.error.URLError, TimeoutError) as exc:
            print(
                f"Failed to list weather.com/retro announcements: {exc}",
                file=sys.stderr,
            )
            failed += 1
            clips = []
        g, s, f = _download_all(
            clips,
            announcements_dest,
            force=force,
            label="weather.com/retro announcements",
            min_bytes=10_000,
        )
        got += g
        skipped += s
        failed += f

    print(f"Done: {got} downloaded, {skipped} skipped, {failed} failed")
    if got == 0 and skipped == 0:
        return 1
    return 1 if failed and got == 0 and skipped == 0 else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Download weather music + RetroCast announcements "
            "(ws4kp-music + weather.com/retro) for native Retro Weather."
        )
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Music directory (default: bundled weather/assets/music)",
    )
    parser.add_argument(
        "--announcements-dest",
        type=Path,
        default=None,
        help="Announcements directory (default: weather/assets/announcements)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when files already exist",
    )
    parser.add_argument(
        "--include-holiday",
        action="store_true",
        help="Also download ws4kp-music Holiday/ tracks (flattened into music dest)",
    )
    parser.add_argument(
        "--source",
        choices=("all", "ws4kp", "twc"),
        default="all",
        help="Which catalog to fetch (default: all)",
    )
    args = parser.parse_args(argv)
    music_dest = args.dest if args.dest is not None else default_music_dest()
    ann_dest = (
        args.announcements_dest
        if args.announcements_dest is not None
        else default_announcements_dest()
    )
    return run(
        music_dest,
        ann_dest,
        force=args.force,
        include_holiday=args.include_holiday,
        source=args.source,
    )


if __name__ == "__main__":
    raise SystemExit(main())
