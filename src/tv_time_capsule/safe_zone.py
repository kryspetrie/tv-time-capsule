"""CRT overscan safe zone — pad outside the fixed 640×480 UI viewport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

UI_W = 640
UI_H = 480

MAX_SAFE_ZONE_PERCENT = 25.0
MAX_SAFE_ZONE_OFFSET = 320


@dataclass(frozen=True)
class SafeZoneMargins:
    """Per-edge padding outside the UI viewport, as % of UI width (L/R) or height (T/B)."""

    top: float = 0.0
    bottom: float = 0.0
    left: float = 0.0
    right: float = 0.0


@dataclass(frozen=True)
class SafeZoneOffset:
    """Pixel shift of the 640×480 UI block within the extended frame (+x = right, +y = down)."""

    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class SafeZoneRect:
    """Axis-aligned rectangle in frame pixel coordinates."""

    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class SafeZoneFrame:
    """Extended display frame: UI viewport is always 640×480, never scaled."""

    canvas_w: int
    canvas_h: int
    ui: SafeZoneRect


def _clamp_percent(value: Any, default: float = 0.0) -> float:
    try:
        pct = float(value)
    except (TypeError, ValueError):
        pct = default
    return max(0.0, min(MAX_SAFE_ZONE_PERCENT, pct))


def parse_safe_zone(raw: Any) -> SafeZoneMargins:
    """Normalize config ``ui.safe_zone`` to margin percentages."""
    if raw is None:
        return SafeZoneMargins()
    if isinstance(raw, (int, float)):
        uniform = _clamp_percent(raw)
        return SafeZoneMargins(uniform, uniform, uniform, uniform)
    if isinstance(raw, dict):
        uniform = raw.get("margin")
        if uniform is None:
            uniform = raw.get("percent")
        if uniform is not None:
            u = _clamp_percent(uniform)
            return SafeZoneMargins(u, u, u, u)
        vertical = raw.get("vertical")
        horizontal = raw.get("horizontal")
        top = raw.get("top", vertical if vertical is not None else 0.0)
        bottom = raw.get("bottom", vertical if vertical is not None else 0.0)
        left = raw.get("left", horizontal if horizontal is not None else 0.0)
        right = raw.get("right", horizontal if horizontal is not None else 0.0)
        return SafeZoneMargins(
            _clamp_percent(top),
            _clamp_percent(bottom),
            _clamp_percent(left),
            _clamp_percent(right),
        )
    return SafeZoneMargins()


def _clamp_offset(value: Any, default: int = 0) -> int:
    try:
        px = int(value)
    except (TypeError, ValueError):
        px = default
    return max(-MAX_SAFE_ZONE_OFFSET, min(MAX_SAFE_ZONE_OFFSET, px))


def parse_safe_zone_offset(raw: Any) -> SafeZoneOffset:
    """Normalize ``offset_x`` / ``offset_y`` from ``ui.safe_zone`` config."""
    if not isinstance(raw, dict):
        return SafeZoneOffset()
    ox = raw.get("offset_x")
    oy = raw.get("offset_y")
    nested = raw.get("offset")
    if isinstance(nested, dict):
        if ox is None:
            ox = nested.get("x")
        if oy is None:
            oy = nested.get("y")
    elif isinstance(nested, (list, tuple)) and len(nested) >= 2:
        if ox is None:
            ox = nested[0]
        if oy is None:
            oy = nested[1]
    return SafeZoneOffset(_clamp_offset(ox), _clamp_offset(oy))


def safe_zone_enabled(margins: SafeZoneMargins) -> bool:
    return any(
        edge > 0.0
        for edge in (margins.top, margins.bottom, margins.left, margins.right)
    )


def safe_zone_margin_pixels(
    margins: SafeZoneMargins,
) -> tuple[int, int, int, int]:
    """Return top, bottom, left, right padding in pixels outside the UI viewport."""
    top = int(UI_H * margins.top / 100.0)
    bottom = int(UI_H * margins.bottom / 100.0)
    left = int(UI_W * margins.left / 100.0)
    right = int(UI_W * margins.right / 100.0)
    return top, bottom, left, right


def safe_zone_canvas_size(margins: SafeZoneMargins) -> tuple[int, int]:
    top, bottom, left, right = safe_zone_margin_pixels(margins)
    return UI_W + left + right, UI_H + top + bottom


def safe_zone_ui_rect(
    margins: SafeZoneMargins,
    offset: SafeZoneOffset,
) -> SafeZoneRect:
    """640×480 UI viewport position inside the extended frame."""
    top, bottom, left, right = safe_zone_margin_pixels(margins)
    canvas_w = UI_W + left + right
    canvas_h = UI_H + top + bottom
    ui_x = left + offset.x
    ui_y = top + offset.y
    ui_x = max(0, min(ui_x, canvas_w - UI_W))
    ui_y = max(0, min(ui_y, canvas_h - UI_H))
    return SafeZoneRect(ui_x, ui_y, UI_W, UI_H)


def safe_zone_frame(
    margins: SafeZoneMargins,
    offset: SafeZoneOffset | None = None,
) -> SafeZoneFrame:
    """Extended frame size plus unscaled UI viewport placement."""
    if offset is None:
        offset = SafeZoneOffset()
    canvas_w, canvas_h = safe_zone_canvas_size(margins)
    ui = safe_zone_ui_rect(margins, offset)
    return SafeZoneFrame(canvas_w, canvas_h, ui)


def safe_zone_rect(
    margins: SafeZoneMargins,
    offset: SafeZoneOffset | None = None,
    **_: Any,
) -> SafeZoneRect:
    """UI viewport rect (always 640×480). Kept for compatibility."""
    return safe_zone_ui_rect(margins, offset or SafeZoneOffset())


def safe_zone_apply_offset(
    rect: SafeZoneRect,
    offset: SafeZoneOffset,
    *,
    canvas_w: int,
    canvas_h: int,
) -> SafeZoneRect:
    """Shift a UI-sized rect within the extended frame."""
    x = rect.x + offset.x
    y = rect.y + offset.y
    x = max(0, min(x, canvas_w - rect.w))
    y = max(0, min(y, canvas_h - rect.h))
    return SafeZoneRect(x, y, rect.w, rect.h)


def safe_zone_layout(
    margins: SafeZoneMargins,
    offset: SafeZoneOffset,
    **_: Any,
) -> SafeZoneRect:
    """UI viewport placement (640×480, never scaled)."""
    return safe_zone_ui_rect(margins, offset)


def safe_zone_to_config(
    margins: SafeZoneMargins,
    offset: SafeZoneOffset | None = None,
) -> dict[str, float | int]:
    out: dict[str, float | int] = {
        "top": margins.top,
        "bottom": margins.bottom,
        "left": margins.left,
        "right": margins.right,
    }
    if offset is not None and (offset.x != 0 or offset.y != 0):
        out["offset_x"] = offset.x
        out["offset_y"] = offset.y
    return out


def playback_overlay_rect(
    margins: SafeZoneMargins,
    offset: SafeZoneOffset | None = None,
) -> SafeZoneRect:
    """Title-safe inset inside the 640×480 video frame for playback HUD."""
    return playback_hud_rect(UI_W, UI_H, margins, offset)


def playback_hud_rect(
    canvas_w: int,
    canvas_h: int,
    margins: SafeZoneMargins,
    offset: SafeZoneOffset | None = None,
) -> SafeZoneRect:
    """Title-safe HUD inset on a playback canvas (video itself is full-bleed)."""
    if offset is None:
        offset = SafeZoneOffset()
    top, bottom, left, right = safe_zone_margin_pixels(margins)
    w = max(1, canvas_w - left - right)
    h = max(1, canvas_h - top - bottom)
    x = max(0, min(left + offset.x, canvas_w - w))
    y = max(0, min(top + offset.y, canvas_h - h))
    return SafeZoneRect(x, y, w, h)


def playback_overlay_scale(rect: SafeZoneRect) -> float:
    """Scale factor for playback HUD on a 640×480 frame."""
    return playback_hud_scale(rect, UI_W, UI_H)


def playback_hud_scale(rect: SafeZoneRect, canvas_w: int, canvas_h: int) -> float:
    """Playback HUD uses native 640×480 menu typography — no shrink for overscan."""
    _ = (rect, canvas_w, canvas_h)
    return 1.0


def clamp_margins(margins: SafeZoneMargins) -> SafeZoneMargins:
    return SafeZoneMargins(
        _clamp_percent(margins.top),
        _clamp_percent(margins.bottom),
        _clamp_percent(margins.left),
        _clamp_percent(margins.right),
    )


def adjust_margins_uniform(
    margins: SafeZoneMargins,
    *,
    vertical: float = 0.0,
    horizontal: float = 0.0,
) -> SafeZoneMargins:
    """Nudge all vertical and/or horizontal margin percentages."""
    return clamp_margins(
        SafeZoneMargins(
            margins.top + vertical,
            margins.bottom + vertical,
            margins.left + horizontal,
            margins.right + horizontal,
        )
    )


def clamp_offset(offset: SafeZoneOffset) -> SafeZoneOffset:
    return SafeZoneOffset(_clamp_offset(offset.x), _clamp_offset(offset.y))
