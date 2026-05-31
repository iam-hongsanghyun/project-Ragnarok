"""Carrier defaults + per-source fuel name mapping.

Each plant importer ships its own ``carrier_map.json`` mapping the upstream
fuel name (WRI GPPD ``primary_fuel``, GEM ``status_detail``, …) to a
Ragnarok carrier in the central ``carrier_defaults.json``. The per-source
file is small and source-specific; this module owns the cross-source
defaults table.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULTS_PATH = Path(__file__).resolve().parent / "carrier_defaults.json"


@lru_cache(maxsize=1)
def load_carrier_defaults() -> dict[str, dict[str, Any]]:
    raw = json.loads(_DEFAULTS_PATH.read_text())
    carriers = raw.get("carriers", {})
    if not isinstance(carriers, dict):
        raise RuntimeError("carrier_defaults.json: 'carriers' must be an object")
    return carriers


def carrier_defaults_for(carrier: str) -> dict[str, Any]:
    """Return defaults for ``carrier``, falling back to ``Other`` if unknown."""
    defaults = load_carrier_defaults()
    return dict(defaults.get(carrier) or defaults.get("Other") or {})


def map_fuel_to_carrier(
    fuel: str | None,
    *,
    mapping: dict[str, str],
    default: str = "Other",
) -> str:
    """Resolve an upstream fuel string to a Ragnarok carrier.

    Lookup is case-insensitive on the source key. Unknown fuels return
    ``default`` (caller's choice, almost always ``"Other"``).
    """
    if not fuel:
        return default
    key = str(fuel).strip().lower()
    for source_name, ragnarok_carrier in mapping.items():
        if source_name.strip().lower() == key:
            return ragnarok_carrier
    return default
