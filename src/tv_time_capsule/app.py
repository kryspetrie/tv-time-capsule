"""Main pygame application UI and event loop."""

from __future__ import annotations

import os
import subprocess
import warnings

import pygame

from .config import (
    C,
    CHANNEL_ERROR_MS,
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
)
from .fonts import enable_freetype_fallback, make_font
from .keymap import KEY_ACTIONS, DEFAULT_KEYMAP, key_display_name, load_keymap
from .media import discover_shows
from .player import (
    EmbeddedPlayer,
    detect_ffmpeg,
    detect_ffplay,
    detect_omxplayer,
    is_pi,
    np_frombuffer,
)
from .state import (
    clear_resume_ep,
    get_episode_position,
    get_resume_ep,
    load_state,
    save_state,
    set_episode_position,
    set_resume_ep,
)


class TVTimeCapsule:
    SHOW_LIST = 0
    SEASON_SELECT = 1
    EPISODE_SELECT = 2
    KEY_CONFIG = 3
    KEY_CAPTURE = 4
    PLAYING = 5
    CONFIRM_EXIT = 6

    def __init__(self, media_paths, fullscreen=True, force_43=False, scanlines=False):
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
        self.scanlines = scanlines

        # Logical canvas — all UI/video is drawn at this size. SCALED asks SDL
        # to GPU-scale it to the real window/desktop, which avoids a per-frame
        # CPU transform.scale up to 4K.
        self.canvas_w = SCREEN_W
        self.canvas_h = SCREEN_H
        self.sw = self.canvas_w
        self.sh = self.canvas_h

        flags = pygame.SCALED
        if fullscreen:
            # SCALED + FULLSCREEN → fullscreen-desktop (no mode set). Passing
            # the logical size (not the desktop size) is what enables GPU
            # upscaling; a desktop-sized SCALED surface would still force us
            # to CPU-scale the canvas ourselves.
            flags |= pygame.FULLSCREEN
        try:
            self.display = pygame.display.set_mode(
                (self.canvas_w, self.canvas_h), flags, vsync=1
            )
        except TypeError:
            # Older pygame without vsync kwarg
            self.display = pygame.display.set_mode(
                (self.canvas_w, self.canvas_h), flags
            )

        self.real_w, self.real_h = pygame.display.get_window_size()
        # With a logical SCALED surface, SDL letterboxes to preserve 4:3.
        # Viewport is identity in logical coords; no CPU pillarboxing needed.
        self.viewport_w = self.canvas_w
        self.viewport_h = self.canvas_h
        self.viewport_x = 0
        self.viewport_y = 0

        # Draw directly to the display surface. Keep a SRCALPHA offscreen
        # canvas only for the legacy omxplayer overlay path (Pi), where the
        # hardware video layer must show through transparent pixels.
        self._omx_overlay = False
        self.canvas = None
        self.screen = self.display

        pygame.display.set_caption("TV Time Capsule")
        pygame.mouse.set_visible(not fullscreen)

        # Detect video player
        ffmpeg_path = detect_ffmpeg()
        ffplay_path = detect_ffplay()
        omx_cmd = detect_omxplayer() if is_pi() else None

        if ffmpeg_path and np_frombuffer is not None:
            # Embedded FFmpeg playback (preferred)
            self.player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
            self.player.ffmpeg_path = ffmpeg_path
            self.player.ffplay_path = ffplay_path
            self.player_cmd = ffmpeg_path
            self.embedded_player = True
        elif omx_cmd:
            # Omxplayer fallback on Pi — transparent overlay canvas
            self._enable_omx_overlay()
            self.player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
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

        self.media_paths = media_paths if isinstance(media_paths, list) else [media_paths]
        self.state = load_state()
        self.keymap = load_keymap(self.state)
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
        self.channel_pending = 0
        self.channel_pending_time = 0

        # Playback state
        self.playing_show = None
        self.playing_season = None
        self.playing_episode = None
        self.playing_episodes = []
        self.playing_index = 0
        self.volume_overlay_timer = 0
        self.progress_overlay_timer = 0

        self.shows = discover_shows(self.media_paths)
        self.show_names = sorted(self.shows.keys())
        self.cur_show = None
        self.cur_season = None

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

    # ─── Scanline overlay ────────────────────────────────────────────────

    def _make_scanlines(self):
        """Create a semi-transparent scanline overlay for CRT effect."""
        surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        for y in range(0, SCREEN_H, 3):
            pygame.draw.line(surf, C.SCANLINE, (0, y), (SCREEN_W, y))
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
        """Use a transparent offscreen canvas so omxplayer's layer shows through."""
        self._omx_overlay = True
        self.canvas = pygame.Surface((self.canvas_w, self.canvas_h), pygame.SRCALPHA)
        self.screen = self.canvas

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
        """Push the logical frame to the display. SCALED handles GPU upscaling."""
        if self._omx_overlay and self.canvas is not None:
            # Do not fill black — that would cover the hardware video layer.
            self.display.blit(self.canvas, (0, 0))
        pygame.display.flip()

    def _apply_scanlines(self):
        """Overlay CRT scanlines on the current frame (if enabled)."""
        if self.scanlines:
            if self._scanline_surf is None:
                self._scanline_surf = self._make_scanlines()
            self.screen.blit(self._scanline_surf, (0, 0))

    def _draw_footer(self, text):
        """Draw a consistent footer bar at the bottom of the screen."""
        bar_h = 34
        fy = self.sh - bar_h
        pygame.draw.rect(self.screen, C.BG_FOOTER, (0, fy, self.sw, bar_h))
        pygame.draw.line(self.screen, C.BLUE, (0, fy), (self.sw, fy), 1)
        # Truncate if text is too wide for the screen
        max_w = self.sw - 32
        t = self.font_sm.render(text, True, C.DIM)
        if t.get_width() > max_w:
            while self.font_sm.size(text + "...")[0] > max_w and len(text) > 3:
                text = text[:-1]
            t = self.font_sm.render(text + "...", True, C.DIM)
        self.screen.blit(t, t.get_rect(centerx=self.sw // 2, centery=fy + bar_h // 2))

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

    def seasons_for_show(self, show):
        return sorted(self.shows.get(show, {}).get('seasons', {}).keys())

    def current_items(self):
        if self.view == self.SHOW_LIST:
            return [{'name': n, 'data': self.shows[n]} for n in self.show_names]
        elif self.view == self.SEASON_SELECT:
            show = self.shows.get(self.cur_show, {})
            seasons = sorted(show.get('seasons', {}).keys())
            return [{'name': f'Season {s}', 'number': s,
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
        if self.view == self.SHOW_LIST:
            self.draw_show_browser()
        elif self.view == self.SEASON_SELECT:
            self.draw_season_browser()
        elif self.view == self.EPISODE_SELECT:
            self.draw_episode_browser()
        self.draw_channel_overlay()

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

                err_surf = self.font_lg.render(self.channel_error, True, C.GREEN)
                box_w = err_surf.get_width() + 60
                box_h = err_surf.get_height() + 30
                box_x = (self.sw - box_w) // 2
                box_y = self.sh // 2 - box_h // 2

                bg_surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
                bg_surf.fill((0, 10, 5, min(220, alpha)))
                pygame.draw.rect(bg_surf, (*C.GREEN[:3], min(alpha, 200)),
                                 (0, 0, box_w, box_h), 2, border_radius=6)
                self.screen.blit(bg_surf, (box_x, box_y))

                if alpha < 255:
                    err_surf.set_alpha(alpha)
                self.screen.blit(err_surf,
                                (box_x + (box_w - err_surf.get_width()) // 2,
                                 box_y + (box_h - err_surf.get_height()) // 2))
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

        idx = self.cursor % len(shows)
        show_name = shows[idx]
        show_data = self.shows[show_name]
        ch_num = idx + 1

        # ── Header ──
        header_h = self._draw_header(show_name.upper(), ch_num=ch_num)

        # ── Up navigation bar (full width) ──
        nav_h = 28
        up_y = header_h
        if idx > 0:
            up_name = shows[idx - 1].upper()
            pygame.draw.rect(self.screen, C.BG_CARD, (0, up_y, self.sw, nav_h))
            up_surf = self.font_sm.render(f"\u25b2  {up_name}", True, C.CYAN)
            self.screen.blit(up_surf, up_surf.get_rect(left=16, centery=up_y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, (14, 20, 35), (0, up_y, self.sw, nav_h))
        pygame.draw.line(self.screen, (25, 40, 70), (0, up_y + nav_h), (self.sw, up_y + nav_h), 1)

        # ── Content area ──
        footer_h = 30
        content_y = up_y + nav_h + 4
        content_bottom = self.sh - footer_h - nav_h - 4
        content_h = content_bottom - content_y
        if content_h < 40:
            content_h = 40

        # ── Down navigation bar (full width) ──
        down_y = content_bottom
        if idx < len(shows) - 1:
            down_name = shows[idx + 1].upper()
            pygame.draw.rect(self.screen, C.BG_CARD, (0, down_y, self.sw, nav_h))
            down_surf = self.font_sm.render(f"\u25bc  {down_name}", True, C.CYAN)
            self.screen.blit(down_surf, down_surf.get_rect(left=16, centery=down_y + nav_h // 2))
        else:
            pygame.draw.rect(self.screen, (14, 20, 35), (0, down_y, self.sw, nav_h))
        pygame.draw.line(self.screen, (25, 40, 70), (0, down_y), (self.sw, down_y), 1)

        # ── Central content: thumbnail or wrapped show title ──
        n_total = self._count_total_eps(show_data)
        seasons = self.seasons_for_show(show_name)
        if len(seasons) > 1:
            info = f"{len(seasons)} seasons - {n_total} episodes"
        else:
            info = f"{n_total} episodes"

        thumb = self.load_image(show_data.get('thumbnail'),
                                 (self.sw - 80, content_h - 40))
        if thumb:
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
        self._draw_footer("ENTER play  #ch  H help")
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
        header_h = self._draw_header(f"{self.cur_show.upper()}",
                                     ch_num=str(self.cursor + 1))

        # Stack area
        footer_h = 30
        stack_top = header_h + 10
        stack_bottom = self.sh - footer_h - 10
        stack_h = stack_bottom - stack_top
        item_h = min(70, (stack_h - (STACK_VISIBLE - 1) * 4) // STACK_VISIBLE)
        gap = 4

        first_visible = max(0, self.cursor - STACK_VISIBLE + 1)
        first_visible = min(first_visible, max(0, total - STACK_VISIBLE))

        # Up arrow
        if first_visible > 0:
            arr = self.font_sm.render("\u25b2 more above", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top - 2))

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

            # Season label
            s_label = f"Season {season_num}"
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

        # Down arrow
        if first_visible + STACK_VISIBLE < total:
            arr = self.font_sm.render("\u25bc more below", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top + STACK_VISIBLE * (item_h + gap)))

        # Footer
        self._draw_footer("Up/Dn >open <back #ch R=reset H")
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
        header_h = self._draw_header(
            f"{self.cur_show.upper()}  -  S-{self.cur_season:02d}",
            ch_num=str(self.cursor + 1))

        # Stack area
        footer_h = 30
        stack_top = header_h + 10
        stack_bottom = self.sh - footer_h - 10
        stack_h = stack_bottom - stack_top
        item_h = min(70, (stack_h - (STACK_VISIBLE - 1) * 4) // STACK_VISIBLE)
        gap = 4

        resume = get_resume_ep(self.state, self.cur_show, self.cur_season)
        pos_ep, pos_secs = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        next_up = next((e['number'] for e in episodes if e['number'] > resume), None)

        first_visible = max(0, self.cursor - STACK_VISIBLE + 1)
        first_visible = min(first_visible, max(0, total - STACK_VISIBLE))

        # Up arrow
        if first_visible > 0:
            arr = self.font_sm.render("\u25b2 more above", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top - 2))

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

        # Down arrow
        if first_visible + STACK_VISIBLE < total:
            arr = self.font_sm.render("\u25bc more below", True, C.DIM)
            self.screen.blit(arr, arr.get_rect(centerx=self.sw // 2, top=stack_top + STACK_VISIBLE * (item_h + gap)))

        # Footer
        self._draw_footer("Up/Dn >play <back #ch R=reset H")
        self._apply_scanlines()

    # ── Playback drawing (embedded video) ─────────────────────────────────

    def draw_playback(self):
        """Render video frame with overlays during playback.

        Embedded mode: video frame fills the canvas, overlays on top.
        Omxplayer mode: video renders on hardware layer — we draw
        transparent overlays only (no black fill).
        """
        if self.player and self.player.use_omx:
            # omxplayer renders on its own hardware layer — don't fill black
            pass
        else:
            self.screen.fill(C.BLACK)

        if self.player:
            frame = self.player.get_frame()
            if frame:
                # FFmpeg already scales/pads to canvas size — blit as-is.
                if frame.get_size() == (self.sw, self.sh):
                    self.screen.blit(frame, (0, 0))
                else:
                    scaled = pygame.transform.scale(frame, (self.sw, self.sh))
                    self.screen.blit(scaled, (0, 0))
            elif not self.player.use_omx:
                # No frame yet — show loading indicator
                t = self.font_md.render("Loading...", True, C.WHITE)
                self.screen.blit(t, t.get_rect(center=(self.sw // 2, self.sh // 2)))

        # Draw overlays on top of video
        self.draw_progress_overlay()
        self.draw_volume_overlay()
        self.draw_pause_overlay()

    # ─── Progress overlay (during playback) ─────────────────────────────────

    def draw_progress_overlay(self):
        """Progress bar overlay — top info bar + bottom scrub line.
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

        # Top bar: show/episode info + time
        bar_h = 44
        bar_surf = pygame.Surface((self.sw, bar_h), pygame.SRCALPHA)
        bar_surf.fill((0, 10, 5, min(200, fade)))
        self.screen.blit(bar_surf, (0, 0))

        ep = self.playing_episode or {}
        ep_num = ep.get('number', 0)
        ep_name = ep.get('name') or ''
        label = f"S-{self.playing_season or 1:02d} - E-{ep_num:02d}"
        if ep_name:
            label += f"  {ep_name}"
        lt = self.font_sm.render(label, True, C.GREEN)
        lt.set_alpha(fade)
        self.screen.blit(lt, (16, (bar_h - lt.get_height()) // 2))

        rt = self.font_sm.render(time_str, True, C.GREEN)
        rt.set_alpha(fade)
        self.screen.blit(rt, (self.sw - rt.get_width() - 16, (bar_h - rt.get_height()) // 2))

        # Bottom scrub bar
        bar_y = self.sh - 28
        bar_w = self.sw - 40
        bar_x = 20
        bar_h = 6

        # Track background
        track = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
        track.fill((20, 60, 35, min(220, fade)))
        self.screen.blit(track, (bar_x, bar_y))

        # Filled progress
        fill_w = max(1, int(bar_w * progress))
        fill = pygame.Surface((fill_w, bar_h), pygame.SRCALPHA)
        fill.fill((*C.GREEN[:3], min(255, fade)))
        self.screen.blit(fill, (bar_x, bar_y))

        # Playhead dot
        dot_x = bar_x + fill_w
        dot_y = bar_y + bar_h // 2
        dot_r = 7
        dot_surf = pygame.Surface((dot_r * 2, dot_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(dot_surf, (*C.BRIGHT, min(255, fade)), (dot_r, dot_r), dot_r)
        self.screen.blit(dot_surf, (dot_x - dot_r, dot_y - dot_r))

    # ─── Volume overlay ───────────────────────────────────────────────────

    def draw_volume_overlay(self):
        """Simple retro volume bar — upper-right corner, no background, no fade."""
        if not self.player:
            return

        now = pygame.time.get_ticks()
        elapsed = now - self.volume_overlay_timer

        if self.volume_overlay_timer <= 0 or elapsed >= OVERLAY_SHOW_MS:
            return

        vol = min(self.player.volume, 100)

        # "VOLUME [||||||||||]" — larger, upper-right corner
        label = self.font_md.render("VOLUME", True, C.GREEN)
        n_bars = 10
        bar_w = 12
        bar_h = 28
        bar_gap = 3
        filled = int(n_bars * vol / 100)

        total_bar_w = n_bars * bar_w + (n_bars - 1) * bar_gap
        total_w = label.get_width() + 16 + total_bar_w
        x = self.sw - total_w - 16
        y = 16

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

        # Static PAUSED text
        txt = self.font_lg.render("PAUSED", True, C.GREEN)
        self.screen.blit(txt, txt.get_rect(centerx=self.sw // 2, centery=self.sh // 2))

    # ─── Splash screen ────────────────────────────────────────────────────

    def draw_splash(self):
        """Show a 10-second controls splash screen. Dismissable by any key."""
        start = pygame.time.get_ticks()
        duration = 10000  # 10 seconds

        # Build control lines - ASCII only, no unicode arrows
        km = self.keymap
        lines = [
            ("NAVIGATION", None),
            ("browse shows", f"{key_display_name(km.get('up','Up'))}/{key_display_name(km.get('down','Down'))}  up / down"),
            ("enter / select", f"{key_display_name(km.get('right','Right'))} or {key_display_name(km.get('select','Enter'))}"),
            ("go back", f"{key_display_name(km.get('left','Left'))} or {key_display_name(km.get('back','Esc'))}"),
            ("", None),
            ("CHANNELS", None),
            ("jump to channel", "type any number  (auto-enters after 1.5s)"),
            ("", None),
            ("DURING PLAYBACK", None),
            ("volume up / down", f"{key_display_name(km.get('up','Up'))}/{key_display_name(km.get('down','Down'))}"),
            ("seek +/-10s", f"{key_display_name(km.get('left','Left'))}/{key_display_name(km.get('right','Right'))}"),
            ("pause / resume", "Space or Enter"),
            ("stop & return", f"{key_display_name(km.get('back','Esc'))}"),
            ("", None),
            ("SETTINGS", None),
            ("reset watch status", f"{key_display_name(km.get('reset','R'))}  (clear * / next-up marks)"),
            ("key configuration", "Tab"),
        ]

        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    return
                if event.type == pygame.KEYDOWN:
                    return  # Any key dismisses

            elapsed = pygame.time.get_ticks() - start
            if elapsed >= duration:
                return

            remaining = max(0, (duration - elapsed) // 1000)

            self.screen.fill(C.BG)

            # Title
            title = self.font_lg.render("TV TIME CAPSULE", True, C.BRIGHT)
            self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=40))

            # Divider under title
            pygame.draw.line(self.screen, C.BLUE, (40, 75), (self.sw - 40, 75), 1)

            # Control lines
            y = 92
            for label, detail in lines:
                if detail is None:
                    if label:
                        # Section header
                        hdr = self.font_md.render(label, True, C.CYAN)
                        self.screen.blit(hdr, (50, y))
                        y += hdr.get_height() + 2
                    else:
                        y += 8
                else:
                    # Key line: label on left, detail on right.
                    lt = self.font_sm.render(label, True, C.WHITE)
                    dt = self.font_sm.render(detail, True, C.GREEN)
                    max_y = self.sh - 80
                    if y + max(lt.get_height(), dt.get_height()) + 4 > max_y:
                        break
                    left_x = 70
                    right_x = self.sw - dt.get_width() - 70
                    if right_x < left_x + lt.get_width() + 20:
                        # Columns would collide — drop the detail to its own line
                        self.screen.blit(lt, (left_x, y + 2))
                        y += lt.get_height() + 2
                        if y + dt.get_height() + 4 > max_y:
                            break
                        self.screen.blit(dt, (max(20, self.sw - dt.get_width() - 70), y + 2))
                        y += dt.get_height() + 4
                    else:
                        self.screen.blit(lt, (left_x, y + 2))
                        self.screen.blit(dt, (right_x, y + 2))
                        y += max(lt.get_height(), dt.get_height()) + 4

            # Divider above footer
            pygame.draw.line(self.screen, C.BLUE, (40, self.sh - 70), (self.sw - 40, self.sh - 70), 1)

            # Countdown + dismiss hint
            hint = self.font_sm.render(f"Press any key to continue...  {remaining}s", True, C.DIM)
            self.screen.blit(hint, hint.get_rect(centerx=self.sw // 2, centery=self.sh - 35))

            self._apply_scanlines()
            self.present()
            self.clock.tick(15)

    # ─── Now-playing splash ──────────────────────────────────────────────

    def draw_now_playing(self, show, season, episode, channel, resume_secs=None):
        """Splash screen before video plays. Green accent."""
        self.screen.fill(C.BLACK)

        ep_num = episode['number']
        ep_name = episode.get('name') or ''

        # Channel number (green, upper right) — matches the episode page
        ch = str(channel)
        ch_surf = self.font_lg.render(ch, True, C.GREEN)
        self.screen.blit(ch_surf, (self.sw - ch_surf.get_width() - 40, 30))

        # Episode number (white)
        label = f"S-{season:02d} - E-{ep_num:02d}"
        s = self.font_md.render(label, True, C.WHITE)
        self.screen.blit(s, s.get_rect(centerx=self.sw // 2, centery=self.sh // 2 - 40))

        # Episode name (blue)
        if ep_name:
            n = self.font_md.render(ep_name, True, C.BLUE)
            self.screen.blit(n, n.get_rect(centerx=self.sw // 2, centery=self.sh // 2 + 10))

        # Resume cue or show name
        if resume_secs and resume_secs > 0:
            mins = int(resume_secs) // 60
            secs = int(resume_secs) % 60
            sn = self.font_sm.render(f"RESUME  {mins}:{secs:02d}", True, C.GREEN)
        else:
            sn = self.font_sm.render(show.upper(), True, C.DIM)
        self.screen.blit(sn, sn.get_rect(centerx=self.sw // 2, centery=self.sh // 2 + 55))

        self.present()
        # Pump/clear events while waiting so held keys (and key-repeat KEYDOWNs)
        # do not pile up and immediately pause/seek when playback begins.
        deadline = pygame.time.get_ticks() + 1500
        while pygame.time.get_ticks() < deadline:
            pygame.event.clear()
            self.clock.tick(30)

        self.screen.fill(C.BLACK)
        self.present()
        pygame.event.clear()

    # ─── Key configuration ────────────────────────────────────────────────

    # ─── Confirm exit dialog ────────────────────────────────────────────

    def draw_confirm_exit(self):
        """'Are you sure?' exit confirmation dialog."""
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
        pygame.draw.rect(self.screen, C.BG_CARD_SEL, yes_rect, border_radius=6)
        pygame.draw.rect(self.screen, C.CYAN, yes_rect, 2, border_radius=6)
        yes_txt = self.font_sm.render("Yes", True, C.BRIGHT)
        self.screen.blit(yes_txt, yes_txt.get_rect(center=yes_rect.center))

        # No button
        no_x = btn_start_x + btn_w + gap
        no_rect = pygame.Rect(no_x, btn_y, btn_w, btn_h)
        pygame.draw.rect(self.screen, C.BG_CARD, no_rect, border_radius=6)
        pygame.draw.rect(self.screen, C.DIM, no_rect, 2, border_radius=6)
        no_txt = self.font_sm.render("No", True, C.DIM)
        self.screen.blit(no_txt, no_txt.get_rect(center=no_rect.center))

        self._apply_scanlines()

    # ─── Key configuration ────────────────────────────────────────────────

    def draw_key_config(self, capturing=False):
        """Key configuration screen with white/blue theme."""
        self.screen.fill(C.BG)

        title = self.font_lg.render("KEY SETUP", True, C.BLUE)
        self.screen.blit(title, title.get_rect(centerx=self.sw // 2, centery=40))

        if capturing:
            hint = self.font_md.render("Press a key...  (Esc cancels)", True, C.GREEN)
        else:
            hint = self.font_sm.render("ENTER assign  |  ESC done  |  TAB reset", True, C.DIM)
        self.screen.blit(hint, hint.get_rect(centerx=self.sw // 2, centery=82))

        y_start = 118
        row_h = 50
        # Leave room for the bound-key value on the right
        label_max_x = self.sw - 180

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

            # Truncate label if it would overflow into the key-name area
            label_color = C.BRIGHT if selected else C.WHITE
            label_text = action_label
            label_surf = self.font_md.render(label_text, True, label_color)
            if label_surf.get_width() > label_max_x - 50:
                while (self.font_md.size(label_text + "...")[0] > label_max_x - 50
                       and len(label_text) > 3):
                    label_text = label_text[:-1]
                label_surf = self.font_md.render(label_text + "...", True, label_color)
            self.screen.blit(label_surf, (50, y + (row_h - label_surf.get_height()) // 2 - 3))

            bound_key = self.keymap.get(action_id, DEFAULT_KEYMAP.get(action_id))
            key_name = key_display_name(bound_key)

            if capturing and selected:
                if (pygame.time.get_ticks() // 500) % 2 == 0:
                    key_surf = self.font_lg.render("_", True, C.GREEN)
                else:
                    key_surf = self.font_lg.render("-", True, C.GREEN)
            else:
                key_surf = self.font_md.render(key_name, True, C.BRIGHT if selected else C.DIM)
            self.screen.blit(key_surf, (self.sw - key_surf.get_width() - 50,
                                         y + (row_h - key_surf.get_height()) // 2 - 3))

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
        self.state["keymap"] = {k: v for k, v in self.keymap.items()}
        save_state(self.state)

    def reset_watch_status(self):
        """Clear watched / next-up progress for the current menu context."""
        if self.view == self.EPISODE_SELECT:
            if not self.cur_show or self.cur_season is None:
                return
            changed = clear_resume_ep(self.state, self.cur_show, self.cur_season)
            label = f"S-{self.cur_season:02d} reset"
        elif self.view == self.SEASON_SELECT:
            if not self.cur_show:
                return
            seasons = self.seasons_for_show(self.cur_show)
            if not seasons or self.cursor >= len(seasons):
                return
            season = seasons[self.cursor]
            changed = clear_resume_ep(self.state, self.cur_show, season)
            label = f"S-{season:02d} reset"
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
        total = self.total_items()
        if not total:
            return
        # Clamp (no wrap) so the on-screen "more above/below" hints stay accurate.
        new_cursor = max(0, min(total - 1, self.cursor + direction))
        if new_cursor != self.cursor:
            self.cursor = new_cursor
            self._marquee_key = None  # restart marquee delay on the new row

    def select(self):
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
        items = self.current_items()

        if self.view == self.SHOW_LIST:
            if 1 <= channel_num <= len(self.show_names):
                self.cursor = channel_num - 1
                return True
            else:
                if len(self.show_names) == 0:
                    self.channel_error = "No Shows"
                elif channel_num > len(self.show_names):
                    self.channel_error = f"Ch {channel_num} Not Found"
                else:
                    self.channel_error = "Channel Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        elif self.view == self.SEASON_SELECT:
            seasons = self.seasons_for_show(self.cur_show)
            if 1 <= channel_num <= len(seasons):
                self.cursor = channel_num - 1
                return True
            else:
                self.channel_error = f"Season {channel_num} Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        elif self.view == self.EPISODE_SELECT:
            episodes = self.current_items()
            if 1 <= channel_num <= len(episodes):
                self.cursor = channel_num - 1
                return True
            else:
                self.channel_error = f"Episode {channel_num} Not Found"
                self.channel_error_time = pygame.time.get_ticks()
                return False

        return False

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
        self.playing_episode = episodes[start]
        self.playing_episodes = episodes
        self.playing_index = start
        self.view = self.PLAYING

        # Show splash — channel is the episode's 1-based position on its page
        pos_ep, pos_secs = get_episode_position(
            self.state, self.cur_show, self.cur_season
        )
        resume_secs = None
        if pos_ep is not None and episodes[start]["number"] == pos_ep:
            resume_secs = pos_secs

        self.draw_now_playing(
            self.cur_show,
            self.cur_season,
            episodes[start],
            start + 1,
            resume_secs=resume_secs,
        )

        # Start player
        self.player = EmbeddedPlayer(self.canvas_w, self.canvas_h)
        # Set player capabilities based on what's available
        ffmpeg_path = detect_ffmpeg()
        ffplay_path = detect_ffplay()
        omx_cmd = detect_omxplayer() if is_pi() else None

        if ffmpeg_path and np_frombuffer is not None:
            self.player.ffmpeg_path = ffmpeg_path
            self.player.ffplay_path = ffplay_path
            self.embedded_player = True
        elif omx_cmd:
            if not self._omx_overlay:
                self._enable_omx_overlay()
            self.player.use_omx = True
            self.player.omx_cmd = omx_cmd
            self.embedded_player = True
        else:
            self.embedded_player = False

        if not self.player.start(episodes[start]['path'], resume_pos=resume_secs):
            self.player = None
            self.channel_error = "PLAY FAILED"
            self.channel_error_time = pygame.time.get_ticks()
            self.view = self.EPISODE_SELECT
            return

        # Discard any KEYDOWNs that accumulated while the splash ran (held Enter
        # would otherwise toggle pause; held Right would seek and often exit).
        pygame.event.clear()
        self._play_input_grace_until = pygame.time.get_ticks() + PLAY_INPUT_GRACE_MS
        self.progress_overlay_timer = 0
        self.volume_overlay_timer = 0

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

    # ─── Main loop ─────────────────────────────────────────────────────────

    def run(self):
        # Show controls splash on startup
        self.draw_splash()

        while self.running:
            # ═══════════════════════════════════════════════════════════════════
            # PLAYBACK MODE: embedded video rendering
            # ═══════════════════════════════════════════════════════════════════
            if self.view == self.PLAYING:
                # Check if video finished naturally (no autoplay).
                # Mark the episode completed only when it actually ends.
                if self.player and self.player.is_finished():
                    self._mark_completed()
                    self.stop_playback(completed=True)
                    continue

                # Process keyboard events — ONLY playback controls here
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.stop_playback()
                        self.running = False
                        break
                    elif event.type == pygame.KEYDOWN:
                        km = self.keymap
                        # Skip transport keys that were held to *start* playback
                        if pygame.time.get_ticks() < self._play_input_grace_until:
                            if event.key in (
                                km.get("right", pygame.K_RIGHT),
                                km.get("left", pygame.K_LEFT),
                                km.get("select", pygame.K_RETURN),
                                pygame.K_RETURN,
                                pygame.K_KP_ENTER,
                                pygame.K_SPACE,
                            ):
                                continue

                        if event.key == km.get("back", pygame.K_ESCAPE):
                            # Stop playback and return to episode list
                            self.stop_playback()
                            break

                        elif event.key == km.get("up", pygame.K_UP):
                            if self.player:
                                self.player.adjust_volume(10)
                                self.volume_overlay_timer = pygame.time.get_ticks()

                        elif event.key == km.get("down", pygame.K_DOWN):
                            if self.player:
                                self.player.adjust_volume(-10)
                                self.volume_overlay_timer = pygame.time.get_ticks()

                        elif event.key == km.get("right", pygame.K_RIGHT):
                            if self.player:
                                self.player.seek(PROGRESS_SEEK_S)
                                self.progress_overlay_timer = pygame.time.get_ticks()

                        elif event.key == km.get("left", pygame.K_LEFT):
                            if self.player:
                                self.player.seek(-PROGRESS_SEEK_S)
                                self.progress_overlay_timer = pygame.time.get_ticks()

                        elif event.key == pygame.K_SPACE or event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            if self.player:
                                self.player.pause()
                                if self.player.paused:
                                    self.progress_overlay_timer = pygame.time.get_ticks()

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

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.KEYDOWN:
                    # Key capture mode
                    if self.view == self.KEY_CAPTURE:
                        if event.key == pygame.K_ESCAPE:
                            # Cancel capture without rebinding
                            self.view = self.KEY_CONFIG
                            continue
                        if event.key == pygame.K_TAB:
                            continue
                        action_id = KEY_ACTIONS[self.config_cursor][0]
                        self.keymap[action_id] = event.key
                        self.state["keymap"] = {k: v for k, v in self.keymap.items()}
                        save_state(self.state)
                        self.view = self.KEY_CONFIG
                        continue

                    # Key config screen
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

                    # Confirm exit screen
                    elif self.view == self.CONFIRM_EXIT:
                        if event.key == pygame.K_ESCAPE:
                            self.view = self.SHOW_LIST
                        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                            self.running = False
                        continue

                    # Channel number input
                    if pygame.K_0 <= event.key <= pygame.K_9 or pygame.K_KP0 <= event.key <= pygame.K_KP9:
                        if pygame.K_0 <= event.key <= pygame.K_9:
                            digit = event.key - pygame.K_0
                        else:
                            digit = event.key - pygame.K_KP0

                        # Cancel any pending auto-select
                        self.channel_pending = 0
                        self.channel_pending_time = 0

                        self.channel_digits += str(digit)
                        self.channel_timer = pygame.time.get_ticks()
                        continue

                    if self.channel_digits:
                        self.channel_digits = ""
                        self.channel_timer = 0

                    # Cancel pending auto-select on any other key
                    self.channel_pending = 0
                    self.channel_pending_time = 0

                    # Normal navigation
                    km = self.keymap
                    if event.key == pygame.K_TAB:
                        self.enter_key_config()
                        continue

                    if event.key == pygame.K_h:
                        # Re-open the controls / help splash on demand
                        self.draw_splash()
                        continue

                    if event.key == km.get("up", pygame.K_UP):
                        self.move_cursor(-1)
                    elif event.key == km.get("down", pygame.K_DOWN):
                        self.move_cursor(1)
                    elif event.key == km.get("select", pygame.K_RETURN) or event.key == km.get("right", pygame.K_RIGHT):
                        self.select()
                    elif event.key == km.get("left", pygame.K_LEFT):
                        self.go_back()
                    elif event.key == km.get("reset", pygame.K_r):
                        self.reset_watch_status()
                    elif event.key == km.get("back", pygame.K_ESCAPE):
                        if self.view == self.SHOW_LIST:
                            self.view = self.CONFIRM_EXIT
                        else:
                            self.go_back()
                    elif event.key == pygame.K_q:
                        self.running = False

            # Channel timeout — first highlight, then auto-select after delay
            if self.channel_digits and self.channel_timer > 0:
                now = pygame.time.get_ticks()
                if now - self.channel_timer >= CHANNEL_TIMEOUT_MS:
                    channel = int(self.channel_digits) if self.channel_digits else 0
                    if channel > 0:
                        success = self.jump_to_channel(channel)
                        if success:
                            self.channel_flash = self.channel_digits
                            self.channel_flash_time = now
                            # Start pending auto-select timer
                            self.channel_pending = channel
                            self.channel_pending_time = now
                    self.channel_digits = ""
                    self.channel_timer = 0

            # Pending auto-select: after brief highlight, actually enter
            if self.channel_pending > 0 and self.channel_pending_time > 0:
                now = pygame.time.get_ticks()
                if now - self.channel_pending_time >= CHANNEL_PENDING_MS:
                    self.select()
                    self.channel_pending = 0
                    self.channel_pending_time = 0

            if self.view == self.CONFIRM_EXIT:
                self.draw_confirm_exit()
                self.present()
            elif self.view in (self.KEY_CONFIG, self.KEY_CAPTURE):
                self.draw_key_config(capturing=(self.view == self.KEY_CAPTURE))
            else:
                self.draw()
                self.present()
            self.clock.tick(30)

        # Clean up any active player
        if self.player:
            self.player.stop()
        pygame.quit()

