"""Unit tests for the Library aggregate."""

from __future__ import annotations

import unittest

from tv_time_capsule.library import Library


class LibraryTests(unittest.TestCase):
    """Tests for Library construction and properties."""

    def test_empty_library(self) -> None:
        lib = Library.empty()
        self.assertEqual(lib.layout, "legacy")
        self.assertEqual(lib.shows, {})
        self.assertEqual(lib.movies, {})
        self.assertEqual(lib.show_names, ())
        self.assertEqual(lib.movie_names, ())
        self.assertFalse(lib.has_shows)
        self.assertFalse(lib.has_movies)
        self.assertEqual(lib.show_count, 0)
        self.assertEqual(lib.movie_count, 0)

    def test_from_discovery_split(self) -> None:
        discovery = {
            "layout": "split",
            "shows": {"Bluey": {"seasons": {1: {"episodes": []}}}},
            "movies": {"Big Hero": {"title": "Big Hero", "path": "/m/Big Hero.mp4"}},
            "show_names": ["Bluey"],
            "movie_names": ["Big Hero"],
            "show_uuids": {"Bluey": "uuid-1"},
            "movie_uuids": {"Big Hero": "uuid-2"},
        }
        lib = Library.from_discovery(discovery)
        self.assertTrue(lib.is_split)
        self.assertTrue(lib.has_shows)
        self.assertTrue(lib.has_movies)
        self.assertEqual(lib.show_count, 1)
        self.assertEqual(lib.movie_count, 1)

    def test_from_discovery_shows_only(self) -> None:
        discovery = {
            "layout": "shows_only",
            "shows": {"Bluey": {}},
            "movies": {},
            "show_names": ["Bluey"],
            "movie_names": [],
            "show_uuids": {"Bluey": "uuid-1"},
            "movie_uuids": {},
        }
        lib = Library.from_discovery(discovery)
        self.assertTrue(lib.is_shows_only)
        self.assertFalse(lib.is_split)
        self.assertFalse(lib.is_movies_only)

    def test_from_discovery_movies_only(self) -> None:
        discovery = {
            "layout": "movies_only",
            "shows": {},
            "movies": {"Big Hero": {"title": "Big Hero"}},
            "show_names": [],
            "movie_names": ["Big Hero"],
            "show_uuids": {},
            "movie_uuids": {"Big Hero": "uuid-2"},
        }
        lib = Library.from_discovery(discovery)
        self.assertTrue(lib.is_movies_only)
        self.assertFalse(lib.has_shows)
        self.assertTrue(lib.has_movies)

    def test_from_discovery_handles_missing_keys(self) -> None:
        discovery = {"layout": "legacy"}
        lib = Library.from_discovery(discovery)
        self.assertEqual(lib.shows, {})
        self.assertEqual(lib.movies, {})
        self.assertEqual(lib.show_names, ())
        self.assertEqual(lib.movie_names, ())

    def test_immutable(self) -> None:
        lib = Library.empty()
        with self.assertRaises(Exception):
            lib.layout = "split"  # type: ignore[misc]

    def test_with_show_names_returns_new_instance(self) -> None:
        lib = Library.empty()
        lib2 = lib.with_show_names(("Bluey", "Bingo"))
        self.assertEqual(lib.show_names, ())
        self.assertEqual(lib2.show_names, ("Bluey", "Bingo"))
        self.assertIsNot(lib, lib2)

    def test_with_movie_names_returns_new_instance(self) -> None:
        lib = Library.empty()
        lib2 = lib.with_movie_names(("Big Hero",))
        self.assertEqual(lib.movie_names, ())
        self.assertEqual(lib2.movie_names, ("Big Hero",))

    def test_show_uuid_lookup(self) -> None:
        lib = Library(
            shows={"Bluey": {}},
            movies={},
            show_names=("Bluey",),
            movie_names=(),
            show_uuids={"Bluey": "abc-123"},
            movie_uuids={},
            layout="shows_only",
        )
        self.assertEqual(lib.show_uuid("Bluey"), "abc-123")
        self.assertIsNone(lib.show_uuid("Nonexistent"))

    def test_movie_uuid_lookup(self) -> None:
        lib = Library(
            shows={},
            movies={"Big Hero": {"title": "Big Hero"}},
            show_names=(),
            movie_names=("Big Hero",),
            show_uuids={},
            movie_uuids={"Big Hero": "def-456"},
            layout="movies_only",
        )
        self.assertEqual(lib.movie_uuid("Big Hero"), "def-456")
        self.assertIsNone(lib.movie_uuid("Nonexistent"))

    def test_show_by_uuid(self) -> None:
        lib = Library(
            shows={"Bluey": {"seasons": {1: {}}}},
            movies={},
            show_names=("Bluey",),
            movie_names=(),
            show_uuids={"Bluey": "abc-123"},
            movie_uuids={},
            layout="shows_only",
        )
        result = lib.show_by_uuid("abc-123")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["seasons"], {1: {}})
        self.assertIsNone(lib.show_by_uuid("nonexistent"))

    def test_movie_by_uuid(self) -> None:
        lib = Library(
            shows={},
            movies={"Big Hero": {"title": "Big Hero"}},
            show_names=(),
            movie_names=("Big Hero",),
            show_uuids={},
            movie_uuids={"Big Hero": "def-456"},
            layout="movies_only",
        )
        result = lib.movie_by_uuid("def-456")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["title"], "Big Hero")
        self.assertIsNone(lib.movie_by_uuid("nonexistent"))

    def test_show_name_by_uuid(self) -> None:
        lib = Library(
            shows={"Bluey": {}},
            movies={},
            show_names=("Bluey",),
            movie_names=(),
            show_uuids={"Bluey": "abc-123"},
            movie_uuids={},
            layout="shows_only",
        )
        self.assertEqual(lib.show_name_by_uuid("abc-123"), "Bluey")
        self.assertIsNone(lib.show_name_by_uuid("nonexistent"))

    def test_movie_key_by_uuid(self) -> None:
        lib = Library(
            shows={},
            movies={"Big Hero": {"title": "Big Hero"}},
            show_names=(),
            movie_names=("Big Hero",),
            show_uuids={},
            movie_uuids={"Big Hero": "def-456"},
            layout="movies_only",
        )
        self.assertEqual(lib.movie_key_by_uuid("def-456"), "Big Hero")
        self.assertIsNone(lib.movie_key_by_uuid("nonexistent"))

    def test_show_at_index(self) -> None:
        lib = Library(
            shows={"Bluey": {}, "Bingo": {}},
            movies={},
            show_names=("Bluey", "Bingo"),
            movie_names=(),
            show_uuids={"Bluey": "u1", "Bingo": "u2"},
            movie_uuids={},
            layout="shows_only",
        )
        self.assertEqual(lib.show_at_index(0), "Bluey")
        self.assertEqual(lib.show_at_index(1), "Bingo")
        self.assertIsNone(lib.show_at_index(2))
        self.assertIsNone(lib.show_at_index(-1))

    def test_movie_at_index(self) -> None:
        lib = Library(
            shows={},
            movies={"Big Hero": {"title": "Big Hero"}},
            show_names=(),
            movie_names=("Big Hero",),
            show_uuids={},
            movie_uuids={"Big Hero": "u1"},
            layout="movies_only",
        )
        self.assertEqual(lib.movie_at_index(0), "Big Hero")
        self.assertIsNone(lib.movie_at_index(1))

    def test_get_show(self) -> None:
        lib = Library(
            shows={"Bluey": {"seasons": {1: {}}}},
            movies={},
            show_names=("Bluey",),
            movie_names=(),
            show_uuids={"Bluey": "u1"},
            movie_uuids={},
            layout="shows_only",
        )
        self.assertIsNotNone(lib.get_show("Bluey"))
        self.assertIsNone(lib.get_show("Nonexistent"))

    def test_get_movie(self) -> None:
        lib = Library(
            shows={},
            movies={"Big Hero": {"title": "Big Hero"}},
            show_names=(),
            movie_names=("Big Hero",),
            show_uuids={},
            movie_uuids={"Big Hero": "u1"},
            layout="movies_only",
        )
        self.assertIsNotNone(lib.get_movie("Big Hero"))
        self.assertIsNone(lib.get_movie("Nonexistent"))


if __name__ == "__main__":
    unittest.main()
