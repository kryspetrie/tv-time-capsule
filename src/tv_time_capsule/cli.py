"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

import pygame

from .app import TVTimeCapsule
from .config import config_file, load_config, save_default_config
from .log import setup_logging
from .media import discover_shows
from .mounts import ensure_mounts, mountpoints_from_config
from .player import detect_ffmpeg, np_frombuffer
from .safe_zone import parse_safe_zone_offset
from .web_admin import DeferredAdminBridge, start_admin_if_enabled


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
            "If omitted, uses media_paths from the active config file "
            "(see config search order in docs/usage/configuration.md)"
        ),
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Run in an 800×600 resizable window (4:3) instead of fullscreen",
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
        "--channel-snow",
        action="store_true",
        help="CRT snow burst when tuning channels (off by default)",
    )
    parser.add_argument(
        "--shutdown-collapse",
        action="store_true",
        help="CRT vertical collapse animation on quit (off by default)",
    )
    parser.add_argument(
        "--analog-artifacts",
        action="store_true",
        help="Random brief static/tear/roll glitches on the show browser",
    )
    parser.add_argument(
        "--analog-artifact-rate",
        type=float,
        metavar="N",
        help="Analog glitches per minute when --analog-artifacts is on (default: config or 12)",
    )
    parser.add_argument(
        "--safe-zone",
        type=float,
        metavar="PCT",
        help="CRT overscan safe zone: uniform inset %% on all sides (0-25, default: config)",
    )
    parser.add_argument(
        "--safe-zone-offset",
        metavar="X,Y",
        help="Pixel shift of UI within the safe zone (+x right, +y down; default: config)",
    )
    parser.add_argument(
        "--skip-mounts",
        action="store_true",
        help="Do not mount remote shares from the config file",
    )
    parser.add_argument(
        "--screensaver",
        action="store_true",
        help="Enable the bouncing VHS logo screensaver after idle timeout",
    )
    parser.add_argument(
        "--screensaver-timeout",
        type=int,
        metavar="SEC",
        help="Seconds of menu inactivity before the screensaver starts (default: config or 300)",
    )
    parser.add_argument(
        "--rescan-only",
        action="store_true",
        help="Scan media paths, print summary, and exit (for hooks / validation)",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Enable the web admin UI (http://127.0.0.1:8765/ by default)",
    )
    parser.add_argument(
        "--admin-port",
        type=int,
        metavar="PORT",
        help="Web admin TCP port when --admin is set (default: config or 8765)",
    )
    args = parser.parse_args(argv)

    setup_logging()

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
        print(f"Configure paths / mounts in: {config_file()}")
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

    if args.rescan_only:
        sys.exit(0)

    admin_cfg = dict(cfg.get("admin") or {})
    if args.admin:
        admin_cfg["enabled"] = True

    admin_bridge: DeferredAdminBridge | None = None
    admin_server = None
    if admin_cfg.get("enabled"):
        admin_bridge = DeferredAdminBridge()
        admin_server = start_admin_if_enabled(
            admin_bridge,
            admin_cfg,
            port_override=args.admin_port,
            local_only=bool(args.windowed),
        )
        if admin_server is None:
            admin_bridge = None

    # When the server was started above, do not start again inside the app.
    admin_flag = None if admin_server else (True if args.admin else None)

    safe_zone_offset = None
    if args.safe_zone_offset:
        try:
            ox, oy = args.safe_zone_offset.split(",", 1)
            safe_zone_offset = parse_safe_zone_offset(
                {"offset_x": ox.strip(), "offset_y": oy.strip()}
            )
        except ValueError:
            parser.error("--safe-zone-offset expects X,Y (pixels)")

    app = TVTimeCapsule(
        media_paths,
        fullscreen=not args.windowed,
        force_43=args.force_43,
        scanlines=True if args.scanlines else None,
        screensaver=True if args.screensaver else None,
        screensaver_timeout=args.screensaver_timeout,
        admin=admin_flag,
        admin_port=args.admin_port,
        admin_bridge=admin_bridge,
        admin_server=admin_server,
        admin_local_only=bool(args.windowed),
        channel_snow=True if args.channel_snow else None,
        shutdown_collapse=True if args.shutdown_collapse else None,
        analog_artifacts=True if args.analog_artifacts else None,
        analog_artifact_rate=args.analog_artifact_rate,
        safe_zone=args.safe_zone,
        safe_zone_offset=safe_zone_offset,
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
