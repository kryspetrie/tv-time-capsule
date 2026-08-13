"""Browse QoL, profiles, PIN, TV guide, stall skip, banners, breadcrumbs."""

from __future__ import annotations

import time
from typing import Any

import pygame

from .breadcrumb import write_breadcrumb
from .channels import build_channel_lineup
from .config import C, save_config
from .log import LOG
from .profiles import (
    PROFILE_IDS,
    copy_allowlist,
    load_profile_state,
    normalize_profile_id,
    profile_pin,
    save_profile_state,
)
from .state import (
    get_episode_position,
    list_continue_watching,
    list_recently_watched,
)
from .thumbnails import ensure_movie_thumbnail, ensure_show_thumbnail
from .tv_guide import (
    PAGE_DWELL_MS,
    PAGE_SCROLL_MS,
    TOP_SLOT_MS,
    build_guide_rows,
    draw_tv_guide,
    ease_in_out,
    ensure_guide_weather,
    guide_row_metrics,
    peek_guide_weather,
    pick_random_preview_idx,
    resolve_top_mode,
)
from .player import detect_ffmpeg


class QolFeaturesMixin:
    """Mixin mixed into TVTimeCapsule (expects app attributes)."""

    def _init_qol_features(self, *, mount_warnings: list[str] | None = None) -> None:
        self._mount_warnings: list[str] = list(mount_warnings or [])
        self._browse_filter: str | None = None  # continue|favorites|recent|None
        self._tv_guide_rows: list[dict[str, Any]] = []
        self._tv_guide_top_mode = "preview"
        self._tv_guide_top_slot = 0
        self._tv_guide_top_slot_at = 0
        self._tv_guide_preview_idx = 0
        self._tv_guide_scroll_offset = 0
        self._tv_guide_scroll_pixel = 0.0
        self._tv_guide_scroll_phase = "dwell"
        self._tv_guide_scroll_to = 0
        self._tv_guide_scroll_delta_rows = 0
        self._tv_guide_scroll_anim_at = 0
        self._tv_guide_row_stride = 74
        self._tv_guide_page_size = 1
        self._tv_guide_page_at = 0
        self._tv_guide_weather = None
        self._pin_prompt_active = False
        self._pin_buffer = ""
        self._pin_pending_action: str | None = None  # leave_kids|switch_profile
        self._pin_pending_profile: str | None = None
        self._stall_retry_count = 0
        self._volume_save_at = 0.0
        pb = self.config.get("playback") or {}
        try:
            self._playback_volume = int(pb.get("volume", 100))
        except (TypeError, ValueError):
            self._playback_volume = 100
        self._playback_volume = max(0, min(100, self._playback_volume))
        self._stall_auto_skip = bool(pb.get("stall_auto_skip", True))
        self._media_read_only = bool((self.config.get("media") or {}).get("read_only", False))
        self._pause_cc_osd = bool((self.config.get("ui") or {}).get("pause_cc_osd", False))
        profiles = self.config.get("profiles") or {}
        self._active_profile = normalize_profile_id(profiles.get("active", "parent"))
        self._load_active_profile_state()
        entry = profiles.get(self._active_profile) or {}
        try:
            self._playback_volume = int(entry.get("volume", self._playback_volume))
        except (TypeError, ValueError):
            pass
        self._playback_volume = max(0, min(100, self._playback_volume))
        fav = self.config.get("favorites") or {}
        self._favorite_shows = [str(x) for x in (fav.get("shows") or [])]
        self._favorite_movies = [str(x) for x in (fav.get("movies") or [])]
        self._sync_favorites_from_profile()
        # Kids profile forces kids UX at startup
        if self._active_profile == "kids" and not self._kids_mode_active:
            # Defer until allowlist is loaded by app init
            self._qol_force_kids_on_ready = True
        else:
            self._qol_force_kids_on_ready = False
    def _load_active_profile_state(self) -> None:
        self.state = load_profile_state(self._active_profile)

    def _save_watch_state(self) -> None:
        save_profile_state(self._active_profile, self.state)

    def _sync_favorites_from_profile(self) -> None:
        profiles = self.config.get("profiles") or {}
        entry = profiles.get(self._active_profile) or {}
        fav = entry.get("favorites")
        if isinstance(fav, dict):
            shows = fav.get("shows")
            movies = fav.get("movies")
            if isinstance(shows, list):
                self._favorite_shows = [str(x) for x in shows]
            if isinstance(movies, list):
                self._favorite_movies = [str(x) for x in movies]
        # Mirror into top-level favorites for older readers
        self.config["favorites"] = {
            "shows": list(self._favorite_shows),
            "movies": list(self._favorite_movies),
        }

    def _persist_favorites(self) -> None:
        fav = {"shows": list(self._favorite_shows), "movies": list(self._favorite_movies)}
        self.config["favorites"] = fav
        profiles = dict(self.config.get("profiles") or {})
        entry = dict(profiles.get(self._active_profile) or {})
        entry["favorites"] = fav
        profiles[self._active_profile] = entry
        profiles["active"] = self._active_profile
        self.config["profiles"] = profiles
        save_config(self.config)

    def _persist_volume(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._volume_save_at) < 0.75:
            return
        self._volume_save_at = now
        pb = dict(self.config.get("playback") or {})
        pb["volume"] = int(self._playback_volume)
        self.config["playback"] = pb
        profiles = dict(self.config.get("profiles") or {})
        entry = dict(profiles.get(self._active_profile) or {})
        entry["volume"] = int(self._playback_volume)
        profiles[self._active_profile] = entry
        profiles["active"] = self._active_profile
        self.config["profiles"] = profiles
        save_config(self.config)

    def _apply_volume_to_player(self) -> None:
        if self.player is not None:
            self.player.volume = int(self._playback_volume)

    def _write_session_breadcrumb(self, **extra: Any) -> None:
        try:
            write_breadcrumb(
                view=getattr(self, "view", None),
                show=getattr(self, "cur_show", None),
                season=getattr(self, "cur_season", None),
                episode=getattr(self, "playing_episode", None),
                path=getattr(self, "_playing_source_path", None),
                kids_mode=bool(getattr(self, "_kids_mode_active", False)),
                profile=self._active_profile,
                browse_filter=self._browse_filter,
                **extra,
            )
        except Exception as exc:
            LOG.debug("breadcrumb write failed: %s", exc)

    def _mount_banner_text(self) -> str | None:
        if self._mount_warnings:
            first = self._mount_warnings[0]
            if len(first) > 48:
                first = first[:45] + "..."
            return first
        return None

    def _filtered_show_names(self, base: list[str]) -> list[str]:
        filt = self._browse_filter
        if not filt:
            return base
        known = set(base)
        if filt == "favorites":
            return [n for n in self._favorite_shows if n in known]
        if filt == "continue":
            items = list_continue_watching(self.state, known_shows=known)
            return [i["name"] for i in items if i["name"] in known]
        if filt == "recent":
            items = list_recently_watched(self.state, known_shows=known)
            return [i["name"] for i in items if i["name"] in known]
        return base

    def _filtered_movie_names(self, base: list[str]) -> list[str]:
        filt = self._browse_filter
        if not filt:
            return base
        known = set(base)
        if filt == "favorites":
            return [n for n in self._favorite_movies if n in known]
        # continue/recent are show-oriented for v1
        if filt in ("continue", "recent"):
            return []
        return base

    def _toggle_favorite_current(self) -> None:
        if self._kids_mode_active:
            return
        name = None
        kind = None
        if self.view == self.SHOW_LIST:
            names = self._browse_show_names()
            if names and 0 <= self.cursor < len(names):
                name, kind = names[self.cursor], "shows"
        elif self.view == self.MOVIE_LIST:
            names = self._browse_movie_names()
            if names and 0 <= self.cursor < len(names):
                name, kind = names[self.cursor], "movies"
        if not name or not kind:
            return
        bucket = self._favorite_shows if kind == "shows" else self._favorite_movies
        if name in bucket:
            bucket.remove(name)
            msg = f"Unfavorited {name}"
        else:
            bucket.append(name)
            msg = f"Favorited {name}"
        self._persist_favorites()
        self._apply_channel_lineup()
        self._mode_toast_message = msg[:40]
        self._mode_toast_until = pygame.time.get_ticks() + 2000

    def _is_favorite(self, name: str, *, movies: bool = False) -> bool:
        bucket = self._favorite_movies if movies else self._favorite_shows
        return name in bucket

    def _enter_browse_filter(self, filt: str) -> None:
        self._browse_filter = filt
        self.cursor = 0
        shows = self._browse_show_names()
        movies = self._browse_movie_names()
        if shows:
            self.view = self.SHOW_LIST
        elif movies:
            self.view = self.MOVIE_LIST
        else:
            self._browse_filter = None
            self._mode_toast_message = "Nothing here yet"
            self._mode_toast_until = pygame.time.get_ticks() + 2000

    def _clear_browse_filter(self) -> None:
        self._browse_filter = None

    def _enter_tv_guide(self) -> None:
        show_names = list(self._browse_show_names())
        movie_names = list(self._browse_movie_names())
        # Refresh posters so the top preview has art.
        ffmpeg = None
        try:
            ffmpeg = detect_ffmpeg()
        except Exception:
            ffmpeg = None
        for name in show_names:
            show = self.shows.get(name)
            if show is not None:
                ensure_show_thumbnail(
                    name,
                    show,
                    ffmpeg_path=ffmpeg,
                    resolve_local=getattr(self, "_resolve_episode_local_video", None),
                )
        for key in movie_names:
            movie = self.movies.get(key)
            if movie is not None:
                ensure_movie_thumbnail(
                    movie.get("title") or key, movie, ffmpeg_path=ffmpeg
                )
        # Use the same display channel numbers as the normal show/movie lists.
        show_channels = {
            name: int(self._display_channel(name)) for name in show_names
        }
        movie_channels = {
            key: int(self._display_movie_channel(key)) for key in movie_names
        }
        self._tv_guide_rows = build_guide_rows(
            show_names=show_names,
            movie_names=movie_names,
            show_channels=show_channels,
            movie_channels=movie_channels,
            shows=self.shows,
            movies=self.movies,
        )
        now = pygame.time.get_ticks()
        self._tv_guide_top_slot = 0
        self._tv_guide_top_slot_at = now
        self._tv_guide_preview_idx = -1
        self._apply_tv_guide_top_slot()
        self._tv_guide_scroll_offset = 0
        self._tv_guide_scroll_pixel = 0.0
        self._tv_guide_scroll_phase = "dwell"
        self._tv_guide_scroll_to = 0
        self._tv_guide_scroll_delta_rows = 0
        self._tv_guide_scroll_anim_at = 0
        self._tv_guide_page_size = 1
        self._tv_guide_page_at = now
        self.view = self.TV_GUIDE
        self.cursor = 0
        # One cache read / rare refresh — not every draw frame.
        self._tv_guide_weather = ensure_guide_weather(self.config)
        self._write_session_breadcrumb(action="tv_guide")

    def _apply_tv_guide_top_slot(self) -> None:
        mode = resolve_top_mode(int(self._tv_guide_top_slot))
        self._tv_guide_top_mode = mode
        if mode == "preview":
            self._tv_guide_preview_idx = pick_random_preview_idx(
                len(self._tv_guide_rows),
                avoid=int(self._tv_guide_preview_idx),
            )

    def _cycle_tv_guide_top_mode(self, delta: int = 1) -> None:
        """Manual left/right: step equal-time top slots."""
        self._tv_guide_top_slot = max(0, int(self._tv_guide_top_slot) + int(delta))
        self._tv_guide_top_slot_at = pygame.time.get_ticks()
        self._apply_tv_guide_top_slot()

    def _tick_tv_guide_panels(self) -> None:
        """Equal-time top slots + dwell / smooth page scroll."""
        if self.view != self.TV_GUIDE:
            return
        now = pygame.time.get_ticks()
        rows = self._tv_guide_rows

        if now - int(self._tv_guide_top_slot_at or 0) >= TOP_SLOT_MS:
            self._tv_guide_top_slot = int(self._tv_guide_top_slot) + 1
            self._tv_guide_top_slot_at = now
            self._apply_tv_guide_top_slot()

        page = max(1, int(getattr(self, "_tv_guide_page_size", 1) or 1))
        stride = max(1, int(getattr(self, "_tv_guide_row_stride", 74) or 74))
        phase = getattr(self, "_tv_guide_scroll_phase", "dwell") or "dwell"

        if phase == "scroll":
            elapsed = now - int(self._tv_guide_scroll_anim_at or 0)
            t = elapsed / float(PAGE_SCROLL_MS)
            if t >= 1.0:
                self._tv_guide_scroll_offset = int(self._tv_guide_scroll_to)
                self._tv_guide_scroll_pixel = 0.0
                self._tv_guide_scroll_phase = "dwell"
                self._tv_guide_page_at = now
            else:
                delta_px = float(self._tv_guide_scroll_delta_rows) * stride
                self._tv_guide_scroll_pixel = ease_in_out(t) * delta_px
            return

        if now - int(self._tv_guide_page_at or 0) < PAGE_DWELL_MS:
            return

        n = len(rows)
        if n <= 0:
            self._tv_guide_scroll_offset = 0
            self._tv_guide_scroll_pixel = 0.0
            self._tv_guide_page_at = now
            return

        cur = int(self._tv_guide_scroll_offset)
        if n <= page:
            # Single page — soft reset to top (no scroll anim).
            self._tv_guide_scroll_offset = 0
            self._tv_guide_scroll_pixel = 0.0
            self._tv_guide_page_at = now
            return

        nxt = cur + page
        if nxt >= n:
            to = 0
        else:
            to = nxt
        self._tv_guide_scroll_phase = "scroll"
        self._tv_guide_scroll_anim_at = now
        self._tv_guide_scroll_to = to
        self._tv_guide_scroll_delta_rows = page
        self._tv_guide_scroll_pixel = 0.0

    def _activate_tv_guide_row(self) -> None:
        """Guide is view-only — Enter does not tune a channel."""
        return

    def _kids_allowlist_shows(self) -> list[str]:
        al = (self.config.get("kids_mode") or {}).get("allowlist") or {}
        return [str(x) for x in (al.get("shows") or [])]

    def _kids_allowlist_movies(self) -> list[str]:
        al = (self.config.get("kids_mode") or {}).get("allowlist") or {}
        return [str(x) for x in (al.get("movies") or [])]

    def _request_leave_kids(self) -> None:
        pin = (self.config.get("kids_mode") or {}).get("pin")
        if not pin:
            profiles = self.config.get("profiles") or {}
            pin = profile_pin(profiles, "kids")
        if pin:
            self._pin_prompt_active = True
            self._pin_buffer = ""
            self._pin_pending_action = "leave_kids"
            self._pin_pending_profile = None
            return
        self._toggle_kids_mode()

    def _request_profile_switch(self, target: str) -> None:
        target = normalize_profile_id(target)
        if target == self._active_profile:
            return
        profiles = self.config.get("profiles") or {}
        # Leaving kids profile or kids mode may need PIN from kids profile
        need_pin = None
        if self._kids_mode_active or self._active_profile == "kids":
            need_pin = profile_pin(profiles, "kids") or (self.config.get("kids_mode") or {}).get(
                "pin"
            )
        if need_pin and target != "kids":
            self._pin_prompt_active = True
            self._pin_buffer = ""
            self._pin_pending_action = "switch_profile"
            self._pin_pending_profile = target
            return
        self._switch_profile(target)

    def _cycle_profile(self) -> None:
        idx = PROFILE_IDS.index(self._active_profile)
        nxt = PROFILE_IDS[(idx + 1) % len(PROFILE_IDS)]
        self._request_profile_switch(nxt)

    def _switch_profile(self, target: str) -> None:
        target = normalize_profile_id(target)
        save_profile_state(self._active_profile, self.state)
        self._active_profile = target
        profiles = dict(self.config.get("profiles") or {})
        profiles["active"] = target
        self.config["profiles"] = profiles
        save_config(self.config)
        self._load_active_profile_state()
        entry = profiles.get(target) or {}
        try:
            self._playback_volume = int(entry.get("volume", self._playback_volume))
        except (TypeError, ValueError):
            pass
        self._playback_volume = max(0, min(100, self._playback_volume))
        self._sync_favorites_from_profile()
        # Kids profile forces kids UX
        if target == "kids":
            if not self._kids_mode_active:
                if self._kids_has_assigned_titles():
                    self._kids_mode_active = True
                    self._apply_kids_startup_view()
                    self._persist_kids_mode()
        elif self._kids_mode_active:
            self._kids_mode_active = False
            self.view = self._view_for_library_layout()
            self.cursor = 0
            self._persist_kids_mode()
        self._apply_channel_lineup()
        label = str(entry.get("label") or target)
        self._mode_toast_message = f"Profile: {label}"
        self._mode_toast_until = pygame.time.get_ticks() + 2000
        self._write_session_breadcrumb(action="profile_switch")

    def _handle_pin_digit(self, digit: str) -> None:
        if not self._pin_prompt_active:
            return
        if len(self._pin_buffer) >= 4:
            return
        self._pin_buffer += digit
        if len(self._pin_buffer) >= 4:
            self._submit_pin()

    def _submit_pin(self) -> None:
        profiles = self.config.get("profiles") or {}
        expected = profile_pin(profiles, "kids") or (self.config.get("kids_mode") or {}).get(
            "pin"
        )
        expected = str(expected or "")
        if self._pin_buffer == expected:
            action = self._pin_pending_action
            target = self._pin_pending_profile
            self._pin_prompt_active = False
            self._pin_buffer = ""
            self._pin_pending_action = None
            self._pin_pending_profile = None
            if action == "leave_kids":
                if self._kids_mode_active:
                    self._toggle_kids_mode()
            elif action == "switch_profile" and target:
                self._switch_profile(target)
        else:
            self._pin_buffer = ""
            self._mode_toast_message = "Wrong PIN"
            self._mode_toast_until = pygame.time.get_ticks() + 1500

    def _cancel_pin_prompt(self) -> None:
        self._pin_prompt_active = False
        self._pin_buffer = ""
        self._pin_pending_action = None
        self._pin_pending_profile = None

    def _draw_pin_prompt(self) -> None:
        if not self._pin_prompt_active:
            return
        overlay = pygame.Surface((self.sw, self.sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))
        title = self.font_lg.render("GROWN-UP PIN", True, C.GREEN)
        dots = "*" * len(self._pin_buffer) + "_" * (4 - len(self._pin_buffer))
        body = self.font_md.render(dots, True, C.WHITE)
        hint = self.font_sm.render("Enter PIN  |  Esc cancel", True, self._dim_color())
        self.screen.blit(title, title.get_rect(center=(self.sw // 2, self.sh // 2 - 40)))
        self.screen.blit(body, body.get_rect(center=(self.sw // 2, self.sh // 2)))
        self.screen.blit(hint, hint.get_rect(center=(self.sw // 2, self.sh // 2 + 40)))

    def _draw_tv_guide(self) -> None:
        self._tick_tv_guide_panels()
        # Smaller list title so more of the show name fits.
        fonts = {
            "xl": self.font_lg,
            "lg": self.font_lg,
            "md": self.font_md,
            "sm": self.font_sm,
            "title": self.font_sm,
            "ch": self.font_sm,
            "sub": self.font_sm,
        }
        # Pick up a completed background fetch without issuing new requests.
        peeked = peek_guide_weather()
        if peeked is not None:
            self._tv_guide_weather = peeked
        row_h, gap = guide_row_metrics(font_title=fonts["title"])
        self._tv_guide_row_stride = row_h + gap
        self._tv_guide_page_size = draw_tv_guide(
            self.screen,
            rows=self._tv_guide_rows,
            scroll_offset=self._tv_guide_scroll_offset,
            scroll_pixel=float(self._tv_guide_scroll_pixel or 0.0),
            top_mode=self._tv_guide_top_mode,
            preview_idx=self._tv_guide_preview_idx,
            fonts=fonts,
            load_image=self.load_image,
            weather=self._tv_guide_weather,
            now_ms=pygame.time.get_ticks(),
        )

    def admin_profiles(self) -> dict[str, Any]:
        profiles = self.config.get("profiles") or {}
        out = {"active": self._active_profile, "profiles": {}}
        for pid in PROFILE_IDS:
            entry = dict(profiles.get(pid) or {})
            fav = entry.get("favorites") or {}
            out["profiles"][pid] = {
                "label": entry.get("label"),
                "has_pin": bool(entry.get("pin")),
                "volume": entry.get("volume", 100),
                "favorites_shows": len((fav.get("shows") or [])),
                "favorites_movies": len((fav.get("movies") or [])),
                "has_allowlist": isinstance(entry.get("allowlist"), dict),
            }
        return out

    def admin_set_active_profile(self, profile_id: str) -> dict[str, Any]:
        self._request_profile_switch(str(profile_id))
        return self.admin_profiles()

    def admin_set_profile_pin(self, profile_id: str, pin: str | None) -> dict[str, Any]:
        pid = normalize_profile_id(profile_id)
        profiles = dict(self.config.get("profiles") or {})
        entry = dict(profiles.get(pid) or {})
        if pin is None or str(pin).strip() == "":
            entry["pin"] = None
        else:
            digits = "".join(ch for ch in str(pin) if ch.isdigit())[:4]
            entry["pin"] = digits or None
        profiles[pid] = entry
        self.config["profiles"] = profiles
        if pid == "kids":
            km = dict(self.config.get("kids_mode") or {})
            km["pin"] = entry["pin"]
            self.config["kids_mode"] = km
        save_config(self.config)
        return self.admin_profiles()

    def admin_copy_allowlist(self, src: str, dest: str) -> dict[str, Any]:
        profiles = dict(self.config.get("profiles") or {})
        km_al = (self.config.get("kids_mode") or {}).get("allowlist")
        updated = copy_allowlist(
            profiles, src=src, dest=dest, kids_mode_allowlist=km_al
        )
        self.config["profiles"] = updated
        dest_id = normalize_profile_id(dest)
        if dest_id == "kids" and isinstance(updated.get("kids", {}).get("allowlist"), dict):
            km = dict(self.config.get("kids_mode") or {})
            km["allowlist"] = updated["kids"]["allowlist"]
            self.config["kids_mode"] = km
        save_config(self.config)
        return self.admin_profiles()
