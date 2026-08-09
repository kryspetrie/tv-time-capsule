"""Choose which weather presentation provider to use.

Default product path is **native** (custom pygame Retro Weather). Live Chrome
screencast providers (``twc``, ``ws4kp``) are opt-in. ``auto`` resolves to
``native`` on all platforms (kept for older configs / the in-app picker).
"""

from __future__ import annotations

from typing import Any, Literal

ProviderId = Literal["auto", "twc", "ws4kp", "native"]
ResolvedProvider = Literal["twc", "ws4kp", "native"]


def normalize_provider(raw: Any) -> ProviderId:
    text = str(raw or "native").strip().lower()
    if text in ("twc", "weather.com", "retro", "weather.com/retro"):
        return "twc"
    if text in ("ws4kp", "weatherstar", "weatherstar4000"):
        return "ws4kp"
    if text in ("auto",):
        return "auto"
    if text in ("native", "pygame", "local"):
        return "native"
    return "native"


def resolve_provider(
    weather_cfg: dict[str, Any] | None,
    *,
    force_weak_arm: bool | None = None,
) -> ResolvedProvider:
    """Map config ``weather.provider`` to a concrete presenter id.

    ``force_weak_arm`` is accepted for back-compat with older tests/callers; it
    no longer changes ``auto`` (always native). Live modes require an explicit
    ``twc`` / ``ws4kp`` provider.
    """
    del force_weak_arm  # retained for API compatibility
    cfg = weather_cfg if isinstance(weather_cfg, dict) else {}
    choice = normalize_provider(cfg.get("provider"))
    if choice in ("twc", "ws4kp", "native"):
        return choice  # type: ignore[return-value]
    # auto → native (custom channel); enable live via provider=twc|ws4kp
    return "native"
