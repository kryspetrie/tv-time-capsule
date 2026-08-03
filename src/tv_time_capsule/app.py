"""Main pygame application UI and event loop."""

from __future__ import annotations

import json
import os
import subprocess
import warnings
from contextlib import contextmanager
from datetime import datetime

import pygame

from .admin_api import (
    effective_media_paths,
    library_summary,
    library_tree_from_discovery,
    scan_paths,
    verify_media_path,
    verify_mount_entry,
)
from .analog_artifacts import AnalogArtifacts
from .channel_fx import FX_DURATION_MS, ChannelChangeFX
from .channels import build_channel_lineup, show_at_channel
from .config import (
    C,
    CHANNEL_ERROR_MS,
    config_file,
    load_config,
    parse_config,
    save_config,
    CHANNEL_FLASH_MS,
    CHANNEL_PENDING_MS,
    CHANNEL_TIMEOUT_MS,
    MARQUEE_DELAY_MS,
    MARQUEE_END_PAUSE_MS,
    MARQUEE_SPEED_PX_S,
    OVERLAY_SHOW_MS,
    PLAY_INPUT_GRACE_MS,
    PROGRESS_SEEK_S,
    SCREEN_H,
    SCREEN_W,
    STACK_VISIBLE,
    WINDOW_DEFAULT_H,
    WINDOW_DEFAULT_W,
    WINDOW_MIN_H,
    WINDOW_MIN_W,
)
from .fonts import enable_freetype_fallback, make_font
from .gamepad import (
    GAMEPAD_ACTIONS,
    GAMEPAD_CONFIG_ROWS,
    GamepadHandler,
    add_gamepad_binding,
    bindings_for_action,
    capture_binding_from_event,
    format_action_bindings,
    load_gamepad_bindings,
    remove_gamepad_binding,
    serialize_gamepad_bindings,
)
from .kids_mode import kids_resume_season
from .keymap import (
    KEY_ACTIONS,
    KEY_CONFIG_ROWS,
    add_binding,
    any_key_pressed,
    digit_for_key,
    format_action_keys,
    key_display_name,
    keymap_for_display,
    keys_for_action,
    key_matches,
    load_keymap,
    remove_binding,
    serialize_keymap,
)
from .log import LOG
from .media import directory_signature, discover_library, is_media_present
from .library import Library
from .movie_nav import (
    band_has_titles,
    first_letter_in_band,
    index_of_letter,
    letter_bucket,
    present_letters,
)
from .dial_nav import DialKind, classify_dial, page_cursor
from .playback_cache import PlaybackCache
from .player import (
    EmbeddedPlayer,
    detect_ffmpeg,
    detect_ffplay,
    detect_omxplayer,
    is_pi,
    np_frombuffer,
)
from .screensaver import VHS_LOGO_PATH, VHSScreensaver
from .safe_zone import (
    SafeZoneMargins,
    SafeZoneOffset,
    SafeZoneRect,
    adjust_margins_uniform,
    clamp_offset,
    parse_safe_zone,
    parse_safe_zone_offset,
    playback_hud_rect,
    playback_hud_scale,
    safe_zone_enabled,
    safe_zone_frame,
    safe_zone_to_config,
)
from .test_patterns import is_show_list_test_dial, pattern_asset_path
from .state import (
    clear_resume_ep,
    reset_episode_progress,
    get_episode_position,
    get_watched_episodes,
    load_state,
    mark_episode_watched,
    save_state,
    set_episode_position,
    watch_summary,
)
from .web_admin import AdminServer, DeferredAdminBridge, start_admin_if_enabled

FOOTER_BAR_H = 34
NAV_BAR_H = 28
HEADER_BAR_H = 48
KIDS_NAV_BAR_H = 44
KIDS_STACK_VISIBLE = 3
LIBRARY_THUMB_CYCLE_MS = 1500
LIBRARY_THUMB_VISIBLE = 2
LIBRARY_THUMB_GAP = 8
LIBRARY_SIDEBAR_W = 200
LIBRARY_THUMB_ASPECT = (4, 3)
CAROUSEL_TRANSITION_MS = 2000
CAROUSEL_CENTER_FRAC = 0.55
CAROUSEL_SIDE_SCALE = 0.5
HUD_PAD = 12
HUD_TOP_BAR_H = 50
HUD_SCRUB_H = 8
HUD_SCRUB_TRACK_H = 32
HUD_SCRUB_DOT_R = 9
HUD_VOL_BAR_W = 14
HUD_VOL_BAR_H = 32
SAFE_ZONE_MARGIN_STEP = 0.5
SAFE_ZONE_OFFSET_STEP = 2

# SDL window events (pygame 2.0.2+); absent on some builds — close still arrives as QUIT.
_PYGAME_WINDOWEVENT = getattr(pygame, "WINDOWEVENT", None)
_PYGAME_WINDOWEVENT_CLOSE = getattr(pygame, "WINDOWEVENT_CLOSE", None)


class TVTimeCapsule:
    SHOW_LIST = 0
    SEASON_SELECT = 1
    EPISODE_SELECT = 2
    KEY_CONFIG = 3
    KEY_CAPTURE = 4
    PLAYING = 5
    CONFIRM_EXIT = 6
    SAFE_ZONE_EDIT = 7
    LIBRARY_SELECT = 8
    MOVIE_LIST = 9
    GAMEPAD_CONFIG = 11
    GAMEPAD_CAPTURE = 12

    def __init__(
        self,
        media_paths,
        fullscreen=True,
        force_43=False,
        screensaver=None,
        screensaver_timeout=None,
        admin=None,
        admin_port=None,
        admin_bridge=None,
        admin_server=None,
        admin_local_only=False,
        channel_snow=None,
        shutdown_collapse=None,
        analog_artifacts=None,
        analog_artifact_rate=None,
        safe_zone=None,
        safe_zone_offset=None,
    ):
        pygame.init()

        # Probe whether pygame.font works. On Python 3.14+ it fails with a
        # circular-import error; we fall back to _freetype. The failure is
        # expected, so silence pygame's noisy RuntimeWarning during the probe.
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pygame.font.Font(None, 24)
        except Exception:
            enable_freetype_fallback()

        self.fullscreen = fullscreen
        self.force_43 = force_43
        self._screensaver_override = screensaver
        self._screensaver_timeout_override = screensaver_timeout
        self._channel_snow_override = channel_snow
        self._shutdown_collapse_override = shutdown_collapse
        self._analog_artifacts_override = analog_artifacts
        self._analog_artifact_rate_override = analog_artifact_rate
        self._safe_zone_override = safe_zone
        self._safe_zone_offset_override = safe_zone_offset

        self.media_paths = media_paths if isinstance(media_paths, list) else [media_paths]
        self.state = load_state()
        self.config = load_config()
        self._device_name = self.config.get("network", {}).get("mdns_hostname", "vintage-tv")
        self._init_safe_zone_state()

        # Logical canvas (safe-zone padded) is drawn offscreen and scaled to the OS window.
        self.sw = SCREEN_W
        self.sh = SCREEN_H
        self._omx_overlay = False
        self.framebuffer: pygame.Surface | None = None
        self.canvas = None
        self._init_display_window()

        pygame.display.set_caption("TV Time Capsule")
        pygame.mouse.set_visible(not fullscreen)

        # Detect video player
        ffmpeg_path = detect_ffmpeg()
        ffplay_path = detect_ffplay()
        omx_cmd = detect_omxplayer() if is_pi() else None

        if ffmpeg_path and np_frombuffer is not None:
            # Embedded FFmpeg playback (video always native 640×480)
            self.player = EmbeddedPlayer(SCREEN_W, SCREEN_H)
            self.player.ffmpeg_path = ffmpeg_path
            self.player.ffplay_path = ffplay_path
            self.player_cmd = ffmpeg_path
            self.embedded_player = True
        elif omx_cmd:
            # Omxplayer fallback on Pi — transparent overlay canvas
            self._enable_omx_overlay()
            self.player = EmbeddedPlayer(SCREEN_W, SCREEN_H)
            self.player.use_omx = True
            self.player.omx_cmd = omx_cmd
            self.player_cmd = omx_cmd
            self.embedded_player = True
        else:
            self.player = None
            self.player_cmd = None
            self.embedded_player = False

        # ─── Font hierarchy: 3 sizes only ───
        self.font_lg = make_font(60)    # Large: channel numbers, splash, key config values
        self.font_md = make_font(36)    # Medium: titles, labels, card text
        self.font_sm = make_font(24)    # Small: info, hints, footer

        if "keymap" in self.state:
            if not self.config.get("keymap"):
                self.config["keymap"] = self.state.pop("keymap")
                save_config(self.config)
            else:
                self.state.pop("keymap", None)
            save_state(self.state)
        self.keymap = load_keymap(self.config)
        self._key_lookup: dict[int, str] = {}
        self._rebuild_key_lookup()
        pb_cfg = self.config.get("playback") or {}
        self._autoplay_mode = pb_cfg.get("autoplay", "off")
        self._autoplay_countdown = pb_cfg.get("autoplay_countdown_seconds", 5)
        self._now_playing_splash = bool(pb_cfg.get("now_playing_splash", True))
        try:
            splash_seconds = float(pb_cfg.get("now_playing_splash_seconds", 1.5))
        except (TypeError, ValueError):
            splash_seconds = 1.5
        splash_seconds = max(0.0, min(30.0, splash_seconds))
        self._now_playing_splash_ms = int(splash_seconds * 1000)
        self._hw_decode_mode = pb_cfg.get("hw_decode", "auto")
        self._playback_cache = PlaybackCache(self.config)
        self._playing_source_path: str | None = None
        self._playback_allow_hot_swap = True
        self._playback_cache_suppressed = False
        self._playback_cache_switched = False
        self._load_kids_mode_config()
        ui_cfg = self.config.get("ui") or {}
        self._footer_hints_enabled = bool(ui_cfg.get("footer_hints", True))
        snow = (
            bool(channel_snow)
            if channel_snow is not None
            else bool(ui_cfg.get("channel_snow", False))
        )
        shutdown = (
            bool(shutdown_collapse)
            if shutdown_collapse is not None
            else bool(ui_cfg.get("shutdown_collapse", False))
        )
        self._channel_fx = ChannelChangeFX(
            snow=snow,
            shutdown=shutdown,
            audio=ui_cfg.get("channel_snow_audio", snow),
        )
        if analog_artifacts is not None:
            artifacts_on = bool(analog_artifacts)
        else:
            artifacts_on = bool(ui_cfg.get("analog_artifacts", False))
        if analog_artifact_rate is not None:
            artifact_rate = float(analog_artifact_rate)
        else:
            artifact_rate = float(ui_cfg.get("analog_artifact_rate", 12))
        self._analog_artifacts = AnalogArtifacts(
            enabled=artifacts_on,
            rate_per_minute=artifact_rate,
        )
        self._show_list_test_pattern: str | None = None
        gp_cfg = self.config.get("gamepad") or {}
        gp_bindings = load_gamepad_bindings(self.config)
        self._gamepad_bindings = gp_bindings
        self._gamepad = GamepadHandler(
            enabled=gp_cfg.get("enabled", True),
            bindings=gp_bindings,
        )
        self._gamepad_count = self._gamepad.init()
        self._gamepad_config_cursor = 0
        self._gamepad_capture_axis_ready = True
        # Most recent input device — drives help screen keyboard vs gamepad labels.
        self._last_input_device = "keyboard"
        ss_cfg = self.config.get("screensaver") or {}
        if screensaver is not None:
            self._screensaver_enabled = bool(screensaver)
        else:
            self._screensaver_enabled = bool(ss_cfg.get("enabled", False))
        if screensaver_timeout is not None:
            timeout_s = max(10, int(screensaver_timeout))
        else:
            try:
                timeout_s = max(10, int(ss_cfg.get("timeout_seconds", 300)))
            except (TypeError, ValueError):
                timeout_s = 300
        self._screensaver_timeout_ms = timeout_s * 1000
        self._screensaver = None
        self._screensaver_active = False
        self._ui_layout_depth = 0
        self._last_activity_ms = 0
        self.running = True
        self.clock = pygame.time.Clock()

        self.view = self.SHOW_LIST
        self.cursor = 0
        self.config_cursor = 0
        self._playback_browse_view = self.SHOW_LIST
        self._playback_browse_cursor = 0
        self._handling_episode_finish = False
        self._ignore_quit_until_ms = 0

        # Channel number input
        self.channel_digits = ""
        self.channel_timer = 0
        self.channel_flash = ""
        self.channel_flash_time = 0
        self.channel_error = ""
        self.channel_error_time = 0
        self._mode_toast_message = ""
        self._mode_toast_until = 0
        self._confirm_exit_yes = False
        self._confirm_exit_return_view = self.SHOW_LIST
        self._safe_zone_edit_mode = "zoom"
        self._safe_zone_save_prompt = False
        self._safe_zone_save_yes = True
        self._safe_zone_return_view = self.SHOW_LIST
        self._safe_zone_backup: tuple[SafeZoneMargins, SafeZoneOffset] | None = None
        self._sz_edit_margins = SafeZoneMargins()
        self._sz_edit_offset = SafeZoneOffset()
        self._pending_canvas_size: tuple[int, int] | None = None
        self._pending_safe_zone_frame = None
        self._in_channel_tune = False
        self._deferred_splash = None

        # Playback state
        self.playing_show = None
        self.playing_season = None
        self.playing_episode = None
        self.playing_episodes = []
        self.playing_index = 0
        self.volume_overlay_timer = 0
        self.progress_overlay_timer = 0

        self.library_layout = "legacy"
        self.shows: dict = {}
        self.movies: dict[str, dict] = {}
        self.movie_names: list[str] = []
        self.show_names: list[str] = []
        self.show_uuids: dict[str, str] = {}   # show_name → uuid
        self.movie_uuids: dict[str, str] = {}  # movie_key → uuid
        self._uuid_to_show: dict[str, str] = {}  # uuid → show_name
        self._uuid_to_movie: dict[str, str] = {}  # uuid → movie_key
        self.library: Library = Library.empty()  # canonical aggregate
        self._show_channel: dict[str, int] = {}
        self._channel_show: dict[int, str] = {}
        self._movie_channel: dict[str, int] = {}
        self._channel_movie: dict[int, str] = {}
        self._letter_menu_open = False
        self._letter_menu_cursor = 0
        self._load_kids_allowlist()
        self._apply_library_discovery(set_initial_view=True)
        if self._kids_mode_active:
            self._apply_kids_startup_view()
        self.cur_show = None
        self.cur_season = None
        self.cur_movie: str | None = None
        self._playing_is_movie = False

        lib_cfg = self.config.get("library") or {}
        self._rescan_interval_ms = int(lib_cfg.get("rescan_interval_seconds", 0)) * 1000
        self._rescan_long_press_ms = int(lib_cfg.get("rescan_long_press_ms", 800))
        self._last_rescan_ms = pygame.time.get_ticks()
        self._rescan_banner_until = 0
        self._media_signatures: dict[str, tuple[int, int, float]] = {}
        self._reset_hold_start = 0
        self._reset_rescan_fired = False

        self._playback_stalled = False
        self._stall_auto_retry_done = False
        self._stall_resume_pos = 0.0
        self._pending_admin_rescan = False
        self._admin_server: AdminServer | None = admin_server
        self._admin_bridge: DeferredAdminBridge | None = admin_bridge
        self._admin_enabled_override = admin
        self._admin_port_override = admin_port
        self._admin_local_only = bool(admin_local_only)

        self._img_cache = {}
        self._img_cache_order = []  # LRU tracking for Pi memory limits
        self._img_cache_max = 16    # Room for multi-thumb library carousel (Pi-safe)
        self._duration_cache = {}   # Lazy ffprobe duration cache (path → "MM:SS")

        # Marquee: scroll overflowing episode titles on the selected row
        self._marquee_key = None
        self._marquee_start = 0
        self._header_marquee_key = None
        self._header_marquee_start = 0

        # Kids library picker: cycle show/movie thumbnails on the big tiles
        self._library_shows_thumb_idx = 0
        self._library_movies_thumb_idx = 0
        self._library_thumb_last_advance = 0

        # Carousel view state
        self._kids_carousel_active = False
        self._carousel_transition_start = 0

        # Ignore play/seek/pause keys briefly after starting an episode
        self._play_input_grace_until = 0

        pygame.key.set_repeat(400, 130)

        if self._admin_bridge is not None:
            self._admin_bridge.attach(self)
        elif self._admin_server is None:
            self._start_admin_server()

    def _load_kids_mode_config(self) -> None:
        km_cfg = self.config.get("kids_mode") or {}
        style = str(km_cfg.get("browse_style", "card"))
        # Legacy alias: "compact" → "card"
        if style == "compact":
            style = "card"
        if style not in ("card", "full"):
            style = "card"
        self._kids_browse_style = style
        if "enabled" in km_cfg:
            self._kids_mode_active = bool(km_cfg["enabled"])
        else:
            self._kids_mode_active = bool(km_cfg.get("default_enabled", False))
        self._load_kids_allowlist()

    def _load_kids_allowlist(self) -> None:
        km_cfg = self.config.get("kids_mode") or {}
        if "allowlist" not in km_cfg:
            self._kids_allowlist = None
            return
        al = km_cfg.get("allowlist") or {}
        if not isinstance(al, dict):
            al = {}
        shows = al.get("shows") or []
        movies = al.get("movies") or []
        self._kids_allowlist = {
            "shows": [str(s) for s in shows] if isinstance(shows, list) else [],
            "movies": [str(m) for m in movies] if isinstance(movies, list) else [],
        }

    def _persist_kids_allowlist(self) -> None:
        if self._kids_allowlist is None:
            return
        km = dict(self.config.get("kids_mode") or {})
        km["allowlist"] = {
            "shows": list(self._kids_allowlist.get("shows") or []),
            "movies": list(self._kids_allowlist.get("movies") or []),
        }
        self.config["kids_mode"] = km
        save_config(self.config)

    def _kids_filtered_show_names(self) -> list[str]:
        if self._kids_allowlist is None:
            return list(self.show_names)
        allowed = set(self._kids_allowlist.get("shows") or [])
        return [n for n in self.show_names if n in allowed]

    def _kids_filtered_movie_names(self) -> list[str]:
        if self._kids_allowlist is None:
            return list(self.movie_names)
        allowed = set(self._kids_allowlist.get("movies") or [])
        return [n for n in self.movie_names if n in allowed]

    def _browse_show_names(self) -> list[str]:
        if self._kids_mode_active:
            return self._kids_filtered_show_names()
        return list(self.show_names)

    def _browse_movie_names(self) -> list[str]:
        if self._kids_mode_active:
            return self._kids_filtered_movie_names()
        return list(self.movie_names)

    def _title_kids_tagged(self, *, show: str | None = None, movie: str | None = None) -> bool:
        if self._kids_allowlist is None:
            return False
        if show is not None:
            return show in (self._kids_allowlist.get("shows") or [])
        if movie is not None:
            return movie in (self._kids_allowlist.get("movies") or [])
        return False

    def _toggle_kids_tag_current(self) -> None:
        if self._kids_mode_active:
            return
        if self.view == self.SHOW_LIST:
            names = self.show_names
            if not names or self.cursor >= len(names):
                return
            key = names[self.cursor]
            kind = "shows"
        elif self.view == self.MOVIE_LIST:
            names = self.movie_names
            if not names or self.cursor >= len(names):
                return
            key = names[self.cursor]
            kind = "movies"
        else:
            return

        if self._kids_allowlist is None:
            self._kids_allowlist = {"shows": [], "movies": []}
        bucket = list(self._kids_allowlist.get(kind) or [])
        if key in bucket:
            bucket = [x for x in bucket if x != key]
            tagged = False
        else:
            bucket.append(key)
            tagged = True
        self._kids_allowlist[kind] = bucket
        self._persist_kids_allowlist()
        self._mode_toast_message = "Kids: on" if tagged else "Kids: off"
        self._mode_toast_until = pygame.time.get_ticks() + CHANNEL_ERROR_MS

    def _persist_kids_mode(self) -> None:
        km = dict(self.config.get("kids_mode") or {})
        km["enabled"] = self._kids_mode_active
        self.config["kids_mode"] = km
        save_config(self.config)

    def _kids_browse_view(self) -> int:
        return self._view_for_library_layout()

    def _apply_kids_startup_view(self) -> None:
        if not self._kids_mode_active:
            return
        self.view = self._view_for_library_layout()
        if self.view == self.SHOW_LIST:
            names = self._browse_show_names()
            self.cursor = min(self.cursor, max(0, len(names) - 1))
        elif self.view == self.MOVIE_LIST:
            names = self._browse_movie_names()
            self.cursor = min(self.cursor, max(0, len(names) - 1))
        else:
            self.cursor = 0

    def _toggle_kids_mode(self) -> None:
        self._kids_mode_active = not self._kids_mode_active
        self._mode_toast_message = "Kids mode" if self._kids_mode_active else "Parent mode"
        self._mode_toast_until = pygame.time.get_ticks() + CHANNEL_ERROR_MS
        self.channel_digits = ""
        self.channel_timer = 0
        self._marquee_key = None
        if self.view == self.PLAYING:
            return
        if self.view in (self.KEY_CONFIG, self.KEY_CAPTURE):
            self.exit_key_config()
        if self.view in (self.GAMEPAD_CONFIG, self.GAMEPAD_CAPTURE):
            self.exit_gamepad_config()
        if self._kids_mode_active:
            self._apply_kids_startup_view()
        else:
            self.view = self._view_for_library_layout()
            self.cursor = 0
        self._persist_kids_mode()

    def _toggle_kids_view(self) -> None:
        """Switch between card and full browse views in kids mode."""
        if not self._kids_mode_active:
            return
        if self._kids_browse_style == "full":
            self._kids_browse_style = "card"
        else:
            self._kids_browse_style = "full"
        self._kids_carousel_active = False
        self._mode_toast_message = f"Kids view: {self._kids_browse_style}"
        self._mode_toast_until = pygame.time.get_ticks() + CHANNEL_ERROR_MS
        km = dict(self.config.get("kids_mode") or {})
        km["browse_style"] = self._kids_browse_style
        self.config["kids_mode"] = km
        save_config(self.config)
        # Switch to the matching browse view if we're on a kids-compatible screen
        if self.view == self.LIBRARY_SELECT:
            self._apply_kids_startup_view()

    def _toggle_kids_carousel(self) -> None:
        """Toggle carousel view on the kids library selector screen."""
        if not self._kids_mode_active:
            return
        if self.view != self.LIBRARY_SELECT:
            return
        self._kids_carousel_active = not self._kids_carousel_active
        self._carousel_transition_start = pygame.time.get_ticks()
        self._mode_toast_message = (
            "Carousel on" if self._kids_carousel_active else "Carousel off"
        )
        self._mode_toast_until = pygame.time.get_ticks() + CHANNEL_ERROR_MS

    def _parent_footer_visible(self) -> bool:
        """Bottom status bar (parent mode only)."""
        return not self._kids_mode_active and self._footer_hints_enabled

    def _persist_footer_hints(self) -> None:
        ui_cfg = dict(self.config.get("ui") or {})
        ui_cfg["footer_hints"] = self._footer_hints_enabled
        self.config["ui"] = ui_cfg
        save_config(self.config)

    def _toggle_footer_hints(self) -> None:
        if self._kids_mode_active:
            return
        self._footer_hints_enabled = not self._footer_hints_enabled
        self._mode_toast_message = (
            "Status bar on" if self._footer_hints_enabled else "Status bar off"
        )
        self._mode_toast_until = pygame.time.get_ticks() + CHANNEL_ERROR_MS
        self._persist_footer_hints()

    def _kids_play_show(self, show_name: str) -> None:
        if not self.player_cmd and not self.player:
            self.channel_error = "NO PLAYER"
            self.channel_error_time = pygame.time.get_ticks()
            return
        show = self.shows.get(show_name)
        if not show:
            return

        self.cur_show = show_name
        self._playing_is_movie = False
        self.cur_movie = None
        seasons = self.seasons_for_show(show_name)
        season = kids_resume_season(
            self.state, show_name, seasons, get_episode_position=get_episode_position
        )
        self.cur_season = season
        episodes = show.get("seasons", {}).get(season, {}).get("episodes", [])
        if not episodes:
            return

        watched_eps = get_watched_episodes(self.state, show_name, season)
        pos_ep, pos_secs = get_episode_position(self.state, show_name, season)
        if pos_ep is not None:
            start = next(
                (i for i, ep in enumerate(episodes) if ep["number"] == pos_ep),
                0,
            )
            resume_secs = pos_secs
        else:
            start = self._next_up_index(episodes, watched_eps, pos_ep=None)
            resume_secs = None

        self.playing_show = show_name
        self.playing_season = season
        self.playing_episodes = episodes
        self.playing_index = start
        if not self._start_current_episode(resume_secs=resume_secs, show_splash=True):
            self.cur_show = show_name

    def _play_movie_key(self, movie_key: str) -> None:
        if movie_key not in self.movie_names:
            return
        self.cursor = self.movie_names.index(movie_key)
        self.play_movie_from_cursor()

    def _kids_restore_browse_cursor(self) -> None:
        """Restore cursor position after playback in kids mode."""
        if self._kids_mode_active and self._playing_is_movie and self.cur_movie:
            names = self._browse_movie_names()
            if self.cur_movie in names:
                self.cursor = names.index(self.cur_movie)
        elif self._kids_mode_active and self.cur_show:
            names = self._browse_show_names()
            if self.cur_show in names:
                self.cursor = names.index(self.cur_show)

    def _apply_channel_lineup(self):
        """Order ``show_names`` and rebuild channel maps from config."""
        channels_cfg = self.config.get("channels") or {}
        ordered, show_to_ch, ch_to_show = build_channel_lineup(
            self.shows.keys(), channels_cfg
        )
        self.show_names = ordered
        self._show_channel = show_to_ch
        self._channel_show = ch_to_show

    def _apply_movie_lineup(self):
        """Order ``movie_names`` and rebuild movie channel maps."""
        channels_cfg = self.config.get("channels") or {}
        ordered, movie_to_ch, ch_to_movie = build_channel_lineup(
            self.movies.keys(), channels_cfg
        )
        self.movie_names = ordered
        self._movie_channel = movie_to_ch
        self._channel_movie = ch_to_movie

    def _view_for_library_layout(self) -> int:
        if self.library_layout == "split":
            return self.LIBRARY_SELECT
        if self.library_layout == "movies_only":
            return self.MOVIE_LIST
        return self.SHOW_LIST

    def _apply_library_discovery(
        self,
        discovery: dict | None = None,
        *,
        set_initial_view: bool = False,
    ) -> None:
        if discovery is None:
            discovery = discover_library(self.media_paths, device_name=self._device_name)
        self.library_layout = discovery.get("layout", "legacy")
        self.shows = discovery.get("shows") or {}
        self.movies = discovery.get("movies") or {}
        self.show_uuids = discovery.get("show_uuids") or {}
        self.movie_uuids = discovery.get("movie_uuids") or {}
        self._uuid_to_show = {v: k for k, v in self.show_uuids.items()}
        self._uuid_to_movie = {v: k for k, v in self.movie_uuids.items()}
        self._apply_channel_lineup()
        self._apply_movie_lineup()
        self.library = Library(
            shows=self.shows,
            movies=self.movies,
            show_names=tuple(self.show_names),
            movie_names=tuple(self.movie_names),
            show_uuids=self.show_uuids,
            movie_uuids=self.movie_uuids,
            layout=self.library_layout,
        )
        if set_initial_view:
            self.view = self._view_for_library_layout()
            self.cursor = 0

    def _display_channel(self, show_name: str) -> int:
        return self._show_channel.get(show_name, 0)

    def _display_movie_channel(self, movie_key: str) -> int:
        return self._movie_channel.get(movie_key, 0)

    def _is_split_library(self) -> bool:
        return self.library_layout == "split"

    def _movie_episode_entry(self, movie_key: str) -> dict:
        movie = self.movies[movie_key]
        return {
            "number": 1,
            "name": movie.get("title") or movie_key,
            "path": movie["path"],
            "thumbnail": movie.get("thumbnail"),
        }

    def _rescan_library(self) -> bool:
        """Re-scan media roots. Safe only while not playing video."""
        if self.view == self.PLAYING:
            return False

        # Check each media path for presence before scanning.
        # If no media is present (unplugged USB, unmounted share), preserve
        # the current in-memory library and don't prune.
        any_present = False
        for mp in self.media_paths:
            if is_media_present(mp, self._device_name):
                any_present = True
                break

        if not any_present:
            LOG.info("No media present — skipping rescan, preserving state")
            return False

        # Check directory signatures — skip expensive rescan if nothing changed.
        all_unchanged = True
        for mp in self.media_paths:
            sig = directory_signature(mp)
            cached = self._media_signatures.get(mp)
            if cached is None or sig != cached:
                all_unchanged = False
                self._media_signatures[mp] = sig
        if all_unchanged and self._media_signatures:
            LOG.debug("Media signatures unchanged — skipping rescan")
            return False

        prev_show = None
        prev_movie = None
        prev_view = self.view
        if self.view == self.SHOW_LIST and self.show_names and 0 <= self.cursor < len(
            self.show_names
        ):
            prev_show = self.show_names[self.cursor]
        if self.view == self.MOVIE_LIST and self.movie_names and 0 <= self.cursor < len(
            self.movie_names
        ):
            prev_movie = self.movie_names[self.cursor]

        discovery = discover_library(self.media_paths, device_name=self._device_name)
        self._apply_library_discovery(discovery)

        if prev_view == self.LIBRARY_SELECT and self.library_layout == "split":
            self.view = self.LIBRARY_SELECT
            self.cursor = max(0, min(1, self.cursor))
        elif prev_view == self.MOVIE_LIST or self.library_layout == "movies_only":
            self.view = self.MOVIE_LIST
            if not self.movie_names:
                self.cursor = 0
            elif prev_movie and prev_movie in self.movie_names:
                self.cursor = self.movie_names.index(prev_movie)
            else:
                self.cursor = min(self.cursor, len(self.movie_names) - 1)
        elif prev_view in (self.SHOW_LIST, self.SEASON_SELECT, self.EPISODE_SELECT):
            if self.library_layout == "split" and prev_view == self.SHOW_LIST:
                self.view = self.SHOW_LIST
            elif self.library_layout == "movies_only":
                self.view = self.MOVIE_LIST
            else:
                self.view = self.SHOW_LIST if prev_view == self.SHOW_LIST else prev_view
            if self.view == self.SHOW_LIST:
                if not self.show_names:
                    self.cursor = 0
                elif prev_show and prev_show in self.show_names:
                    self.cursor = self.show_names.index(prev_show)
                else:
                    self.cursor = min(self.cursor, len(self.show_names) - 1)
        else:
            self.view = self._view_for_library_layout()
            self.cursor = 0

        if self._kids_mode_active:
            self._apply_kids_startup_view()

        self._duration_cache.clear()
        self._img_cache.clear()
        self._img_cache_order.clear()
        self._library_shows_thumb_idx = 0
        self._library_movies_thumb_idx = 0
        self._library_thumb_last_advance = 0
        self._kids_carousel_active = False
        self._carousel_transition_start = 0
        self._last_rescan_ms = pygame.time.get_ticks()
        self._rescan_banner_until = self._last_rescan_ms + 1500
        return True

    def _rebuild_key_lookup(self) -> None:
        lookup: dict[int, str] = {}
        for action_id, _label in KEY_ACTIONS:
            for code in keys_for_action(self.keymap, action_id):
                lookup[code] = action_id
        self._key_lookup = lookup

    def _action_for_key(self, key: int) -> str | None:
        return self._key_lookup.get(key)

    def _persist_keymap(self) -> None:
        self.config["keymap"] = serialize_keymap(self.keymap)
        save_config(self.config)

    def _quit_allowed(self) -> bool:
        return not self._kids_mode_active

    def _arm_quit_grace(self, ms: int = 750) -> None:
        """Ignore stray ``pygame.QUIT`` events for a short window (decoder teardown)."""
        self._ignore_quit_until_ms = pygame.time.get_ticks() + max(0, ms)

    def _request_quit(self, *, source: str = "unknown") -> None:
        if not self._quit_allowed():
            LOG.debug("quit ignored in kids mode (source=%s)", source)
            return
        LOG.info("exiting (%s)", source)
        self.running = False

    def _handle_quit_event(self, source: str) -> None:
        """Handle ``pygame.QUIT`` — may be spurious after playback stops."""
        now = pygame.time.get_ticks()
        if now < self._ignore_quit_until_ms:
            LOG.warning("ignored spurious quit from %s", source)
            return
        self._request_quit(source=source)

    def _enter_confirm_exit(self) -> None:
        if not self._quit_allowed():
            return
        self._confirm_exit_return_view = self.view
        self._confirm_exit_yes = False
        self.view = self.CONFIRM_EXIT

    def _remember_playback_browse_state(self) -> None:
        if self.view != self.PLAYING:
            self._playback_browse_view = self.view
            self._playback_browse_cursor = self.cursor

    def _playback_return_view(self) -> int:
        if self._kids_mode_active:
            saved = getattr(self, "_playback_browse_view", self.PLAYING)
            if saved != self.PLAYING:
                return saved
            return self._kids_browse_view()
        if self._playing_is_movie:
            return self.MOVIE_LIST
        return self.EPISODE_SELECT

    def _restore_kids_browse_after_playback(self, *, return_movie: bool, movie_key: str | None) -> None:
        self.view = self._playback_return_view()
        if self._kids_mode_active:
            self._kids_restore_browse_cursor()
            return
        total = self.total_items()
        if return_movie and movie_key and movie_key in self.movie_names:
            self.cursor = self.movie_names.index(movie_key)
        elif self.cur_show and self.cur_show in self.show_names and self.view == self.SHOW_LIST:
            self.cursor = self.show_names.index(self.cur_show)
        elif total:
            saved = getattr(self, "_playback_browse_cursor", self.cursor)
            self.cursor = max(0, min(saved, total - 1))

    def _splash_show_label(self, show_key: str) -> str:
        if self._playing_is_movie:
            movie = self.movies.get(show_key, {})
            return movie.get("title") or show_key
        return show_key

    def _splash_channel(self) -> int:
        if self._playing_is_movie:
            return self._display_movie_channel(self.playing_show)
        return self.playing_index + 1

    def _stack_page_size_for_view(self) -> int:
        if self._kids_mode_active and self.view in (
            self.SHOW_LIST,
            self.MOVIE_LIST,
        ):
            if self._kids_browse_style == "full":
                return 1
            return KIDS_STACK_VISIBLE
        return STACK_VISIBLE

    def _page_browse(self, direction: int) -> None:
        """Flip the visible window by one page (± visible slot count)."""
        total = self.total_items()
        if total <= 0:
            return
        page_size = self._stack_page_size_for_view()
        self.cursor = page_cursor(self.cursor, total, page_size, direction)
        self._marquee_key = None
        self._clear_show_list_test_pattern()

    def _close_letter_menu(self) -> None:
        self._letter_menu_open = False
        self._letter_menu_cursor = 0

    def _letter_menu_titles(self) -> list[str]:
        if self.view == self.SHOW_LIST:
            return list(self.show_names)
        if self.view == self.MOVIE_LIST:
            return [
                (self.movies.get(k) or {}).get("title") or k for k in self.movie_names
            ]
        return []

    def _open_letter_menu(self) -> None:
        if self._kids_mode_active:
            self.channel_error = "Not Available"
            self.channel_error_time = pygame.time.get_ticks()
            return
        if self.view not in (self.SHOW_LIST, self.MOVIE_LIST):
            self.channel_error = "Not Available"
            self.channel_error_time = pygame.time.get_ticks()
            return
        titles = self._letter_menu_titles()
        letters = present_letters(titles)
        if not letters:
            self.channel_error = "No Letters"
            self.channel_error_time = pygame.time.get_ticks()
            return
        self._letter_menu_open = True
        # Start on the letter of the current title when possible.
        if self.view == self.SHOW_LIST and self.show_names:
            cur = letter_bucket(self.show_names[self.cursor % len(self.show_names)])
        elif self.view == self.MOVIE_LIST and self.movie_names:
            key = self.movie_names[self.cursor % len(self.movie_names)]
            cur = letter_bucket((self.movies.get(key) or {}).get("title") or key)
        else:
            cur = letters[0]
        self._letter_menu_cursor = letters.index(cur) if cur in letters else 0

    def _jump_browse_to_letter(self, letter: str) -> None:
        if self.view == self.SHOW_LIST:
            titles = self.show_names
            idx = index_of_letter(titles, letter)
        elif self.view == self.MOVIE_LIST:
            titles = [
                (self.movies.get(k) or {}).get("title") or k for k in self.movie_names
            ]
            idx = index_of_letter(titles, letter)
        else:
            return
        if idx is None:
            return
        self.cursor = idx
        self._marquee_key = None
        self._close_letter_menu()

    def _process_letter_menu_action(self, action: str) -> None:
        titles = self._letter_menu_titles()
        letters = present_letters(titles)
        if not letters:
            self._close_letter_menu()
            return
        if action in ("up", "left"):
            self._letter_menu_cursor = (self._letter_menu_cursor - 1) % len(letters)
        elif action in ("down", "right"):
            self._letter_menu_cursor = (self._letter_menu_cursor + 1) % len(letters)
        elif action == "select":
            self._jump_browse_to_letter(letters[self._letter_menu_cursor])
        elif action == "back":
            self._close_letter_menu()

    def _process_letter_menu_digit(self, digit: int) -> None:
        if digit == 0:
            self._close_letter_menu()
            return
        titles = self._letter_menu_titles()
        letter = first_letter_in_band(titles, str(digit))
        if letter is None:
            self.channel_error = f"No {digit}"
            self.channel_error_time = pygame.time.get_ticks()
            return
        self._jump_browse_to_letter(letter)

    def _draw_letter_menu(self) -> None:
        titles = self._letter_menu_titles()
        letters = present_letters(titles)
        if not letters:
            return
        overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        box_w, box_h = min(520, self.sw - 40), min(360, self.sh - 40)
        box_x = (self.sw - box_w) // 2
        box_y = (self.sh - box_h) // 2
        pygame.draw.rect(
            self.screen, C.BG_CARD, (box_x, box_y, box_w, box_h), border_radius=10
        )
        pygame.draw.rect(
            self.screen, C.CYAN, (box_x, box_y, box_w, box_h), 2, border_radius=10
        )

        title = self.font_md.render("JUMP TO LETTER", True, C.BRIGHT)
        self.screen.blit(
            title, title.get_rect(centerx=self.sw // 2, top=box_y + 16)
        )

        # Digit band legend
        legend_y = box_y + 56
        labels = {
            "1": "A-C", "2": "D-F", "3": "G-I", "4": "J-L", "5": "M-O",
            "6": "P-R", "7": "S-U", "8": "V-X", "9": "Y-Z/#",
        }
        for d in "123456789":
            active = band_has_titles(titles, d)
            color = C.GREEN if active else C.DIM
            surf = self.font_sm.render(f"{d}:{labels[d]}", True, color)
            col = (int(d) - 1) % 3
            row = (int(d) - 1) // 3
            x = box_x + 24 + col * ((box_w - 48) // 3)
            y = legend_y + row * 28
            self.screen.blit(surf, (x, y))

        focus = letters[self._letter_menu_cursor % len(letters)]
        focus_y = box_y + box_h // 2 + 20
        big = self.font_lg.render(focus, True, C.CYAN)
        big_rect = big.get_rect(centerx=self.sw // 2, centery=focus_y)
        self.screen.blit(big, big_rect)

        # Directional cue around the focused letter.
        arrow = self.font_lg.render("<", True, C.DIM)
        self.screen.blit(
            arrow,
            arrow.get_rect(right=big_rect.left - 18, centery=focus_y),
        )
        arrow = self.font_lg.render(">", True, C.DIM)
        self.screen.blit(
            arrow,
            arrow.get_rect(left=big_rect.right + 18, centery=focus_y),
        )

        # Present letters strip
        strip = "  ".join(
            f"[{L}]" if L == focus else L for L in letters
        )
        while self.font_sm.size(strip)[0] > box_w - 40 and len(strip) > 10:
            strip = strip[:-1]
        strip_surf = self.font_sm.render(strip, True, C.DIM)
        self.screen.blit(
            strip_surf,
            strip_surf.get_rect(centerx=self.sw // 2, bottom=box_y + box_h - 48),
        )
        hint = self.font_sm.render("< > choose  |  0 back", True, C.DIM)
        self.screen.blit(
            hint, hint.get_rect(centerx=self.sw // 2, bottom=box_y + box_h - 16)
        )

    def _append_dial_digit(self, digit: int) -> None:
        """Append a digit using 0 / 0x / 00x timing rules."""
        d = str(digit)
        now = pygame.time.get_ticks()
        if self._letter_menu_open:
            self._process_letter_menu_digit(digit)
            return

        buf = self.channel_digits
        if not buf:
            self.channel_digits = d
            self.channel_timer = now
            return

        if buf == "0":
            if d == "0":
                self.channel_digits = "00"
                self.channel_timer = now
                return
            self.channel_digits = "0" + d
            if d in ("1", "2"):
                # Brief pause so the second digit is visible before paging.
                self.channel_timer = now
                return
            self._commit_dial_digits(immediate=True)
            return

        if buf == "00":
            self.channel_digits = "00" + d
            self._commit_dial_digits(immediate=True)
            return

        if buf in ("01", "02"):
            # Extra digit while page action is pending — treat as invalid.
            self.channel_digits = buf + d
            self._commit_dial_digits(immediate=True)
            return

        if buf.startswith("0"):
            # Should not accumulate further; commit as invalid.
            self.channel_digits = buf + d
            self._commit_dial_digits(immediate=True)
            return

        self.channel_digits = buf + d
        self.channel_timer = now

    def _commit_dial_digits(self, *, immediate: bool = False) -> None:
        digits = self.channel_digits
        self.channel_digits = ""
        self.channel_timer = 0
        if not digits:
            return
        result = classify_dial(digits)
        if result.kind == DialKind.BACK:
            if self._letter_menu_open:
                self._close_letter_menu()
            else:
                self._process_browse_action("back")
            return
        if result.kind == DialKind.PAGE_UP:
            self._page_browse(-1)
            return
        if result.kind == DialKind.PAGE_DOWN:
            self._page_browse(1)
            return
        if result.kind == DialKind.LETTER_MENU:
            self._open_letter_menu()
            return
        if result.kind == DialKind.TEST_PATTERN:
            if self._test_pattern_dial_allowed():
                if self._commit_show_list_test_pattern(digits):
                    return
            self.channel_error = f"Ch {digits} Not Found"
            self.channel_error_time = pygame.time.get_ticks()
            return
        if result.kind == DialKind.CHANNEL and result.channel is not None:
            success = self.jump_to_channel(result.channel)
            if success:
                self.channel_flash = str(result.channel)
                self.channel_flash_time = pygame.time.get_ticks()
            return
        self.channel_error = f"Ch {digits} Not Found"
        self.channel_error_time = pygame.time.get_ticks()

    def _tick_dial_timeout(self) -> None:
        if not self.channel_digits or self.channel_timer <= 0:
            return
        elapsed = pygame.time.get_ticks() - self.channel_timer
        digits = self.channel_digits
        # Page flips use a short hold so "01"/"02" are visible on screen.
        if digits in ("01", "02"):
            if elapsed >= CHANNEL_PENDING_MS:
                self._commit_dial_digits()
            return
        if elapsed < CHANNEL_TIMEOUT_MS:
            return
        # Timeout-commit bare 0, 00, or normal channel buffers.
        if digits in ("0", "00") or not digits.startswith("0"):
            self._commit_dial_digits()
        else:
            self.channel_digits = ""
            self.channel_timer = 0

    def _draw_rescan_banner(self):
        if pygame.time.get_ticks() >= self._rescan_banner_until:
            return
        self._draw_popup_banner("Updating channels...")

    def _tick_reset_hold(self):
        """Long-press reset key triggers library rescan."""
        if self._reset_hold_start <= 0 or self._reset_rescan_fired:
            return
        if self.view == self.PLAYING:
            return
        if not any_key_pressed(keys_for_action(self.keymap, "reset")):
            return
        now = pygame.time.get_ticks()
        if now - self._reset_hold_start >= self._rescan_long_press_ms:
            self._reset_rescan_fired = True
            if self._rescan_library():
                self.channel_error = "Library updated"
                self.channel_error_time = now

    def _tick_periodic_rescan(self):
        if self._pending_admin_rescan:
            self._pending_admin_rescan = False
            if self.view != self.PLAYING:
                if self._rescan_library():
                    self.channel_error = "Library updated"
                    self.channel_error_time = pygame.time.get_ticks()
            return
        if self._rescan_interval_ms <= 0:
            return
        if self.view != self.SHOW_LIST and self.view != self.MOVIE_LIST and self.view != self.LIBRARY_SELECT:
            return
        now = pygame.time.get_ticks()
        if now - self._last_rescan_ms >= self._rescan_interval_ms:
            self._rescan_library()

    # ─── Duration lookup ─────────────────────────────────────────────────

    def _get_duration(self, filepath):
        """Lazy ffprobe duration lookup, cached. Returns 'MM:SS' or empty string."""
        if filepath in self._duration_cache:
            return self._duration_cache[filepath]
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", filepath],
                capture_output=True, text=True, timeout=3
            )
            info = json.loads(result.stdout)
            dur = float(info.get("format", {}).get("duration", 0))
            if dur > 0:
                m, s = divmod(int(dur), 60)
                if dur >= 3600:
                    h, m = divmod(m, 60)
                    text = f"{h}:{m:02d}:{s:02d}"
                else:
                    text = f"{m}:{s:02d}"
            else:
                text = ""
        except Exception:
            text = ""
        self._duration_cache[filepath] = text
        return text

    # ─── Image handling ────────────────────────────────────────────────────

    def load_image(self, path, max_size, *, cover=False):
        key = (path, max_size, "cover" if cover else "fit")
        if key in self._img_cache:
            # Move to end of LRU order
            if key in self._img_cache_order:
                self._img_cache_order.remove(key)
            self._img_cache_order.append(key)
            return self._img_cache[key]

        if not path or not os.path.isfile(path):
            self._img_cache[key] = None
            return None

        try:
            img = self._load_image_surface(
                path,
                max_pixels=min(2048, max(max_size[0], max_size[1]) * 2),
            )
            if img is None:
                self._img_cache[key] = None
                return None
            src_w, src_h = img.get_size()
            if src_w == 0 or src_h == 0:
                self._img_cache[key] = None
                return None
            if cover:
                s = max(max_size[0] / src_w, max_size[1] / src_h)
            else:
                s = min(max_size[0] / src_w, max_size[1] / src_h)
            new_w = max(1, int(src_w * s))
            new_h = max(1, int(src_h * s))
            # Use scale (not smoothscale) for ARMv6 / Pi Model B compatibility
            img = pygame.transform.scale(img, (new_w, new_h))
            # LRU eviction: cap cache at _img_cache_max entries
            while len(self._img_cache_order) >= self._img_cache_max:
                old_key = self._img_cache_order.pop(0)
                if old_key in self._img_cache:
                    del self._img_cache[old_key]
            self._img_cache[key] = img
            self._img_cache_order.append(key)
            return img
        except Exception:
            self._img_cache[key] = None
            return None

    def _blit_image_fit(self, path: str | None, dest: pygame.Rect) -> bool:
        """Draw *path* letterboxed to fit inside *dest* (no crop)."""
        if not path or dest.w <= 0 or dest.h <= 0:
            return False
        thumb = self.load_image(path, (dest.w, dest.h), cover=False)
        if thumb is None:
            return False
        tx = dest.x + (dest.w - thumb.get_width()) // 2
        ty = dest.y + (dest.h - thumb.get_height()) // 2
        self.screen.blit(thumb, (tx, ty))
        return True

    def _blit_image_cover(self, path: str | None, dest: pygame.Rect) -> bool:
        """Draw *path* scaled to cover *dest* (center crop)."""
        if not path or dest.w <= 0 or dest.h <= 0:
            return False
        thumb = self.load_image(path, (dest.w, dest.h), cover=True)
        if thumb is None:
            return False
        prev_clip = self.screen.get_clip()
        self.screen.set_clip(dest)
        tx = dest.x + (dest.w - thumb.get_width()) // 2
        ty = dest.y + (dest.h - thumb.get_height()) // 2
        self.screen.blit(thumb, (tx, ty))
        self.screen.set_clip(prev_clip)
        return True

    def _blit_fullscreen_asset(self, path) -> bool:
        """Scale an asset to the full logical canvas (including safe-zone padding)."""
        img = self._load_image_surface(str(path))
        if img is None:
            return False
        target = (self.canvas_w, self.canvas_h)
        if img.get_size() != target:
            img = pygame.transform.scale(img, target)
        self.screen.blit(img, (0, 0))
        return True

    @staticmethod
    def _load_image_surface(path, *, max_pixels: int = 2048):
        """Load an image file as a pygame Surface.
        Tries pygame's native loader first, falls back to Pillow for
        systems where SDL_image lacks PNG/JPEG support (e.g. macOS wheels).
        Large files are downscaled during decode to limit memory spikes.
        """
        # Try pygame's native loader (works for BMP, and for PNG/JPEG when
        # SDL_image is compiled with extended format support).
        try:
            img = pygame.image.load(path)
            w, h = img.get_size()
            if max(w, h) <= max_pixels:
                return img.convert()
        except Exception:
            pass

        # Fall back to Pillow → pygame surface (with optional downscale).
        try:
            from PIL import Image as PILImage

            resample = getattr(PILImage, "Resampling", PILImage)
            lanczos = getattr(resample, "LANCZOS", PILImage.LANCZOS)
            with PILImage.open(path) as pil_img:
                pil_img.load()
                if max(pil_img.size) > max_pixels:
                    resized = pil_img.copy()
                    resized.thumbnail((max_pixels, max_pixels), lanczos)
                    pil_img = resized
                rgb = pil_img.convert("RGB")
            data = rgb.tobytes("raw", "RGB")
            return pygame.image.fromstring(data, rgb.size, "RGB")
        except Exception:
            return None

    # ─── Display setup ───────────────────────────────────────────────────

    def _enable_omx_overlay(self):
        """Use a transparent framebuffer so omxplayer's layer shows through."""
        self._omx_overlay = True
        self._create_framebuffer()

    def _marquee_offset_for(
        self,
        key,
        text_w,
        avail_w,
        *,
        key_attr: str,
        start_attr: str,
    ):
        """Pixel offset for an independently timed back-and-forth scroll."""
        overflow = text_w - avail_w
        if overflow <= 0:
            return 0

        now = pygame.time.get_ticks()
        if key != getattr(self, key_attr):
            setattr(self, key_attr, key)
            setattr(self, start_attr, now)

        elapsed = now - getattr(self, start_attr)
        if elapsed < MARQUEE_DELAY_MS:
            return 0

        scroll_ms = max(1, int(overflow / MARQUEE_SPEED_PX_S * 1000))
        cycle = scroll_ms + MARQUEE_END_PAUSE_MS
        t = (elapsed - MARQUEE_DELAY_MS) % (2 * cycle)
        if t < MARQUEE_END_PAUSE_MS:
            return 0
        if t < cycle:
            progress = (t - MARQUEE_END_PAUSE_MS) / scroll_ms
            return int(overflow * progress)
        if t < cycle + MARQUEE_END_PAUSE_MS:
            return overflow
        progress = (t - cycle - MARQUEE_END_PAUSE_MS) / scroll_ms
        return int(overflow * (1.0 - progress))

    def _marquee_offset(self, key, text_w, avail_w):
        """Pixel offset for scrolling the selected card's title."""
        return self._marquee_offset_for(
            key,
            text_w,
            avail_w,
            key_attr="_marquee_key",
            start_attr="_marquee_start",
        )

    def _header_marquee_offset(self, key, text_w, avail_w):
        """Pixel offset for scrolling a title-bar title."""
        return self._marquee_offset_for(
            key,
            text_w,
            avail_w,
            key_attr="_header_marquee_key",
            start_attr="_header_marquee_start",
        )

    def _blit_marquee_text(self, text, font, color, x, y, avail_w, *, key, active):
        """Blit text; if active and too wide, scroll it inside avail_w."""
        surf = font.render(text, True, color)
        if surf.get_width() <= avail_w:
            self.screen.blit(surf, (x, y))
            return

        if not active:
            clipped = text
            while font.size(clipped + "...")[0] > avail_w and len(clipped) > 1:
                clipped = clipped[:-1]
            surf = font.render(clipped + "...", True, color)
            self.screen.blit(surf, (x, y))
            return

        offset = self._marquee_offset(key, surf.get_width(), avail_w)
        clip = pygame.Rect(x, y, avail_w, surf.get_height())
        prev = self.screen.get_clip()
        self.screen.set_clip(clip)
        self.screen.blit(surf, (x - offset, y))
        self.screen.set_clip(prev)

    def present(self):
        """Scale the logical framebuffer to the OS window (letterboxed 4:3)."""
        if self.framebuffer is None:
            pygame.display.flip()
            return
        src = self.framebuffer
        dst = self.display
        dw, dh = dst.get_size()
        sw, sh = src.get_size()
        x, y, w, h = self._fit_rect(sw, sh, dw, dh)
        if not self._omx_overlay:
            dst.fill(C.BLACK)
        scaled = src if (w, h) == (sw, sh) else pygame.transform.smoothscale(src, (w, h))
        dst.blit(scaled, (x, y))
        pygame.display.flip()

    def _parse_safe_zone_sources(self) -> tuple[SafeZoneMargins, SafeZoneOffset]:
        ui_cfg = self.config.get("ui") or {}
        raw = ui_cfg.get("safe_zone")
        if self._safe_zone_override is not None:
            margins = parse_safe_zone(self._safe_zone_override)
        else:
            margins = parse_safe_zone(raw)
        if self._safe_zone_offset_override is not None:
            offset = self._safe_zone_offset_override
        elif isinstance(self._safe_zone_override, dict):
            offset = parse_safe_zone_offset(self._safe_zone_override)
        else:
            offset = parse_safe_zone_offset(raw if isinstance(raw, dict) else None)
        return margins, offset

    def _init_safe_zone_state(self) -> None:
        margins, offset = self._parse_safe_zone_sources()
        self._safe_zone_margins = margins
        self._safe_zone_offset = offset
        self._safe_zone_enabled = safe_zone_enabled(margins)
        frame = safe_zone_frame(margins, offset)
        self._safe_zone_frame = frame
        self._safe_ui_rect = frame.ui
        self.canvas_w = frame.canvas_w
        self.canvas_h = frame.canvas_h

    def _init_display_window(self) -> None:
        """Create the OS window (fixed 800×600 when windowed) and logical framebuffer."""
        if self.fullscreen:
            try:
                self.display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN, vsync=1)
            except TypeError:
                self.display = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            w, h = self._window_size_43(WINDOW_DEFAULT_W, WINDOW_DEFAULT_H)
            try:
                self.display = pygame.display.set_mode((w, h), pygame.RESIZABLE, vsync=1)
            except TypeError:
                self.display = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.real_w, self.real_h = self.display.get_size()
        self._create_framebuffer()

    @staticmethod
    def _window_size_43(width: int, height: int) -> tuple[int, int]:
        """Clamp a resize request to 4:3."""
        width = max(WINDOW_MIN_W, width)
        height = max(WINDOW_MIN_H, height)
        if width * 3 > height * 4:
            width = max(WINDOW_MIN_W, int(height * 4 / 3))
        elif height * 4 > width * 3:
            height = max(WINDOW_MIN_H, int(width * 3 / 4))
        return width, height

    @staticmethod
    def _fit_rect(
        src_w: int, src_h: int, dst_w: int, dst_h: int
    ) -> tuple[int, int, int, int]:
        """Letterbox *src* into *dst*, preserving aspect ratio."""
        scale = min(dst_w / src_w, dst_h / src_h)
        w = max(1, int(src_w * scale))
        h = max(1, int(src_h * scale))
        x = (dst_w - w) // 2
        y = (dst_h - h) // 2
        return x, y, w, h

    def _create_framebuffer(self) -> None:
        """Recreate the offscreen logical canvas (safe-zone size)."""
        flags = pygame.SRCALPHA if self._omx_overlay else 0
        self.framebuffer = pygame.Surface((self.canvas_w, self.canvas_h), flags)
        self.screen = self.framebuffer
        if self._omx_overlay:
            self.canvas = self.framebuffer

    def _on_window_resize(self, width: int, height: int) -> None:
        """Handle OS window resize — keep 4:3 aspect."""
        if self.fullscreen:
            return
        w, h = self._window_size_43(width, height)
        if (w, h) == self.display.get_size():
            return
        self.display = pygame.display.set_mode((w, h), pygame.RESIZABLE)
        self.real_w, self.real_h = w, h

    def _handle_window_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.VIDEORESIZE:
            self._on_window_resize(event.w, event.h)
            return True
        if (
            _PYGAME_WINDOWEVENT is not None
            and _PYGAME_WINDOWEVENT_CLOSE is not None
            and event.type == _PYGAME_WINDOWEVENT
            and event.window.event == _PYGAME_WINDOWEVENT_CLOSE
        ):
            self._request_quit(source="window-close")
            return True
        return False

    def _resize_framebuffer(self, width: int, height: int) -> None:
        """Resize the logical canvas when safe-zone margins change (not the OS window)."""
        self.canvas_w = width
        self.canvas_h = height
        self._create_framebuffer()
        if self.player:
            self.player.canvas_w = width
            self.player.canvas_h = height
        if self._screensaver is not None:
            self._screensaver = None

    def _enter_playback_display(self) -> None:
        """Keep the current canvas size; video is full-bleed on the whole frame."""

    def _exit_playback_display(self) -> None:
        """Apply any safe-zone resize deferred during playback."""
        self._flush_pending_canvas_resize()

    def _apply_safe_zone_frame(self, frame) -> None:
        """Apply parsed safe-zone geometry and resize the display if needed."""
        old_size = (self.canvas_w, self.canvas_h)
        self._safe_zone_frame = frame
        self._safe_ui_rect = frame.ui
        self.canvas_w = frame.canvas_w
        self.canvas_h = frame.canvas_h
        if (self.canvas_w, self.canvas_h) != old_size:
            self._resize_framebuffer(self.canvas_w, self.canvas_h)
            self._screensaver = None

    def _flush_pending_canvas_resize(self) -> None:
        """Apply a deferred framebuffer resize (e.g. after playback ends)."""
        if self._pending_safe_zone_frame is None:
            return
        frame = self._pending_safe_zone_frame
        self._pending_safe_zone_frame = None
        self._pending_canvas_size = None
        self._apply_safe_zone_frame(frame)

    def _apply_safe_zone_from_config(self) -> None:
        margins, offset = self._parse_safe_zone_sources()
        self._safe_zone_margins = margins
        self._safe_zone_offset = offset
        self._safe_zone_enabled = safe_zone_enabled(margins)
        frame = safe_zone_frame(margins, offset)
        new_size = (frame.canvas_w, frame.canvas_h)
        old_size = (self.canvas_w, self.canvas_h)

        if new_size != old_size and self.view == self.PLAYING:
            self._pending_canvas_size = new_size
            self._pending_safe_zone_frame = frame
            return

        self._pending_canvas_size = None
        self._pending_safe_zone_frame = None
        if new_size == old_size:
            self._safe_zone_frame = frame
            self._safe_ui_rect = frame.ui
            return
        self._apply_safe_zone_frame(frame)

    def _ui_surface_size(self) -> tuple[int, int]:
        """Pixel size of the surface menus/screensaver draw into."""
        if self._safe_zone_for_ui():
            return SCREEN_W, SCREEN_H
        return self.canvas_w, self.canvas_h

    def _safe_zone_for_ui(self) -> bool:
        """Safe zone applies to menus/UI only — never video playback."""
        if self.view == self.PLAYING:
            return False
        if not self._safe_zone_enabled:
            return False
        if self._show_list_test_pattern:
            return False
        return True

    def _playback_overlay_layout(self) -> tuple[SafeZoneRect, float]:
        """Title-safe rect and scale for playback HUD (video is full-bleed)."""
        rect = playback_hud_rect(
            self.canvas_w,
            self.canvas_h,
            self._safe_zone_margins,
            self._safe_zone_offset,
        )
        scale = playback_hud_scale(rect, self.canvas_w, self.canvas_h)
        return rect, scale

    def _scale_overlay_surface(self, surf: pygame.Surface, scale: float) -> pygame.Surface:
        if scale >= 0.999:
            return surf
        w, h = surf.get_size()
        return pygame.transform.smoothscale(
            surf, (max(1, int(w * scale)), max(1, int(h * scale)))
        )

    def _blit_overlay_text(
        self,
        surf: pygame.Surface,
        x: int,
        y: int,
        *,
        scale: float = 1.0,
        alpha: int = 255,
    ) -> pygame.Surface:
        """Blit label text, scaled to fit the playback safe inset."""
        if alpha < 255:
            surf = surf.copy()
            surf.set_alpha(alpha)
        surf = self._scale_overlay_surface(surf, scale)
        self.screen.blit(surf, (x, y))
        return surf

    def _truncate_overlay_text(self, text: str, font, color, max_w: int, *, scale: float):
        if max_w <= 8:
            return font.render("", True, color)
        surf = font.render(text, True, color)
        surf = self._scale_overlay_surface(surf, scale)
        if surf.get_width() <= max_w:
            return surf
        trimmed = text
        while trimmed and self._scale_overlay_surface(
            font.render(trimmed + "...", True, color), scale
        ).get_width() > max_w:
            trimmed = trimmed[:-1]
        return self._scale_overlay_surface(
            font.render((trimmed + "...") if trimmed else "...", True, color), scale
        )

    def _ui_letterbox_color(self) -> tuple[int, int, int]:
        """Margin fill matching the active screen so the UI appears inset, not framed."""
        if self._screensaver_active:
            return C.BLACK
        if self.view == self.PLAYING:
            return C.BLACK
        return C.BG

    @contextmanager
    def _ui_layout(
        self,
        *,
        letterbox: bool = True,
        enabled: bool | None = None,
        bg: tuple[int, int, int] | None = None,
    ):
        """Draw UI at native 640×480, composited into the extended frame (no scaling)."""
        if enabled is None:
            use = self._safe_zone_for_ui()
        else:
            use = bool(enabled) and self._safe_zone_enabled
        if not use:
            yield
            return

        if self._ui_layout_depth:
            raise RuntimeError("nested _ui_layout is not supported")
        self._ui_layout_depth += 1

        ui = self._safe_ui_rect
        root = self.framebuffer
        saved_screen = self.screen
        saved_sw = self.sw
        saved_sh = self.sh
        margin_color = bg if bg is not None else self._ui_letterbox_color()

        try:
            ui_buffer = pygame.Surface((SCREEN_W, SCREEN_H))
            self.screen = ui_buffer
            self.sw = SCREEN_W
            self.sh = SCREEN_H
            if letterbox:
                root.fill(margin_color)
                yield
                root.blit(ui_buffer, (ui.x, ui.y))
            else:
                yield
                saved_screen.blit(ui_buffer, (ui.x, ui.y))
        finally:
            self.screen = saved_screen
            self.sw = saved_sw
            self.sh = saved_sh
            self._ui_layout_depth -= 1

    def _shutdown_viewport(self) -> tuple[int, int, int, int] | None:
        """UI viewport for shutdown FX when the canvas is larger than 640×480."""
        sw, sh = self.screen.get_size()
        if (sw, sh) == (SCREEN_W, SCREEN_H):
            return None
        if self._safe_zone_enabled and self._safe_ui_rect is not None:
            ui = self._safe_ui_rect
            return (ui.x, ui.y, ui.w, ui.h)
        return None

    def _apply_analog_artifacts(self) -> None:
        if self.view == self.SHOW_LIST:
            self._analog_artifacts.tick()
            self._analog_artifacts.apply(self.screen)

    def _clear_show_list_test_pattern(self) -> None:
        self._show_list_test_pattern = None

    def _draw_test_pattern_screen(self) -> None:
        """Full-screen easter egg pattern, drawn over whichever browse screen is active."""
        self.screen.fill(C.BLACK)
        pattern_path = pattern_asset_path(self._show_list_test_pattern or "")
        if pattern_path and self._blit_fullscreen_asset(pattern_path):
            return
        t = self.font_md.render("TEST PATTERN NOT FOUND", True, C.DIM)
        self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))

    def _test_pattern_dial_allowed(self) -> bool:
        """Easter egg dials work on any parent browse screen."""
        return not self._kids_mode_active and self.view in (
            self.LIBRARY_SELECT,
            self.SHOW_LIST,
            self.MOVIE_LIST,
            self.SEASON_SELECT,
            self.EPISODE_SELECT,
        )

    def _commit_show_list_test_pattern(self, dial: str) -> bool:
        """Show a secret test pattern for dial codes 001 / 002 / 003."""
        path = pattern_asset_path(dial)
        if path is None:
            self.channel_error = f"Ch {dial} Not Found"
            self.channel_error_time = pygame.time.get_ticks()
            return False
        self._show_list_test_pattern = dial
        self._animate_channel_snow_burst()
        return True

    def _apply_channel_fx(self):
        """Brief static burst when tuning channels (if enabled)."""
        if self._channel_fx.is_active():
            self._channel_fx.draw(self.screen)

    def _trigger_channel_change_fx(self):
        self._channel_fx.trigger()

    def _draw_browse_content(self) -> None:
        """Menu layers only — no snow, channel overlay, or rescan banner."""
        if self._show_list_test_pattern:
            self._draw_test_pattern_screen()
            return
        if self.view == self.LIBRARY_SELECT:
            self.draw_library_selector()
        elif self.view == self.SHOW_LIST:
            if self._kids_mode_active and self._kids_browse_style == "full":
                self.draw_kids_full_card()
            else:
                self.draw_show_browser()
        elif self.view == self.MOVIE_LIST:
            if self._kids_mode_active and self._kids_browse_style == "full":
                self.draw_kids_full_card()
            else:
                self.draw_movie_browser()
        elif self.view == self.SEASON_SELECT:
            self.draw_season_browser()
        elif self.view == self.EPISODE_SELECT:
            self.draw_episode_browser()

    def _draw_episode_splash(
        self,
        show,
        season,
        episode,
        channel,
        *,
        resume_secs=None,
        header: str | None = None,
        footer: str | None = None,
    ) -> None:
        """Shared layout for now-playing and up-next splashes."""
        rect, scale = self._playback_overlay_layout()
        pad = HUD_PAD
        mid_y = rect.y + rect.h // 2

        if header:
            title = self._scale_overlay_surface(
                self.font_lg.render(header, True, C.GREEN), scale
            )
            self.screen.blit(
                title,
                title.get_rect(centerx=rect.x + rect.w // 2, centery=rect.y + pad + 20),
            )

        ch = self._scale_overlay_surface(
            self.font_lg.render(str(channel), True, C.GREEN), scale
        )
        self.screen.blit(ch, (rect.x + rect.w - ch.get_width() - pad, rect.y + pad))

        ep_num = episode["number"]
        ep_name = episode.get("name") or ""
        if getattr(self, "_playing_is_movie", False) or season is None:
            label = show
            s = self._scale_overlay_surface(
                self.font_md.render(label, True, C.WHITE), scale
            )
            self.screen.blit(
                s, s.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y - 10)
            )
        else:
            label = f"S-{season:02d} - E-{ep_num:02d}"
            s = self._scale_overlay_surface(
                self.font_md.render(label, True, C.WHITE), scale
            )
            self.screen.blit(
                s, s.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y - 30)
            )
            if ep_name:
                n = self._truncate_overlay_text(
                    ep_name, self.font_md, C.BLUE, rect.w - pad * 2, scale=scale
                )
                self.screen.blit(
                    n, n.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y + 10)
                )

        if resume_secs and resume_secs > 0:
            mins = int(resume_secs) // 60
            secs = int(resume_secs) % 60
            sub = f"RESUME  {mins}:{secs:02d}"
            sub_color = C.GREEN
        else:
            sub = show.upper()
            sub_color = C.DIM
        sn = self._truncate_overlay_text(
            sub, self.font_sm, sub_color, rect.w - pad * 2, scale=scale
        )
        self.screen.blit(
            sn, sn.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y + 55)
        )

        if footer:
            hint = self._scale_overlay_surface(
                self.font_sm.render(footer, True, C.DIM), scale
            )
            self.screen.blit(
                hint,
                hint.get_rect(centerx=rect.x + rect.w // 2, centery=rect.y + rect.h - pad - 12),
            )

    def _blit_now_playing_content(
        self, show, season, episode, channel, resume_secs=None
    ) -> None:
        """Now-playing splash artwork without blocking or snow."""
        self.screen.fill(C.BLACK)
        self._draw_episode_splash(
            show, season, episode, channel, resume_secs=resume_secs
        )

    def _draw_channel_tune_frame(self) -> None:
        """Destination screen drawn under a channel-change snow burst."""
        deferred = self._deferred_splash
        if self.view == self.PLAYING and deferred is not None:
            self._blit_now_playing_content(*deferred)
        elif self.view == self.CONFIRM_EXIT:
            self.draw_confirm_exit()
        elif self.view == self.SAFE_ZONE_EDIT:
            self.draw_safe_zone_editor()
        elif self.view in (self.KEY_CONFIG, self.KEY_CAPTURE):
            self.draw_key_config(capturing=(self.view == self.KEY_CAPTURE))
        elif self.view in (self.GAMEPAD_CONFIG, self.GAMEPAD_CAPTURE):
            self.draw_gamepad_config(capturing=(self.view == self.GAMEPAD_CAPTURE))
        else:
            self._draw_browse_content()
            if self.view == self.SHOW_LIST:
                self._apply_analog_artifacts()

    def _animate_channel_snow_burst(self) -> None:
        """Run a fixed-length static burst so every tune feels the same."""
        if not self._channel_fx.snow_enabled:
            return
        self._channel_fx.trigger()
        start = pygame.time.get_ticks()
        while pygame.time.get_ticks() - start < FX_DURATION_MS:
            pygame.event.pump()
            if self.view == self.SAFE_ZONE_EDIT:
                self._draw_channel_tune_frame()
                self.draw_channel_overlay()
                self._draw_rescan_banner()
            else:
                with self._ui_layout(letterbox=True):
                    self._draw_channel_tune_frame()
                    self.draw_channel_overlay()
                    self._draw_rescan_banner()
            # Snow overlays the full canvas after UI is composited into the safe zone.
            self._channel_fx.draw(self.screen)
            self.present()
            self.clock.tick(60)

    def _draw_footer(self, *hints):
        """Status bar: local time on the left, help key on the right.

        Extra *hints* are ignored — remapped keys made a dense hint strip unreadable.
        """
        if not self._parent_footer_visible():
            return
        bar_h = FOOTER_BAR_H
        fy = self.sh - bar_h
        pygame.draw.rect(self.screen, C.BG_FOOTER, (0, fy, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, fy), (self.sw, fy), 1)

        clock = datetime.now().strftime("%I:%M %p").lstrip("0")
        clock_surf = self.font_sm.render(clock, True, C.DIM)
        help_label = f"{format_action_keys(self.keymap, 'help')} help"
        help_surf = self.font_sm.render(help_label, True, C.DIM)
        cy = fy + bar_h // 2
        self.screen.blit(clock_surf, clock_surf.get_rect(left=16, centery=cy))
        self.screen.blit(help_surf, help_surf.get_rect(right=self.sw - 16, centery=cy))

    def _draw_header(self, left_text, right_text="", ch_num=None, badge_text=""):
        """Draw a consistent header bar at the top of the screen."""
        bar_h = HEADER_BAR_H
        pygame.draw.rect(self.screen, C.BG_HEADER, (0, 0, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, bar_h), (self.sw, bar_h), 1)

        # Fixed right-side fields: channel at the edge, kids badge just before it.
        right_edge = self.sw - 16
        right_value = str(ch_num) if ch_num is not None else right_text
        if right_value:
            rt = self.font_md.render(right_value, True, C.GREEN)
            self.screen.blit(
                rt,
                (right_edge - rt.get_width(), (bar_h - rt.get_height()) // 2),
            )
            right_edge -= rt.get_width() + 12

        if badge_text:
            badge = self.font_sm.render(badge_text, True, C.CYAN)
            self.screen.blit(
                badge,
                (right_edge - badge.get_width(), (bar_h - badge.get_height()) // 2),
            )
            right_edge -= badge.get_width() + 12

        # Keep right-side fields stationary while an overflowing title scrolls.
        title_x = 16
        title_w = max(1, right_edge - title_x)
        lt = self.font_md.render(left_text, True, C.BRIGHT)
        title_y = (bar_h - lt.get_height()) // 2
        if lt.get_width() <= title_w:
            self.screen.blit(lt, (title_x, title_y))
        else:
            offset = self._header_marquee_offset(
                (left_text, right_value, badge_text),
                lt.get_width(),
                title_w,
            )
            previous_clip = self.screen.get_clip()
            self.screen.set_clip(pygame.Rect(title_x, title_y, title_w, lt.get_height()))
            self.screen.blit(lt, (title_x - offset, title_y))
            self.screen.set_clip(previous_clip)

        return bar_h

    def _draw_nav_bar(self, y, label, direction, active):
        """Full-width up/down navigation strip (matches show browser)."""
        nav_h = 28
        if active and label:
            pygame.draw.rect(self.screen, C.BG_CARD, (0, y, self.sw, nav_h))
            arrow = "\u25b2" if direction == "up" else "\u25bc"
            max_w = self.sw - 32
            text = f"{arrow}  {label}"
            surf = self.font_sm.render(text, True, C.CYAN)
            if surf.get_width() > max_w:
                while self.font_sm.size(text + "...")[0] > max_w and len(text) > 4:
                    text = text[:-1]
                surf = self.font_sm.render(text + "...", True, C.CYAN)
            self.screen.blit(surf, surf.get_rect(left=16, centery=y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, C.BG, (0, y, self.sw, nav_h))
        if active:
            if direction == "up":
                pygame.draw.line(
                    self.screen, (25, 40, 70), (0, y + nav_h), (self.sw, y + nav_h), 1
                )
            else:
                pygame.draw.line(self.screen, (25, 40, 70), (0, y), (self.sw, y), 1)
        return nav_h

    def _draw_arrow_nav_bar(self, y: int, nav_h: int, direction: str, active: bool) -> None:
        """Full-width up/down strip with a centered arrow (kid-friendly show browser)."""
        if active:
            pygame.draw.rect(self.screen, C.BG_CARD, (0, y, self.sw, nav_h))
            arrow = "\u25b2" if direction == "up" else "\u25bc"
            surf = self.font_lg.render(arrow, True, C.CYAN)
            self.screen.blit(surf, surf.get_rect(centerx=self.sw // 2, centery=y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, C.BG, (0, y, self.sw, nav_h))
        if active:
            if direction == "up":
                pygame.draw.line(
                    self.screen, (25, 40, 70), (0, y + nav_h), (self.sw, y + nav_h), 1
                )
            else:
                pygame.draw.line(self.screen, (25, 40, 70), (0, y), (self.sw, y), 1)

    def _show_browser_layout(self, header_h: int, *, kids: bool = False):
        """Vertical layout for the cable-TV show browser."""
        nav_h = KIDS_NAV_BAR_H if kids else NAV_BAR_H
        footer_h = 0 if kids or not self._footer_hints_enabled else FOOTER_BAR_H
        # Leave visible background between the title bar and page navigation.
        up_y = header_h + 4
        down_y = self.sh - footer_h - nav_h
        content_y = up_y + nav_h + 4
        content_bottom = down_y
        content_h = max(40, content_bottom - content_y)
        return {
            "nav_h": nav_h,
            "footer_h": footer_h,
            "up_y": up_y,
            "down_y": down_y,
            "content_y": content_y,
            "content_bottom": content_bottom,
            "content_h": content_h,
        }

    def _stack_browser_layout(self):
        """Shared vertical layout for season/episode stack browsers."""
        nav_h = NAV_BAR_H
        footer_h = FOOTER_BAR_H if self._footer_hints_enabled else 0
        header_h = HEADER_BAR_H
        # Without this gap, the navigation strip reads as part of the title bar.
        up_y = header_h + 4
        down_y = self.sh - footer_h - nav_h
        stack_top = up_y + nav_h + 4
        stack_bottom = down_y - 4
        stack_h = max(40, stack_bottom - stack_top)
        gap = 4
        item_h = min(70, (stack_h - (STACK_VISIBLE - 1) * gap) // STACK_VISIBLE)
        return {
            "nav_h": nav_h,
            "footer_h": footer_h,
            "up_y": up_y,
            "down_y": down_y,
            "stack_top": stack_top,
            "stack_bottom": stack_bottom,
            "item_h": item_h,
            "gap": gap,
        }

    def _stack_first_visible(self, cursor, total, page_size: int | None = None):
        """Start index of the current page (fixed pages, no scroll)."""
        ps = page_size if page_size is not None else self._stack_page_size_for_view()
        if total <= ps:
            return 0
        return (cursor // ps) * ps

    def _stack_page_size(self, first_visible, total, page_size: int | None = None):
        """How many cards are on this page (may be fewer on the last page)."""
        ps = page_size if page_size is not None else self._stack_page_size_for_view()
        return min(ps, total - first_visible)

    def _stack_page_nav(self, first_visible, total, page_size: int | None = None):
        """Labels for page-up / page-down nav bars on stack browsers."""
        ps = page_size if page_size is not None else self._stack_page_size_for_view()
        items_above = first_visible
        items_below = max(0, total - (first_visible + ps))
        up_label = f"Previous {ps}" if items_above > 0 else ""
        down_label = (
            f"Next {min(ps, items_below)}" if items_below > 0 else ""
        )
        return up_label, down_label, items_above > 0, items_below > 0

    def _move_cursor_stack(self, direction, total, page_size: int | None = None):
        """Step within a page; at the page edge, flip to the next/previous page."""
        ps = page_size if page_size is not None else self._stack_page_size_for_view()
        first_visible = self._stack_first_visible(self.cursor, total, ps)
        page_top = first_visible
        page_bottom = first_visible + self._stack_page_size(first_visible, total, ps) - 1

        if direction > 0:
            if self.cursor >= total - 1:
                return
            if self.cursor >= page_bottom:
                self.cursor = first_visible + ps
            else:
                self.cursor += 1
        else:
            if self.cursor <= 0:
                return
            if self.cursor <= page_top:
                self.cursor = first_visible - 1
            else:
                self.cursor -= 1

        self._marquee_key = None

    # ─── Navigation helpers ───────────────────────────────────────────────

    def _count_total_eps(self, show_data):
        """Count total episodes across all seasons."""
        return sum(len(s.get('episodes', [])) for s in show_data.get('seasons', {}).values())

    def _wrap_text(self, text, font, max_width):
        """Word-wrap text to fit within max_width pixels. Returns list of lines."""
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip()
            if font.size(test_line)[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines if lines else [text]

    def _draw_popup_banner(
        self,
        message: str,
        *,
        color=C.GREEN,
        text_color=C.BRIGHT,
        font=None,
        max_width: int | None = None,
    ) -> None:
        """Centered message box with word wrap for transient warnings."""
        if not message or not message.strip():
            return
        font = font or self.font_sm
        pad_x, pad_y = 24, 16
        line_gap = 4
        max_w = max_width if max_width is not None else self.sw - 80
        lines = self._wrap_text(message, font, max_w)
        line_h = font.get_linesize()
        text_w = max(font.size(line)[0] for line in lines)
        text_h = line_h * len(lines) + line_gap * max(0, len(lines) - 1)
        box_w = min(self.sw - 40, text_w + pad_x * 2)
        box_h = text_h + pad_y * 2
        box_x = (self.sw - box_w) // 2
        box_y = (self.sh - box_h) // 2

        bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        bg_surf.fill((0, 10, 5, 220))
        pygame.draw.rect(bg_surf, color, (0, 0, box_w, box_h), 2, border_radius=6)
        self.screen.blit(bg_surf, (box_x, box_y))

        y = box_y + pad_y
        for line in lines:
            surf = font.render(line, True, text_color)
            x = box_x + (box_w - surf.get_width()) // 2
            self.screen.blit(surf, (x, y))
            y += line_h + line_gap

    def _draw_mode_toast(self) -> None:
        """Kids/parent mode toggle message — separate from channel error overlay."""
        if not self._mode_toast_message:
            return
        now = pygame.time.get_ticks()
        if now >= self._mode_toast_until:
            self._mode_toast_message = ""
            return
        self._draw_popup_banner(self._mode_toast_message)

    def seasons_for_show(self, show):
        return sorted(self.shows.get(show, {}).get('seasons', {}).keys())

    def season_display_name(self, show, season_num):
        """Season menu title — folder name or ``Season N``."""
        season_data = self.shows.get(show, {}).get("seasons", {}).get(season_num, {})
        label = season_data.get("label")
        if label:
            return str(label)
        return f"Season {season_num}"

    def current_items(self):
        if self.view == self.LIBRARY_SELECT:
            if self._kids_mode_active:
                return [
                    {"name": "SHOWS", "count": len(self._kids_filtered_show_names())},
                    {"name": "MOVIES", "count": len(self._kids_filtered_movie_names())},
                ]
            return [
                {"name": "SHOWS", "count": len(self.show_names)},
                {"name": "MOVIES", "count": len(self.movie_names)},
            ]
        if self.view == self.SHOW_LIST:
            names = self._browse_show_names()
            return [{'name': n, 'data': self.shows[n]} for n in names if n in self.shows]
        if self.view == self.MOVIE_LIST:
            return [self.movies[k] for k in self._browse_movie_names() if k in self.movies]
        elif self.view == self.SEASON_SELECT:
            show = self.shows.get(self.cur_show, {})
            seasons = sorted(show.get('seasons', {}).keys())
            return [{'name': self.season_display_name(self.cur_show, s), 'number': s,
                     'data': show['seasons'][s]} for s in seasons]
        else:
            show = self.shows.get(self.cur_show, {})
            season_data = show.get('seasons', {}).get(self.cur_season, {})
            return list(season_data.get('episodes', []))

    def total_items(self):
        items = self.current_items()
        return len(items) if items else 0

    # ─── Main draw dispatch ──────────────────────────────────────────────

    def draw(self):
        with self._ui_layout(letterbox=True):
            self._draw_browse_content()
            if self._letter_menu_open:
                self._draw_letter_menu()
            self.draw_channel_overlay()
            self._draw_mode_toast()
            self._draw_rescan_banner()
            if self.view == self.SHOW_LIST:
                self._apply_analog_artifacts()
        self._apply_channel_fx()

    # ─── Channel overlay ─────────────────────────────────────────────────

    def draw_channel_overlay(self):
        """Channel number overlay — building digits, commit flash, or error."""
        now = pygame.time.get_ticks()

        # Error message overlay
        if self.channel_error and self.channel_error_time > 0:
            elapsed = now - self.channel_error_time
            if elapsed < CHANNEL_ERROR_MS:
                self._draw_popup_banner(self.channel_error)
                return
            else:
                self.channel_error = ""
                self.channel_error_time = 0

        # Commit flash overlay (shown after channel is committed)
        if self.channel_flash and self.channel_flash_time > 0:
            elapsed = now - self.channel_flash_time
            if elapsed < CHANNEL_FLASH_MS:
                box_w = 160
                box_h = 100
                box_x = self.sw - box_w - 16
                box_y = 16

                bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
                bg_surf.fill((0, 10, 5, 200))
                pygame.draw.rect(bg_surf, C.GREEN, (0, 0, box_w, box_h), 2, border_radius=6)
                self.screen.blit(bg_surf, (box_x, box_y))

                ch_surf = self.font_lg.render(self.channel_flash, True, C.BRIGHT)
                self.screen.blit(
                    ch_surf,
                    (
                        box_x + (box_w - ch_surf.get_width()) // 2,
                        box_y + (box_h - ch_surf.get_height()) // 2,
                    ),
                )
                return
            else:
                self.channel_flash = ""
                self.channel_flash_time = 0

        # Building digits overlay — fixed-width 3-digit display, left-aligned
        if self.channel_digits:
            # Fixed box sized for 3 digits
            sample = self.font_lg.render("888", True, C.GREEN)
            digit_w = sample.get_width()
            digit_h = sample.get_height()
            box_w = digit_w + 40
            box_h = digit_h + 30
            box_x = self.sw - box_w - 16
            box_y = 16

            bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
            bg_surf.fill((0, 10, 5, 200))
            pygame.draw.rect(bg_surf, C.GREEN, (0, 0, box_w, box_h), 2, border_radius=6)
            self.screen.blit(bg_surf, (box_x, box_y))

            # Build display: digits left-aligned, cursor at next position
            cursor_on = (now // 400) % 2 == 0
            display = self.channel_digits
            if len(display) < 3 and cursor_on:
                display += "_"
            # Pad to 3 positions so it stays left-aligned
            while len(display) < 3:
                display += " "
            ch_surf = self.font_lg.render(display, True, C.GREEN)
            self.screen.blit(ch_surf, (box_x + (box_w - ch_surf.get_width()) // 2,
                                       box_y + (box_h - ch_surf.get_height()) // 2))

    # ─── Show browser ────────────────────────────────────────────────────

    def draw_show_browser(self):
        """Paged show list (stack of title cards)."""
        self.screen.fill(C.BG)
        shows = self._browse_show_names()
        if not shows:
            msg = (
                "Nothing for kids yet — tag titles in parent mode"
                if self._kids_mode_active and self._kids_allowlist is not None
                else "No shows found"
            )
            t = self.font_md.render(msg, True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        total = len(shows)
        self.cursor = min(self.cursor, total - 1)
        show_name = shows[self.cursor]
        ch_num = self._display_channel(show_name)
        tagged = (
            not self._kids_mode_active
            and self._title_kids_tagged(show=show_name)
        )
        self._draw_header(
            show_name.upper(),
            badge_text="[kids]" if tagged else "",
        )

        kids = self._kids_mode_active
        page_size = self._stack_page_size_for_view()
        layout = self._stack_browser_layout()
        stack_top = layout["stack_top"]
        stack_bottom = layout["stack_bottom"]
        gap = layout["gap"]
        item_h = min(
            90 if kids else 70,
            (stack_bottom - stack_top - (page_size - 1) * gap) // max(1, page_size),
        )

        first_visible = self._stack_first_visible(self.cursor, total, page_size)
        up_label, down_label, up_active, down_active = self._stack_page_nav(
            first_visible, total, page_size
        )
        if kids:
            self._draw_arrow_nav_bar(layout["up_y"], layout["nav_h"], "up", up_active)
            self._draw_arrow_nav_bar(layout["down_y"], layout["nav_h"], "down", down_active)
        else:
            self._draw_nav_bar(layout["up_y"], up_label, "up", up_active)
            self._draw_nav_bar(layout["down_y"], down_label, "down", down_active)

        for i in range(page_size):
            item_idx = first_visible + i
            if item_idx >= total:
                break
            y = stack_top + i * (item_h + gap)
            if y + item_h > stack_bottom:
                break
            name = shows[item_idx]
            data = self.shows.get(name, {})
            selected = item_idx == self.cursor
            rect = pygame.Rect(30, y, self.sw - 60, item_h)
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            ch = str(self._display_channel(name))
            ch_surf = self.font_lg.render(ch, True, C.GREEN if selected else C.DIM)
            self.screen.blit(
                ch_surf,
                (rect.x + 14, rect.y + (rect.height - ch_surf.get_height()) // 2),
            )

            thumb_size = min(item_h - 12, 64)
            thumb = self.load_image(data.get("thumbnail"), (thumb_size, thumb_size))
            label_x = rect.x + 14 + ch_surf.get_width() + 16
            text_right = rect.right - 14
            if thumb:
                thumb_x = rect.right - thumb.get_width() - 10
                self.screen.blit(
                    thumb,
                    (thumb_x, rect.y + (rect.height - thumb.get_height()) // 2),
                )
                text_right = thumb_x - 10

            n_total = self._count_total_eps(data)
            seasons = self.seasons_for_show(name)
            if len(seasons) > 1:
                info = f"{len(seasons)} seasons - {n_total} ep"
            else:
                info = f"{n_total} ep"
            info_surf = self.font_sm.render(info, True, C.DIM)
            line1_h = self.font_md.get_height()
            total_text_h = line1_h + info_surf.get_height() + 2
            text_top = rect.y + (rect.height - total_text_h) // 2
            self._blit_marquee_text(
                name.upper(),
                self.font_md,
                C.BRIGHT if selected else C.WHITE,
                label_x,
                text_top,
                max(1, text_right - label_x),
                key=("show", name),
                active=selected,
            )
            self.screen.blit(
                info_surf,
                (label_x, text_top + line1_h + 2),
            )

        if not kids:
            self._draw_footer()

    def draw_library_selector(self):
        """Top-level Shows / Movies picker when both library folders exist."""
        if self._kids_mode_active:
            self._draw_kids_library_selector()
            return

        self.screen.fill(C.BG)
        items = self.current_items()
        if not items:
            t = self.font_md.render("No library", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        self._draw_header("LIBRARY")
        layout = self._stack_browser_layout()
        stack_top = layout["stack_top"]
        item_h = layout["item_h"]
        gap = layout["gap"]

        for i, item in enumerate(items):
            y = stack_top + i * (item_h + gap)
            rect = pygame.Rect(30, y, self.sw - 60, item_h)
            selected = i == self.cursor
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            ch = str(i + 1)
            ch_surf = self.font_lg.render(ch, True, C.GREEN if selected else C.DIM)
            self.screen.blit(
                ch_surf,
                (rect.x + 14, rect.y + (rect.height - ch_surf.get_height()) // 2),
            )

            label = item["name"]
            count = item["count"]
            label_x = rect.x + 14 + ch_surf.get_width() + 16
            title = self.font_md.render(label, True, C.BRIGHT if selected else C.WHITE)
            info = self.font_sm.render(
                f"{count} title{'s' if count != 1 else ''}", True, C.DIM
            )
            self.screen.blit(title, (label_x, rect.y + 12))
            self.screen.blit(info, (rect.right - info.get_width() - 16, rect.y + 14))

        self._draw_footer()

    def _show_thumbnail_paths(self) -> list[str]:
        """Poster/thumbnail paths for the show library only (one per show)."""
        paths: list[str] = []
        movie_keys = set(self.movies.keys())
        names = self._browse_show_names() if self._kids_mode_active else self.show_names
        for name in names:
            if name in movie_keys:
                continue
            show = self.shows.get(name)
            if not show:
                continue
            thumb = show.get("thumbnail")
            if thumb and os.path.isfile(thumb):
                paths.append(thumb)
        return paths

    def _movie_thumbnail_paths(self) -> list[str]:
        """Poster/thumbnail paths for the movie library only (one per movie)."""
        paths: list[str] = []
        show_names = set(self.show_names)
        names = self._browse_movie_names() if self._kids_mode_active else self.movie_names
        for key in names:
            if key in show_names:
                continue
            movie = self.movies.get(key)
            if not movie:
                continue
            thumb = movie.get("thumbnail")
            if thumb and os.path.isfile(thumb):
                paths.append(thumb)
        return paths

    @staticmethod
    def _library_thumb_slot_layout(
        area_w: int,
        area_h: int,
        max_visible: int = LIBRARY_THUMB_VISIBLE,
    ) -> tuple[int, int, int]:
        """Return ``(slot_count, cell_w, cell_h)`` for 4:3 tiles in *area_w* × *area_h*."""
        if area_w <= 0 or area_h <= 0 or max_visible <= 0:
            return 0, 0, 0
        aspect_w, aspect_h = LIBRARY_THUMB_ASPECT
        gap = LIBRARY_THUMB_GAP
        # Try to fit max_visible thumbnails; if too wide, reduce count.
        slots = max_visible
        while slots > 0:
            total_gap = max(0, slots - 1) * gap
            cell_w = (area_w - total_gap) // slots
            if cell_w <= 0:
                slots -= 1
                continue
            cell_h = max(1, int(cell_w * aspect_h / aspect_w))
            if cell_h > area_h:
                cell_h = area_h
                cell_w = max(1, int(cell_h * aspect_w / aspect_h))
                total_gap = max(0, slots - 1) * gap
                if cell_w * slots + total_gap > area_w:
                    slots -= 1
                    continue
            break
        return slots, cell_w, cell_h

    @staticmethod
    def _library_thumb_window(
        paths: list[str], start_idx: int, max_visible: int
    ) -> list[str]:
        """Return up to *max_visible* unique thumbnails starting at *start_idx*."""
        if not paths or max_visible <= 0:
            return []
        seen: set[str] = set()
        result: list[str] = []
        for offset in range(len(paths)):
            idx = (start_idx + offset) % len(paths)
            if paths[idx] not in seen:
                seen.add(paths[idx])
                result.append(paths[idx])
            if len(result) >= max_visible:
                break
        return result

    def _advance_library_thumbnail_cycle(self) -> None:
        now = pygame.time.get_ticks()
        if self._library_thumb_last_advance == 0:
            self._library_thumb_last_advance = now
            return
        if now - self._library_thumb_last_advance < LIBRARY_THUMB_CYCLE_MS:
            return
        self._library_thumb_last_advance = now
        show_paths = self._show_thumbnail_paths()
        if show_paths:
            self._library_shows_thumb_idx = (
                self._library_shows_thumb_idx + 1
            ) % len(show_paths)
        movie_paths = self._movie_thumbnail_paths()
        if movie_paths:
            self._library_movies_thumb_idx = (
                self._library_movies_thumb_idx + 1
            ) % len(movie_paths)

    def _draw_kids_library_panel(
        self,
        rect: pygame.Rect,
        label: str,
        count: int,
        *,
        kind: str,
        channel_num: int,
        selected: bool,
    ) -> None:
        """Large half-screen Shows / Movies tile for kid-friendly mode."""
        if rect.w <= 0 or rect.h <= 0:
            return
        radius = min(12, rect.w // 4, rect.h // 4)
        if selected:
            pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=radius)
            pygame.draw.rect(self.screen, C.CYAN, rect.inflate(4, 4), 3, border_radius=radius)
        else:
            pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=radius)
            pygame.draw.rect(self.screen, C.DIM, rect, 1, border_radius=radius)

        pad = 12
        inner = rect.inflate(-pad * 2, -pad * 2)
        inner.w = max(1, inner.w)
        inner.h = max(1, inner.h)

        ch_surf = self.font_lg.render(str(channel_num), True, C.GREEN if selected else C.DIM)
        count_text = f"{count} title{'s' if count != 1 else ''}"
        count_surf = self.font_sm.render(count_text, True, C.BLUE)
        sidebar_w = max(
            ch_surf.get_width() + 20,
            count_surf.get_width() + 20,
        )
        sidebar_w = min(sidebar_w, max(80, inner.w // 3))
        sidebar_gap = 14
        sidebar = pygame.Rect(inner.x, inner.y, sidebar_w, inner.h)
        thumb_area = pygame.Rect(
            sidebar.right + sidebar_gap,
            inner.y,
            max(1, inner.right - sidebar.right - sidebar_gap),
            inner.h,
        )

        # Channel number: centered vertically
        ch_y = sidebar.y + (sidebar.h - ch_surf.get_height()) // 2
        self.screen.blit(ch_surf, (sidebar.x, ch_y))
        # Count text: bottom of sidebar
        count_y = sidebar.bottom - count_surf.get_height() - 8
        self.screen.blit(count_surf, (sidebar.x, count_y))

        if kind == "show":
            all_paths = self._show_thumbnail_paths()
            start_idx = self._library_shows_thumb_idx
        else:
            all_paths = self._movie_thumbnail_paths()
            start_idx = self._library_movies_thumb_idx

        slot_count, cell_w, cell_h = self._library_thumb_slot_layout(
            thumb_area.w,
            thumb_area.h,
            LIBRARY_THUMB_VISIBLE,
        )
        thumb_paths = self._library_thumb_window(all_paths, start_idx, slot_count)
        if not thumb_paths:
            return

        gap = LIBRARY_THUMB_GAP
        n = len(thumb_paths)
        strip_w = n * cell_w + max(0, n - 1) * gap
        x0 = thumb_area.x + max(0, (thumb_area.w - strip_w) // 2)
        y0 = thumb_area.y + max(0, (thumb_area.h - cell_h) // 2)
        for i, path in enumerate(thumb_paths):
            cell = pygame.Rect(x0 + i * (cell_w + gap), y0, cell_w, cell_h)
            pygame.draw.rect(self.screen, (20, 28, 45), cell, border_radius=4)
            if not self._blit_image_fit(path, cell):
                ph = self.font_sm.render("?", True, C.DIM)
                self.screen.blit(ph, ph.get_rect(center=cell.center))

    def _draw_kids_carousel_panel(
        self,
        rect: pygame.Rect,
        label: str,
        count: int,
        *,
        kind: str,
        channel_num: int,
        selected: bool,
    ) -> None:
        """Carousel panel: 3 thumbnails (small-big-small) scrolling left with scale transition."""
        if rect.w <= 0 or rect.h <= 0:
            return
        radius = min(12, rect.w // 4, rect.h // 4)
        if selected:
            pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=radius)
            pygame.draw.rect(self.screen, C.CYAN, rect.inflate(4, 4), 3, border_radius=radius)
        else:
            pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=radius)
            pygame.draw.rect(self.screen, C.DIM, rect, 1, border_radius=radius)

        pad = 12
        inner = rect.inflate(-pad * 2, -pad * 2)
        inner.w = max(1, inner.w)
        inner.h = max(1, inner.h)

        # Sidebar: channel number + count
        ch_surf = self.font_lg.render(str(channel_num), True, C.GREEN if selected else C.DIM)
        count_text = f"{count} title{'s' if count != 1 else ''}"
        count_surf = self.font_sm.render(count_text, True, C.BLUE)
        sidebar_w = max(ch_surf.get_width() + 20, count_surf.get_width() + 20)
        sidebar_w = min(sidebar_w, max(80, inner.w // 3))
        sidebar_gap = 14
        sidebar = pygame.Rect(inner.x, inner.y, sidebar_w, inner.h)
        thumb_area = pygame.Rect(
            sidebar.right + sidebar_gap,
            inner.y,
            max(1, inner.right - sidebar.right - sidebar_gap),
            inner.h,
        )

        # Channel number: centered vertically
        ch_y = sidebar.y + (sidebar.h - ch_surf.get_height()) // 2
        self.screen.blit(ch_surf, (sidebar.x, ch_y))
        # Count text: bottom of sidebar
        count_y = sidebar.bottom - count_surf.get_height() - 8
        self.screen.blit(count_surf, (sidebar.x, count_y))

        # Get thumbnail paths
        if kind == "show":
            all_paths = self._show_thumbnail_paths()
            start_idx = self._library_shows_thumb_idx
        else:
            all_paths = self._movie_thumbnail_paths()
            start_idx = self._library_movies_thumb_idx

        if not all_paths:
            return

        # Carousel: 3 slots — left (small), center (big), right (small)
        # Transition progress 0→1 scrolls left: left exits, center→left, right→center, new→right
        now = pygame.time.get_ticks()
        elapsed = now - self._carousel_transition_start
        progress = min(1.0, elapsed / CAROUSEL_TRANSITION_MS)

        center_frac = CAROUSEL_CENTER_FRAC
        side_scale = CAROUSEL_SIDE_SCALE

        # Calculate sizes
        center_h = thumb_area.h
        center_w = int(center_h * LIBRARY_THUMB_ASPECT[0] / LIBRARY_THUMB_ASPECT[1])
        side_h = int(center_h * side_scale)
        side_w = int(side_h * LIBRARY_THUMB_ASPECT[0] / LIBRARY_THUMB_ASPECT[1])

        # Total width of the 3-card strip
        total_w = side_w + 8 + center_w + 8 + side_w
        # Center the strip in thumb_area
        strip_x = thumb_area.x + (thumb_area.w - total_w) // 2

        # Positions (static, no transition offset — the cycle handles the "scroll" effect)
        left_x = strip_x
        center_x = strip_x + side_w + 8
        right_x = strip_x + side_w + 8 + center_w + 8

        # Which 3 thumbnails to show (unique, no duplicates)
        seen: set[str] = set()
        indices: list[int] = []
        for offset in range(len(all_paths)):
            idx = (start_idx + offset) % len(all_paths)
            if all_paths[idx] not in seen:
                seen.add(all_paths[idx])
                indices.append(idx)
            if len(indices) >= 3:
                break
        # Pad with repeats only if we have fewer than 3 unique paths
        while len(indices) < 3:
            indices.append(indices[-1] if indices else 0)
        idx0, idx1, idx2 = indices[0], indices[1], indices[2]

        # Draw left (small)
        left_rect = pygame.Rect(left_x, thumb_area.y + (thumb_area.h - side_h) // 2, side_w, side_h)
        pygame.draw.rect(self.screen, (20, 28, 45), left_rect, border_radius=4)
        if not self._blit_image_fit(all_paths[idx0], left_rect):
            ph = self.font_sm.render("?", True, C.DIM)
            self.screen.blit(ph, ph.get_rect(center=left_rect.center))

        # Draw center (big)
        center_rect = pygame.Rect(center_x, thumb_area.y, center_w, center_h)
        pygame.draw.rect(self.screen, (20, 28, 45), center_rect, border_radius=4)
        if not self._blit_image_fit(all_paths[idx1], center_rect):
            ph = self.font_sm.render("?", True, C.DIM)
            self.screen.blit(ph, ph.get_rect(center=center_rect.center))

        # Draw right (small)
        right_rect = pygame.Rect(right_x, thumb_area.y + (thumb_area.h - side_h) // 2, side_w, side_h)
        pygame.draw.rect(self.screen, (20, 28, 45), right_rect, border_radius=4)
        if not self._blit_image_fit(all_paths[idx2], right_rect):
            ph = self.font_sm.render("?", True, C.DIM)
            self.screen.blit(ph, ph.get_rect(center=right_rect.center))

    def _draw_kids_library_selector(self) -> None:
        """Kid-friendly Shows / Movies picker — two large tiles with cycling art."""
        self._advance_library_thumbnail_cycle()
        self.screen.fill(C.BG)
        items = self.current_items()
        if not items:
            t = self.font_md.render("No library", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        header_text = items[self.cursor]["name"] if items else "LIBRARY"
        header_h = self._draw_header(header_text, ch_num="")
        pad = 14
        gap = 14
        content_h = self.sh - header_h
        panel_h = max(80, (content_h - pad * 2 - gap) // 2)
        panel_w = max(1, self.sw - pad * 2)

        if self._kids_carousel_active:
            for i, item in enumerate(items):
                y = header_h + pad + i * (panel_h + gap)
                rect = pygame.Rect(pad, y, panel_w, panel_h)
                kind = "show" if item["name"] == "SHOWS" else "movie"
                self._draw_kids_carousel_panel(
                    rect,
                    item["name"],
                    item["count"],
                    kind=kind,
                    channel_num=i + 1,
                    selected=(i == self.cursor),
                )
        else:
            for i, item in enumerate(items):
                y = header_h + pad + i * (panel_h + gap)
                rect = pygame.Rect(pad, y, panel_w, panel_h)
                kind = "show" if item["name"] == "SHOWS" else "movie"
                self._draw_kids_library_panel(
                    rect,
                    item["name"],
                    item["count"],
                    kind=kind,
                    channel_num=i + 1,
                    selected=(i == self.cursor),
                )

    def draw_movie_browser(self):
        """Paged movie list (stack of title cards)."""
        self.screen.fill(C.BG)
        movies = self._browse_movie_names()
        if not movies:
            msg = (
                "Nothing for kids yet — tag titles in parent mode"
                if self._kids_mode_active and self._kids_allowlist is not None
                else "No movies found"
            )
            t = self.font_md.render(msg, True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        total = len(movies)
        self.cursor = min(self.cursor, total - 1)
        movie_key = movies[self.cursor]
        movie = self.movies[movie_key]
        title = movie.get("title") or movie_key
        ch_num = self._display_movie_channel(movie_key)
        tagged = (
            not self._kids_mode_active and self._title_kids_tagged(movie=movie_key)
        )
        self._draw_header(
            title.upper(),
            badge_text="[kids]" if tagged else "",
        )

        kids = self._kids_mode_active
        page_size = self._stack_page_size_for_view()
        layout = self._stack_browser_layout()
        stack_top = layout["stack_top"]
        stack_bottom = layout["stack_bottom"]
        gap = layout["gap"]
        item_h = min(
            90 if kids else 70,
            (stack_bottom - stack_top - (page_size - 1) * gap) // max(1, page_size),
        )

        first_visible = self._stack_first_visible(self.cursor, total, page_size)
        up_label, down_label, up_active, down_active = self._stack_page_nav(
            first_visible, total, page_size
        )
        if kids:
            self._draw_arrow_nav_bar(layout["up_y"], layout["nav_h"], "up", up_active)
            self._draw_arrow_nav_bar(layout["down_y"], layout["nav_h"], "down", down_active)
        else:
            self._draw_nav_bar(layout["up_y"], up_label, "up", up_active)
            self._draw_nav_bar(layout["down_y"], down_label, "down", down_active)

        for i in range(page_size):
            item_idx = first_visible + i
            if item_idx >= total:
                break
            y = stack_top + i * (item_h + gap)
            if y + item_h > stack_bottom:
                break
            key = movies[item_idx]
            data = self.movies.get(key, {})
            name = data.get("title") or key
            selected = item_idx == self.cursor
            rect = pygame.Rect(30, y, self.sw - 60, item_h)
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            ch = str(self._display_movie_channel(key))
            ch_surf = self.font_lg.render(ch, True, C.GREEN if selected else C.DIM)
            self.screen.blit(
                ch_surf,
                (rect.x + 14, rect.y + (rect.height - ch_surf.get_height()) // 2),
            )

            thumb_size = min(item_h - 12, 64)
            thumb = self.load_image(data.get("thumbnail"), (thumb_size, thumb_size))
            label_x = rect.x + 14 + ch_surf.get_width() + 16
            text_right = rect.right - 14
            if thumb:
                thumb_x = rect.right - thumb.get_width() - 10
                self.screen.blit(
                    thumb,
                    (thumb_x, rect.y + (rect.height - thumb.get_height()) // 2),
                )
                text_right = thumb_x - 10

            title_surf = self.font_md.render(
                name.upper(), True, C.BRIGHT if selected else C.WHITE
            )
            max_w = text_right - label_x
            if title_surf.get_width() > max_w and max_w > 40:
                text = name.upper()
                while self.font_md.size(text + "...")[0] > max_w and len(text) > 3:
                    text = text[:-1]
                title_surf = self.font_md.render(
                    text + "...", True, C.BRIGHT if selected else C.WHITE
                )
            self.screen.blit(
                title_surf,
                (label_x, rect.y + (rect.height - title_surf.get_height()) // 2),
            )

        if not kids:
            self._draw_footer()

    def draw_kids_full_card(self):
        """Kid-friendly full-card view: one show/movie at a time with large thumbnail."""
        self.screen.fill(C.BG)

        if self.view == self.SHOW_LIST:
            names = self._browse_show_names()
            get_title = lambda n: n
            get_thumb = lambda n: self.shows.get(n, {}).get("thumbnail")
            get_ch = self._display_channel
        else:
            names = self._browse_movie_names()
            get_title = lambda k: self.movies.get(k, {}).get("title") or k
            get_thumb = lambda k: self.movies.get(k, {}).get("thumbnail")
            get_ch = self._display_movie_channel

        if not names:
            msg = (
                "Nothing for kids yet — tag titles in parent mode"
                if self._kids_allowlist is not None
                else "Nothing to watch"
            )
            t = self.font_md.render(msg, True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        total = len(names)
        self.cursor = min(self.cursor, total - 1)
        key = names[self.cursor]
        title = get_title(key)
        ch_num = get_ch(key)
        self._draw_header(title.upper())

        layout = self._show_browser_layout(HEADER_BAR_H, kids=True)
        nav_h = layout["nav_h"]
        up_y = layout["up_y"]
        down_y = layout["down_y"]
        content_y = layout["content_y"]
        content_bottom = layout["content_bottom"]
        content_h = max(40, content_bottom - content_y)

        # Up arrow
        up_active = self.cursor > 0
        self._draw_arrow_nav_bar(up_y, nav_h, "up", up_active)

        # Down arrow
        down_active = self.cursor < total - 1
        self._draw_arrow_nav_bar(down_y, nav_h, "down", down_active)

        # Full-height card
        card_pad = 12
        card_rect = pygame.Rect(
            card_pad, content_y + 4,
            self.sw - card_pad * 2, content_h - 8,
        )
        pygame.draw.rect(self.screen, C.BG_CARD, card_rect, border_radius=10)
        pygame.draw.rect(self.screen, C.CYAN, card_rect.inflate(2, 2), 2, border_radius=10)

        # Large channel number on the left
        ch_str = str(ch_num)
        ch_surf = self.font_lg.render(ch_str, True, C.GREEN)
        ch_x = card_rect.x + 18
        ch_y = card_rect.y + (card_rect.height - ch_surf.get_height()) // 2
        self.screen.blit(ch_surf, (ch_x, ch_y))

        # Thumbnail fills remaining space
        thumb_x = ch_x + ch_surf.get_width() + 20
        thumb_w = max(40, card_rect.right - thumb_x - 16)
        thumb_h = max(40, card_rect.height - 20)
        thumb_path = get_thumb(key)
        thumb = self.load_image(thumb_path, (thumb_w, thumb_h))

        if thumb:
            tx = thumb_x + (thumb_w - thumb.get_width()) // 2
            ty = card_rect.y + (card_rect.height - thumb.get_height()) // 2
            self.screen.blit(thumb, (tx, ty))
        else:
            # No thumbnail — show title large
            max_w = thumb_w
            lines = self._wrap_text(title.upper(), self.font_lg, max_w)
            line_h = self.font_lg.size("Mg")[1] + 6
            total_text_h = len(lines) * line_h
            text_start_y = card_rect.y + (card_rect.height - total_text_h) // 2
            for i, line in enumerate(lines):
                surf = self.font_lg.render(line, True, C.WHITE)
                self.screen.blit(
                    surf,
                    surf.get_rect(centerx=thumb_x + thumb_w // 2, top=text_start_y + i * line_h),
                )

    def draw_season_browser(self):
        """Season browser: vertical stack of season cards."""
        self.screen.fill(C.BG)
        seasons = self.seasons_for_show(self.cur_show)
        show_data = self.shows.get(self.cur_show, {})
        total = len(seasons)

        if not seasons:
            t = self.font_md.render("No seasons", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        # Header
        self._draw_header(
            self.cur_show.upper(),
            badge_text=(
                "[kids]"
                if not self._kids_mode_active
                and self._title_kids_tagged(show=self.cur_show)
                else ""
            ),
        )

        layout = self._stack_browser_layout()
        stack_top = layout["stack_top"]
        stack_bottom = layout["stack_bottom"]
        item_h = layout["item_h"]
        gap = layout["gap"]

        first_visible = self._stack_first_visible(self.cursor, total)
        up_label, down_label, up_active, down_active = self._stack_page_nav(
            first_visible, total
        )
        self._draw_nav_bar(layout["up_y"], up_label, "up", up_active)

        for i in range(STACK_VISIBLE):
            item_idx = first_visible + i
            if item_idx >= total:
                break

            y = stack_top + i * (item_h + gap)
            # Ensure card doesn't go below stack area
            if y + item_h > stack_bottom:
                break

            selected = (item_idx == self.cursor)
            season_num = seasons[item_idx]
            season_data = show_data['seasons'][season_num]

            rect = pygame.Rect(30, y, self.sw - 60, item_h)

            # Card background
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            # Channel number — unique per page (1-based position in this list)
            ch_label = str(item_idx + 1)
            ch_surf = self.font_lg.render(ch_label, True, C.GREEN if selected else C.DIM)
            self.screen.blit(ch_surf, (rect.x + 14,
                                       rect.y + (rect.height - ch_surf.get_height()) // 2))

            # Season label — folder name (e.g. Action) or Season N
            s_label = self.season_display_name(self.cur_show, season_num)

            # Episode count / status (right side) — measure first for label truncation
            season_eps = season_data.get('episodes', [])
            n_eps = len(season_eps)
            watched_eps = get_watched_episodes(self.state, self.cur_show, season_num)
            watched_count = sum(1 for e in season_eps if e['number'] in watched_eps)
            nxt = next((e for e in season_eps if e['number'] not in watched_eps), None)
            count_part = f"{n_eps} ep{'s' if n_eps != 1 else ''}"
            if n_eps > 0 and watched_count >= n_eps:
                info_w = self.font_sm.size(f"{count_part}  [done]")[0]
            elif watched_count > 0 and nxt is not None:
                info_w = (
                    self.font_sm.size(f"{count_part}  ")[0]
                    + self.font_sm.size(f"E-{nxt['number']:02d} next")[0]
                )
            else:
                info_w = self.font_sm.size(count_part)[0]

            sl = self.font_md.render(s_label, True, C.BRIGHT if selected else C.WHITE)
            sl_x = rect.x + 14 + ch_surf.get_width() + 16
            max_label_w = rect.right - sl_x - info_w - 20
            if sl.get_width() > max_label_w and max_label_w > 30:
                label_text = s_label
                while self.font_md.size(label_text + "...")[0] > max_label_w and len(label_text) > 3:
                    label_text = label_text[:-1]
                sl = self.font_md.render(label_text + "...", True, C.BRIGHT if selected else C.WHITE)
            self.screen.blit(sl, (sl_x, rect.y + (rect.height - sl.get_height()) // 2))

            info_x = rect.right - 14
            info_y = rect.y + (rect.height - self.font_sm.get_height()) // 2
            if n_eps > 0 and watched_count >= n_eps:
                info = f"{count_part}  [done]"
                it = self.font_sm.render(info, True, C.DIM)
                self.screen.blit(it, (info_x - it.get_width(), info_y))
            elif watched_count > 0 and nxt is not None:
                next_part = f"E-{nxt['number']:02d} next"
                next_surf = self.font_sm.render(next_part, True, C.GREEN)
                count_surf = self.font_sm.render(f"{count_part}  ", True, C.DIM)
                total_w = count_surf.get_width() + next_surf.get_width()
                self.screen.blit(count_surf, (info_x - total_w, info_y))
                self.screen.blit(next_surf, (info_x - next_surf.get_width(), info_y))
            else:
                it = self.font_sm.render(count_part, True, C.DIM)
                self.screen.blit(it, (info_x - it.get_width(), info_y))

        self._draw_nav_bar(layout["down_y"], down_label, "down", down_active)
        self._draw_footer()

    # ─── Episode browser ─────────────────────────────────────────────────

    def draw_episode_browser(self):
        """Episode browser: vertical stack of episode cards."""
        self.screen.fill(C.BG)
        show_data = self.shows.get(self.cur_show, {})
        season_data = show_data.get('seasons', {}).get(self.cur_season, {})
        episodes = season_data.get('episodes', [])
        total = len(episodes)

        if not episodes:
            t = self.font_md.render("No episodes", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            return

        # Header
        self._draw_header(
            f"{self.cur_show.upper()}  -  S-{self.cur_season:02d}",
            badge_text=(
                "[kids]"
                if not self._kids_mode_active
                and self._title_kids_tagged(show=self.cur_show)
                else ""
            ),
        )

        layout = self._stack_browser_layout()
        stack_top = layout["stack_top"]
        stack_bottom = layout["stack_bottom"]
        item_h = layout["item_h"]
        gap = layout["gap"]

        first_visible = self._stack_first_visible(self.cursor, total)
        up_label, down_label, up_active, down_active = self._stack_page_nav(
            first_visible, total
        )
        self._draw_nav_bar(layout["up_y"], up_label, "up", up_active)

        watched_eps = get_watched_episodes(self.state, self.cur_show, self.cur_season)
        pos_ep, pos_secs = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        next_up = next(
            (e['number'] for e in episodes if e['number'] not in watched_eps), None
        )

        for i in range(STACK_VISIBLE):
            item_idx = first_visible + i
            if item_idx >= total:
                break

            ep = episodes[item_idx]
            y = stack_top + i * (item_h + gap)
            if y + item_h > stack_bottom:
                break

            rect = pygame.Rect(30, y, self.sw - 60, item_h)
            selected = (item_idx == self.cursor)
            ep_num = ep['number']
            is_watched = ep_num in watched_eps
            is_next = (ep_num == next_up)
            is_in_progress = (pos_ep is not None and ep_num == pos_ep)

            # Card background
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            elif is_in_progress or is_next:
                pygame.draw.rect(self.screen, C.NEXT_UP, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.NEXT_UP_BORDER, rect, 2, border_radius=8)
                accent = pygame.Rect(rect.x, rect.y + 6, 4, rect.height - 12)
                pygame.draw.rect(self.screen, C.GREEN, accent, border_radius=2)
            elif is_watched:
                pygame.draw.rect(self.screen, C.WATCHED, rect, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            # Channel number on the left (consistent with show browser)
            ch_label = str(item_idx + 1)
            ch_surf = self.font_lg.render(ch_label, True, C.GREEN if selected else C.DIM)
            self.screen.blit(
                ch_surf,
                (rect.x + 14, rect.y + (rect.height - ch_surf.get_height()) // 2),
            )

            # Keep episode text left-aligned; optional artwork floats right.
            thumb = self.load_image(ep.get('thumbnail'), (item_h - 12, item_h - 12))
            label_x = rect.x + 14 + ch_surf.get_width() + 16
            content_right = rect.right - 14
            if thumb:
                tx = rect.right - thumb.get_width() - 10
                ty = rect.y + (rect.height - thumb.get_height()) // 2
                self.screen.blit(thumb, (tx, ty))
                content_right = tx - 8

            # Status indicator (right of card)
            status_text = ""
            status_color = C.DIM
            if is_in_progress and not selected:
                status_text = "RESUME"
                status_color = C.GREEN
            elif is_next and not selected:
                status_text = "NEXT"
                status_color = C.GREEN
            elif is_watched and not is_next and not is_in_progress:
                status_text = "WATCHED"
                status_color = C.DIM
            st = self.font_sm.render(status_text, True, status_color) if status_text else None

            # Calculate available width for text and right-side indicators.
            right_margin = 0
            if st:
                right_margin += st.get_width() + 6
            avail_w = content_right - label_x - right_margin - 8

            # ── Line 1: "E-01  Episode Name" ──
            ep_label = f"E-{ep_num:02d}"
            ep_name = ep.get('name') or ''

            el = self.font_md.render(ep_label, True, C.BRIGHT if selected else C.WHITE)
            gap_w = self.font_md.size("  ")[0]

            # Vertically center the one or two lines
            dur_text = self._get_duration(ep['path'])
            line2_text = dur_text
            line2_color = C.DIM
            if is_in_progress:
                mins = int(pos_secs) // 60
                secs = int(pos_secs) % 60
                resume_label = f"Resume {mins}:{secs:02d}"
                line2_text = f"{resume_label}  {dur_text}" if dur_text else resume_label
                line2_color = C.GREEN
            has_line2 = bool(line2_text)
            line1_h = el.get_height()
            line2_h = self.font_sm.size("0:00")[1] if has_line2 else 0
            total_text_h = line1_h + (line2_h + 2 if has_line2 else 0)
            text_top = rect.y + (rect.height - total_text_h) // 2

            # Draw line 1: "E-01  Name" (selected row marquees when truncated)
            self.screen.blit(el, (label_x, text_top))
            if ep_name and avail_w > el.get_width() + gap_w + 8:
                name_x = label_x + el.get_width() + gap_w
                name_avail = avail_w - el.get_width() - gap_w
                self._blit_marquee_text(
                    ep_name,
                    self.font_md,
                    C.WHITE,
                    name_x,
                    text_top,
                    name_avail,
                    key=(self.cur_show, self.cur_season, ep_num, ep_name),
                    active=selected,
                )

            # ── Line 2: Duration / resume point ──
            if has_line2:
                dur = self.font_sm.render(line2_text, True, line2_color)
                dur_y = text_top + line1_h + 2
                if dur_y + dur.get_height() <= rect.y + rect.height - 2:
                    self.screen.blit(dur, (label_x, dur_y))

            # Status indicator (right side)
            if st:
                self.screen.blit(
                    st,
                    (
                        content_right - st.get_width(),
                        rect.y + (rect.height - st.get_height()) // 2,
                    ),
                )

        self._draw_nav_bar(layout["down_y"], down_label, "down", down_active)
        self._draw_footer()

    # ── Playback drawing (embedded video) ─────────────────────────────────

    def draw_playback(self):
        """Render video frame with overlays during playback.

        Video is full-bleed on the whole canvas; HUD alone respects safe-zone inset.
        Omxplayer mode: video renders on hardware layer — overlays only on canvas.
        """
        self._draw_playback_content()

    def _draw_playback_content(self):
        cw, ch = self.canvas_w, self.canvas_h
        if self.player and self.player.use_omx:
            # omxplayer renders on its own hardware layer — don't fill black
            pass
        else:
            self.screen.fill(C.BLACK)

        if self.player:
            frame = self.player.get_frame()
            if frame:
                # FFmpeg scales/pads to the full canvas — blit edge to edge.
                if frame.get_size() == (cw, ch):
                    self.screen.blit(frame, (0, 0))
                else:
                    scaled = pygame.transform.scale(frame, (cw, ch))
                    self.screen.blit(scaled, (0, 0))
            elif not self.player.use_omx:
                rect, scale = self._playback_overlay_layout()
                t = self._scale_overlay_surface(
                    self.font_md.render("Loading...", True, C.WHITE), scale
                )
                self.screen.blit(
                    t,
                    t.get_rect(
                        center=(rect.x + rect.w // 2, rect.y + rect.h // 2),
                    ),
                )

        self.draw_progress_overlay()
        self.draw_volume_overlay()
        self.draw_pause_overlay()
        self.draw_cache_status_overlay()
        if self._playback_stalled:
            self.draw_stall_overlay()

        self._apply_channel_fx()

    # ─── Progress overlay (during playback) ─────────────────────────────────

    def draw_progress_overlay(self):
        """Progress bar overlay — top season/episode bar, optional bottom title bar, scrub line.
        Green color scheme like a real CRT TV."""
        if not self.player:
            return

        now = pygame.time.get_ticks()
        elapsed = now - self.progress_overlay_timer

        if not self.player.paused and self.progress_overlay_timer > 0 and elapsed > OVERLAY_SHOW_MS:
            return

        if self.player.paused:
            pass
        elif self.progress_overlay_timer > 0 and elapsed < OVERLAY_SHOW_MS:
            pass
        else:
            return

        self.player.update_time()
        progress = self.player.progress()
        time_str = f"{self.player.format_time(self.player.time_pos)} / {self.player.format_time(self.player.duration)}"

        rect, scale = self._playback_overlay_layout()
        pad = HUD_PAD
        top_bar_h = HUD_TOP_BAR_H

        bar_surf = pygame.Surface((rect.w, top_bar_h), pygame.SRCALPHA)
        bar_surf.fill((0, 10, 5, 200))
        self.screen.blit(bar_surf, (rect.x, rect.y))

        ep = self.playing_episode or {}
        ep_num = ep.get('number', 0)
        ep_name = ep.get('name') or ''
        label = f"S-{self.playing_season or 1:02d} - E-{ep_num:02d}"

        rt = self._scale_overlay_surface(
            self.font_md.render(time_str, True, C.GREEN), scale
        )
        rt_x = rect.x + rect.w - rt.get_width() - pad
        rt_y = rect.y + (top_bar_h - rt.get_height()) // 2
        self.screen.blit(rt, (rt_x, rt_y))

        label_max_w = max(20, rt_x - (rect.x + pad) - 8)
        lt = self._truncate_overlay_text(label, self.font_md, C.GREEN, label_max_w, scale=scale)
        self.screen.blit(lt, (rect.x + pad, rect.y + (top_bar_h - lt.get_height()) // 2))

        scrub_h = HUD_SCRUB_H
        scrub_track_h = HUD_SCRUB_TRACK_H
        bottom_bar_h = HUD_TOP_BAR_H if ep_name else 0
        scrub_y = rect.y + rect.h - scrub_track_h

        if ep_name:
            bottom_bar_y = scrub_y - bottom_bar_h
            bottom_bar = pygame.Surface((rect.w, bottom_bar_h), pygame.SRCALPHA)
            bottom_bar.fill((0, 10, 5, 200))
            self.screen.blit(bottom_bar, (rect.x, bottom_bar_y))

            name_surf = self._truncate_overlay_text(
                ep_name, self.font_md, C.GREEN, rect.w - pad * 2, scale=scale
            )
            self.screen.blit(
                name_surf,
                (rect.x + pad, bottom_bar_y + (bottom_bar_h - name_surf.get_height()) // 2),
            )

        bar_w = rect.w - pad * 2
        bar_x = rect.x + pad

        track = pygame.Surface((bar_w, scrub_h), pygame.SRCALPHA)
        track.fill((20, 60, 35, 220))
        self.screen.blit(track, (bar_x, scrub_y + (scrub_track_h - scrub_h) // 2))

        fill_w = max(1, int(bar_w * progress))
        fill = pygame.Surface((fill_w, scrub_h), pygame.SRCALPHA)
        fill.fill((*C.GREEN[:3], 255))
        self.screen.blit(fill, (bar_x, scrub_y + (scrub_track_h - scrub_h) // 2))

        dot_x = bar_x + fill_w
        dot_y = scrub_y + scrub_track_h // 2
        dot_r = HUD_SCRUB_DOT_R
        dot_surf = pygame.Surface((dot_r * 2, dot_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(dot_surf, (*C.BRIGHT, 255), (dot_r, dot_r), dot_r)
        self.screen.blit(dot_surf, (dot_x - dot_r, dot_y - dot_r))

    # ─── Volume overlay ───────────────────────────────────────────────────

    def draw_volume_overlay(self):
        """Simple retro volume bar — upper-right, below the metadata bar."""
        if not self.player:
            return

        now = pygame.time.get_ticks()
        elapsed = now - self.volume_overlay_timer

        if self.volume_overlay_timer <= 0 or elapsed >= OVERLAY_SHOW_MS:
            return

        vol = min(self.player.volume, 100)
        rect, scale = self._playback_overlay_layout()
        pad = HUD_PAD
        top_bar_h = HUD_TOP_BAR_H

        label = self._scale_overlay_surface(
            self.font_md.render("VOLUME", True, C.GREEN), scale
        )
        n_bars = 10
        bar_w = HUD_VOL_BAR_W
        bar_h = HUD_VOL_BAR_H
        bar_gap = 4
        filled = int(n_bars * vol / 100)

        total_bar_w = n_bars * bar_w + (n_bars - 1) * bar_gap
        total_w = label.get_width() + 16 + total_bar_w
        x = rect.x + rect.w - total_w - pad
        y = rect.y + top_bar_h + pad

        self.screen.blit(label, (x, y + (bar_h - label.get_height()) // 2))

        bar_x = x + label.get_width() + 16
        for i in range(n_bars):
            bx = bar_x + i * (bar_w + bar_gap)
            color = C.GREEN if i < filled else C.GREEN_DIM
            pygame.draw.rect(self.screen, color, (bx, y, bar_w, bar_h))

    # ─── Pause overlay ────────────────────────────────────────────────────

    def draw_pause_overlay(self):
        """Show PAUSED indicator when video is paused."""
        if not self.player or not self.player.paused:
            return

        rect, scale = self._playback_overlay_layout()
        txt = self._scale_overlay_surface(
            self.font_lg.render("PAUSED", True, C.GREEN), scale
        )
        cx = rect.x + rect.w // 2
        cy = rect.y + rect.h // 2
        self.screen.blit(txt, txt.get_rect(center=(cx, cy)))

    # ─── Splash / help screens ────────────────────────────────────────────

    def _help_pages(
        self, *, device: str | None = None
    ) -> list[tuple[str, list[tuple[str, str | None]]]]:
        """Context pages for the in-app help browser."""
        device = device or self._help_input_device()
        bind = lambda action: self._help_binding(action, device=device)
        up = bind("up")
        down = bind("down")
        left = bind("left")
        right = bind("right")
        select = bind("select")
        back = bind("back")
        number_section = (
            [
                ("NUMBER KEYS", None),
                ("channel / index", "type 1-999  (enters after ~1.5s)"),
                ("back", "press 0"),
                ("prev / next page", "press 01 / 02"),
                ("alphabet jump", "press 00  or  " + bind("letter_menu")),
                ("test patterns", "press 001 / 002 / 003"),
            ]
            if device == "keyboard"
            else [
                ("NUMBER KEYS", None),
                ("channel / page codes", "use keyboard number keys"),
                ("alphabet / kids / help", "keyboard only on this pad"),
            ]
        )
        pages: list[tuple[str, list[tuple[str, str | None]]]] = [
            (
                "Overview",
                [
                    ("ABOUT", None),
                    ("what is this", "Cable-style browser for your show & movie library"),
                    ("open this help", bind("help")),
                    ("hide status bar", bind("footer_hints_toggle")),
                    ("kids / parent mode", bind("kids_mode_toggle")),
                    ("quit", bind("quit")),
                    *number_section,
                ],
            ),
            (
                "Library",
                [
                    ("SHOWS / MOVIES PICKER", None),
                    ("move", f"{up} / {down}"),
                    ("open", f"{select} or {right}"),
                    ("quit dialog", back),
                    (
                        "jump",
                        "press 1 = Shows, 2 = Movies"
                        if device == "keyboard"
                        else "keyboard number keys",
                    ),
                ],
            ),
            (
                "Shows",
                [
                    ("SHOW LIST", None),
                    ("move", f"{up} / {down}"),
                    ("open seasons", f"{select} or {right}"),
                    (
                        "page",
                        "01 previous  /  02 next"
                        if device == "keyboard"
                        else "keyboard 01 / 02",
                    ),
                    ("alphabet jump", bind("letter_menu")),
                    ("tag for kids", bind("kids_tag_toggle")),
                    ("reset watch / rescan", f"tap {bind('reset')} / hold"),
                    (
                        "channel jump",
                        "type the show channel number"
                        if device == "keyboard"
                        else "keyboard number keys",
                    ),
                ],
            ),
            (
                "Movies",
                [
                    ("MOVIE LIST", None),
                    ("move", f"{up} / {down}"),
                    ("play", f"{select} or {right}"),
                    (
                        "page",
                        "01 previous  /  02 next"
                        if device == "keyboard"
                        else "keyboard 01 / 02",
                    ),
                    ("alphabet jump", bind("letter_menu")),
                    ("tag for kids", bind("kids_tag_toggle")),
                    (
                        "channel jump",
                        "type the movie channel number"
                        if device == "keyboard"
                        else "keyboard number keys",
                    ),
                ],
            ),
            (
                "Seasons",
                [
                    ("SEASON LIST", None),
                    ("move", f"{up} / {down}"),
                    ("open episodes", f"{select} or {right}"),
                    ("back to shows", f"{left} or {back}"),
                    (
                        "page",
                        "01 previous  /  02 next"
                        if device == "keyboard"
                        else "keyboard 01 / 02",
                    ),
                    (
                        "jump",
                        "press season number on this page"
                        if device == "keyboard"
                        else "keyboard number keys",
                    ),
                    ("reset season", bind("reset")),
                ],
            ),
            (
                "Episodes",
                [
                    ("EPISODE LIST", None),
                    ("move", f"{up} / {down}"),
                    ("play", f"{select} or {right}"),
                    ("back to seasons", f"{left} or {back}"),
                    (
                        "page",
                        "01 previous  /  02 next"
                        if device == "keyboard"
                        else "keyboard 01 / 02",
                    ),
                    (
                        "jump",
                        "press episode number on this page"
                        if device == "keyboard"
                        else "keyboard number keys",
                    ),
                    ("reset episode", bind("reset")),
                ],
            ),
            (
                "Playback",
                [
                    ("WHILE WATCHING", None),
                    ("volume", f"{up} / {down}"),
                    ("seek +/-10s", f"{left} / {right}"),
                    ("pause", select),
                    (
                        "stop",
                        f"{back} or press 0" if device == "keyboard" else back,
                    ),
                    ("cancel cache", bind("cache_cancel")),
                ],
            ),
            (
                "Settings",
                [
                    ("SETUP", None),
                    ("rebind keys", bind("key_config")),
                    ("gamepad setup", bind("gamepad_config")),
                    ("safe zone", bind("safe_zone")),
                    ("status bar on/off", bind("footer_hints_toggle")),
                    ("kids allowlist", "parent mode: " + bind("kids_tag_toggle")),
                    ("kids card/full view", bind("kids_view_toggle")),
                ],
            ),
        ]
        return pages

    def _help_page_index_for_view(self, pages=None) -> int:
        """Start help on the page that matches the current browse screen."""
        pages = pages if pages is not None else self._help_pages()
        titles = [title for title, _ in pages]
        wanted = {
            self.LIBRARY_SELECT: "Library",
            self.SHOW_LIST: "Shows",
            self.MOVIE_LIST: "Movies",
            self.SEASON_SELECT: "Seasons",
            self.EPISODE_SELECT: "Episodes",
            self.PLAYING: "Playback",
        }.get(self.view, "Overview")
        try:
            return titles.index(wanted)
        except ValueError:
            return 0

    def _splash_help_content_height(self, lines, section_gap):
        """Total height of the help menu text block (matches draw layout)."""
        y = 0
        first_section = True
        for label, detail in lines:
            if detail is None:
                if not first_section:
                    y += section_gap
                first_section = False
                y += self.font_sm.render(label, True, C.CYAN).get_height() + 6
            else:
                lt = self.font_sm.render(label, True, C.WHITE)
                dt = self.font_sm.render(detail, True, C.GREEN)
                left_x = 70
                right_x = self.sw - dt.get_width() - 70
                if right_x < left_x + lt.get_width() + 20:
                    y += lt.get_height() + 3 + dt.get_height() + 3
                else:
                    y += max(lt.get_height(), dt.get_height()) + 4
        return y

    def _draw_help_lines(self, lines, y_start, content_max_y, section_gap=16) -> None:
        y = y_start
        first_section = True
        for label, detail in lines:
            if y >= content_max_y:
                break
            if detail is None:
                if not first_section:
                    y += section_gap
                first_section = False
                hdr = self.font_sm.render(label, True, C.CYAN)
                if y + hdr.get_height() > content_max_y:
                    break
                self.screen.blit(hdr, (50, y))
                y += hdr.get_height() + 6
            else:
                lt = self.font_sm.render(label, True, C.WHITE)
                dt = self.font_sm.render(detail, True, C.GREEN)
                row_h = max(lt.get_height(), dt.get_height()) + 4
                if y + row_h > content_max_y:
                    break
                left_x = 70
                right_x = self.sw - dt.get_width() - 70
                if right_x < left_x + lt.get_width() + 20:
                    self.screen.blit(lt, (left_x, y))
                    y += lt.get_height() + 3
                    if y + dt.get_height() > content_max_y:
                        break
                    self.screen.blit(
                        dt, (max(20, self.sw - dt.get_width() - 70), y)
                    )
                    y += dt.get_height() + 3
                else:
                    self.screen.blit(lt, (left_x, y))
                    self.screen.blit(dt, (right_x, y))
                    y += row_h

    def draw_startup_splash(self):
        """Brief brand splash on launch. Dismiss with any key."""
        start = pygame.time.get_ticks()
        duration = 8000
        help_key = format_action_keys(self.keymap, "help")

        while self.running:
            for event in pygame.event.get():
                if self._handle_window_event(event):
                    continue
                if event.type == pygame.QUIT:
                    self._handle_quit_event("splash")
                    return
                if event.type == pygame.KEYDOWN:
                    return

            elapsed = pygame.time.get_ticks() - start
            if elapsed >= duration:
                return
            remaining = max(0, (duration - elapsed) // 1000)

            with self._ui_layout(letterbox=True):
                self.screen.fill(C.BG)
                title = self.font_lg.render("TV TIME CAPSULE", True, C.BRIGHT)
                self.screen.blit(
                    title, title.get_rect(centerx=self.sw // 2, centery=self.sh // 2 - 48)
                )
                pygame.draw.line(
                    self.screen,
                    C.BLUE,
                    (self.sw // 2 - 160, self.sh // 2 - 18),
                    (self.sw // 2 + 160, self.sh // 2 - 18),
                    1,
                )
                blurb = self.font_sm.render(
                    "Your media library, cable-style",
                    True,
                    C.DIM,
                )
                self.screen.blit(
                    blurb, blurb.get_rect(centerx=self.sw // 2, centery=self.sh // 2 + 8)
                )
                help_line = self.font_sm.render(
                    f"Press {help_key} anytime for controls",
                    True,
                    C.CYAN,
                )
                self.screen.blit(
                    help_line,
                    help_line.get_rect(centerx=self.sw // 2, centery=self.sh // 2 + 40),
                )
                hint = self.font_sm.render(
                    f"Press any key to continue...  {remaining}s",
                    True,
                    C.DIM,
                )
                self.screen.blit(
                    hint, hint.get_rect(centerx=self.sw // 2, bottom=self.sh - 24)
                )

            self.present()
            self.clock.tick(15)

    def draw_splash(self):
        """Compatibility alias — open context help for the current screen."""
        self.draw_help()

    def draw_help(self, start_index: int | None = None):
        """Multi-page help. Starts on the page for the current browse view.

        Shows keyboard or gamepad bindings (toggle with select). Defaults to the
        device used for the most recent key/button press.
        """
        device = self._help_input_device()
        pages = self._help_pages(device=device)
        if not pages:
            return
        page = (
            start_index
            if start_index is not None
            else self._help_page_index_for_view(pages)
        )
        page = max(0, min(len(pages) - 1, page))
        can_toggle_gamepad = self._gamepad_count > 0

        while self.running:
            for event in pygame.event.get():
                if self._handle_window_event(event):
                    continue
                if event.type == pygame.QUIT:
                    self._handle_quit_event("help")
                    return
                action = None
                if event.type == pygame.KEYDOWN:
                    self._note_keyboard_input()
                    key_action = self._action_for_key(event.key)
                    if key_action in ("back", "help"):
                        return
                    if key_action == "select":
                        if can_toggle_gamepad:
                            device = "gamepad" if device == "keyboard" else "keyboard"
                            self._last_input_device = device
                            pages = self._help_pages(device=device)
                            page = min(page, len(pages) - 1)
                        continue
                    action = self._key_to_browse_action(event.key)
                else:
                    action = self._gamepad.event_to_action(event)
                    if action:
                        self._note_gamepad_input()
                if action in ("up", "left"):
                    page = (page - 1) % len(pages)
                elif action in ("down", "right"):
                    page = (page + 1) % len(pages)
                elif action == "back":
                    return
                elif action == "select" and can_toggle_gamepad:
                    device = "gamepad" if device == "keyboard" else "keyboard"
                    self._last_input_device = device
                    pages = self._help_pages(device=device)
                    page = min(page, len(pages) - 1)

            title, lines = pages[page]
            with self._ui_layout(letterbox=True):
                self.screen.fill(C.BG)
                device_label = f" ({device.upper()})"
                hdr = self.font_md.render(title.upper() + device_label, True, C.BRIGHT)
                self.screen.blit(hdr, hdr.get_rect(centerx=self.sw // 2, top=18))
                page_label = self.font_sm.render(
                    f"{page + 1} / {len(pages)}", True, C.GREEN
                )
                self.screen.blit(
                    page_label, page_label.get_rect(right=self.sw - 20, top=22)
                )
                pygame.draw.line(self.screen, C.BLUE, (40, 52), (self.sw - 40, 52), 1)

                content_top = 66
                content_bottom = self.sh - 48
                self._draw_help_lines(lines, content_top, content_bottom)

                pygame.draw.line(
                    self.screen,
                    C.BLUE,
                    (40, self.sh - 36),
                    (self.sw - 40, self.sh - 36),
                    1,
                )
                if can_toggle_gamepad:
                    other = "gamepad" if device == "keyboard" else "keyboard"
                    toggle = self._help_binding("select", device=device)
                    hint_text = f"{toggle}: view {other}  |  Esc: close"
                else:
                    hint_text = "Esc: close"
                hint = self.font_sm.render(hint_text, True, C.DIM)
                self.screen.blit(
                    hint, hint.get_rect(centerx=self.sw // 2, centery=self.sh - 18)
                )

            self.present()
            self.clock.tick(30)

    # ─── Now-playing splash ──────────────────────────────────────────────

    def draw_now_playing(self, show, season, episode, channel, resume_secs=None):
        """Splash screen before video plays. Green accent."""
        if not self._now_playing_splash or self._now_playing_splash_ms <= 0:
            return

        self._blit_now_playing_content(
            show, season, episode, channel, resume_secs=resume_secs
        )
        self.present()
        # Pump/clear events while waiting so held keys (and key-repeat KEYDOWNs)
        # do not pile up and immediately pause/seek when playback begins.
        deadline = pygame.time.get_ticks() + self._now_playing_splash_ms
        while pygame.time.get_ticks() < deadline:
            pygame.event.clear()
            self.clock.tick(30)

        self.screen.fill(C.BLACK)
        self.present()
        pygame.event.clear()

    def _format_cache_bytes(self, nbytes: int) -> str:
        if nbytes >= 1024 ** 3:
            return f"{nbytes / (1024 ** 3):.1f} GB"
        if nbytes >= 1024 ** 2:
            return f"{nbytes / (1024 ** 2):.1f} MB"
        if nbytes >= 1024:
            return f"{nbytes / 1024:.0f} KB"
        return f"{nbytes} B"

    def _draw_cache_progress_bar(
        self,
        fraction: float,
        bytes_done: int,
        total_bytes: int,
        *,
        footer: str | None = None,
        playback: bool = False,
    ) -> None:
        """Download progress bar on the now-playing splash or during paused playback."""
        if footer is None:
            footer = f"{format_action_keys(self.keymap, 'back')} to cancel"
        rect, scale = self._playback_overlay_layout()
        pad = HUD_PAD
        bar_w = max(120, rect.w - pad * 2)
        bar_h = max(6, int(HUD_SCRUB_H * scale))
        bottom_inset = int(80 * scale) if playback else int(28 * scale)
        track_y = rect.y + rect.h - pad - bar_h - bottom_inset
        bar_x = rect.x + (rect.w - bar_w) // 2

        track = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
        track.fill((30, 30, 30, 200))
        self.screen.blit(track, (bar_x, track_y))

        clamped = max(0.0, min(1.0, fraction))
        fill_w = max(0, min(bar_w, int(bar_w * clamped)))
        if fill_w > 0:
            fill = pygame.Surface((fill_w, bar_h), pygame.SRCALPHA)
            fill.fill((*C.GREEN, 220))
            self.screen.blit(fill, (bar_x, track_y))

        pct = int(clamped * 100)
        label = (
            f"CACHING  {pct}%  "
            f"({self._format_cache_bytes(bytes_done)} / {self._format_cache_bytes(total_bytes)})"
        )
        hint = self._scale_overlay_surface(
            self.font_sm.render(label, True, C.GREEN), scale
        )
        self.screen.blit(
            hint,
            hint.get_rect(centerx=rect.x + rect.w // 2, centery=track_y - int(14 * scale)),
        )
        footer_surf = self._scale_overlay_surface(
            self.font_sm.render(footer, True, C.DIM), scale
        )
        self.screen.blit(
            footer_surf,
            footer_surf.get_rect(
                centerx=rect.x + rect.w // 2, centery=track_y + bar_h + int(16 * scale)
            ),
        )

    def _is_streaming_remote(self) -> bool:
        if not self.player or not self._playing_source_path:
            return False
        return not self._playback_cache.is_playing_from_cache(
            self.player.filepath, self._playing_source_path
        )

    def _background_cache_in_progress(self) -> bool:
        source = self._playing_source_path
        if not source:
            return False
        cache = self._playback_cache
        if cache.get_cached_path(source):
            return False
        return cache.is_copy_active(source) or cache.get_copy_progress(source) is not None

    def _should_show_cache_overlay(self) -> bool:
        return (
            self.player is not None
            and self.player.paused
            and self._is_streaming_remote()
            and self._background_cache_in_progress()
            and not self._playback_cache_suppressed
        )

    def draw_cache_status_overlay(self) -> None:
        """Cache progress while paused during streamed remote playback."""
        if not self._should_show_cache_overlay():
            return
        source = self._playing_source_path
        prog = self._playback_cache.get_copy_progress(source)
        if prog:
            done, total = prog
            frac = done / total if total else 0.0
        else:
            done, total, frac = 0, 1, 0.0
        self._draw_cache_progress_bar(
            frac,
            done,
            total,
            footer="C cancel cache",
            playback=True,
        )

    def _cancel_background_cache(self) -> None:
        if not self._playing_source_path:
            return
        self._playback_cache.cancel_cache(self._playing_source_path)
        self._playback_cache_suppressed = True
        self._playback_allow_hot_swap = False

    def _wait_for_playback_cache(self, source_path, splash_args) -> str:
        """Show the title screen with a cache progress bar until the copy finishes.

        Returns ``cached``, ``stream`` (play now from remote), or ``cancelled``.
        """
        cache = self._playback_cache
        if cache.get_cached_path(source_path):
            return "cached"

        cache.schedule_cache(source_path)
        show, season, episode, channel, resume_secs = splash_args
        km = self.keymap
        footer = (
            f"{format_action_keys(km, 'select')} play from stream  |  "
            f"{format_action_keys(km, 'back')} cancel"
        )

        while self.running:
            for event in pygame.event.get():
                if self._handle_window_event(event):
                    continue
                if event.type == pygame.QUIT:
                    self._handle_quit_event("cache-wait")
                    if not self.running:
                        return "cancelled"
                if event.type == pygame.KEYDOWN:
                    action = self._action_for_key(event.key)
                    if action == "back":
                        cache.cancel_cache(source_path)
                        return "cancelled"
                    if action == "select":
                        return "stream"
                action = self._gamepad.event_to_action(event)
                if action == "back":
                    cache.cancel_cache(source_path)
                    return "cancelled"
                if action == "select":
                    return "stream"

            cached = cache.get_cached_path(source_path)
            if cached:
                self._blit_now_playing_content(
                    show, season, episode, channel, resume_secs=resume_secs
                )
                total = os.path.getsize(cached)
                self._draw_cache_progress_bar(1.0, total, total, footer=footer)
                self.present()
                pygame.event.clear()
                return "cached"

            if not cache.is_copy_active(source_path):
                if cache.get_copy_progress(source_path) is None:
                    LOG.warning("cache before play failed; streaming from remote")
                    return "stream"

            prog = cache.get_copy_progress(source_path)
            self._blit_now_playing_content(
                show, season, episode, channel, resume_secs=resume_secs
            )
            if prog:
                done, total = prog
                frac = done / total if total else 0.0
            else:
                done, total, frac = 0, 1, 0.0
            self._draw_cache_progress_bar(frac, done, total, footer=footer)
            self.present()
            self.clock.tick(30)

        return "cancelled"

    # ─── Key configuration ────────────────────────────────────────────────

    def _key_to_browse_action(self, key):
        """Map a pygame key code to a browse action, or None."""
        action = self._action_for_key(key)
        if action in ("up", "down", "left", "right", "select", "back"):
            return action
        return None

    def _key_to_playback_action(self, key):
        """Map a pygame key code to a playback action, or None."""
        action = self._action_for_key(key)
        if action in ("up", "down", "left", "right", "select", "back"):
            return action
        return None

    # ─── Confirm exit dialog ────────────────────────────────────────────

    def draw_confirm_exit(self):
        """'Are you sure?' exit confirmation dialog."""
        with self._ui_layout(letterbox=True):
            self.screen.fill(C.BG)

            # Dim overlay
            overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            self.screen.blit(overlay, (0, 0))

            # Dialog box
            box_w = 400
            box_h = 160
            box_x = (self.sw - box_w) // 2
            box_y = (self.sh - box_h) // 2

            pygame.draw.rect(self.screen, C.BG_CARD, (box_x, box_y, box_w, box_h), border_radius=10)
            pygame.draw.rect(self.screen, C.BLUE, (box_x, box_y, box_w, box_h), 2, border_radius=10)

            # Title
            title = self.font_md.render("Quit?", True, C.BRIGHT)
            self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=box_y + 40))

            # Buttons — simple Yes / No
            btn_w = 100
            btn_h = 44
            btn_y = box_y + 95
            gap = 40
            total_btn_w = btn_w * 2 + gap
            btn_start_x = box_x + (box_w - total_btn_w) // 2

            # Yes button
            yes_x = btn_start_x
            yes_rect = pygame.Rect(yes_x, btn_y, btn_w, btn_h)
            yes_sel = self._confirm_exit_yes
            pygame.draw.rect(
                self.screen,
                C.BG_CARD_SEL if yes_sel else C.BG_CARD,
                yes_rect,
                border_radius=6,
            )
            pygame.draw.rect(
                self.screen,
                C.CYAN if yes_sel else C.DIM,
                yes_rect,
                2,
                border_radius=6,
            )
            yes_txt = self.font_sm.render("Yes", True, C.BRIGHT if yes_sel else C.DIM)
            self.screen.blit(yes_txt, yes_txt.get_rect(center=yes_rect.center))

            # No button
            no_x = btn_start_x + btn_w + gap
            no_rect = pygame.Rect(no_x, btn_y, btn_w, btn_h)
            no_sel = not self._confirm_exit_yes
            pygame.draw.rect(
                self.screen,
                C.BG_CARD_SEL if no_sel else C.BG_CARD,
                no_rect,
                border_radius=6,
            )
            pygame.draw.rect(
                self.screen,
                C.CYAN if no_sel else C.DIM,
                no_rect,
                2,
                border_radius=6,
            )
            no_txt = self.font_sm.render("No", True, C.BRIGHT if no_sel else C.DIM)
            self.screen.blit(no_txt, no_txt.get_rect(center=no_rect.center))


    def _set_confirm_exit_choice(self, yes: bool) -> None:
        self._confirm_exit_yes = bool(yes)

    def _activate_confirm_exit_choice(self) -> None:
        if self._confirm_exit_yes:
            self._request_quit(source="confirm-exit")
        else:
            self.view = getattr(
                self, "_confirm_exit_return_view", self._view_for_library_layout()
            )

    def _process_confirm_exit_action(self, action: str) -> None:
        # Yes is on the left, No on the right.
        if action in ("left", "up"):
            self._set_confirm_exit_choice(True)
        elif action in ("right", "down"):
            self._set_confirm_exit_choice(False)
        elif action == "select":
            self._activate_confirm_exit_choice()
        elif action == "back":
            self.view = getattr(
                self, "_confirm_exit_return_view", self._view_for_library_layout()
            )

    # ─── Safe zone calibration ───────────────────────────────────────────

    def enter_safe_zone_editor(self) -> None:
        self._safe_zone_return_view = self.view
        self._safe_zone_backup = (self._safe_zone_margins, self._safe_zone_offset)
        self._sz_edit_margins = self._safe_zone_margins
        self._sz_edit_offset = self._safe_zone_offset
        self._safe_zone_edit_mode = "zoom"
        self._safe_zone_save_prompt = False
        self._safe_zone_save_yes = True
        self.view = self.SAFE_ZONE_EDIT

    def _apply_sz_draft_to_runtime(self) -> None:
        self._safe_zone_margins = self._sz_edit_margins
        self._safe_zone_offset = self._sz_edit_offset
        self._safe_zone_enabled = safe_zone_enabled(self._sz_edit_margins)
        frame = safe_zone_frame(self._sz_edit_margins, self._sz_edit_offset)
        self._pending_canvas_size = None
        self._pending_safe_zone_frame = None
        self._apply_safe_zone_frame(frame)

    def _restore_safe_zone_backup(self) -> None:
        if self._safe_zone_backup is None:
            self._apply_safe_zone_from_config()
            return
        margins, offset = self._safe_zone_backup
        self._sz_edit_margins = margins
        self._sz_edit_offset = offset
        self._apply_sz_draft_to_runtime()

    def _commit_safe_zone_edit(self) -> None:
        ui_cfg = dict(self.config.get("ui") or {})
        sz = safe_zone_to_config(self._sz_edit_margins, self._sz_edit_offset)
        sz["offset_x"] = self._sz_edit_offset.x
        sz["offset_y"] = self._sz_edit_offset.y
        ui_cfg["safe_zone"] = sz
        self.config["ui"] = ui_cfg
        save_config(self.config)
        self._apply_sz_draft_to_runtime()

    def exit_safe_zone_editor(self, *, save: bool) -> None:
        if save:
            self._commit_safe_zone_edit()
        else:
            self._restore_safe_zone_backup()
        self._safe_zone_backup = None
        self._safe_zone_save_prompt = False
        self.view = self._safe_zone_return_view

    def _toggle_safe_zone_edit_mode(self) -> None:
        self._safe_zone_edit_mode = (
            "position" if self._safe_zone_edit_mode == "zoom" else "zoom"
        )

    def _adjust_safe_zone_edit(self, direction: str) -> None:
        if self._safe_zone_edit_mode == "position":
            ox, oy = self._sz_edit_offset.x, self._sz_edit_offset.y
            step = SAFE_ZONE_OFFSET_STEP
            if direction == "left":
                ox -= step
            elif direction == "right":
                ox += step
            elif direction == "up":
                oy -= step
            elif direction == "down":
                oy += step
            self._sz_edit_offset = clamp_offset(SafeZoneOffset(ox, oy))
        else:
            step = SAFE_ZONE_MARGIN_STEP
            m = self._sz_edit_margins
            if direction == "up":
                m = adjust_margins_uniform(m, vertical=-step)
            elif direction == "down":
                m = adjust_margins_uniform(m, vertical=step)
            elif direction == "left":
                m = adjust_margins_uniform(m, horizontal=-step)
            elif direction == "right":
                m = adjust_margins_uniform(m, horizontal=step)
            self._sz_edit_margins = m
        self._apply_sz_draft_to_runtime()

    def _process_safe_zone_save_action(self, action: str) -> None:
        if action in ("left", "up"):
            self._safe_zone_save_yes = True
        elif action in ("right", "down"):
            self._safe_zone_save_yes = False
        elif action == "select":
            self.exit_safe_zone_editor(save=self._safe_zone_save_yes)
        elif action == "back":
            self._safe_zone_save_prompt = False

    def _process_safe_zone_edit_action(self, action: str) -> None:
        if self._safe_zone_save_prompt:
            self._process_safe_zone_save_action(action)
            return
        if action == "select":
            self._toggle_safe_zone_edit_mode()
        elif action == "back":
            self._safe_zone_save_prompt = True
            self._safe_zone_save_yes = True
        elif action in ("up", "down", "left", "right"):
            self._adjust_safe_zone_edit(action)

    def draw_safe_zone_editor(self) -> None:
        """Full-frame safe zone preview — white inset box with diagonal guides."""
        surface = self.screen
        cw, ch = self.canvas_w, self.canvas_h
        surface.fill(C.BLACK)

        frame = safe_zone_frame(self._sz_edit_margins, self._sz_edit_offset)
        ui = frame.ui

        safe_rect = pygame.Rect(ui.x, ui.y, ui.w, ui.h)
        pygame.draw.rect(surface, C.WHITE, safe_rect)
        pygame.draw.line(
            surface, C.BLACK, safe_rect.topleft, safe_rect.bottomright, 2
        )
        pygame.draw.line(
            surface, C.BLACK, safe_rect.topright, safe_rect.bottomleft, 2
        )
        pygame.draw.rect(surface, C.DIM, (0, 0, cw, ch), 1)

        zoom_active = self._safe_zone_edit_mode == "zoom"
        pos_active = not zoom_active
        mode_y = 24
        zoom_color = C.GREEN if zoom_active else C.DIM
        pos_color = C.GREEN if pos_active else C.DIM
        zoom_label = self.font_md.render("ZOOM", True, zoom_color)
        pos_label = self.font_md.render("POSITION", True, pos_color)
        gap = 24
        total_w = zoom_label.get_width() + gap + pos_label.get_width()
        start_x = (cw - total_w) // 2
        surface.blit(zoom_label, (start_x, mode_y))
        surface.blit(pos_label, (start_x + zoom_label.get_width() + gap, mode_y))

        m = self._sz_edit_margins
        o = self._sz_edit_offset
        stats = (
            f"T{m.top:.1f}% B{m.bottom:.1f}% L{m.left:.1f}% R{m.right:.1f}%"
            f"   X{o.x} Y{o.y}"
        )
        stats_surf = self.font_sm.render(stats, True, C.CYAN)
        surface.blit(stats_surf, stats_surf.get_rect(centerx=cw // 2, top=52))

        km = self.keymap
        if self._safe_zone_save_prompt:
            hint_text = (
                f"Save changes?  {format_action_keys(km, 'left')} Yes   "
                f"{format_action_keys(km, 'right')} No   "
                f"{format_action_keys(km, 'select')} confirm   "
                f"{format_action_keys(km, 'back')} cancel"
            )
        elif zoom_active:
            hint_text = (
                f"{format_action_keys(km, 'up')}/{format_action_keys(km, 'down')} margins  |  "
                f"{format_action_keys(km, 'left')}/{format_action_keys(km, 'right')} horizontal  |  "
                f"{format_action_keys(km, 'select')}: position  |  "
                f"{format_action_keys(km, 'back')}: save"
            )
        else:
            hint_text = (
                f"{format_action_keys(km, 'up')}/{format_action_keys(km, 'down')}/"
                f"{format_action_keys(km, 'left')}/{format_action_keys(km, 'right')} move  |  "
                f"{format_action_keys(km, 'select')}: zoom  |  "
                f"{format_action_keys(km, 'back')}: save"
            )
        hint = self.font_sm.render(hint_text, True, C.DIM)
        max_hint_w = cw - 32
        if hint.get_width() > max_hint_w:
            # Truncate to fit
            text = hint_text
            while self.font_sm.size(text + "...")[0] > max_hint_w and len(text) > 3:
                text = text[:-1]
            hint = self.font_sm.render(text + "...", True, C.DIM)
        surface.blit(hint, hint.get_rect(centerx=cw // 2, bottom=ch - 16))

        if self._safe_zone_save_prompt:
            self._draw_safe_zone_save_prompt_on(surface, cw, ch)

        self.present()

    def _draw_safe_zone_save_prompt_on(
        self, surface: pygame.Surface, cw: int, ch: int
    ) -> None:
        overlay = pygame.Surface((cw, ch), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surface.blit(overlay, (0, 0))

        box_w = 420
        box_h = 160
        box_x = (cw - box_w) // 2
        box_y = (ch - box_h) // 2

        pygame.draw.rect(surface, C.BG_CARD, (box_x, box_y, box_w, box_h), border_radius=10)
        pygame.draw.rect(surface, C.BLUE, (box_x, box_y, box_w, box_h), 2, border_radius=10)

        title = self.font_md.render("Save safe zone changes?", True, C.BRIGHT)
        surface.blit(title, title.get_rect(centerx=cw // 2, centery=box_y + 40))

        btn_w = 100
        btn_h = 44
        btn_y = box_y + 95
        gap = 40
        btn_start_x = box_x + (box_w - btn_w * 2 - gap) // 2

        yes_rect = pygame.Rect(btn_start_x, btn_y, btn_w, btn_h)
        yes_sel = self._safe_zone_save_yes
        pygame.draw.rect(
            surface,
            C.BG_CARD_SEL if yes_sel else C.BG_CARD,
            yes_rect,
            border_radius=6,
        )
        pygame.draw.rect(
            surface,
            C.CYAN if yes_sel else C.DIM,
            yes_rect,
            2,
            border_radius=6,
        )
        yes_txt = self.font_sm.render("Yes", True, C.BRIGHT if yes_sel else C.DIM)
        surface.blit(yes_txt, yes_txt.get_rect(center=yes_rect.center))

        no_x = btn_start_x + btn_w + gap
        no_rect = pygame.Rect(no_x, btn_y, btn_w, btn_h)
        no_sel = not self._safe_zone_save_yes
        pygame.draw.rect(
            surface,
            C.BG_CARD_SEL if no_sel else C.BG_CARD,
            no_rect,
            border_radius=6,
        )
        pygame.draw.rect(
            surface,
            C.CYAN if no_sel else C.DIM,
            no_rect,
            2,
            border_radius=6,
        )
        no_txt = self.font_sm.render("No", True, C.BRIGHT if no_sel else C.DIM)
        surface.blit(no_txt, no_txt.get_rect(center=no_rect.center))

    # ─── Key configuration ────────────────────────────────────────────────

    def draw_key_config(self, capturing=False):
        """Key configuration screen with white/blue theme."""
        with self._ui_layout(letterbox=True):
            self.screen.fill(C.BG)

            title = self.font_lg.render("KEY SETUP", True, C.BLUE)
            self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=40))

            km = self.keymap

            page = self.config_cursor // KEY_CONFIG_ROWS
            page_count = max(1, (len(KEY_ACTIONS) + KEY_CONFIG_ROWS - 1) // KEY_CONFIG_ROWS)
            page_start = page * KEY_CONFIG_ROWS
            visible = KEY_ACTIONS[page_start : page_start + KEY_CONFIG_ROWS]

            page_label = self.font_sm.render(
                f"Page {page + 1} / {page_count}",
                True,
                C.DIM,
            )
            self.screen.blit(page_label, page_label.get_rect(centerx=self.sw // 2, centery=82))

            y_start = 110
            row_h = 44
            label_x = 50
            row_font = self.font_sm

            # Reserve right 45% of the row for key bindings text.
            key_area_frac = 0.45
            bar_left = 30
            bar_right = self.sw - 30
            bar_w = bar_right - bar_left
            key_area_w = int(bar_w * key_area_frac)
            key_area_x = bar_right - key_area_w
            label_max_w = max(20, key_area_x - label_x - 16)

            for i, (action_id, action_label) in enumerate(visible):
                global_index = page_start + i
                y = y_start + i * row_h

                selected = global_index == self.config_cursor

                bar_rect = pygame.Rect(bar_left, y, bar_w, row_h - 6)
                if selected:
                    pygame.draw.rect(self.screen, C.BG_CARD_SEL, bar_rect, border_radius=6)
                    pygame.draw.rect(self.screen, C.CYAN, bar_rect.inflate(2, 2), 2, border_radius=7)
                else:
                    pygame.draw.rect(self.screen, C.BG_CARD, bar_rect, border_radius=6)

                key_name = format_action_keys(km, action_id)
                label_color = C.BRIGHT if selected else C.WHITE
                key_color = C.BRIGHT if selected else C.DIM

                # Action label (left side) — truncate if needed
                label_text = action_label
                label_surf = row_font.render(label_text, True, label_color)
                if label_surf.get_width() > label_max_w:
                    while (
                        row_font.size(label_text + "...")[0] > label_max_w
                        and len(label_text) > 3
                    ):
                        label_text = label_text[:-1]
                    label_surf = row_font.render(label_text + "...", True, label_color)

                row_text_y = y + (row_h - label_surf.get_height()) // 2 - 3
                self.screen.blit(label_surf, (label_x, row_text_y))

                # Key bindings (right side) — marquee-scroll when selected, truncate otherwise
                if capturing and selected:
                    if (pygame.time.get_ticks() // 500) % 2 == 0:
                        key_surf = row_font.render("_", True, C.GREEN)
                    else:
                        key_surf = row_font.render("-", True, C.GREEN)
                    key_y = y + (row_h - key_surf.get_height()) // 2 - 3
                    self.screen.blit(key_surf, (key_area_x, key_y))
                else:
                    self._blit_marquee_text(
                        key_name,
                        row_font,
                        key_color,
                        key_area_x,
                        y + (row_h - row_font.get_height()) // 2 - 3,
                        key_area_w,
                        key=("keycfg", action_id),
                        active=selected,
                    )

            # Bottom bar
            bar_h = FOOTER_BAR_H
            fy = self.sh - bar_h
            pygame.draw.rect(self.screen, C.BG_FOOTER, (0, fy, self.sw, bar_h))
            pygame.draw.line(self.screen, C.BLUE, (0, fy), (self.sw, fy), 1)
            if capturing:
                hint_text = f"Press a key...  ({format_action_keys(km, 'back')} cancels)"
            else:
                hint_text = (
                    f"{format_action_keys(km, 'select')} set  |  "
                    f"{format_action_keys(km, 'keymap_remove')} remove  |  "
                    f"{format_action_keys(km, 'back')} done  |  "
                    f"{format_action_keys(km, 'keymap_reset')} reset"
                )
            hint = self.font_sm.render(hint_text, True, C.DIM)
            self.screen.blit(
                hint, hint.get_rect(centerx=self.sw // 2, centery=fy + bar_h // 2)
            )

        self.present()

    def enter_key_config(self):
        if self._kids_mode_active:
            return
        self._key_config_return_view = self.view
        self.view = self.KEY_CONFIG
        self.config_cursor = 0

    def exit_key_config(self):
        self.view = getattr(self, "_key_config_return_view", self._view_for_library_layout())
        self.cursor = 0

    def _remove_key_config_binding(self) -> None:
        action_id = KEY_ACTIONS[self.config_cursor][0]
        bindings = keys_for_action(self.keymap, action_id)
        if len(bindings) <= 1:
            return
        remove_binding(self.keymap, action_id, bindings[-1])
        self._rebuild_key_lookup()
        self._persist_keymap()

    def _key_config_prev_page(self) -> None:
        page = self.config_cursor // KEY_CONFIG_ROWS
        if page <= 0:
            return
        self.config_cursor = (page - 1) * KEY_CONFIG_ROWS

    def _key_config_next_page(self) -> None:
        page = self.config_cursor // KEY_CONFIG_ROWS
        max_page = (len(KEY_ACTIONS) - 1) // KEY_CONFIG_ROWS
        if page >= max_page:
            return
        self.config_cursor = min((page + 1) * KEY_CONFIG_ROWS, len(KEY_ACTIONS) - 1)

    def reset_keymap(self):
        self.keymap = load_keymap({})
        self._rebuild_key_lookup()
        self.config["keymap"] = {}
        save_config(self.config)

    def _persist_gamepad_bindings(self) -> None:
        gp_cfg = dict(self.config.get("gamepad") or {})
        serialized = serialize_gamepad_bindings(self._gamepad_bindings)
        if serialized:
            gp_cfg["bindings"] = serialized
        else:
            gp_cfg.pop("bindings", None)
        self.config["gamepad"] = gp_cfg
        save_config(self.config)
        self._gamepad.set_bindings(self._gamepad_bindings)

    def draw_gamepad_config(self, capturing: bool = False) -> None:
        """Gamepad binding screen — capture live controller input."""
        with self._ui_layout(letterbox=True):
            self.screen.fill(C.BG)

            title = self.font_lg.render("GAMEPAD SETUP", True, C.BLUE)
            self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=40))

            km = self.keymap

            page = self._gamepad_config_cursor // GAMEPAD_CONFIG_ROWS
            page_count = max(
                1, (len(GAMEPAD_ACTIONS) + GAMEPAD_CONFIG_ROWS - 1) // GAMEPAD_CONFIG_ROWS
            )
            page_start = page * GAMEPAD_CONFIG_ROWS
            visible = GAMEPAD_ACTIONS[page_start : page_start + GAMEPAD_CONFIG_ROWS]

            page_label = self.font_sm.render(
                f"Page {page + 1} / {page_count}",
                True,
                C.DIM,
            )
            self.screen.blit(page_label, page_label.get_rect(centerx=self.sw // 2, centery=82))

            y_start = 110
            row_h = 44
            label_x = 50
            row_font = self.font_sm
            bindings = self._gamepad_bindings

            # Reserve right 45% of the row for binding text.
            key_area_frac = 0.45
            bar_left = 30
            bar_right = self.sw - 30
            bar_w = bar_right - bar_left
            key_area_w = int(bar_w * key_area_frac)
            key_area_x = bar_right - key_area_w
            label_max_w = max(20, key_area_x - label_x - 16)

            for i, (action_id, action_label) in enumerate(visible):
                global_index = page_start + i
                y = y_start + i * row_h
                selected = global_index == self._gamepad_config_cursor

                bar_rect = pygame.Rect(bar_left, y, bar_w, row_h - 6)
                if selected:
                    pygame.draw.rect(self.screen, C.BG_CARD_SEL, bar_rect, border_radius=6)
                    pygame.draw.rect(self.screen, C.CYAN, bar_rect.inflate(2, 2), 2, border_radius=7)
                else:
                    pygame.draw.rect(self.screen, C.BG_CARD, bar_rect, border_radius=6)

                binding_text = format_action_bindings(bindings, action_id)
                label_color = C.BRIGHT if selected else C.WHITE
                key_color = C.BRIGHT if selected else C.DIM

                # Action label (left side) — truncate if needed
                label_text = action_label
                label_surf = row_font.render(label_text, True, label_color)
                if label_surf.get_width() > label_max_w:
                    while (
                        row_font.size(label_text + "...")[0] > label_max_w
                        and len(label_text) > 3
                    ):
                        label_text = label_text[:-1]
                    label_surf = row_font.render(label_text + "...", True, label_color)

                row_text_y = y + (row_h - label_surf.get_height()) // 2 - 3
                self.screen.blit(label_surf, (label_x, row_text_y))

                # Bindings (right side) — marquee-scroll when selected, truncate otherwise
                if capturing and selected:
                    if (pygame.time.get_ticks() // 500) % 2 == 0:
                        key_surf = row_font.render("_", True, C.GREEN)
                    else:
                        key_surf = row_font.render("-", True, C.GREEN)
                    key_y = y + (row_h - key_surf.get_height()) // 2 - 3
                    self.screen.blit(key_surf, (key_area_x, key_y))
                else:
                    self._blit_marquee_text(
                        binding_text,
                        row_font,
                        key_color,
                        key_area_x,
                        y + (row_h - row_font.get_height()) // 2 - 3,
                        key_area_w,
                        key=("gpadcfg", action_id),
                        active=selected,
                    )

            # Bottom bar
            bar_h = FOOTER_BAR_H
            fy = self.sh - bar_h
            pygame.draw.rect(self.screen, C.BG_FOOTER, (0, fy, self.sw, bar_h))
            pygame.draw.line(self.screen, C.BLUE, (0, fy), (self.sw, fy), 1)
            if self._gamepad_count <= 0:
                hint_text = "No gamepad detected — connect a USB controller"
            elif capturing:
                hint_text = (
                    "Press a button, D-pad, or move a stick...  "
                    f"({format_action_keys(km, 'back')} cancels)"
                )
            else:
                hint_text = (
                    f"{format_action_keys(km, 'select')} set  |  "
                    f"{format_action_keys(km, 'keymap_remove')} remove  |  "
                    f"{format_action_keys(km, 'back')} done  |  "
                    f"{format_action_keys(km, 'keymap_reset')} reset"
                )
            hint = self.font_sm.render(hint_text, True, C.DIM)
            self.screen.blit(
                hint, hint.get_rect(centerx=self.sw // 2, centery=fy + bar_h // 2)
            )

        self.present()

    def enter_gamepad_config(self) -> None:
        if self._kids_mode_active:
            return
        self._gamepad_config_return_view = self.view
        self._gamepad_config_cursor = 0
        self.view = self.GAMEPAD_CONFIG

    def exit_gamepad_config(self) -> None:
        self.view = getattr(
            self, "_gamepad_config_return_view", self._view_for_library_layout()
        )
        self.cursor = 0

    def _remove_gamepad_config_binding(self) -> None:
        action_id = GAMEPAD_ACTIONS[self._gamepad_config_cursor][0]
        tokens = bindings_for_action(self._gamepad_bindings, action_id)
        if len(tokens) <= 1:
            return
        remove_gamepad_binding(self._gamepad_bindings, action_id, tokens[-1])
        self._persist_gamepad_bindings()

    def _gamepad_config_prev_page(self) -> None:
        page = self._gamepad_config_cursor // GAMEPAD_CONFIG_ROWS
        if page <= 0:
            return
        self._gamepad_config_cursor = (page - 1) * GAMEPAD_CONFIG_ROWS

    def _gamepad_config_next_page(self) -> None:
        page = self._gamepad_config_cursor // GAMEPAD_CONFIG_ROWS
        max_page = (len(GAMEPAD_ACTIONS) - 1) // GAMEPAD_CONFIG_ROWS
        if page >= max_page:
            return
        self._gamepad_config_cursor = min(
            (page + 1) * GAMEPAD_CONFIG_ROWS, len(GAMEPAD_ACTIONS) - 1
        )

    def reset_gamepad_bindings(self) -> None:
        self._gamepad_bindings = load_gamepad_bindings({})
        gp_cfg = dict(self.config.get("gamepad") or {})
        gp_cfg.pop("bindings", None)
        self.config["gamepad"] = gp_cfg
        save_config(self.config)
        self._gamepad.set_bindings(self._gamepad_bindings)

    def _start_gamepad_capture(self) -> None:
        if self._gamepad_count <= 0:
            return
        self._gamepad_capture_axis_ready = True
        self.view = self.GAMEPAD_CAPTURE

    def _finish_gamepad_capture(self, token: str) -> None:
        action_id = GAMEPAD_ACTIONS[self._gamepad_config_cursor][0]
        add_gamepad_binding(self._gamepad_bindings, action_id, token)
        self._persist_gamepad_bindings()
        self.view = self.GAMEPAD_CONFIG

    def _handle_gamepad_capture_event(self, event: pygame.event.Event) -> bool:
        if self.view != self.GAMEPAD_CAPTURE:
            return False
        if event.type == pygame.JOYAXISMOTION:
            if abs(event.value) < 0.55:
                self._gamepad_capture_axis_ready = True
                return True
            if not self._gamepad_capture_axis_ready:
                return True
            self._gamepad_capture_axis_ready = False
        token = capture_binding_from_event(event)
        if token:
            self._finish_gamepad_capture(token)
        return True

    def reset_watch_status(self):
        """Clear watched / next-up progress for the current menu context."""
        if self.view == self.EPISODE_SELECT:
            if not self.cur_show or self.cur_season is None:
                return
            episodes = self.current_items()
            if not episodes or self.cursor >= len(episodes):
                return
            ep_num = episodes[self.cursor]["number"]
            changed = reset_episode_progress(
                self.state, self.cur_show, self.cur_season, ep_num
            )
            label = f"E-{ep_num:02d} reset"
        elif self.view == self.SEASON_SELECT:
            if not self.cur_show:
                return
            seasons = self.seasons_for_show(self.cur_show)
            if not seasons or self.cursor >= len(seasons):
                return
            season = seasons[self.cursor]
            changed = clear_resume_ep(self.state, self.cur_show, season)
            label = f"{self.season_display_name(self.cur_show, season)} reset"
        elif self.view == self.SHOW_LIST:
            if not self.show_names or self.cursor >= len(self.show_names):
                return
            show = self.show_names[self.cursor]
            changed = clear_resume_ep(self.state, show, season=None)
            label = "Show reset"
        elif self.view == self.MOVIE_LIST:
            if not self.movie_names or self.cursor >= len(self.movie_names):
                return
            movie_key = self.movie_names[self.cursor]
            changed = reset_episode_progress(self.state, movie_key, 1, 1)
            label = "Movie reset"
        else:
            return

        if changed:
            self.channel_error = label
            if self.view == self.EPISODE_SELECT:
                episodes = self.current_items()
                watched_eps = get_watched_episodes(
                    self.state, self.cur_show, self.cur_season
                )
                pos_ep, _ = get_episode_position(
                    self.state, self.cur_show, self.cur_season
                )
                self.cursor = self._next_up_index(episodes, watched_eps, pos_ep=pos_ep)
        else:
            self.channel_error = "No progress"
        self.channel_error_time = pygame.time.get_ticks()

    # ─── Navigation ────────────────────────────────────────────────────────

    def move_cursor(self, direction):
        if self.view == self.SHOW_LIST:
            self._clear_show_list_test_pattern()
        total = self.total_items()
        if not total:
            return
        if self.view in (
            self.SEASON_SELECT,
            self.EPISODE_SELECT,
            self.SHOW_LIST,
            self.MOVIE_LIST,
            self.LIBRARY_SELECT,
        ):
            self._move_cursor_stack(direction, total)
            return
        new_cursor = max(0, min(total - 1, self.cursor + direction))
        if new_cursor != self.cursor:
            self.cursor = new_cursor
            self._marquee_key = None

    def _channel_tune(self, apply) -> None:
        """Apply navigation first, then snow — destination sits under the burst."""
        self._in_channel_tune = True
        self._deferred_splash = None
        try:
            apply()
            self._animate_channel_snow_burst()
            deferred = self._deferred_splash
            self._deferred_splash = None
            if deferred is not None and self.view == self.PLAYING:
                self.draw_now_playing(*deferred)
        finally:
            self._in_channel_tune = False

    def select(self):
        if self._show_list_test_pattern:
            return
        items = self.current_items()
        if not items or self.cursor >= len(items):
            return

        if self.view == self.SHOW_LIST:
            names = self._browse_show_names()
            if self.cursor >= len(names):
                return
            show_name = names[self.cursor]
            if self._kids_mode_active:
                self._kids_play_show(show_name)
                return
            self.cur_show = show_name
            show = self.shows[self.cur_show]
            if not show['has_seasons']:
                seasons = sorted(show['seasons'].keys())
                if seasons:
                    self.cur_season = seasons[0]
                    self.view = self.EPISODE_SELECT
                else:
                    return
            else:
                self.view = self.SEASON_SELECT
            self.cursor = 0

            if self.view == self.EPISODE_SELECT:
                watched_eps = get_watched_episodes(
                    self.state, self.cur_show, self.cur_season
                )
                pos_ep, _ = get_episode_position(
                    self.state, self.cur_show, self.cur_season
                )
                eps = show['seasons'][self.cur_season]['episodes']
                self.cursor = self._next_up_index(eps, watched_eps, pos_ep=pos_ep)

        elif self.view == self.SEASON_SELECT:
            seasons = self.seasons_for_show(self.cur_show)
            if self.cursor < len(seasons):
                self.cur_season = seasons[self.cursor]
                self.view = self.EPISODE_SELECT
                self.cursor = 0
                watched_eps = get_watched_episodes(
                    self.state, self.cur_show, self.cur_season
                )
                pos_ep, _ = get_episode_position(
                    self.state, self.cur_show, self.cur_season
                )
                eps = self.shows[self.cur_show]['seasons'][self.cur_season]['episodes']
                self.cursor = self._next_up_index(eps, watched_eps, pos_ep=pos_ep)

        elif self.view == self.EPISODE_SELECT:
            self.play_from_cursor()

        elif self.view == self.LIBRARY_SELECT:
            if self.cursor == 0:
                self.view = self.SHOW_LIST
            else:
                self.view = self.MOVIE_LIST
            self.cursor = 0

        elif self.view == self.MOVIE_LIST:
            self.play_movie_from_cursor()

    def go_back(self):
        if self.view == self.EPISODE_SELECT:
            show = self.shows.get(self.cur_show, {})
            if show.get('has_seasons', False):
                self.view = self.SEASON_SELECT
                seasons = self.seasons_for_show(self.cur_show)
                if self.cur_season in seasons:
                    self.cursor = seasons.index(self.cur_season)
                else:
                    self.cursor = 0
            else:
                self.view = self.SHOW_LIST
                if self.cur_show in self.show_names:
                    self.cursor = self.show_names.index(self.cur_show)
                else:
                    self.cursor = 0

        elif self.view == self.SEASON_SELECT:
            self.view = self.SHOW_LIST
            if self.cur_show in self.show_names:
                self.cursor = self.show_names.index(self.cur_show)
            else:
                self.cursor = 0

        elif self.view == self.SHOW_LIST and self._is_split_library():
            self.view = self.LIBRARY_SELECT
            self.cursor = 0

        elif self.view == self.MOVIE_LIST and self._is_split_library():
            self.view = self.LIBRARY_SELECT
            self.cursor = 1
        # On top-level lists without split layout, left arrow does nothing — use Escape to quit

    def jump_to_channel(self, channel_num):
        if self.view == self.SHOW_LIST:
            names = self._browse_show_names()
            show_name = show_at_channel(self._channel_show, channel_num)
            if show_name and show_name in names:
                self._clear_show_list_test_pattern()
                idx = names.index(show_name)

                def apply():
                    self.cursor = idx
                    self.select()

                self._channel_tune(apply)
                return True
            if len(names) == 0:
                self.channel_error = "No Shows"
            elif show_name is None:
                self.channel_error = f"Ch {channel_num} Not Found"
            else:
                self.channel_error = "Channel Not Found"
            self.channel_error_time = pygame.time.get_ticks()
            return False

        elif self.view == self.SEASON_SELECT:
            seasons = self.seasons_for_show(self.cur_show)
            if 1 <= channel_num <= len(seasons):

                def apply():
                    self.cursor = channel_num - 1
                    self.select()

                self._channel_tune(apply)
                return True
            else:
                self.channel_error = f"Season {channel_num} Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        elif self.view == self.EPISODE_SELECT:
            episodes = self.current_items()
            if 1 <= channel_num <= len(episodes):

                def apply():
                    self.cursor = channel_num - 1

                self._channel_tune(apply)
                self.play_from_cursor()
                return True
            else:
                self.channel_error = f"Episode {channel_num} Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        elif self.view == self.MOVIE_LIST:
            names = self._browse_movie_names()
            movie_key = show_at_channel(self._channel_movie, channel_num)
            if movie_key and movie_key in names:
                idx = names.index(movie_key)

                def apply():
                    self.cursor = idx
                    self.play_movie_from_cursor()

                self._channel_tune(apply)
                return True
            if len(names) == 0:
                self.channel_error = "No Movies"
            elif movie_key is None:
                self.channel_error = f"Ch {channel_num} Not Found"
            else:
                self.channel_error = "Channel Not Found"
            self.channel_error_time = pygame.time.get_ticks()
            return False

        elif self.view == self.LIBRARY_SELECT:
            items = self.current_items()
            if 1 <= channel_num <= len(items):

                def apply():
                    self.cursor = channel_num - 1
                    self.select()

                self._channel_tune(apply)
                return True
            self.channel_error = f"Ch {channel_num} Not Found"
            self.channel_error_time = pygame.time.get_ticks()
            return False

        return False

    def _create_player(self):
        """Build an EmbeddedPlayer using the best available backend."""
        player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
        ffmpeg_path = detect_ffmpeg()
        ffplay_path = detect_ffplay()
        omx_cmd = detect_omxplayer() if is_pi() else None

        if ffmpeg_path and np_frombuffer is not None:
            player.ffmpeg_path = ffmpeg_path
            player.ffplay_path = ffplay_path
            self.embedded_player = True
        elif omx_cmd:
            if not self._omx_overlay:
                self._enable_omx_overlay()
            player.use_omx = True
            player.omx_cmd = omx_cmd
            self.embedded_player = True
        else:
            return None
        player.hw_decode_mode = self._hw_decode_mode
        return player

    def _retry_playback(self, resume_secs=None):
        """Restart the current episode after a stall."""
        if not self.playing_episodes or self.playing_episode is None:
            return False
        if self.player:
            self.player.stop()
            self.player = None
        self._playback_stalled = False
        return self._start_current_episode(
            resume_secs=resume_secs if resume_secs is not None else self.time_pos_if_playing(),
            show_splash=False,
        )

    def time_pos_if_playing(self):
        if self.player:
            self.player.update_time()
            return self.player.time_pos
        return 0.0

    def _handle_playback_stall(self):
        """Detect freeze; auto-retry once, then prompt the user."""
        if not self.player or self._playback_stalled:
            return

        pos = self.time_pos_if_playing()
        path = self.player.filepath
        LOG.warning("playback stall detected path=%s pos=%.1fs", path, pos)

        if not self._stall_auto_retry_done and path:
            self._stall_auto_retry_done = True
            LOG.info("auto-retry playback path=%s pos=%.1fs", path, pos)
            if self._retry_playback(resume_secs=pos):
                return
            LOG.error("auto-retry failed path=%s", path)

        self._playback_stalled = True
        self._stall_resume_pos = pos
        if self.player:
            self.player.stalled = True
            self.player.stop()
            self.player = None

    def draw_stall_overlay(self):
        """Prompt after watchdog gives up or auto-retry fails."""
        rect, scale = self._playback_overlay_layout()
        overlay = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (rect.x, rect.y))

        title = self._scale_overlay_surface(
            self.font_lg.render("PLAYBACK STALLED", True, C.GREEN), scale
        )
        hint = self._scale_overlay_surface(
            self.font_md.render(
                f"{format_action_keys(self.keymap, 'select')} retry  |  "
                f"{format_action_keys(self.keymap, 'back')} back",
                True,
                C.DIM,
            ),
            scale,
        )
        cx = rect.x + rect.w // 2
        cy = rect.y + rect.h // 2
        self.screen.blit(title, title.get_rect(center=(cx, cy - 24)))
        self.screen.blit(hint, hint.get_rect(center=(cx, cy + 20)))

    def _start_current_episode(self, *, resume_secs=None, show_splash=True):
        """Start ``playing_episodes[playing_index]``. Returns True on success."""
        self._remember_playback_browse_state()

        episode = self.playing_episodes[self.playing_index]
        self.playing_episode = episode
        source_path = episode["path"]
        self._playing_source_path = source_path

        splash_args = (
            self._splash_show_label(self.playing_show),
            None if self._playing_is_movie else self.playing_season,
            episode,
            self._splash_channel(),
            resume_secs,
        )

        if self._playback_cache.should_cache_before_play(source_path):
            wait_result = self._wait_for_playback_cache(source_path, splash_args)
            if wait_result == "cancelled":
                self.view = self._playback_return_view()
                if self._playing_is_movie:
                    self._playing_is_movie = False
                    self.cur_movie = None
                return False
        else:
            wait_result = None

        self.view = self.PLAYING

        self._playback_cache_suppressed = False
        self._playback_cache_switched = False
        self._playback_allow_hot_swap = (
            not self._playback_cache.cache_before_playing or wait_result == "stream"
        )

        if wait_result == "stream":
            play_path = source_path
        else:
            play_path = self._playback_cache.resolve_playback_path(source_path)

        if wait_result is None and not self._playback_cache.cache_before_playing:
            self._playback_cache.schedule_cache(source_path)

        if (
            wait_result is None
            and show_splash
            and self._now_playing_splash
            and self._now_playing_splash_ms > 0
        ):
            if self._in_channel_tune:
                self._deferred_splash = splash_args
            else:
                self.draw_now_playing(*splash_args)

        self._enter_playback_display()
        self.player = self._create_player()
        if self.player is None:
            self._exit_playback_display()
            self.channel_error = "NO PLAYER"
            self.channel_error_time = pygame.time.get_ticks()
            self.view = self._playback_return_view()
            if self._playing_is_movie:
                self._playing_is_movie = False
                self.cur_movie = None
            return False

        if not self.player.start(play_path, resume_pos=resume_secs):
            self.player = None
            self._exit_playback_display()
            self.channel_error = "PLAY FAILED"
            self.channel_error_time = pygame.time.get_ticks()
            self.view = self._playback_return_view()
            if self._playing_is_movie:
                self._playing_is_movie = False
                self.cur_movie = None
            return False

        pygame.event.clear()
        self._play_input_grace_until = pygame.time.get_ticks() + PLAY_INPUT_GRACE_MS
        self.progress_overlay_timer = 0
        self.volume_overlay_timer = 0
        self._playback_stalled = False
        self._stall_auto_retry_done = False
        return True

    def _maybe_switch_to_playback_cache(self) -> None:
        """Seamlessly restart from a local cache copy when background caching finishes."""
        if (
            not self._playback_allow_hot_swap
            or self._playback_cache_suppressed
            or self._playback_cache_switched
        ):
            return
        if not self.player or not self._playing_source_path or self._playback_stalled:
            return
        if self.player.paused:
            return
        if not self._playback_cache.cache_ready_for_hot_swap(
            self._playing_source_path, self.player.filepath
        ):
            return
        pos = self.time_pos_if_playing()
        cached = self._playback_cache.get_cached_path(self._playing_source_path)
        if not cached:
            return
        LOG.info(
            "switching to local playback cache path=%s pos=%.1fs",
            self._playing_source_path,
            pos,
        )
        self.player.stop()
        self.player = self._create_player()
        if self.player is None:
            self._playback_stalled = True
            self._stall_resume_pos = pos
            return
        if not self.player.start(cached, resume_pos=pos):
            self.player = None
            self._playback_stalled = True
            self._stall_resume_pos = pos
            return
        self._playback_cache_switched = True

    def _resolve_autoplay_target(self):
        """Return (episodes, index, season) for autoplay, or None."""
        if self._autoplay_mode == "off":
            return None

        next_idx = self.playing_index + 1
        if next_idx < len(self.playing_episodes):
            return self.playing_episodes, next_idx, self.playing_season

        if self._autoplay_mode != "next_episode":
            return None

        if not self.playing_show or self.playing_show not in self.shows:
            return None

        seasons = self.seasons_for_show(self.playing_show)
        try:
            si = seasons.index(self.playing_season)
        except ValueError:
            return None
        if si + 1 >= len(seasons):
            return None
        next_season = seasons[si + 1]
        eps = self.shows[self.playing_show]["seasons"].get(next_season, {}).get(
            "episodes", []
        )
        if not eps:
            return None
        return eps, 0, next_season

    def _draw_up_next_splash(self, episode, season, channel, seconds_left):
        self.screen.fill(C.BLACK)
        self._draw_episode_splash(
            self.playing_show,
            season,
            episode,
            channel,
            header="UP NEXT",
            footer=f"Starting in {seconds_left}s  -  {format_action_keys(self.keymap, 'back')} to cancel",
        )

    def _run_up_next_countdown(self, episode, season, channel):
        """Countdown before autoplay. Returns True to continue, False if cancelled."""
        if self._playback_cache.prefetch_next:
            self._playback_cache.schedule_cache(episode["path"])

        total = self._autoplay_countdown
        if total <= 0:
            return True

        start = pygame.time.get_ticks()
        duration_ms = total * 1000

        while self.running:
            for event in pygame.event.get():
                if self._handle_window_event(event):
                    continue
                if event.type == pygame.QUIT:
                    self._handle_quit_event("up-next-countdown")
                    if not self.running:
                        return False
                if event.type == pygame.KEYDOWN:
                    if self._action_for_key(event.key) == "back":
                        return False
                action = self._gamepad.event_to_action(event)
                if action == "back":
                    return False

            elapsed = pygame.time.get_ticks() - start
            if elapsed >= duration_ms:
                return True

            remaining = max(1, (duration_ms - elapsed + 999) // 1000)
            self._draw_up_next_splash(episode, season, channel, remaining)
            self.present()
            self.clock.tick(30)

        return False

    def _handle_episode_finished(self):
        """Natural end: mark watched, optionally autoplay the next episode."""
        if self._handling_episode_finish:
            return
        self._handling_episode_finish = True
        try:
            self._mark_completed()

            target = self._resolve_autoplay_target()
            if target is None:
                self.stop_playback(completed=True)
                return

            episodes, index, season = target
            episode = episodes[index]

            if not self._run_up_next_countdown(episode, season, index + 1):
                self.stop_playback(completed=True)
                return

            if self.player:
                self.player.stop()
                self.player = None

            self.playing_episodes = episodes
            self.playing_index = index
            self.playing_season = season
            self.cur_season = season

            pos_ep, pos_secs = get_episode_position(
                self.state, self.playing_show, season
            )
            resume_secs = None
            if pos_ep is not None and episode["number"] == pos_ep:
                resume_secs = pos_secs

            if not self._start_current_episode(resume_secs=resume_secs, show_splash=False):
                self.stop_playback(completed=True)
        except Exception:
            LOG.exception("episode finish handling failed")
            try:
                self.stop_playback(completed=True)
            except Exception:
                LOG.exception("stop after episode finish failure")
        finally:
            self._handling_episode_finish = False
            # Decoder teardown (ffmpeg/ffplay exit) can post a spurious QUIT that
            # would otherwise be processed on the next browse frame and close the app.
            pygame.event.clear()
            self._arm_quit_grace()

    def _process_playback_action(self, action):
        """Handle a logical action during PLAYING. Returns False if playback stopped."""
        km = self.keymap
        if action == "back":
            self.stop_playback()
            return False

        if pygame.time.get_ticks() < self._play_input_grace_until:
            if action in ("left", "right", "select"):
                return True

        if action == "up":
            if self.player:
                self.player.adjust_volume(10)
                self.volume_overlay_timer = pygame.time.get_ticks()
        elif action == "down":
            if self.player:
                self.player.adjust_volume(-10)
                self.volume_overlay_timer = pygame.time.get_ticks()
        elif action == "right":
            if self.player:
                self.player.seek(PROGRESS_SEEK_S)
                self.progress_overlay_timer = pygame.time.get_ticks()
        elif action == "left":
            if self.player:
                self.player.seek(-PROGRESS_SEEK_S)
                self.progress_overlay_timer = pygame.time.get_ticks()
        elif action == "select":
            if self.player:
                self.player.pause()
                if self.player.paused:
                    self.progress_overlay_timer = pygame.time.get_ticks()
        return True

    def _process_browse_action(self, action):
        """Handle menu navigation from keyboard or gamepad."""
        km = self.keymap
        if action == "up":
            self.move_cursor(-1)
        elif action == "down":
            self.move_cursor(1)
        elif action in ("select", "right"):
            self.select()
        elif action == "left":
            self.go_back()
        elif action == "back":
            if self._show_list_test_pattern:
                self._clear_show_list_test_pattern()
                return
            if self._kids_mode_active:
                if self.view == self.SHOW_LIST and self._is_split_library():
                    self.view = self.LIBRARY_SELECT
                    self.cursor = 0
                elif self.view == self.MOVIE_LIST and self._is_split_library():
                    self.view = self.LIBRARY_SELECT
                    self.cursor = 1
                return
            if self.view == self.SHOW_LIST:
                self._enter_confirm_exit()
            elif self.view in (self.MOVIE_LIST, self.LIBRARY_SELECT):
                self._enter_confirm_exit()
            else:
                self.go_back()

    def play_movie_from_cursor(self):
        if not self.player_cmd and not self.player:
            self.channel_error = "NO PLAYER"
            self.channel_error_time = pygame.time.get_ticks()
            return
        movies = self._browse_movie_names()
        if not movies or self.cursor >= len(movies):
            return

        movie_key = movies[self.cursor]
        self.cur_movie = movie_key
        self._playing_is_movie = True
        self.playing_show = movie_key
        self.playing_season = 1
        episode = self._movie_episode_entry(movie_key)
        self.playing_episodes = [episode]
        self.playing_index = 0

        pos_ep, pos_secs = get_episode_position(self.state, movie_key, 1)
        resume_secs = pos_secs if pos_ep == 1 else None

        if not self._start_current_episode(resume_secs=resume_secs, show_splash=True):
            self._playing_is_movie = False
            self.cur_movie = None

    def play_from_cursor(self):
        if not self.player_cmd and not self.player:
            self.channel_error = "NO PLAYER"
            self.channel_error_time = pygame.time.get_ticks()
            return
        show = self.shows.get(self.cur_show, {})
        season_data = show.get('seasons', {}).get(self.cur_season, {})
        episodes = season_data.get('episodes', [])
        if not episodes:
            return

        start = min(self.cursor, len(episodes) - 1)

        self._playing_is_movie = False
        self.cur_movie = None
        self.playing_show = self.cur_show
        self.playing_season = self.cur_season
        self.playing_episodes = episodes
        self.playing_index = start

        pos_ep, pos_secs = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        resume_secs = None
        if pos_ep is not None and episodes[start]["number"] == pos_ep:
            resume_secs = pos_secs

        if not self._start_current_episode(resume_secs=resume_secs, show_splash=True):
            return

    def _next_up_index(self, episodes, watched_eps, pos_ep=None):
        """Index of the in-progress episode, else first unwatched, else last."""
        if pos_ep is not None:
            for i, e in enumerate(episodes):
                if e["number"] == pos_ep:
                    return i
        watched = watched_eps if isinstance(watched_eps, set) else set(watched_eps)
        for i, e in enumerate(episodes):
            if e['number'] not in watched:
                return i
        return max(0, len(episodes) - 1)

    def _mark_completed(self):
        """Record that the currently-playing episode finished."""
        ep = self.playing_episode
        if ep is None:
            return
        mark_episode_watched(
            self.state, self.playing_show, self.playing_season, ep['number']
        )

    def _sync_playback_navigation_state(self) -> None:
        """Keep browse menus aligned with what was just playing."""
        if self._playing_is_movie:
            return
        if self.playing_show:
            self.cur_show = self.playing_show
        if self.playing_season is not None:
            self.cur_season = self.playing_season

    def stop_playback(self, *, completed=False):
        """Stop playback and return to episode or movie list.

        On early stop, bookmark the in-episode position so Play resumes there.
        """
        ep = self.playing_episode
        return_movie = self._playing_is_movie
        movie_key = self.cur_movie if return_movie else None

        if self.player:
            if not completed and ep is not None:
                self.player.update_time()
                set_episode_position(
                    self.state,
                    self.playing_show,
                    self.playing_season,
                    ep["number"],
                    self.player.time_pos,
                    duration=self.player.duration,
                )
            self.player.stop()
            self.player = None

        self._playing_source_path = None
        self._playback_cache_suppressed = False
        self._sync_playback_navigation_state()

        if self._kids_mode_active:
            self._restore_kids_browse_after_playback(
                return_movie=return_movie,
                movie_key=movie_key,
            )
            self._playing_is_movie = False
            self.cur_movie = None
            self._exit_playback_display()
            # Decoder teardown can post a spurious QUIT on the next browse frame.
            pygame.event.clear()
            self._arm_quit_grace()
            return

        if return_movie:
            self.view = self.MOVIE_LIST
            if movie_key and movie_key in self.movie_names:
                self.cursor = self.movie_names.index(movie_key)
            self._playing_is_movie = False
            self.cur_movie = None
            self._exit_playback_display()
            pygame.event.clear()
            self._arm_quit_grace()
            return

        # Land on the in-progress episode if any, otherwise next-up.
        watched_eps = get_watched_episodes(self.state, self.cur_show, self.cur_season)
        pos_ep, _pos = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        episodes = (self.shows.get(self.cur_show, {})
                    .get('seasons', {}).get(self.cur_season, {})
                    .get('episodes', []))
        if episodes:
            self.cursor = self._next_up_index(episodes, watched_eps, pos_ep=pos_ep)

        self.view = self.EPISODE_SELECT
        self._exit_playback_display()
        pygame.event.clear()
        self._arm_quit_grace()

    # ─── Main loop ─────────────────────────────────────────────────────────

    def _touch_activity(self, device: str | None = None):
        """Reset idle timer; leave screensaver on input."""
        self._last_activity_ms = pygame.time.get_ticks()
        self._screensaver_active = False
        if device in ("keyboard", "gamepad"):
            self._last_input_device = device

    def _note_keyboard_input(self) -> None:
        self._touch_activity(device="keyboard")

    def _note_gamepad_input(self) -> None:
        self._touch_activity(device="gamepad")

    def _help_input_device(self) -> str:
        """Device labels to show in help (gamepad only when a controller is present)."""
        if self._last_input_device == "gamepad" and self._gamepad_count > 0:
            return "gamepad"
        return "keyboard"

    def _help_binding(self, action: str, *, device: str | None = None) -> str:
        """Format one action binding for the active help device."""
        device = device or self._help_input_device()
        if device == "gamepad":
            gamepad_actions = {action_id for action_id, _ in GAMEPAD_ACTIONS}
            if action in gamepad_actions:
                label = format_action_bindings(self._gamepad_bindings, action)
                return label.replace(", ", " / ")
            return "keyboard only"
        return format_action_keys(self.keymap, action)

    def _screensaver_idle_views(self):
        return self.view not in (
            self.PLAYING,
            self.KEY_CONFIG,
            self.KEY_CAPTURE,
            self.GAMEPAD_CONFIG,
            self.GAMEPAD_CAPTURE,
            self.CONFIRM_EXIT,
            self.SAFE_ZONE_EDIT,
        )

    def _enter_screensaver(self):
        if not self._screensaver_enabled or not VHS_LOGO_PATH.is_file():
            return
        w, h = self._ui_surface_size()
        if (
            self._screensaver is None
            or self._screensaver.screen_w != w
            or self._screensaver.screen_h != h
        ):
            try:
                self._screensaver = VHSScreensaver(w, h)
            except FileNotFoundError:
                self._screensaver_enabled = False
                return
        self._screensaver.randomize_color()
        self._screensaver_active = True

    def _tick_screensaver(self):
        dt = max(self.clock.get_time(), 1) / 1000.0
        if self._screensaver.update(dt):
            self._screensaver.randomize_color()
        if self._safe_zone_for_ui():
            with self._ui_layout(letterbox=True):
                self._screensaver.draw(self.screen)
        else:
            self._screensaver.draw(self.screen)

    def _apply_runtime_config(self) -> None:
        """Apply reloadable settings from ``self.config`` without restarting."""
        ui_cfg = self.config.get("ui") or {}
        snow = (
            bool(self._channel_snow_override)
            if self._channel_snow_override is not None
            else bool(ui_cfg.get("channel_snow", False))
        )
        shutdown = (
            bool(self._shutdown_collapse_override)
            if self._shutdown_collapse_override is not None
            else bool(ui_cfg.get("shutdown_collapse", False))
        )
        self._channel_fx.configure(
            snow=snow,
            shutdown=shutdown,
            audio=ui_cfg.get("channel_snow_audio", snow),
        )

        ss_cfg = self.config.get("screensaver") or {}
        if self._screensaver_override is None:
            self._screensaver_enabled = bool(ss_cfg.get("enabled", False))
        if self._screensaver_timeout_override is None:
            try:
                timeout_s = max(10, int(ss_cfg.get("timeout_seconds", 300)))
            except (TypeError, ValueError):
                timeout_s = 300
            self._screensaver_timeout_ms = timeout_s * 1000

        pb_cfg = self.config.get("playback") or {}
        self._autoplay_mode = pb_cfg.get("autoplay", "off")
        self._autoplay_countdown = pb_cfg.get("autoplay_countdown_seconds", 5)
        self._now_playing_splash = bool(pb_cfg.get("now_playing_splash", True))
        try:
            splash_seconds = float(pb_cfg.get("now_playing_splash_seconds", 1.5))
        except (TypeError, ValueError):
            splash_seconds = 1.5
        splash_seconds = max(0.0, min(30.0, splash_seconds))
        self._now_playing_splash_ms = int(splash_seconds * 1000)
        self._hw_decode_mode = pb_cfg.get("hw_decode", "auto")
        self._playback_cache = PlaybackCache(self.config)
        self._load_kids_mode_config()
        ui_cfg = self.config.get("ui") or {}
        self._footer_hints_enabled = bool(ui_cfg.get("footer_hints", True))

        gp_cfg = self.config.get("gamepad") or {}
        self._gamepad.enabled = bool(gp_cfg.get("enabled", True))
        self._gamepad_bindings = load_gamepad_bindings(self.config)
        self._gamepad.set_bindings(self._gamepad_bindings)

        lib_cfg = self.config.get("library") or {}
        self._rescan_interval_ms = int(lib_cfg.get("rescan_interval_seconds", 0)) * 1000
        self._rescan_long_press_ms = int(lib_cfg.get("rescan_long_press_ms", 800))

        paths = effective_media_paths(self.config)
        if paths:
            self.media_paths = paths

        self.keymap = load_keymap(self.config)
        self._key_lookup: dict[int, str] = {}
        self._rebuild_key_lookup()
        self._apply_channel_lineup()

        if self._analog_artifacts_override is None:
            self._analog_artifacts.configure(
                enabled=bool(ui_cfg.get("analog_artifacts", False)),
                rate_per_minute=float(ui_cfg.get("analog_artifact_rate", 12)),
            )
        else:
            self._analog_artifacts.configure(enabled=bool(self._analog_artifacts_override))
        if self._analog_artifact_rate_override is not None:
            self._analog_artifacts.configure(
                rate_per_minute=float(self._analog_artifact_rate_override)
            )

        self._apply_safe_zone_from_config()

    def _reload_config_from_disk(self) -> None:
        self.config = load_config()
        self._apply_runtime_config()

    # ─── Web admin (AdminContext) ────────────────────────────────────────

    def admin_status(self) -> dict:
        view_names = {
            self.LIBRARY_SELECT: "library_select",
            self.SHOW_LIST: "show_list",
            self.MOVIE_LIST: "movie_list",
            self.SEASON_SELECT: "season_select",
            self.EPISODE_SELECT: "episode_select",
            self.PLAYING: "playing",
        }
        return {
            "shows": len(self.show_names),
            "movies": len(self.movie_names),
            "layout": self.library_layout,
            "kids_mode": self._kids_mode_active,
            "view": view_names.get(self.view, "other"),
            "playing": self.view == self.PLAYING,
            "current_show": self.cur_show,
            "current_movie": self.cur_movie,
        }

    def admin_shows(self) -> list[str]:
        return list(self.show_names)

    def admin_channels(self) -> dict:
        ch = self.config.get("channels") or {}
        return {
            "order": list(ch.get("order") or []),
            "numbers": dict(ch.get("numbers") or {}),
            "shows": self.admin_shows(),
        }

    def admin_save_channels(self, order: list[str], numbers: dict[str, int]) -> None:
        self.config.setdefault("channels", {})
        self.config["channels"]["order"] = order
        self.config["channels"]["numbers"] = numbers
        save_config(self.config)
        self._apply_channel_lineup()
        LOG.info("admin saved channel lineup (%d shows)", len(order))

    def admin_request_rescan(self) -> tuple[bool, str]:
        if self.view == self.PLAYING:
            return False, "playback active — stop video first or use the TV"
        self._pending_admin_rescan = True
        LOG.info("admin queued library rescan")
        return True, "Rescan queued"

    def admin_watch_summary(self) -> dict:
        return watch_summary(self.state)

    def admin_keymap(self) -> dict:
        return {
            "keyboard": keymap_for_display(self.keymap),
            "gamepad": [
                {
                    "action": action_id,
                    "label": label,
                    "binding": format_action_bindings(self._gamepad_bindings, action_id),
                }
                for action_id, label in GAMEPAD_ACTIONS
            ],
        }

    def admin_library(self) -> dict:
        summary = library_summary(self.shows, self.movies)
        return {
            **summary,
            "layout": self.library_layout,
            "tree": library_tree_from_discovery(self.shows, self.movies),
            "media_paths": list(self.media_paths),
        }

    def admin_config_get(self) -> dict:
        return {"path": config_file(), "config": self.config}

    def admin_config_save(self, raw: dict) -> tuple[bool, str]:
        try:
            if not isinstance(raw, dict):
                return False, "config must be a JSON object"
            parsed = parse_config(raw)
            save_config(parsed)
            self._reload_config_from_disk()
            return True, f"Saved to {config_file()}"
        except (TypeError, ValueError, KeyError) as exc:
            return False, str(exc)

    def admin_config_reload(self) -> tuple[bool, str]:
        try:
            self._reload_config_from_disk()
            return True, f"Reloaded from {config_file()}"
        except OSError as exc:
            return False, str(exc)

    def admin_settings(self) -> dict:
        ui_cfg = self.config.get("ui") or {}
        ss_cfg = self.config.get("screensaver") or {}
        return {
            "channel_snow": self._channel_fx.snow_enabled,
            "shutdown_collapse": self._channel_fx.shutdown_enabled,
            "channel_snow_audio": self._channel_fx.audio_enabled,
            "analog_artifacts": self._analog_artifacts.enabled,
            "analog_artifact_rate": self._analog_artifacts.rate_per_minute,
            "footer_hints": self._footer_hints_enabled,
            "safe_zone_top": self._safe_zone_margins.top,
            "safe_zone_bottom": self._safe_zone_margins.bottom,
            "safe_zone_left": self._safe_zone_margins.left,
            "safe_zone_right": self._safe_zone_margins.right,
            "safe_zone_offset_x": self._safe_zone_offset.x,
            "safe_zone_offset_y": self._safe_zone_offset.y,
            "screensaver": self._screensaver_enabled,
            "screensaver_timeout_seconds": self._screensaver_timeout_ms // 1000,
            "cli_overrides": {
                "channel_snow": self._channel_snow_override is not None,
                "shutdown_collapse": self._shutdown_collapse_override is not None,
                "analog_artifacts": self._analog_artifacts_override is not None,
                "safe_zone": self._safe_zone_override is not None,
                "safe_zone_offset": self._safe_zone_offset_override is not None,
                "screensaver": self._screensaver_override is not None,
                "screensaver_timeout": self._screensaver_timeout_override is not None,
            },
        }

    def admin_update_settings(self, patch: dict) -> tuple[bool, str]:
        if not isinstance(patch, dict):
            return False, "settings must be a JSON object"

        ui_cfg = dict(self.config.get("ui") or {})
        ss_cfg = dict(self.config.get("screensaver") or {})

        if "channel_snow" in patch and self._channel_snow_override is None:
            ui_cfg["channel_snow"] = bool(patch["channel_snow"])
        if "shutdown_collapse" in patch and self._shutdown_collapse_override is None:
            ui_cfg["shutdown_collapse"] = bool(patch["shutdown_collapse"])
        if "channel_snow_audio" in patch:
            ui_cfg["channel_snow_audio"] = bool(patch["channel_snow_audio"])
        if "analog_artifacts" in patch and self._analog_artifacts_override is None:
            ui_cfg["analog_artifacts"] = bool(patch["analog_artifacts"])
        if "footer_hints" in patch:
            ui_cfg["footer_hints"] = bool(patch["footer_hints"])
        if "analog_artifact_rate" in patch:
            try:
                ui_cfg["analog_artifact_rate"] = max(
                    0.0, min(60.0, float(patch["analog_artifact_rate"]))
                )
            except (TypeError, ValueError):
                return False, "invalid analog_artifact_rate"
        if self._safe_zone_override is None:
            sz = dict(ui_cfg.get("safe_zone") or safe_zone_to_config(parse_safe_zone(None)))
            for key, field in (
                ("safe_zone_top", "top"),
                ("safe_zone_bottom", "bottom"),
                ("safe_zone_left", "left"),
                ("safe_zone_right", "right"),
            ):
                if key in patch:
                    try:
                        sz[field] = max(0.0, min(25.0, float(patch[key])))
                    except (TypeError, ValueError):
                        return False, f"invalid {key}"
            for key, field in (
                ("safe_zone_offset_x", "offset_x"),
                ("safe_zone_offset_y", "offset_y"),
            ):
                if key in patch:
                    if self._safe_zone_offset_override is not None:
                        continue
                    try:
                        sz[field] = max(-320, min(320, int(patch[key])))
                    except (TypeError, ValueError):
                        return False, f"invalid {key}"
            if any(k in patch for k in (
                "safe_zone_top", "safe_zone_bottom", "safe_zone_left", "safe_zone_right",
                "safe_zone_offset_x", "safe_zone_offset_y",
            )):
                ui_cfg["safe_zone"] = sz
        if "screensaver" in patch and self._screensaver_override is None:
            ss_cfg["enabled"] = bool(patch["screensaver"])
        if "screensaver_timeout_seconds" in patch and self._screensaver_timeout_override is None:
            try:
                ss_cfg["timeout_seconds"] = max(10, int(patch["screensaver_timeout_seconds"]))
            except (TypeError, ValueError):
                return False, "invalid screensaver_timeout_seconds"

        self.config["ui"] = ui_cfg
        self.config["screensaver"] = ss_cfg
        save_config(self.config)
        self._apply_runtime_config()
        return True, "Settings updated"

    def admin_verify_path(self, path: str) -> dict:
        return verify_media_path(path)

    def admin_verify_mount(self, index: int) -> dict:
        mounts = list(self.config.get("mounts") or [])
        if index < 0 or index >= len(mounts):
            return {"ok": False, "error": "mount index out of range"}
        entry = mounts[index]
        if not isinstance(entry, dict):
            return {"ok": False, "error": "invalid mount entry"}
        result = verify_mount_entry(entry)
        result["index"] = index
        return result

    def admin_scan_library(
        self, paths: list[str] | None = None, *, apply: bool = False
    ) -> dict:
        scan_list = [p for p in (paths or self.media_paths) if p]
        result = scan_paths(scan_list)
        if apply and result.get("ok") and self.view != self.PLAYING:
            self._apply_library_discovery(result.get("discovery") or discover_library(scan_list, device_name=self._device_name))
            self._duration_cache.clear()
            self._img_cache.clear()
            self._img_cache_order.clear()
            summary = library_summary(self.shows, self.movies)
            result.update(summary)
            result["layout"] = self.library_layout
            result["tree"] = library_tree_from_discovery(self.shows, self.movies)
            result["applied"] = True
            result["message"] = (
                f"Applied: {summary['shows']} show(s), {summary['episodes']} episode(s), "
                f"{summary['movies']} movie(s)"
            )
        else:
            result["applied"] = False
        return result

    def admin_update_paths(self, patch: dict) -> tuple[bool, str]:
        if not isinstance(patch, dict):
            return False, "body must be a JSON object"
        if "media_paths" in patch:
            paths = patch["media_paths"]
            if not isinstance(paths, list):
                return False, "media_paths must be a list"
            self.config["media_paths"] = [str(p) for p in paths if str(p).strip()]
        if "mounts" in patch:
            mounts = patch["mounts"]
            if not isinstance(mounts, list):
                return False, "mounts must be a list"
            self.config["mounts"] = mounts
        save_config(self.config)
        self._apply_runtime_config()
        return True, "Paths updated"

    def _start_admin_server(self) -> None:
        admin_cfg = dict(self.config.get("admin") or {})
        if self._admin_enabled_override is not None:
            admin_cfg["enabled"] = bool(self._admin_enabled_override)
        if self._admin_port_override is not None:
            admin_cfg["port"] = int(self._admin_port_override)
        self._admin_server = start_admin_if_enabled(
            self,
            admin_cfg,
            local_only=self._admin_local_only,
        )

    def _shutdown(self) -> None:
        """Release playback and admin resources."""
        LOG.info("shutting down")
        shutdown_snapshot = None
        if self._channel_fx.shutdown_enabled:
            shutdown_snapshot = self.screen.copy()
        if self.player:
            self.player.stop()
        self._playback_cache.shutdown()
        if shutdown_snapshot is not None:
            self._channel_fx.play_shutdown(
                self.screen,
                shutdown_snapshot,
                self._shutdown_viewport(),
                after_frame=self.present,
            )
        if self._admin_server:
            self._admin_server.stop()
            self._admin_server = None

    def run(self):
        # Brief brand splash on startup (parent mode only)
        try:
            if not self._kids_mode_active:
                self.draw_startup_splash()
            pygame.event.clear()
            self._arm_quit_grace(1000)
            self._last_activity_ms = pygame.time.get_ticks()
            LOG.info(
                "ready view=%s layout=%s kids=%s",
                self.view,
                self.library_layout,
                self._kids_mode_active,
            )

            while self.running:
                # ═══════════════════════════════════════════════════════════════════
                # PLAYBACK MODE: embedded video rendering
                # ═══════════════════════════════════════════════════════════════════
                if self.view == self.PLAYING:
                    if not self.player:
                        self.view = self._playback_return_view()
                        if self._kids_mode_active:
                            self._kids_restore_browse_cursor()
                        continue
                    if self._playback_stalled:
                        for event in pygame.event.get():
                            if self._handle_window_event(event):
                                continue
                            if event.type == pygame.QUIT:
                                self._handle_quit_event("playback-stall")
                                break
                            action = None
                            if event.type == pygame.KEYDOWN:
                                self._note_keyboard_input()
                                # Dial 0 = stop, same as Esc back during playback.
                                if digit_for_key(self.keymap, event.key) == 0:
                                    action = "back"
                                else:
                                    action = self._key_to_playback_action(event.key)
                            else:
                                action = self._gamepad.event_to_action(event)
                                if action:
                                    self._note_gamepad_input()
                            if action == "back":
                                self._playback_stalled = False
                                self._stall_auto_retry_done = False
                                self.stop_playback()
                                break
                            if action == "select":
                                self._stall_auto_retry_done = False
                                if self._retry_playback(resume_secs=self._stall_resume_pos):
                                    continue
                                self.channel_error = "RETRY FAILED"
                                self.channel_error_time = pygame.time.get_ticks()
                                self._playback_stalled = False
                                self.stop_playback()
                                break
                        self.screen.fill(C.BLACK)
                        self.draw_stall_overlay()
                        self.present()
                        self.clock.tick(30)
                        continue

                    if self.player and self.player.is_finished():
                        self._handle_episode_finished()
                        continue

                    if self.player and self.player.check_stall():
                        self._handle_playback_stall()
                        if self._playback_stalled:
                            continue

                    self._maybe_switch_to_playback_cache()

                    for event in pygame.event.get():
                        if self._handle_window_event(event):
                            continue
                        if event.type == pygame.QUIT:
                            self.stop_playback()
                            self._request_quit(source="playback-quit")
                            break
                        action = None
                        if event.type == pygame.KEYDOWN:
                            self._note_keyboard_input()
                            if (
                                key_matches(self.keymap, event.key, "cache_cancel")
                                and self._should_show_cache_overlay()
                            ):
                                self._cancel_background_cache()
                                continue
                            # Dial 0 = stop, same as Esc back during playback.
                            if digit_for_key(self.keymap, event.key) == 0:
                                action = "back"
                            else:
                                action = self._key_to_playback_action(event.key)
                        else:
                            action = self._gamepad.event_to_action(event)
                            if action:
                                self._note_gamepad_input()
                        if action and not self._process_playback_action(action):
                            break

                    # Update time position for progress bar
                    if self.player and self.player.is_playing():
                        self.player.update_time()

                    # Render: video frame + overlays
                    self.draw_playback()
                    self.present()
                    self.clock.tick(30)
                    continue

                # ═══════════════════════════════════════════════════════════════════
                # BROWSING MODE: menu navigation
                # ═══════════════════════════════════════════════════════════════════

                if self._screensaver_active:
                    for event in pygame.event.get():
                        if self._handle_window_event(event):
                            continue
                        if event.type == pygame.QUIT:
                            self._handle_quit_event("screensaver")
                        elif event.type == pygame.KEYDOWN:
                            self._note_keyboard_input()
                    if self.running:
                        self._tick_screensaver()
                        self.present()
                        self.clock.tick(60)
                    continue

                if (
                    self._screensaver_enabled
                    and self._screensaver_idle_views()
                    and pygame.time.get_ticks() - self._last_activity_ms >= self._screensaver_timeout_ms
                ):
                    self._enter_screensaver()
                    continue

                for event in pygame.event.get():
                    if self._handle_window_event(event):
                        continue
                    if event.type == pygame.QUIT:
                        self._handle_quit_event("browse")

                    elif event.type == pygame.KEYDOWN:
                        self._note_keyboard_input()
                        key_action = self._action_for_key(event.key)

                        if self.view == self.KEY_CAPTURE:
                            if key_action == "back":
                                self.view = self.KEY_CONFIG
                                continue
                            if key_matches(self.keymap, event.key, "keymap_reset"):
                                continue
                            if key_matches(self.keymap, event.key, "keymap_remove"):
                                continue
                            action_id = KEY_ACTIONS[self.config_cursor][0]
                            add_binding(self.keymap, action_id, event.key)
                            self._rebuild_key_lookup()
                            self._persist_keymap()
                            self.view = self.KEY_CONFIG
                            continue

                        elif self.view == self.KEY_CONFIG:
                            if key_matches(self.keymap, event.key, "keymap_reset"):
                                self.reset_keymap()
                                continue
                            if key_matches(self.keymap, event.key, "keymap_remove"):
                                self._remove_key_config_binding()
                                continue
                            if key_action == "back":
                                self.exit_key_config()
                            elif key_action == "select":
                                self.view = self.KEY_CAPTURE
                            elif key_action == "up":
                                self.config_cursor = (
                                    self.config_cursor - 1
                                ) % len(KEY_ACTIONS)
                            elif key_action == "down":
                                self.config_cursor = (
                                    self.config_cursor + 1
                                ) % len(KEY_ACTIONS)
                            elif key_action == "left":
                                self._key_config_prev_page()
                            elif key_action == "right":
                                self._key_config_next_page()
                            continue

                        elif self.view == self.GAMEPAD_CAPTURE:
                            if key_action == "back":
                                self.view = self.GAMEPAD_CONFIG
                            continue

                        elif self.view == self.GAMEPAD_CONFIG:
                            if key_matches(self.keymap, event.key, "keymap_reset"):
                                self.reset_gamepad_bindings()
                                continue
                            if key_matches(self.keymap, event.key, "keymap_remove"):
                                self._remove_gamepad_config_binding()
                                continue
                            if key_action == "back":
                                self.exit_gamepad_config()
                            elif key_action == "select":
                                self._start_gamepad_capture()
                            elif key_action == "up":
                                self._gamepad_config_cursor = (
                                    self._gamepad_config_cursor - 1
                                ) % len(GAMEPAD_ACTIONS)
                            elif key_action == "down":
                                self._gamepad_config_cursor = (
                                    self._gamepad_config_cursor + 1
                                ) % len(GAMEPAD_ACTIONS)
                            elif key_action == "left":
                                self._gamepad_config_prev_page()
                            elif key_action == "right":
                                self._gamepad_config_next_page()
                            continue

                        elif self.view == self.CONFIRM_EXIT:
                            if key_action == "back":
                                self.view = getattr(
                                    self,
                                    "_confirm_exit_return_view",
                                    self._view_for_library_layout(),
                                )
                            elif key_action == "left":
                                self._set_confirm_exit_choice(True)
                            elif key_action == "right":
                                self._set_confirm_exit_choice(False)
                            elif key_action in ("up", "down"):
                                self._confirm_exit_yes = not self._confirm_exit_yes
                            elif key_action == "select":
                                self._activate_confirm_exit_choice()
                            continue

                        elif self.view == self.SAFE_ZONE_EDIT:
                            if key_action == "select":
                                if self._safe_zone_save_prompt:
                                    self.exit_safe_zone_editor(
                                        save=self._safe_zone_save_yes
                                    )
                                else:
                                    self._toggle_safe_zone_edit_mode()
                            elif key_action == "back":
                                if self._safe_zone_save_prompt:
                                    self._safe_zone_save_prompt = False
                                else:
                                    self._safe_zone_save_prompt = True
                                    self._safe_zone_save_yes = True
                            elif self._safe_zone_save_prompt:
                                if key_action in ("left", "up"):
                                    self._safe_zone_save_yes = True
                                elif key_action in ("right", "down"):
                                    self._safe_zone_save_yes = False
                            elif key_action == "up":
                                self._adjust_safe_zone_edit("up")
                            elif key_action == "down":
                                self._adjust_safe_zone_edit("down")
                            elif key_action == "left":
                                self._adjust_safe_zone_edit("left")
                            elif key_action == "right":
                                self._adjust_safe_zone_edit("right")
                            continue

                        digit = digit_for_key(self.keymap, event.key)
                        if digit is not None:
                            self._append_dial_digit(digit)
                            continue

                        if self.channel_digits:
                            self.channel_digits = ""
                            self.channel_timer = 0

                        if key_action == "kids_mode_toggle":
                            self._toggle_kids_mode()
                            continue

                        if key_action == "footer_hints_toggle":
                            self._toggle_footer_hints()
                            continue

                        if key_action == "letter_menu" and not self._kids_mode_active:
                            self._open_letter_menu()
                            continue

                        if key_action == "kids_tag_toggle" and not self._kids_mode_active:
                            self._toggle_kids_tag_current()
                            continue

                        if key_action == "kids_view_toggle":
                            self._toggle_kids_view()
                            continue

                        if key_action == "kids_carousel_toggle":
                            self._toggle_kids_carousel()
                            continue

                        if key_action == "key_config" and not self._kids_mode_active:
                            self.enter_key_config()
                            continue

                        if key_action == "gamepad_config" and not self._kids_mode_active:
                            self.enter_gamepad_config()
                            continue

                        if key_action == "safe_zone":
                            self.enter_safe_zone_editor()
                            continue

                        if key_action == "help" and not self._kids_mode_active:
                            self.draw_help()
                            continue

                        if key_action == "quit":
                            self._request_quit(source="quit-key")
                            continue

                        if key_action == "reset":
                            self._reset_hold_start = pygame.time.get_ticks()
                            self._reset_rescan_fired = False
                            continue

                        action = self._key_to_browse_action(event.key)
                        if action:
                            if self._letter_menu_open:
                                self._process_letter_menu_action(action)
                            else:
                                self._process_browse_action(action)

                    elif event.type == pygame.KEYUP:
                        if key_matches(self.keymap, event.key, "reset"):
                            if self._reset_hold_start and not self._reset_rescan_fired:
                                self.reset_watch_status()
                            self._reset_hold_start = 0
                            self._reset_rescan_fired = False

                    elif event.type in (
                        pygame.JOYBUTTONDOWN,
                        pygame.JOYHATMOTION,
                        pygame.JOYAXISMOTION,
                    ):
                        if self._handle_gamepad_capture_event(event):
                            continue
                        action = self._gamepad.event_to_action(event)
                        if not action:
                            continue
                        self._note_gamepad_input()
                        if self.view == self.CONFIRM_EXIT:
                            self._process_confirm_exit_action(action)
                            continue
                        if self.view == self.SAFE_ZONE_EDIT:
                            self._process_safe_zone_edit_action(action)
                            continue
                        if self.view in (
                            self.KEY_CONFIG,
                            self.KEY_CAPTURE,
                            self.GAMEPAD_CONFIG,
                            self.GAMEPAD_CAPTURE,
                        ):
                            if action == "back" and self.view == self.KEY_CONFIG:
                                self.exit_key_config()
                            elif action == "back" and self.view == self.GAMEPAD_CONFIG:
                                self.exit_gamepad_config()
                            continue
                        if self._letter_menu_open:
                            self._process_letter_menu_action(action)
                        else:
                            self._process_browse_action(action)

                # Dial timeout — bare 0 / 00 / normal channels
                self._tick_dial_timeout()
                self._tick_reset_hold()
                self._tick_periodic_rescan()

                if self.view == self.PLAYING:
                    continue

                if self.view == self.CONFIRM_EXIT:
                    self.draw_confirm_exit()
                    self._apply_channel_fx()
                    self.present()
                elif self.view == self.SAFE_ZONE_EDIT:
                    self.draw_safe_zone_editor()
                    self._apply_channel_fx()
                elif self.view in (self.KEY_CONFIG, self.KEY_CAPTURE):
                    self.draw_key_config(capturing=(self.view == self.KEY_CAPTURE))
                    self._apply_channel_fx()
                elif self.view in (self.GAMEPAD_CONFIG, self.GAMEPAD_CAPTURE):
                    self.draw_gamepad_config(capturing=(self.view == self.GAMEPAD_CAPTURE))
                    self._apply_channel_fx()
                else:
                    self.draw()
                    self.present()
                self.clock.tick(30)
        except Exception:
            LOG.exception("TV Time Capsule stopped due to an unexpected error")
        finally:
            if not self.running:
                LOG.info("main loop ended")
            self._shutdown()
            pygame.quit()

