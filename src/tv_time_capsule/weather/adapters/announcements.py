"""RetroCast-style page announcements (voiceovers + alert tone)."""

from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger(__name__)

# Native page id → announcement basename (from weather.com/retro assets).
# Hourly has no VO: stock ``local.mp3`` says "36-hour forecast", which does not
# match our shorter hourly pages.
PAGE_ANNOUNCEMENTS: dict[str, str] = {
    "current": "current.mp3",
    "daily": "extended.mp3",
    "regional": "regional.mp3",
    "radar": "radar.mp3",
    "alerts": "alert-tone.mp3",
}


def bundled_announcements_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "announcements"


def discover_announcements(extra_dir: Path | None = None) -> dict[str, Path]:
    """Map page id → clip path for available announcement files."""
    roots = [p for p in (extra_dir, bundled_announcements_dir()) if p is not None]
    by_name: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.mp3"):
            if path.is_file() and path.stat().st_size > 0:
                by_name[path.name.lower()] = path
    found: dict[str, Path] = {}
    for page, filename in PAGE_ANNOUNCEMENTS.items():
        path = by_name.get(filename.lower())
        if path is not None:
            found[page] = path
    return found


class AnnouncementPlayer:
    """Play short voiceovers on a mixer Sound channel (alongside music)."""

    def __init__(self) -> None:
        self._clips: dict[str, Path] = {}
        self._sounds: dict[str, object] = {}
        self._channel = None
        self._volume = 70
        self._ready = False

    def start(self, clips: dict[str, Path], volume: int) -> None:
        self._clips = dict(clips)
        self._volume = max(0, min(100, int(volume)))
        self._sounds.clear()
        self._channel = None
        self._ready = False
        if not self._clips:
            LOG.info(
                "Weather announcements: no clips "
                "(run scripts/fetch-weather-music.sh)"
            )
            return
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            # Reserve channel 1 for VOs so channel 0 stays free for other SFX.
            self._channel = pygame.mixer.Channel(1)
            for page, path in self._clips.items():
                try:
                    self._sounds[page] = pygame.mixer.Sound(str(path))
                except Exception:
                    LOG.exception("Failed to load announcement %s", path)
            self.set_volume(self._volume)
            self._ready = bool(self._sounds)
            LOG.info(
                "Weather announcements: loaded %s",
                ", ".join(sorted(self._sounds)),
            )
        except Exception:
            LOG.exception("Weather announcements init failed")

    def stop(self) -> None:
        try:
            if self._channel is not None:
                self._channel.stop()
        except Exception:
            pass
        self._sounds.clear()
        self._clips.clear()
        self._channel = None
        self._ready = False

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        level = self._volume / 100.0
        try:
            for sound in self._sounds.values():
                sound.set_volume(level)  # type: ignore[attr-defined]
        except Exception:
            pass

    def play_for_page(self, page: str) -> None:
        if not self._ready or self._channel is None:
            return
        key = page.split(":", 1)[0]
        sound = self._sounds.get(key)
        if sound is None:
            return
        try:
            self._channel.stop()
            self._channel.play(sound)  # type: ignore[arg-type]
        except Exception:
            LOG.exception("Weather announcement play failed (%s)", page)
