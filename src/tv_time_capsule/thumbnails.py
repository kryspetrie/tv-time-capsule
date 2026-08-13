"""Generate and persist show/movie poster thumbnails."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .config import STATE_DIR
from .log import LOG

GENERATED_THUMB_DIR = os.path.join(STATE_DIR, "generated-thumbs")
CUSTOM_THUMB_DIR = os.path.join(STATE_DIR, "show-thumbs")

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")

# Distinct CRT-ish palette for synthetic posters
_SYNTH_PALETTE = (
    (30, 60, 120),
    (20, 90, 70),
    (90, 40, 70),
    (70, 70, 30),
    (40, 50, 90),
    (80, 55, 35),
    (50, 35, 80),
    (25, 75, 95),
)


def _safe_name(title: str) -> str:
    base = _SAFE_RE.sub("_", (title or "untitled").strip())[:80].strip("._")
    return base or "untitled"


def generated_thumb_path(title: str, *, kind: str = "show") -> str:
    digest = hashlib.sha1(f"{kind}:{title}".encode("utf-8")).hexdigest()[:10]
    return os.path.join(GENERATED_THUMB_DIR, f"{kind}-{_safe_name(title)}-{digest}.png")


def custom_thumb_path(title: str, *, kind: str = "show") -> str:
    return os.path.join(CUSTOM_THUMB_DIR, f"{kind}-{_safe_name(title)}.jpg")


def ensure_synthetic_thumbnail(title: str, *, kind: str = "show") -> str | None:
    """Create a colored title card PNG if missing; return path or None."""
    path = generated_thumb_path(title, kind=kind)
    if os.path.isfile(path):
        return path
    try:
        import pygame

        os.makedirs(GENERATED_THUMB_DIR, exist_ok=True)
        w, h = 640, 480
        surf = pygame.Surface((w, h))
        idx = int(hashlib.sha1(title.encode("utf-8")).hexdigest(), 16) % len(_SYNTH_PALETTE)
        bg = _SYNTH_PALETTE[idx]
        surf.fill(bg)
        # Soft vignette bars
        bar = pygame.Surface((w, 48), pygame.SRCALPHA)
        bar.fill((0, 0, 0, 90))
        surf.blit(bar, (0, 0))
        surf.blit(bar, (0, h - 48))

        font = pygame.font.Font(None, 64)
        words = (title or "?").upper().split()
        lines: list[str] = []
        cur = ""
        for word in words:
            trial = f"{cur} {word}".strip()
            if font.size(trial)[0] <= w - 48:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        lines = lines[:4] or ["?"]
        line_h = font.get_height() + 8
        total_h = len(lines) * line_h
        y = (h - total_h) // 2
        for line in lines:
            text = font.render(line, True, (230, 235, 245))
            surf.blit(text, text.get_rect(centerx=w // 2, top=y))
            y += line_h
        pygame.image.save(surf, path)
        return path
    except Exception as exc:
        LOG.debug("synthetic thumbnail failed for %s: %s", title, exc)
        return None


def weather_asset_path() -> str | None:
    """Bundled ``assets/weather.png`` if present."""
    path = os.path.join(os.path.dirname(__file__), "assets", "weather.png")
    return path if os.path.isfile(path) else None


def ensure_weather_thumbnail() -> str | None:
    """Weather card art: prefer bundled ``weather.png``, else synthetic poster."""
    asset = weather_asset_path()
    if asset:
        return asset
    path = generated_thumb_path("Weather Channel", kind="channel")
    if os.path.isfile(path):
        return path
    try:
        import pygame

        os.makedirs(GENERATED_THUMB_DIR, exist_ok=True)
        w, h = 640, 480
        surf = pygame.Surface((w, h))
        for y in range(h):
            t = y / max(1, h - 1)
            r = int(18 + 20 * t)
            g = int(55 + 70 * t)
            b = int(110 + 50 * (1.0 - t))
            pygame.draw.line(surf, (r, g, b), (0, y), (w, y))
        sun_c = (255, 210, 90)
        pygame.draw.circle(surf, sun_c, (480, 120), 56)
        pygame.draw.circle(surf, (255, 235, 160), (480, 120), 38)
        cloud = (235, 240, 250)
        for cx, cy, rx, ry in (
            (160, 150, 90, 42),
            (220, 140, 70, 36),
            (120, 165, 60, 30),
            (300, 280, 100, 45),
            (360, 270, 75, 38),
        ):
            pygame.draw.ellipse(
                surf, cloud, pygame.Rect(cx - rx, cy - ry, rx * 2, ry * 2)
            )
        pygame.draw.rect(surf, (12, 40, 70), (0, h - 110, w, 110))
        band = pygame.Surface((w, 72), pygame.SRCALPHA)
        band.fill((0, 0, 0, 140))
        surf.blit(band, (0, 28))
        title_font = pygame.font.Font(None, 72)
        sub_font = pygame.font.Font(None, 36)
        title = title_font.render("WEATHER", True, (240, 245, 255))
        sub = sub_font.render("CHANNEL 004", True, (120, 220, 160))
        surf.blit(title, title.get_rect(centerx=w // 2, top=34))
        surf.blit(sub, sub.get_rect(centerx=w // 2, top=92))
        pygame.image.save(surf, path)
        return path
    except Exception as exc:
        LOG.debug("weather thumbnail failed: %s", exc)
        return None


def extract_video_thumbnail(
    video_path: str,
    dest_path: str,
    *,
    seek_secs: float = 12.0,
    ffmpeg_path: str | None = None,
) -> str | None:
    """Grab one frame from *video_path* into *dest_path* via ffmpeg."""
    if not video_path or not os.path.isfile(video_path):
        return None
    ffmpeg = ffmpeg_path or "ffmpeg"
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    tmp = dest_path + ".tmp.jpg"
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(max(0.0, float(seek_secs))),
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "3",
        "-y",
        tmp,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=20, check=False)
        if result.returncode != 0 or not os.path.isfile(tmp):
            LOG.debug(
                "ffmpeg thumb failed path=%s rc=%s",
                video_path,
                result.returncode,
            )
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return None
        os.replace(tmp, dest_path)
        return dest_path
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.debug("ffmpeg thumb error: %s", exc)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None


def first_episode_path(
    show: dict[str, Any],
    *,
    resolve_local: Any | None = None,
) -> str | None:
    """First on-disk episode path; *resolve_local(ep)* may map yt: → cached file."""
    seasons = show.get("seasons") or {}
    for s_num in sorted(seasons.keys()):
        eps = (seasons.get(s_num) or {}).get("episodes") or []
        for ep in eps:
            if resolve_local is not None:
                try:
                    resolved = resolve_local(ep)
                except Exception:
                    resolved = None
                if resolved and os.path.isfile(resolved):
                    return str(resolved)
            path = ep.get("path") if isinstance(ep, dict) else None
            if path and os.path.isfile(path) and not str(path).startswith("yt:"):
                return path
    return None


def ensure_show_thumbnail(
    title: str,
    show: dict[str, Any] | None,
    *,
    ffmpeg_path: str | None = None,
    resolve_local: Any | None = None,
) -> str | None:
    """Resolve a usable show poster: existing → custom → extracted → synthetic."""
    if show:
        existing = show.get("thumbnail")
        if existing and os.path.isfile(existing):
            return existing
    custom = custom_thumb_path(title, kind="show")
    if os.path.isfile(custom):
        if show is not None:
            show["thumbnail"] = custom
        return custom
    if show:
        video = first_episode_path(show, resolve_local=resolve_local)
        if video:
            dest = generated_thumb_path(title, kind="show").replace(".png", ".jpg")
            extracted = extract_video_thumbnail(
                video, dest, ffmpeg_path=ffmpeg_path
            )
            if extracted:
                show["thumbnail"] = extracted
                return extracted
    synth = ensure_synthetic_thumbnail(title, kind="show")
    if synth and show is not None:
        show["thumbnail"] = synth
    return synth


def ensure_movie_thumbnail(
    title: str,
    movie: dict[str, Any] | None,
    *,
    ffmpeg_path: str | None = None,
) -> str | None:
    if movie:
        existing = movie.get("thumbnail")
        if existing and os.path.isfile(existing):
            return existing
    custom = custom_thumb_path(title, kind="movie")
    if os.path.isfile(custom):
        if movie is not None:
            movie["thumbnail"] = custom
        return custom
    if movie:
        path = movie.get("path")
        if path and os.path.isfile(path):
            dest = generated_thumb_path(title, kind="movie").replace(".png", ".jpg")
            extracted = extract_video_thumbnail(
                path, dest, ffmpeg_path=ffmpeg_path
            )
            if extracted:
                movie["thumbnail"] = extracted
                return extracted
    synth = ensure_synthetic_thumbnail(title, kind="movie")
    if synth and movie is not None:
        movie["thumbnail"] = synth
    return synth


def save_surface_as_thumbnail(surface, title: str, *, kind: str = "show") -> str | None:
    """Persist a pygame Surface as the custom poster for *title*."""
    try:
        import pygame

        os.makedirs(CUSTOM_THUMB_DIR, exist_ok=True)
        path = custom_thumb_path(title, kind=kind)
        pygame.image.save(surface, path)
        return path
    except Exception as exc:
        LOG.warning("save thumbnail failed: %s", exc)
        return None
