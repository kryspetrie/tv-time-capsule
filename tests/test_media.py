"""Unit tests for media discovery helpers."""

from __future__ import annotations

import os
import tempfile
import unittest

from tv_time_capsule.media import (
    directory_signature,
    discover_library,
    discover_movies,
    folder_season_info,
    is_media_present,
    parse_episode_name,
    parse_episode_number,
    parse_season_episode,
)


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00")


class MediaParseTests(unittest.TestCase):
    def test_parse_season_episode(self):
        self.assertEqual(parse_season_episode("s01e03 - Dance.mp4"), (1, 3))
        self.assertEqual(parse_season_episode("S02E11.mkv"), (2, 11))
        self.assertEqual(parse_season_episode("plain.mp4"), (None, None))

    def test_parse_episode_number(self):
        self.assertEqual(parse_episode_number("s01e05.mp4"), 5)
        self.assertEqual(parse_episode_number("03-intro.mp4"), 3)

    def test_parse_episode_name(self):
        self.assertEqual(parse_episode_name("s01e01 - Dancing.mp4"), "Dancing")
        self.assertEqual(parse_episode_name("02 - Swim.mp4"), "Swim")

    def test_folder_season_info(self):
        self.assertEqual(folder_season_info("s01", 1), (1, None))
        self.assertEqual(folder_season_info("Season 2", 1), (2, None))
        self.assertEqual(folder_season_info("Action", 3), (3, "Action"))


class MediaDiscoveryTests(unittest.TestCase):
    def test_discover_movies_flat_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "Zulu.mp4"))
            _touch(os.path.join(tmp, "Alpha.mp4"))
            _touch(os.path.join(tmp, "nested", "Middle.mp4"))
            movies = discover_movies([tmp])
            titles = [m["title"] for m in movies]
            self.assertEqual(titles, ["Alpha", "Middle", "Zulu"])

    def test_discover_library_split_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "split")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Big Hero", discovery["movies"])

    def test_discover_library_shows_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "shows_only")
            self.assertIn("Bluey", discovery["shows"])
            self.assertEqual(discovery["movies"], {})

    def test_discover_library_movies_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "movies_only")
            self.assertEqual(discovery["shows"], {})
            self.assertIn("Big Hero", discovery["movies"])

    def test_discover_library_legacy_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "Bluey", "s01", "s01e01.mp4"))
            discovery = discover_library(tmp)
            self.assertEqual(discovery["layout"], "legacy")
            self.assertIn("Bluey", discovery["shows"])


class UUIDDiscoveryTests(unittest.TestCase):
    """Tests for stable UUID assignment during library discovery."""

    def test_discover_library_assigns_show_uuids(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            discovery = discover_library(tmp, device_name="TestBox")
            self.assertIn("show_uuids", discovery)
            self.assertIn("Bluey", discovery["show_uuids"])
            uuid_val = discovery["show_uuids"]["Bluey"]
            self.assertTrue(len(uuid_val) > 0)
            # Should be a valid UUID string
            import uuid
            uuid.UUID(uuid_val)

    def test_discover_library_assigns_movie_uuids(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))
            discovery = discover_library(tmp, device_name="TestBox")
            self.assertIn("movie_uuids", discovery)
            self.assertIn("Big Hero", discovery["movie_uuids"])
            uuid_val = discovery["movie_uuids"]["Big Hero"]
            self.assertTrue(len(uuid_val) > 0)

    def test_discover_library_preserves_uuids_across_rescans(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            first = discover_library(tmp, device_name="TestBox")
            second = discover_library(tmp, device_name="TestBox")
            self.assertEqual(
                first["show_uuids"]["Bluey"],
                second["show_uuids"]["Bluey"],
            )

    def test_discover_library_writes_catalog_to_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))
            discover_library(tmp, device_name="TestBox")

            from pathlib import Path
            from tv_time_capsule.media_catalog_paths import (
                shows_catalog_path,
                movies_catalog_path,
            )
            shows_path = shows_catalog_path(Path(tmp), "TestBox")
            movies_path = movies_catalog_path(Path(tmp), "TestBox")
            self.assertTrue(shows_path.is_file(), f"Expected {shows_path} to exist")
            self.assertTrue(movies_path.is_file(), f"Expected {movies_path} to exist")

    def test_discover_library_new_show_gets_fresh_uuid(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            first = discover_library(tmp, device_name="TestBox")
            # Add a new show
            _touch(os.path.join(tmp, "shows", "Bingo", "s01", "s01e01.mp4"))
            second = discover_library(tmp, device_name="TestBox")
            self.assertIn("Bingo", second["show_uuids"])
            self.assertNotEqual(
                first["show_uuids"]["Bluey"],
                second["show_uuids"]["Bingo"],
            )


class MediaPresenceTests(unittest.TestCase):
    """Tests for is_media_present() detection."""

    def test_present_with_video_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "show.mp4"))
            self.assertTrue(is_media_present(tmp))

    def test_present_with_subdirectories(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "shows"))
            self.assertTrue(is_media_present(tmp))

    def test_present_with_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            from tv_time_capsule.media_catalog_paths import shows_catalog_path
            cat_path = shows_catalog_path(Path(tmp), "TestBox")
            cat_path.parent.mkdir(parents=True, exist_ok=True)
            cat_path.write_text('{"device_name":"TestBox","shows":[]}')
            self.assertTrue(is_media_present(tmp, "TestBox"))

    def test_present_empty_writable_directory(self):
        """Empty but writable directory → present (initial setup)."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(is_media_present(tmp))

    def test_absent_nonexistent_path(self):
        self.assertFalse(is_media_present("/nonexistent/path/12345"))

    def test_absent_stale_mount_with_empty_catalog_dir(self):
        """Empty .tv-time-capsule/{device}/ on stale mount → absent."""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            from tv_time_capsule.media_catalog_paths import catalog_device_dir
            dev_dir = catalog_device_dir(Path(tmp), "TestBox")
            dev_dir.mkdir(parents=True, exist_ok=True)
            # No catalog files, no media files → absent
            self.assertFalse(is_media_present(tmp, "TestBox"))

    def test_dotfiles_ignored_but_writable_root_still_present(self):
        """Dotfiles don't count as media, but writable root → present."""
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, ".hidden.mp4"))
            self.assertTrue(is_media_present(tmp))

    def test_dotdirs_ignored_but_writable_root_still_present(self):
        """Dotdirs don't count as media, but writable root → present."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".hidden_dir"))
            self.assertTrue(is_media_present(tmp))


class DirectorySignatureTests(unittest.TestCase):
    """Tests for directory_signature()."""

    def test_signature_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sig = directory_signature(tmp)
            self.assertEqual(sig, (0, 0, 0.0))

    def test_signature_nonexistent_path(self) -> None:
        sig = directory_signature("/nonexistent/path/12345")
        self.assertEqual(sig, (0, 0, 0.0))

    def test_signature_with_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "show.mp4"))
            sig = directory_signature(tmp)
            self.assertEqual(sig[0], 1)  # count
            self.assertGreater(sig[1], 0)  # size
            self.assertGreater(sig[2], 0.0)  # mtime

    def test_signature_unchanged_after_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "show.mp4"))
            sig1 = directory_signature(tmp)
            sig2 = directory_signature(tmp)
            self.assertEqual(sig1, sig2)

    def test_signature_changed_after_file_added(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "show.mp4"))
            sig1 = directory_signature(tmp)
            _touch(os.path.join(tmp, "show2.mp4"))
            sig2 = directory_signature(tmp)
            self.assertNotEqual(sig1, sig2)

    def test_signature_ignores_dotfiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, ".hidden.mp4"))
            sig = directory_signature(tmp)
            self.assertEqual(sig, (0, 0, 0.0))

    def test_signature_ignores_catalog_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "show.mp4"))
            sig1 = directory_signature(tmp)
            # Create a file inside .tv-time-capsule — should not affect signature
            cat_dir = os.path.join(tmp, ".tv-time-capsule", "TestBox")
            os.makedirs(cat_dir, exist_ok=True)
            _touch(os.path.join(cat_dir, "shows.json"))
            sig2 = directory_signature(tmp)
            self.assertEqual(sig1, sig2)

    def test_signature_ignores_non_video_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "readme.txt"))
            _touch(os.path.join(tmp, "poster.jpg"))
            sig = directory_signature(tmp)
            self.assertEqual(sig, (0, 0, 0.0))

    def test_signature_nested_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
            sig = directory_signature(tmp)
            self.assertEqual(sig[0], 1)
            self.assertGreater(sig[1], 0)


class CorruptCatalogProtectionTests(unittest.TestCase):
    """Tests for corrupt catalog protection during discovery."""

    def test_corrupt_catalog_not_overwritten(self) -> None:
        """Corrupt catalog file must be preserved, not overwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            from tv_time_capsule.media_catalog_paths import shows_catalog_path

            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))

            # Write a corrupt catalog
            cat_path = shows_catalog_path(Path(tmp), "TestBox")
            cat_path.parent.mkdir(parents=True, exist_ok=True)
            cat_path.write_text("{not valid json", encoding="utf-8")

            # Discovery should still work (in-memory only)
            discovery = discover_library(tmp, device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])

            # Corrupt file must be preserved
            self.assertEqual(
                cat_path.read_text(encoding="utf-8"),
                "{not valid json",
            )

    def test_discover_library_survives_corrupt_catalog(self) -> None:
        """Discovery should work even with a corrupt catalog."""
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path
            from tv_time_capsule.media_catalog_paths import shows_catalog_path

            _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))

            cat_path = shows_catalog_path(Path(tmp), "TestBox")
            cat_path.parent.mkdir(parents=True, exist_ok=True)
            cat_path.write_text("{corrupt", encoding="utf-8")

            discovery = discover_library(tmp, device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Bluey", discovery["show_uuids"])


if __name__ == "__main__":
    unittest.main()
