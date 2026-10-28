"""Shared toy networks for the plant tests (not collected: leading underscore)."""
from __future__ import annotations

from typing import Any

import pandas as pd

from backend.app import fragment_merge
from backend.app.plants import catalog

Model = dict[str, list[dict[str, Any]]]
SCENARIO = {"discountRate": 0.05, "carbonPrice": 0.0}


def stamps(hours: int, start: str = "2030-01-01") -> list[str]:
    return [str(t).replace(" ", "T") for t in pd.date_range(start, periods=hours, freq="h")]


def grid(hours: int = 24, load_mw: float = 100.0) -> Model:
    """One AC bus with a constant load and nothing else: every plant brings its own supply."""
    return {
        "buses": [{"name": "grid", "carrier": "AC"}],
        "carriers": [{"name": "AC"}],
        "snapshots": [{"snapshot": s} for s in stamps(hours)],
        "loads": [{"name": "demand", "bus": "grid", "p_set": load_mw}],
    }


def with_h2_window(model: Model, available_hours: int = 12, price: float = 10.0) -> Model:
    """An H2 bus fed by a supplier that is only available in the first ``available_hours`` snapshots."""
    snaps = [r["snapshot"] for r in model["snapshots"]]
    out = {k: list(v) for k, v in model.items()}
    out["buses"] = [*out["buses"], {"name": "h2", "carrier": "H2"}]
    out["carriers"] = [*out["carriers"], {"name": "H2", "co2_emissions": 0.0}]
    out["generators"] = [{"name": "h2_src", "bus": "h2", "carrier": "H2", "p_nom": 500, "marginal_cost": price}]
    out["generators-p_max_pu"] = [{"snapshot": s, "h2_src": 1.0 if i < available_hours else 0.0} for i, s in enumerate(snaps)]
    return out


def add_plant(model: Model, type_id: str, spec: dict[str, Any]) -> tuple[Model, dict[str, Any]]:
    built = catalog.build_plant(type_id, spec, model)
    return fragment_merge.merge_fragment(model, built["fragment"]), built


def series(res: dict[str, Any], sheet: str, name: str) -> list[float]:
    return [float(r[name]) for r in res["outputs"]["series"][sheet]]


def bundle(model: Model, res: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"model": model, "result": res, "options": options or {}, "scenario": SCENARIO}
