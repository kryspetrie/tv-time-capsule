"""Immutable library aggregate — mirrors MusicBox's MediaLibrary pattern.

Holds the merged view of shows and movies discovered from media roots,
with stable UUIDs and layout metadata.  All mutating methods return new
instances.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class Library:
    """Immutable aggregate root for the media library.

    Attributes:
        shows: Show name → show data dict (seasons, episodes, thumbnails).
        movies: Movie key → movie data dict (title, path, thumbnail).
        show_names: Ordered browse names for shows.
        movie_names: Ordered browse names for movies.
        show_uuids: Show name → stable UUID.
        movie_uuids: Movie key → stable UUID.
        layout: ``"split"``, ``"shows_only"``, ``"movies_only"``, or ``"legacy"``.
    """

    shows: dict[str, dict[str, Any]]
    movies: dict[str, dict[str, Any]]
    show_names: tuple[str, ...]
    movie_names: tuple[str, ...]
    show_uuids: dict[str, str]
    movie_uuids: dict[str, str]
    layout: str

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def has_shows(self) -> bool:
        return len(self.shows) > 0

    @property
    def has_movies(self) -> bool:
        return len(self.movies) > 0

    @property
    def is_split(self) -> bool:
        return self.layout == "split"

    @property
    def is_movies_only(self) -> bool:
        return self.layout == "movies_only"

    @property
    def is_shows_only(self) -> bool:
        return self.layout == "shows_only"

    @property
    def show_count(self) -> int:
        return len(self.show_names)

    @property
    def movie_count(self) -> int:
        return len(self.movie_names)

    # ── UUID lookups ────────────────────────────────────────────────────

    def show_uuid(self, name: str) -> str | None:
        """Return the stable UUID for a show, or ``None``."""
        return self.show_uuids.get(name)

    def movie_uuid(self, key: str) -> str | None:
        """Return the stable UUID for a movie, or ``None``."""
        return self.movie_uuids.get(key)

    def show_by_uuid(self, uuid: str) -> dict[str, Any] | None:
        """Look up a show by its UUID."""
        for name, sid in self.show_uuids.items():
            if sid == uuid:
                return self.shows.get(name)
        return None

    def movie_by_uuid(self, uuid: str) -> dict[str, Any] | None:
        """Look up a movie by its UUID."""
        for key, mid in self.movie_uuids.items():
            if mid == uuid:
                return self.movies.get(key)
        return None

    def show_name_by_uuid(self, uuid: str) -> str | None:
        """Return the show name for a UUID, or ``None``."""
        for name, sid in self.show_uuids.items():
            if sid == uuid:
                return name
        return None

    def movie_key_by_uuid(self, uuid: str) -> str | None:
        """Return the movie key for a UUID, or ``None``."""
        for key, mid in self.movie_uuids.items():
            if mid == uuid:
                return key
        return None

    # ── Show / movie access ─────────────────────────────────────────────

    def get_show(self, name: str) -> dict[str, Any] | None:
        return self.shows.get(name)

    def get_movie(self, key: str) -> dict[str, Any] | None:
        return self.movies.get(key)

    def show_at_index(self, index: int) -> str | None:
        if 0 <= index < len(self.show_names):
            return self.show_names[index]
        return None

    def movie_at_index(self, index: int) -> str | None:
        if 0 <= index < len(self.movie_names):
            return self.movie_names[index]
        return None

    # ── Factory ─────────────────────────────────────────────────────────

    @classmethod
    def from_discovery(cls, discovery: dict[str, Any]) -> Library:
        """Build a Library from a ``discover_library()`` result."""
        return cls(
            shows=discovery.get("shows") or {},
            movies=discovery.get("movies") or {},
            show_names=tuple(discovery.get("show_names") or ()),
            movie_names=tuple(discovery.get("movie_names") or ()),
            show_uuids=discovery.get("show_uuids") or {},
            movie_uuids=discovery.get("movie_uuids") or {},
            layout=discovery.get("layout", "legacy"),
        )

    @classmethod
    def empty(cls) -> Library:
        """Return an empty library."""
        return cls(
            shows={},
            movies={},
            show_names=(),
            movie_names=(),
            show_uuids={},
            movie_uuids={},
            layout="legacy",
        )

    # ── Mutations (return new instances) ────────────────────────────────

    def with_show_names(self, show_names: tuple[str, ...]) -> Library:
        return replace(self, show_names=show_names)

    def with_movie_names(self, movie_names: tuple[str, ...]) -> Library:
        return replace(self, movie_names=movie_names)
