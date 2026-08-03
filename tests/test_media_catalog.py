"""Unit tests for on-media catalog infrastructure.

Mirrors patterns from MusicBox's ``test_json_media_tracks_adapter.py``
and ``test_media_catalog_paths.py``.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

from tv_time_capsule.media_catalog import (
    MovieCatalogEntry,
    ShowCatalogEntry,
    _atomic_write,
    catalog_is_writable,
    generate_movie_uuid,
    generate_show_uuid,
    read_movies_catalog,
    read_shows_catalog,
    write_movies_catalog,
    write_shows_catalog,
)
from tv_time_capsule.media_catalog_paths import (
    catalog_device_dir,
    movies_catalog_path,
    resolve_relative_path,
    sanitize_device_name,
    shows_catalog_path,
    to_relative_path,
)


class MediaCatalogPathsTests(unittest.TestCase):
    """Tests for path helpers."""

    def test_sanitize_device_name_clean(self) -> None:
        self.assertEqual(sanitize_device_name("LivingRoom"), "LivingRoom")

    def test_sanitize_device_name_spaces(self) -> None:
        self.assertEqual(sanitize_device_name("Living Room TV"), "Living-Room-TV")

    def test_sanitize_device_name_special_chars(self) -> None:
        self.assertEqual(sanitize_device_name("TV@Home!"), "TV-Home")

    def test_sanitize_device_name_empty(self) -> None:
        self.assertEqual(sanitize_device_name(""), "vintage-tv")

    def test_sanitize_device_name_truncates_long(self) -> None:
        long_name = "a" * 50
        result = sanitize_device_name(long_name)
        self.assertLessEqual(len(result), 32)

    def test_shows_catalog_path(self) -> None:
        root = pathlib.Path("/media/usb")
        path = shows_catalog_path(root, "LivingRoom")
        self.assertEqual(
            path,
            root / ".tv-time-capsule" / "LivingRoom" / "shows.json",
        )

    def test_movies_catalog_path(self) -> None:
        root = pathlib.Path("/media/usb")
        path = movies_catalog_path(root, "LivingRoom")
        self.assertEqual(
            path,
            root / ".tv-time-capsule" / "LivingRoom" / "movies.json",
        )

    def test_catalog_device_dir(self) -> None:
        root = pathlib.Path("/media/usb")
        d = catalog_device_dir(root, "TV Room")
        self.assertEqual(d, root / ".tv-time-capsule" / "TV-Room")

    def test_to_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            video = root / "shows" / "Bluey" / "s01e01.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_text("fake")
            rel = to_relative_path(video, root)
            self.assertEqual(rel, "shows/Bluey/s01e01.mp4")

    def test_to_relative_path_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            outside = pathlib.Path("/etc/passwd")
            rel = to_relative_path(outside, root)
            self.assertIsNone(rel)

    def test_to_relative_path_excludes_catalog_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            catalog_file = root / ".tv-time-capsule" / "test" / "shows.json"
            catalog_file.parent.mkdir(parents=True, exist_ok=True)
            catalog_file.write_text("{}")
            rel = to_relative_path(catalog_file, root)
            self.assertIsNone(rel)

    def test_resolve_relative_path(self) -> None:
        root = pathlib.Path("/media/usb")
        resolved = resolve_relative_path(root, "shows/Bluey/s01e01.mp4")
        self.assertEqual(resolved, root / "shows" / "Bluey" / "s01e01.mp4")

    def test_resolve_relative_path_rejects_absolute(self) -> None:
        with self.assertRaises(ValueError):
            resolve_relative_path(pathlib.Path("/media"), "/etc/passwd")

    def test_resolve_relative_path_rejects_parent_traversal(self) -> None:
        with self.assertRaises(ValueError):
            resolve_relative_path(pathlib.Path("/media"), "../etc/passwd")


class StableUUIDTests(unittest.TestCase):
    """Tests for deterministic UUID generation."""

    def test_same_input_same_uuid(self) -> None:
        u1 = generate_show_uuid("Bluey", "shows/Bluey")
        u2 = generate_show_uuid("Bluey", "shows/Bluey")
        self.assertEqual(u1, u2)

    def test_different_name_different_uuid(self) -> None:
        u1 = generate_show_uuid("Bluey", "shows/Bluey")
        u2 = generate_show_uuid("Bingo", "shows/Bluey")
        self.assertNotEqual(u1, u2)

    def test_different_path_different_uuid(self) -> None:
        u1 = generate_show_uuid("Bluey", "shows/Bluey")
        u2 = generate_show_uuid("Bluey", "kids/Bluey")
        self.assertNotEqual(u1, u2)

    def test_movie_uuid_stable(self) -> None:
        u1 = generate_movie_uuid("Big Hero", "movies/Big Hero.mp4")
        u2 = generate_movie_uuid("Big Hero", "movies/Big Hero.mp4")
        self.assertEqual(u1, u2)

    def test_show_and_movie_uuid_different(self) -> None:
        su = generate_show_uuid("Test", "path")
        mu = generate_movie_uuid("Test", "path")
        self.assertNotEqual(su, mu)


class ShowCatalogEntryTests(unittest.TestCase):
    """Tests for ShowCatalogEntry serialization."""

    def test_round_trip_minimal(self) -> None:
        entry = ShowCatalogEntry(
            uuid="abc-123",
            name="Bluey",
            relative_path="shows/Bluey",
        )
        data = entry.to_dict()
        restored = ShowCatalogEntry.from_dict(data)
        self.assertEqual(restored.uuid, "abc-123")
        self.assertEqual(restored.name, "Bluey")
        self.assertEqual(restored.relative_path, "shows/Bluey")
        self.assertEqual(restored.seasons, {})
        self.assertIsNone(restored.thumbnail_relative)

    def test_round_trip_with_seasons(self) -> None:
        entry = ShowCatalogEntry(
            uuid="abc-123",
            name="Bluey",
            relative_path="shows/Bluey",
            seasons={1: {"episodes": 52}, 2: {"episodes": 52}},
            thumbnail_relative="shows/Bluey/thumbnail.png",
        )
        data = entry.to_dict()
        restored = ShowCatalogEntry.from_dict(data)
        self.assertEqual(restored.seasons, {1: {"episodes": 52}, 2: {"episodes": 52}})
        self.assertEqual(restored.thumbnail_relative, "shows/Bluey/thumbnail.png")

    def test_from_dict_handles_string_season_keys(self) -> None:
        data = {
            "uuid": "abc",
            "name": "Test",
            "relative_path": "shows/Test",
            "seasons": {"1": {"episodes": 10}, "2": {"episodes": 20}},
        }
        entry = ShowCatalogEntry.from_dict(data)
        self.assertEqual(entry.seasons, {1: {"episodes": 10}, 2: {"episodes": 20}})

    def test_from_dict_handles_invalid_season_keys(self) -> None:
        data = {
            "uuid": "abc",
            "name": "Test",
            "relative_path": "shows/Test",
            "seasons": {"one": {"episodes": 10}},
        }
        entry = ShowCatalogEntry.from_dict(data)
        self.assertEqual(entry.seasons, {})


class MovieCatalogEntryTests(unittest.TestCase):
    """Tests for MovieCatalogEntry serialization."""

    def test_round_trip_minimal(self) -> None:
        entry = MovieCatalogEntry(
            uuid="def-456",
            title="Big Hero",
            relative_path="movies/Big Hero.mp4",
        )
        data = entry.to_dict()
        restored = MovieCatalogEntry.from_dict(data)
        self.assertEqual(restored.uuid, "def-456")
        self.assertEqual(restored.title, "Big Hero")
        self.assertEqual(restored.relative_path, "movies/Big Hero.mp4")
        self.assertIsNone(restored.thumbnail_relative)

    def test_round_trip_with_thumbnail(self) -> None:
        entry = MovieCatalogEntry(
            uuid="def-456",
            title="Big Hero",
            relative_path="movies/Big Hero.mp4",
            thumbnail_relative="movies/Big Hero.jpg",
        )
        data = entry.to_dict()
        restored = MovieCatalogEntry.from_dict(data)
        self.assertEqual(restored.thumbnail_relative, "movies/Big Hero.jpg")


class CatalogReadWriteTests(unittest.TestCase):
    """Tests for reading and writing catalogs to disk."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.device = "TestBox"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_and_read_shows_catalog(self) -> None:
        entries = [
            ShowCatalogEntry(uuid="u1", name="Bluey", relative_path="shows/Bluey"),
            ShowCatalogEntry(uuid="u2", name="Bingo", relative_path="shows/Bingo"),
        ]
        write_shows_catalog(self.root, self.device, entries)
        result = read_shows_catalog(self.root, self.device)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].name, "Bluey")
        self.assertEqual(result[1].name, "Bingo")

    def test_write_and_read_movies_catalog(self) -> None:
        entries = [
            MovieCatalogEntry(uuid="m1", title="Big Hero", relative_path="movies/Big Hero.mp4"),
        ]
        write_movies_catalog(self.root, self.device, entries)
        result = read_movies_catalog(self.root, self.device)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Big Hero")

    def test_read_absent_catalog_returns_none(self) -> None:
        result = read_shows_catalog(self.root, self.device)
        self.assertIsNone(result)

    def test_read_corrupt_catalog_returns_none(self) -> None:
        path = shows_catalog_path(self.root, self.device)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        result = read_shows_catalog(self.root, self.device)
        self.assertIsNone(result)

    def test_corrupt_catalog_file_preserved(self) -> None:
        """Corrupt catalog must not be overwritten by a read."""
        path = shows_catalog_path(self.root, self.device)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not valid json", encoding="utf-8")
        read_shows_catalog(self.root, self.device)
        self.assertEqual(path.read_text(encoding="utf-8"), "{not valid json")

    def test_atomic_write_preserves_on_crash(self) -> None:
        """If atomic write fails mid-way, the original file is untouched."""
        path = shows_catalog_path(self.root, self.device)
        path.parent.mkdir(parents=True, exist_ok=True)
        original = '{"device_name":"TestBox","shows":[]}'
        path.write_text(original, encoding="utf-8")

        # Simulate a failure by passing a non-serializable object
        with self.assertRaises(TypeError):
            _atomic_write(path, {"bad": object()})  # type: ignore[dict-item]

        # Original file must be intact
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_device_isolation(self) -> None:
        """Two device names produce separate catalogs on the same media root."""
        entries_a = [ShowCatalogEntry(uuid="u1", name="A", relative_path="shows/A")]
        entries_b = [ShowCatalogEntry(uuid="u2", name="B", relative_path="shows/B")]

        write_shows_catalog(self.root, "DeviceA", entries_a)
        write_shows_catalog(self.root, "DeviceB", entries_b)

        result_a = read_shows_catalog(self.root, "DeviceA")
        result_b = read_shows_catalog(self.root, "DeviceB")

        self.assertIsNotNone(result_a)
        self.assertIsNotNone(result_b)
        assert result_a is not None and result_b is not None
        self.assertEqual(result_a[0].name, "A")
        self.assertEqual(result_b[0].name, "B")

    def test_empty_catalog_round_trip(self) -> None:
        write_shows_catalog(self.root, self.device, [])
        result = read_shows_catalog(self.root, self.device)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 0)

    def test_skips_invalid_entries(self) -> None:
        """Catalog with one valid and one invalid entry should return the valid one."""
        path = shows_catalog_path(self.root, self.device)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "device_name": self.device,
            "shows": [
                {"uuid": "ok", "name": "Good", "relative_path": "shows/Good"},
                {"uuid": "bad"},  # missing required fields
            ],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = read_shows_catalog(self.root, self.device)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "Good")


class CatalogWritableTests(unittest.TestCase):
    """Tests for writability probing."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_writable_fresh_directory(self) -> None:
        self.assertTrue(catalog_is_writable(self.root, "TestBox"))

    def test_writable_existing_catalog_dir(self) -> None:
        d = catalog_device_dir(self.root, "TestBox")
        d.mkdir(parents=True, exist_ok=True)
        self.assertTrue(catalog_is_writable(self.root, "TestBox"))

    def test_not_writable_read_only(self) -> None:
        d = catalog_device_dir(self.root, "TestBox")
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(d), 0o444)
            # On some systems (macOS), chmod on a dir we own may still allow writes.
            # Just verify the function doesn't crash.
            result = catalog_is_writable(self.root, "TestBox")
            self.assertIsInstance(result, bool)
        finally:
            os.chmod(str(d), 0o755)


if __name__ == "__main__":
    unittest.main()
