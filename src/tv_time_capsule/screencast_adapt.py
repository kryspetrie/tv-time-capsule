"""Adaptive screencast FPS/quality controller (Weather Channel).

Pure logic — unit-testable without Chrome. Maps measured frame latency to
CDP ``Page.startScreencast`` knobs: ``everyNthFrame``, ``quality``, and
optional max dimensions.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScreencastParams:
    every_nth_frame: int
    quality: int
    max_width: int
    max_height: int
    effective_fps: float


@dataclass
class ScreencastAdaptState:
    params: ScreencastParams
    ema_latency_ms: float = 0.0
    samples: int = 0


def _is_weak_arm() -> bool:
    machine = platform.machine().lower()
    return machine in ("armv6l", "armv7l", "aarch64", "arm64") and (
        # Pi-ish: prefer conservative start; desktop ARM (M1) still OK to start mid.
        platform.system() == "Linux"
    )


def initial_screencast_params(
    cfg: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
) -> ScreencastParams:
    """Pick starting CDP knobs from config + hardware heuristic."""
    mode = str(cfg.get("mode") or "auto").lower()
    min_fps = float(cfg.get("min_fps") or 1)
    max_fps = float(cfg.get("max_fps") or 15)
    min_fps = max(0.5, min_fps)
    max_fps = max(min_fps, max_fps)
    target = cfg.get("target_fps")
    quality = int(cfg.get("jpeg_quality") or 80)
    quality = max(20, min(95, quality))

    max_w = cfg.get("max_width")
    max_h = cfg.get("max_height")
    try:
        max_w = int(max_w) if max_w else canvas_w
    except (TypeError, ValueError):
        max_w = canvas_w
    try:
        max_h = int(max_h) if max_h else canvas_h
    except (TypeError, ValueError):
        max_h = canvas_h
    max_w = max(160, min(int(canvas_w), max_w))
    max_h = max(120, min(int(canvas_h), max_h))

    if mode == "fixed" or target is not None:
        fps = float(target) if target is not None else min(8.0, max_fps)
        fps = max(min_fps, min(max_fps, fps))
        nth = max(1, int(round(15.0 / fps)))  # CDP base ~15Hz when everyNth=1
        return ScreencastParams(nth, quality, max_w, max_h, fps)

    # auto: start conservative on weak ARM
    if _is_weak_arm():
        fps = max(min_fps, min(4.0, max_fps))
        quality = min(quality, 55)
        max_w = min(max_w, 480)
        max_h = min(max_h, 360)
    else:
        fps = max(min_fps, min(10.0, max_fps))
    nth = max(1, int(round(15.0 / fps)))
    return ScreencastParams(nth, quality, max_w, max_h, fps)


def observe_frame_latency(
    state: ScreencastAdaptState,
    latency_ms: float,
    cfg: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
) -> tuple[ScreencastAdaptState, bool]:
    """Update EMA latency; return ``(state, restart_needed)``.

    ``restart_needed`` is True when params should be reapplied via
    stop/start screencast.
    """
    mode = str(cfg.get("mode") or "auto").lower()
    if mode != "auto" or cfg.get("target_fps") is not None:
        return state, False

    min_fps = float(cfg.get("min_fps") or 1)
    max_fps = float(cfg.get("max_fps") or 15)
    min_fps = max(0.5, min_fps)
    max_fps = max(min_fps, max_fps)

    alpha = 0.25
    if state.samples == 0:
        ema = float(latency_ms)
    else:
        ema = alpha * float(latency_ms) + (1.0 - alpha) * state.ema_latency_ms
    state.ema_latency_ms = ema
    state.samples += 1

    # Need a few samples before adapting.
    if state.samples < 8:
        return state, False

    old = state.params
    # Target budget: prefer latency under ~120ms; step down above 250ms.
    quality = old.quality
    nth = old.every_nth_frame
    max_w, max_h = old.max_width, old.max_height
    changed = False

    if ema > 280:
        if nth < 8:
            nth = min(8, nth + 1)
            changed = True
        elif quality > 35:
            quality = max(35, quality - 10)
            changed = True
        elif max_w > 320:
            max_w = max(320, int(max_w * 0.85))
            max_h = max(240, int(max_h * 0.85))
            changed = True
    elif ema > 160:
        if nth < 4:
            nth = min(4, nth + 1)
            changed = True
        elif quality > 45:
            quality = max(45, quality - 5)
            changed = True
    elif ema < 70 and nth > 1:
        # Room to improve
        nth = max(1, nth - 1)
        changed = True
    elif ema < 50 and quality < int(cfg.get("jpeg_quality") or 80):
        quality = min(int(cfg.get("jpeg_quality") or 80), quality + 5)
        changed = True

    # Enforce FPS floor/ceiling via everyNthFrame (assume ~15Hz base).
    eff = 15.0 / max(1, nth)
    if eff < min_fps and nth > 1:
        nth = max(1, int(round(15.0 / min_fps)))
        changed = True
        eff = 15.0 / max(1, nth)
    if eff > max_fps:
        nth = max(1, int(round(15.0 / max_fps)))
        changed = True
        eff = 15.0 / max(1, nth)

    max_w = max(160, min(int(canvas_w), max_w))
    max_h = max(120, min(int(canvas_h), max_h))
    if not changed:
        return state, False

    state.params = ScreencastParams(nth, quality, max_w, max_h, eff)
    state.samples = 0  # re-settle after change
    return state, True
