"""Shared toy networks for the P2X tests (not collected: leading underscore)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app import fragment_merge
from backend.app.p2x.chains import build_chain

Model = dict[str, list[dict[str, Any]]]
SCENARIO = {"discountRate": 0.05, "carbonPrice": 0.0}


def stamps(start: str, hours: int) -> list[str]:
    return [str(t).replace(" ", "T") for t in pd.date_range(start, periods=hours, freq="h")]


def night_gas_network(start: str = "2030-01-01", hours: int = 48, *, build_year: int | None = 2030) -> Model:
    """Grid with 20 MW demand, wind (40 MW, 30 EUR/MWh, daytime only) and cheaper gas (20 EUR/MWh).

    Without matching an electrolyser prefers gas at every hour (20 < 30); matching to wind forces it onto the wind hours.
    """
    snaps = stamps(start, hours)
    wind: dict[str, Any] = {"name": "wind", "bus": "grid", "carrier": "wind", "p_nom": 40, "marginal_cost": 30}
    if build_year:
        wind["build_year"] = build_year
    return {
        "buses": [{"name": "grid", "carrier": "AC"}],
        "carriers": [{"name": "AC"}, {"name": "wind"}, {"name": "gas", "co2_emissions": 0.2}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [wind, {"name": "gas", "bus": "grid", "carrier": "gas", "p_nom": 300, "marginal_cost": 20}],
        "generators-p_max_pu": [{"snapshot": s, "wind": 1.0 if 8 <= pd.Timestamp(s).hour < 20 else 0.0} for s in snaps],
        "loads": [{"name": "demand", "bus": "grid", "p_set": 20}],
    }


def with_chain(base: Model, spec: dict[str, Any]) -> tuple[Model, dict[str, Any]]:
    built = build_chain(spec, base)
    return fragment_merge.merge_fragment(base, built["fragment"]), built


H2_SPEC: dict[str, Any] = {
    "chainId": "p2x", "products": ["H2"],
    "electrolyser": {"tech": "aec", "extendable": False, "pNom": 30, "applyAvailability": False, "buildYear": 2030},
    "storage": {"type": "tank", "extendable": True},
    "offtake": {"H2": {"mode": "flat", "mw": 5}},
    "designatedGenerators": ["wind"],
}


def series(result: dict[str, Any], sheet: str, name: str) -> list[float]:
    return [float(r[name]) for r in result["outputs"]["series"][sheet]]
