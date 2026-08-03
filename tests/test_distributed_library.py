"""Integration tests for the distributed video library / config methodology.

Mirrors patterns from MusicBox's ``test_json_library_adapter.py``,
``test_composite_library_adapter.py``, and ``test_json_media_tracks_adapter.py``.

Tests cover:
- Full pipeline: discover → catalog write → rediscover → UUID stability
- Multi-device merge with separate catalogs
- Corrupt catalog on one device doesn't block others
- Relative path round-trip across rescans
- App-level _rescan_library with presence/signature/catalog integration
- Channel lineup + kids allowlist + library discovery together
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from tv_time_capsule.media import (
    directory_signature,
    discover_library,
    is_media_present,
)
from tv_time_capsule.media_catalog import (
    MovieCatalogEntry,
    ShowCatalogEntry,
    read_movies_catalog,
    read_shows_catalog,
    write_movies_catalog,
    write_shows_catalog,
)
from tv_time_capsule.media_catalog_paths import (
    movies_catalog_path,
    resolve_relative_path,
    shows_catalog_path,
    to_relative_path,
)
from tv_time_capsule.library import Library


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _touch(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00")


def _make_split_media(tmp: str) -> None:
    """Create a split-layout media tree with one show and one movie."""
    _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e01.mp4"))
    _touch(os.path.join(tmp, "shows", "Bluey", "s01", "s01e02.mp4"))
    _touch(os.path.join(tmp, "movies", "Big Hero.mp4"))


def _make_shows_only_media(tmp: str) -> None:
    """Create a shows-only media tree."""
    _touch(os.path.join(tmp, "shows", "Bingo", "s01", "s01e01.mp4"))


def _make_movies_only_media(tmp: str) -> None:
    """Create a movies-only media tree."""
    _touch(os.path.join(tmp, "movies", "Zulu.mp4"))


# ---------------------------------------------------------------------------
# 1. Full pipeline: discover → catalog write → rediscover → UUID stability
# ---------------------------------------------------------------------------


class TestFullPipeline(unittest.TestCase):
    """End-to-end tests for the discover → catalog → rediscover pipeline."""

    def test_discover_writes_catalog_to_media(self) -> None:
        """After discovery, catalog files exist on the media root."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discover_library(tmp, device_name="TestBox")

            root = Path(tmp)
            self.assertTrue(shows_catalog_path(root, "TestBox").is_file())
            self.assertTrue(movies_catalog_path(root, "TestBox").is_file())

    def test_catalog_contains_relative_paths(self) -> None:
        """Catalog entries use relative paths, not absolute."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discover_library(tmp, device_name="TestBox")

            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None
            self.assertEqual(len(shows), 1)
            self.assertEqual(shows[0].relative_path, "shows/Bluey")
            # Must not be absolute
            self.assertFalse(shows[0].relative_path.startswith("/"))

            movies = read_movies_catalog(root, "TestBox")
            self.assertIsNotNone(movies)
            assert movies is not None
            self.assertEqual(len(movies), 1)
            self.assertEqual(movies[0].relative_path, "movies/Big Hero.mp4")
            self.assertFalse(movies[0].relative_path.startswith("/"))

    def test_catalog_contains_season_summary(self) -> None:
        """Show catalog entries include season episode counts."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discover_library(tmp, device_name="TestBox")

            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None
            self.assertEqual(shows[0].seasons, {1: {"episode_count": 2}})

    def test_uuids_preserved_across_rescans(self) -> None:
        """UUIDs are stable when rediscovering the same media."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            first = discover_library(tmp, device_name="TestBox")
            second = discover_library(tmp, device_name="TestBox")

            self.assertEqual(
                first["show_uuids"]["Bluey"],
                second["show_uuids"]["Bluey"],
            )
            self.assertEqual(
                first["movie_uuids"]["Big Hero"],
                second["movie_uuids"]["Big Hero"],
            )

    def test_uuids_preserved_across_fresh_instance(self) -> None:
        """UUIDs survive when a completely new process reads the catalog."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            first = discover_library(tmp, device_name="TestBox")

            # Simulate a fresh process: read catalog directly, then rediscover
            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None
            self.assertEqual(shows[0].uuid, first["show_uuids"]["Bluey"])

            # Rediscover should match
            second = discover_library(tmp, device_name="TestBox")
            self.assertEqual(
                first["show_uuids"]["Bluey"],
                second["show_uuids"]["Bluey"],
            )

    def test_new_show_gets_fresh_uuid(self) -> None:
        """Adding a new show assigns a new UUID without breaking existing ones."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            first = discover_library(tmp, device_name="TestBox")

            # Add a new show
            _touch(os.path.join(tmp, "shows", "Bingo", "s01", "s01e01.mp4"))
            second = discover_library(tmp, device_name="TestBox")

            # Existing UUID preserved
            self.assertEqual(
                first["show_uuids"]["Bluey"],
                second["show_uuids"]["Bluey"],
            )
            # New show has a different UUID
            self.assertIn("Bingo", second["show_uuids"])
            self.assertNotEqual(
                first["show_uuids"]["Bluey"],
                second["show_uuids"]["Bingo"],
            )

    def test_removed_show_cleared_from_catalog(self) -> None:
        """When a show is removed from disk, it's gone from the catalog."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            _touch(os.path.join(tmp, "shows", "Bingo", "s01", "s01e01.mp4"))
            first = discover_library(tmp, device_name="TestBox")
            self.assertIn("Bingo", first["shows"])

            # Remove Bingo's files
            import shutil
            shutil.rmtree(os.path.join(tmp, "shows", "Bingo"))
            second = discover_library(tmp, device_name="TestBox")
            self.assertNotIn("Bingo", second["shows"])

            # Catalog should only have Bluey now
            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None
            self.assertEqual(len(shows), 1)
            self.assertEqual(shows[0].name, "Bluey")

    def test_relative_paths_resolve_correctly(self) -> None:
        """Relative paths in catalog resolve to the correct absolute paths."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discover_library(tmp, device_name="TestBox")

            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None

            resolved = resolve_relative_path(root, shows[0].relative_path)
            self.assertTrue(resolved.is_dir())
            self.assertEqual(resolved.name, "Bluey")

            movies = read_movies_catalog(root, "TestBox")
            self.assertIsNotNone(movies)
            assert movies is not None

            resolved = resolve_relative_path(root, movies[0].relative_path)
            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.name, "Big Hero.mp4")


# ---------------------------------------------------------------------------
# 2. Multi-device merge with separate catalogs
# ---------------------------------------------------------------------------


class TestMultiDeviceMerge(unittest.TestCase):
    """Tests for merging libraries from multiple media roots."""

    def test_two_devices_merge_shows(self) -> None:
        """Shows from two media roots are merged into one library."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            _make_split_media(tmp1)
            _make_shows_only_media(tmp2)

            discovery = discover_library([tmp1, tmp2], device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Bingo", discovery["shows"])
            self.assertIn("Big Hero", discovery["movies"])

    def test_two_devices_separate_catalogs(self) -> None:
        """Each media root gets its own catalog, not shared."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            _make_split_media(tmp1)
            _make_shows_only_media(tmp2)

            discover_library([tmp1, tmp2], device_name="TestBox")

            root1 = Path(tmp1)
            root2 = Path(tmp2)

            # Root 1 has both shows and movies catalogs
            s1 = read_shows_catalog(root1, "TestBox")
            m1 = read_movies_catalog(root1, "TestBox")
            self.assertIsNotNone(s1)
            self.assertIsNotNone(m1)
            assert s1 is not None and m1 is not None
            self.assertEqual(s1[0].name, "Bluey")
            self.assertEqual(m1[0].title, "Big Hero")

            # Root 2 only has shows catalog (no movies dir)
            s2 = read_shows_catalog(root2, "TestBox")
            self.assertIsNotNone(s2)
            assert s2 is not None
            self.assertEqual(s2[0].name, "Bingo")

    def test_two_devices_different_device_names(self) -> None:
        """Different device names produce isolated catalogs on the same root."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)

            discover_library(tmp, device_name="LivingRoom")
            discover_library(tmp, device_name="Bedroom")

            root = Path(tmp)
            # Both device catalogs exist
            self.assertTrue(shows_catalog_path(root, "LivingRoom").is_file())
            self.assertTrue(shows_catalog_path(root, "Bedroom").is_file())

            # They are independent
            lr = read_shows_catalog(root, "LivingRoom")
            br = read_shows_catalog(root, "Bedroom")
            self.assertIsNotNone(lr)
            self.assertIsNotNone(br)
            assert lr is not None and br is not None
            self.assertEqual(lr[0].name, "Bluey")
            self.assertEqual(br[0].name, "Bluey")

    def test_merge_preserves_uuids_per_device(self) -> None:
        """UUIDs from each device's catalog are preserved during merge."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            _make_split_media(tmp1)
            _make_shows_only_media(tmp2)

            first = discover_library([tmp1, tmp2], device_name="TestBox")
            second = discover_library([tmp1, tmp2], device_name="TestBox")

            self.assertEqual(first["show_uuids"]["Bluey"], second["show_uuids"]["Bluey"])
            self.assertEqual(first["show_uuids"]["Bingo"], second["show_uuids"]["Bingo"])

    def test_merge_with_one_empty_device(self) -> None:
        """Merging with an empty device doesn't break anything."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            _make_split_media(tmp1)
            # tmp2 is empty

            discovery = discover_library([tmp1, tmp2], device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Big Hero", discovery["movies"])

            # Empty device doesn't get a catalog written
            root2 = Path(tmp2)
            self.assertFalse(shows_catalog_path(root2, "TestBox").exists())


# ---------------------------------------------------------------------------
# 3. Corrupt catalog isolation
# ---------------------------------------------------------------------------


class TestCorruptCatalogIsolation(unittest.TestCase):
    """Tests for corrupt catalog handling across multiple devices."""

    def test_corrupt_on_one_device_doesnt_block_other(self) -> None:
        """A corrupt catalog on device A doesn't prevent discovery on device B."""
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            _make_split_media(tmp1)
            _make_shows_only_media(tmp2)

            # Corrupt the catalog on tmp1
            root1 = Path(tmp1)
            cat = shows_catalog_path(root1, "TestBox")
            cat.parent.mkdir(parents=True, exist_ok=True)
            cat.write_text("{not valid json", encoding="utf-8")

            # Discovery should still work
            discovery = discover_library([tmp1, tmp2], device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Bingo", discovery["shows"])

            # Corrupt file preserved
            self.assertEqual(cat.read_text(encoding="utf-8"), "{not valid json")

            # tmp2 catalog is fine
            root2 = Path(tmp2)
            s2 = read_shows_catalog(root2, "TestBox")
            self.assertIsNotNone(s2)
            assert s2 is not None
            self.assertEqual(s2[0].name, "Bingo")

    def test_corrupt_catalog_still_allows_in_memory_discovery(self) -> None:
        """Even with a corrupt catalog, in-memory discovery works."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)

            root = Path(tmp)
            cat = shows_catalog_path(root, "TestBox")
            cat.parent.mkdir(parents=True, exist_ok=True)
            cat.write_text("{corrupt", encoding="utf-8")

            discovery = discover_library(tmp, device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Bluey", discovery["show_uuids"])

    def test_corrupt_movies_catalog_isolated(self) -> None:
        """A corrupt movies catalog doesn't affect shows discovery."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)

            root = Path(tmp)
            mcat = movies_catalog_path(root, "TestBox")
            mcat.parent.mkdir(parents=True, exist_ok=True)
            mcat.write_text("{corrupt", encoding="utf-8")

            discovery = discover_library(tmp, device_name="TestBox")
            self.assertIn("Bluey", discovery["shows"])
            self.assertIn("Big Hero", discovery["movies"])

            # Movies catalog preserved
            self.assertEqual(mcat.read_text(encoding="utf-8"), "{corrupt")


# ---------------------------------------------------------------------------
# 4. Relative path round-trip across rescans
# ---------------------------------------------------------------------------


class TestRelativePathRoundTrip(unittest.TestCase):
    """Tests for relative path handling across discovery cycles."""

    def test_to_relative_path_round_trip(self) -> None:
        """to_relative_path produces paths that resolve back correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "shows" / "Bluey" / "s01" / "s01e01.mp4"
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_text("fake")

            rel = to_relative_path(video, root)
            self.assertEqual(rel, "shows/Bluey/s01/s01e01.mp4")

            resolved = resolve_relative_path(root, rel)
            self.assertEqual(resolved.resolve(), video.resolve())

    def test_catalog_relative_paths_survive_remount(self) -> None:
        """Catalog entries use relative paths that work after remount."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discover_library(tmp, device_name="TestBox")

            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None

            # Resolve the relative path — should point to the actual dir
            resolved = resolve_relative_path(root, shows[0].relative_path)
            self.assertTrue(resolved.is_dir())
            self.assertTrue((resolved / "s01" / "s01e01.mp4").is_file())

    def test_thumbnail_relative_path_in_catalog(self) -> None:
        """Thumbnail paths in catalog are relative when inside media root."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            # Add a thumbnail
            thumb = os.path.join(tmp, "shows", "Bluey", "thumbnail.png")
            _touch(thumb)

            discovery = discover_library(tmp, device_name="TestBox")

            root = Path(tmp)
            shows = read_shows_catalog(root, "TestBox")
            self.assertIsNotNone(shows)
            assert shows is not None
            self.assertEqual(
                shows[0].thumbnail_relative,
                "shows/Bluey/thumbnail.png",
            )

    def test_thumbnail_outside_root_not_in_catalog(self) -> None:
        """Thumbnails outside the media root are not stored as relative paths."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            # This thumbnail is outside the media root
            outside_thumb = "/tmp/outside_thumb.png"

            # We can't easily inject an outside thumbnail into discovery,
            # but we can verify to_relative_path returns None for outside paths.
            root = Path(tmp)
            rel = to_relative_path(Path(outside_thumb), root)
            self.assertIsNone(rel)


# ---------------------------------------------------------------------------
# 5. App-level _rescan_library integration
# ---------------------------------------------------------------------------


class TestAppRescanIntegration(unittest.TestCase):
    """Tests for the app-level rescan flow with presence/signature/catalog."""

    def setUp(self) -> None:
        # Ensure pygame is initialized for app tests
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        import pygame
        pygame.init()
        pygame.display.set_mode((800, 600))

    def test_rescan_discovers_split_library(self) -> None:
        """_rescan_library discovers shows and movies from a split layout."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            self.assertEqual(app.library_layout, "split")
            self.assertIn("Bluey", app.shows)
            self.assertIn("Big Hero", app.movies)
            self.assertTrue(app.library.has_shows)
            self.assertTrue(app.library.has_movies)

    def test_rescan_preserves_uuids(self) -> None:
        """UUIDs are stable across multiple rescans."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            uuid1 = app.show_uuids.get("Bluey")
            self.assertIsNotNone(uuid1)

            # Rescan again
            app._rescan_library()
            uuid2 = app.show_uuids.get("Bluey")
            self.assertEqual(uuid1, uuid2)

    def test_rescan_skips_when_media_absent(self) -> None:
        """_rescan_library preserves state when media is absent."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()
            self.assertIn("Bluey", app.shows)

            # Now point at a nonexistent path
            app.media_paths = ["/nonexistent/path/12345"]
            result = app._rescan_library()
            self.assertFalse(result)  # skipped
            # Library preserved
            self.assertIn("Bluey", app.shows)

    def test_rescan_skips_when_signature_unchanged(self) -> None:
        """_rescan_library skips when directory signatures haven't changed."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)

            # First rescan — should happen
            result1 = app._rescan_library()
            self.assertTrue(result1)

            # Second rescan — should skip (signature unchanged)
            result2 = app._rescan_library()
            self.assertFalse(result2)

    def test_rescan_runs_when_signature_changed(self) -> None:
        """_rescan_library runs when a file is added."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            # Add a new file
            _touch(os.path.join(tmp, "shows", "Bluey", "s02", "s02e01.mp4"))
            result = app._rescan_library()
            self.assertTrue(result)

    def test_rescan_builds_library_aggregate(self) -> None:
        """After rescan, the Library aggregate is correctly populated."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            lib = app.library
            self.assertEqual(lib.layout, "split")
            self.assertEqual(lib.show_count, 1)
            self.assertEqual(lib.movie_count, 1)
            self.assertEqual(lib.show_at_index(0), "Bluey")
            self.assertEqual(lib.movie_at_index(0), "Big Hero")
            self.assertEqual(lib.show_uuid("Bluey"), app.show_uuids["Bluey"])

    def test_rescan_writes_catalog_to_media(self) -> None:
        """After rescan, catalog files exist on the media root."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            root = Path(tmp)
            self.assertTrue(shows_catalog_path(root, app._device_name).is_file())
            self.assertTrue(movies_catalog_path(root, app._device_name).is_file())


# ---------------------------------------------------------------------------
# 6. Channel lineup + kids allowlist + library discovery together
# ---------------------------------------------------------------------------


class TestConfigIntegration(unittest.TestCase):
    """Tests for config (channels, kids) + library discovery integration."""

    def setUp(self) -> None:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        import pygame
        pygame.init()
        pygame.display.set_mode((800, 600))

    def test_channel_lineup_applied_after_rescan(self) -> None:
        """Channel lineup is rebuilt after rescan."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            # Channel maps should be populated
            self.assertIn("Bluey", app._show_channel)
            self.assertGreater(app._show_channel["Bluey"], 0)

    def test_movie_channels_applied_after_rescan(self) -> None:
        """Movie channel lineup is rebuilt after rescan."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            self.assertIn("Big Hero", app._movie_channel)
            self.assertGreater(app._movie_channel["Big Hero"], 0)

    def test_kids_allowlist_survives_rescan(self) -> None:
        """Kids allowlist entries persist across rescans."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            # Tag Bluey for kids
            app._kids_allowlist = {"shows": ["Bluey"], "movies": []}
            app._kids_mode_active = True

            # Rescan
            app._rescan_library()

            # Kids allowlist should still have Bluey
            self.assertIsNotNone(app._kids_allowlist)
            assert app._kids_allowlist is not None
            self.assertIn("Bluey", app._kids_allowlist.get("shows", []))

    def test_kids_filtered_names_after_rescan(self) -> None:
        """Kids filtered show/movie names are correct after rescan."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            _touch(os.path.join(tmp, "shows", "Bingo", "s01", "s01e01.mp4"))

            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            # Tag only Bluey for kids
            app._kids_allowlist = {"shows": ["Bluey"], "movies": []}
            app._kids_mode_active = True

            filtered = app._kids_filtered_show_names()
            self.assertIn("Bluey", filtered)
            self.assertNotIn("Bingo", filtered)

    def test_library_aggregate_reflects_kids_filtering(self) -> None:
        """Library aggregate is built from the full (unfiltered) discovery."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            # Library aggregate has all shows, regardless of kids mode
            lib = app.library
            self.assertEqual(lib.show_count, 1)
            self.assertEqual(lib.show_at_index(0), "Bluey")

    def test_channel_numbers_stable_across_rescans(self) -> None:
        """Channel numbers don't change on rescan with same content."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            ch1 = app._show_channel.get("Bluey")
            self.assertIsNotNone(ch1)

            app._rescan_library()
            ch2 = app._show_channel.get("Bluey")
            self.assertEqual(ch1, ch2)

    def test_device_name_used_for_catalog_isolation(self) -> None:
        """The app's _device_name is used for catalog path isolation."""
        from tv_time_capsule.app import TVTimeCapsule

        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            app = TVTimeCapsule([tmp], fullscreen=False, admin=False)
            app._rescan_library()

            root = Path(tmp)
            # Catalog should be under the app's device name
            self.assertTrue(
                shows_catalog_path(root, app._device_name).is_file()
            )


# ---------------------------------------------------------------------------
# 7. Library aggregate + discovery integration
# ---------------------------------------------------------------------------


class TestLibraryDiscoveryIntegration(unittest.TestCase):
    """Tests for Library aggregate construction from discovery results."""

    def test_library_from_discovery_split(self) -> None:
        """Library.from_discovery correctly handles split layout."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discovery = discover_library(tmp, device_name="TestBox")
            # discover_library returns movie_names but not show_names;
            # show_names is set by _apply_channel_lineup in the app.
            discovery["show_names"] = list(discovery["shows"].keys())
            lib = Library.from_discovery(discovery)

            self.assertTrue(lib.is_split)
            self.assertTrue(lib.has_shows)
            self.assertTrue(lib.has_movies)
            self.assertEqual(lib.show_count, 1)
            self.assertEqual(lib.movie_count, 1)

    def test_library_from_discovery_shows_only(self) -> None:
        """Library.from_discovery correctly handles shows_only layout."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_shows_only_media(tmp)
            discovery = discover_library(tmp, device_name="TestBox")
            discovery["show_names"] = list(discovery["shows"].keys())
            lib = Library.from_discovery(discovery)

            self.assertTrue(lib.is_shows_only)
            self.assertFalse(lib.has_movies)

    def test_library_from_discovery_movies_only(self) -> None:
        """Library.from_discovery correctly handles movies_only layout."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_movies_only_media(tmp)
            discovery = discover_library(tmp, device_name="TestBox")
            lib = Library.from_discovery(discovery)

            self.assertTrue(lib.is_movies_only)
            self.assertFalse(lib.has_shows)

    def test_library_uuid_lookups_work(self) -> None:
        """UUID lookups on Library work after discovery."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discovery = discover_library(tmp, device_name="TestBox")
            discovery["show_names"] = list(discovery["shows"].keys())
            lib = Library.from_discovery(discovery)

            show_uuid = lib.show_uuid("Bluey")
            self.assertIsNotNone(show_uuid)
            assert show_uuid is not None

            # Reverse lookup
            self.assertEqual(lib.show_name_by_uuid(show_uuid), "Bluey")
            self.assertIsNotNone(lib.show_by_uuid(show_uuid))

    def test_library_immutable_after_discovery(self) -> None:
        """Library remains immutable after construction from discovery."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_split_media(tmp)
            discovery = discover_library(tmp, device_name="TestBox")
            discovery["show_names"] = list(discovery["shows"].keys())
            lib = Library.from_discovery(discovery)

            with self.assertRaises(Exception):
                lib.layout = "legacy"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
