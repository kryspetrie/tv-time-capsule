"""OS keychain / keyring helpers for mount (and other) secrets.

Backends (via the ``keyring`` package):
  - macOS Keychain
  - Windows Credential Locker
  - Linux Secret Service (GNOME Keyring / KWallet) when a session is unlocked

Headless kiosk note: the login keyring is often locked without a desktop
session. Prefer NetworkManager *system* Wi‑Fi connections for networking, and
either unlockable keyring secrets or ``credentials`` files for mounts.
"""

from __future__ import annotations

from typing import Optional

KEYRING_SERVICE = "tv-time-capsule"


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError(
            "keyring package not installed (pip/poetry install keyring)"
        ) from exc
    return keyring


def get_secret(name: str) -> Optional[str]:
    """Return a secret stored under service tv-time-capsule / username ``name``."""
    if not name:
        return None
    try:
        return _keyring().get_password(KEYRING_SERVICE, name)
    except Exception as exc:  # backend missing / locked / dbus
        print(f"keyring read failed for {name!r}: {exc}", flush=True)
        return None


def set_secret(name: str, secret: str) -> None:
    _keyring().set_password(KEYRING_SERVICE, name, secret)


def delete_secret(name: str) -> None:
    try:
        _keyring().delete_password(KEYRING_SERVICE, name)
    except Exception as exc:
        # delete_password raises PasswordDeleteError if missing
        raise RuntimeError(f"could not delete keyring item {name!r}: {exc}") from exc


def resolve_password(entry: dict, *, field: str = "password") -> Optional[str]:
    """Resolve a password from explicit value, keyring name, or None.

    Config options (first match wins):
      - ``password``: literal (discouraged)
      - ``keyring``: keyring item name for the password
      - ``password_keyring``: alias of ``keyring``
    """
    if entry.get(field) is not None:
        return entry.get(field)
    key = entry.get("password_keyring") or entry.get("keyring")
    if key:
        return get_secret(str(key))
    return None


def resolve_username(entry: dict) -> Optional[str]:
    """Resolve username from config or optional ``username_keyring`` item."""
    if entry.get("username") is not None:
        return entry.get("username")
    key = entry.get("username_keyring")
    if key:
        return get_secret(str(key))
    return None
