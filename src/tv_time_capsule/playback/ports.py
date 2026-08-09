"""Ports (protocols) for live vs cached playback backends.

Defaults prefer cached / offline-friendly adapters. Live Chrome CDP backends
remain first-class when config opts in (``youtube.playback_mode: live``,
``retro_tv.playback_mode: live``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

PlaybackBackend = Literal["live", "file", "blocked"]
YoutubePlaybackMode = Literal["live", "prefer_cache", "cached_only"]
RetroPlaybackMode = Literal["live", "cached"]


@runtime_checkable
class EpisodeOfflineCache(Protocol):
    """Forever offline tree for virtual YouTube shows."""

    enabled: bool
    playback_mode: str

    def is_cached(self, youtube_id: str | None) -> bool:
        ...

    def cached_path(self, youtube_id: str | None) -> Path | None:
        ...

    def backend_for_episode(self, episode: dict | None) -> PlaybackBackend:
        ...


@runtime_checkable
class RollingClipCache(Protocol):
    """Short-lived rolling clip cache (MyRetroTVs ``cached`` mode)."""

    def path_for(self, youtube_id: str | None) -> Path | None:
        ...

    def is_cached(self, youtube_id: str | None) -> bool:
        ...

    def download(
        self,
        youtube_id: str,
        *,
        keep: object | None = None,
    ) -> Path | None:
        ...

    def cancel(self) -> None:
        ...
