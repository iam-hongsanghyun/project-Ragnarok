"""Per-snapshot carrier output cap (sheet ``RAGNAROK_CarrierOutputCap``).

Analytical case, parity with a plain ``n.optimize(extra_functionality=...)``, run paths (single period, rolling,
refused modes), Forge alignment, model check, and delivery through a backend plugin's ``contribute``.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.app import model_store, module_hooks, session_store
from backend.app.constraints import carrier_output_cap as coc
from backend.app.model_check.checks import check_model
from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
HOURS = 4
LABELS = [f"2030-01-01T{h:02d}:00:00" for h in range(HOURS)]
CAP_HOUR = 1
CAP_MW = 120.0


def _model(cap: list[float | None] | None = None) -> dict[str, list[dict[str, Any]]]:
    """Two coal units on two buses (10 and 20 /MWh, 100 MW each) + gas backup (100 /MWh); flat 150 MW load."""
    m: dict[str, list[dict[str, Any]]] = {
        "buses": [{"name": "b1"}, {"name": "b2"}],
        "carriers": [{"name": "coal"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in LABELS],
        "lines": [{"name": "l12", "bus0": "b1", "bus1": "b2", "x": 0.1, "s_nom": 1000.0}],
        "loads": [{"name": "L1", "bus": "b1", "p_set": 75.0}, {"name": "L2", "bus": "b2", "p_set": 75.0}],
        "generators": [
            {"name": "C1", "bus": "b1", "carrier": "coal", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "C2", "bus": "b2", "carrier": "coal", "p_nom": 100.0, "marginal_cost": 20.0},
            {"name": "G", "bus": "b1", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 100.0},
        ],
    }
    if cap is not None:
        m[coc.SHEET] = [{"snapshot": s, "coal": c} for s, c in zip(LABELS, cap)]
    return m


CAP = [None, CAP_MW, None, None]


def _solve(model: dict, options: dict | None = None):
    n, _ = build_network(model, SCENARIO, options or {})
    ctx = module_hooks.RunContext(model=model, scenario=SCENARIO, options=options or {}, network=n, notes=[])
    n.optimize(solver_name="highs", extra_functionality=module_hooks.compose_constraints(ctx))
    return n, ctx


def test_analytical_cap_binds_the_fleet_sum_and_leaves_units_free() -> None:
    n, ctx = _solve(_model(CAP))
    coal = n.generators_t.p[["C1", "C2"]]
    np.testing.assert_allclose(coal.sum(axis=1).to_numpy(), [150.0, CAP_MW, 150.0, 150.0], atol=1e-6)
    # Unit dispatch is free: merit order fills the cheap unit first (100 + 50 / 100 + 20), not a per-unit derate.
    np.testing.assert_allclose(coal["C1"].to_numpy(), [100.0] * HOURS, atol=1e-6)
    np.testing.assert_allclose(n.generators_t.p["G"].to_numpy(), [0.0, 30.0, 0.0, 0.0], atol=1e-6)
    assert any("coal fleet output capped in 1 of 4" in x for x in ctx.notes)


def test_blank_everywhere_is_unconstrained() -> None:
    n, _ = _solve(_model([None] * HOURS))
    np.testing.assert_allclose(n.generators_t.p["G"].to_numpy(), 0.0, atol=1e-6)


def test_parity_with_plain_extra_functionality() -> None:
    model = _model(CAP)
    ours, _ = _solve(model)

    plain, _ = build_network(_model(None), SCENARIO, {})

    def extra(n, snapshots):
        p = n.model["Generator-p"]
        cols = list(n.generators.index[n.generators.carrier == "coal"])
        t = pd.Index([pd.Timestamp(LABELS[CAP_HOUR])], name="snapshot")
        n.model.add_constraints(p.sel(name=cols).sum("name").sel(snapshot=t) <= CAP_MW, name="by_hand")

    plain.optimize(solver_name="highs", extra_functionality=extra)
    np.testing.assert_allclose(float(ours.objective), float(plain.objective), rtol=1e-9)
    np.testing.assert_allclose(ours.generators_t.p.to_numpy(), plain.generators_t.p.to_numpy(), rtol=1e-9, atol=1e-9)


def test_constraint_name_and_dual_in_applied_constraints() -> None:
    from backend.pypsa.results.market import build_applied_constraints

    n, _ = _solve(_model(CAP))
    assert "carrier_output_cap_coal" in list(n.model.constraints)
    row = next(r for r in build_applied_constraints(n) if r["name"] == "carrier_output_cap_coal")
    assert row["source"] == "carrier_output_cap" and row["bindingHours"] == 1
    # Relaxing the cap by 1 MW swaps 1 MWh of gas (100) for coal (20): the dual is the 80/MWh difference.
    assert abs(row["shadowPrice"]) == pytest.approx(80.0, rel=1e-6)


def test_rolling_horizon_reads_each_windows_own_slice() -> None:
    caps = [None, CAP_MW, None, 130.0]
    res = run_pypsa(_model(caps), SCENARIO, {"rollingConfig": {"enabled": True, "horizonSnapshots": 2, "overlapSnapshots": 0}})
    assert res["rolling"]["windowCount"] == 2  # ceil((4 - 0) / (2 - 0)); one cap in each window
    series = res["outputs"]["series"]["generators-p"]
    coal = [float(r["C1"]) + float(r["C2"]) for r in series]
    np.testing.assert_allclose(coal, [150.0, CAP_MW, 150.0, 130.0], atol=1e-6)


def test_refused_in_pathway_and_stochastic_modes() -> None:
    ctx = module_hooks.RunContext(model=_model(CAP), pathway=type("P", (), {"enabled": True})())
    with pytest.raises(HTTPException) as err:
        module_hooks.run_guards(ctx)
    assert err.value.status_code == 400 and "pathway" in err.value.detail
    ctx = module_hooks.RunContext(model=_model(CAP), pf_enabled=True)
    with pytest.raises(HTTPException):
        module_hooks.run_guards(ctx)
    # An empty sheet is not a cap: nothing to refuse.
    module_hooks.run_guards(module_hooks.RunContext(model=_model([None] * HOURS), pf_enabled=True))


@pytest.mark.parametrize("bad", ["abc", -5.0])
def test_bad_cell_is_a_400_not_a_silent_loosening(bad) -> None:
    with pytest.raises(HTTPException) as err:
        coc.read_caps(_model([None, bad, None, None]))
    assert err.value.status_code == 400


def test_model_check_warns_on_unknown_carrier_and_off_axis_snapshot() -> None:
    model = _model(CAP)
    model[coc.SHEET] = [{"snapshot": "2031-06-01T00:00:00", "coal": 10.0, "lignite": 5.0}] + model[coc.SHEET]
    codes = {f["code"] for f in check_model(model)["findings"]}
    assert {"carrier_cap_no_generators", "carrier_cap_off_axis"} <= codes
    assert not {"carrier_cap_no_generators", "carrier_cap_off_axis"} & {f["code"] for f in check_model(_model(CAP))["findings"]}


def test_sheet_is_registered_as_series() -> None:
    assert session_store.is_series_sheet(coc.SHEET) and model_store.is_series_sheet(coc.SHEET)
    from backend.app import run_store

    assert run_store._is_series_sheet(coc.SHEET)


def test_forge_realign_filter_and_blocks() -> None:
    rows = [{"snapshot": s, "coal": c} for s, c in zip(LABELS, [100.0, 80.0, None, 60.0])]
    kept = pd.DatetimeIndex(pd.to_datetime(LABELS[1:3]))
    out = coc.realign(rows, LABELS[1:3], kept, mode="filter")
    assert out == [{"snapshot": LABELS[1], "coal": 80.0}]
    new = pd.DatetimeIndex(pd.to_datetime([LABELS[0], LABELS[2]]))
    blocks = coc.realign(rows, [LABELS[0], LABELS[2]], new, mode="blocks")
    assert blocks == [{"snapshot": LABELS[0], "coal": 90.0}]  # block 2 has a blank hour: stays uncapped, row dropped


def test_contribute_delivers_the_sheet_as_series_and_the_run_applies_it(tmp_path, monkeypatch) -> None:
    from backend.app import plugins
    from backend.app.routers import plugins as plugins_router

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    plugin_dir = tmp_path / "plugins" / "oepcap"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text('{"id": "oepcap", "name": "oepcap"}', encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "def contribute(model, config):\n"
        f"    rows = [{{'snapshot': s, 'coal': c}} for s, c in zip({LABELS!r}, {CAP!r})]\n"
        f"    return {{'sheets': {{'{coc.SHEET}': rows}}}}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(plugins, "BACKEND_PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(plugins, "PLUGIN_FILES_DIR", tmp_path / "plugin_files")
    plugins._REGISTRY = None
    try:
        model_store.save_model("default", _model(None), filename="x.xlsx", scenario_name="")
        meta = plugins_router.contribute_plugin("oepcap", plugins_router.TransformRequest(sessionId="default"))
        kinds = {s["name"]: s["kind"] for s in meta["sheets"]}
        assert kinds[coc.SHEET] == "series"
        win = model_store.get_series_window("default", coc.SHEET, start=1, end=3, max_points=100)
        assert win is not None and win["total"] == HOURS and win["returned"] == 2
        assert win["indexCol"] == "snapshot"

        stored = model_store.load_full_model("default")
        res = run_pypsa(stored, SCENARIO, {})
        series = res["outputs"]["series"]["generators-p"]
        coal = [float(r["C1"]) + float(r["C2"]) for r in series]
        np.testing.assert_allclose(coal, [150.0, CAP_MW, 150.0, 150.0], atol=1e-6)
        assert any(r["name"] == "carrier_output_cap_coal" for r in res["appliedConstraints"])
    finally:
        plugins._REGISTRY = None
