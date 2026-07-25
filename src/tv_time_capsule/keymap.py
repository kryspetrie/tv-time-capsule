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

# ASCII-safe key display names (no unicode arrows)
KEY_NAMES = {
    pygame.K_LEFT: "Left",
    pygame.K_RIGHT: "Right",
    pygame.K_UP: "Up",
    pygame.K_DOWN: "Down",
    pygame.K_RETURN: "Enter",
    pygame.K_KP_ENTER: "NumEnter",
    pygame.K_ESCAPE: "Esc",
    pygame.K_BACKSPACE: "Backspace",
    pygame.K_SPACE: "Space",
    pygame.K_TAB: "Tab",
    pygame.K_DELETE: "Del",
    pygame.K_INSERT: "Ins",
    pygame.K_HOME: "Home",
    pygame.K_END: "End",
    pygame.K_PAGEUP: "PgUp",
    pygame.K_PAGEDOWN: "PgDn",
    pygame.K_F1: "F1",
    pygame.K_F2: "F2",
    pygame.K_F3: "F3",
    pygame.K_F4: "F4",
    pygame.K_F5: "F5",
    pygame.K_F6: "F6",
    pygame.K_F7: "F7",
    pygame.K_F8: "F8",
    pygame.K_F9: "F9",
    pygame.K_F10: "F10",
    pygame.K_F11: "F11",
    pygame.K_F12: "F12",
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
    pygame.K_a: "A",
    pygame.K_b: "B",
    pygame.K_c: "C",
    pygame.K_d: "D",
    pygame.K_e: "E",
    pygame.K_f: "F",
    pygame.K_g: "G",
    pygame.K_h: "H",
    pygame.K_i: "I",
    pygame.K_j: "J",
    pygame.K_k: "K",
    pygame.K_l: "L",
    pygame.K_m: "M",
    pygame.K_n: "N",
    pygame.K_o: "O",
    pygame.K_p: "P",
    pygame.K_q: "Q",
    pygame.K_r: "R",
    pygame.K_s: "S",
    pygame.K_t: "T",
    pygame.K_u: "U",
    pygame.K_v: "V",
    pygame.K_w: "W",
    pygame.K_x: "X",
    pygame.K_y: "Y",
    pygame.K_z: "Z",
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
    pygame.K_LSHIFT: "LShift",
    pygame.K_RSHIFT: "RShift",
    pygame.K_LCTRL: "LCtrl",
    pygame.K_RCTRL: "RCtrl",
    pygame.K_LALT: "LAlt",
    pygame.K_RALT: "RAlt",
    pygame.K_KP0: "Num0",
    pygame.K_KP1: "Num1",
    pygame.K_KP2: "Num2",
    pygame.K_KP3: "Num3",
    pygame.K_KP4: "Num4",
    pygame.K_KP5: "Num5",
    pygame.K_KP6: "Num6",
    pygame.K_KP7: "Num7",
    pygame.K_KP8: "Num8",
    pygame.K_KP9: "Num9",
    pygame.K_KP_PLUS: "Num+",
    pygame.K_KP_MINUS: "Num-",
    pygame.K_KP_MULTIPLY: "Num*",
    pygame.K_KP_DIVIDE: "Num/",
}


def key_display_name(keycode):
    return KEY_NAMES.get(keycode, f"Key({keycode})")


def load_keymap(config):
    """Build keymap from config, falling back to defaults."""
    saved = config.get("keymap", {})
    km = dict(DEFAULT_KEYMAP)
    for action in DEFAULT_KEYMAP:
        if action in saved:
            km[action] = saved[action]
    return km
