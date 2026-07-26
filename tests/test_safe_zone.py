"""Tests for CRT safe zone parsing."""

from __future__ import annotations

import unittest

from tv_time_capsule.safe_zone import (
    UI_H,
    UI_W,
    SafeZoneMargins,
    SafeZoneOffset,
    adjust_margins_uniform,
    parse_safe_zone,
    parse_safe_zone_offset,
    playback_hud_rect,
    playback_hud_scale,
    playback_overlay_rect,
    playback_overlay_scale,
    safe_zone_apply_offset,
    safe_zone_canvas_size,
    safe_zone_enabled,
    safe_zone_frame,
    safe_zone_layout,
    safe_zone_rect,
)


class SafeZoneTests(unittest.TestCase):
    def test_default_off(self):
        margins = parse_safe_zone(None)
        self.assertFalse(safe_zone_enabled(margins))
        frame = safe_zone_frame(margins)
        self.assertEqual((frame.canvas_w, frame.canvas_h), (640, 480))
        self.assertEqual((frame.ui.x, frame.ui.y, frame.ui.w, frame.ui.h), (0, 0, 640, 480))

    def test_uniform_number(self):
        margins = parse_safe_zone(5)
        self.assertTrue(safe_zone_enabled(margins))
        frame = safe_zone_frame(margins)
        self.assertEqual(safe_zone_canvas_size(margins), (704, 528))
        self.assertEqual((frame.ui.x, frame.ui.y), (32, 24))
        self.assertEqual((frame.ui.w, frame.ui.h), (640, 480))

    def test_per_edge_dict(self):
        margins = parse_safe_zone({"top": 10, "bottom": 8, "left": 5, "right": 5})
        self.assertEqual(margins.top, 10.0)
        self.assertEqual(margins.bottom, 8.0)
        frame = safe_zone_frame(margins)
        self.assertEqual(frame.ui.y, 48)
        self.assertEqual(frame.canvas_h, 480 + 48 + 38)

    def test_margin_alias(self):
        margins = parse_safe_zone({"margin": 7})
        self.assertEqual(margins, SafeZoneMargins(7, 7, 7, 7))

    def test_clamps_high_values(self):
        margins = parse_safe_zone(40)
        self.assertEqual(margins.top, 25.0)

    def test_offset_parsing(self):
        offset = parse_safe_zone_offset({"offset_x": 12, "offset_y": -8})
        self.assertEqual(offset, SafeZoneOffset(12, -8))
        offset = parse_safe_zone_offset({"offset": {"x": 5, "y": 3}})
        self.assertEqual(offset, SafeZoneOffset(5, 3))
        offset = parse_safe_zone_offset({"offset": [10, -4]})
        self.assertEqual(offset, SafeZoneOffset(10, -4))

    def test_offset_shifts_ui_block(self):
        margins = parse_safe_zone(5)
        base = safe_zone_rect(margins)
        shifted = safe_zone_layout(margins, SafeZoneOffset(10, -6))
        self.assertEqual((shifted.w, shifted.h), (UI_W, UI_H))
        self.assertEqual(shifted.x, base.x + 10)
        self.assertEqual(shifted.y, base.y - 6)

    def test_offset_clamps_to_canvas(self):
        margins = parse_safe_zone({"top": 5, "bottom": 5, "left": 5, "right": 5})
        frame = safe_zone_frame(margins)
        self.assertEqual(frame.canvas_w, 704)
        self.assertEqual(frame.canvas_h, 528)
        shifted = safe_zone_layout(margins, SafeZoneOffset(200, 200))
        self.assertEqual(shifted.x + shifted.w, frame.canvas_w)
        self.assertEqual(shifted.y + shifted.h, frame.canvas_h)
        shifted = safe_zone_layout(margins, SafeZoneOffset(-200, -200))
        self.assertEqual(shifted.x, 0)
        self.assertEqual(shifted.y, 0)

    def test_adjust_margins_uniform(self):
        margins = parse_safe_zone(5)
        expanded = adjust_margins_uniform(margins, vertical=-1.0)
        self.assertEqual(expanded.top, 4.0)
        self.assertEqual(expanded.bottom, 4.0)
        self.assertEqual(expanded.left, 5.0)
        wider = adjust_margins_uniform(margins, horizontal=-1.0)
        self.assertEqual(wider.left, 4.0)
        self.assertEqual(wider.right, 4.0)

    def test_playback_overlay_inset(self):
        margins = parse_safe_zone(5)
        rect = playback_overlay_rect(margins)
        self.assertEqual((rect.x, rect.y, rect.w, rect.h), (32, 24, 576, 432))
        self.assertEqual(playback_overlay_scale(rect), 1.0)
        shifted = playback_overlay_rect(margins, SafeZoneOffset(8, -4))
        self.assertEqual((shifted.x, shifted.y), (40, 20))

    def test_playback_hud_on_extended_canvas(self):
        margins = parse_safe_zone(5)
        rect = playback_hud_rect(704, 528, margins)
        self.assertEqual((rect.x, rect.y, rect.w, rect.h), (32, 24, 640, 480))
        self.assertEqual(playback_hud_scale(rect, 704, 528), 1.0)


if __name__ == "__main__":
    unittest.main()
