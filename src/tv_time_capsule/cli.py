"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

import pygame

from .app import TVTimeCapsule
from .config import CONFIG_FILE, load_config, save_default_config
from .media import discover_shows
from .mounts import ensure_mounts, mountpoints_from_config
from .player import detect_ffmpeg, np_frombuffer


def _merge_media_paths(configured: list[str], mount_points: list[str]) -> list[str]:
    """Configured paths first, then any mountpoints not already listed."""
    out: list[str] = []
    for path in list(configured) + list(mount_points):
        if path and path not in out:
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="TV Time Capsule")
    parser.add_argument(
        "--media-dir",
        action="append",
        dest="media_dirs",
        metavar="DIR",
        help=(
            "Media directory to scan (may be repeated). "
            "If omitted, uses media_paths from ~/.config/tv-time-capsule/config.json"
        ),
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Run in a window instead of fullscreen (useful for testing)",
    )
    parser.add_argument(
        "--force-43",
        action="store_true",
        help=(
            "Keep 4:3 letterboxing (default behaviour with the 640x480 canvas; "
            "accepted for compatibility)"
        ),
    )
    parser.add_argument(
        "--scanlines",
        action="store_true",
        help="Enable CRT scanline overlay effect",
    )
    parser.add_argument(
        "--skip-mounts",
        action="store_true",
        help="Do not mount remote shares from the config file",
    )
    args = parser.parse_args(argv)

    save_default_config()
    cfg = load_config()

    if not args.skip_mounts:
        for line in ensure_mounts(cfg.get("mounts") or []):
            print(line)

    # Determine media paths: CLI flags > config (+ mountpoints)
    if args.media_dirs:
        media_paths = args.media_dirs
    else:
        media_paths = _merge_media_paths(
            cfg["media_paths"],
            mountpoints_from_config(cfg.get("mounts")),
        )

    shows = discover_shows(media_paths)
    if not shows:
        print(f"No shows found in: {', '.join(media_paths)}")
        print("Expected: <media-dir>/Show Name/s01/s01e01.mp4")
        print(f"Configure paths / mounts in: {CONFIG_FILE}")
        sys.exit(1)

    total_eps = sum(
        len(season["episodes"])
        for show in shows.values()
        for season in show["seasons"].values()
    )
    print(f"Found {len(shows)} show(s), {total_eps} total episode(s)")
    for name, show in shows.items():
        for s_num, s_data in sorted(show["seasons"].items()):
            n = len(s_data["episodes"])
            thumb = "[ok]" if s_data.get("thumbnail") else " [ ]"
            print(f"  {name} -- S-{s_num:02d}: {n} episode(s) {thumb}")

    app = TVTimeCapsule(
        media_paths,
        fullscreen=not args.windowed,
        force_43=args.force_43,
        scanlines=args.scanlines,
    )

    if not app.player_cmd and not app.player:
        ffmpeg = detect_ffmpeg()
        if not ffmpeg:
            print("\nWARNING: ffmpeg not found. Video playback requires ffmpeg.")
            print("  Auto-install: ./scripts/install-system-deps.sh")
            print("  Or manually:  brew install ffmpeg      (macOS)")
            print("                sudo apt install ffmpeg  (Linux/Pi)")
        if np_frombuffer is None:
            print("\nWARNING: numpy not found. Embedded video requires numpy.")
            print("  Install: pip install numpy")

    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
