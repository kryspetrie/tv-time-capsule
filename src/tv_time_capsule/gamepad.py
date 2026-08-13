"""USB gamepad / joystick input with configurable bindings."""

from __future__ import annotations

from typing import Any

import pygame

AXIS_DEADZONE = 0.55
AXIS_COOLDOWN_MS = 180

GAMEPAD_ACTIONS = [
    ("up", "Up"),
    ("down", "Down"),
    ("left", "Left"),
    ("right", "Right"),
    ("select", "Select / pause"),
    ("back", "Back / stop"),
    ("next_episode", "Next episode"),
    ("prev_episode", "Previous episode"),
    ("stop_clear", "Stop & clear resume"),
]

DEFAULT_GAMEPAD_BINDINGS: dict[str, list[str]] = {
    "select": ["button-0", "button-7"],
    "back": ["button-1", "button-6"],
    "up": ["hat-up", "stick-up"],
    "down": ["hat-down", "stick-down"],
    "left": ["hat-left", "stick-left"],
    "right": ["hat-right", "stick-right"],
    "next_episode": ["button-5"],
    "prev_episode": ["button-4"],
    "stop_clear": [],
}

GAMEPAD_CONFIG_ROWS = 6

# Friendly labels for common SDL game-controller indices.
_BUTTON_LABELS = {
    0: "A / Cross",
    1: "B / Circle",
    2: "X / Square",
    3: "Y / Triangle",
    6: "Back / Select",
    7: "Start",
}


def binding_display_name(token: str) -> str:
    if token.startswith("button-"):
        try:
            index = int(token.split("-", 1)[1])
        except (IndexError, ValueError):
            return token
        label = _BUTTON_LABELS.get(index)
        return f"{label} ({token})" if label else token.replace("-", " ").title()
    if token.startswith("hat-"):
        return f"D-pad {token.split('-', 1)[1].title()}"
    if token.startswith("stick-"):
        return f"Left stick {token.split('-', 1)[1].title()}"
    return token


def format_action_bindings(bindings: dict[str, list[str]], action: str) -> str:
    tokens = bindings_for_action(bindings, action)
    if not tokens:
        return "?"
    return ", ".join(binding_display_name(token) for token in tokens)


def _normalize_token(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        token = value.strip().lower()
        return [token] if token else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            out.extend(_normalize_token(item))
        return out
    return []


def bindings_for_action(bindings: dict[str, list[str]], action: str) -> list[str]:
    if action in bindings:
        return list(_normalize_token(bindings[action]))
    return list(DEFAULT_GAMEPAD_BINDINGS.get(action, []))


def _bindings_equal(saved: list[str], default: list[str]) -> bool:
    return sorted(saved) == sorted(default)


def load_gamepad_bindings(config: dict[str, Any]) -> dict[str, list[str]]:
    """Build runtime gamepad bindings from config (per-action replace)."""
    gp_cfg = config.get("gamepad") or {}
    saved = gp_cfg.get("bindings") or {}
    bindings: dict[str, list[str]] = {}
    for action_id, default_tokens in DEFAULT_GAMEPAD_BINDINGS.items():
        if action_id in saved:
            bindings[action_id] = _normalize_token(saved[action_id])
        else:
            bindings[action_id] = list(default_tokens)
    return bindings


def serialize_gamepad_bindings(bindings: dict[str, list[str]]) -> dict[str, list[str]]:
    saved: dict[str, list[str]] = {}
    for action_id in DEFAULT_GAMEPAD_BINDINGS:
        tokens = bindings_for_action(bindings, action_id)
        default = DEFAULT_GAMEPAD_BINDINGS[action_id]
        if not _bindings_equal(tokens, default):
            saved[action_id] = list(tokens)
    return saved


def build_gamepad_lookup(bindings: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for action_id, _label in GAMEPAD_ACTIONS:
        for token in bindings_for_action(bindings, action_id):
            lookup[token] = action_id
    return lookup


def add_gamepad_binding(bindings: dict[str, list[str]], action: str, token: str) -> None:
    """Assign *token* to *action*, replacing previous bindings for that action."""
    if action not in DEFAULT_GAMEPAD_BINDINGS:
        return
    token = token.strip().lower()
    if not token:
        return
    for other_action in DEFAULT_GAMEPAD_BINDINGS:
        if other_action == action:
            continue
        tokens = bindings.get(other_action, [])
        if token in tokens:
            bindings[other_action] = [t for t in tokens if t != token]
    bindings[action] = [token]


def remove_gamepad_binding(bindings: dict[str, list[str]], action: str, token: str) -> None:
    tokens = list(bindings_for_action(bindings, action))
    if len(tokens) <= 1:
        return
    bindings[action] = [t for t in tokens if t != token]


def _hat_token(value: tuple[int, int]) -> str | None:
    hx, hy = value
    if hy == 1:
        return "hat-up"
    if hy == -1:
        return "hat-down"
    if hx == -1:
        return "hat-left"
    if hx == 1:
        return "hat-right"
    return None


def _stick_token(axis: int, value: float) -> str | None:
    if axis == 1:
        if value <= -AXIS_DEADZONE:
            return "stick-up"
        if value >= AXIS_DEADZONE:
            return "stick-down"
    elif axis == 0:
        if value <= -AXIS_DEADZONE:
            return "stick-left"
        if value >= AXIS_DEADZONE:
            return "stick-right"
    return None


def capture_binding_from_event(event: pygame.event.Event) -> str | None:
    """Return a binding token from a live gamepad event (for mapping UI)."""
    if event.type == pygame.JOYBUTTONDOWN:
        return f"button-{event.button}"
    if event.type == pygame.JOYHATMOTION:
        return _hat_token(event.value)
    if event.type == pygame.JOYAXISMOTION:
        return _stick_token(event.axis, event.value)
    return None


def gamepad_bindings_for_display(bindings: dict[str, list[str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for action_id, label in GAMEPAD_ACTIONS:
        rows.append(
            {
                "action": action_id,
                "label": label,
                "binding": format_action_bindings(bindings, action_id),
            }
        )
    return rows


class GamepadHandler:
    """Translate pygame joystick events into logical action names."""

    def __init__(
        self,
        enabled: bool = True,
        bindings: dict[str, list[str]] | None = None,
    ):
        self.enabled = enabled
        self._bindings = bindings or load_gamepad_bindings({})
        self._token_lookup = build_gamepad_lookup(self._bindings)
        self._joysticks: list[pygame.joystick.Joystick] = []
        self._last_hat: dict[int, tuple[int, int]] = {}
        self._axis_latch: dict[tuple[int, int], int] = {}
        self._axis_cooldown_until: dict[tuple[int, int], int] = {}

    def set_bindings(self, bindings: dict[str, list[str]]) -> None:
        self._bindings = bindings
        self._token_lookup = build_gamepad_lookup(bindings)

    @property
    def bindings(self) -> dict[str, list[str]]:
        return self._bindings

    def init(self) -> int:
        """Probe connected controllers. Returns count."""
        if not self.enabled:
            return 0
        pygame.joystick.init()
        count = pygame.joystick.get_count()
        self._joysticks = []
        for i in range(count):
            joy = pygame.joystick.Joystick(i)
            joy.init()
            self._joysticks.append(joy)
        return count

    @property
    def device_count(self) -> int:
        return len(self._joysticks)

    def event_to_action(self, event: pygame.event.Event) -> str | None:
        """Return a logical action id or None if the event is not handled."""
        if not self.enabled:
            return None

        token: str | None = None
        if event.type == pygame.JOYHATMOTION:
            token = self._hat_action_token(event.joy, event.value)
        elif event.type == pygame.JOYBUTTONDOWN:
            token = f"button-{event.button}"
        elif event.type == pygame.JOYAXISMOTION:
            token = self._axis_action_token(event.joy, event.axis, event.value)

        if not token:
            return None
        return self._token_lookup.get(token)

    def _hat_action_token(self, joy_id: int, value: tuple[int, int]) -> str | None:
        prev = self._last_hat.get(joy_id, (0, 0))
        self._last_hat[joy_id] = value
        if value == (0, 0) or value == prev:
            return None
        return _hat_token(value)

    def _axis_action_token(self, joy_id: int, axis: int, value: float) -> str | None:
        if axis not in (0, 1):
            return None

        now = pygame.time.get_ticks()
        key = (joy_id, axis)
        if now < self._axis_cooldown_until.get(key, 0):
            return None

        direction = 0
        if value <= -AXIS_DEADZONE:
            direction = -1
        elif value >= AXIS_DEADZONE:
            direction = 1
        else:
            self._axis_latch.pop(key, None)
            return None

        if self._axis_latch.get(key) == direction:
            return None

        self._axis_latch[key] = direction
        self._axis_cooldown_until[key] = now + AXIS_COOLDOWN_MS
        return _stick_token(axis, value)
