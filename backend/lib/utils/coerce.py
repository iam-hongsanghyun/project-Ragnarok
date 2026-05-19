from __future__ import annotations

from typing import Any

import numpy as np


def number(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if np.isnan(parsed) or np.isinf(parsed):
        return default
    return parsed


def text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    string = str(value).strip()
    return string if string else default


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).lower() in {"1", "true", "yes", "y"}
