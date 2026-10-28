"""Technology data for the P2X chains: loader, parameter overrides and unit helpers.

The defaults live in ``technologies.json`` (nothing is hard-coded in Python):
every parameter carries ``value``, ``unit``, ``source`` (document, locator,
year), ``costYear`` / ``currency`` and a ``verified`` flag (``file`` = read from
the pinned upstream file by the generator, ``derived``, ``literature-recalled``
or ``assumption``). ``RAGNAROK_P2X_TECHNOLOGIES_FILE`` points the app at another
file with the same schema.

Units are explicit strings on every value (no bare floats cross a module
boundary without one); the conversions the chains need are the few functions
below, each documented with its units.

Algorithm (annualised fixed cost with FOM folded into the overnight cost):
    $$K_{eq} = K\\,\\Bigl(1 + \\frac{f}{a(r,L)}\\Bigr),\\qquad a(r,L)=\\frac{r(1+r)^L}{(1+r)^L-1}$$
    ASCII: K_eq = K * (1 + f / a(r, L)); a = r (1+r)^L / ((1+r)^L - 1).
    K = overnight cost (EUR per unit capacity), f = fixed O&M (fraction of K per year),
    r = discount rate (1/a), L = lifetime (a). The app annualises ``capital_cost`` with
    ``a(r, L)`` and pro-rates it to the modelled window, so K_eq * a = K * (a + f) is the
    annual capital-plus-FOM charge per unit capacity.
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...pypsa.utils.annuity import annuity_factor

BUNDLED_FILE = Path(__file__).with_name("technologies.json")
ENV_FILE = "RAGNAROK_P2X_TECHNOLOGIES_FILE"


def technologies_path() -> Path:
    """The data file in use: ``RAGNAROK_P2X_TECHNOLOGIES_FILE`` or the bundled one."""
    named = os.environ.get(ENV_FILE, "").strip()
    return Path(named).expanduser() if named else BUNDLED_FILE


@lru_cache(maxsize=4)
def _load(path: str, stamp: float) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("schema") != 1 or "technologies" not in data:
        raise ValueError(f"{path}: not a P2X technologies file (schema 1 expected).")
    return data


def load_technologies() -> dict[str, Any]:
    """The parsed data file (cached per path and modification time)."""
    path = technologies_path()
    return _load(str(path), path.stat().st_mtime)


def constants() -> dict[str, float]:
    """Numeric constants of the data file, keyed by name (units are in the key)."""
    return {k: float(v["value"]) for k, v in load_technologies()["constants"].items()}


def default_discount_rate() -> float:
    """Default discount rate (1/a) when the caller gives none."""
    return float(load_technologies()["defaults"]["discount_rate"]["value"])


def parameter_defaults() -> dict[str, dict[str, float]]:
    """``{technology: {parameter: value}}`` of the data file."""
    return {
        tech: {name: float(p["value"]) for name, p in body["parameters"].items()}
        for tech, body in load_technologies()["technologies"].items()
    }


def resolve_parameters(overrides: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    """Defaults with dotted-key overrides applied (``"electrolyser_aec.capex": 600``).

    Raises:
        ValueError: an unknown technology or parameter, or a non-numeric value.
    """
    params = parameter_defaults()
    for key, raw in (overrides or {}).items():
        tech, _, name = str(key).partition(".")
        if tech not in params or name not in params[tech]:
            raise ValueError(f"Unknown P2X parameter {key!r}. See GET /api/p2x/technologies for the keys.")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter {key!r} must be a number, got {raw!r}.") from exc
        if not math.isfinite(value):
            raise ValueError(f"Parameter {key!r} must be finite.")
        params[tech][name] = value
    return params


def catalogue(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The full data file for the API, with effective values when ``overrides`` is given."""
    data = load_technologies()
    effective = resolve_parameters(overrides)
    techs: dict[str, Any] = {}
    for tech, body in data["technologies"].items():
        techs[tech] = {
            **{k: v for k, v in body.items() if k != "parameters"},
            "parameters": {
                name: {**p, "default": p["value"], "value": effective[tech][name]}
                for name, p in body["parameters"].items()
            },
        }
    return {
        "schema": data["schema"],
        "title": data.get("title"),
        "file": str(technologies_path()),
        "basis": data["basis"],
        "sources": data["sources"],
        "constants": data["constants"],
        "defaults": data.get("defaults", {}),
        "technologies": techs,
    }


# ── conversions (every function states its units) ───────────────────────────────


def overnight_equivalent(capex: float, fom_pct: float, lifetime_years: float, discount_rate: float) -> float:
    """Overnight cost that, annualised by the app, equals ``capex * (a + fom)`` per year.

    Args:
        capex: overnight cost per unit capacity (EUR/MW or EUR/MWh).
        fom_pct: fixed O&M, percent of ``capex`` per year.
        lifetime_years: asset lifetime (a).
        discount_rate: discount rate (1/a).

    Returns:
        ``K_eq`` in the same unit as ``capex`` (see the module docstring).
    """
    a = annuity_factor(discount_rate, lifetime_years)
    return float(capex) * (1.0 + (float(fom_pct) / 100.0) / a)


def fom_share(fom_pct: float, lifetime_years: float, discount_rate: float) -> float:
    """Fraction of the annual fixed charge that is FOM: ``f / (a + f)`` (dimensionless)."""
    a = annuity_factor(discount_rate, lifetime_years)
    f = float(fom_pct) / 100.0
    return f / (a + f)


def lhv_efficiency(specific_energy_kwh_per_kg: float, h2_lhv_kwh_per_kg: float) -> float:
    """Electrolyser LHV efficiency (per unit) from kWh_el per kg H2 and the H2 LHV (kWh/kg)."""
    return float(h2_lhv_kwh_per_kg) / float(specific_energy_kwh_per_kg)


def kg_to_mwh(kg: float, lhv_kwh_per_kg: float) -> float:
    """Mass (kg) to energy (MWh, LHV)."""
    return float(kg) * float(lhv_kwh_per_kg) / 1000.0


def mwh_to_kg(mwh: float, lhv_kwh_per_kg: float) -> float:
    """Energy (MWh, LHV) to mass (kg)."""
    return float(mwh) * 1000.0 / float(lhv_kwh_per_kg)
