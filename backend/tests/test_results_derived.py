"""Parity tests for backend/app/results_derived.py (+ its /api routes) against the
fixtures of the TS suites (lib/results/assetDetails.test.ts) and the logic of
KpiStripCard / CompanyComparisonCard / ComparisonPane."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import results_derived as rd

# ── assetDetails.test.ts fixtures ────────────────────────────────────────────

MODEL = {
    "buses": [{"name": "b1"}],
    "carriers": [{"name": "AC"}],
    "generators": [],
    "loads": [{"name": "l1", "bus": "b1", "p_set": 0}],
    "storage_units": [{"name": "s1", "bus": "b1", "p_nom": 0, "max_hours": 4, "p_nom_extendable": True}],
    "stores": [{"name": "st1", "bus": "b1", "e_nom": 0, "e_nom_extendable": True}],
    "loads-p_set": [
        {"period": 2030, "snapshot": "2030-01-01T00:00:00", "l1": 50},
        {"period": 2040, "snapshot": "2030-01-01T00:00:00", "l1": 80},
    ],
}
OUTPUTS = {
    "static": {"storage_units": {"s1": {"p_nom_opt": 25}}, "stores": {"st1": {"e_nom_opt": 90}}},
    "series": {
        "buses-marginal_price": [
            {"period": 2030, "snapshot": "2030-01-01T00:00:00", "b1": 1},
            {"period": 2040, "snapshot": "2030-01-01T00:00:00", "b1": 2},
        ]
    },
}


def test_normalize_stamp() -> None:
    assert rd.normalize_stamp("2030-01-01T00:00:00.000000") == "2030-01-01T00:00:00"
    assert rd.normalize_stamp("2030-01-01 05:00:00+00:00") == "2030-01-01T05:00:00"
    assert rd.normalize_stamp("2030-01-01T05:00Z") == "2030-01-01T05:00:00"
    assert rd.normalize_stamp("not a date") == "not a date"


def test_input_lookup_keyed_by_period_and_stamp() -> None:
    idx = rd.InputIndex(MODEL["loads-p_set"])
    assert idx.value_at("2030-01-01T00:00:00", "l1", 0, 2030) == 50
    assert idx.value_at("2030-01-01T00:00:00", "l1", 0, 2040) == 80
    assert idx.value_at("2030-01-01T00:00:00", "l1", 0) == 80


def test_each_pathway_period_sees_its_own_demand() -> None:
    d = rd.derive_asset_details(MODEL, OUTPUTS)
    assert [p["load"] for p in d["buses"]["b1"]["netSeries"]] == [50, 80]


def test_solved_capacity_for_extendable_storage() -> None:
    d = rd.derive_asset_details(MODEL, OUTPUTS)
    assert d["storageUnits"]["s1"]["summary"][0]["value"] == "25 MW"
    assert d["storageUnits"]["s1"]["summary"][1]["value"] == "100 MWh"
    assert d["stores"]["st1"]["summary"][0]["value"] == "90 MWh"


def test_period_filter() -> None:
    d = rd.derive_asset_details(MODEL, OUTPUTS, snapshot_weight=1, period=2040)
    assert [p["load"] for p in d["buses"]["b1"]["netSeries"]] == [80]


def test_averaged_sampling_uses_positional_mean() -> None:
    model = {**MODEL, "loads-p_set": [
        {"snapshot": f"2030-01-01T0{h}:00:00", "l1": v} for h, v in enumerate([10, 20, 30, 40])
    ]}
    outputs = {"static": {}, "series": {"buses-marginal_price": [
        {"snapshot": "2030-01-01T00:00:00", "b1": 1}, {"snapshot": "2030-01-01T01:00:00", "b1": 1}]}}
    sampling = {"enabled": True, "mode": "average", "blockSize": 2, "representedSnapshots": 4}
    d = rd.derive_asset_details(model, outputs, "$", 2, sampling)
    assert [p["load"] for p in d["buses"]["b1"]["netSeries"]] == [20, 30]


def test_generator_detail_matches_ts_formulae() -> None:
    model = {
        "buses": [{"name": "b1"}], "carriers": [{"name": "gas", "co2_emissions": 0.2}],
        "generators": [{"name": "g1", "bus": "b1", "carrier": "gas", "p_nom": 100, "marginal_cost": 10, "efficiency": 0.5}],
    }
    outputs = {"static": {}, "series": {"generators-p": [
        {"snapshot": "2030-01-01T00:00:00", "g1": 60}, {"snapshot": "2030-01-01T01:00:00", "g1": 40}]}}
    g = rd.derive_asset_details(model, outputs, "$", 2, kinds=["generators"])["generators"]["g1"]
    s = {i["label"]: i for i in g["summary"]}
    assert s["Energy"]["value"] == "200 MWh"                       # (60+40) * 2 h
    assert s["Operating cost"]["value"] == "2,000 $"               # 200 * 10
    assert s["Emissions"]["value"] == "80 tCO2e"                   # 200 MWh * 0.2 / 0.5
    assert g["curtailmentSeries"] == []                            # no time-varying availability


def test_fmt_matches_to_locale_string() -> None:
    assert rd.fmt(1234567.4) == "1,234,567"
    assert rd.fmt(0.5) == "1"          # half away from zero, as Intl
    assert rd.fmt(12.3456, 3) == "12.346"
    assert rd.fmt(-0.2) == "0"


# ── KPI strip ────────────────────────────────────────────────────────────────

RESULT = {
    "carrierMix": [{"label": "wind", "value": 600.0}, {"label": "gas", "value": 400.0}, {"label": "battery", "value": 0.0}],
    "systemPriceSeries": [{"value": 10.0}, {"value": 30.0}],
    "summary": [{"label": "Peak demand", "value": "1,250 MW"}, {"label": "System emissions", "value": "80 tCO2"}],
    "costBreakdown": [{"label": "Fuel", "value": 1000.4}, {"label": "Carbon", "value": 500.4}],
    "runMeta": {"snapshotCount": 2, "snapshotWeight": 1.0},
}
CARRIERS = [{"name": "wind", "co2_emissions": 0}, {"name": "gas", "co2_emissions": 0.2}]


def test_kpis_follow_the_card() -> None:
    k = rd.compute_kpis(RESULT, CARRIERS)
    assert k["dispatchMwh"] == 1000
    assert (k["avgPrice"], k["minPrice"], k["maxPrice"]) == (20, 10, 30)
    assert k["peakLoadMw"] == 1250                      # parsed from "1,250 MW", not 1
    assert k["totalCost"] == "$1,501"                   # costBreakdown sum when no summary entry
    assert k["loadFactor"] == pytest.approx(500 / 1250)  # (1000 MWh / 2 h) / peak
    assert k["renewableSharePct"] == pytest.approx(60)
    assert k["emissions"] == "80 tCO2"


def test_kpis_avg_price_is_the_load_weighted_run_average_when_stored() -> None:
    # Re-baselined (P28): runMeta.averageSystemPrice = n.statistics.prices(weighting="load")
    # replaces the unweighted series mean (20 above), which stays the fallback for runs
    # stored before that field existed (test_kpis_follow_the_card).
    result = {**RESULT, "runMeta": {**RESULT["runMeta"], "averageSystemPrice": 24.5}}
    k = rd.compute_kpis(result, CARRIERS)
    assert k["avgPrice"] == 24.5
    assert (k["minPrice"], k["maxPrice"]) == (10, 30)   # still the series extremes


def test_kpis_storage_and_nuclear_are_not_renewable() -> None:
    result = {**RESULT, "carrierMix": [{"label": "nuclear", "value": 500.0}, {"label": "battery", "value": 500.0}]}
    carriers = [{"name": "nuclear", "co2_emissions": 0}, {"name": "battery", "co2_emissions": 0}]
    assert rd.compute_kpis(result, carriers, {"battery"})["renewableSharePct"] == 0


def test_kpis_peak_fallback_uses_system_load() -> None:
    result = {**RESULT, "summary": []}
    k = rd.compute_kpis(result, CARRIERS, system_load_per_snapshot=lambda: [400.0, 600.0])
    assert k["peakLoadMw"] == 600 and k["emissions"] is None


# ── company comparison ───────────────────────────────────────────────────────


def test_companies_join_and_sort() -> None:
    result = {
        "companies": {"currency": "$", "companies": [
            {"company": "A", "capacityMW": 10, "energyMWh": 5, "revenue": 100, "emissionsTonnes": 1},
            {"company": "B", "capacityMW": 20, "energyMWh": 6, "revenue": 50, "emissionsTonnes": 2}]},
        "companyFinance": {"companies": [{"company": "A", "npv": 5, "irr": 0.1, "paybackYears": 4}]},
    }
    out = rd.compare_companies(result)
    assert out["sortedBy"] == "npv" and [c["company"] for c in out["companies"]] == ["A", "B"]  # B has no npv -> last
    assert [m["key"] for m in out["metrics"]] == ["npv", "irr", "revenue", "capacityMW", "emissionsTonnes"]
    assert [c["company"] for c in rd.compare_companies(result, "emissionsTonnes")["companies"]] == ["A", "B"]  # lower first
    assert [c["company"] for c in rd.compare_companies(result, "capacityMW")["companies"]] == ["B", "A"]


# ── comparison ───────────────────────────────────────────────────────────────


def test_installed_capacity_prefers_solved_p_nom_opt() -> None:
    static = {"generators": [{"name": "w", "carrier": "wind", "p_nom": 0}, {"name": "load_shedding_x", "p_nom": 9e9},
                             {"name": "g", "carrier": "gas", "p_nom": 50}],
              "storage_units": [{"name": "s", "p_nom": 10}]}
    info = rd.installed_capacity(static, {"generators": {"w": {"p_nom_opt": 120}}})
    assert info["genCapMw"] == 170 and info["storCapMw"] == 10
    assert info["genSolved"] is False and info["storSolved"] is False   # g / s fell back to input
    assert info["mix"][0] == {"label": "wind", "value": 120}
    summary = rd.split_capacity_summary(
        [{"label": "Installed capacity", "value": "x"}, {"label": "Peak demand", "value": "100 MW"},
         {"label": "Reserve position", "value": "y"}], info)
    assert [s["label"] for s in summary] == [
        "Generator capacity", "Storage capacity", "Peak demand", "Generator reserve", "Storage reserve"]
    assert summary[3]["value"] == "70 MW" and summary[4]["value"] == "-90 MW"


# ── endpoints over a stored run ──────────────────────────────────────────────


@pytest.fixture()
def stored(tmp_path, monkeypatch):
    from backend.app import run_store
    from backend.app.main import app

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    model = {
        "buses": [{"name": "b1"}], "carriers": [{"name": "wind", "co2_emissions": 0}, {"name": "gas", "co2_emissions": 0.2}],
        "generators": [{"name": "w", "bus": "b1", "carrier": "wind", "p_nom": 10}],
        "loads": [{"name": "l1", "bus": "b1", "p_set": 5}],
    }
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    names = []
    for i, label in enumerate(("one", "two")):
        result = {**RESULT, "summary": list(RESULT["summary"]), "companies": {"currency": "$", "companies": [
            {"company": "A", "capacityMW": 10, "energyMWh": 5, "revenue": 100 + i, "emissionsTonnes": 1}]},
            "outputs": {"static": {"generators": {"w": {"p_nom_opt": 20}}}, "series": {
                "generators-p": [{"snapshot": s, "w": 4.0 + i} for s in snaps],
                "buses-marginal_price": [{"snapshot": s, "b1": 7.0} for s in snaps]}}}
        meta = run_store.store_run(model, {"label": label}, {"snapshotWeight": 1, "runLabel": label}, result)
        assert meta is not None
        names.append(meta["name"])
    return TestClient(app), names


def test_compare_endpoint(stored) -> None:
    client, names = stored
    r = client.get("/api/results/compare", params={"runs": ",".join(names), "topics": "kpi,generation-mix,installed-capacity,cost"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and body["topics"] == ["kpi", "generation-mix", "installed-capacity", "cost"]
    first = body["items"][0]
    assert first["generatorCapacityMw"] == 20            # solved p_nom_opt, not input 10
    assert first["carrierMix"][0] == {"label": "wind", "value": 600.0}
    assert first["costBreakdown"][0]["label"] == "Fuel"
    assert client.get("/api/results/compare", params={"runs": names[0]}).status_code == 400
    assert client.get("/api/results/compare", params={"runs": ",".join(names), "topics": "zzz"}).status_code == 400


def test_kpis_companies_assets_endpoints(stored) -> None:
    client, names = stored
    k = client.get(f"/api/runs/{names[0]}/kpis").json()
    assert k["kpis"]["peakLoadMw"] == 1250 and k["kpis"]["renewableSharePct"] == pytest.approx(60)
    c = client.get(f"/api/runs/{names[1]}/companies").json()
    assert c["total"] == 1 and c["items"][0]["revenue"] == 101
    a = client.get(f"/api/runs/{names[0]}/assets", params={"kind": "generators"}).json()
    assert a["total"] == 1 and "outputSeries" not in a["items"][0]        # summaries only by default
    full = client.get(f"/api/runs/{names[1]}/assets", params={"names": "w"}).json()
    assert [p["output"] for p in full["items"][0]["outputSeries"]] == [5.0, 5.0]
    assert full["items"][0]["summary"][0]["value"] == "10 MWh"
    assert client.get(f"/api/runs/{names[0]}/assets", params={"kind": "x"}).status_code == 400
    assert client.get("/api/runs/nope/kpis").status_code == 404


@pytest.fixture()
def stored_with_snapshots(tmp_path, monkeypatch):
    """Two stored runs whose model carries a snapshots sheet, so a network can be rebuilt from them."""
    from backend.app import run_store
    from backend.app.main import app

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00"]
    model = {
        "snapshots": [{"snapshot": s} for s in snaps],
        "buses": [{"name": "b1"}], "carriers": [{"name": "wind", "co2_emissions": 0}],
        "generators": [{"name": "w", "bus": "b1", "carrier": "wind", "p_nom": 10}],
        "loads": [{"name": "l1", "bus": "b1", "p_set": 5}],
    }
    names = []
    for i, label in enumerate(("one", "two")):
        result = {**RESULT, "summary": list(RESULT["summary"]),
                  "outputs": {"static": {"generators": {"w": {"p_nom_opt": 20}}}, "series": {
                      "generators-p": [{"snapshot": s, "w": 4.0 + i} for s in snaps],
                      "loads-p": [{"snapshot": s, "l1": 5.0} for s in snaps],
                      "buses-marginal_price": [{"snapshot": s, "b1": 7.0} for s in snaps]}}}
        meta = run_store.store_run(model, {"label": label}, {"snapshotWeight": 1, "runLabel": label}, result)
        assert meta is not None
        names.append(meta["name"])
    return TestClient(app), names


def test_compare_statistics_topic_uses_network_collection(stored_with_snapshots) -> None:
    """P39: topic ``statistics`` evaluates n.statistics for all runs in one NetworkCollection.

    Both stored runs have wind ``w`` with solved ``p_nom_opt`` 20 MW and dispatch 4 / 5 MW over two
    hourly snapshots, so ``supply`` is 8 / 10 MWh and ``optimal_capacity`` 20 MW. Other topics keep
    their shape.
    """
    client, names = stored_with_snapshots
    r = client.get("/api/results/compare", params={
        "runs": ",".join(names), "topics": "kpi,statistics", "metrics": "optimal_capacity,supply"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["statistics"]["mode"] == "collection"
    assert body["statistics"]["metrics"] == ["optimal_capacity", "supply"]
    assert body["statistics"]["units"] == {"optimal_capacity": "MW", "supply": "MWh"}
    first, second = body["items"]
    assert "summary" in first  # existing topic untouched

    def value(item, metric):
        rows = [x for x in item["statistics"][metric] if x["carrier"] == "wind"]
        assert len(rows) == 1 and rows[0]["component"] == "Generator"
        return rows[0]["value"]

    assert value(first, "optimal_capacity") == 20.0 and value(second, "optimal_capacity") == 20.0
    assert value(first, "supply") == 8.0 and value(second, "supply") == 10.0
    # bad metric -> 400; default topics unchanged (no statistics key)
    assert client.get("/api/results/compare", params={"runs": ",".join(names), "topics": "statistics", "metrics": "zzz"}).status_code == 400
    plain = client.get("/api/results/compare", params={"runs": ",".join(names)}).json()
    assert "statistics" not in plain and "statistics" not in plain["items"][0]


def test_collection_statistics_matches_single_network() -> None:
    """The collection value equals a plain per-network ``n.statistics`` call (no drift from batching)."""
    import warnings

    import pandas as pd
    import pypsa

    from backend.app.run_collection import collection_statistics

    warnings.simplefilter("ignore")
    bundles = {}
    nets = []
    for i in range(2):
        n = pypsa.Network()
        n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
        n.add("Carrier", "wind")
        n.add("Bus", "b")
        n.add("Generator", "w", bus="b", carrier="wind", p_nom=10 + i)
        n.add("Load", "l", bus="b", p_set=3.0)
        nets.append(n)
    from backend.app import run_collection

    run_collection._rebuild = lambda b: b["net"]  # type: ignore[assignment]  # bypass rebuild: nets are already built
    try:
        for i, n in enumerate(nets):
            n.generators_t.p = pd.DataFrame({"w": [3.0, 3.0]}, index=n.snapshots)
            bundles[f"r{i}"] = {"net": n}
        out = collection_statistics(bundles, ["supply"], "carrier")
    finally:
        import importlib
        importlib.reload(run_collection)
    for i, n in enumerate(nets):
        native = float(n.statistics.supply(groupby="carrier", drop_zero=False).loc[("Generator", "wind")])
        got = [r for r in out["runs"][f"r{i}"]["supply"] if r["carrier"] == "wind"][0]["value"]
        assert got == native == 6.0


# ── colours + per-asset chart options (the chart card's server pipeline) ──────


def test_colours_match_helpers_ts() -> None:
    """``hash_color`` / ``carrier_color`` reproduce helpers.ts (values captured from node, int32 shift included)."""
    from backend.app import results_derived as rd

    assert rd.hash_color("generator:G1:output") == "hsl(298 65% 46%)"
    assert rd.hash_color("bus:Seoul:load") == "hsl(314 65% 46%)"  # negative int32 intermediate
    assert rd.hash_color("a very long carrier name for overflow checks xyz") == "hsl(161 65% 46%)"
    assert rd.hash_color("coal 한국") == "hsl(338 65% 46%)"
    assert rd.carrier_color("Wind ") == "#9467bd"  # palette index 14, case/space-insensitive
    assert rd.carrier_color("wind", [{"name": "WIND", "color": "#112233"}]) == "#112233"
    assert rd.carrier_color("") == "#94a3b8"
    assert rd.resolved_color("#abc", "wind") == "#abc"
    assert rd.resolved_color("red", "wind") == "#9467bd"  # only hex counts as an explicit colour


def test_assets_carry_the_carrier_colour() -> None:
    """The /assets generator detail has the carriers-sheet colour, so the map popup dot matches the chart."""
    model = {**MODEL, "carriers": [{"name": "wind", "color": "#00aa00"}, {"name": "gas"}],
             "generators": [{"name": "w", "bus": "b1", "carrier": "wind"}, {"name": "g", "bus": "b1", "carrier": "gas"}]}
    out = {"series": {"generators-p": [{"snapshot": "2030-01-01T00:00:00", "w": 1.0}]}}
    gens = rd.derive_asset_details(model, out, kinds=["generators"])["generators"]
    colours = {name: g["color"] for name, g in gens.items()}
    assert colours["w"] == "#00aa00"  # carrier colour; the row has none of its own
    assert all(c for c in colours.values())


def _metric_fixture():
    model = {
        "buses": [{"name": "b1"}, {"name": "b2"}],
        "carriers": [{"name": "gas", "color": "#ff0000"}, {"name": "wind", "color": "#0000ff"}],
        "generators": [
            {"name": "w1", "bus": "b1", "carrier": "wind", "p_nom": 10},
            {"name": "w2", "bus": "b2", "carrier": "wind", "p_nom": 10},
            {"name": "g1", "bus": "b1", "carrier": "gas", "p_nom": 10, "color": "#123456"},
        ],
        "loads": [{"name": "l1", "bus": "b1", "p_set": 5}],
        "storage_units": [{"name": "s1", "bus": "b1", "p_nom": 5, "max_hours": 2}],
    }
    snaps = ["2030-01-01T00:00:00", "2030-01-01T01:00:00", "2030-01-01T02:00:00"]
    outputs = {"series": {
        "generators-p": [{"snapshot": s, "w1": 1.0 + i, "w2": 2.0, "g1": 3.0} for i, s in enumerate(snaps)],
        "buses-marginal_price": [{"snapshot": s, "b1": 7.0, "b2": 8.0} for s in snaps],
        "storage_units-p": [{"snapshot": s, "s1": v} for s, v in zip(snaps, (-2.0, 0.0, 3.0))],
        "storage_units-state_of_charge": [{"snapshot": s, "s1": 1.0 + i} for i, s in enumerate(snaps)],
    }}
    return model, outputs


def _options(focus, keys, **kw):
    model, outputs = _metric_fixture()
    kinds = [rd.FOCUS_KINDS[focus], "generators"]
    details = {}
    for kind in kinds:
        details.update({k: v for k, v in rd.derive_asset_details(model, outputs, kinds=[kind]).items() if v})
    return {o["key"]: o for o in rd.build_metric_options(details, model, focus, keys, **kw)}


def test_single_generator_options_use_the_carrier_colour() -> None:
    opts = _options("generator", ["w1"])
    assert list(opts) == ["output", "available", "curtailment", "emissions"]
    assert [r["output"] for r in opts["output"]["rows"]] == [1.0, 2.0, 3.0]
    assert opts["output"]["series"][0]["color"] == "#0000ff"
    assert _options("generator", ["g1"])["output"]["series"][0]["color"] == "#123456"  # own hex wins


def test_multi_generator_groups_by_carrier_in_sheet_order() -> None:
    opts = _options("generator", [], group_by="carrier")
    out = opts["output"]
    # carriers-sheet order (gas, wind), summed per timestamp; allowDonut only when grouped by carrier
    assert [s["key"] for s in out["series"]] == ["gas", "wind"]
    assert [s["color"] for s in out["series"]] == ["#ff0000", "#0000ff"]
    assert [r["wind"] for r in out["rows"]] == [3.0, 4.0, 5.0] and [r["gas"] for r in out["rows"]] == [3.0] * 3
    assert out["allowDonut"] is True and out["reducer"] == "mean"
    assert opts["emissions"]["reducer"] == "sum"
    by_asset = _options("generator", [], group_by="asset")["output"]
    assert [s["key"] for s in by_asset["series"]] == ["w1", "w2", "g1"] and by_asset["allowDonut"] is False
    assert by_asset["series"][2]["color"] == "#123456"
    # filters narrow the generators
    only_b2 = _options("generator", [], bus_filter=["b2"])["output"]
    assert [s["key"] for s in only_b2["series"]] == ["wind"] and [r["wind"] for r in only_b2["rows"]] == [2.0] * 3
    assert [s["key"] for s in _options("generator", [], carrier_filter=["gas"])["output"]["series"]] == ["gas"]


def test_bus_options_add_attached_generator_metrics() -> None:
    opts = _options("bus", [])
    assert {"load", "generation", "smp", "gen_output_by_bus", "gen_emissions_by_bus"} <= set(opts)
    assert [s["key"] for s in opts["smp"]["series"]] == ["b1", "b2"]
    assert opts["gen_output_by_bus"]["rows"][0]["wind"] == 3.0
    one = _options("bus", ["b2"])
    assert "gen_output_by_bus" not in one and one["smp"]["rows"][0]["smp"] == 8.0


def test_storage_multi_merges_one_column_per_asset() -> None:
    single = _options("storageUnit", ["s1"])
    assert [r["charge"] for r in single["storage_power"]["rows"]] == [2.0, 0.0, 0.0]
    assert single["storage_power"]["allowDonut"] is True
    multi = _options("storageUnit", [])
    assert [s["key"] for s in multi["storage_power"]["series"]] == ["s1__charge", "s1__discharge"]
    assert [r["s1"] for r in multi["state"]["rows"]] == [1.0, 2.0, 3.0] and multi["state"]["allowDonut"] is False


def test_metrics_endpoint_windows_and_validates(stored) -> None:
    client, names = stored
    url = f"/api/runs/{names[0]}/metrics"
    r = client.get(url, params={"focus": "generator", "keys": "w"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run"] == names[0] and body["focus"] == "generator" and body["total"] == len(body["items"]) == 4
    output = body["items"][0]
    assert output["key"] == "output" and [x["output"] for x in output["rows"]] == [4.0, 4.0]
    assert len(client.get(url, params={"focus": "generator", "keys": "w", "end": 1}).json()["items"][0]["rows"]) == 1
    assert client.get(url, params={"focus": "nope"}).status_code == 400
    assert client.get(url, params={"focus": "generator", "groupBy": "x"}).status_code == 400
    assert client.get("/api/runs/missing/metrics", params={"focus": "generator"}).status_code == 404
    # /assets and /metrics agree on the generator colour
    asset = client.get(f"/api/runs/{names[0]}/assets", params={"kind": "generators", "names": "w"}).json()["items"][0]
    assert asset["color"] == output["series"][0]["color"]
