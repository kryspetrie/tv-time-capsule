"""Playback backends: ports + factories for live vs cached modes."""

from __future__ import annotations

from typing import Any

from .ports import (
    EpisodeOfflineCache,
    PlaybackBackend,
    RetroPlaybackMode,
    RollingClipCache,
    YoutubePlaybackMode,
)

__all__ = [
    "EpisodeOfflineCache",
    "PlaybackBackend",
    "RetroPlaybackMode",
    "RollingClipCache",
    "YoutubePlaybackMode",
    "create_episode_offline_cache",
    "create_retro_clip_cache",
]


def create_episode_offline_cache(config: dict[str, Any]):
    """Build the forever YouTube offline-cache adapter from config.

    Returns :class:`~tv_time_capsule.youtube_offline_cache.YoutubeOfflineCache`,
    which satisfies :class:`EpisodeOfflineCache`.
    """
    from ..youtube_offline_cache import YoutubeOfflineCache

    return YoutubeOfflineCache(config)


def create_retro_clip_cache(
    config: dict[str, Any] | None,
    *,
    decade: str,
):
    """Build the Decades 2-slot temp-cache adapter.

    Returns :class:`~tv_time_capsule.retro_tv_cache.RetroTvTempCache`,
    which satisfies :class:`RollingClipCache`.
    """
    from ..retro_tv_cache import RetroTvTempCache

    return RetroTvTempCache(config, decade=decade)
