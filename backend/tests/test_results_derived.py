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
