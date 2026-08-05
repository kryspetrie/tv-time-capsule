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
