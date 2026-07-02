"""M4 EV demand reshaping — energy conservation + region/time split."""
from __future__ import annotations

import pytest

from backend.app.ev_demand import ev_demand_adjustment


def _day_rows(loads: dict[str, float]):
    return [{"snapshot": f"2030-01-01T{h:02d}:00:00", **loads} for h in range(24)]


def test_energy_conservation() -> None:
    rows = _day_rows({"L": 100.0})
    # 100k vehicles × 7 kWh/day × 1 day = 700 MWh.
    out, meta = ev_demand_adjustment(rows, fleet_size=100_000, kwh_per_vehicle_day=7.0)
    assert meta["addedMwh"] == pytest.approx(700.0)
    added = sum(o["L"] for o in out) - 2400.0
    assert added == pytest.approx(700.0, rel=1e-5)


def test_home_energy_lands_overnight_work_energy_daytime() -> None:
    # Two regions with opposite roles: suburb = all homes, cbd = all workplaces.
    rows = _day_rows({"suburb": 50.0, "cbd": 50.0})
    out, meta = ev_demand_adjustment(
        rows, fleet_size=10_000, kwh_per_vehicle_day=10.0, home_charging_share=0.6,
        home_shares={"suburb": 1.0, "cbd": 0.0},
        work_shares={"suburb": 0.0, "cbd": 1.0},
    )
    by = {o["snapshot"]: o for o in out}
    suburb_night = by["2030-01-01T02:00:00"]["suburb"] - 50.0
    suburb_noon = by["2030-01-01T12:00:00"]["suburb"] - 50.0
    cbd_night = by["2030-01-01T02:00:00"]["cbd"] - 50.0
    cbd_noon = by["2030-01-01T12:00:00"]["cbd"] - 50.0
    # The energy follows the fleet: the home region charges overnight (a small
    # daytime shoulder remains), the work region charges in office hours.
    assert suburb_night > 5 * suburb_noon > 0
    assert cbd_noon > 5 * cbd_night > 0
    # Split honours alpha: 60% home / 40% work.
    added_suburb = sum(o["suburb"] for o in out) - 1200.0
    added_cbd = sum(o["cbd"] for o in out) - 1200.0
    assert added_suburb == pytest.approx(meta["homeMwh"], rel=1e-5)
    assert added_cbd == pytest.approx(meta["workMwh"], rel=1e-5)
    assert added_suburb == pytest.approx(1.5 * added_cbd, rel=1e-5)  # 60/40


def test_default_shares_follow_base_energy() -> None:
    rows = _day_rows({"big": 300.0, "small": 100.0})
    out, _ = ev_demand_adjustment(rows, fleet_size=1000, kwh_per_vehicle_day=8.0)
    added_big = sum(o["big"] for o in out) - 7200.0
    added_small = sum(o["small"] for o in out) - 2400.0
    assert added_big == pytest.approx(3 * added_small, rel=1e-5)


def test_endpoint_via_session() -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    c = TestClient(app)
    sid = "test_m4_ev"
    rows = _day_rows({"L": 100.0})
    model = {"loads": [{"name": "L", "bus": "b"}], "loads-p_set": rows,
             "snapshots": [{"snapshot": r["snapshot"]} for r in rows]}
    assert c.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200
    r = c.post("/api/session/snapshots/ev-demand", json={
        "fleetSize": 50_000, "kwhPerVehicleDay": 7.0, "sessionId": sid,
    })
    assert r.status_code == 200
    assert r.json()["addedMwh"] == pytest.approx(350.0)
    c.post(f"/api/session/clear?session_id={sid}")
