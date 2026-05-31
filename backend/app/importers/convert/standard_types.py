"""Voltage → electrical parameters lookup.

We reuse the existing PyPSA standard-types catalogue
(``frontend/Ragnarok_default/src/config/pypsa_standard_types.json``) — the
backend already mirrors the workbook schema from the same place, so this
keeps line-type defaults consistent with the rest of the app.

For OSM lines the typical voltages are 110 / 220 / 380 kV. The catalogue
contains AC line types whose names end with the voltage class (e.g.
``"243-AL1/39-ST1A 220.0"``). We pick a representative type per voltage and
expose ``line_params_for_voltage`` for the few common AC voltages.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

# Repo-root → frontend config dir; matches the path resolution in
# backend/pypsa/pypsa_schema.py.
_STANDARD_TYPES_PATH = (
    Path(__file__).resolve().parents[4]
    / "frontend"
    / "Ragnarok_default"
    / "src"
    / "config"
    / "pypsa_standard_types.json"
)


@lru_cache(maxsize=1)
def line_type_table() -> list[dict[str, Any]]:
    raw = json.loads(_STANDARD_TYPES_PATH.read_text())
    types = raw.get("line_types", [])
    if not isinstance(types, list):
        raise RuntimeError("pypsa_standard_types.json: 'line_types' must be a list")
    return types


def _voltage_from_type_name(name: str) -> float | None:
    """Trailing token of a standard-type name is the voltage in kV (e.g. 220.0)."""
    parts = name.strip().rsplit(" ", 1)
    if len(parts) != 2:
        return None
    try:
        return float(parts[1])
    except ValueError:
        return None


def default_line_type_for_voltage(v_nom_kv: float) -> dict[str, Any] | None:
    """Pick a representative AC overhead line type at the given voltage.

    Strategy: pick the catalogue entry with the largest ``i_nom`` (≈ highest
    current rating) at that voltage class; this matches the high-voltage
    trunk that OSM ``power=line`` typically maps to.
    """
    candidates = [
        t
        for t in line_type_table()
        if _voltage_from_type_name(str(t.get("name", ""))) == v_nom_kv
        and t.get("mounting") == "ol"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda t: float(t.get("i_nom", 0.0)))


def line_params_for_voltage(
    v_nom_kv: float,
    length_km: float,
    num_parallel: int = 1,
) -> dict[str, float]:
    """Compute ``r``, ``x``, ``b``, ``s_nom`` for a line at ``v_nom_kv``.

    Falls back to coarse defaults (a 220 kV overhead type) when the voltage
    has no matching entry in the standard-types table.
    """
    t = default_line_type_for_voltage(v_nom_kv)
    if t is None:
        # Generic fallback (rough 220 kV AC overhead line averages).
        r_per_km = 0.06
        x_per_km = 0.30
        c_per_km_nf = 11.5
        i_nom_ka = 1.0
    else:
        r_per_km = float(t.get("r_per_length", 0.06))
        x_per_km = float(t.get("x_per_length", 0.30))
        c_per_km_nf = float(t.get("c_per_length", 11.5))
        i_nom_ka = float(t.get("i_nom", 1.0))
    parallel = max(int(num_parallel), 1)
    # PyPSA convention: r, x, b are aggregated per circuit / parallel count.
    r = (r_per_km * length_km) / parallel
    x = (x_per_km * length_km) / parallel
    # b (S) ≈ 2π·f·C — with C in nF/km, f=50 Hz: 2π·50·C[nF]·length·1e-9.
    b = 2.0 * math.pi * 50.0 * c_per_km_nf * length_km * 1e-9 * parallel
    # s_nom (MVA) ≈ sqrt(3) · v_nom · i_nom · parallel
    s_nom = math.sqrt(3.0) * v_nom_kv * i_nom_ka * parallel
    return {"r": r, "x": x, "b": b, "s_nom": s_nom}
