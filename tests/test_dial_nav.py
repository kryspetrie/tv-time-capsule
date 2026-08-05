"""Tests for dial timing classifier and page cursor helper."""

from __future__ import annotations

import unittest

from tv_time_capsule.dial_nav import (
    DialKind,
    classify_dial,
    dial_needs_more_input,
    page_cursor,
)
from tv_time_capsule.movie_nav import (
    first_letter_in_band,
    index_of_letter,
    letter_bucket,
    present_letters,
)
from tv_time_capsule.retro_tv_channel import (
    decade_slug_for_year,
    decade_slug_from_digits,
    url_for_decade,
)
from tv_time_capsule.test_patterns import is_show_list_test_dial


class DialNavTests(unittest.TestCase):
    def test_classify_actions(self):
        self.assertEqual(classify_dial("0").kind, DialKind.BACK)
        self.assertEqual(classify_dial("00").kind, DialKind.LETTER_MENU)
        self.assertEqual(classify_dial("01").kind, DialKind.PAGE_UP)
        self.assertEqual(classify_dial("02").kind, DialKind.PAGE_DOWN)
        self.assertEqual(classify_dial("03").kind, DialKind.INVALID)
        self.assertEqual(classify_dial("001").kind, DialKind.TEST_PATTERN)
        self.assertEqual(classify_dial("000").kind, DialKind.HIDDEN_GUIDE)
        self.assertEqual(classify_dial("004").kind, DialKind.WEATHER)
        self.assertEqual(classify_dial("1").kind, DialKind.CHANNEL)
        self.assertEqual(classify_dial("1").channel, 1)
        self.assertEqual(classify_dial("12").channel, 12)
        self.assertEqual(classify_dial("01").channel, None)
        self.assertEqual(classify_dial("010").kind, DialKind.INVALID)

    def test_classify_retro_tv_years(self):
        r = classify_dial("1999")
        self.assertEqual(r.kind, DialKind.RETRO_TV)
        self.assertEqual(r.decade, "90")
        self.assertIsNone(r.channel)

        r = classify_dial("1950")
        self.assertEqual(r.kind, DialKind.RETRO_TV)
        self.assertEqual(r.decade, "50")

        r = classify_dial("2000")
        self.assertEqual(r.kind, DialKind.RETRO_TV)
        self.assertEqual(r.decade, "00")

        r = classify_dial("2009")
        self.assertEqual(r.kind, DialKind.RETRO_TV)
        self.assertEqual(r.decade, "00")

        # Out of MyRetroTVs range → normal channel
        self.assertEqual(classify_dial("1949").kind, DialKind.CHANNEL)
        self.assertEqual(classify_dial("1949").channel, 1949)
        self.assertEqual(classify_dial("2010").kind, DialKind.CHANNEL)
        self.assertEqual(classify_dial("2010").channel, 2010)

        # Shorter numbers stay channels (not decades)
        self.assertEqual(classify_dial("90").kind, DialKind.CHANNEL)
        self.assertEqual(classify_dial("199").kind, DialKind.CHANNEL)

    def test_page_cursor_preserves_row(self):
        # Page size 4: items 0-3 visible, cursor on row 2 → next page row 2 = index 6
        self.assertEqual(page_cursor(2, 20, 4, 1), 6)
        self.assertEqual(page_cursor(6, 20, 4, -1), 2)
        self.assertEqual(page_cursor(0, 20, 4, -1), 0)
        self.assertEqual(page_cursor(18, 20, 4, 1), 18)

    def test_dial_needs_more_input(self):
        self.assertTrue(dial_needs_more_input("0"))
        self.assertTrue(dial_needs_more_input("00"))
        self.assertTrue(dial_needs_more_input("01"))
        self.assertTrue(dial_needs_more_input("02"))
        self.assertTrue(dial_needs_more_input("12"))
        self.assertTrue(dial_needs_more_input("1999"))
        self.assertFalse(dial_needs_more_input("001"))
        self.assertFalse(dial_needs_more_input("000"))
        self.assertFalse(dial_needs_more_input("004"))
        self.assertFalse(dial_needs_more_input("03"))

    def test_test_pattern_dials(self):
        self.assertTrue(is_show_list_test_dial("001"))
        self.assertTrue(is_show_list_test_dial("002"))
        self.assertTrue(is_show_list_test_dial("003"))
        self.assertFalse(is_show_list_test_dial("0"))
        self.assertFalse(is_show_list_test_dial("00"))
        self.assertFalse(is_show_list_test_dial("000"))


class RetroDecadeTests(unittest.TestCase):
    def test_decade_slug_for_year(self):
        self.assertIsNone(decade_slug_for_year(1949))
        self.assertIsNone(decade_slug_for_year(2010))
        self.assertEqual(decade_slug_for_year(1950), "50")
        self.assertEqual(decade_slug_for_year(1959), "50")
        self.assertEqual(decade_slug_for_year(1985), "80")
        self.assertEqual(decade_slug_for_year(1990), "90")
        self.assertEqual(decade_slug_for_year(1999), "90")
        self.assertEqual(decade_slug_for_year(2000), "00")
        self.assertEqual(decade_slug_for_year(2009), "00")

    def test_decade_slug_from_digits(self):
        self.assertEqual(decade_slug_from_digits("1999"), "90")
        self.assertIsNone(decade_slug_from_digits("90"))
        self.assertIsNone(decade_slug_from_digits("01990"))
        self.assertIsNone(decade_slug_from_digits("abcd"))

    def test_url_for_decade(self):
        self.assertEqual(url_for_decade("90"), "https://90s.myretrotvs.com/")
        self.assertEqual(url_for_decade("00"), "https://00s.myretrotvs.com/")


class LetterMenuTests(unittest.TestCase):
    def test_present_and_bands(self):
        titles = ["Alpha", "Beta", "Zebra", "123"]
        self.assertEqual(letter_bucket("Alpha"), "A")
        self.assertEqual(present_letters(titles), ["A", "B", "Z", "#"])
        self.assertEqual(first_letter_in_band(titles, "1"), "A")
        self.assertEqual(first_letter_in_band(titles, "9"), "Z")
        self.assertIsNone(first_letter_in_band(titles, "3"))
        self.assertEqual(index_of_letter(titles, "Z"), 2)


if __name__ == "__main__":
    unittest.main()
