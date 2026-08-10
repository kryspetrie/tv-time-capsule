"""Standard weather page layouts (CRT-sized typography)."""

from __future__ import annotations

import pygame

from ..models import WeatherSnapshot
from . import theme as T
from .icons import load_icon
from .text import (
    ascii_safe,
    fit_condition,
    rain_amount_label,
    rain_chance_label,
    rain_summary,
    shorten_place_name,
)


def _fmt_temp(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{int(round(v))}F"


def _text_width(font: pygame.font.Font, text: str) -> int:
    """Prefer rendered surface width (VCR/freetype get_rect can under-measure)."""
    try:
        return font.render(text, True, (255, 255, 255)).get_width()
    except Exception:
        if hasattr(font, "size"):
            return int(font.size(text)[0])
        return 0


def _wrap(
    font: pygame.font.Font, text: str, max_w: int, *, max_lines: int = 6
) -> list[str]:
    words = ascii_safe(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    line = ""
    for w in words:
        trial = f"{line} {w}".strip()
        if _text_width(font, trial) <= max_w:
            line = trial
            continue
        if line:
            lines.append(line)
            if len(lines) >= max_lines:
                return lines
        line = w
    if line and len(lines) < max_lines:
        lines.append(line)
    return lines


def _condition_fits(
    font: pygame.font.Font,
    text: str,
    max_w: int,
    *,
    max_lines: int = 1,
) -> bool:
    """True when ``text`` wraps cleanly into ``max_lines`` within ``max_w``."""
    if max_w <= 0 or not text:
        return False
    for word in text.split():
        if _text_width(font, word) > max_w:
            return False
    # Probe one extra line — overflow means it does not fit.
    lines = _wrap(font, text, max_w, max_lines=max_lines + 1)
    if len(lines) > max_lines:
        return False
    # If wrap hit max_lines early and leftover words remain, _wrap truncates;
    # detect by comparing joined wrap to original word count.
    wrapped_words = sum(len(line.split()) for line in lines)
    return wrapped_words >= len(text.split())


def _fit_condition_text(
    font: pygame.font.Font,
    text: str,
    max_w: int,
    *,
    max_lines: int = 1,
    max_len: int | None = None,
) -> str:
    return fit_condition(
        text,
        max_len=max_len,
        fits=lambda s: _condition_fits(font, s, max_w, max_lines=max_lines),
    )


def _rain_line_font(
    fonts: dict[str, pygame.font.Font], line: str, max_w: int
) -> pygame.font.Font:
    """Prefer md; drop to sm when the line is wider than the column."""
    if _text_width(fonts["md"], line) <= max_w:
        return fonts["md"]
    return fonts["sm"]


def _rain_block_height(
    fonts: dict[str, pygame.font.Font],
    rain: str,
    *,
    max_w: int,
) -> int:
    """Height reserved for rain — must match :func:`_blit_rain_lines` fonts."""
    lines = [ln for ln in (rain or "").splitlines() if ln.strip()]
    if not lines:
        return 0
    h = 0
    for line in lines:
        font = _rain_line_font(fonts, line, max_w)
        h += font.get_height() + 2
    return h + 4


def _blit_rain_lines(
    screen: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    rain: str,
    *,
    centerx: int,
    top: int,
    max_w: int,
    bottom: int,
) -> int:
    """Draw ``45%`` / ``.17in`` on consecutive lines. Returns Y after the block.

    Both lines are drawn when they fit; if not, shrink to ``sm`` before dropping
    the inches line. Never split a day's chance onto one column and its inches
    onto the next.
    """
    lines = [ln for ln in (rain or "").splitlines() if ln.strip()]
    if not lines:
        return top

    def _height(use_lines: list[str], *, force_sm: bool) -> int:
        total = 0
        for line in use_lines:
            font = fonts["sm"] if force_sm else _rain_line_font(fonts, line, max_w)
            total += font.get_height() + 2
        return total

    force_sm = False
    need = _height(lines, force_sm=False)
    if top + need > bottom and len(lines) > 1:
        # Prefer two compact lines over collapsing chance + inches onto one.
        need_sm = _height(lines, force_sm=True)
        if top + need_sm <= bottom:
            force_sm = True
            need = need_sm
        else:
            lines = lines[:1]
            need = _height(lines, force_sm=False)
            if top + need > bottom:
                force_sm = True
                need = _height(lines, force_sm=True)
    if top + need > bottom:
        force_sm = True
        need = _height(lines, force_sm=True)
        if top + need > bottom:
            return top

    y = top
    for line in lines:
        rain_font = fonts["sm"] if force_sm else _rain_line_font(fonts, line, max_w)
        p = rain_font.render(ascii_safe(line), True, T.CYAN)
        screen.blit(p, p.get_rect(centerx=centerx, top=y))
        y += p.get_height() + 2
    return y + 4


def draw_chrome(
    screen: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    *,
    page_title: str,
) -> int:
    """Page title only (clock/logo/location live in the lower-thirds bar)."""
    screen.fill(T.BG)
    title = fonts["lg"].render(ascii_safe(page_title), True, T.TEXT)
    screen.blit(title, (20, 14))
    return 14 + title.get_height() + 12


def draw_current(
    screen: pygame.Surface,
    snap: WeatherSnapshot,
    fonts: dict[str, pygame.font.Font],
    *,
    content_bottom: int,
) -> None:
    top = draw_chrome(screen, fonts, page_title="Current")
    sw, _sh = screen.get_size()
    cur = snap.current
    if cur is None:
        msg = fonts["lg"].render("NO DATA", True, T.TEXT_DIM)
        screen.blit(msg, msg.get_rect(center=(sw // 2, (top + content_bottom) // 2)))
        return

    icon_sz = max(96, min(150, (content_bottom - top) // 3))
    icon = load_icon(icon_sz, cur.icon_id, icon_url=cur.icon_url or None)
    left = 24
    screen.blit(icon, (left, top))

    temp = fonts["xxl"].render(_fmt_temp(cur.temperature_f), True, T.TEXT)
    tx = left + icon_sz + 20
    screen.blit(temp, (tx, top))
    cond_w = max(80, sw - tx - 20)
    cond_text = _fit_condition_text(
        fonts["md"], cur.condition_text or "-", cond_w, max_lines=1, max_len=40
    )
    cond = fonts["md"].render(cond_text, True, T.CYAN)
    screen.blit(cond, (tx, top + temp.get_height() - 4))

    stats_top = top + max(icon_sz, temp.get_height() + cond.get_height()) + 12
    # Keep chance + accumulation as sibling columns (not a multiline value that
    # can visually spill into the next cell).
    rain_pct = rain_chance_label(cur.precip_pct)
    rain_amt = rain_amount_label(cur.precip_in)
    cells: list[tuple[str, str]] = [
        ("FEELS", _fmt_temp(cur.feels_like_f)),
        (
            "HUMIDITY",
            f"{int(cur.humidity_pct)}%" if cur.humidity_pct is not None else "--",
        ),
        (
            "WIND",
            (
                f"{cur.wind_mph:.0f} mph {cur.wind_dir}".strip()
                if cur.wind_mph is not None
                else (cur.wind_dir or "--")
            ),
        ),
    ]
    if rain_pct:
        cells.append(("RAIN", rain_pct))
    if rain_amt:
        cells.append(("ACCUM", rain_amt))
    cells.extend(
        [
            (
                "GUSTS",
                f"{cur.wind_gust_mph:.0f} mph"
                if cur.wind_gust_mph is not None
                else "--",
            ),
            ("DEWPOINT", _fmt_temp(cur.dewpoint_f)),
            (
                "PRESSURE",
                f"{cur.pressure_inhg:.2f} in"
                if cur.pressure_inhg is not None
                else "--",
            ),
            (
                "VISIBILITY",
                f"{cur.visibility_mi:.0f} mi"
                if cur.visibility_mi is not None
                else "--",
            ),
            ("SUNRISE", cur.sunrise or "--"),
            ("SUNSET", cur.sunset or "--"),
        ]
    )

    cols = 3
    gap = 12
    cell_w = (sw - 48 - gap * (cols - 1)) // cols
    cell_h = max(52, fonts["sm"].get_linesize() + fonts["md"].get_linesize() + 12)
    for i, (label, value) in enumerate(cells):
        col = i % cols
        row = i // cols
        x = 24 + col * (cell_w + gap)
        y = stats_top + row * (cell_h + 8)
        if y + cell_h > content_bottom - 8:
            break
        pygame.draw.rect(screen, T.BG_PANEL, (x, y, cell_w, cell_h), border_radius=6)
        clip = screen.get_clip()
        screen.set_clip(pygame.Rect(x + 4, y + 4, cell_w - 8, cell_h - 8))
        lab = fonts["sm"].render(ascii_safe(label), True, T.TEXT_DIM)
        val = fonts["md"].render(ascii_safe(value), True, T.TEXT)
        screen.blit(lab, (x + 10, y + 6))
        screen.blit(val, (x + 10, y + 6 + lab.get_height()))
        screen.set_clip(clip)

    narr = ascii_safe((cur.narrative or "").strip())
    if narr:
        rows_used = (len(cells) + cols - 1) // cols
        box_top = stats_top + rows_used * (cell_h + 8) + 8
        box_h = content_bottom - box_top - 8
        if box_h > 60:
            pygame.draw.rect(
                screen, T.BG_PANEL, (24, box_top, sw - 48, box_h), border_radius=6
            )
            head = fonts["sm"].render("LATER TODAY", True, T.ACCENT)
            screen.blit(head, (36, box_top + 8))
            y = box_top + 8 + head.get_height() + 4
            line_h = fonts["md"].get_linesize() + 2
            max_lines = max(2, (box_h - 28) // line_h)
            for line in _wrap(fonts["md"], narr, sw - 72, max_lines=max_lines):
                surf = fonts["md"].render(line, True, T.TEXT)
                screen.blit(surf, (36, y))
                y += surf.get_height() + 2


HOURS_PER_PAGE = 4


def draw_hourly(
    screen: pygame.Surface,
    snap: WeatherSnapshot,
    fonts: dict[str, pygame.font.Font],
    *,
    content_bottom: int,
    page_index: int = 0,
    hours_per_page: int = HOURS_PER_PAGE,
) -> None:
    hours_all = list(snap.hourly)
    total_pages = max(1, (len(hours_all) + hours_per_page - 1) // hours_per_page) if hours_all else 1
    page_index = max(0, min(page_index, total_pages - 1))
    start = page_index * hours_per_page
    hours = hours_all[start : start + hours_per_page]
    title = (
        f"Hourly ({page_index + 1}/{total_pages})"
        if total_pages > 1
        else "Hourly"
    )
    top = draw_chrome(screen, fonts, page_title=title)
    sw = screen.get_width()
    if not hours:
        msg = fonts["lg"].render("NO HOURLY DATA", True, T.TEXT_DIM)
        screen.blit(msg, msg.get_rect(center=(sw // 2, (top + content_bottom) // 2)))
        return

    n = len(hours)
    pad = 18
    gap = 10
    usable = sw - pad * 2 - gap * (n - 1)
    panel_w = max(120, usable // n)
    panel_h = content_bottom - top - 8
    icon_sz = min(72, panel_w - 24)

    for i, h in enumerate(hours):
        x = pad + i * (panel_w + gap)
        pygame.draw.rect(
            screen, T.BG_PANEL, (x, top, panel_w, panel_h), border_radius=6
        )
        inner_w = panel_w - 16
        clip = screen.get_clip()
        screen.set_clip(pygame.Rect(x + 4, top + 4, panel_w - 8, panel_h - 8))

        t = fonts["lg"].render(ascii_safe(h.time_label), True, T.TEXT)
        screen.blit(t, t.get_rect(centerx=x + panel_w // 2, top=top + 12))
        ic = load_icon(icon_sz, h.icon_id, icon_url=h.icon_url or None)
        screen.blit(ic, ic.get_rect(centerx=x + panel_w // 2, top=top + 52))
        temp = fonts["xl"].render(_fmt_temp(h.temperature_f), True, T.ACCENT)
        y = top + 56 + icon_sz
        screen.blit(temp, temp.get_rect(centerx=x + panel_w // 2, top=y))
        y += temp.get_height() + 8

        cond = _fit_condition_text(
            fonts["md"], h.condition_text, inner_w, max_lines=2, max_len=28
        )
        if cond:
            for line in _wrap(fonts["md"], cond, inner_w, max_lines=2):
                s = fonts["md"].render(line, True, T.TEXT)
                screen.blit(s, s.get_rect(centerx=x + panel_w // 2, top=y))
                y += s.get_height() + 2
            y += 8

        rain = rain_summary(h.precip_pct, h.precip_in)
        if rain:
            y = _blit_rain_lines(
                screen,
                fonts,
                rain,
                centerx=x + panel_w // 2,
                top=y,
                max_w=inner_w,
                bottom=top + panel_h - 8,
            )

        details: list[str] = []
        if h.feels_like_f is not None and (
            h.temperature_f is None
            or abs(h.feels_like_f - h.temperature_f) >= 2
        ):
            details.append(f"Feels {_fmt_temp(h.feels_like_f)}")
        if h.wind_mph is not None:
            mph = f"{h.wind_mph:.0f}"
            if len(mph) >= 2 or not h.wind_dir:
                details.append(f"Wnd {mph}")
            else:
                details.append(f"Wnd {mph} {h.wind_dir}".strip())
        elif h.wind_dir:
            details.append(h.wind_dir)
        if h.humidity_pct is not None:
            details.append(f"Hum {int(round(h.humidity_pct))}%")
        for line in details:
            if y + fonts["sm"].get_linesize() > top + panel_h - 8:
                break
            s = fonts["sm"].render(ascii_safe(line), True, T.TEXT_DIM)
            screen.blit(s, s.get_rect(centerx=x + panel_w // 2, top=y))
            y += s.get_height() + 4

        screen.set_clip(clip)


def draw_daily(
    screen: pygame.Surface,
    snap: WeatherSnapshot,
    fonts: dict[str, pygame.font.Font],
    *,
    content_bottom: int,
) -> None:
    top = draw_chrome(screen, fonts, page_title="5-Day")
    sw = screen.get_width()
    days = snap.daily[:5] or []
    if not days:
        msg = fonts["lg"].render("NO DAILY DATA", True, T.TEXT_DIM)
        screen.blit(msg, msg.get_rect(center=(sw // 2, (top + content_bottom) // 2)))
        return
    n = len(days)
    pad = 16
    gap = 8
    panel_w = max(100, (sw - pad * 2 - gap * (n - 1)) // n)
    panel_h = content_bottom - top - 8
    icon_sz = min(72, panel_w - 16)
    for i, d in enumerate(days):
        x = pad + i * (panel_w + gap)
        pygame.draw.rect(
            screen, T.BG_PANEL, (x, top, panel_w, panel_h), border_radius=6
        )
        # Clip to the full panel (not panel_h-8) so the bottom rain band is not cut.
        clip = screen.get_clip()
        screen.set_clip(pygame.Rect(x + 2, top + 2, panel_w - 4, panel_h - 4))
        centerx = x + panel_w // 2
        inner_w = panel_w - 14
        panel_bottom = top + panel_h - 6

        # Only show inches when there is also a chance — orphan `.17in` under
        # one day next to `40%` under the next reads as a layout bug.
        # Two lines: chance above inches (``54%\n.17in``), pinned to panel bottom.
        chance = rain_chance_label(d.precip_pct)
        amt = rain_amount_label(d.precip_in) if chance else ""
        rain = f"{chance}\n{amt}" if chance and amt else chance
        rain_h = _rain_block_height(fonts, rain, max_w=inner_w) if rain else 0
        rain_top = panel_bottom - rain_h + 2 if rain_h else panel_bottom
        content_bottom_y = rain_top - 2

        wd = fonts["lg"].render(d.weekday, True, T.CYAN)
        screen.blit(wd, wd.get_rect(centerx=centerx, top=top + 12))
        ic = load_icon(icon_sz, d.icon_id, icon_url=d.icon_url or None)
        screen.blit(ic, ic.get_rect(centerx=centerx, top=top + 52))
        y = top + 60 + icon_sz
        hi = fonts["lg"].render(_fmt_temp(d.high_f), True, T.ACCENT)
        lo = fonts["md"].render(_fmt_temp(d.low_f), True, T.TEXT_DIM)
        screen.blit(hi, hi.get_rect(centerx=centerx, top=y))
        y += hi.get_height()
        screen.blit(lo, lo.get_rect(centerx=centerx, top=y))
        y += lo.get_height() + 8

        cond_room = content_bottom_y - y
        md_h = fonts["md"].get_linesize() + 2
        cond_lines = 2 if cond_room >= md_h * 2 + 4 else 1
        cond = _fit_condition_text(
            fonts["md"],
            d.condition_text,
            inner_w,
            max_lines=cond_lines,
            max_len=28,
        )
        if cond and cond_room >= md_h:
            for line in _wrap(fonts["md"], cond, inner_w, max_lines=cond_lines):
                if y + fonts["md"].get_linesize() > content_bottom_y:
                    break
                s = fonts["md"].render(line, True, T.TEXT)
                screen.blit(s, s.get_rect(centerx=centerx, top=y))
                y += s.get_height() + 2

        if rain and rain_h:
            _blit_rain_lines(
                screen,
                fonts,
                rain,
                centerx=centerx,
                top=rain_top,
                max_w=inner_w,
                bottom=panel_bottom,
            )
        screen.set_clip(clip)


CITIES_PER_PAGE = 4


def draw_regional(
    screen: pygame.Surface,
    snap: WeatherSnapshot,
    fonts: dict[str, pygame.font.Font],
    *,
    content_bottom: int,
    page_index: int = 0,
    cities_per_page: int = CITIES_PER_PAGE,
) -> None:
    all_cities = list(snap.regional)
    total_pages = (
        max(1, (len(all_cities) + cities_per_page - 1) // cities_per_page)
        if all_cities
        else 1
    )
    page_index = max(0, min(page_index, total_pages - 1))
    start = page_index * cities_per_page
    cities = all_cities[start : start + cities_per_page]
    title = (
        f"Regional ({page_index + 1}/{total_pages})"
        if total_pages > 1
        else "Regional"
    )
    top = draw_chrome(screen, fonts, page_title=title)
    sw = screen.get_width()
    if not cities:
        msg = fonts["lg"].render("NO REGIONAL DATA", True, T.TEXT_DIM)
        screen.blit(msg, msg.get_rect(center=(sw // 2, (top + content_bottom) // 2)))
        return
    cols = 2
    rows = (len(cities) + cols - 1) // cols
    gap = 12
    cell_w = (sw - 40 - gap) // cols
    avail_h = content_bottom - top - 8
    cell_h = max(96, (avail_h - gap * (rows - 1)) // max(1, rows))
    icon_sz = min(64, cell_h - 24)
    for i, city in enumerate(cities):
        col = i % cols
        row = i // cols
        x = 20 + col * (cell_w + gap)
        y = top + row * (cell_h + gap)
        if y + cell_h > content_bottom:
            break
        pygame.draw.rect(screen, T.BG_PANEL, (x, y, cell_w, cell_h), border_radius=6)
        clip = screen.get_clip()
        screen.set_clip(pygame.Rect(x + 4, y + 4, cell_w - 8, cell_h - 8))
        ic = load_icon(icon_sz, city.icon_id, icon_url=city.icon_url or None)
        screen.blit(ic, (x + 10, y + 10))
        tx = x + 20 + icon_sz
        text_right = x + cell_w - 10
        text_w = max(40, text_right - tx)
        line_y = y + 8
        cell_bottom = y + cell_h - 8
        sm_h = fonts["sm"].get_linesize() + 2

        # Pack details first so we can reserve vertical room (Hum must stay visible).
        # Do not show distance-from-here — not a classic regional page field.
        detail_bits: list[str] = []
        if city.humidity_pct is not None:
            detail_bits.append(f"Hm {int(round(city.humidity_pct))}%")
        if city.wind_mph is not None:
            dir_abbr = (city.wind_dir or "").replace(" ", "")
            detail_bits.append(f"Wnd {city.wind_mph:.0f}{dir_abbr}")
        elif city.wind_dir:
            detail_bits.append((city.wind_dir or "").replace(" ", ""))
        if city.feels_like_f is not None:
            detail_bits.append(f"Feels {_fmt_temp(city.feels_like_f)}")
        detail_lines: list[str] = []
        if detail_bits:
            joined = " ".join(detail_bits)
            if _text_width(fonts["sm"], joined) <= text_w:
                detail_lines = [joined]
            else:
                # Two compact rows max: Hum/Wind, then Feels.
                row1 = " ".join(detail_bits[:2])
                row2 = " ".join(detail_bits[2:])
                detail_lines = [row1] + ([row2] if row2 else [])
        details_h = len(detail_lines) * sm_h

        place = city.name or ""
        if not _condition_fits(fonts["md"], ascii_safe(place), text_w, max_lines=1):
            approx = max(8, text_w // max(1, fonts["md"].size("M")[0]))
            place = shorten_place_name(place, max_len=approx)
        name = fonts["md"].render(ascii_safe(place), True, T.TEXT)
        screen.blit(name, (tx, line_y))
        line_y += name.get_height() + 2

        temp = fonts["lg"].render(_fmt_temp(city.temperature_f), True, T.ACCENT)
        screen.blit(temp, (tx, line_y))
        line_y += temp.get_height() + 2

        # Condition uses leftover space above reserved details (prefer 1 line).
        cond_bottom = cell_bottom - details_h
        cond_room = cond_bottom - line_y
        md_h = fonts["md"].get_linesize() + 2
        cond_lines = 2 if cond_room >= md_h * 2 + 4 else 1
        cond = _fit_condition_text(
            fonts["md"],
            city.condition_text,
            text_w,
            max_lines=cond_lines,
            max_len=32,
        )
        if cond and line_y + fonts["md"].get_linesize() <= cond_bottom:
            for line in _wrap(fonts["md"], cond, text_w, max_lines=cond_lines):
                if line_y + fonts["md"].get_linesize() > cond_bottom:
                    break
                cs = fonts["md"].render(line, True, T.TEXT_DIM)
                screen.blit(cs, (tx, line_y))
                line_y += cs.get_height() + 2

        # Pin details to the bottom of the cell so Hum never falls off-screen.
        detail_y = cell_bottom - details_h + 2
        if detail_y < line_y:
            detail_y = line_y
        for bit in detail_lines:
            if detail_y + fonts["sm"].get_linesize() > cell_bottom + 2:
                break
            ms = fonts["sm"].render(ascii_safe(bit), True, T.CYAN)
            screen.blit(ms, (tx, detail_y))
            detail_y += ms.get_height() + 2
        screen.set_clip(clip)


def radar_content_box(
    screen_w: int,
    *,
    title_bottom: int,
    content_bottom: int,
) -> pygame.Rect:
    """Panel rect used by the Radar page (shared with once-scale decode)."""
    return pygame.Rect(
        16,
        title_bottom,
        max(1, screen_w - 32),
        max(40, content_bottom - title_bottom - 8),
    )


def draw_radar(
    screen: pygame.Surface,
    fonts: dict[str, pygame.font.Font],
    *,
    content_bottom: int,
    image: pygame.Surface | None,
    credit: str = "",
    loading: bool = False,
) -> None:
    """Full-bleed regional radar loop page."""
    title = "Radar"
    if credit:
        title = f"Radar - {credit}"
    top = draw_chrome(screen, fonts, page_title=title)
    sw = screen.get_width()
    box = radar_content_box(sw, title_bottom=top, content_bottom=content_bottom)
    pygame.draw.rect(screen, T.BG_PANEL, box, border_radius=6)
    if image is None:
        if loading:
            msg = fonts["lg"].render("Loading Radar...", True, T.TEXT_DIM)
            hint = fonts["sm"].render(
                "NWS regional loop", True, T.TEXT_DIM
            )
        else:
            msg = fonts["lg"].render("NO RADAR IMAGE", True, T.TEXT_DIM)
            hint = fonts["sm"].render(
                "NWS regional loop unavailable", True, T.TEXT_DIM
            )
        screen.blit(msg, msg.get_rect(center=box.center))
        screen.blit(
            hint,
            hint.get_rect(centerx=box.centerx, top=box.centery + msg.get_height()),
        )
        return
    iw, ih = image.get_size()
    if iw <= 0 or ih <= 0:
        return
    # Prefer a once-scaled loop from materialize_radar_loop; only re-scale
    # if the canvas size changed since decode.
    scale = min(box.width / iw, box.height / ih)
    size = (max(1, int(iw * scale)), max(1, int(ih * scale)))
    scaled = (
        image
        if size == (iw, ih)
        else pygame.transform.smoothscale(image, size)
    )
    screen.blit(scaled, scaled.get_rect(center=box.center))


def draw_alerts_page(
    screen: pygame.Surface,
    snap: WeatherSnapshot,
    fonts: dict[str, pygame.font.Font],
    *,
    content_bottom: int,
    scroll_y: int = 0,
) -> None:
    top = draw_chrome(screen, fonts, page_title="Alerts")
    sw = screen.get_width()
    y = top - scroll_y
    for a in snap.alerts:
        cat = (a.category or "weather").strip().upper() or "ALERT"
        head = fonts["md"].render(
            ascii_safe(f"[{cat}/{a.severity}] {a.headline}"), True, T.ALERT
        )
        screen.blit(head, (24, y))
        y += head.get_height() + 6
        for line in _wrap(fonts["md"], a.description or "", sw - 48, max_lines=8):
            surf = fonts["md"].render(line, True, T.TEXT)
            screen.blit(surf, (24, y))
            y += surf.get_height() + 2
        y += 16
        if y > content_bottom:
            break
