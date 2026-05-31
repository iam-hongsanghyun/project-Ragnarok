"""OSM ``voltage`` tag parser.

The tag is wildly inconsistent in the wild. Examples (from real OSM data):

- ``"110000"``           → 110 kV
- ``"110000;220000"``    → [110, 220] kV
- ``"110 kV"`` / ``"110kV"`` / ``"110 kv"`` → 110 kV
- ``"110000 V"``         → 110 kV
- ``"110,220"``          → [110, 220] kV
- ``"110"``              → 110 kV (lone bare numbers are conventionally kV)
- ``"0.4"``              → 0.4 kV (LV; ignored for transmission imports)
- ``""`` / ``None`` / ``"unknown"`` → None

The convention we use: any bare number ≥ 1000 is interpreted as volts (and
divided by 1000); anything smaller is taken as kV.
"""
from __future__ import annotations

import re

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_VOLTS_THRESHOLD = 1000.0


def _coerce_to_kv(raw: float) -> float:
    """A bare number ≥ 1000 is volts; below that, kV."""
    if raw >= _VOLTS_THRESHOLD:
        return raw / 1000.0
    return raw


def _maybe_float(token: str) -> float | None:
    token = token.strip()
    if not token:
        return None
    m = _NUM_RE.search(token.replace(",", "."))
    if m is None:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_voltage_kv(value: str | None) -> list[float]:
    """Parse a raw OSM ``voltage`` tag into a list of voltages in kV.

    Returns an empty list for missing / unparseable values. Each element is
    rounded to 4 decimal places to absorb floating-point noise.
    """
    if not value:
        return []
    text = str(value).strip().lower()
    if not text or text in {"unknown", "none", "n/a"}:
        return []
    # Strip explicit "kv" markers — the magnitude tells us anyway.
    text = text.replace("kv", "").replace("volts", "").replace("v", "")
    out: list[float] = []
    seen: set[float] = set()
    for chunk in re.split(r"[;,]", text):
        v = _maybe_float(chunk)
        if v is None:
            continue
        kv = round(_coerce_to_kv(v), 4)
        if kv <= 0:
            continue
        if kv in seen:
            continue
        seen.add(kv)
        out.append(kv)
    return out


def max_voltage_kv(value: str | None) -> float | None:
    """Convenience: max parsed voltage, or ``None`` if nothing parsed."""
    parsed = parse_voltage_kv(value)
    return max(parsed) if parsed else None
