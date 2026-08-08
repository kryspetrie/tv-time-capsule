"""YouTube pillarbox / letterbox crop detection and ffmpeg helpers."""

from __future__ import annotations

import logging

import numpy as np
import pygame

LOG = logging.getLogger(__name__)

try:
    import cv2  # type: ignore
except ImportError:  # pragma: no cover - optional at runtime
    cv2 = None  # type: ignore


def _surface_rgb(surf: pygame.Surface) -> np.ndarray | None:
    """Return HxWx3 uint16 RGB copy, or ``None`` if unavailable."""
    try:
        arr = pygame.surfarray.pixels3d(surf)
        rgb = np.asarray(arr, dtype=np.uint16).transpose(1, 0, 2).copy()
        del arr
        return rgb
    except Exception:
        return None


def _color_dist(a: np.ndarray | tuple, b: np.ndarray | tuple) -> float:
    return float(
        max(
            abs(int(a[0]) - int(b[0])),
            abs(int(a[1]) - int(b[1])),
            abs(int(a[2]) - int(b[2])),
        )
    )


def normalize_crop_rect(
    crop: tuple[int, int, int, int] | None,
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    """Absolute pixels → fractions of width/height (0..1)."""
    if crop is None:
        return None
    if width <= 0 or height <= 0:
        return None
    x, y, w, h = crop
    return (x / width, y / height, w / width, h / height)


def denormalize_crop_rect(
    norm: tuple[float, float, float, float] | None,
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    """Fractions → absolute pixels for a viewport."""
    if norm is None:
        return None
    if width <= 0 or height <= 0:
        return None
    x, y, w, h = norm
    return (
        int(round(x * width)),
        int(round(y * height)),
        int(round(w * width)),
        int(round(h * height)),
    )


def ffmpeg_crop_filter(
    norm: tuple[float, float, float, float] | None,
    width: int,
    height: int,
    *,
    apply: bool,
    cover: bool = True,
) -> str:
    """Build ffmpeg -vf string: optional crop= then scale/pad or cover-style scale+crop.

    When apply is False or norm is None: just scale+pad to width:height (fit).
    When apply True: crop using normalized fractions of the *source* frame
    (``iw``/``ih`` expressions) then scale to fill (cover) if cover=True, else fit.
    """
    tw, th = int(width), int(height)
    fit_tail = (
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2"
    )
    if not apply or norm is None:
        return fit_tail

    nx, ny, nw, nh = (float(v) for v in norm)
    if nw <= 0 or nh <= 0:
        return fit_tail
    # Clamp to valid crop region.
    nx = max(0.0, min(1.0, nx))
    ny = max(0.0, min(1.0, ny))
    nw = max(0.01, min(1.0 - nx, nw))
    nh = max(0.01, min(1.0 - ny, nh))
    head = (
        f"crop=iw*{nw:.6f}:ih*{nh:.6f}:iw*{nx:.6f}:ih*{ny:.6f}"
    )
    if cover:
        return (
            f"{head},scale={tw}:{th}:force_original_aspect_ratio=increase,"
            f"crop={tw}:{th}"
        )
    return f"{head},{fit_tail}"


def _consensus_crop(
    crops: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float] | None:
    """Pick a stable crop from multi-frame samples via aspect clustering.

    Windowboxes (wider aspect) need ≥2 agreeing samples; classic pillarboxes
    can accept a single confident hit. When clusters compete, prefer the one
    with larger median fill (avoids dark-studio false windowboxes).
    """
    if not crops:
        return None
    if len(crops) == 1:
        aspect = crops[0][2] / max(crops[0][3], 1e-6)
        # Single-frame windowbox is too easy to fake from a dark scene.
        if aspect > 1.42:
            return None
        return crops[0]

    # Cluster by aspect ratio (bucket width ~0.08).
    buckets: dict[int, list[tuple[float, float, float, float]]] = {}
    for crop in crops:
        aspect = crop[2] / max(crop[3], 1e-6)
        key = int(round(aspect / 0.08))
        buckets.setdefault(key, []).append(crop)

    def _fill(c: tuple[float, float, float, float]) -> float:
        return float(c[2] * c[3])

    def _cluster_key(group: list[tuple[float, float, float, float]]) -> tuple:
        fills = sorted(_fill(c) for c in group)
        mid = fills[len(fills) // 2]
        heights = sorted(float(c[3]) for c in group)
        mid_h = heights[len(heights) // 2]
        # Prefer larger picture area first (dark-studio false crops are smaller),
        # then agreement count, then height fill.
        return (mid, len(group), mid_h)

    eligible = [
        g
        for g in buckets.values()
        if len(g) >= 2 or (g[0][2] / max(g[0][3], 1e-6)) <= 1.42
    ]
    if not eligible:
        return None
    best = max(eligible, key=_cluster_key)
    if len(best) < 2 and (best[0][2] / max(best[0][3], 1e-6)) > 1.42:
        return None

    # Medoid: minimize L1 distance to other members in the cluster.
    def _dist(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        return sum(abs(float(x) - float(y)) for x, y in zip(a, b))

    medoid = min(best, key=lambda c: sum(_dist(c, o) for o in best))
    aspect = medoid[2] / max(medoid[3], 1e-6)
    mode = "windowbox" if aspect > 1.42 else "pillarbox"
    LOG.info(
        "YouTube crop consensus mode=%s samples=%d cluster=%d aspect=%.2f fill=%.2f",
        mode,
        len(crops),
        len(best),
        aspect,
        _fill(medoid),
    )
    return medoid


def probe_file_pillarbox_crop(
    filepath: str,
    *,
    sample_times: tuple[float, ...] = (3.0, 8.0, 15.0, 30.0, 45.0, 75.0, 120.0),
    probe_max_width: int = 640,
    ffmpeg_path: str | None = None,
    # Backward-compat aliases (ignored for sizing; keep call sites working).
    probe_width: int | None = None,
    probe_height: int | None = None,
) -> tuple[float, float, float, float] | None:
    """Sample frames from a local file and return normalized crop or None.

    Scales each frame to ``probe_max_width`` on the long edge **without**
    padding into a fixed 4:3 canvas (padding invented false bars).
    """
    import subprocess
    import tempfile
    from pathlib import Path

    del probe_height  # unused; kept for API compatibility
    max_w = int(probe_width or probe_max_width)
    max_w = max(160, min(1280, max_w))
    ffmpeg = ffmpeg_path or "ffmpeg"
    crops: list[tuple[float, float, float, float]] = []
    with tempfile.TemporaryDirectory(prefix="ttc-yt-probe-") as tmp:
        for i, t in enumerate(sample_times):
            out = Path(tmp) / f"frame_{i}.png"
            # Scale width to max_w, preserve aspect — no pad.
            cmd = [
                ffmpeg,
                "-y",
                "-ss",
                str(max(0.0, float(t))),
                "-i",
                filepath,
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({max_w},iw)':-2",
                "-loglevel",
                "error",
                str(out),
            ]
            try:
                subprocess.run(cmd, check=False, timeout=20, capture_output=True)
            except (OSError, subprocess.TimeoutExpired) as exc:
                LOG.debug("file crop probe ffmpeg failed: %s", exc)
                continue
            if not out.is_file():
                continue
            try:
                surf = pygame.image.load(str(out))
            except Exception:
                continue
            sw, sh = surf.get_size()
            if sw < 32 or sh < 32:
                continue
            if is_near_solid_frame(surf):
                continue
            rect = detect_letterbox_rect(surf)
            if rect is None:
                continue
            norm = normalize_crop_rect(rect, sw, sh)
            if norm is not None:
                crops.append(norm)
    return _consensus_crop(crops)


def is_near_solid_frame(
    surf: pygame.Surface,
    *,
    mad_max: float = 7.0,
    center_mad_max: float = 8.0,
    center_mean_max: float = 20.0,
) -> bool:
    """True for flat full-frame holds (solid black/color fades, empty cards).

    These have no readable pillarbox signal and must not be recorded as
    "no crop" evidence.
    """
    w, h = surf.get_size()
    if w < 16 or h < 16:
        return True
    rgb = _surface_rgb(surf)
    if rgb is None:
        return False
    pix = rgb.astype(np.float64)
    mean = pix.mean(axis=(0, 1))
    mad = float(np.abs(pix - mean).mean())
    if mad <= mad_max:
        return True
    # Soft fades: center is also a flat field matching the overall mean.
    cy0, cy1 = h // 3, (2 * h) // 3
    cx0, cx1 = w // 3, (2 * w) // 3
    center = pix[cy0:cy1, cx0:cx1]
    if center.size == 0:
        return False
    c_mean = center.mean(axis=(0, 1))
    c_mad = float(np.abs(center - c_mean).mean())
    return c_mad <= center_mad_max and _color_dist(c_mean, mean) <= center_mean_max


def sample_side_matte(
    surf: pygame.Surface,
    *,
    probe_frac: float = 0.05,
    min_probe_px: int = 6,
    flat_mad_max: float = 14.0,
    side_match_max: float = 22.0,
) -> tuple[float, float, float] | None:
    """Mean RGB of matching flat left/right edge rectangles, or ``None``."""
    w, h = surf.get_size()
    if w < 32 or h < 32:
        return None
    rgb = _surface_rgb(surf)
    if rgb is None:
        return None

    probe = max(min_probe_px, int(w * probe_frac))
    probe = min(probe, max(6, w // 6))
    y0, y1 = int(h * 0.18), int(h * 0.82)
    if y1 - y0 < 16:
        y0, y1 = 0, h

    left_patch = rgb[y0:y1, 0:probe]
    right_patch = rgb[y0:y1, w - probe : w]
    left_mean = left_patch.mean(axis=(0, 1))
    right_mean = right_patch.mean(axis=(0, 1))
    left_mad = float(np.abs(left_patch.astype(np.int16) - left_mean).mean())
    right_mad = float(np.abs(right_patch.astype(np.int16) - right_mean).mean())
    if left_mad > flat_mad_max or right_mad > flat_mad_max:
        return None
    if _color_dist(left_mean, right_mean) > side_match_max:
        return None
    mid = (left_mean + right_mean) * 0.5
    return (float(mid[0]), float(mid[1]), float(mid[2]))


def _finalize_crop(
    w: int, h: int, x: int, y: int, rw: int, rh: int, *, pad: int = 2,
    windowboxed: bool = False,
) -> tuple[int, int, int, int] | None:
    x = min(max(0, x + pad), w - 8)
    y = min(max(0, y + pad), h - 8)
    rw = max(8, min(rw - 2 * pad, w - x))
    rh = max(8, min(rh - 2 * pad, h - y))
    if rw >= w * 0.98 and rh >= h * 0.98:
        return None
    # Reject absurd windowboxes from dark scenes / chrome (e.g. a thin
    # title-card slice carved out of an already-4:3 frame).
    if rw < w * 0.45 or rh < h * 0.55:
        return None
    aspect = rw / float(rh)
    if aspect < 0.90:
        return None
    # Prefer ~4:3 SD picture (classic pillarbox). Also accept true ~16:9
    # windowboxes (bars on all four sides) — e.g. widescreen Arthur burned
    # into a 4:3 upload — but not letterbox-only or tiny title-card slices.
    if aspect <= 1.42:
        return x, y, rw, rh
    if (
        windowboxed
        and aspect <= 1.90
        and rw >= w * 0.55
        and rh >= h * 0.52
        and y >= max(4, int(h * 0.04))
        and (h - (y + rh)) >= max(4, int(h * 0.04))
    ):
        return x, y, rw, rh
    return None


def _region_mad(
    rgb: np.ndarray, x: int, y: int, rw: int, rh: int
) -> float:
    patch = rgb[y : y + rh, x : x + rw]
    if patch.size < 16:
        return 0.0
    pix = patch.astype(np.float64)
    return float(np.abs(pix - pix.mean(axis=(0, 1))).mean())


def _bars_match_matte(
    rgb: np.ndarray,
    *,
    x: int,
    y: int,
    rw: int,
    rh: int,
    matte_rgb: tuple[float, float, float] | None,
    black_max: float = 28.0,
    matte_tol: float = 28.0,
    flat_mad_max: float = 18.0,
) -> bool:
    """True when top/bottom strips look like the same flat matte as the sides."""
    h, w = rgb.shape[0], rgb.shape[1]
    top_h = y
    bot_h = h - (y + rh)
    if top_h < 2 or bot_h < 2:
        return True
    x0 = max(0, x)
    x1 = min(w, x + rw)
    if x1 - x0 < 8:
        return False
    top = rgb[0:top_h, x0:x1].astype(np.float64)
    bot = rgb[y + rh : h, x0:x1].astype(np.float64)
    if top.size < 16 or bot.size < 16:
        return False
    t_mean = top.mean(axis=(0, 1))
    b_mean = bot.mean(axis=(0, 1))
    t_mad = float(np.abs(top - t_mean).mean())
    b_mad = float(np.abs(bot - b_mean).mean())
    if t_mad > flat_mad_max or b_mad > flat_mad_max:
        return False
    if _color_dist(t_mean, b_mean) > matte_tol:
        return False
    if matte_rgb is not None:
        return (
            _color_dist(t_mean, matte_rgb) <= matte_tol
            and _color_dist(b_mean, matte_rgb) <= matte_tol
        )
    # No side matte sample — require near-black letterbox bars.
    return float(np.max(t_mean)) <= black_max and float(np.max(b_mean)) <= black_max


def _side_bars_symmetric(
    left: int,
    right: int,
    width: int,
    *,
    max_ratio: float = 2.0,
    max_delta_frac: float = 0.10,
) -> bool:
    """True when left/right mattes look like a centered pillarbox."""
    if left < 1 or right < 1 or width < 8:
        return False
    ratio = max(left, right) / float(max(1, min(left, right)))
    if abs(left - right) <= max(2, int(width * 0.03)):
        return True
    return ratio <= max_ratio and abs(left - right) <= width * max_delta_frac


def _snap_symmetric_sides(
    width: int, left: int, right: int
) -> tuple[int, int]:
    """Re-center using the smaller side bar when insets are badly skewed."""
    bar = max(1, min(left, right))
    # If one side is hugely larger, trust the smaller (true matte) edge.
    if max(left, right) > bar * 1.8:
        return bar, width - 2 * bar
    # Mild skew: average the bars.
    bar = max(1, int(round(0.5 * (left + right))))
    bar = min(bar, (width - 8) // 2)
    return bar, width - 2 * bar


def _relax_false_windowbox(
    rgb: np.ndarray,
    crop: tuple[int, int, int, int],
    matte_rgb: tuple[float, float, float] | None = None,
) -> tuple[int, int, int, int]:
    """Expand to full height unless top+bottom are a real matching windowbox.

    Also re-centers badly asymmetric side crops (OpenCV latching onto a bright
    subject inside an already-pillarboxed frame).
    """
    x, y, rw, rh = crop
    h, w = rgb.shape[0], rgb.shape[1]
    left_bar = x
    right_bar = w - (x + rw)
    top_bar = y
    bot_bar = h - (y + rh)
    min_letter = max(4, int(h * 0.04))

    # Fix skewed side bars first (independent of letterbox).
    if left_bar >= min(6, min_letter) and right_bar >= min(6, min_letter):
        if not _side_bars_symmetric(left_bar, right_bar, w):
            nx, nrw = _snap_symmetric_sides(w, left_bar, right_bar)
            snapped = _finalize_crop(
                w, h, nx, 0, nrw, h, windowboxed=False, pad=0
            )
            if snapped is not None and _crop_has_picture(rgb, snapped, matte_rgb):
                x, y, rw, rh = snapped
                left_bar = x
                right_bar = w - (x + rw)
                top_bar = y
                bot_bar = h - (y + rh)

    if top_bar < min_letter and bot_bar < min_letter:
        return x, y, rw, rh

    # True windowbox: both letterbox bands present and matching the side matte.
    if (
        top_bar >= min_letter
        and bot_bar >= min_letter
        and _bars_match_matte(
            rgb, x=x, y=y, rw=rw, rh=rh, matte_rgb=matte_rgb
        )
    ):
        return x, y, rw, rh

    # One-sided or non-matte vertical insets → classic full-height pillarbox.
    relaxed = _finalize_crop(w, h, x, 0, rw, h, windowboxed=False, pad=0)
    return relaxed if relaxed is not None else (x, y, rw, rh)


def _crop_has_picture(
    rgb: np.ndarray,
    crop: tuple[int, int, int, int],
    matte_rgb: tuple[float, float, float] | None = None,
) -> bool:
    """True when the cropped region looks like picture, not another matte."""
    cx, cy, cw, ch = crop
    patch = rgb[cy : cy + ch, cx : cx + cw]
    if patch.size < 16:
        return False
    pix = patch.astype(np.float64)
    mean = pix.mean(axis=(0, 1))
    mad = float(np.abs(pix - mean).mean())
    if mad >= 8.0:
        return True
    if matte_rgb is not None and _color_dist(mean, matte_rgb) > 28:
        return True
    # Flat but clearly not a near-black hold / bar.
    return float(np.max(mean)) >= 36.0


def _crop_solid_matte(
    rgb: np.ndarray,
    matte_rgb: tuple[float, float, float],
    *,
    min_bar_px: int,
    min_bar_frac: float,
    matte_tol: float,
    flat_mad_max: float,
) -> tuple[int, int, int, int] | None:
    """Walk inward from solid-colored side mattes; optional matching top/bottom."""
    h, w = rgb.shape[0], rgb.shape[1]
    y0, y1 = int(h * 0.18), int(h * 0.82)
    if y1 - y0 < 16:
        y0, y1 = max(0, h // 10), min(h, (9 * h) // 10)

    matte = np.asarray(matte_rgb, dtype=np.float64)
    band = rgb[y0:y1, :, :].astype(np.float64)
    col_mean = band.mean(axis=0)
    col_mad = np.abs(band - col_mean).mean(axis=(0, 2))
    dist = np.max(np.abs(col_mean - matte), axis=1)

    left = 0
    while left < w and dist[left] <= matte_tol and col_mad[left] <= flat_mad_max:
        left += 1
    right = w - 1
    while right >= 0 and dist[right] <= matte_tol and col_mad[right] <= flat_mad_max:
        right -= 1
    if right <= left:
        return None

    min_bar = max(min_bar_px, int(min(h, w) * min_bar_frac))
    if left < min_bar or (w - 1 - right) < min_bar:
        return None

    right_bar = w - 1 - right
    if not _side_bars_symmetric(left, right_bar, w):
        left, width_c = _snap_symmetric_sides(w, left, right_bar)
        right = left + width_c - 1
    x0c, x1c = left, right + 1
    mid_band = rgb[:, x0c:x1c, :].astype(np.float64)
    row_mean = mid_band.mean(axis=1)
    row_mad = np.abs(mid_band - row_mean[:, None, :]).mean(axis=(1, 2))
    row_dist = np.max(np.abs(row_mean - matte), axis=1)
    top = 0
    while top < h and row_dist[top] <= matte_tol and row_mad[top] <= flat_mad_max:
        top += 1
    bot = h - 1
    while bot >= 0 and row_dist[bot] <= matte_tol and row_mad[bot] <= flat_mad_max:
        bot -= 1
    letterbox = (
        top >= min_bar and (h - 1 - bot) >= min_bar and bot > top
    )
    y = top if letterbox else 0
    rh = (bot - top + 1) if letterbox else h
    return _finalize_crop(
        w, h, left, y, right - left + 1, rh, windowboxed=letterbox
    )


def _crop_black_bars(
    rgb: np.ndarray,
    *,
    black_max: int,
    min_bar_px: int,
    min_bar_frac: float,
) -> tuple[int, int, int, int] | None:
    """Legacy near-black luma pillarbox / windowbox detection."""
    h, w = rgb.shape[0], rgb.shape[1]
    luma = (rgb[:, :, 0] * 3 + rgb[:, :, 1] * 6 + rgb[:, :, 2]) // 10
    mid_x0, mid_x1 = w // 3, (2 * w) // 3
    mid_y0, mid_y1 = h // 3, (2 * h) // 3
    col_strip = luma[:, mid_x0:mid_x1].mean(axis=1)
    row_strip = luma[mid_y0:mid_y1, :].mean(axis=0)

    def _bar_extent(line: np.ndarray, length: int) -> tuple[int, int]:
        dark = line <= black_max
        lo = 0
        while lo < length and dark[lo]:
            lo += 1
        hi = length - 1
        while hi >= 0 and dark[hi]:
            hi -= 1
        return lo, hi

    top, bot = _bar_extent(col_strip, h)
    left, right = _bar_extent(row_strip, w)
    if bot <= top or right <= left:
        return None
    min_bar = max(min_bar_px, int(min(h, w) * min_bar_frac))
    right_bar = w - 1 - right
    pillarbox = left >= min_bar and right_bar >= min_bar
    if not pillarbox:
        return None
    if not _side_bars_symmetric(left, right_bar, w):
        left, width_c = _snap_symmetric_sides(w, left, right_bar)
        right = left + width_c - 1
    letterbox = top >= min_bar and (h - 1 - bot) >= min_bar
    y = top if letterbox else 0
    rh = (bot - top + 1) if letterbox else h
    return _finalize_crop(
        w, h, left, y, right - left + 1, rh, windowboxed=letterbox
    )


def _variance_profile_crop(
    rgb: np.ndarray,
    *,
    min_bar_px: int,
    min_bar_frac: float,
    flat_var_max: float = 180.0,
) -> tuple[int, int, int, int] | None:
    """Locate flat matte bands via per-column/row color variance (any color)."""
    h, w = rgb.shape[0], rgb.shape[1]
    pix = rgb.astype(np.float64)
    # Mid-band to avoid logos/chrome in corners.
    y0, y1 = int(h * 0.15), int(h * 0.85)
    x0, x1 = int(w * 0.15), int(w * 0.85)
    if y1 - y0 < 16 or x1 - x0 < 16:
        return None

    col_var = pix[y0:y1, :, :].var(axis=(0, 2))
    row_var = pix[:, x0:x1, :].var(axis=(1, 2))

    def _flat_extent(line: np.ndarray, length: int) -> tuple[int, int]:
        lo = 0
        while lo < length and line[lo] <= flat_var_max:
            lo += 1
        hi = length - 1
        while hi >= 0 and line[hi] <= flat_var_max:
            hi -= 1
        return lo, hi

    left, right = _flat_extent(col_var, w)
    top, bot = _flat_extent(row_var, h)
    if right <= left or bot <= top:
        return None
    min_bar = max(min_bar_px, int(min(h, w) * min_bar_frac))
    pillarbox = left >= min_bar and (w - 1 - right) >= min_bar
    if not pillarbox:
        return None
    letterbox = top >= min_bar and (h - 1 - bot) >= min_bar
    y = top if letterbox else 0
    rh = (bot - top + 1) if letterbox else h
    return _finalize_crop(
        w, h, left, y, right - left + 1, rh, windowboxed=letterbox
    )


def _opencv_content_crop(
    rgb: np.ndarray,
    *,
    min_bar_px: int,
    min_bar_frac: float,
) -> tuple[int, int, int, int] | None:
    """OpenCV edge/contour content rectangle (Arthur windowboxes, colored mattes)."""
    if cv2 is None:
        return None
    h, w = rgb.shape[0], rgb.shape[1]
    # uint8 BGR for OpenCV
    bgr = np.clip(rgb, 0, 255).astype(np.uint8)[:, :, ::-1]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    # Close gaps along bar boundaries.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _hier = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        # Fall back to variance profiles computed via OpenCV meanStdDev-style numpy.
        return _variance_profile_crop(
            rgb, min_bar_px=min_bar_px, min_bar_frac=min_bar_frac
        )

    min_bar = max(min_bar_px, int(min(h, w) * min_bar_frac))
    frame_area = float(w * h)
    best: tuple[float, tuple[int, int, int, int]] | None = None

    for cnt in contours:
        x, y, rw, rh = cv2.boundingRect(cnt)
        area = float(rw * rh)
        if area < frame_area * 0.28 or area > frame_area * 0.97:
            continue
        # Must be inset enough to be a real matte (sides required).
        left_bar = x
        right_bar = w - (x + rw)
        top_bar = y
        bot_bar = h - (y + rh)
        if left_bar < min_bar or right_bar < min_bar:
            continue
        # Reject / repair contours that hug a bright subject inside side mattes
        # (asymmetric leftover "bars" are the usual tell).
        if not _side_bars_symmetric(left_bar, right_bar, w):
            x, rw = _snap_symmetric_sides(w, left_bar, right_bar)
            y, rh = 0, h
            left_bar = x
            right_bar = w - (x + rw)
            top_bar = 0
            bot_bar = 0
        windowboxed = top_bar >= min_bar and bot_bar >= min_bar
        finalized = _finalize_crop(
            w, h, x, y, rw, rh, windowboxed=windowboxed, pad=1
        )
        if finalized is None:
            continue
        fx, fy, frw, frh = finalized
        if not _crop_has_picture(rgb, finalized):
            continue
        # Score: border energy + interior variance + fill + height.
        # Prefer geometry near classic 4:3-in-widescreen when the frame is wide.
        border = np.zeros_like(edges)
        cv2.rectangle(border, (fx, fy), (fx + frw - 1, fy + frh - 1), 255, 2)
        border_energy = float(cv2.mean(edges, mask=border)[0])
        interior = rgb[fy : fy + frh, fx : fx + frw].astype(np.float64)
        interior_var = float(interior.var()) if interior.size else 0.0
        fill = (frw * frh) / frame_area
        height_fill = frh / float(h)
        score = (
            border_energy * 2.0
            + min(interior_var, 4000.0) / 40.0
            + fill * 55.0
            + height_fill * 35.0
        )
        frame_aspect = w / float(h)
        if frame_aspect > 1.45:
            expected_w = h * (4.0 / 3.0)
            width_err = abs(frw - expected_w) / max(expected_w, 1.0)
            score += max(0.0, 18.0 * (1.0 - min(1.0, width_err * 2.0)))
        if windowboxed:
            side_matte = None
            left_strip = rgb[:, max(0, fx - max(2, min_bar)) : fx]
            if left_strip.size >= 16:
                side_matte = tuple(
                    float(v) for v in left_strip.astype(np.float64).mean(axis=(0, 1))
                )
            if _bars_match_matte(
                rgb, x=fx, y=fy, rw=frw, rh=frh, matte_rgb=side_matte
            ):
                score += 12.0
            else:
                score -= 30.0
        if best is None or score > best[0]:
            best = (score, finalized)

    if best is not None:
        return best[1]

    # Contours failed — variance profiles still catch flat colored mattes.
    return _variance_profile_crop(
        rgb, min_bar_px=min_bar_px, min_bar_frac=min_bar_frac
    )


def detect_letterbox_rect(
    surf: pygame.Surface,
    *,
    black_max: int = 22,
    min_bar_px: int = 6,
    min_bar_frac: float = 0.03,
    matte_tol: float = 20.0,
    flat_mad_max: float = 16.0,
    matte_rgb: tuple[float, float, float] | None = None,
) -> tuple[int, int, int, int] | None:
    """Return content ``(x, y, w, h)`` for pillarboxed / windowboxed frames.

    Prefers OpenCV content-rectangle detection when available, then solid side
    mattes of any color, then classic near-black luma bars. True widescreen
    letterbox-only (top/bottom, no sides) is left alone.
    """
    w, h = surf.get_size()
    if w < 32 or h < 32:
        return None
    rgb = _surface_rgb(surf)
    if rgb is None:
        return None

    matte = matte_rgb
    if matte is None:
        matte = sample_side_matte(
            surf, min_probe_px=min_bar_px, flat_mad_max=min(flat_mad_max, 14.0)
        )

    cv_crop = _opencv_content_crop(
        rgb, min_bar_px=min_bar_px, min_bar_frac=min_bar_frac
    )
    if cv_crop is not None and _crop_has_picture(rgb, cv_crop):
        return _relax_false_windowbox(rgb, cv_crop, matte)

    if matte is not None:
        crop = _crop_solid_matte(
            rgb,
            matte,
            min_bar_px=min_bar_px,
            min_bar_frac=min_bar_frac,
            matte_tol=matte_tol,
            flat_mad_max=flat_mad_max,
        )
        if crop is not None and _crop_has_picture(rgb, crop, matte):
            return _relax_false_windowbox(rgb, crop, matte)

    # Variance profile without OpenCV contours (numpy-only path).
    var_crop = _variance_profile_crop(
        rgb, min_bar_px=min_bar_px, min_bar_frac=min_bar_frac
    )
    if var_crop is not None and _crop_has_picture(rgb, var_crop, matte):
        return _relax_false_windowbox(rgb, var_crop, matte)

    crop = _crop_black_bars(
        rgb,
        black_max=black_max,
        min_bar_px=min_bar_px,
        min_bar_frac=min_bar_frac,
    )
    if crop is None:
        return None
    if not _crop_has_picture(rgb, crop, matte):
        return None
    return _relax_false_windowbox(rgb, crop, matte)


def scale_uniform(
    surf: pygame.Surface,
    target_w: int,
    target_h: int,
    *,
    mode: str = "fit",
) -> pygame.Surface:
    """Scale ``surf`` into ``target_w``×``target_h`` with equal X/Y scale.

    ``fit`` — contain (letterbox/pillarbox with black); ``cover`` — fill and
    center-crop overflow. Never uses different horizontal vs vertical ratios.
    """
    tw, th = int(target_w), int(target_h)
    sw, sh = surf.get_size()
    if tw <= 0 or th <= 0 or sw <= 0 or sh <= 0:
        return surf
    if (sw, sh) == (tw, th):
        return surf

    if mode == "cover":
        scale = max(tw / sw, th / sh)
    else:
        scale = min(tw / sw, th / sh)

    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    try:
        scaled = pygame.transform.smoothscale(surf, (nw, nh))
    except Exception:
        scaled = pygame.transform.scale(surf, (nw, nh))

    if mode == "cover":
        x = max(0, (nw - tw) // 2)
        y = max(0, (nh - th) // 2)
        # smoothscale rounding can leave us 1px short — pad rather than crash.
        if nw < tw or nh < th:
            out = pygame.Surface((tw, th))
            out.fill((0, 0, 0))
            out.blit(scaled, ((tw - nw) // 2, (th - nh) // 2))
            return out
        try:
            return scaled.subsurface((x, y, tw, th)).copy()
        except Exception:
            out = pygame.Surface((tw, th))
            out.fill((0, 0, 0))
            out.blit(scaled, (-x, -y))
            return out

    out = pygame.Surface((tw, th))
    out.fill((0, 0, 0))
    out.blit(scaled, ((tw - nw) // 2, (th - nh) // 2))
    return out
