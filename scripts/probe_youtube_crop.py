#!/usr/bin/env python3
"""Live-probe YouTube pillarbox crop for a video id (diagnostic)."""

from __future__ import annotations

import io
import logging
import sys
import time
from pathlib import Path

import pygame

from tv_time_capsule.youtube_crop_cache import crop_cache_dir, load_pillarbox_crop_entry
from tv_time_capsule.youtube_player import (
    YouTubePlayer,
    _crop_black_bars,
    _crop_solid_matte,
    _finalize_crop,
    _surface_rgb,
    detect_letterbox_rect,
    is_near_solid_frame,
    sample_side_matte,
)

LOG = logging.getLogger("probe")


def _analyze(surf: pygame.Surface, label: str, out_dir: Path) -> None:
    w, h = surf.get_size()
    path = out_dir / f"{label}.jpg"
    pygame.image.save(surf, str(path))
    solid = is_near_solid_frame(surf)
    matte = sample_side_matte(surf)
    rect = detect_letterbox_rect(surf, matte_rgb=matte)
    rgb = _surface_rgb(surf)
    raw_solid = raw_black = None
    if rgb is not None:
        if matte is not None:
            raw_solid = _crop_solid_matte(
                rgb,
                matte,
                min_bar_px=6,
                min_bar_frac=0.03,
                matte_tol=20.0,
                flat_mad_max=16.0,
            )
            # Peek pre-finalize extents by temporarily ignoring finalize rules:
            # re-run walk logic is inside _crop_*; finalize already applied.
        raw_black = _crop_black_bars(rgb, black_max=22, min_bar_px=6, min_bar_frac=0.03)

    def fmt(c):
        if not c:
            return None
        x, y, cw, ch = c
        return f"{c} aspect={cw / ch:.3f} area={cw * ch / (w * h):.2%}"

    print(f"\n=== {label} ({w}x{h}) solid={solid} matte={matte} ===")
    print(f"  detect_letterbox_rect: {fmt(rect)}")
    print(f"  raw solid-matte crop:  {fmt(raw_solid)}")
    print(f"  raw black-bar crop:    {fmt(raw_black)}")
    if rect is None and (raw_solid or raw_black):
        cand = raw_solid or raw_black
        x, y, cw, ch = cand
        finalized = _finalize_crop(w, h, x, y, cw, ch, pad=0)
        print(f"  finalize(pad=0) on raw: {fmt(finalized)}")
    print(f"  saved {path}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    yid = sys.argv[1] if len(sys.argv) > 1 else "w97MpQ1q0zA"
    out_dir = Path("/tmp/ttc-crop-probe") / yid
    out_dir.mkdir(parents=True, exist_ok=True)

    cache = crop_cache_dir() / f"{yid}.json"
    if cache.exists():
        cache.unlink()
        print(f"cleared cache {cache}")

    pygame.init()
    pygame.display.set_mode((1, 1))

    player = YouTubePlayer(640, 480)
    samples: list[tuple[str, bytes]] = []

    # Capture JPEGs as they arrive during hold, tagged by probe region.
    orig_maybe = player._maybe_update_letterbox

    def wrapped(jpeg: bytes) -> None:
        region = player._crop_probe_region
        if player._hold_display_for_crop and len(samples) < 24:
            samples.append((region, jpeg))
        return orig_maybe(jpeg)

    player._maybe_update_letterbox = wrapped  # type: ignore[method-assign]

    print(f"probing youtube:{yid} …")
    ok = player.start(f"youtube:{yid}", resume_pos=0)
    print(f"start ok={ok} crop={player._content_crop} detected={player._detected_crop}")
    print(f"duration={player.duration:.1f}s time_pos={player.time_pos:.1f}s")

    # Analyze unique region samples (first few per region).
    seen = {"start": 0, "mid": 0, "end": 0}
    for region, jpeg in samples:
        if seen.get(region, 0) >= 2:
            continue
        seen[region] = seen.get(region, 0) + 1
        try:
            surf = pygame.image.load(io.BytesIO(jpeg))
        except Exception as exc:
            print(f"bad jpeg {region}: {exc}")
            continue
        if surf.get_size() != (640, 480):
            from tv_time_capsule.youtube_player import scale_uniform

            surf = scale_uniform(surf, 640, 480, mode="fit")
        _analyze(surf, f"{region}_{seen[region]}", out_dir)

    entry = load_pillarbox_crop_entry(yid, width=640, height=480)
    print(f"\ncache entry: {entry}")
    if cache.exists():
        print(cache.read_text())

    player.stop()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
