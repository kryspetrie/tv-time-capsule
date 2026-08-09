"""Background smooth-jazz player for native weather."""

from __future__ import annotations

import logging
import random
from pathlib import Path

LOG = logging.getLogger(__name__)


def bundled_music_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "music"


def discover_tracks(extra_dir: Path | None = None) -> list[Path]:
    """Collect .mp3 paths from operator dir and/or bundled assets."""
    found: list[Path] = []
    for root in (extra_dir, bundled_music_dir()):
        if root is None or not root.is_dir():
            continue
        for path in sorted(root.glob("*.mp3")):
            if path.is_file() and path.stat().st_size > 0:
                found.append(path)
    return found


class PygameMusicPlayer:
    def __init__(self) -> None:
        self._volume = 70
        self._tracks: list[Path] = []
        self._index = 0
        self._started = False

    @property
    def volume(self) -> int:
        return self._volume

    def start(self, tracks: list[Path], volume: int) -> None:
        self._tracks = list(tracks)
        random.shuffle(self._tracks)
        self._volume = max(0, min(100, int(volume)))
        if not self._tracks:
            LOG.info("Weather music: no tracks found (add MP3s under weather assets or music.directory)")
            return
        try:
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self.set_volume(self._volume)
            self._index = 0
            self._play_current()
            self._started = True
        except Exception:
            LOG.exception("Weather music init failed")

    def stop(self) -> None:
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        self._started = False

    def adjust_volume(self, delta: int) -> int:
        self._volume = max(0, min(100, self._volume + int(delta)))
        self.set_volume(self._volume)
        return self._volume

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.set_volume(self._volume / 100.0)
        except Exception:
            pass

    def _set_volume(self, volume: int) -> None:
        self.set_volume(volume)

    def tick(self) -> None:
        """Advance to the next track when the current one finishes."""
        if not self._started or not self._tracks:
            return
        try:
            import pygame

            if not pygame.mixer.get_init():
                return
            if pygame.mixer.music.get_busy():
                return
            self._index += 1
            if self._index >= len(self._tracks):
                random.shuffle(self._tracks)
                self._index = 0
            self._play_current()
        except Exception:
            LOG.debug("Weather music tick failed", exc_info=True)

    def _play_current(self) -> None:
        if not self._tracks:
            return
        import pygame

        path = self._tracks[self._index % len(self._tracks)]
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            LOG.debug("Weather music playing %s", path.name)
        except Exception:
            LOG.exception("Weather music failed to play %s", path)
