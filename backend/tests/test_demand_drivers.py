"""I3 driver-based demand forecast — analytical shape + energy checks."""
from __future__ import annotations

import pytest

from backend.app.demand_drivers import driver_demand_forecast


def _year_rows(year: int = 2023, days: int = 365, loads: dict[str, float] | None = None):
    """A full hourly year (8760 rows) of flat demand per column."""
    loads = loads or {"L": 100.0}
    rows = []
    months_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for m, nd in enumerate(months_days, start=1):
        for d in range(1, nd + 1):
            for h in range(24):
                rows.append({"snapshot": f"{year}-{m:02d}-{d:02d}T{h:02d}:00:00", **loads})
    return rows


def test_zero_drivers_is_a_pure_year_shift() -> None:
    rows = _year_rows()
    out, meta = driver_demand_forecast(rows, from_year=2023, to_year=2030)
    assert meta["macroFactor"] == pytest.approx(1.0)
    assert out[0]["snapshot"].startswith("2030-")
    assert all(o["L"] == pytest.approx(r["L"]) for o, r in zip(out, rows))


def test_macro_growth_scales_energy_and_preserves_shape() -> None:
    rows = _year_rows()
    # 1%/yr pop + 2%/yr GDP at elasticity 0.5 over 7 years.
    out, meta = driver_demand_forecast(
        rows, from_year=2023, to_year=2030, pop_growth_pct=1.0, gdp_growth_pct=2.0, gdp_elasticity=0.5,
    )
    g = (1.01 ** 7) * (1.01 ** 7)
    assert meta["macroFactor"] == pytest.approx(g, rel=1e-6)
    base = sum(r["L"] for r in rows)
    new = sum(o["L"] for o in out)
    assert new == pytest.approx(base * g, rel=1e-6)  # energy scales exactly
    # Flat base stays flat — the macro factor alone never reshapes.
    vals = {round(o["L"], 6) for o in out}
    assert len(vals) == 1


def test_heat_electrification_adds_exact_energy_winter_weighted() -> None:
    rows = _year_rows()
    out, meta = driver_demand_forecast(
        rows, from_year=2023, to_year=2023, heat_added_gwh=100.0,
    )
    added = sum(o["L"] for o in out) - sum(r["L"] for r in rows)
    assert added == pytest.approx(100_000.0, rel=1e-6)      # 100 GWh == 100k MWh, full year
    assert meta["heatAddedMwh"] == pytest.approx(100_000.0, rel=1e-6)
    by_stamp = {o["snapshot"]: o["L"] for o in out}
    # Winter evening gets far more added heat load than a summer evening…
    jan_evening = by_stamp["2023-01-15 18:00"] - 100.0
    jul_evening = by_stamp["2023-07-15 18:00"] - 100.0
    assert jan_evening > 10 * max(jul_evening, 1e-9)
    # …and the yearly peak moves to a winter hour (shape actually evolved).
    peak_stamp = max(out, key=lambda o: o["L"])["snapshot"]
    assert peak_stamp[5:7] in ("01", "12", "02")


def test_ev_charging_is_overnight_heavy() -> None:
    rows = _year_rows()
    out, _ = driver_demand_forecast(rows, from_year=2023, to_year=2023, ev_added_gwh=50.0)
    by_stamp = {o["snapshot"]: o["L"] for o in out}
    night = by_stamp["2023-06-10 02:00"] - 100.0
    midday = by_stamp["2023-06-10 12:00"] - 100.0
    shoulder = by_stamp["2023-06-10 08:00"] - 100.0
    assert night > midday > shoulder > 0
    added = sum(o["L"] for o in out) - sum(r["L"] for r in rows)
    assert added == pytest.approx(50_000.0, rel=1e-6)


def test_added_load_splits_by_column_share() -> None:
    rows = _year_rows(loads={"big": 300.0, "small": 100.0})
    out, _ = driver_demand_forecast(rows, from_year=2023, to_year=2023, ev_added_gwh=40.0)
    added_big = sum(o["big"] for o in out) - 300.0 * len(rows)
    added_small = sum(o["small"] for o in out) - 100.0 * len(rows)
    assert added_big == pytest.approx(3 * added_small, rel=1e-6)  # 75% / 25% split


def test_partial_window_scales_annual_energy() -> None:
    rows = _year_rows()[: 24 * 7]  # one week
    out, meta = driver_demand_forecast(rows, from_year=2023, to_year=2023, ev_added_gwh=87.6)
    # 87.6 GWh/yr × (168 h / 8760 h) = 1680 MWh in the window.
    assert meta["evAddedMwh"] == pytest.approx(1680.0, rel=1e-6)
    added = sum(o["L"] for o in out) - 100.0 * len(rows)
    assert added == pytest.approx(1680.0, rel=1e-6)


def test_endpoint_via_session() -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    c = TestClient(app)
    sid = "test_i3_drivers"
    rows = _year_rows()[: 24 * 2]
    model = {
        "loads": [{"name": "L", "bus": "b"}],
        "loads-p_set": rows,
        "snapshots": [{"snapshot": r["snapshot"]} for r in rows],
    }
    assert c.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200
    r = c.post("/api/session/snapshots/driver-forecast", json={
        "fromYear": 2023, "toYear": 2035, "popGrowthPct": 1.0,
        "heatAddedGWh": 10.0, "evAddedGWh": 5.0, "sessionId": sid,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["snapshots"] == len(rows)
    assert body["macroFactor"] == pytest.approx(1.01 ** 12, rel=1e-6)
    page = c.get(f"/api/session/sheet/loads-p_set?session_id={sid}&limit=5").json()
    assert page["rows"][0]["snapshot"].startswith("2035-")
    c.post(f"/api/session/clear?session_id={sid}")
