"""Main pygame application UI and event loop."""

from __future__ import annotations

import json
import os
import subprocess
import warnings
from contextlib import contextmanager

import pygame

from .admin_api import (
    effective_media_paths,
    library_summary,
    library_tree_from_shows,
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
from .gamepad import GamepadHandler
from .keymap import KEY_ACTIONS, DEFAULT_KEYMAP, key_display_name, keymap_for_display, load_keymap
from .log import LOG
from .media import discover_shows
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
    get_resume_ep,
    load_state,
    save_state,
    set_episode_position,
    set_resume_ep,
    watch_summary,
)
from .web_admin import AdminServer, DeferredAdminBridge, start_admin_if_enabled

FOOTER_BAR_H = 34
NAV_BAR_H = 28
HUD_PAD = 12
HUD_TOP_BAR_H = 50
HUD_SCRUB_H = 8
HUD_SCRUB_TRACK_H = 32
HUD_SCRUB_DOT_R = 9
HUD_VOL_BAR_W = 14
HUD_VOL_BAR_H = 32
SAFE_ZONE_MARGIN_STEP = 0.5
SAFE_ZONE_OFFSET_STEP = 2


class TVTimeCapsule:
    SHOW_LIST = 0
    SEASON_SELECT = 1
    EPISODE_SELECT = 2
    KEY_CONFIG = 3
    KEY_CAPTURE = 4
    PLAYING = 5
    CONFIRM_EXIT = 6
    SAFE_ZONE_EDIT = 7

    def __init__(
        self,
        media_paths,
        fullscreen=True,
        force_43=False,
        scanlines=None,
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
        self._scanlines_override = scanlines
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
        self._init_safe_zone_state()

        ui_cfg_pre = self.config.get("ui") or {}
        if scanlines is not None:
            self.scanlines = bool(scanlines)
        else:
            self.scanlines = bool(ui_cfg_pre.get("scanlines", False))

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

        # Pre-render the scanline overlay (lazy — only if enabled)
        self._scanline_surf = None

        if "keymap" in self.state:
            if not self.config.get("keymap"):
                self.config["keymap"] = self.state.pop("keymap")
                save_config(self.config)
            else:
                self.state.pop("keymap", None)
            save_state(self.state)
        self.keymap = load_keymap(self.config)
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
        ui_cfg = self.config.get("ui") or {}
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
        self._gamepad = GamepadHandler(enabled=gp_cfg.get("enabled", True))
        self._gamepad_count = self._gamepad.init()
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

        # Channel number input
        self.channel_digits = ""
        self.channel_timer = 0
        self.channel_flash = ""
        self.channel_flash_time = 0
        self.channel_error = ""
        self.channel_error_time = 0
        self._confirm_exit_yes = False
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

        self.shows = discover_shows(self.media_paths)
        self.show_names: list[str] = []
        self._show_channel: dict[str, int] = {}
        self._channel_show: dict[int, str] = {}
        self._apply_channel_lineup()
        self.cur_show = None
        self.cur_season = None

        lib_cfg = self.config.get("library") or {}
        self._rescan_interval_ms = int(lib_cfg.get("rescan_interval_seconds", 0)) * 1000
        self._rescan_long_press_ms = int(lib_cfg.get("rescan_long_press_ms", 800))
        self._last_rescan_ms = pygame.time.get_ticks()
        self._rescan_banner_until = 0
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
        self._img_cache_max = 8     # Max thumbnails cached (safe for 256MB Pi)
        self._duration_cache = {}   # Lazy ffprobe duration cache (path → "MM:SS")

        # Marquee: scroll overflowing episode titles on the selected row
        self._marquee_key = None
        self._marquee_start = 0

        # Ignore play/seek/pause keys briefly after starting an episode
        self._play_input_grace_until = 0

        pygame.key.set_repeat(400, 130)

        if self._admin_bridge is not None:
            self._admin_bridge.attach(self)
        elif self._admin_server is None:
            self._start_admin_server()

    def _apply_channel_lineup(self):
        """Order ``show_names`` and rebuild channel maps from config."""
        channels_cfg = self.config.get("channels") or {}
        ordered, show_to_ch, ch_to_show = build_channel_lineup(
            self.shows.keys(), channels_cfg
        )
        self.show_names = ordered
        self._show_channel = show_to_ch
        self._channel_show = ch_to_show

    def _display_channel(self, show_name: str) -> int:
        return self._show_channel.get(show_name, 0)

    def _rescan_library(self) -> bool:
        """Re-scan media roots. Safe only while not playing video."""
        if self.view == self.PLAYING:
            return False

        prev_show = None
        if self.show_names and 0 <= self.cursor < len(self.show_names):
            prev_show = self.show_names[self.cursor]

        self.shows = discover_shows(self.media_paths)
        self._apply_channel_lineup()

        if not self.show_names:
            self.cursor = 0
        elif prev_show and prev_show in self.show_names:
            self.cursor = self.show_names.index(prev_show)
        else:
            self.cursor = min(self.cursor, len(self.show_names) - 1)

        self._duration_cache.clear()
        self._img_cache.clear()
        self._img_cache_order.clear()
        self._last_rescan_ms = pygame.time.get_ticks()
        self._rescan_banner_until = self._last_rescan_ms + 1500
        return True

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
        reset_key = self.keymap.get("reset", DEFAULT_KEYMAP["reset"])
        if not pygame.key.get_pressed()[reset_key]:
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
        if self.view != self.SHOW_LIST:
            return
        now = pygame.time.get_ticks()
        if now - self._last_rescan_ms >= self._rescan_interval_ms:
            self._rescan_library()

    # ─── Scanline overlay ────────────────────────────────────────────────

    def _make_scanlines(self, width: int = SCREEN_W, height: int = SCREEN_H):
        """Create a semi-transparent scanline overlay for CRT effect."""
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        for y in range(0, height, 3):
            pygame.draw.line(surf, C.SCANLINE, (0, y), (width, y))
        return surf

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

    def load_image(self, path, max_size):
        key = (path, max_size)
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
            img = self._load_image_surface(path)
            if img is None:
                self._img_cache[key] = None
                return None
            src_w, src_h = img.get_size()
            if src_w == 0 or src_h == 0:
                self._img_cache[key] = None
                return None
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
    def _load_image_surface(path):
        """Load an image file as a pygame Surface.
        Tries pygame's native loader first, falls back to Pillow for
        systems where SDL_image lacks PNG/JPEG support (e.g. macOS wheels).
        """
        # Try pygame's native loader (works for BMP, and for PNG/JPEG when
        # SDL_image is compiled with extended format support).
        try:
            return pygame.image.load(path).convert()
        except Exception:
            pass

        # Fall back to Pillow → pygame surface
        try:
            from PIL import Image as PILImage
            pil_img = PILImage.open(path).convert("RGB")
            data = pil_img.tobytes("raw", "RGB")
            return pygame.image.fromstring(data, pil_img.size, "RGB")
        except Exception:
            return None

    # ─── Display setup ───────────────────────────────────────────────────

    def _enable_omx_overlay(self):
        """Use a transparent framebuffer so omxplayer's layer shows through."""
        self._omx_overlay = True
        self._create_framebuffer()

    def _marquee_offset(self, key, text_w, avail_w):
        """Pixel offset for a back-and-forth scroll of overflowing text."""
        overflow = text_w - avail_w
        if overflow <= 0:
            return 0

        now = pygame.time.get_ticks()
        if key != self._marquee_key:
            self._marquee_key = key
            self._marquee_start = now

        elapsed = now - self._marquee_start
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
        return False

    def _resize_framebuffer(self, width: int, height: int) -> None:
        """Resize the logical canvas when safe-zone margins change (not the OS window)."""
        self.canvas_w = width
        self.canvas_h = height
        self._create_framebuffer()
        if self.player:
            self.player.canvas_w = width
            self.player.canvas_h = height
        self._scanline_surf = None
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

    def _safe_zone_for_ui(self) -> bool:
        """Safe zone applies to menus/UI only — never video playback."""
        if self.view == self.PLAYING:
            return False
        if not self._safe_zone_enabled:
            return False
        if self.view == self.SHOW_LIST and self._show_list_test_pattern:
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

    def _apply_scanlines(self):
        """Overlay CRT scanlines on the current frame (if enabled)."""
        if not self.scanlines:
            return
        w, h = self.screen.get_size()
        if self._scanline_surf is None or self._scanline_surf.get_size() != (w, h):
            self._scanline_surf = self._make_scanlines(w, h)
        self.screen.blit(self._scanline_surf, (0, 0))

    def _apply_analog_artifacts(self) -> None:
        if self.view == self.SHOW_LIST:
            self._analog_artifacts.tick()
            self._analog_artifacts.apply(self.screen)

    def _clear_show_list_test_pattern(self) -> None:
        self._show_list_test_pattern = None

    def _commit_show_list_test_pattern(self, dial: str) -> bool:
        """Show a secret test pattern for dial codes 0 / 00 / 000."""
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
        if self.view == self.SHOW_LIST:
            self.draw_show_browser()
        elif self.view == self.SEASON_SELECT:
            self.draw_season_browser()
        elif self.view == self.EPISODE_SELECT:
            self.draw_episode_browser()

    def _blit_now_playing_content(
        self, show, season, episode, channel, resume_secs=None
    ) -> None:
        """Now-playing splash artwork without blocking or snow."""
        self.screen.fill(C.BLACK)
        rect = SafeZoneRect(0, 0, self.sw, self.sh)
        scale = min(rect.w / SCREEN_W, rect.h / SCREEN_H)
        pad = max(6, int(12 * scale))

        ep_num = episode["number"]
        ep_name = episode.get("name") or ""

        ch = self._scale_overlay_surface(
            self.font_lg.render(str(channel), True, C.GREEN), scale
        )
        self.screen.blit(ch, (rect.x + rect.w - ch.get_width() - pad, rect.y + pad))

        label = f"S-{season:02d} - E-{ep_num:02d}"
        s = self._scale_overlay_surface(
            self.font_md.render(label, True, C.WHITE), scale
        )
        mid_y = rect.y + rect.h // 2
        self.screen.blit(
            s, s.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y - int(40 * scale))
        )
        if ep_name:
            n = self._truncate_overlay_text(
                ep_name, self.font_md, C.BLUE, rect.w - pad * 2, scale=scale
            )
            self.screen.blit(
                n, n.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y + int(10 * scale))
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
            sn, sn.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y + int(55 * scale))
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
            else:
                with self._ui_layout(letterbox=True):
                    self._draw_channel_tune_frame()
            self._channel_fx.draw(self.screen)
            if self.view == self.SAFE_ZONE_EDIT:
                self.draw_channel_overlay()
                self._draw_rescan_banner()
            else:
                with self._ui_layout(letterbox=True):
                    self.draw_channel_overlay()
                    self._draw_rescan_banner()
            self.present()
            self.clock.tick(60)

    def _draw_footer(self, *hints):
        """Draw a consistent footer bar with spaced hint segments."""
        bar_h = FOOTER_BAR_H
        fy = self.sh - bar_h
        gap = 28
        pygame.draw.rect(self.screen, C.BG_FOOTER, (0, fy, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, fy), (self.sw, fy), 1)

        segments = [h for h in hints if h]
        if not segments:
            return

        surfaces = [self.font_sm.render(text, True, C.DIM) for text in segments]
        total_w = sum(s.get_width() for s in surfaces) + gap * (len(surfaces) - 1)
        max_w = self.sw - 32

        while total_w > max_w and gap > 12:
            gap -= 4
            total_w = sum(s.get_width() for s in surfaces) + gap * (len(surfaces) - 1)

        if total_w > max_w:
            # Drop trailing hints until it fits, then truncate the last one if needed.
            while surfaces and total_w > max_w:
                surfaces.pop()
                total_w = sum(s.get_width() for s in surfaces) + gap * max(0, len(surfaces) - 1)
            if surfaces:
                text = segments[len(surfaces) - 1]
                while self.font_sm.size(text + "...")[0] > max_w and len(text) > 3:
                    text = text[:-1]
                surfaces[-1] = self.font_sm.render(text + "...", True, C.DIM)
                total_w = surfaces[-1].get_width()

        x = (self.sw - total_w) // 2
        cy = fy + bar_h // 2
        for surf in surfaces:
            self.screen.blit(surf, surf.get_rect(left=x, centery=cy))
            x += surf.get_width() + gap

    def _draw_header(self, left_text, right_text="", ch_num=None):
        """Draw a consistent header bar at the top of the screen."""
        bar_h = 48
        pygame.draw.rect(self.screen, C.BG_HEADER, (0, 0, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, bar_h), (self.sw, bar_h), 1)

        # Left: breadcrumb/title text — larger, bright white
        lt = self.font_md.render(left_text, True, C.BRIGHT)
        self.screen.blit(lt, (16, (bar_h - lt.get_height()) // 2))

        # Right: channel number if provided
        if ch_num is not None:
            rt = self.font_md.render(str(ch_num), True, C.GREEN)
            self.screen.blit(rt, (self.sw - rt.get_width() - 16,
                                  (bar_h - rt.get_height()) // 2))

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
            pygame.draw.rect(self.screen, (14, 20, 35), (0, y, self.sw, nav_h))
        if direction == "up":
            pygame.draw.line(self.screen, (25, 40, 70), (0, y + nav_h), (self.sw, y + nav_h), 1)
        else:
            pygame.draw.line(self.screen, (25, 40, 70), (0, y), (self.sw, y), 1)
        return nav_h

    def _show_browser_layout(self, header_h: int):
        """Vertical layout for the cable-TV show browser."""
        nav_h = NAV_BAR_H
        footer_h = FOOTER_BAR_H
        up_y = header_h
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
        footer_h = FOOTER_BAR_H
        header_h = 48
        up_y = header_h
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

    def _stack_first_visible(self, cursor, total):
        """Start index of the current page (fixed pages of STACK_VISIBLE, no scroll)."""
        if total <= STACK_VISIBLE:
            return 0
        return (cursor // STACK_VISIBLE) * STACK_VISIBLE

    def _stack_page_size(self, first_visible, total):
        """How many cards are on this page (may be fewer than STACK_VISIBLE on the last page)."""
        return min(STACK_VISIBLE, total - first_visible)

    def _stack_page_nav(self, first_visible, total):
        """Labels for page-up / page-down nav bars on stack browsers."""
        items_above = first_visible
        items_below = max(0, total - (first_visible + STACK_VISIBLE))
        up_label = f"Previous {STACK_VISIBLE}" if items_above > 0 else ""
        down_label = (
            f"Next {min(STACK_VISIBLE, items_below)}" if items_below > 0 else ""
        )
        return up_label, down_label, items_above > 0, items_below > 0

    def _move_cursor_stack(self, direction, total):
        """Step within a page; at the page edge, flip to the next/previous page."""
        first_visible = self._stack_first_visible(self.cursor, total)
        page_top = first_visible
        page_bottom = first_visible + self._stack_page_size(first_visible, total) - 1

        if direction > 0:
            if self.cursor >= total - 1:
                return
            if self.cursor >= page_bottom:
                self.cursor = first_visible + STACK_VISIBLE
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
        alpha: int = 255,
        color=C.GREEN,
        font=None,
        max_width: int | None = None,
    ) -> None:
        """Centered message box with word wrap for transient warnings."""
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
        bg_surf.fill((0, 10, 5, min(220, alpha)))
        pygame.draw.rect(
            bg_surf,
            (*color[:3], min(alpha, 200)),
            (0, 0, box_w, box_h),
            2,
            border_radius=6,
        )
        self.screen.blit(bg_surf, (box_x, box_y))

        y = box_y + pad_y
        for line in lines:
            surf = font.render(line, True, color)
            if alpha < 255:
                surf.set_alpha(alpha)
            x = box_x + (box_w - surf.get_width()) // 2
            self.screen.blit(surf, (x, y))
            y += line_h + line_gap

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
        if self.view == self.SHOW_LIST:
            return [{'name': n, 'data': self.shows[n]} for n in self.show_names]
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
            self.draw_channel_overlay()
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
                alpha = 255
                if elapsed > CHANNEL_ERROR_MS // 2:
                    fade_progress = (elapsed - CHANNEL_ERROR_MS // 2) / (CHANNEL_ERROR_MS // 2)
                    alpha = int(255 * (1.0 - fade_progress))

                self._draw_popup_banner(self.channel_error, alpha=alpha)
                return
            else:
                self.channel_error = ""
                self.channel_error_time = 0

        # Commit flash overlay (shown after channel is committed)
        if self.channel_flash and self.channel_flash_time > 0:
            elapsed = now - self.channel_flash_time
            if elapsed < CHANNEL_FLASH_MS:
                alpha = 255
                if elapsed > CHANNEL_FLASH_MS // 2:
                    fade_progress = (elapsed - CHANNEL_FLASH_MS // 2) / (CHANNEL_FLASH_MS // 2)
                    alpha = int(255 * (1.0 - fade_progress))

                box_w = 160
                box_h = 100
                box_x = self.sw - box_w - 16
                box_y = 16

                bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
                bg_surf.fill((0, 10, 5, min(200, alpha)))
                pygame.draw.rect(bg_surf, (*C.GREEN[:3], min(alpha, 180)),
                                 (0, 0, box_w, box_h), 2, border_radius=6)
                self.screen.blit(bg_surf, (box_x, box_y))

                ch_surf = self.font_lg.render(self.channel_flash, True, C.GREEN)
                if alpha < 255:
                    ch_surf.set_alpha(alpha)
                self.screen.blit(ch_surf, (box_x + (box_w - ch_surf.get_width()) // 2,
                                           box_y + (box_h - ch_surf.get_height()) // 2))
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
        """Cable-TV show browser: one show at a time, full-screen.

        Layout:
          [HEADER BAR: show name + channel number]
          [UP NAV BAR: full-width, shows show above if available]
          [CONTENT: thumbnail or wrapped show title]
          [DOWN NAV BAR: full-width, shows show below if available]
          [FOOTER BAR: controls hint]
        """
        self.screen.fill(C.BG)
        shows = self.show_names
        if not shows:
            t = self.font_md.render("No shows found", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            self._apply_scanlines()
            return

        test_dial = self._show_list_test_pattern
        if test_dial:
            pattern_path = pattern_asset_path(test_dial)
            if pattern_path and self._blit_fullscreen_asset(pattern_path):
                self._apply_scanlines()
                return
            t = self.font_md.render("TEST PATTERN NOT FOUND", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            self._apply_scanlines()
            return

        idx = self.cursor % len(shows)
        show_name = shows[idx]
        show_data = self.shows[show_name]
        ch_num = self._display_channel(show_name)

        # ── Header ──
        header_h = self._draw_header(show_name.upper(), ch_num=ch_num)
        layout = self._show_browser_layout(header_h)
        nav_h = layout["nav_h"]
        up_y = layout["up_y"]
        content_y = layout["content_y"]
        content_bottom = layout["content_bottom"]
        content_h = layout["content_h"]
        down_y = layout["down_y"]

        # ── Up navigation bar (full width) ──
        if idx > 0:
            up_name = shows[idx - 1].upper()
            pygame.draw.rect(self.screen, C.BG_CARD, (0, up_y, self.sw, nav_h))
            up_surf = self.font_sm.render(f"\u25b2  {up_name}", True, C.CYAN)
            self.screen.blit(up_surf, up_surf.get_rect(left=16, centery=up_y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, (14, 20, 35), (0, up_y, self.sw, nav_h))
        pygame.draw.line(self.screen, (25, 40, 70), (0, up_y + nav_h), (self.sw, up_y + nav_h), 1)

        # ── Down navigation bar (full width) ──
        if idx < len(shows) - 1:
            down_name = shows[idx + 1].upper()
            pygame.draw.rect(self.screen, C.BG_CARD, (0, down_y, self.sw, nav_h))
            down_surf = self.font_sm.render(f"\u25bc  {down_name}", True, C.CYAN)
            self.screen.blit(down_surf, down_surf.get_rect(left=16, centery=down_y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, (14, 20, 35), (0, down_y, self.sw, nav_h))
        pygame.draw.line(self.screen, (25, 40, 70), (0, down_y), (self.sw, down_y), 1)

        # ── Central content: test pattern, thumbnail, or wrapped show title ──
        n_total = self._count_total_eps(show_data)
        seasons = self.seasons_for_show(show_name)
        if len(seasons) > 1:
            info = f"{len(seasons)} seasons - {n_total} episodes"
        else:
            info = f"{n_total} episodes"

        if thumb := self.load_image(
            show_data.get("thumbnail"), (self.sw - 80, content_h - 40)
        ):
            tx = (self.sw - thumb.get_width()) // 2
            ty = content_y + (content_h - thumb.get_height() - 20) // 2
            self.screen.blit(thumb, (tx, ty))

            # Info line below thumbnail
            it = self.font_sm.render(info, True, C.DIM)
            info_y = ty + thumb.get_height() + 6
            # Make sure info doesn't go below content area
            if info_y + it.get_height() > content_bottom:
                info_y = content_bottom - it.get_height() - 2
            self.screen.blit(it, it.get_rect(centerx=self.sw // 2, top=info_y))
        else:
            # No thumbnail - wrap the show title and center it
            max_w = self.sw - 60
            lines = self._wrap_text(show_name.upper(), self.font_lg, max_w)

            line_h = self.font_lg.size("Mg")[1] + 6  # extra spacing for readability
            info_h = self.font_sm.size(info)[1]
            total_h = len(lines) * line_h + 10 + info_h
            text_start_y = content_y + max(0, (content_h - total_h) // 2)

            for i, line in enumerate(lines):
                surf = self.font_lg.render(line, True, C.WHITE)
                self.screen.blit(surf, surf.get_rect(centerx=self.sw // 2,
                                                      top=text_start_y + i * line_h))

            # Info line below the title
            it = self.font_sm.render(info, True, C.DIM)
            it_y = text_start_y + len(lines) * line_h + 10
            if it_y + it.get_height() > content_bottom:
                it_y = content_bottom - it.get_height() - 2
            self.screen.blit(it, it.get_rect(centerx=self.sw // 2, top=it_y))

        # ── Footer ──
        self._draw_footer("\u25b2 Up", "\u25bc Down", "> Play", "#ch", "H Help", "Hold R Scan")
        self._apply_scanlines()

    # ─── Season browser ──────────────────────────────────────────────────

    def draw_season_browser(self):
        """Season browser: vertical stack of season cards."""
        self.screen.fill(C.BG)
        seasons = self.seasons_for_show(self.cur_show)
        show_data = self.shows.get(self.cur_show, {})
        total = len(seasons)

        if not seasons:
            t = self.font_md.render("No seasons", True, C.DIM)
            self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))
            self._apply_scanlines()
            return

        # Header — channel number reflects the highlighted item on THIS page
        self._draw_header(f"{self.cur_show.upper()}",
                          ch_num=str(self.cursor + 1))

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
            ch_surf = self.font_md.render(ch_label, True, C.GREEN if selected else C.DIM)
            self.screen.blit(ch_surf, (rect.x + 14,
                                       rect.y + (rect.height - ch_surf.get_height()) // 2))

            # Season label — folder name (e.g. Action) or Season N
            s_label = self.season_display_name(self.cur_show, season_num)
            sl = self.font_md.render(s_label, True, C.BRIGHT if selected else C.WHITE)
            sl_x = rect.x + 100
            # Truncate if too wide
            max_label_w = rect.right - sl_x - 100
            if sl.get_width() > max_label_w and max_label_w > 30:
                label_text = s_label
                while self.font_md.size(label_text + "...")[0] > max_label_w and len(label_text) > 3:
                    label_text = label_text[:-1]
                sl = self.font_md.render(label_text + "...", True, C.BRIGHT if selected else C.WHITE)
            self.screen.blit(sl, (sl_x, rect.y + (rect.height - sl.get_height()) // 2))

            # Episode count / status (right side)
            season_eps = season_data.get('episodes', [])
            n_eps = len(season_eps)
            resume = get_resume_ep(self.state, self.cur_show, season_num)
            watched = sum(1 for e in season_eps if e['number'] <= resume) if resume > 0 else 0
            nxt = next((e for e in season_eps if e['number'] > resume), None)
            if n_eps > 0 and watched >= n_eps:
                info = "[done]"
                info_color = C.DIM
            elif watched > 0 and nxt is not None:
                info = f"E-{nxt['number']:02d} next"
                info_color = C.GREEN
            else:
                info = f"{n_eps} ep{'s' if n_eps != 1 else ''}"
                info_color = C.DIM

            it = self.font_sm.render(info, True, info_color)
            self.screen.blit(it, (rect.right - it.get_width() - 14,
                                   rect.y + (rect.height - it.get_height()) // 2))

        self._draw_nav_bar(layout["down_y"], down_label, "down", down_active)

        # Footer
        self._draw_footer(
            "\u25b2 Up", "\u25bc Down", "> Open", "< Back",
            "#ch", "R Reset",
        )
        self._apply_scanlines()

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
            self._apply_scanlines()
            return

        # Header — channel number reflects the highlighted episode on THIS page
        self._draw_header(
            f"{self.cur_show.upper()}  -  S-{self.cur_season:02d}",
            ch_num=str(self.cursor + 1))

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

        resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
        pos_ep, pos_secs = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        next_up = next((e['number'] for e in episodes if e['number'] > resume), None)

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
            is_watched = resume > 0 and ep_num <= resume
            is_next = (ep_num == next_up)
            is_in_progress = (pos_ep is not None and ep_num == pos_ep)

            # Card background
            if selected:
                pygame.draw.rect(self.screen, C.BG_CARD_SEL, rect, border_radius=8)
                pygame.draw.rect(self.screen, C.CYAN, rect.inflate(2, 2), 2, border_radius=8)
            elif is_in_progress:
                pygame.draw.rect(self.screen, C.NEXT_UP, rect, border_radius=8)
            elif is_next:
                pygame.draw.rect(self.screen, C.NEXT_UP, rect, border_radius=8)
            elif is_watched:
                pygame.draw.rect(self.screen, C.WATCHED, rect, border_radius=8)
            else:
                pygame.draw.rect(self.screen, C.BG_CARD, rect, border_radius=8)

            # Episode thumbnail (small, left side)
            thumb = self.load_image(ep.get('thumbnail'), (item_h - 12, item_h - 12))
            label_x = rect.x + 14
            if thumb:
                tx = rect.x + 10
                ty = rect.y + (rect.height - thumb.get_height()) // 2
                self.screen.blit(thumb, (tx, ty))
                label_x = rect.x + thumb.get_width() + 18

            # Right side: channel number — unique per page (1-based position)
            ch_label = str(item_idx + 1)
            ec = self.font_sm.render(ch_label, True, C.GREEN if selected else C.DIM)

            # Status indicator (right of card)
            status_text = ""
            status_color = C.DIM
            if is_in_progress and not selected:
                status_text = "||"
                status_color = C.GREEN
            elif is_next and not selected:
                status_text = ">"
            elif is_watched and not is_next and not is_in_progress:
                status_text = "*"
                status_color = C.DIM
            st = self.font_sm.render(status_text, True, status_color) if status_text else None

            # Calculate available width for text
            right_margin = ec.get_width() + 14
            if st:
                right_margin += st.get_width() + 6
            avail_w = rect.right - label_x - right_margin

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

            # Right side: channel number
            self.screen.blit(ec, (rect.right - ec.get_width() - 14,
                                   rect.y + (rect.height - ec.get_height()) // 2))

            # Status indicator
            if st:
                self.screen.blit(st, (rect.right - ec.get_width() - st.get_width() - 22,
                                       rect.y + (rect.height - st.get_height()) // 2))

        self._draw_nav_bar(layout["down_y"], down_label, "down", down_active)

        # Footer
        self._draw_footer(
            "\u25b2 Up", "\u25bc Down", "> Play", "< Back",
            "#ch", "R Reset",
        )
        self._apply_scanlines()

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
            fade = 255
        elif self.progress_overlay_timer > 0 and elapsed < OVERLAY_SHOW_MS:
            remaining = OVERLAY_SHOW_MS - elapsed
            fade = min(255, int(255 * remaining / 500)) if remaining < 500 else 255
        else:
            return

        self.player.update_time()
        progress = self.player.progress()
        time_str = f"{self.player.format_time(self.player.time_pos)} / {self.player.format_time(self.player.duration)}"

        rect, scale = self._playback_overlay_layout()
        pad = HUD_PAD
        top_bar_h = HUD_TOP_BAR_H

        bar_surf = pygame.Surface((rect.w, top_bar_h), pygame.SRCALPHA)
        bar_surf.fill((0, 10, 5, min(200, fade)))
        self.screen.blit(bar_surf, (rect.x, rect.y))

        ep = self.playing_episode or {}
        ep_num = ep.get('number', 0)
        ep_name = ep.get('name') or ''
        label = f"S-{self.playing_season or 1:02d} - E-{ep_num:02d}"

        rt = self._scale_overlay_surface(
            self.font_md.render(time_str, True, C.GREEN), scale
        )
        rt.set_alpha(fade)
        rt_x = rect.x + rect.w - rt.get_width() - pad
        rt_y = rect.y + (top_bar_h - rt.get_height()) // 2
        self.screen.blit(rt, (rt_x, rt_y))

        label_max_w = max(20, rt_x - (rect.x + pad) - 8)
        lt = self._truncate_overlay_text(label, self.font_md, C.GREEN, label_max_w, scale=scale)
        lt.set_alpha(fade)
        self.screen.blit(lt, (rect.x + pad, rect.y + (top_bar_h - lt.get_height()) // 2))

        scrub_h = HUD_SCRUB_H
        scrub_track_h = HUD_SCRUB_TRACK_H
        bottom_bar_h = HUD_TOP_BAR_H if ep_name else 0
        scrub_y = rect.y + rect.h - scrub_track_h

        if ep_name:
            bottom_bar_y = scrub_y - bottom_bar_h
            bottom_bar = pygame.Surface((rect.w, bottom_bar_h), pygame.SRCALPHA)
            bottom_bar.fill((0, 10, 5, min(200, fade)))
            self.screen.blit(bottom_bar, (rect.x, bottom_bar_y))

            name_surf = self._truncate_overlay_text(
                ep_name, self.font_md, C.GREEN, rect.w - pad * 2, scale=scale
            )
            name_surf.set_alpha(fade)
            self.screen.blit(
                name_surf,
                (rect.x + pad, bottom_bar_y + (bottom_bar_h - name_surf.get_height()) // 2),
            )

        bar_w = rect.w - pad * 2
        bar_x = rect.x + pad

        track = pygame.Surface((bar_w, scrub_h), pygame.SRCALPHA)
        track.fill((20, 60, 35, min(220, fade)))
        self.screen.blit(track, (bar_x, scrub_y + (scrub_track_h - scrub_h) // 2))

        fill_w = max(1, int(bar_w * progress))
        fill = pygame.Surface((fill_w, scrub_h), pygame.SRCALPHA)
        fill.fill((*C.GREEN[:3], min(255, fade)))
        self.screen.blit(fill, (bar_x, scrub_y + (scrub_track_h - scrub_h) // 2))

        dot_x = bar_x + fill_w
        dot_y = scrub_y + scrub_track_h // 2
        dot_r = HUD_SCRUB_DOT_R
        dot_surf = pygame.Surface((dot_r * 2, dot_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(dot_surf, (*C.BRIGHT, min(255, fade)), (dot_r, dot_r), dot_r)
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

    # ─── Splash screen ────────────────────────────────────────────────────

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

    def _splash_layout(self, lines, section_gap=20):
        """Vertical layout for the controls splash (uses current self.sh / self.sw)."""
        footer_hint_y = self.sh - 18
        divider_y = self.sh - 36
        content_region_top = 62
        content_region_bottom = divider_y - 10
        min_top_pad = 24
        help_height = self._splash_help_content_height(lines, section_gap)
        slack = content_region_bottom - content_region_top - help_height
        y_start = content_region_top + max(min_top_pad, slack // 2)
        if y_start + help_height > content_region_bottom:
            y_start = max(content_region_top, content_region_bottom - help_height)
        return {
            "footer_hint_y": footer_hint_y,
            "divider_y": divider_y,
            "content_region_bottom": content_region_bottom,
            "y_start": y_start,
        }

    def draw_splash(self):
        """Show a 10-second controls splash screen. Dismissable by any key."""
        start = pygame.time.get_ticks()
        duration = 10000  # 10 seconds

        # Build control lines
        km = self.keymap
        lines = [
            ("NAVIGATION", None),
            ("browse shows", f"{key_display_name(km.get('up', DEFAULT_KEYMAP['up']))}/{key_display_name(km.get('down', DEFAULT_KEYMAP['down']))}  up / down"),
            ("enter / select", f"{key_display_name(km.get('right', DEFAULT_KEYMAP['right']))} or {key_display_name(km.get('select', DEFAULT_KEYMAP['select']))}"),
            ("go back", f"{key_display_name(km.get('left', DEFAULT_KEYMAP['left']))} or {key_display_name(km.get('back', DEFAULT_KEYMAP['back']))}"),
            ("reset watch status", f"tap {key_display_name(km.get('reset', DEFAULT_KEYMAP['reset']))}  |  hold to rescan"),
            ("rebind keys", "Tab"),
            ("safe zone setup", "Z"),
            ("CHANNELS", None),
            ("jump to channel", "type any number  (auto-enters after 1.5s)"),
            ("DURING PLAYBACK", None),
            ("volume up / down", f"{key_display_name(km.get('up', DEFAULT_KEYMAP['up']))}/{key_display_name(km.get('down', DEFAULT_KEYMAP['down']))}"),
            ("seek +/-10s", f"{key_display_name(km.get('left', DEFAULT_KEYMAP['left']))}/{key_display_name(km.get('right', DEFAULT_KEYMAP['right']))}"),
            ("pause / stop", "Space or Enter / Esc"),
        ]
        if self._gamepad_count > 0:
            lines.append(("GAMEPAD", None))
            lines.append(
                ("navigate", "D-pad / left stick"),
            )
            lines.append(
                ("select / back", "A / B  (or Start / Back)"),
            )

        section_gap = 20

        while self.running:
            for event in pygame.event.get():
                if self._handle_window_event(event):
                    continue
                if event.type == pygame.QUIT:
                    self.running = False
                    return
                if event.type == pygame.KEYDOWN:
                    return  # Any key dismisses

            elapsed = pygame.time.get_ticks() - start
            if elapsed >= duration:
                return

            remaining = max(0, (duration - elapsed) // 1000)

            with self._ui_layout(letterbox=True):
                splash = self._splash_layout(lines, section_gap)
                footer_hint_y = splash["footer_hint_y"]
                divider_y = splash["divider_y"]
                content_region_bottom = splash["content_region_bottom"]
                y_start = splash["y_start"]

                self.screen.fill(C.BG)

                # Title
                title = self.font_lg.render("TV TIME CAPSULE", True, C.BRIGHT)
                self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=28))

                # Divider under title
                pygame.draw.line(self.screen, C.BLUE, (40, 56), (self.sw - 40, 56), 1)

                # Control lines — vertically centered in the region below the title
                y = y_start
                content_max_y = content_region_bottom
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
                            self.screen.blit(dt, (max(20, self.sw - dt.get_width() - 70), y))
                            y += dt.get_height() + 3
                        else:
                            self.screen.blit(lt, (left_x, y))
                            self.screen.blit(dt, (right_x, y))
                            y += row_h

                # Divider above footer — below content, not through it
                pygame.draw.line(self.screen, C.BLUE, (40, divider_y), (self.sw - 40, divider_y), 1)

                # Countdown + dismiss hint
                hint = self.font_sm.render(f"Press any key to continue...  {remaining}s", True, C.DIM)
                self.screen.blit(hint, hint.get_rect(centerx=self.sw // 2, centery=footer_hint_y))

                self._apply_scanlines()
            self.present()
            self.clock.tick(15)

    # ─── Now-playing splash ──────────────────────────────────────────────

    def draw_now_playing(self, show, season, episode, channel, resume_secs=None):
        """Splash screen before video plays. Green accent."""
        if not self._now_playing_splash or self._now_playing_splash_ms <= 0:
            return

        on_extended = (self.canvas_w, self.canvas_h) != (SCREEN_W, SCREEN_H)
        with self._ui_layout(letterbox=True, enabled=on_extended):
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

    # ─── Key configuration ────────────────────────────────────────────────

    def _key_to_browse_action(self, key):
        """Map a pygame key code to a browse action, or None."""
        km = self.keymap
        if key == km.get("up", pygame.K_UP):
            return "up"
        if key == km.get("down", pygame.K_DOWN):
            return "down"
        if key == km.get("select", pygame.K_RETURN) or key == km.get("right", pygame.K_RIGHT):
            return "select"
        if key == km.get("left", pygame.K_LEFT):
            return "left"
        if key == km.get("back", pygame.K_ESCAPE):
            return "back"
        return None

    def _key_to_playback_action(self, key):
        """Map a pygame key code to a playback action, or None."""
        km = self.keymap
        if key == km.get("back", pygame.K_ESCAPE):
            return "back"
        if key == km.get("up", pygame.K_UP):
            return "up"
        if key == km.get("down", pygame.K_DOWN):
            return "down"
        if key == km.get("right", pygame.K_RIGHT):
            return "right"
        if key == km.get("left", pygame.K_LEFT):
            return "left"
        if key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
            return "select"
        if key == km.get("select", pygame.K_RETURN):
            return "select"
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

            self._apply_scanlines()

    def _set_confirm_exit_choice(self, yes: bool) -> None:
        self._confirm_exit_yes = bool(yes)

    def _activate_confirm_exit_choice(self) -> None:
        if self._confirm_exit_yes:
            self.running = False
        else:
            self.view = self.SHOW_LIST

    def _process_confirm_exit_action(self, action: str) -> None:
        # Yes is on the left, No on the right.
        if action in ("left", "up"):
            self._set_confirm_exit_choice(True)
        elif action in ("right", "down"):
            self._set_confirm_exit_choice(False)
        elif action == "select":
            self._activate_confirm_exit_choice()
        elif action == "back":
            self.view = self.SHOW_LIST

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

        if self._safe_zone_save_prompt:
            hint = self.font_sm.render(
                "Save changes?  \u2190 Yes   \u2192 No   Enter confirm   Esc cancel",
                True,
                C.DIM,
            )
        elif zoom_active:
            hint = self.font_sm.render(
                "ZOOM: \u2191\u2193 vertical margins   \u2190\u2192 horizontal"
                "   Enter: position mode   Esc: save",
                True,
                C.DIM,
            )
        else:
            hint = self.font_sm.render(
                "POSITION: arrows move inset   Enter: zoom mode   Esc: save",
                True,
                C.DIM,
            )
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

            if capturing:
                hint = self.font_md.render("Press a key...  (Esc cancels)", True, C.GREEN)
            else:
                hint = self.font_sm.render("ENTER assign  |  ESC done  |  TAB reset", True, C.DIM)
            self.screen.blit(hint, hint.get_rect(centerx=self.sw // 2, centery=82))

            y_start = 118
            row_h = 44
            label_x = 50
            right_pad = 50
            col_gap = 16
            row_font = self.font_sm

            for i, (action_id, action_label) in enumerate(KEY_ACTIONS):
                y = y_start + i * row_h
                if y + row_h > self.sh - 30:
                    break

                selected = (i == self.config_cursor)

                bar_rect = pygame.Rect(30, y, self.sw - 60, row_h - 6)
                if selected:
                    pygame.draw.rect(self.screen, C.BG_CARD_SEL, bar_rect, border_radius=6)
                    pygame.draw.rect(self.screen, C.CYAN, bar_rect.inflate(2, 2), 2, border_radius=7)
                else:
                    pygame.draw.rect(self.screen, C.BG_CARD, bar_rect, border_radius=6)

                bound_key = self.keymap.get(action_id, DEFAULT_KEYMAP.get(action_id))
                key_name = key_display_name(bound_key)
                label_color = C.BRIGHT if selected else C.WHITE
                key_color = C.BRIGHT if selected else C.DIM

                if capturing and selected:
                    if (pygame.time.get_ticks() // 500) % 2 == 0:
                        key_surf = row_font.render("_", True, C.GREEN)
                    else:
                        key_surf = row_font.render("-", True, C.GREEN)
                else:
                    key_surf = row_font.render(key_name, True, key_color)

                key_x = self.sw - right_pad - key_surf.get_width()
                label_max_w = max(20, key_x - label_x - col_gap)
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
                self.screen.blit(
                    key_surf,
                    (key_x, y + (row_h - key_surf.get_height()) // 2 - 3),
                )

            self._apply_scanlines()
        self.present()

    def enter_key_config(self):
        self.view = self.KEY_CONFIG
        self.config_cursor = 0

    def exit_key_config(self):
        self.view = self.SHOW_LIST
        self.cursor = 0

    def reset_keymap(self):
        self.keymap = dict(DEFAULT_KEYMAP)
        self.config["keymap"] = {}
        save_config(self.config)

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
        else:
            return

        if changed:
            self.channel_error = label
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
        if self.view in (self.SEASON_SELECT, self.EPISODE_SELECT):
            self._move_cursor_stack(direction, total)
            return
        # Clamp (no wrap) on the show browser.
        new_cursor = max(0, min(total - 1, self.cursor + direction))
        if new_cursor != self.cursor:
            self.cursor = new_cursor
            self._marquee_key = None  # restart marquee delay on the new row

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
        if self.view == self.SHOW_LIST and self._show_list_test_pattern:
            return
        items = self.current_items()
        if not items or self.cursor >= len(items):
            return

        if self.view == self.SHOW_LIST:
            self.cur_show = self.show_names[self.cursor]
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
                resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
                pos_ep, _ = get_episode_position(
                    self.state, self.cur_show, self.cur_season
                )
                eps = show['seasons'][self.cur_season]['episodes']
                self.cursor = self._next_up_index(eps, resume, pos_ep=pos_ep)

        elif self.view == self.SEASON_SELECT:
            seasons = self.seasons_for_show(self.cur_show)
            if self.cursor < len(seasons):
                self.cur_season = seasons[self.cursor]
                self.view = self.EPISODE_SELECT
                self.cursor = 0
                resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
                pos_ep, _ = get_episode_position(
                    self.state, self.cur_show, self.cur_season
                )
                eps = self.shows[self.cur_show]['seasons'][self.cur_season]['episodes']
                self.cursor = self._next_up_index(eps, resume, pos_ep=pos_ep)

        elif self.view == self.EPISODE_SELECT:
            self.play_from_cursor()

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
        # On SHOW_LIST, left arrow does nothing — use Escape to quit

    def jump_to_channel(self, channel_num):
        if self.view == self.SHOW_LIST:
            show_name = show_at_channel(self._channel_show, channel_num)
            if show_name and show_name in self.show_names:
                self._clear_show_list_test_pattern()
                idx = self.show_names.index(show_name)

                def apply():
                    self.cursor = idx
                    self.select()

                self._channel_tune(apply)
                return True
            if len(self.show_names) == 0:
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
                    self.select()

                self._channel_tune(apply)
                return True
            else:
                self.channel_error = f"Episode {channel_num} Not Found"
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
            self.font_md.render("Enter retry  |  Esc back", True, C.DIM), scale
        )
        cx = rect.x + rect.w // 2
        cy = rect.y + rect.h // 2
        self.screen.blit(title, title.get_rect(center=(cx, cy - 24)))
        self.screen.blit(hint, hint.get_rect(center=(cx, cy + 20)))

    def _start_current_episode(self, *, resume_secs=None, show_splash=True):
        """Start ``playing_episodes[playing_index]``. Returns True on success."""
        episode = self.playing_episodes[self.playing_index]
        self.playing_episode = episode
        self.view = self.PLAYING

        splash_args = (
            self.playing_show,
            self.playing_season,
            episode,
            self.playing_index + 1,
            resume_secs,
        )
        if show_splash and self._now_playing_splash and self._now_playing_splash_ms > 0:
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
            self.view = self.EPISODE_SELECT
            return False

        if not self.player.start(episode["path"], resume_pos=resume_secs):
            self.player = None
            self._exit_playback_display()
            self.channel_error = "PLAY FAILED"
            self.channel_error_time = pygame.time.get_ticks()
            self.view = self.EPISODE_SELECT
            return False

        pygame.event.clear()
        self._play_input_grace_until = pygame.time.get_ticks() + PLAY_INPUT_GRACE_MS
        self.progress_overlay_timer = 0
        self.volume_overlay_timer = 0
        self._playback_stalled = False
        self._stall_auto_retry_done = False
        return True

    def _resolve_autoplay_target(self):
        """Return (episodes, index, season) for autoplay, or None."""
        if self._autoplay_mode == "off":
            return None

        next_idx = self.playing_index + 1
        if next_idx < len(self.playing_episodes):
            return self.playing_episodes, next_idx, self.playing_season

        if self._autoplay_mode != "next_episode":
            return None

        seasons = self.seasons_for_show(self.playing_show)
        try:
            si = seasons.index(self.playing_season)
        except ValueError:
            return None
        if si + 1 >= len(seasons):
            return None
        next_season = seasons[si + 1]
        eps = self.shows[self.playing_show]["seasons"][next_season]["episodes"]
        if not eps:
            return None
        return eps, 0, next_season

    def _draw_up_next_splash(self, episode, season, channel, seconds_left):
        self.screen.fill(C.BLACK)
        rect, scale = self._playback_overlay_layout()
        pad = HUD_PAD

        title = self._scale_overlay_surface(
            self.font_lg.render("UP NEXT", True, C.GREEN), scale
        )
        title_y = rect.y + 40
        self.screen.blit(title, title.get_rect(centerx=rect.x + rect.w // 2, centery=title_y))

        ep_num = episode["number"]
        ep_name = episode.get("name") or ""
        label = f"S-{season:02d} - E-{ep_num:02d}"
        s = self._scale_overlay_surface(self.font_md.render(label, True, C.WHITE), scale)
        mid_y = rect.y + rect.h // 2
        self.screen.blit(s, s.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y - 30))
        if ep_name:
            n = self._truncate_overlay_text(
                ep_name, self.font_md, C.BLUE, rect.w - pad * 2, scale=scale
            )
            self.screen.blit(n, n.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y + 10))

        ch = self._scale_overlay_surface(
            self.font_lg.render(str(channel), True, C.GREEN), scale
        )
        self.screen.blit(
            ch,
            (rect.x + rect.w - ch.get_width() - pad, rect.y + pad),
        )

        show = self._truncate_overlay_text(
            self.playing_show.upper(), self.font_md, C.DIM, rect.w - pad * 2, scale=scale
        )
        self.screen.blit(show, show.get_rect(centerx=rect.x + rect.w // 2, centery=mid_y + 55))

        hint = self._scale_overlay_surface(
            self.font_sm.render(
                f"Starting in {seconds_left}s  -  Esc to cancel", True, C.DIM
            ),
            scale,
        )
        hint_y = rect.y + rect.h - 40
        self.screen.blit(hint, hint.get_rect(centerx=rect.x + rect.w // 2, centery=hint_y))
        self._apply_scanlines()

    def _run_up_next_countdown(self, episode, season, channel):
        """Countdown before autoplay. Returns True to continue, False if cancelled."""
        total = self._autoplay_countdown
        if total <= 0:
            return True

        start = pygame.time.get_ticks()
        duration_ms = total * 1000
        km = self.keymap

        while self.running:
            for event in pygame.event.get():
                if self._handle_window_event(event):
                    continue
                if event.type == pygame.QUIT:
                    self.running = False
                    return False
                if event.type == pygame.KEYDOWN:
                    if event.key == km.get("back", pygame.K_ESCAPE):
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

        if not self._start_current_episode(resume_secs=resume_secs, show_splash=True):
            self.stop_playback(completed=True)

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
            if self.view == self.SHOW_LIST:
                if self._show_list_test_pattern:
                    self._clear_show_list_test_pattern()
                else:
                    self._confirm_exit_yes = False
                    self.view = self.CONFIRM_EXIT
            else:
                self.go_back()

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

    def _next_up_index(self, episodes, resume, pos_ep=None):
        """Index of the in-progress episode, else first uncompleted, else last."""
        if pos_ep is not None:
            for i, e in enumerate(episodes):
                if e["number"] == pos_ep:
                    return i
        for i, e in enumerate(episodes):
            if e['number'] > resume:
                return i
        return max(0, len(episodes) - 1)

    def _mark_completed(self):
        """Record that the currently-playing episode finished.
        Drives both resume position and the 'watched' marks."""
        ep = self.playing_episode
        if ep is None:
            return
        prev = get_resume_ep(self.state, self.playing_show, self.playing_season)
        set_resume_ep(self.state, self.playing_show, self.playing_season,
                      max(prev, ep['number']))

    def stop_playback(self, *, completed=False):
        """Stop playback and return to episode list.

        On early stop, bookmark the in-episode position so Play resumes there.
        """
        ep = self.playing_episode
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

        # Land on the in-progress episode if any, otherwise next-up.
        resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
        pos_ep, _pos = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        episodes = (self.shows.get(self.cur_show, {})
                    .get('seasons', {}).get(self.cur_season, {})
                    .get('episodes', []))
        if episodes:
            self.cursor = self._next_up_index(episodes, resume, pos_ep=pos_ep)

        self.view = self.EPISODE_SELECT
        self._exit_playback_display()

    # ─── Main loop ─────────────────────────────────────────────────────────

    def _touch_activity(self):
        """Reset idle timer; leave screensaver on input."""
        self._last_activity_ms = pygame.time.get_ticks()
        self._screensaver_active = False

    def _screensaver_idle_views(self):
        return self.view not in (
            self.PLAYING,
            self.KEY_CONFIG,
            self.KEY_CAPTURE,
            self.CONFIRM_EXIT,
            self.SAFE_ZONE_EDIT,
        )

    def _enter_screensaver(self):
        if not self._screensaver_enabled or not VHS_LOGO_PATH.is_file():
            return
        if self._screensaver is None:
            try:
                self._screensaver = VHSScreensaver(self.sw, self.sh)
            except FileNotFoundError:
                self._screensaver_enabled = False
                return
        self._screensaver.randomize_color()
        self._screensaver_active = True

    def _tick_screensaver(self):
        dt = max(self.clock.get_time(), 1) / 1000.0
        if self._screensaver.update(dt):
            self._screensaver.randomize_color()
        with self._ui_layout(letterbox=True):
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

        if self._scanlines_override is None:
            self.scanlines = bool(ui_cfg.get("scanlines", False))
            if not self.scanlines:
                self._scanline_surf = None

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

        gp_cfg = self.config.get("gamepad") or {}
        self._gamepad.enabled = bool(gp_cfg.get("enabled", True))

        lib_cfg = self.config.get("library") or {}
        self._rescan_interval_ms = int(lib_cfg.get("rescan_interval_seconds", 0)) * 1000
        self._rescan_long_press_ms = int(lib_cfg.get("rescan_long_press_ms", 800))

        paths = effective_media_paths(self.config)
        if paths:
            self.media_paths = paths

        self.keymap = load_keymap(self.config)
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
            self.SHOW_LIST: "show_list",
            self.SEASON_SELECT: "season_select",
            self.EPISODE_SELECT: "episode_select",
            self.PLAYING: "playing",
        }
        return {
            "shows": len(self.show_names),
            "view": view_names.get(self.view, "other"),
            "playing": self.view == self.PLAYING,
            "current_show": self.cur_show,
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
        return {"bindings": keymap_for_display(self.keymap)}

    def admin_library(self) -> dict:
        summary = library_summary(self.shows)
        return {
            **summary,
            "tree": library_tree_from_shows(self.shows),
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
            "scanlines": self.scanlines,
            "analog_artifacts": self._analog_artifacts.enabled,
            "analog_artifact_rate": self._analog_artifacts.rate_per_minute,
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
                "scanlines": self._scanlines_override is not None,
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
        if "scanlines" in patch and self._scanlines_override is None:
            ui_cfg["scanlines"] = bool(patch["scanlines"])
        if "analog_artifacts" in patch and self._analog_artifacts_override is None:
            ui_cfg["analog_artifacts"] = bool(patch["analog_artifacts"])
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
            self.shows = discover_shows(scan_list)
            self._apply_channel_lineup()
            self._duration_cache.clear()
            self._img_cache.clear()
            self._img_cache_order.clear()
            summary = library_summary(self.shows)
            result.update(summary)
            result["tree"] = library_tree_from_shows(self.shows)
            result["applied"] = True
            result["message"] = (
                f"Applied: {summary['shows']} show(s), {summary['episodes']} episode(s)"
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

    def run(self):
        # Show controls splash on startup
        self.draw_splash()
        self._last_activity_ms = pygame.time.get_ticks()

        while self.running:
            # ═══════════════════════════════════════════════════════════════════
            # PLAYBACK MODE: embedded video rendering
            # ═══════════════════════════════════════════════════════════════════
            if self.view == self.PLAYING:
                if self._playback_stalled:
                    for event in pygame.event.get():
                        if self._handle_window_event(event):
                            continue
                        if event.type == pygame.QUIT:
                            self.running = False
                            break
                        action = None
                        if event.type == pygame.KEYDOWN:
                            self._touch_activity()
                            action = self._key_to_playback_action(event.key)
                        else:
                            action = self._gamepad.event_to_action(event)
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

                for event in pygame.event.get():
                    if self._handle_window_event(event):
                        continue
                    if event.type == pygame.QUIT:
                        self.stop_playback()
                        self.running = False
                        break
                    action = None
                    if event.type == pygame.KEYDOWN:
                        self._touch_activity()
                        action = self._key_to_playback_action(event.key)
                    else:
                        action = self._gamepad.event_to_action(event)
                        if action:
                            self._touch_activity()
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
                        self.running = False
                    elif event.type == pygame.KEYDOWN:
                        self._touch_activity()
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
                    self.running = False

                elif event.type == pygame.KEYDOWN:
                    self._touch_activity()
                    if self.view == self.KEY_CAPTURE:
                        if event.key == pygame.K_ESCAPE:
                            self.view = self.KEY_CONFIG
                            continue
                        if event.key == pygame.K_TAB:
                            continue
                        action_id = KEY_ACTIONS[self.config_cursor][0]
                        self.keymap[action_id] = event.key
                        self.config["keymap"] = {k: v for k, v in self.keymap.items()}
                        save_config(self.config)
                        self.view = self.KEY_CONFIG
                        continue

                    elif self.view == self.KEY_CONFIG:
                        if event.key == pygame.K_ESCAPE:
                            self.exit_key_config()
                        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.view = self.KEY_CAPTURE
                        elif event.key == pygame.K_UP:
                            self.config_cursor = (self.config_cursor - 1) % len(KEY_ACTIONS)
                        elif event.key == pygame.K_DOWN:
                            self.config_cursor = (self.config_cursor + 1) % len(KEY_ACTIONS)
                        elif event.key == pygame.K_TAB:
                            self.reset_keymap()
                        continue

                    elif self.view == self.CONFIRM_EXIT:
                        km = self.keymap
                        left = km.get("left", pygame.K_LEFT)
                        right = km.get("right", pygame.K_RIGHT)
                        up = km.get("up", pygame.K_UP)
                        down = km.get("down", pygame.K_DOWN)
                        if event.key == pygame.K_ESCAPE or event.key == km.get(
                            "back", pygame.K_ESCAPE
                        ):
                            self.view = self.SHOW_LIST
                        elif event.key in (left, pygame.K_LEFT):
                            self._set_confirm_exit_choice(True)
                        elif event.key in (right, pygame.K_RIGHT):
                            self._set_confirm_exit_choice(False)
                        elif event.key in (up, pygame.K_UP, down, pygame.K_DOWN):
                            self._confirm_exit_yes = not self._confirm_exit_yes
                        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self._activate_confirm_exit_choice()
                        continue

                    elif self.view == self.SAFE_ZONE_EDIT:
                        km = self.keymap
                        left = km.get("left", pygame.K_LEFT)
                        right = km.get("right", pygame.K_RIGHT)
                        up = km.get("up", pygame.K_UP)
                        down = km.get("down", pygame.K_DOWN)
                        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            if self._safe_zone_save_prompt:
                                self.exit_safe_zone_editor(save=self._safe_zone_save_yes)
                            else:
                                self._toggle_safe_zone_edit_mode()
                        elif event.key == pygame.K_ESCAPE or event.key == km.get(
                            "back", pygame.K_ESCAPE
                        ):
                            if self._safe_zone_save_prompt:
                                self._safe_zone_save_prompt = False
                            else:
                                self._safe_zone_save_prompt = True
                                self._safe_zone_save_yes = True
                        elif self._safe_zone_save_prompt:
                            if event.key in (left, pygame.K_LEFT, up, pygame.K_UP):
                                self._safe_zone_save_yes = True
                            elif event.key in (right, pygame.K_RIGHT, down, pygame.K_DOWN):
                                self._safe_zone_save_yes = False
                        elif event.key in (up, pygame.K_UP):
                            self._adjust_safe_zone_edit("up")
                        elif event.key in (down, pygame.K_DOWN):
                            self._adjust_safe_zone_edit("down")
                        elif event.key in (left, pygame.K_LEFT):
                            self._adjust_safe_zone_edit("left")
                        elif event.key in (right, pygame.K_RIGHT):
                            self._adjust_safe_zone_edit("right")
                        continue

                    if pygame.K_0 <= event.key <= pygame.K_9 or pygame.K_KP0 <= event.key <= pygame.K_KP9:
                        if pygame.K_0 <= event.key <= pygame.K_9:
                            digit = event.key - pygame.K_0
                        else:
                            digit = event.key - pygame.K_KP0

                        self.channel_digits += str(digit)
                        self.channel_timer = pygame.time.get_ticks()
                        continue

                    if self.channel_digits:
                        self.channel_digits = ""
                        self.channel_timer = 0

                    if event.key == pygame.K_TAB:
                        self.enter_key_config()
                        continue

                    if event.key == pygame.K_z:
                        self.enter_safe_zone_editor()
                        continue

                    if event.key == pygame.K_h:
                        self.draw_splash()
                        continue

                    if event.key == pygame.K_q:
                        self.running = False
                        continue

                    reset_key = self.keymap.get("reset", DEFAULT_KEYMAP["reset"])
                    if event.key == reset_key:
                        self._reset_hold_start = pygame.time.get_ticks()
                        self._reset_rescan_fired = False
                        continue

                    action = self._key_to_browse_action(event.key)
                    if action:
                        self._process_browse_action(action)

                elif event.type == pygame.KEYUP:
                    reset_key = self.keymap.get("reset", DEFAULT_KEYMAP["reset"])
                    if event.key == reset_key:
                        if self._reset_hold_start and not self._reset_rescan_fired:
                            self.reset_watch_status()
                        self._reset_hold_start = 0
                        self._reset_rescan_fired = False

                elif event.type in (
                    pygame.JOYBUTTONDOWN,
                    pygame.JOYHATMOTION,
                    pygame.JOYAXISMOTION,
                ):
                    action = self._gamepad.event_to_action(event)
                    if not action:
                        continue
                    self._touch_activity()
                    if self.view == self.CONFIRM_EXIT:
                        self._process_confirm_exit_action(action)
                        continue
                    if self.view == self.SAFE_ZONE_EDIT:
                        self._process_safe_zone_edit_action(action)
                        continue
                    if self.view in (self.KEY_CONFIG, self.KEY_CAPTURE):
                        if action == "back" and self.view == self.KEY_CONFIG:
                            self.exit_key_config()
                        continue
                    self._process_browse_action(action)

            # Channel timeout — first highlight, then auto-select after delay
            if self.channel_digits and self.channel_timer > 0:
                now = pygame.time.get_ticks()
                if now - self.channel_timer >= CHANNEL_TIMEOUT_MS:
                    digits = self.channel_digits
                    if self.view == self.SHOW_LIST and is_show_list_test_dial(digits):
                        if self._commit_show_list_test_pattern(digits):
                            self.channel_flash = digits
                            self.channel_flash_time = now
                    elif digits:
                        if self._show_list_test_pattern:
                            self._clear_show_list_test_pattern()
                        channel = int(digits)
                        if channel > 0:
                            success = self.jump_to_channel(channel)
                            if success:
                                self.channel_flash = digits
                                self.channel_flash_time = now
                    self.channel_digits = ""
                    self.channel_timer = 0

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
            else:
                self.draw()
                self.present()
            self.clock.tick(30)

        # Clean up any active player
        shutdown_snapshot = None
        if self._channel_fx.shutdown_enabled:
            shutdown_snapshot = self.screen.copy()
        if self.player:
            self.player.stop()
        if shutdown_snapshot is not None:
            self._channel_fx.play_shutdown(
                self.screen,
                shutdown_snapshot,
                self._shutdown_viewport(),
                after_frame=self.present,
            )
        if self._admin_server:
            self._admin_server.stop()
        pygame.quit()

