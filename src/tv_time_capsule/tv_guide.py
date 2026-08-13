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
# Weather / branding (and short previews that need no blurb scroll).
TOP_SLOT_MS = 6000
# Preview with a title but no overflowing blurb.
TOP_SLOT_PREVIEW_MS = 9000
# Blurb vertical scroll: long hold at top, scroll through both sentences,
# brief pause at bottom, then advance.
BLURB_HOLD_MS = 5200
BLURB_END_HOLD_MS = 800
BLURB_SCROLL_PX_PER_S = 16.0
# Extra slack so the slot never advances before the scroll reaches the end.
BLURB_SCROLL_TAIL_MS = 500
# List: dwell on a page, then smooth-scroll one page.
PAGE_DWELL_MS = 5500
PAGE_SCROLL_MS = 1200
# Don't hit live weather more than once per this window.
WEATHER_REFRESH_MIN_S = 30 * 60

_weather_lock = threading.Lock()
_weather_snap: WeatherSnapshot | None = None
_weather_fetching = False
_weather_last_fetch_at = 0.0
# idle | fetching | ready | unavailable
_weather_status = "idle"


def guide_header_h(*, font_sub: pygame.font.Font) -> int:
    """List header height — shared by page-size math and draw."""
    return max(26, font_sub.get_height() + 8)


def build_guide_rows(
    *,
    show_names: list[str],
    movie_names: list[str],
    show_channels: dict[str, int],
    movie_channels: dict[str, int],
    shows: dict[str, Any] | None = None,
    movies: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Lineup: all shows, then all movies (section headers when both exist)."""
    from .guide_meta import resolve_nfo_dir_for_row

    shows = shows or {}
    movies = movies or {}
    show_rows: list[dict[str, Any]] = []
    movie_rows: list[dict[str, Any]] = []
    for name in show_names:
        ch = show_channels.get(name)
        thumb = (shows.get(name) or {}).get("thumbnail")
        row = {
            "kind": "show",
            "name": name,
            "channel": int(ch) if isinstance(ch, int) else None,
            "thumbnail": thumb,
        }
        nfo_dir = resolve_nfo_dir_for_row(row, shows=shows, movies=movies)
        if nfo_dir:
            row["nfo_dir"] = nfo_dir
        show_rows.append(row)
    for key in movie_names:
        movie = movies.get(key) or {}
        ch = movie_channels.get(key)
        row = {
            "kind": "movie",
            "name": movie.get("title") or key,
            "key": key,
            "channel": int(ch) if isinstance(ch, int) else None,
            "thumbnail": movie.get("thumbnail"),
        }
        nfo_dir = resolve_nfo_dir_for_row(row, shows=shows, movies=movies)
        if nfo_dir:
            row["nfo_dir"] = nfo_dir
        movie_rows.append(row)

    rows: list[dict[str, Any]] = []
    both = bool(show_rows) and bool(movie_rows)
    if show_rows:
        if both:
            rows.append({"kind": "section", "name": "SHOWS", "channel": None})
        rows.extend(show_rows)
    if movie_rows:
        if both:
            rows.append({"kind": "section", "name": "MOVIES", "channel": None})
        rows.extend(movie_rows)
    return rows


def is_guide_program_row(row: dict[str, Any] | None) -> bool:
    """True for tuneable show/movie rows (not section headers)."""
    if not row:
        return False
    return (row.get("kind") or "") in ("show", "movie")


def guide_program_indices(rows: list[dict[str, Any]]) -> list[int]:
    return [i for i, row in enumerate(rows) if is_guide_program_row(row)]


def guide_row_metrics(*, font_title: pygame.font.Font) -> tuple[int, int]:
    """Return ``(row_h, gap)`` — taller cards, compact title font."""
    row_h = max(64, font_title.get_height() + 36)
    gap = 10
    return row_h, gap


def guide_section_row_h(*, font_title: pygame.font.Font) -> int:
    """Height of a SHOWS/MOVIES section divider (same stride as program rows)."""
    row_h, _gap = guide_row_metrics(font_title=font_title)
    return row_h


def guide_page_size(
    *,
    screen_h: int,
    top_h: int,
    font_title: pygame.font.Font,
    font_sub: pygame.font.Font | None = None,
) -> int:
    """How many channel rows fit in the list area."""
    header_h = guide_header_h(font_sub=font_sub or font_title)
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


def guide_weather_status() -> str:
    """Current guide-weather state: ready | fetching | unavailable | idle."""
    with _weather_lock:
        return str(_weather_status)


def ensure_guide_weather(
    config: dict[str, Any] | None,
    *,
    force_refresh: bool = False,
) -> CurrentConditions | None:
    """Current conditions from disk cache; rare background refresh only."""
    global _weather_snap, _weather_fetching, _weather_last_fetch_at, _weather_status
    weather_cfg = (config or {}).get("weather") or {}
    if not isinstance(weather_cfg, dict):
        weather_cfg = {}
    location = resolve_location(weather_cfg)
    if location is None:
        with _weather_lock:
            _weather_status = "unavailable"
        return None

    with _weather_lock:
        snap = _weather_snap
    if snap is None:
        try:
            snap = DiskForecastStore().load(location, max_age_s=6 * 3600)
            if snap is not None:
                with _weather_lock:
                    _weather_snap = snap
                    _weather_status = "ready"
        except Exception:
            LOG.debug("TV Guide weather cache load failed", exc_info=True)

    now = time.time()
    age = now - float(getattr(snap, "fetched_at", 0) or 0) if snap else 1e9
    need = force_refresh or snap is None or age > WEATHER_REFRESH_MIN_S
    with _weather_lock:
        fetching = _weather_fetching
        last_try = _weather_last_fetch_at
        if snap is not None:
            _weather_status = "ready"
        elif fetching:
            _weather_status = "fetching"
        else:
            _weather_status = "unavailable"
    if need and not fetching and now - last_try >= WEATHER_REFRESH_MIN_S:
        with _weather_lock:
            _weather_last_fetch_at = now
            _weather_fetching = True
            if snap is None:
                _weather_status = "fetching"

        def _worker() -> None:
            global _weather_snap, _weather_fetching, _weather_status
            try:
                client = build_forecast_client()
                fresh = client.fetch(location)
                DiskForecastStore().save(location, fresh)
                with _weather_lock:
                    _weather_snap = fresh
                    _weather_status = "ready"
            except Exception:
                LOG.debug("TV Guide weather fetch failed", exc_info=True)
                with _weather_lock:
                    if _weather_snap is None:
                        _weather_status = "unavailable"
            finally:
                with _weather_lock:
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
    rows: list[dict[str, Any]] | int,
    *,
    avoid: int | None = None,
    rng: random.Random | None = None,
) -> int:
    """Pick a random program row for the top preview (skip section headers)."""
    if isinstance(rows, int):
        # Legacy: plain count with no section headers.
        row_count = rows
        choices = list(range(row_count)) if row_count > 0 else []
    else:
        choices = guide_program_indices(rows)
    if not choices:
        return 0
    if len(choices) == 1:
        return choices[0]
    chooser = rng if rng is not None else random
    filtered = [i for i in choices if i != avoid] if avoid is not None else choices
    if not filtered:
        filtered = choices
    return int(chooser.choice(filtered))


def pick_random_scroll_offset(
    rows: list[dict[str, Any]] | int,
    *,
    rng: random.Random | None = None,
) -> int:
    """Pick a random list start index when opening the guide (any row, incl. sections)."""
    if isinstance(rows, int):
        n = max(0, int(rows))
    else:
        n = len(rows)
    if n <= 1:
        return 0
    chooser = rng if rng is not None else random
    return int(chooser.randrange(n))


def guide_list_cycle_ms() -> int:
    """Dwell + scroll duration for one virtual page advance."""
    return int(PAGE_DWELL_MS) + int(PAGE_SCROLL_MS)


# Approximate top-panel slot length for virtual-channel resume (real slots vary with blurbs).
GUIDE_TOP_SLOT_APPROX_MS = TOP_SLOT_PREVIEW_MS


def next_guide_scroll_offset(
    cur: int,
    rows: list[dict[str, Any]],
    page: int,
) -> tuple[int, int]:
    """Next list offset and row-delta after one page advance (section-aware)."""
    n = len(rows)
    page = max(1, int(page))
    if n <= 0:
        return 0, 0
    if n <= page:
        return 0, 0
    cur = int(cur) % n
    nxt = cur + page
    if nxt < n:
        for i in range(cur + 1, min(nxt + 1, n)):
            if (rows[i].get("kind") or "") == "section":
                nxt = i
                break
    if nxt >= n:
        return 0, page
    return int(nxt), max(1, int(nxt) - cur)


def guide_scroll_offset_after_steps(
    origin: int,
    steps: int,
    rows: list[dict[str, Any]],
    page: int,
) -> int:
    """Apply *steps* page advances from *origin* (cycle-aware for long absences)."""
    n = len(rows)
    page = max(1, int(page))
    if n <= 0 or n <= page:
        return 0
    cur = int(origin) % n
    steps = max(0, int(steps))
    if steps == 0:
        return cur
    seen: dict[int, int] = {cur: 0}
    seq = [cur]
    for step in range(steps):
        cur, _delta = next_guide_scroll_offset(cur, rows, page)
        if cur in seen:
            cycle_start = seen[cur]
            cycle = seq[cycle_start:]
            remaining = steps - (step + 1)
            if not cycle:
                return cur
            return cycle[remaining % len(cycle)]
        seen[cur] = len(seq)
        seq.append(cur)
    return cur


def resolve_virtual_guide_list(
    *,
    origin_offset: int,
    elapsed_ms: float,
    rows: list[dict[str, Any]],
    page: int,
) -> tuple[int, str, float, int, int]:
    """Map wall-clock elapsed time to list scroll state.

    Returns ``(scroll_offset, phase, scroll_t, scroll_to, delta_rows)`` where
    ``scroll_t`` is 0..1 during ``scroll`` (else 0).
    """
    cycle = float(guide_list_cycle_ms())
    elapsed = max(0.0, float(elapsed_ms))
    if cycle <= 0:
        return int(origin_offset), "dwell", 0.0, int(origin_offset), 0
    n = len(rows)
    page = max(1, int(page))
    if n <= 0 or n <= page:
        return 0, "dwell", 0.0, 0, 0

    steps = int(elapsed // cycle)
    phase_ms = elapsed - steps * cycle
    cur = guide_scroll_offset_after_steps(origin_offset, steps, rows, page)
    if phase_ms < float(PAGE_DWELL_MS):
        return cur, "dwell", 0.0, cur, 0
    to, delta = next_guide_scroll_offset(cur, rows, page)
    scroll_ms = float(PAGE_SCROLL_MS) or 1.0
    t = max(0.0, min(1.0, (phase_ms - float(PAGE_DWELL_MS)) / scroll_ms))
    return cur, "scroll", t, to, delta


def resolve_virtual_guide_top(
    *,
    elapsed_ms: float,
    rows: list[dict[str, Any]],
    seed: int,
) -> tuple[int, str, int, float]:
    """Approximate top-panel slot from elapsed time.

    Returns ``(slot, mode, preview_idx, phase_ms_into_slot)``.
    """
    slot_ms = float(GUIDE_TOP_SLOT_APPROX_MS) or 1.0
    elapsed = max(0.0, float(elapsed_ms))
    absolute = int(elapsed // slot_ms)
    phase = elapsed - absolute * slot_ms
    mode = resolve_top_mode(absolute)
    preview_idx = 0
    if mode == "preview" and rows:
        rng = random.Random((int(seed) * 1_000_003 + absolute) & 0xFFFFFFFF)
        preview_idx = pick_random_preview_idx(rows, rng=rng)
    return absolute, mode, preview_idx, phase


def resolve_top_slot(
    slot: int,
    *,
    row_count: int | None = None,
    rows: list[dict[str, Any]] | None = None,
    avoid: int | None = None,
    rng: random.Random | None = None,
) -> tuple[str, int]:
    """Return ``(mode, preview_idx)`` — preview picks are randomized."""
    mode = resolve_top_mode(slot)
    if mode != "preview":
        return mode, 0
    if rows is not None:
        return mode, pick_random_preview_idx(rows, avoid=avoid, rng=rng)
    return mode, pick_random_preview_idx(int(row_count or 0), avoid=avoid, rng=rng)


def wrap_text_lines(
    text: str,
    font: pygame.font.Font,
    max_w: int,
) -> list[str]:
    """Word-wrap *text* into lines that fit *max_w*."""
    words = (text or "").split()
    if not words:
        return []
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if font.size(trial)[0] <= max_w:
            line = trial
            continue
        if line:
            lines.append(line)
        if font.size(word)[0] > max_w:
            chunk = word
            while chunk:
                fit = chunk
                while fit and font.size(fit)[0] > max_w:
                    fit = fit[:-1]
                if not fit:
                    break
                lines.append(fit)
                chunk = chunk[len(fit) :]
            line = ""
        else:
            line = word
    if line:
        lines.append(line)
    return lines


def _blurb_line_stride(font: pygame.font.Font) -> int:
    return max(1, font.get_height() + 2)


def blurb_scroll_offset_px(
    elapsed_ms: int,
    *,
    content_h: int,
    viewport_h: int,
) -> float:
    """Pixel offset for vertical blurb scroll (0 = top)."""
    if content_h <= viewport_h:
        return 0.0
    travel = float(content_h - viewport_h)
    if elapsed_ms <= BLURB_HOLD_MS:
        return 0.0
    t = elapsed_ms - BLURB_HOLD_MS
    scroll_ms = max(1, int(travel / BLURB_SCROLL_PX_PER_S * 1000.0))
    if t >= scroll_ms:
        return travel
    return (t / float(scroll_ms)) * travel


def preview_blurb_layout(
    row: dict[str, Any] | None,
    *,
    fonts: dict[str, pygame.font.Font],
    screen_w: int,
    screen_h: int,
) -> tuple[str, list[str], int, int]:
    """Return ``(blurb, lines, viewport_h, content_h)`` for the top preview."""
    if not row:
        return "", [], 0, 0
    blurb = str(row.get("blurb") or "").strip()
    if not blurb:
        return "", [], 0, 0
    font_sm = fonts.get("sm") or fonts["md"]
    font_md = fonts.get("md") or fonts["sm"]
    top_h = max(120, screen_h // 2)
    panel = pygame.Rect(16, 12, screen_w - 32, top_h - 16)
    pad = 14
    thumb_h = panel.h - pad * 2
    thumb_w = max(1, int(thumb_h * 4 / 3))
    if thumb_w > panel.w // 2:
        thumb_w = max(1, panel.w // 2 - pad)
    text_x = panel.x + pad + thumb_w + 16
    max_w = max(40, panel.right - pad - text_x)
    # CH + name + meta lines reserved above the blurb viewport.
    reserved = (
        font_md.get_height()
        + 6
        + font_md.get_height()
        + 4
        + font_sm.get_height()
        + 6
    )
    viewport_h = max(1, panel.h - pad * 2 - reserved)
    lines = wrap_text_lines(blurb, font_sm, max_w)
    content_h = len(lines) * _blurb_line_stride(font_sm)
    return blurb, lines, viewport_h, content_h


def top_slot_duration_ms(
    *,
    top_mode: str,
    rows: list[dict[str, Any]],
    preview_idx: int,
    fonts: dict[str, pygame.font.Font],
    screen_w: int,
    screen_h: int,
) -> int:
    """How long the current top slot should linger before advancing."""
    if top_mode != "preview" or not rows:
        return TOP_SLOT_MS
    row = rows[int(preview_idx) % len(rows)]
    blurb, _lines, viewport_h, content_h = preview_blurb_layout(
        row, fonts=fonts, screen_w=screen_w, screen_h=screen_h
    )
    if not blurb:
        return TOP_SLOT_PREVIEW_MS
    if content_h <= viewport_h:
        # Both sentences visible without scrolling — linger to read them.
        return max(TOP_SLOT_PREVIEW_MS, BLURB_HOLD_MS + BLURB_END_HOLD_MS)
    travel = content_h - viewport_h
    scroll_ms = max(1, int(travel / BLURB_SCROLL_PX_PER_S * 1000.0))
    # Hold at top → full scroll → brief end pause (+ tail so we never cut off).
    return max(
        TOP_SLOT_PREVIEW_MS,
        BLURB_HOLD_MS + scroll_ms + BLURB_END_HOLD_MS + BLURB_SCROLL_TAIL_MS,
    )


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
    weather_status: str | None = None,
    top_slot_at_ms: int = 0,
    blit_marquee: Callable[..., None] | None = None,
) -> int:
    """Draw menu-styled guide. Returns page_size (rows per screen)."""
    sw, sh = screen.get_size()
    screen.fill(C.BG)

    # Prefer smaller title font for longer names in the list.
    font_title = fonts.get("title") or fonts["sm"]
    font_ch = fonts.get("ch") or fonts["md"]
    font_sub = fonts.get("sub") or fonts["sm"]

    # Half-screen top when the active preview has a description blurb.
    preview_has_blurb = False
    if top_mode == "preview" and rows:
        idx = int(preview_idx) % len(rows)
        blurb = str((rows[idx] or {}).get("blurb") or "").strip()
        preview_has_blurb = bool(blurb)
    top_h = max(120, sh // 2) if preview_has_blurb else max(120, sh // 3)
    page_size = guide_page_size(
        screen_h=sh, top_h=top_h, font_title=font_title, font_sub=font_sub
    )
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
            elapsed_ms=max(0, int(now_ms) - int(top_slot_at_ms or 0)),
            blit_marquee=blit_marquee,
        )
    elif top_mode == "weather":
        _draw_top_weather(
            screen,
            weather=weather,
            area=panel,
            fonts=fonts,
            status=weather_status or guide_weather_status(),
        )
    else:
        _draw_top_branding(screen, area=panel, fonts=fonts, now_ms=now_ms)

    list_top = top_h + 2
    header_h = guide_header_h(font_sub=font_sub)
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
    # Pixel scroll; when past the end, wrap indices so wrap-anim isn't blank.
    base_y = int(scroll_offset) * stride + float(scroll_pixel)
    prev_clip = screen.get_clip()
    screen.set_clip(pygame.Rect(0, body_top, sw, max(1, body_bottom - body_top)))

    wrap = n > page_size
    first_f = base_y / float(stride)
    first_i = int(math.floor(first_f))
    sub = (first_f - first_i) * stride
    slots = page_size + 3
    for i in range(slots):
        raw_idx = first_i + i
        if wrap:
            idx = raw_idx % n
        else:
            if raw_idx < 0 or raw_idx >= n:
                continue
            idx = raw_idx
        y = body_top + i * stride - sub
        if y + row_h < body_top or y > body_bottom:
            continue
        row = rows[idx]
        if (row.get("kind") or "") == "section":
            # Section divider — full-width label, no channel card.
            label = str(row.get("name") or "").upper()
            bar = pygame.Rect(row_left, int(y) + 8, sw - 60, max(28, row_h - 16))
            pygame.draw.rect(screen, C.BG_HEADER, bar, border_radius=6)
            pygame.draw.line(
                screen, C.CYAN, (bar.x + 10, bar.bottom - 1), (bar.right - 10, bar.bottom - 1), 1
            )
            title_surf = font_title.render(label, True, C.CYAN)
            screen.blit(
                title_surf,
                (
                    title_x,
                    bar.y + (bar.height - title_surf.get_height()) // 2,
                ),
            )
            continue

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
        subtitle = str(row.get("meta_subtitle") or "").strip()
        if not subtitle:
            years = str(row.get("years") or "").strip()
            network = str(row.get("network") or "").strip()
            parts = []
            if years:
                parts.append(years)
            if network:
                parts.append(network)
            subtitle = " - ".join(parts) if parts else (
                "Movie" if kind == "movie" else "Show"
            )
        max_w = max(20, rect.right - 14 - title_x)
        sub_surf = font_sub.render(subtitle, True, C.DIM)
        title_h = font_title.get_height()
        text_h = title_h + 2 + sub_surf.get_height()
        text_y = rect.y + (rect.height - text_h) // 2
        if blit_marquee is not None:
            blit_marquee(
                title,
                font_title,
                C.WHITE,
                title_x,
                text_y,
                max_w,
                key=("guide", idx, title),
                active=True,
            )
        else:
            title_surf = font_title.render(title, True, C.WHITE)
            if title_surf.get_width() > max_w:
                # Tests / no-marquee path: hard-clip, no ellipsis.
                clipped = title
                while clipped and font_title.size(clipped)[0] > max_w:
                    clipped = clipped[:-1]
                title_surf = font_title.render(clipped, True, C.WHITE)
            screen.blit(title_surf, (title_x, text_y))
        screen.blit(sub_surf, (title_x, text_y + title_h + 2))

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
    elapsed_ms: int = 0,
    blit_marquee: Callable[..., None] | None = None,
) -> None:
    pad = 14
    if not rows:
        msg = fonts["md"].render("No programs", True, C.DIM)
        screen.blit(msg, msg.get_rect(center=area.center))
        return
    idx = preview_idx % len(rows)
    row = rows[idx]
    if not is_guide_program_row(row):
        # Skip section headers — fall back to first program row.
        for candidate in rows:
            if is_guide_program_row(candidate):
                row = candidate
                break
        else:
            msg = fonts["md"].render("No programs", True, C.DIM)
            screen.blit(msg, msg.get_rect(center=area.center))
            return

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
    name_h = fonts["md"].get_height()
    if y + name_h <= text_bottom:
        if blit_marquee is not None:
            blit_marquee(
                name,
                fonts["md"],
                C.BRIGHT,
                text_x,
                y,
                max_w,
                key=("guide-top", name),
                active=True,
            )
        else:
            name_surf = fonts["md"].render(name, True, C.BRIGHT)
            if name_surf.get_width() > max_w:
                clipped = name
                while clipped and fonts["md"].size(clipped)[0] > max_w:
                    clipped = clipped[:-1]
                name_surf = fonts["md"].render(clipped, True, C.BRIGHT)
            screen.blit(name_surf, (text_x, y))
        y += name_h + 4

    kind = "Movie" if row.get("kind") == "movie" else "Show"
    years = str(row.get("years") or "").strip()
    network = str(row.get("network") or "").strip()
    meta_bits = []
    if years:
        meta_bits.append(years)
    if network:
        meta_bits.append(network)
    meta_line = " - ".join(meta_bits) if meta_bits else kind
    kind_surf = fonts["sm"].render(meta_line, True, C.DIM)
    if y + kind_surf.get_height() <= text_bottom:
        screen.blit(kind_surf, (text_x, y))
        y += kind_surf.get_height() + 6

    blurb = str(row.get("blurb") or "").strip()
    if blurb and y < text_bottom:
        font = fonts["sm"]
        lines = wrap_text_lines(blurb, font, max_w)
        if not lines:
            return
        stride = _blurb_line_stride(font)
        content_h = len(lines) * stride
        viewport_h = max(1, text_bottom - y)
        offset = blurb_scroll_offset_px(
            int(elapsed_ms),
            content_h=content_h,
            viewport_h=viewport_h,
        )
        clip = pygame.Rect(text_x, y, max_w, viewport_h)
        prev = screen.get_clip()
        screen.set_clip(clip)
        draw_y = y - int(offset)
        for line in lines:
            if draw_y + stride < y:
                draw_y += stride
                continue
            if draw_y > text_bottom:
                break
            surf = font.render(line, True, C.WHITE)
            screen.blit(surf, (text_x, draw_y))
            draw_y += stride
        screen.set_clip(prev)


def _draw_top_weather(
    screen: pygame.Surface,
    *,
    weather: CurrentConditions | None,
    area: pygame.Rect,
    fonts: dict[str, pygame.font.Font],
    status: str = "idle",
) -> None:
    pad = 14
    title = fonts["sm"].render("LOCAL WEATHER", True, C.CYAN)
    screen.blit(title, (area.x + pad, area.y + pad))

    if weather is None:
        if status == "fetching":
            label = "Fetching..."
        else:
            label = "Unavailable"
        msg = fonts["md"].render(label, True, C.DIM)
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
    pulse = 80 + int(40 * abs(((now_ms // 40) % 100) - 50) / 50)
    line_y = title_rect.bottom + 4
    pygame.draw.line(
        screen,
        (pulse // 3, pulse, pulse // 2),
        (area.x + 48, line_y),
        (area.right - 48, line_y),
        2,
    )
    screen.blit(sub, sub.get_rect(centerx=area.centerx, top=line_y + 8))
