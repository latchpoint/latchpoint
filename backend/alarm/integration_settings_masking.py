from __future__ import annotations

from collections.abc import Callable

Masker = Callable[[object], object]

_maskers: dict[str, Masker] = {}


def register_setting_masker(*, key: str, masker: Masker) -> None:
    """Register a masker function for a specific settings key."""
    if not isinstance(key, str) or not key:
        raise ValueError("key is required")
    _maskers[key] = masker


def mask_setting_value(*, key: str, value: object) -> object:
    """Mask a settings value using the registered masker, returning original on failure."""
    masker = _maskers.get(key)
    if not masker:
        return value
    try:
        return masker(value)
    except Exception:
        # Best-effort masking: never fail serialization because a masker failed.
        return value
