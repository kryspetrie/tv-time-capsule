"""Key binding defaults, multi-key aliases, and helpers."""

from __future__ import annotations

from typing import Any

import pygame

KEY_ACTIONS = [
    ("up", "Up"),
    ("down", "Down"),
    ("left", "Left"),
    ("right", "Right"),
    ("select", "Select / pause"),
    ("back", "Back / stop"),
    ("quit", "Quit"),
    ("help", "Help screen"),
    ("reset", "Reset watch status"),
    ("keymap_reset", "Reset key bindings"),
    ("keymap_remove", "Remove key binding"),
    ("kids_mode_toggle", "Kids / parent mode"),
    ("footer_hints_toggle", "Toggle status bar"),
    ("letter_menu", "Alphabet jump menu"),
    ("kids_tag_toggle", "Tag for kids mode"),
    ("kids_view_toggle", "Kids card/compact view"),
    ("kids_carousel_toggle", "Kids carousel view"),
    ("key_config", "Key configuration"),
    ("gamepad_config", "Gamepad configuration"),
    ("safe_zone", "Safe zone setup"),
    ("cache_cancel", "Cancel playback cache"),
    ("digit_0", "Channel 0"),
    ("digit_1", "Channel 1"),
    ("digit_2", "Channel 2"),
    ("digit_3", "Channel 3"),
    ("digit_4", "Channel 4"),
    ("digit_5", "Channel 5"),
    ("digit_6", "Channel 6"),
    ("digit_7", "Channel 7"),
    ("digit_8", "Channel 8"),
    ("digit_9", "Channel 9"),
    ("large_text_toggle", "Large text on/off"),
    ("high_contrast_toggle", "High contrast on/off"),
    ("play_all_unwatched", "Play all unwatched"),
]

DEFAULT_KEYMAP: dict[str, list[int]] = {
    "up": [pygame.K_UP],
    "down": [pygame.K_DOWN],
    "left": [pygame.K_LEFT],
    "right": [pygame.K_RIGHT],
    "select": [pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE],
    "back": [pygame.K_ESCAPE],
    "quit": [pygame.K_q],
    "help": [pygame.K_h],
    "reset": [pygame.K_r],
    "keymap_reset": [pygame.K_F3],
    "keymap_remove": [pygame.K_DELETE],
    "kids_mode_toggle": [pygame.K_TAB],
    "footer_hints_toggle": [pygame.K_F5],
    "letter_menu": [pygame.K_l],
    "kids_tag_toggle": [pygame.K_k],
    "kids_view_toggle": [pygame.K_v],
    "key_config": [pygame.K_F2],
    "gamepad_config": [pygame.K_F4],
    "safe_zone": [pygame.K_z],
    "cache_cancel": [pygame.K_c],
    "kids_carousel_toggle": [pygame.K_c],
    "digit_0": [pygame.K_0, pygame.K_KP0],
    "digit_1": [pygame.K_1, pygame.K_KP1],
    "digit_2": [pygame.K_2, pygame.K_KP2],
    "digit_3": [pygame.K_3, pygame.K_KP3],
    "digit_4": [pygame.K_4, pygame.K_KP4],
    "digit_5": [pygame.K_5, pygame.K_KP5],
    "digit_6": [pygame.K_6, pygame.K_KP6],
    "digit_7": [pygame.K_7, pygame.K_KP7],
    "digit_8": [pygame.K_8, pygame.K_KP8],
    "digit_9": [pygame.K_9, pygame.K_KP9],
    "large_text_toggle": [pygame.K_F6],
    "high_contrast_toggle": [pygame.K_F7],
    "play_all_unwatched": [pygame.K_p],
}

KEY_CONFIG_ROWS = 6

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

# Canonical config.json names (no angle brackets). Also accepts legacy pygame ints.
CONFIG_NAME_TO_CODE: dict[str, int] = {
    "left-arrow": pygame.K_LEFT,
    "right-arrow": pygame.K_RIGHT,
    "kp-enter": pygame.K_KP_ENTER,
    "esc": pygame.K_ESCAPE,
    "return": pygame.K_RETURN,
}
CODE_TO_CONFIG_NAME: dict[int, str] = {}

for code, label in KEY_NAMES.items():
    if label.startswith("<") and label.endswith(">"):
        name = label[1:-1]
    else:
        name = label
    CONFIG_NAME_TO_CODE.setdefault(name, code)
    CODE_TO_CONFIG_NAME.setdefault(code, name)

CODE_TO_CONFIG_NAME[pygame.K_KP_ENTER] = "kp-enter"


def key_display_name(keycode: int) -> str:
    return KEY_NAMES.get(keycode, f"<key-{keycode}>")


def key_code_to_config_name(keycode: int) -> str:
    return CODE_TO_CONFIG_NAME.get(keycode, f"key-{keycode}")


def config_name_to_key_code(name: str) -> int | None:
    if not isinstance(name, str):
        return None
    key = name.strip().lower()
    if not key:
        return None
    return CONFIG_NAME_TO_CODE.get(key)


def _normalize_binding(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        code = config_name_to_key_code(value)
        return [code] if code is not None else []
    if isinstance(value, (list, tuple)):
        out: list[int] = []
        for item in value:
            out.extend(_normalize_binding(item))
        return out
    return []


def keys_for_action(keymap: dict[str, Any], action: str) -> list[int]:
    if action in keymap:
        return list(_normalize_binding(keymap[action]))
    return list(DEFAULT_KEYMAP.get(action, []))


def key_matches(keymap: dict[str, Any], key: int, action: str) -> bool:
    return key in keys_for_action(keymap, action)


def build_key_lookup(keymap: dict[str, Any]) -> dict[int, str]:
    lookup: dict[int, str] = {}
    for action_id, _label in KEY_ACTIONS:
        for code in keys_for_action(keymap, action_id):
            lookup[code] = action_id
    return lookup


def action_for_key(keymap: dict[str, Any], key: int) -> str | None:
    return build_key_lookup(keymap).get(key)


def digit_for_key(keymap: dict[str, Any], key: int) -> int | None:
    for digit in range(10):
        if key_matches(keymap, key, f"digit_{digit}"):
            return digit
    return None


def format_action_keys(keymap: dict[str, Any], action: str) -> str:
    """Format bindings for compact UI display.

    Physically distinct keys that have the same user-facing meaning, such as
    Return and keypad Enter, are shown once. Config serialization keeps them
    distinct so both keys remain bound.
    """
    keys = keys_for_action(keymap, action)
    if not keys:
        return "?"
    labels: list[str] = []
    seen: set[str] = set()
    for code in keys:
        label = key_display_name(code)
        if label.startswith("<") and label.endswith(">"):
            label = label[1:-1]
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return " / ".join(labels)


def _bindings_equal(saved: list[int], default: list[int]) -> bool:
    return sorted(saved) == sorted(default)


def serialize_keymap(keymap: dict[str, Any]) -> dict[str, list[str]]:
    """Write human-readable key names for config.json.

    Only actions that differ from defaults are written. An empty list means the
    action was explicitly unbound (replace), not “use default”.
    """
    saved: dict[str, list[str]] = {}
    for action_id in DEFAULT_KEYMAP:
        bindings = keys_for_action(keymap, action_id)
        default = DEFAULT_KEYMAP[action_id]
        if _bindings_equal(bindings, default):
            continue
        names: list[str] = []
        seen: set[str] = set()
        for code in bindings:
            name = key_code_to_config_name(code)
            if name not in seen:
                seen.add(name)
                names.append(name)
        saved[action_id] = names
    return saved


def load_keymap(config: dict[str, Any]) -> dict[str, list[int]]:
    """Build runtime keymap from config.

    Each action listed in ``config["keymap"]`` fully **replaces** that action's
    defaults (not merged). An empty list unbinds the action. Actions omitted
    from config keep their defaults.
    """
    saved = config.get("keymap") or {}
    km: dict[str, list[int]] = {}
    for action_id, default_codes in DEFAULT_KEYMAP.items():
        if action_id in saved:
            km[action_id] = _normalize_binding(saved[action_id])
        else:
            km[action_id] = list(default_codes)
    return km


def add_binding(keymap: dict[str, list[int]], action: str, key: int) -> None:
    """Assign *key* to *action*, replacing any previous bindings for that action.

    If *key* was bound to another action, it is moved (removed from the other).
    Multi-key aliases are set via config arrays, not by stacking F2 captures.
    """
    if action not in DEFAULT_KEYMAP:
        return
    for other_action in DEFAULT_KEYMAP:
        if other_action == action:
            continue
        codes = keymap.get(other_action, [])
        if key in codes:
            keymap[other_action] = [code for code in codes if code != key]
    keymap[action] = [key]


def remove_binding(keymap: dict[str, list[int]], action: str, key: int) -> None:
    bindings = list(keys_for_action(keymap, action))
    if len(bindings) <= 1:
        return
    keymap[action] = [code for code in bindings if code != key]


def any_key_pressed(codes: list[int]) -> bool:
    if not codes:
        return False
    pressed = pygame.key.get_pressed()
    limit = len(pressed)
    return any(0 <= code < limit and pressed[code] for code in codes)


def keymap_for_display(keymap: dict[str, Any]) -> list[dict[str, str]]:
    """Action labels with human-readable bound keys."""
    rows: list[dict[str, str]] = []
    for action_id, label in KEY_ACTIONS:
        rows.append(
            {
                "action": action_id,
                "label": label,
                "key": format_action_keys(keymap, action_id),
            }
        )
    return rows
