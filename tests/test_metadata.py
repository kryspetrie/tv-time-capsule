"""Unit tests for NFO and poster metadata helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tv_time_capsule.metadata import (
    find_folder_poster,
    parse_nfo,
    resolve_episode_title,
    resolve_nfo_thumb,
    resolve_show_thumbnail,
)


class MetadataTests(unittest.TestCase):
    def test_parse_nfo_tvshow(self):
        with tempfile.TemporaryDirectory() as tmp:
            nfo = Path(tmp) / "tvshow.nfo"
            nfo.write_text(
                """<?xml version="1.0"?>
                <tvshow>
                  <title>Bluey</title>
                  <plot>Australian kids show</plot>
                  <thumb>poster.jpg</thumb>
                </tvshow>""",
                encoding="utf-8",
            )
            meta = parse_nfo(nfo)
            self.assertEqual(meta["title"], "Bluey")
            self.assertEqual(meta["plot"], "Australian kids show")
            self.assertEqual(meta["thumb"], "poster.jpg")

    def test_find_folder_poster(self):
        with tempfile.TemporaryDirectory() as tmp:
            poster = Path(tmp) / "folder.jpg"
            poster.write_bytes(b"fake")
            self.assertEqual(find_folder_poster(tmp), str(poster))

    def test_resolve_show_thumbnail_from_nfo(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "poster.jpg").write_bytes(b"fake")
            Path(tmp, "tvshow.nfo").write_text(
                "<tvshow><thumb>poster.jpg</thumb></tvshow>", encoding="utf-8"
            )
            thumb = resolve_show_thumbnail(tmp, "Bluey")
            self.assertTrue(thumb.endswith("poster.jpg"))

    def test_resolve_nfo_thumb_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "art.png").write_bytes(b"x")
            self.assertTrue(
                resolve_nfo_thumb(tmp, "art.png").endswith("art.png")
            )

    def test_resolve_episode_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp) / "s01e01.mp4"
            ep.write_bytes(b"")
            nfo = Path(tmp) / "s01e01.nfo"
            nfo.write_text("<episodedetails><title>Dance Mode</title></episodedetails>")
            self.assertEqual(
                resolve_episode_title(str(ep), "s01e01"),
                "Dance Mode",
            )


if __name__ == "__main__":
    unittest.main()
