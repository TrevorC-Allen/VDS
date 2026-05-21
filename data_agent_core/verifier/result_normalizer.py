"""Result normalization for comparing execution backends."""

from __future__ import annotations

from typing import Any


def normalize_value(value: Any, ndigits: int = 10) -> Any:
    """Normalize scalars, lists, and dicts for comparison."""

    if isinstance(value, float):
        return round(value, ndigits)
    if isinstance(value, list):
        return [normalize_value(item, ndigits=ndigits) for item in value]
    if isinstance(value, dict):
        return {key: normalize_value(value[key], ndigits=ndigits) for key in sorted(value)}
    return value
