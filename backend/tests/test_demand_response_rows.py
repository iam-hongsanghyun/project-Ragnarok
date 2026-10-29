"""Demand response as visible workbook rows, and the carbon-price term reading the one shared factor map.

Demand response: the apply step writes the ``dr_*`` components into the model sheets; a run built from those rows
(no ``demandResponseConfig``) must solve to exactly the numbers of the legacy build-time rewiring, which stays the
back-compat path for a workbook that has the config but no rows.

Carbon pricing: the per-generator factors are :func:`backend.app.emissions.carrier_emission_factors`, the same map a
run puts on ``RunContext.emissions_factors``; the module keeps no carrier read of its own.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pandas as pd
import pypsa
import pytest

from backend.app import carbon_pricing as cp
from backend.app import demand_response as dr
from backend.app import module_hooks as mh
from backend.app.carbon_pricing import term as cp_term
from backend.app.emissions import carrier_emission_factors
from backend.app.routers import operations_modules as ops
from backend.pypsa.network import build_network

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 2, "snapshotWeight": 1.0}
SNAPS = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]

SHIFT = {"enabled": True, "shiftFraction": 0.5, "maxShiftHours": 2.0}
ELASTIC = {"elasticEnabled": True, "elasticFraction": 0.4, "wtpMax": 200.0}


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "buses": [{"name": "b", "carrier": "AC"}],
        "carriers": [{"name": "cheap"}, {"name": "peaker"}, {"name": "AC"}],
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "loads": [{"name": "L", "bus": "b"}, {"name": "L2", "bus": "b"}],
        "loads-p_set": [
            {"snapshot": SNAPS[0], "L": 50.0, "L2": 30.0},
            {"snapshot": SNAPS[1], "L": 150.0, "L2": 30.0},
        ],
        "generators": [
            {"name": "G_cheap", "bus": "b", "carrier": "cheap", "p_nom": 100.0, "marginal_cost": 10.0},
            {"name": "G_peak", "bus": "b", "carrier": "peaker", "p_nom": 150.0, "marginal_cost": 100.0},
        ],
    }


def _solve(model: dict[str, Any], options: dict[str, Any]) -> tuple[pypsa.Network, list[str]]:
    n, notes = build_network(model, SCENARIO, options)
    n.optimize(solver_name="highs")
    return n, notes


def _frames(n: pypsa.Network) -> dict[str, pd.DataFrame]:
    return {
        "gen": n.generators_t.p.sort_index(axis=1),
        "link": n.links_t.p0.sort_index(axis=1),
        "store": n.stores_t.p.sort_index(axis=1),
        "store_e": n.stores_t.e.sort_index(axis=1),
    }


@pytest.mark.parametrize("cfg", [
    {**SHIFT, "loads": ["L"]},
    {**ELASTIC, "loads": ["L"]},
    {**SHIFT, **ELASTIC},
], ids=["shift", "elastic", "both"])
def test_rows_build_solves_identically_to_the_legacy_rewiring(cfg: dict[str, Any]) -> None:
    legacy, legacy_notes = _solve(_model(), {**OPTIONS, "demandResponseConfig": cfg})
    assert any("(legacy)" in note for note in legacy_notes)

    written = dr.compute_rows(_model(), cfg)
    rows_net, rows_notes = _solve(written["model"], OPTIONS)  # no demandResponseConfig: the workbook alone
    assert not any("(legacy)" in note for note in rows_notes)

    assert rows_net.objective == pytest.approx(legacy.objective, rel=1e-9, abs=1e-9)
    a, b = _frames(legacy), _frames(rows_net)
    for key in a:
        pd.testing.assert_frame_equal(a[key], b[key], check_exact=False, rtol=1e-9, atol=1e-9, check_names=False)
    assert dr.build_demand_response(rows_net) == dr.build_demand_response(legacy)
    assert dr.build_price_elastic(rows_net) == dr.build_price_elastic(legacy)


def test_rows_are_written_into_the_sheets_and_the_load_moves() -> None:
    out = dr.compute_rows(_model(), {**SHIFT, **ELASTIC, "loads": ["L"]})
    model = out["model"]
    assert {"dr_L"} <= {r["name"] for r in model["buses"]}
    link = next(r for r in model["links"] if r["name"] == "drlink_L")
    assert (link["bus0"], link["bus1"]) == ("b", "dr_L")
    assert link["p_nom"] == pytest.approx(150.0 + 75.0)            # peak + 0.5 x peak
    store = next(r for r in model["stores"] if r["name"] == "drstore_L")
    assert store["e_nom"] == pytest.approx(75.0 * 2.0) and store["e_cyclic"] is True
    assert next(r for r in model["loads"] if r["name"] == "L")["bus"] == "dr_L"
    assert next(r for r in model["loads"] if r["name"] == "L2")["bus"] == "b"
    elastic = [r for r in model["generators"] if r["name"].startswith("load_shedding_elastic_L_")]
    assert len(elastic) == 4 and all(r["bus"] == "dr_L" and r["carrier"] == "elastic_demand" for r in elastic)
    assert "elastic_demand" in {r["name"] for r in model["carriers"]}
    assert out["sheets"] == ["buses", "carriers", "generators", "links", "loads", "stores"]
    assert dr.workbook_rows(model) == {
        "links": ["drlink_L"], "buses": ["dr_L"], "stores": ["drstore_L"],
        "generators": [f"load_shedding_elastic_L_{k}" for k in range(4)],
    }


def test_rows_in_the_workbook_win_over_the_config_and_are_not_duplicated() -> None:
    model = dr.compute_rows(_model(), {**SHIFT, "loads": ["L"]})["model"]
    n, notes = build_network(model, SCENARIO, {**OPTIONS, "demandResponseConfig": {**SHIFT}})  # config says all loads
    assert [str(x) for x in n.links.index if str(x).startswith("drlink_")] == ["drlink_L"]
    assert "dr_L2" not in n.buses.index
    assert any("from the workbook rows" in note for note in notes)


def test_reapply_replaces_and_disable_removes_the_rows() -> None:
    first = dr.compute_rows(_model(), {**SHIFT, **ELASTIC})["model"]
    again = dr.compute_rows(first, {**SHIFT, "shiftFraction": 0.2, "loads": ["L2"]})
    model = again["model"]
    assert dr.workbook_rows(model) == {"links": ["drlink_L2"], "buses": ["dr_L2"], "stores": ["drstore_L2"]}
    assert {r["name"]: r["bus"] for r in model["loads"]} == {"L": "b", "L2": "dr_L2"}
    assert set(again["removed"]["links"]) == {"drlink_L", "drlink_L2"}

    off = dr.compute_rows(model, {"enabled": False})
    assert dr.workbook_rows(off["model"]) == {}
    assert {r["name"]: r["bus"] for r in off["model"]["loads"]} == {"L": "b", "L2": "b"}
    assert off["rows"] == {}
    # the elastic carrier row added by the first apply stays: it is an ordinary carrier now
    assert off["model"]["buses"] == _model()["buses"]


def test_a_users_own_dr_named_bus_is_not_the_modules() -> None:
    model = _model()
    model["buses"].append({"name": "dr_site", "carrier": "AC"})
    assert dr.workbook_rows(model) == {}
    assert {r["name"] for r in dr.remove_rows(model)[0]["buses"]} == {"b", "dr_site"}


def test_apply_endpoint_writes_the_changed_sheets(monkeypatch: pytest.MonkeyPatch) -> None:
    store: dict[str, Any] = {}
    base = _model()
    monkeypatch.setattr(ops, "_model", lambda _sid: {**base, **store})
    monkeypatch.setattr(ops.model_store, "merge_static_model", lambda sid, sheets: store.update(sheets) or {})
    prev = ops.demand_response_preview(ops.DemandResponseBody(config={**SHIFT, "loads": ["L"]}))
    assert prev["existing"] == {} and [r["name"] for r in prev["rows"]["links"]] == ["drlink_L"]
    assert store == {}                                          # the preview writes nothing
    out = ops.demand_response_apply(ops.DemandResponseBody(config={**SHIFT, "loads": ["L"]}))
    assert out["sheetsWritten"] == ["buses", "links", "loads", "stores"]
    assert dr.workbook_rows({**base, **store})["links"] == ["drlink_L"]
    gone = ops.demand_response_apply(ops.DemandResponseBody(config={}))
    assert gone["removed"]["links"] == ["drlink_L"] and dr.workbook_rows({**base, **store}) == {}


# ── carbon pricing: one shared factor source ─────────────────────────────────────

def _carbon_net() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.DatetimeIndex(["2030-01-01 00:00", "2030-01-01 01:00"]))
    n.add("Carrier", "gas", co2_emissions=0.4)
    n.add("Carrier", "coal", co2_emissions=0.9)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Bus", "b0")
    n.add("Generator", "g_gas", bus="b0", carrier="gas", p_nom=100.0, efficiency=0.5)
    n.add("Generator", "g_coal", bus="b0", carrier="coal", p_nom=100.0)
    n.add("Generator", "g_wind", bus="b0", carrier="wind", p_nom=100.0)
    return n


def test_carbon_factors_are_the_shared_carrier_map() -> None:
    n = _carbon_net()
    shared = carrier_emission_factors(n)
    ef = cp.emission_factors(n)
    assert ef.to_dict() == {g: float(shared[c]) for g, c in n.generators["carrier"].items()}
    assert not hasattr(cp_term, "_carrier_factor")             # no private read left


def test_carbon_term_uses_a_passed_map_and_the_hook_passes_the_run_context_map() -> None:
    n = _carbon_net()
    cfg = cp.parse_carbon_price_config(50.0, None)
    adder = cp.adder_frame(n, cfg)
    assert adder["g_gas"].iloc[0] == pytest.approx(50.0 * 0.4 / 0.5)
    only_coal = cp.adder_frame(n, cfg, carrier_factors={"gas": 0.0, "coal": 0.9})
    assert list(only_coal.columns) == ["g_coal"]

    hook = next(h for h in mh.hooks("constraints") if h.hook_id == "carbon-pricing")
    ctx_map = {"coal": 0.9}
    part = hook.fn(SimpleNamespace(emissions_factors=ctx_map))
    assert part.keywords["carrier_factors"] is ctx_map
