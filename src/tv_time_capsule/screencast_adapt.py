"""Adaptive screencast FPS/quality controller (Weather Channel).

Pure logic — unit-testable without Chrome. Maps CDP frame latency **and**
UI present stats (pygame FPS / blit cost, optional loadavg) to
``Page.startScreencast`` knobs: ``everyNthFrame``, ``quality``, and max
dimensions.
"""

from __future__ import annotations

import os
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
    ema_present_fps: float = 0.0
    ema_blit_ms: float = 0.0
    present_samples: int = 0


# Present-side budgets (UI decode/scale/blit).
_BLIT_STRESS_MS = 220.0
_BLIT_HEALTHY_MS = 100.0
_PRESENT_STRESS_RATIO = 0.55  # present FPS vs target effective_fps
_PRESENT_HEALTHY_RATIO = 0.85
_LOAD_STRESS = 1.5  # 1-min loadavg / cpu count
_MIN_PRESENT_SAMPLES = 8
_MIN_LATENCY_SAMPLES = 8


def _is_weak_arm() -> bool:
    machine = platform.machine().lower()
    return machine in ("armv6l", "armv7l", "aarch64", "arm64") and (
        # Pi-ish: prefer conservative start; desktop ARM (M1) still OK to start mid.
        platform.system() == "Linux"
    )


def read_load_per_cpu() -> float | None:
    """1-minute load average divided by CPU count, or None if unavailable."""
    try:
        load1, _load5, _load15 = os.getloadavg()
    except (AttributeError, OSError):
        return None
    cpus = os.cpu_count() or 1
    return float(load1) / float(max(1, cpus))


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


def _auto_mode(cfg: dict[str, Any]) -> bool:
    mode = str(cfg.get("mode") or "auto").lower()
    return mode == "auto" and cfg.get("target_fps") is None


def _fps_bounds(cfg: dict[str, Any]) -> tuple[float, float]:
    min_fps = float(cfg.get("min_fps") or 1)
    max_fps = float(cfg.get("max_fps") or 15)
    min_fps = max(0.5, min_fps)
    max_fps = max(min_fps, max_fps)
    return min_fps, max_fps


def _clamp_dims(
    max_w: int, max_h: int, *, canvas_w: int, canvas_h: int
) -> tuple[int, int]:
    return (
        max(160, min(int(canvas_w), max_w)),
        max(120, min(int(canvas_h), max_h)),
    )


def _enforce_fps_nth(
    nth: int, *, min_fps: float, max_fps: float
) -> tuple[int, float, bool]:
    """Return ``(nth, effective_fps, changed)`` clamped to min/max FPS."""
    changed = False
    eff = 15.0 / max(1, nth)
    if eff < min_fps and nth > 1:
        nth = max(1, int(round(15.0 / min_fps)))
        changed = True
        eff = 15.0 / max(1, nth)
    if eff > max_fps:
        nth = max(1, int(round(15.0 / max_fps)))
        changed = True
        eff = 15.0 / max(1, nth)
    return nth, eff, changed


def _step_down(
    quality: int,
    nth: int,
    max_w: int,
    max_h: int,
    *,
    aggressive: bool,
) -> tuple[int, int, int, int, bool]:
    """One notch worse: nth → quality → resolution."""
    if aggressive:
        if nth < 8:
            return quality, min(8, nth + 1), max_w, max_h, True
        if quality > 35:
            return max(35, quality - 10), nth, max_w, max_h, True
        if max_w > 320:
            return (
                quality,
                nth,
                max(320, int(max_w * 0.85)),
                max(240, int(max_h * 0.85)),
                True,
            )
        return quality, nth, max_w, max_h, False
    if nth < 4:
        return quality, min(4, nth + 1), max_w, max_h, True
    if quality > 45:
        return max(45, quality - 5), nth, max_w, max_h, True
    return quality, nth, max_w, max_h, False


def _present_stressed(state: ScreencastAdaptState, *, load_per_cpu: float | None) -> bool:
    if state.present_samples < _MIN_PRESENT_SAMPLES:
        return False
    target = max(0.5, float(state.params.effective_fps))
    if state.ema_present_fps < target * _PRESENT_STRESS_RATIO:
        return True
    if state.ema_blit_ms > _BLIT_STRESS_MS:
        return True
    if load_per_cpu is not None and load_per_cpu > _LOAD_STRESS:
        return True
    return False


def _present_allows_step_up(
    state: ScreencastAdaptState, *, load_per_cpu: float | None
) -> bool:
    """True when present side looks healthy enough to raise quality/FPS."""
    if state.present_samples < _MIN_PRESENT_SAMPLES:
        # No present data yet — allow latency-only step-up (legacy behavior).
        return True
    target = max(0.5, float(state.params.effective_fps))
    if state.ema_present_fps < target * _PRESENT_HEALTHY_RATIO:
        return False
    if state.ema_blit_ms > _BLIT_HEALTHY_MS:
        return False
    if load_per_cpu is not None and load_per_cpu > _LOAD_STRESS:
        return False
    return True


def _latency_allows_step_up(state: ScreencastAdaptState) -> bool:
    if state.samples < _MIN_LATENCY_SAMPLES:
        return True
    return state.ema_latency_ms < 70.0


def _commit_change(
    state: ScreencastAdaptState,
    *,
    quality: int,
    nth: int,
    max_w: int,
    max_h: int,
    canvas_w: int,
    canvas_h: int,
    min_fps: float,
    max_fps: float,
) -> tuple[ScreencastAdaptState, bool]:
    nth, eff, _ = _enforce_fps_nth(nth, min_fps=min_fps, max_fps=max_fps)
    max_w, max_h = _clamp_dims(max_w, max_h, canvas_w=canvas_w, canvas_h=canvas_h)
    old = state.params
    if (
        nth == old.every_nth_frame
        and quality == old.quality
        and max_w == old.max_width
        and max_h == old.max_height
    ):
        return state, False
    state.params = ScreencastParams(nth, quality, max_w, max_h, eff)
    state.samples = 0
    state.present_samples = 0
    return state, True


def observe_frame_latency(
    state: ScreencastAdaptState,
    latency_ms: float,
    cfg: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
    load_per_cpu: float | None = None,
) -> tuple[ScreencastAdaptState, bool]:
    """Update EMA latency; return ``(state, restart_needed)``.

    ``restart_needed`` is True when params should be reapplied via
    stop/start screencast. Step-up requires healthy present stats when those
    samples exist (avoids oscillating against a slow blit path).
    """
    if not _auto_mode(cfg):
        return state, False

    min_fps, max_fps = _fps_bounds(cfg)
    alpha = 0.25
    if state.samples == 0:
        ema = float(latency_ms)
    else:
        ema = alpha * float(latency_ms) + (1.0 - alpha) * state.ema_latency_ms
    state.ema_latency_ms = ema
    state.samples += 1

    if state.samples < _MIN_LATENCY_SAMPLES:
        return state, False

    old = state.params
    quality = old.quality
    nth = old.every_nth_frame
    max_w, max_h = old.max_width, old.max_height
    changed = False

    if ema > 280:
        quality, nth, max_w, max_h, changed = _step_down(
            quality, nth, max_w, max_h, aggressive=True
        )
    elif ema > 160:
        quality, nth, max_w, max_h, changed = _step_down(
            quality, nth, max_w, max_h, aggressive=False
        )
    elif ema < 70 and nth > 1:
        if _present_allows_step_up(state, load_per_cpu=load_per_cpu):
            nth = max(1, nth - 1)
            changed = True
    elif ema < 50 and quality < int(cfg.get("jpeg_quality") or 80):
        if _present_allows_step_up(state, load_per_cpu=load_per_cpu):
            quality = min(int(cfg.get("jpeg_quality") or 80), quality + 5)
            changed = True

    if not changed:
        # Still enforce FPS bounds if somehow out of range.
        nth2, _eff, bound_changed = _enforce_fps_nth(
            nth, min_fps=min_fps, max_fps=max_fps
        )
        if not bound_changed:
            return state, False
        nth = nth2
        changed = True

    return _commit_change(
        state,
        quality=quality,
        nth=nth,
        max_w=max_w,
        max_h=max_h,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        min_fps=min_fps,
        max_fps=max_fps,
    )


def observe_present_stats(
    state: ScreencastAdaptState,
    present_fps: float,
    blit_ms: float,
    cfg: dict[str, Any],
    *,
    canvas_w: int,
    canvas_h: int,
    load_per_cpu: float | None = None,
) -> tuple[ScreencastAdaptState, bool]:
    """Update present-side EMAs; step down when the UI cannot keep up.

    Step-up only when both CDP latency (if sampled) and present stats look
    healthy.
    """
    if not _auto_mode(cfg):
        return state, False

    fps = float(present_fps)
    blit = float(blit_ms)
    if fps <= 0.05 or blit < 0:
        return state, False

    min_fps, max_fps = _fps_bounds(cfg)
    alpha = 0.25
    if state.present_samples == 0:
        state.ema_present_fps = fps
        state.ema_blit_ms = blit
    else:
        state.ema_present_fps = (
            alpha * fps + (1.0 - alpha) * state.ema_present_fps
        )
        state.ema_blit_ms = alpha * blit + (1.0 - alpha) * state.ema_blit_ms
    state.present_samples += 1

    if state.present_samples < _MIN_PRESENT_SAMPLES:
        return state, False

    old = state.params
    quality = old.quality
    nth = old.every_nth_frame
    max_w, max_h = old.max_width, old.max_height
    changed = False

    if _present_stressed(state, load_per_cpu=load_per_cpu):
        quality, nth, max_w, max_h, changed = _step_down(
            quality, nth, max_w, max_h, aggressive=True
        )
    elif (
        _present_allows_step_up(state, load_per_cpu=load_per_cpu)
        and _latency_allows_step_up(state)
        and nth > 1
        and state.ema_blit_ms < _BLIT_HEALTHY_MS * 0.7
        and state.ema_present_fps
        >= max(0.5, float(old.effective_fps)) * 1.05
    ):
        # Clear headroom: raise FPS one notch.
        nth = max(1, nth - 1)
        changed = True

    if not changed:
        return state, False

    return _commit_change(
        state,
        quality=quality,
        nth=nth,
        max_w=max_w,
        max_h=max_h,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        min_fps=min_fps,
        max_fps=max_fps,
    )
