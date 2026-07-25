"""USB gamepad / joystick input → logical navigation actions."""

from __future__ import annotations

import pygame

# SDL game controller face buttons (Xbox / PlayStation style via SDL mapping)
_BTN_SELECT = 0  # A / Cross
_BTN_BACK = 1    # B / Circle
_BTN_GUIDE = 6    # Back / Select on many pads
_BTN_START = 7

AXIS_DEADZONE = 0.55
AXIS_COOLDOWN_MS = 180


class GamepadHandler:
    """Translate pygame joystick events into keymap action names."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._joysticks: list[pygame.joystick.Joystick] = []
        self._last_hat: dict[int, tuple[int, int]] = {}
        self._axis_latch: dict[tuple[int, int], int] = {}
        self._axis_cooldown_until: dict[tuple[int, int], int] = {}

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

        if event.type == pygame.JOYHATMOTION:
            return self._hat_action(event.joy, event.value)

        if event.type == pygame.JOYBUTTONDOWN:
            return self._button_action(event.button)

        if event.type == pygame.JOYAXISMOTION:
            return self._axis_action(event.joy, event.axis, event.value)

        return None

    def _button_action(self, button: int) -> str | None:
        if button in (_BTN_SELECT, _BTN_START):
            return "select"
        if button in (_BTN_BACK, _BTN_GUIDE):
            return "back"
        return None

    def _hat_action(self, joy_id: int, value: tuple[int, int]) -> str | None:
        prev = self._last_hat.get(joy_id, (0, 0))
        self._last_hat[joy_id] = value
        if value == (0, 0):
            return None
        if value == prev:
            return None
        hx, hy = value
        if hy == 1:
            return "up"
        if hy == -1:
            return "down"
        if hx == -1:
            return "left"
        if hx == 1:
            return "right"
        return None

    def _axis_action(self, joy_id: int, axis: int, value: float) -> str | None:
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

        if axis == 1:
            return "up" if direction == -1 else "down"
        return "left" if direction == -1 else "right"
