"""Key binding defaults and helpers."""

from __future__ import annotations

import pygame

KEY_ACTIONS = [
    ("up", "Up"),
    ("down", "Down"),
    ("left", "Left / Back"),
    ("right", "Right / Select"),
    ("select", "Select"),
    ("back", "Back / Stop"),
    ("reset", "Reset watch status"),
]

DEFAULT_KEYMAP = {
    "up": pygame.K_UP,
    "down": pygame.K_DOWN,
    "left": pygame.K_LEFT,
    "right": pygame.K_RIGHT,
    "select": pygame.K_RETURN,
    "back": pygame.K_ESCAPE,
    "reset": pygame.K_r,
}

# Human-readable key labels for UI (splash, key setup, web admin)
KEY_NAMES = {
    pygame.K_LEFT: "<left-arrow>",
    pygame.K_RIGHT: "<right-arrow>",
    pygame.K_UP: "<up>",
    pygame.K_DOWN: "<down>",
    pygame.K_RETURN: "<enter>",
    pygame.K_KP_ENTER: "<enter>",
    pygame.K_ESCAPE: "<escape>",
    pygame.K_BACKSPACE: "<backspace>",
    pygame.K_SPACE: "<space>",
    pygame.K_TAB: "<tab>",
    pygame.K_DELETE: "<delete>",
    pygame.K_INSERT: "<insert>",
    pygame.K_HOME: "<home>",
    pygame.K_END: "<end>",
    pygame.K_PAGEUP: "<page-up>",
    pygame.K_PAGEDOWN: "<page-down>",
    pygame.K_F1: "<f1>",
    pygame.K_F2: "<f2>",
    pygame.K_F3: "<f3>",
    pygame.K_F4: "<f4>",
    pygame.K_F5: "<f5>",
    pygame.K_F6: "<f6>",
    pygame.K_F7: "<f7>",
    pygame.K_F8: "<f8>",
    pygame.K_F9: "<f9>",
    pygame.K_F10: "<f10>",
    pygame.K_F11: "<f11>",
    pygame.K_F12: "<f12>",
    pygame.K_0: "0",
    pygame.K_1: "1",
    pygame.K_2: "2",
    pygame.K_3: "3",
    pygame.K_4: "4",
    pygame.K_5: "5",
    pygame.K_6: "6",
    pygame.K_7: "7",
    pygame.K_8: "8",
    pygame.K_9: "9",
    pygame.K_a: "a",
    pygame.K_b: "b",
    pygame.K_c: "c",
    pygame.K_d: "d",
    pygame.K_e: "e",
    pygame.K_f: "f",
    pygame.K_g: "g",
    pygame.K_h: "h",
    pygame.K_i: "i",
    pygame.K_j: "j",
    pygame.K_k: "k",
    pygame.K_l: "l",
    pygame.K_m: "m",
    pygame.K_n: "n",
    pygame.K_o: "o",
    pygame.K_p: "p",
    pygame.K_q: "q",
    pygame.K_r: "r",
    pygame.K_s: "s",
    pygame.K_t: "t",
    pygame.K_u: "u",
    pygame.K_v: "v",
    pygame.K_w: "w",
    pygame.K_x: "x",
    pygame.K_y: "y",
    pygame.K_z: "z",
    pygame.K_COMMA: ",",
    pygame.K_PERIOD: ".",
    pygame.K_SLASH: "/",
    pygame.K_SEMICOLON: ";",
    pygame.K_QUOTE: "'",
    pygame.K_BACKQUOTE: "`",
    pygame.K_MINUS: "-",
    pygame.K_EQUALS: "=",
    pygame.K_LEFTBRACKET: "[",
    pygame.K_RIGHTBRACKET: "]",
    pygame.K_BACKSLASH: "\\",
    pygame.K_LSHIFT: "<left-shift>",
    pygame.K_RSHIFT: "<right-shift>",
    pygame.K_LCTRL: "<left-ctrl>",
    pygame.K_RCTRL: "<right-ctrl>",
    pygame.K_LALT: "<left-alt>",
    pygame.K_RALT: "<right-alt>",
    pygame.K_KP0: "<num-0>",
    pygame.K_KP1: "<num-1>",
    pygame.K_KP2: "<num-2>",
    pygame.K_KP3: "<num-3>",
    pygame.K_KP4: "<num-4>",
    pygame.K_KP5: "<num-5>",
    pygame.K_KP6: "<num-6>",
    pygame.K_KP7: "<num-7>",
    pygame.K_KP8: "<num-8>",
    pygame.K_KP9: "<num-9>",
    pygame.K_KP_PLUS: "<num-+>",
    pygame.K_KP_MINUS: "<num-->",
    pygame.K_KP_MULTIPLY: "<num-*>",
    pygame.K_KP_DIVIDE: "<num-/>",
}


def key_display_name(keycode):
    return KEY_NAMES.get(keycode, f"<key-{keycode}>")


def keymap_for_display(keymap: dict[str, int]) -> list[dict[str, str]]:
    """Action labels with human-readable bound keys."""
    km = keymap or {}
    rows: list[dict[str, str]] = []
    for action_id, label in KEY_ACTIONS:
        code = km.get(action_id, DEFAULT_KEYMAP.get(action_id))
        rows.append(
            {
                "action": action_id,
                "label": label,
                "key": key_display_name(code) if code is not None else "?",
            }
        )
    return rows


def load_keymap(config):
    """Build keymap from config, falling back to defaults."""
    saved = config.get("keymap", {})
    km = dict(DEFAULT_KEYMAP)
    for action in DEFAULT_KEYMAP:
        if action in saved:
            km[action] = saved[action]
    return km
