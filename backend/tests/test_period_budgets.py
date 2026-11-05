"""Period budgets (``RAGNAROK_PeriodBudgets``) and whole-run limits under rolling horizon.

Baselines are worked by hand. The model: one bus, 80 MW flat load, 6-hourly snapshots (weight 6 h) over January
and February 2030 (124 + 112 = 236 snapshots, 1416 h). A free hydro unit (100 MW, 0/MWh) and gas at 50/MWh.
Hydro's monthly budgets (Jan 5000 MWh, Feb 3000 MWh) bind, so gas serves the rest:

    objective = 50 * (80 * 1416 - (5000 + 3000)) = 50 * 105 280 = 5 264 000

A rolling run must reach the same answer whatever the window length: each window gets what is left of the month's
budget, so the months' totals come out exactly at the budget, never above.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
from fastapi import HTTPException

from backend.pypsa.results import run_pypsa

STEP_H = 6
LOAD = 80.0
JAN, FEB = 5000.0, 3000.0
HOURS = 236 * STEP_H
OBJECTIVE = 50.0 * (LOAD * HOURS - (JAN + FEB))


def _model(budgets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    stamps = pd.date_range("2030-01-01", "2030-02-28 18:00", freq=f"{STEP_H}h")
    assert len(stamps) == 236
    return {
        "snapshots": [{"snapshot": s.isoformat(), "objective": STEP_H, "generators": STEP_H, "stores": STEP_H} for s in stamps],
        "buses": [{"name": "b"}],
        "carriers": [{"name": "hydro", "co2_emissions": 0.0}, {"name": "gas", "co2_emissions": 0.5}],
        "loads": [{"name": "L", "bus": "b", "p_set": LOAD}],
        "generators": [
            {"name": "hydro", "bus": "b", "carrier": "hydro", "p_nom": 100, "marginal_cost": 0},
            {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 1000, "marginal_cost": 50},
        ],
        "RAGNAROK_Schema": [{"ragnarok_schema_version": 4}],
        **({"RAGNAROK_PeriodBudgets": budgets} if budgets is not None else {}),
    }


MONTHLY = [
    {"name": "hydro-jan", "measure": "energy", "carrier": "hydro", "period": "2030-01", "sense": "<=", "value": JAN},
    {"name": "hydro-feb", "measure": "energy", "carrier": "hydro", "period": "2030-02", "sense": "<=", "value": FEB},
]


def _run(model: dict[str, Any], rolling: dict[str, Any] | None = None) -> dict[str, Any]:
    opts: dict[str, Any] = {"enableLoadShedding": False}
    if rolling:
        opts["rollingConfig"] = {"enabled": True, **rolling}
    return run_pypsa(model, {"carbonPrice": 0.0, "discountRate": 0.0}, opts)


def _monthly_energy(res: dict[str, Any], gen: str) -> dict[str, float]:
    rows = res["outputs"]["series"]["generators-p"]
    frame = pd.DataFrame(rows)
    frame["month"] = pd.to_datetime(frame["snapshot"]).dt.strftime("%Y-%m")
    return {m: float(g[gen].sum() * STEP_H) for m, g in frame.groupby("month")}


def _objective(res: dict[str, Any]) -> float:
    rows = res["outputs"]["series"]["generators-p"]
    frame = pd.DataFrame(rows)
    return float(frame["gas"].sum() * STEP_H * 50.0 + frame["hydro"].sum() * 0.0)


def test_single_solve_binds_each_month_exactly() -> None:
    res = _run(_model(MONTHLY))
    energy = _monthly_energy(res, "hydro")
    assert energy["2030-01"] == pytest.approx(JAN, rel=1e-6)
    assert energy["2030-02"] == pytest.approx(FEB, rel=1e-6)
    assert _objective(res) == pytest.approx(OBJECTIVE, rel=1e-6)


@pytest.mark.parametrize("horizon,overlap", [(124, 0), (59, 0), (40, 8)])
def test_rolling_windows_keep_every_month_at_its_budget(horizon: int, overlap: int) -> None:
    """Aligned (124 = January), misaligned (59) and overlapping (40 + 8) windows all give the single-solve answer."""
    res = _run(_model(MONTHLY), {"horizonSnapshots": horizon, "overlapSnapshots": overlap})
    energy = _monthly_energy(res, "hydro")
    assert energy["2030-01"] == pytest.approx(JAN, rel=1e-6)
    assert energy["2030-02"] == pytest.approx(FEB, rel=1e-6)
    assert _objective(res) == pytest.approx(OBJECTIVE, rel=1e-6)


def test_rolling_without_budgets_would_let_every_window_spend_the_month() -> None:
    """The failure being fixed: the same month limit applied to each window in full overspends."""
    res = _run(_model(None), {"horizonSnapshots": 59, "overlapSnapshots": 0})
    assert _monthly_energy(res, "hydro")["2030-01"] > JAN * 5


def test_rolling_co2_cap_is_tracked_not_refused() -> None:
    """A whole-run CO2 cap of 30 000 t, which rolling used to refuse. Hydro is limited to 20 MW, so 60 MW must come
    from gas (0.5 t/MWh, 50/MWh) or clean (0 t, 500/MWh): gas could make 60 * 1416 = 84 960 MWh = 42 480 t, so the
    cap binds at 30 000 t = 60 000 MWh of gas - in a single solve and in a 59-snapshot rolling run alike."""
    m = _model(None)
    m["generators"][0]["p_nom"] = 20
    m["carriers"].append({"name": "clean", "co2_emissions": 0.0})
    m["generators"].append({"name": "clean", "bus": "b", "carrier": "clean", "p_nom": 1000, "marginal_cost": 500})
    cap = 30_000.0
    m["global_constraints"] = [{"name": "co2", "type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": "<=", "constant": cap}]
    single = _run(m)
    rolled = _run(m, {"horizonSnapshots": 59, "overlapSnapshots": 0})
    for res in (single, rolled):
        frame = pd.DataFrame(res["outputs"]["series"]["generators-p"])
        assert float(frame["gas"].sum() * STEP_H * 0.5) == pytest.approx(cap, rel=1e-6)
    assert any("applied per window from what is left" in n for n in rolled.get("narrative", []))


def test_rolling_e_sum_max_is_tracked() -> None:
    m = _model(None)
    m["generators"][0]["e_sum_max"] = 9000.0
    res = _run(m, {"horizonSnapshots": 59, "overlapSnapshots": 0})
    total = sum(_monthly_energy(res, "hydro").values())
    assert total == pytest.approx(9000.0, rel=1e-6)


def test_emissions_budget_by_month() -> None:
    """Gas emits 0.5 t/MWh; a January emissions budget of 1000 t allows 2000 MWh of gas in January."""
    m = _model(None)
    m["generators"][0]["p_nom"] = 0  # no hydro: gas or clean only
    m["carriers"].append({"name": "clean", "co2_emissions": 0.0})
    m["generators"].append({"name": "clean", "bus": "b", "carrier": "clean", "p_nom": 1000, "marginal_cost": 500})
    m["RAGNAROK_PeriodBudgets"] = [{"name": "co2-jan", "measure": "emissions", "period": "2030-01", "value": 1000.0}]
    for rolling in (None, {"horizonSnapshots": 59, "overlapSnapshots": 0}):
        res = _run(m, rolling)
        assert _monthly_energy(res, "gas")["2030-01"] == pytest.approx(2000.0, rel=1e-6)
        assert _monthly_energy(res, "gas")["2030-02"] == pytest.approx(LOAD * 112 * STEP_H, rel=1e-6)  # unbounded


@pytest.mark.parametrize("row,fragment", [
    ({"measure": "energy", "period": "2030-01", "value": 1}, "needs a carrier or a generator"),
    ({"carrier": "hydro", "period": "2030-13", "value": 1}, "period"),
    ({"carrier": "hydro", "period": "2030-01", "value": "lots"}, "not a number"),
    ({"carrier": "hydro", "period": "2030-01", "value": 1, "sense": "<>"}, "sense"),
    ({"generator": "nope", "period": "2030-01", "value": 1}, "no generator named nope"),
])
def test_a_misread_row_stops_the_run(row: dict[str, Any], fragment: str) -> None:
    with pytest.raises(HTTPException) as ei:
        _run(_model([row]))
    assert ei.value.status_code == 400 and fragment in str(ei.value.detail)
