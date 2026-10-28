"""P2X chains: the Process form of the conversion steps is the same LP as the multi-port Link form.

The synthesis steps (Haber-Bosch, methanolisation, Fischer-Tropsch), the ASU and the CO2 capture are
``Process``es by default (``componentType: "process"``); ``"link"`` builds the old multi-port Links.
Both are solved on the same case and must agree on the objective, every dispatch series, the sizes,
LCOH / LCOA / LCOM and the P2X results; a chain whose registry still says ``links`` (an old session) must
be read correctly.

Algorithm: Link ``p_i = -eta_i p`` and Process ``p_i = -rate_i p`` with ``rate_0 = -1``, ``rate_i = eta_i``,
so ``p_nom``, ``capital_cost`` (annuitised and window-scaled identically), ``marginal_cost`` and all ports coincide.
ASCII: Link p_i = -eta_i*p ; Process p_i = -rate_i*p with rate = (-1, eta_1, eta_2, ...).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
from numpy.testing import assert_allclose

from backend.app.p2x import chains
from backend.app.p2x import results as pr
from backend.pypsa.results import run_pypsa

from ._p2x_fixtures import SCENARIO, night_gas_network, with_chain

RTOL = 1e-9
ATOL = 1e-7
SPEC: dict[str, Any] = {
    "chainId": "x", "products": ["H2", "NH3", "MeOH", "eFuel"], "storage": {"type": "none"},
    "productStorage": {p: {"enabled": False} for p in chains.PRODUCTS},
    "offtake": {p: {"mode": "flat", "tonnesPerYear": 1000} for p in chains.ALL_PRODUCTS},
}
_cache: dict[str, Any] = {}


def _solve(kind: str) -> tuple[dict, dict]:
    if kind not in _cache:
        model, _ = with_chain(night_gas_network(hours=24), {**SPEC, "componentType": kind})
        _cache[kind] = (model, run_pypsa(model, SCENARIO, {}))
    return _cache[kind]


def test_process_is_the_default_for_the_conversion_steps() -> None:
    model, res = _solve("process")
    procs = {r["name"] for r in model["processes"]}
    assert procs == {"x_synth_NH3", "x_synth_MeOH", "x_synth_eFuel", "x_asu", "x_co2_supply"}
    assert {r["name"] for r in model["links"]} == {"x_electrolyser"}
    nh3 = next(r for r in model["processes"] if r["name"] == "x_synth_NH3")
    assert (nh3["rate0"], nh3["bus2"], nh3["bus3"].endswith("n2")) == (-1.0, "grid", True)
    assert nh3["rate1"] > 0 and nh3["rate2"] < 0 and nh3["rate3"] < 0
    reg = json.loads(model["RAGNAROK_P2X"][0]["json"])
    assert reg["componentType"] == "process" and reg["components"]["synth_NH3"]["sheet"] == "processes"


def test_link_and_process_have_the_same_objective_sizes_and_dispatch() -> None:
    (ml, rl), (mp, rp) = _solve("link"), _solve("process")
    assert {r["name"] for r in ml["links"]} >= {"x_synth_NH3", "x_asu"} and not ml.get("processes")
    # the objective: cost lines are labelled per component class (Link / Process operating cost), so compare the grouped total
    def total(res: dict) -> float:
        return float(sum(r["value"] for r in res["costBreakdown"]))

    def by_kind(res: dict) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in res["costBreakdown"]:
            out[r["label"].replace("Process", "Link")] = out.get(r["label"].replace("Process", "Link"), 0.0) + r["value"]
        return out
    cb_l, cb_p = by_kind(rl), by_kind(rp)
    assert cb_l.keys() == cb_p.keys()
    assert_allclose(total(rp), total(rl), rtol=1e-6, atol=1.0)          # costBreakdown values are rounded to 1 currency unit
    capital = "Capital cost (annuity, pro-rated to window)"
    assert_allclose(cb_p[capital], cb_l[capital], rtol=1e-6, atol=1.0)
    for sheet_l, sheet_p in (("links-p0", "processes-p0"), ("links-p1", "processes-p1"), ("links-p2", "processes-p2"), ("links-p3", "processes-p3")):
        for name in ("x_synth_NH3", "x_synth_MeOH", "x_synth_eFuel"):
            a = np.array([r[name] for r in rl["outputs"]["series"][sheet_l]])
            b = np.array([r[name] for r in rp["outputs"]["series"][sheet_p]])
            assert_allclose(b, a, rtol=RTOL, atol=ATOL)
    for name in ("x_synth_NH3", "x_synth_MeOH", "x_synth_eFuel", "x_asu", "x_co2_supply"):
        a = rl["outputs"]["static"]["links"][name]["p_nom_opt"]
        b = rp["outputs"]["static"]["processes"][name]["p_nom_opt"]
        assert_allclose(b, a, rtol=RTOL, atol=ATOL)
    for key in ("carrierMix", "energyBalance", "nodalBalance", "generatorEnergy", "emissionsBreakdown", "summary"):
        assert _close(rl[key], rp[key]), key
    # PyPSA's effective capital cost (overnight x annuity x window) and the FOM are the same number on both sides, read from the built networks
    from backend.pypsa.network import build_network

    nl, _ = build_network(ml, SCENARIO, {})
    npr, _ = build_network(mp, SCENARIO, {})
    for name in ("x_synth_NH3", "x_synth_MeOH", "x_synth_eFuel", "x_asu", "x_co2_supply"):
        assert_allclose(float(npr.components["processes"].capital_cost[name]), float(nl.components["links"].capital_cost[name]), rtol=RTOL)
        assert float(npr.processes.at[name, "fom_cost"]) == float(nl.links.at[name, "fom_cost"])
        assert float(npr.processes.at[name, "overnight_cost"]) == float(nl.links.at[name, "overnight_cost"]) > 0
        assert float(npr.processes.at[name, "capital_cost"]) == 0.0


def test_expansion_and_economics_list_the_processes() -> None:
    _, rp = _solve("process")
    _, rl = _solve("link")
    exp_p = {r["name"]: r for r in rp["expansionResults"]}
    exp_l = {r["name"]: r for r in rl["expansionResults"]}
    assert exp_p["x_synth_NH3"]["component"] == "Process" and exp_l["x_synth_NH3"]["component"] == "Link"
    for name, row in exp_l.items():
        assert_allclose(exp_p[name]["p_nom_opt_mw"], row["p_nom_opt_mw"], rtol=RTOL, atol=ATOL)
    econ = {r["name"] for r in rp["generatorEconomics"]["processes"]}
    assert econ == {"x_synth_NH3", "x_synth_MeOH", "x_synth_eFuel", "x_asu", "x_co2_supply"}


def test_p2x_results_are_identical_for_link_and_process_chains() -> None:
    out = {}
    for kind in ("link", "process"):
        model, res = _solve(kind)
        out[kind] = pr.p2x_results({"model": model, "result": res, "options": {}, "scenario": {"discountRate": 0.05}})
    lh_l, lh_p = out["link"]["lcoh"], out["process"]["lcoh"]
    assert_allclose(lh_p["perKg"], lh_l["perKg"], rtol=RTOL)
    assert_allclose(lh_p["totalCost"], lh_l["totalCost"], rtol=RTOL)
    for p in chains.PRODUCTS:
        a, b = out["link"]["products"][p], out["process"]["products"][p]
        assert_allclose(b["costPerTonne"], a["costPerTonne"], rtol=RTOL, err_msg=p)
        assert_allclose(b["totalCost"], a["totalCost"], rtol=RTOL, err_msg=p)
        assert_allclose(b["producedMwh"], a["producedMwh"], rtol=RTOL, err_msg=p)
        assert_allclose(b["synthesisCapacityMw"], a["synthesisCapacityMw"], rtol=RTOL, atol=ATOL, err_msg=p)
        for k, v in a["components"].items():
            assert_allclose(b["components"][k], v, rtol=1e-7, atol=1e-6, err_msg=f"{p}/{k}")
    assert out["process"]["products"]["NH3"]["costPerTonne"] > 0
    print("PARITY", {p: (out["link"]["products"][p]["costPerTonne"], out["process"]["products"][p]["costPerTonne"]) for p in chains.PRODUCTS},
          (lh_l["perKg"], lh_p["perKg"]))


def test_a_chain_stored_as_links_in_an_old_session_is_still_read() -> None:
    """Old registry: version 1, no componentType, every component on ``links``; the reader must not need the new keys."""
    model, res = _solve("link")
    reg = json.loads(model["RAGNAROK_P2X"][0]["json"])
    assert reg["version"] == 2 and reg["componentType"] == "link"
    legacy = {k: v for k, v in reg.items() if k != "componentType"} | {"version": 1}
    old = {**model, "RAGNAROK_P2X": [{"name": "x", "json": json.dumps(legacy)}]}
    new = pr.p2x_results({"model": old, "result": res, "options": {}, "scenario": {"discountRate": 0.05}})
    ref = pr.p2x_results({"model": model, "result": res, "options": {}, "scenario": {"discountRate": 0.05}})
    assert_allclose(new["products"]["MeOH"]["costPerTonne"], ref["products"]["MeOH"]["costPerTonne"], rtol=RTOL)


def test_unknown_component_type_is_refused() -> None:
    with pytest.raises(ValueError, match="componentType"):
        chains.build_chain({**SPEC, "componentType": "generator"}, night_gas_network(hours=4))


def _close(a: Any, b: Any) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return bool(np.isclose(a, b, rtol=RTOL, atol=ATOL))
    return a == b


@pytest.mark.parametrize("fmt", ["csv", "netcdf"])
def test_process_chain_survives_a_pypsa_export_import_round_trip(fmt: str, tmp_path: Any) -> None:
    """Workbook -> PyPSA file -> workbook keeps the Process ports, sizing flags and (un-annuitised) capital cost."""
    import pypsa

    from backend.pypsa.network import build_network
    from backend.pypsa.network.pypsa_io import (
        export_network_bytes,
        network_from_csv_zip,
    )
    from backend.pypsa.network.serialize import network_to_model

    model, _ = _solve("process")
    net, _ = build_network(model, SCENARIO, {"skipCapexAnnuitisation": True})
    data, _media, _name = export_network_bytes(net, fmt)
    if fmt == "csv":
        back = network_from_csv_zip(data)
    else:
        path = tmp_path / "n.nc"
        path.write_bytes(data)
        back = pypsa.Network(str(path))
    rows = {r["name"]: r for r in network_to_model(back)["processes"]}
    src = {r["name"]: r for r in model["processes"]}
    assert set(rows) == set(src)
    for name, row in src.items():
        for key in ("bus0", "bus1", "bus2", "bus3"):
            assert rows[name].get(key, "") == row.get(key, ""), (name, key)
        for key in ("rate0", "rate1", "rate2", "rate3", "capital_cost", "lifetime"):
            if key in row:
                assert_allclose(float(rows[name][key]), float(row[key]), rtol=1e-9, atol=1e-12, err_msg=f"{name}.{key}")
        assert bool(rows[name].get("p_nom_extendable")) == bool(row.get("p_nom_extendable"))
