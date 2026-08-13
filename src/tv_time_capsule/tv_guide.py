"""TV Guide Channel — menu-styled auto-scrolling lineup."""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any, Callable

import pygame

from .config import C
from .log import LOG
from .weather.adapters.forecast_cache import DiskForecastStore
from .weather.adapters.forecast_resilient import build_forecast_client
from .weather.adapters.geocode_twc import resolve_location
from .weather.models import CurrentConditions, WeatherSnapshot
from .weather.ui.icons import load_icon

# Equal-time top slots: N show previews, then weather, then branding.
PREVIEWS_PER_CYCLE = 5
TOP_SLOT_MS = 4000
# List: dwell on a page, then smooth-scroll one page.
PAGE_DWELL_MS = 5500
PAGE_SCROLL_MS = 1200
# Don't hit live weather more than once per this window.
WEATHER_REFRESH_MIN_S = 30 * 60

_weather_lock = threading.Lock()
_weather_snap: WeatherSnapshot | None = None
_weather_fetching = False
_weather_last_fetch_at = 0.0


def build_guide_rows(
    *,
    show_names: list[str],
    movie_names: list[str],
    show_channels: dict[str, int],
    movie_channels: dict[str, int],
    shows: dict[str, Any] | None = None,
    movies: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Lineup in show-list then movie-list order (same numbers as each list)."""
    rows: list[dict[str, Any]] = []
    shows = shows or {}
    movies = movies or {}
    for name in show_names:
        ch = show_channels.get(name)
        thumb = (shows.get(name) or {}).get("thumbnail")
        rows.append(
            {
                "kind": "show",
                "name": name,
                "channel": int(ch) if isinstance(ch, int) else None,
                "thumbnail": thumb,
            }
        )
    for key in movie_names:
        movie = movies.get(key) or {}
        ch = movie_channels.get(key)
        rows.append(
            {
                "kind": "movie",
                "name": movie.get("title") or key,
                "key": key,
                "channel": int(ch) if isinstance(ch, int) else None,
                "thumbnail": movie.get("thumbnail"),
            }
        )
    return rows


def guide_row_metrics(*, font_title: pygame.font.Font) -> tuple[int, int]:
    """Return ``(row_h, gap)`` — taller cards, compact title font."""
    row_h = max(64, font_title.get_height() + 36)
    gap = 10
    return row_h, gap


def guide_page_size(
    *,
    screen_h: int,
    top_h: int,
    font_title: pygame.font.Font,
) -> int:
    """How many channel rows fit in the list area."""
    header_h = max(26, font_title.get_height() + 6)
    list_top = top_h + 2
    body_top = list_top + header_h + 8
    row_h, gap = guide_row_metrics(font_title=font_title)
    usable = max(1, screen_h - body_top - 12)
    return max(1, (usable + gap) // (row_h + gap))


def _channel_column_width(font: pygame.font.Font, rows: list[dict[str, Any]]) -> int:
    widest = font.size("000")[0]
    for row in rows:
        ch = row.get("channel")
        text = str(ch) if isinstance(ch, int) else "-"
        widest = max(widest, font.size(text)[0])
    return widest


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(math.pi * t)


def ensure_guide_weather(
    config: dict[str, Any] | None,
    *,
    force_refresh: bool = False,
) -> CurrentConditions | None:
    """Current conditions from disk cache; rare background refresh only."""
    global _weather_snap, _weather_fetching, _weather_last_fetch_at
    weather_cfg = (config or {}).get("weather") or {}
    if not isinstance(weather_cfg, dict):
        weather_cfg = {}
    location = resolve_location(weather_cfg)
    if location is None:
        return None

    with _weather_lock:
        snap = _weather_snap
    if snap is None:
        try:
            snap = DiskForecastStore().load(location, max_age_s=6 * 3600)
            if snap is not None:
                with _weather_lock:
                    _weather_snap = snap
        except Exception:
            LOG.debug("TV Guide weather cache load failed", exc_info=True)

    now = time.time()
    age = now - float(getattr(snap, "fetched_at", 0) or 0) if snap else 1e9
    need = force_refresh or snap is None or age > WEATHER_REFRESH_MIN_S
    if (
        need
        and not _weather_fetching
        and now - _weather_last_fetch_at >= WEATHER_REFRESH_MIN_S
    ):
        _weather_last_fetch_at = now
        _weather_fetching = True

        def _worker() -> None:
            global _weather_snap, _weather_fetching
            try:
                client = build_forecast_client()
                fresh = client.fetch(location)
                DiskForecastStore().save(location, fresh)
                with _weather_lock:
                    _weather_snap = fresh
            except Exception:
                LOG.debug("TV Guide weather fetch failed", exc_info=True)
            finally:
                _weather_fetching = False

        threading.Thread(target=_worker, daemon=True, name="tv-guide-weather").start()

    with _weather_lock:
        snap = _weather_snap
    return snap.current if snap is not None else None


def peek_guide_weather() -> CurrentConditions | None:
    """In-memory snapshot only — never starts a network fetch."""
    with _weather_lock:
        snap = _weather_snap
    return snap.current if snap is not None else None


def top_slot_count() -> int:
    return PREVIEWS_PER_CYCLE + 2  # shows + weather + branding


def resolve_top_mode(slot: int) -> str:
    """Mode for a top-panel slot: preview × N, then weather, then branding."""
    pos = int(slot) % top_slot_count()
    if pos < PREVIEWS_PER_CYCLE:
        return "preview"
    if pos == PREVIEWS_PER_CYCLE:
        return "weather"
    return "branding"


def pick_random_preview_idx(
    row_count: int,
    *,
    avoid: int | None = None,
    rng: random.Random | None = None,
) -> int:
    """Pick a random guide row for the top preview (avoid immediate repeat)."""
    if row_count <= 0:
        return 0
    if row_count == 1:
        return 0
    chooser = rng if rng is not None else random
    choices = list(range(row_count))
    if avoid is not None and 0 <= int(avoid) < row_count:
        filtered = [i for i in choices if i != int(avoid)]
        if filtered:
            choices = filtered
    return int(chooser.choice(choices))


def resolve_top_slot(
    slot: int,
    *,
    row_count: int,
    avoid: int | None = None,
    rng: random.Random | None = None,
) -> tuple[str, int]:
    """Return ``(mode, preview_idx)`` — preview picks are randomized."""
    mode = resolve_top_mode(slot)
    if mode != "preview":
        return mode, 0
    return mode, pick_random_preview_idx(row_count, avoid=avoid, rng=rng)


def draw_tv_guide(
    screen: pygame.Surface,
    *,
    rows: list[dict[str, Any]],
    scroll_offset: int,
    scroll_pixel: float,
    top_mode: str,
    preview_idx: int,
    fonts: dict[str, pygame.font.Font],
    load_image: Callable[..., pygame.Surface | None],
    weather: CurrentConditions | None,
    now_ms: int,
) -> int:
    """Draw menu-styled guide. Returns page_size (rows per screen)."""
    sw, sh = screen.get_size()
    screen.fill(C.BG)

    # Prefer smaller title font for longer names in the list.
    font_title = fonts.get("title") or fonts["sm"]
    font_ch = fonts.get("ch") or fonts["md"]
    font_sub = fonts.get("sub") or fonts["sm"]

    top_h = max(120, sh // 3)
    page_size = guide_page_size(screen_h=sh, top_h=top_h, font_title=font_title)
    row_h, gap = guide_row_metrics(font_title=font_title)
    stride = row_h + gap

    panel = pygame.Rect(16, 12, sw - 32, top_h - 16)
    pygame.draw.rect(screen, C.BG_CARD, panel, border_radius=10)
    pygame.draw.rect(screen, C.BLUE, panel, 1, border_radius=10)

    if top_mode == "preview":
        _draw_top_preview(
            screen,
            rows=rows,
            preview_idx=preview_idx,
            area=panel,
            fonts=fonts,
            load_image=load_image,
        )
    elif top_mode == "weather":
        _draw_top_weather(screen, weather=weather, area=panel, fonts=fonts)
    else:
        _draw_top_branding(screen, area=panel, fonts=fonts, now_ms=now_ms)

    list_top = top_h + 2
    header_h = max(26, font_sub.get_height() + 8)
    pygame.draw.rect(screen, C.BG_HEADER, (0, list_top, sw, header_h))
    pygame.draw.line(
        screen, C.BLUE, (0, list_top + header_h - 1), (sw, list_top + header_h - 1), 1
    )

    ch_col_w = _channel_column_width(font_ch, rows)
    row_left = 30
    ch_x = row_left + 14
    title_x = ch_x + ch_col_w + 16

    ch_h = font_sub.render("CH", True, C.GREEN)
    name_h = font_sub.render("PROGRAM", True, C.BRIGHT)
    # Left-align CH header with left-aligned channel numbers.
    screen.blit(ch_h, (ch_x, list_top + (header_h - ch_h.get_height()) // 2))
    screen.blit(name_h, (title_x, list_top + (header_h - name_h.get_height()) // 2))
    clock = time.strftime("%I:%M %p").lstrip("0")
    clk = font_sub.render(clock, True, C.DIM)
    screen.blit(
        clk,
        (sw - clk.get_width() - 20, list_top + (header_h - clk.get_height()) // 2),
    )

    body_top = list_top + header_h + 8
    body_bottom = sh - 8
    if not rows:
        empty = fonts["md"].render("No channels in lineup", True, C.DIM)
        screen.blit(empty, empty.get_rect(center=(sw // 2, (body_top + sh) // 2)))
        return page_size

    n = len(rows)
    # Pixel scroll: base at scroll_offset, plus smooth animation pixels.
    base_y = int(scroll_offset) * stride + float(scroll_pixel)
    # Clip list area so rows don't draw over the header/top panel.
    prev_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(0, body_top, sw, max(1, body_bottom - body_top)))

    # Draw enough rows to cover the viewport during a scroll.
    first = max(0, int(base_y // stride) - 1)
    last = min(n, first + page_size + 3)
    for idx in range(first, last):
        y = body_top + idx * stride - base_y
        if y + row_h < body_top or y > body_bottom:
            continue
        row = rows[idx]
        rect = pygame.Rect(row_left, int(y), sw - 60, row_h)
        pygame.draw.rect(screen, C.BG_CARD, rect, border_radius=8)

        ch = row.get("channel")
        ch_text = str(ch) if isinstance(ch, int) else "-"
        ch_surf = font_ch.render(ch_text, True, C.GREEN)
        screen.blit(
            ch_surf,
            (ch_x, rect.y + (rect.height - ch_surf.get_height()) // 2),
        )

        title = str(row.get("name") or "")
        kind = row.get("kind") or "show"
        subtitle = "Movie" if kind == "movie" else "Show"
        max_w = max(20, rect.right - 14 - title_x)
        title_surf = font_title.render(title, True, C.WHITE)
        if title_surf.get_width() > max_w:
            while title and font_title.size(title + "...")[0] > max_w:
                title = title[:-1]
            title_surf = font_title.render(title + "...", True, C.WHITE)
        sub_surf = font_sub.render(subtitle, True, C.DIM)
        text_h = title_surf.get_height() + 2 + sub_surf.get_height()
        text_y = rect.y + (rect.height - text_h) // 2
        screen.blit(title_surf, (title_x, text_y))
        screen.blit(sub_surf, (title_x, text_y + title_surf.get_height() + 2))

    screen.set_clip(prev_clip)
    return page_size


def _draw_top_preview(
    screen: pygame.Surface,
    *,
    rows: list[dict[str, Any]],
    preview_idx: int,
    area: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    load_image: Callable[..., pygame.Surface | None],
) -> None:
    pad = 14
    if not rows:
        msg = fonts["md"].render("No programs", True, C.DIM)
        screen.blit(msg, msg.get_rect(center=area.center))
        return
    idx = preview_idx % len(rows)
    row = rows[idx]

    thumb_h = area.h - pad * 2
    thumb_w = max(1, int(thumb_h * 4 / 3))
    if thumb_w > area.w // 2:
        thumb_w = max(1, area.w // 2 - pad)
        thumb_h = max(1, int(thumb_w * 3 / 4))
    thumb_rect = pygame.Rect(
        area.x + pad,
        area.y + pad + max(0, (area.h - pad * 2 - thumb_h) // 2),
        thumb_w,
        thumb_h,
    )
    pygame.draw.rect(screen, C.BG, thumb_rect, border_radius=6)
    pygame.draw.rect(screen, C.CYAN, thumb_rect, 2, border_radius=6)

    path = row.get("thumbnail")
    # Cover-scale then center-crop into the 4:3 rect.
    img = load_image(path, (thumb_w, thumb_h), cover=True) if path else None
    if img is not None:
        prev = screen.get_clip()
        screen.set_clip(thumb_rect.inflate(-2, -2))
        tx = thumb_rect.x + (thumb_rect.w - img.get_width()) // 2
        ty = thumb_rect.y + (thumb_rect.h - img.get_height()) // 2
        screen.blit(img, (tx, ty))
        screen.set_clip(prev)
    else:
        ph = fonts["md"].render("?", True, C.DIM)
        screen.blit(ph, ph.get_rect(center=thumb_rect.center))

    text_x = thumb_rect.right + 16
    text_right = area.right - pad
    max_w = max(40, text_right - text_x)
    text_top = area.y + pad
    text_bottom = area.bottom - pad

    ch = row.get("channel")
    ch_label = f"CH {ch}" if isinstance(ch, int) else "CH -"
    ch_surf = fonts["md"].render(ch_label, True, C.GREEN)
    y = text_top
    if y + ch_surf.get_height() <= text_bottom:
        screen.blit(ch_surf, (text_x, y))
        y += ch_surf.get_height() + 6

    name = str(row.get("name") or "")
    name_surf = fonts["md"].render(name, True, C.BRIGHT)
    if name_surf.get_width() > max_w:
        while name and fonts["md"].size(name + "...")[0] > max_w:
            name = name[:-1]
        name_surf = fonts["md"].render(name + "...", True, C.BRIGHT)
    if y + name_surf.get_height() <= text_bottom:
        screen.blit(name_surf, (text_x, y))
        y += name_surf.get_height() + 4

    kind = "Movie" if row.get("kind") == "movie" else "Show"
    kind_surf = fonts["sm"].render(kind, True, C.DIM)
    if y + kind_surf.get_height() <= text_bottom:
        screen.blit(kind_surf, (text_x, y))


def _draw_top_weather(
    screen: pygame.Surface,
    *,
    weather: CurrentConditions | None,
    area: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
) -> None:
    pad = 14
    title = fonts["sm"].render("LOCAL WEATHER", True, C.CYAN)
    screen.blit(title, (area.x + pad, area.y + pad))

    if weather is None:
        msg = fonts["md"].render("Fetching...", True, C.DIM)
        screen.blit(msg, msg.get_rect(midright=(area.right - pad, area.centery)))
        return

    right = area.right - pad
    icon_size = min(72, area.h - pad * 2 - title.get_height())
    icon = load_icon(
        icon_size,
        weather.icon_id or "unknown",
        icon_url=weather.icon_url or None,
    )

    temp = (
        f"{int(round(weather.temperature_f))} F"
        if weather.temperature_f is not None
        else "-- F"
    )
    temp_surf = fonts["lg"].render(temp, True, C.BRIGHT)
    cond = (weather.condition_text or weather.narrative or "-").strip()
    max_cond_w = max(60, area.w // 2 - icon_size - 24)
    cond_surf = fonts["sm"].render(cond, True, C.WHITE)
    if cond_surf.get_width() > max_cond_w:
        while cond and fonts["sm"].size(cond + "...")[0] > max_cond_w:
            cond = cond[:-1]
        cond_surf = fonts["sm"].render(cond + "...", True, C.WHITE)
    hum = (
        f"Humidity {int(round(weather.humidity_pct))}%"
        if weather.humidity_pct is not None
        else "Humidity --"
    )
    hum_surf = fonts["sm"].render(hum, True, C.DIM)

    icon_x = right - icon_size
    icon_y = area.y + pad + title.get_height() + 4
    if icon_y + icon_size > area.bottom - pad:
        icon_y = area.bottom - pad - icon_size
    screen.blit(icon, (icon_x, icon_y))

    text_right = icon_x - 12
    text_block_h = (
        temp_surf.get_height() + 4 + cond_surf.get_height() + 4 + hum_surf.get_height()
    )
    text_y = max(
        area.y + pad + title.get_height() + 4,
        area.y + (area.h - text_block_h) // 2,
    )
    screen.blit(temp_surf, temp_surf.get_rect(right=text_right, top=text_y))
    text_y += temp_surf.get_height() + 4
    screen.blit(cond_surf, cond_surf.get_rect(right=text_right, top=text_y))
    text_y += cond_surf.get_height() + 4
    screen.blit(hum_surf, hum_surf.get_rect(right=text_right, top=text_y))


def _draw_top_branding(
    screen: pygame.Surface,
    *,
    area: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    now_ms: int,
) -> None:
    title = fonts["lg"].render("TV GUIDE CHANNEL", True, C.GREEN)
    sub = fonts["sm"].render("Dial 005", True, C.DIM)
    title_rect = title.get_rect(centerx=area.centerx, centery=area.centery - 10)
    if title_rect.width > area.w - 40:
        title = fonts["md"].render("TV GUIDE CHANNEL", True, C.GREEN)
        title_rect = title.get_rect(centerx=area.centerx, centery=area.centery - 10)
    screen.blit(title, title_rect)
    screen.blit(sub, sub.get_rect(centerx=area.centerx, top=title_rect.bottom + 8))
    pulse = 80 + int(40 * abs(((now_ms // 40) % 100) - 50) / 50)
    line_y = title_rect.bottom + 4
    pygame.draw.line(
        screen,
        (pulse // 3, pulse, pulse // 2),
        (area.x + 48, line_y),
        (area.right - 48, line_y),
        2,
    )
