"""Command-line entry point."""

from __future__ import annotations

import argparse
import signal
import sys

import pygame

from .app import TVTimeCapsule
from .config import (
    WINDOW_SCALE_MAX,
    WINDOW_SCALE_MIN,
    config_file,
    load_config,
    save_default_config,
)
from .log import LOG, setup_logging
from .media import discover_library
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


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser (also used in tests)."""
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
        "--scale",
        type=int,
        choices=list(range(WINDOW_SCALE_MIN, WINDOW_SCALE_MAX + 1)),
        metavar="N",
        help=(
            f"Windowed integer scale of the 640×480 canvas "
            f"({WINDOW_SCALE_MIN}–{WINDOW_SCALE_MAX} → "
            f"{640 * WINDOW_SCALE_MIN}×{480 * WINDOW_SCALE_MIN} … "
            f"{640 * WINDOW_SCALE_MAX}×{480 * WINDOW_SCALE_MAX}). "
            "Implies --windowed"
        ),
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
        "--channel-snow",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable channel-tune static burst (default: config)",
    )
    parser.add_argument(
        "--shutdown-collapse",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable CRT shutdown collapse on quit (default: config)",
    )
    parser.add_argument(
        "--analog-artifacts",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable analog glitches on the show browser (default: config)",
    )
    parser.add_argument(
        "--analog-artifact-rate",
        type=float,
        metavar="N",
        help="Analog glitches per minute when analog artifacts are on (default: config or 12)",
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
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable the VHS logo screensaver (default: config)",
    )
    parser.add_argument(
        "--screensaver-timeout",
        type=int,
        metavar="SEC",
        help="Seconds of menu inactivity before the screensaver starts (default: config)",
    )
    parser.add_argument(
        "--rescan-only",
        action="store_true",
        help="Scan media paths, print summary, and exit (for hooks / validation)",
    )
    parser.add_argument(
        "--admin",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable the web admin UI (default: config)",
    )
    parser.add_argument(
        "--admin-port",
        type=int,
        metavar="PORT",
        help="Web admin TCP port (default: config or 8765)",
    )
    return parser


def _is_raspberry_pi() -> bool:
    """Return True when running on a Raspberry Pi."""
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path) as f:
                if "raspberry pi" in f.read().lower():
                    return True
        except (FileNotFoundError, OSError):
            continue
    return False


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging()

    def _on_signal(signum, _frame):
        LOG.info("received signal %s", signum)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

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

    discovery = discover_library(media_paths)
    shows = discovery.get("shows") or {}
    movies = discovery.get("movies") or {}
    layout = discovery.get("layout", "legacy")

    if not shows and not movies:
        print(f"No shows or movies found in: {', '.join(media_paths)}")
        print("Expected: <media-dir>/Show Name/s01/s01e01.mp4")
        print("Or split layout: <media-dir>/shows/ ... and <media-dir>/movies/ ...")
        print(f"Configure paths / mounts in: {config_file()}")
        sys.exit(1)

    total_eps = sum(
        len(season["episodes"])
        for show in shows.values()
        for season in show["seasons"].values()
    )
    print(f"Layout: {layout}")
    print(f"Found {len(shows)} show(s), {total_eps} total episode(s), {len(movies)} movie(s)")
    for name, show in shows.items():
        for s_num, s_data in sorted(show["seasons"].items()):
            n = len(s_data["episodes"])
            thumb = "[ok]" if s_data.get("thumbnail") else " [ ]"
            print(f"  {name} -- S-{s_num:02d}: {n} episode(s) {thumb}")
    if movies:
        print("Movies:")
        for key in discovery.get("movie_names") or sorted(movies.keys()):
            movie = movies[key]
            thumb = "[ok]" if movie.get("thumbnail") else " [ ]"
            print(f"  {movie.get('title') or key} {thumb}")

    if args.rescan_only:
        sys.exit(0)

    windowed = bool(args.windowed or args.scale)

    admin_cfg = dict(cfg.get("admin") or {})
    if args.admin is not None:
        admin_cfg["enabled"] = bool(args.admin)

    admin_bridge: DeferredAdminBridge | None = None
    admin_server = None
    if admin_cfg.get("enabled"):
        admin_bridge = DeferredAdminBridge()
        admin_server = start_admin_if_enabled(
            admin_bridge,
            admin_cfg,
            port_override=args.admin_port,
            local_only=windowed,
        )
        if admin_server is None:
            admin_bridge = None

    # When the server was started above, do not start again inside the app.
    admin_override = args.admin

    safe_zone_offset = None
    if args.safe_zone_offset:
        try:
            ox, oy = args.safe_zone_offset.split(",", 1)
            safe_zone_offset = parse_safe_zone_offset(
                {"offset_x": ox.strip(), "offset_y": oy.strip()}
            )
        except ValueError:
            parser.error("--safe-zone-offset expects X,Y (pixels)")

    safe_zone_override = args.safe_zone
    if safe_zone_override is None and windowed:
        # Windowed dev mode: no overscan padding unless --safe-zone is explicit.
        safe_zone_override = 0.0

    app = TVTimeCapsule(
        media_paths,
        fullscreen=not windowed,
        force_43=args.force_43,
        window_scale=args.scale,
        screensaver=args.screensaver,
        screensaver_timeout=args.screensaver_timeout,
        admin=admin_override,
        admin_port=args.admin_port,
        admin_bridge=admin_bridge,
        admin_server=admin_server,
        admin_local_only=windowed,
        channel_snow=args.channel_snow,
        shutdown_collapse=args.shutdown_collapse,
        analog_artifacts=args.analog_artifacts,
        analog_artifact_rate=args.analog_artifact_rate,
        safe_zone=safe_zone_override,
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

    # Start systemd watchdog on Raspberry Pi (production hardware only).
    watchdog_started = False
    if _is_raspberry_pi():
        try:
            from .systemd_watchdog import start_watchdog_thread

            start_watchdog_thread(interval_sec=10.0)
            watchdog_started = True
            LOG.info("systemd watchdog enabled (10s interval)")
        except ImportError:
            LOG.debug("systemd watchdog not available (sdnotify not installed)")
        except Exception as e:
            LOG.debug("systemd watchdog initialization skipped: %s", e)

    try:
        app.run()
    except KeyboardInterrupt:
        LOG.info("interrupted (Ctrl+C)")
    finally:
        if watchdog_started:
            try:
                from .systemd_watchdog import stop_watchdog_thread

                stop_watchdog_thread()
                LOG.debug("systemd watchdog stopped")
            except Exception:
                pass
        if admin_server is not None:
            admin_server.stop()
        if pygame.get_init():
            pygame.quit()


if __name__ == "__main__":
    main()
