"""Tests for perspective-based reports (backend/app/reporting.py + router).

Pins the reporting invariants: every figure in a report document traces
verbatim to the stored run analytics (selection, never recomputation beyond
presentation aggregates), sections whose source module was not enabled render
an ``unavailable`` block instead of failing, ``latest`` resolves to the newest
stored run, and the router maps unknown perspective / missing run to 400/404.
Everything runs against a temporary RUNS_DIR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import reporting, run_store


@pytest.fixture()
def _runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point RUNS_DIR at a throwaway directory for the duration of a test."""
    target = tmp_path / "runs"
    monkeypatch.setattr(run_store, "RUNS_DIR", target)
    return target


def _rich_result() -> dict:
    """A canned solve payload covering every module the report sections read."""
    return {
        "summary": [
            {"label": "Generator capacity", "value": "132 MW", "detail": "4 generators"},
            {"label": "Peak demand", "value": "132 MW", "detail": "workbook load"},
        ],
        "runMeta": {
            "snapshotCount": 24,
            "modeledHours": 24.0,
            "planningMode": "single_period",
            "sampling": None,
            "componentCounts": {"buses": 1, "generators": 2, "storage_units": 0},
        },
        "carrierMix": [
            {"label": "coal", "value": 1200.0, "color": "#333"},
            {"label": "gas", "value": 800.0, "color": "#a52"},
        ],
        "costBreakdown": [
            {"label": "Fuel cost", "value": 72550},
            {"label": "Capital cost", "value": 1082},
        ],
        "expansionResults": [
            {"name": "gas_1", "component": "Generator", "carrier": "gas", "bus": "b1",
             "p_nom_mw": 50.0, "p_nom_opt_mw": 82.0, "delta_mw": 32.0,
             "capital_cost": 100.0, "capex_annual": 1082.0},
        ],
        "statistics": {
            "columns": ["Optimal Capacity", "Installed Capacity"],
            "rows": [
                {"component": "Generator", "carrier": "coal",
                 "values": {"Optimal Capacity": 50.0, "Installed Capacity": 50.0}},
                {"component": "Generator", "carrier": "gas",
                 "values": {"Optimal Capacity": 82.0, "Installed Capacity": 50.0}},
            ],
        },
        "emissionsBreakdown": {
            "byGenerator": [],
            "byCarrier": [
                {"carrier": "coal", "energy_mwh": 1200.0, "emissions_tco2": 408.0,
                 "intensity_kg_mwh": 340.0},
            ],
        },
        "co2Shadow": {"found": False, "note": "No CO2 constraint active in this run."},
        "nearOptimal": {
            "slack": 0.05,
            "currency": "$",
            "optimum": {"cost": 1000.0, "capacityByCarrier": {"coal": 50.0, "gas": 82.0}},
            "carriers": ["gas"],
            "alternatives": [
                {"carrier": "gas", "sense": "min", "status": "ok", "cost": 1050.0,
                 "costRatio": 1.05, "capacityByCarrier": {"coal": 50.0, "gas": 78.0}},
                {"carrier": "gas", "sense": "max", "status": "ok", "cost": 1050.0,
                 "costRatio": 1.05, "capacityByCarrier": {"coal": 50.0, "gas": 90.0}},
            ],
            "droppedCarriers": [],
        },
        "priceFormation": {
            "currency": "$",
            "series": [],
            "marginalSummary": [
                {"carrier": "gas", "hours": 23.0, "shareOfHours": 0.9583, "avgPrice": 259.33},
            ],
        },
        "systemPriceSeries": [
            {"label": "00:00", "timestamp": "2030-06-21T00:00:00", "period": None, "value": 50.0},
            {"label": "01:00", "timestamp": "2030-06-21T01:00:00", "period": None, "value": 20.0},
        ],
        "generatorEconomics": {
            "currency": "$",
            "byCarrier": [
                {"carrier": "gas", "capacityMw": 82.0, "energyMwh": 800.0, "revenue": 443344,
                 "variableCost": 48550, "grossMargin": 394794, "capturePrice": 456.58,
                 "recoveryPct": 120.0},
            ],
            "system": {"revenue": 742572, "variableCost": 72550, "grossMargin": 670022,
                       "generatorsModeled": 2, "generatorsRecovered": 1},
        },
        "companyFinance": {
            "ownerColumn": "owner", "currency": "$", "discountRate": 0.05,
            "companies": [
                {"company": "Altkraft", "overnightCapex": 0.0, "annualMargin": 902547.86,
                 "horizonYears": 25, "npv": 12720459.57, "irr": None,
                 "paybackYears": 0.0, "dscr": None},
            ],
        },
        "merchant": {
            "owner": "Nordwind", "ownerColumn": "owner", "priceSource": "lmp", "currency": "$",
            "priceStats": {"mean": 23.92, "min": 15.14, "max": 50.0},
            "assets": [
                {"name": "wind_1", "type": "generator", "bus": "b1", "carrier": "wind",
                 "capacityMW": 150.0, "energyMWh": 603645.0, "revenue": 12784478.0,
                 "operatingCost": 0.0, "capex": 12784478.0, "profit": 0.0,
                 "capturePrice": 21.18},
            ],
            "totals": {"revenue": 13640082.0, "operatingCost": 0.0, "capex": 13640082.0,
                       "profit": 0.0, "energyMWh": 638439.0},
        },
        "ppa": {
            "owner": "Nordwind", "volumeType": "generation", "currency": "$",
            "strikePrice": 45.0, "energyMWh": 1000.0, "avgSpotPrice": 40.0,
            "spotValue": 40000.0, "contractValue": 45000.0,
            "sellerNet": 5000.0, "buyerNet": -5000.0,
        },
        "ppaExplorer": {
            "currency": "$", "strikePrice": 45.0,
            "shapes": [
                {"shape": "Peak block (top 25% hours)", "energyMWh": 500.0,
                 "avgSpotPrice": 60.0, "sellerNet": -1000.0, "buyerNet": 1000.0},
                {"shape": "Generation (as-produced)", "energyMWh": 1000.0,
                 "avgSpotPrice": 40.0, "sellerNet": 5000.0, "buyerNet": -5000.0},
            ],
        },
        "adequacy": {
            "members": 200, "variability": 0.15, "firmCapacityMW": 240.0,
            "renewableCapacityMW": 189.0, "peakLoadMW": 174.67, "lole": 0.5,
            "eens": 2.0, "worstPeriods": [], "band": [],
        },
        "energyBalance": {
            "carriers": [
                {"carrier": "AC", "supplyMWh": 2000.0, "demandMWh": 2000.0,
                 "sources": [{"label": "coal", "energyMWh": 1200.0, "kind": "generation"}],
                 "sinks": [{"label": "Demand", "energyMWh": 2000.0, "kind": "load"}]},
            ],
        },
        "outputs": {"static": {}, "series": {}},
    }


def _store(result: dict, label: str = "Report Run") -> str:
    meta = run_store.store_run(
        {"buses": [{"name": "b1"}]},
        {"label": "Scenario", "carbonPrice": 25.0},
        {"runLabel": label, "currencySymbol": "$", "snapshotWeight": 1,
         "enableLoadSheddingCost": False},
        result,
    )
    assert meta is not None
    return str(meta["name"])


def test_list_perspectives_outline() -> None:
    perspectives = reporting.list_perspectives()
    ids = {p["id"] for p in perspectives}
    assert {"policy-maker", "investor", "ppa-buyer", "lender", "procurement"} <= ids
    for p in perspectives:
        assert p["label"] and p["audience"] and p["sections"]
        for section in p["sections"]:
            assert section["id"] in reporting._SECTION_TITLES
            assert section["keyQuestion"].endswith("?")


def test_report_figures_trace_to_stored_payload(_runs_dir: Path) -> None:
    result = _rich_result()
    name = _store(result)
    doc = reporting.build_report(name, "policy-maker")
    assert doc is not None
    assert doc["runName"] == name
    sections = {s["id"]: s for s in doc["sections"]}

    # Generation mix: donut data is the stored carrierMix, verbatim.
    mix_chart = sections["mix"]["blocks"][0]["chart"]
    assert mix_chart["data"] == result["carrierMix"]

    # Cost: chart values verbatim; narrative total is the plain sum.
    cost_chart = sections["cost"]["blocks"][0]["chart"]
    assert cost_chart["series"][0]["values"] == [72550, 1082]
    assert "73,632" in sections["cost"]["blocks"][1]["paragraphs"][0]

    # Robustness: min/max come from stored alternatives, optimum passes through.
    rob_rows = {r["carrier"]: r for r in sections["robustness"]["blocks"][0]["rows"]}
    assert rob_rows["gas"] == {"carrier": "gas", "optimal": 82.0, "minimum": 78.0,
                               "maximum": 90.0}

    # Emissions table rows are the stored byCarrier rows, verbatim.
    assert sections["emissions"]["blocks"][0]["rows"] == result["emissionsBreakdown"]["byCarrier"]

    # Adequacy KPIs read the stored fields.
    adequacy_kpis = sections["adequacy"]["blocks"][0]["items"]
    assert any(i["value"] == "0.5 h/yr" for i in adequacy_kpis)


def test_every_perspective_assembles_and_orders_sections(_runs_dir: Path) -> None:
    name = _store(_rich_result())
    for p in reporting.list_perspectives():
        doc = reporting.build_report(name, p["id"])
        assert doc is not None
        assert [s["id"] for s in doc["sections"]] == [s["id"] for s in p["sections"]]
        # With the rich payload, no section should degrade to unavailable.
        for section in doc["sections"]:
            kinds = {b["type"] for b in section["blocks"]}
            assert "unavailable" not in kinds, (p["id"], section["id"])
        assert doc["caveats"]
        assert doc["provenance"]["runName"] == name


def test_missing_modules_degrade_to_unavailable(_runs_dir: Path) -> None:
    result = _rich_result()
    for key in ("ppa", "ppaExplorer", "companyFinance", "merchant", "adequacy",
                "nearOptimal"):
        result[key] = None
    name = _store(result)
    doc = reporting.build_report(name, "lender")
    assert doc is not None
    sections = {s["id"]: s for s in doc["sections"]}
    for sid in ("finance", "merchant", "adequacy", "robustness"):
        blocks = sections[sid]["blocks"]
        assert blocks[0]["type"] == "unavailable"
        assert blocks[0]["requires"]


def test_latest_resolves_to_newest_run(_runs_dir: Path) -> None:
    _store(_rich_result(), label="Older")
    newest = _store(_rich_result(), label="Newer")
    doc = reporting.build_report("latest", "investor")
    assert doc is not None
    assert doc["runName"] == newest


def test_router_endpoints(_runs_dir: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.app.main import app

    client = TestClient(app)
    resp = client.get("/api/reports/perspectives")
    assert resp.status_code == 200
    assert {p["id"] for p in resp.json()["perspectives"]} >= {"policy-maker", "lender"}

    name = _store(_rich_result())
    resp = client.get(f"/api/reports/{name}/policy-maker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["perspective"] == "policy-maker"
    assert body["sections"]

    assert client.get(f"/api/reports/{name}/not-a-perspective").status_code == 400
    assert client.get("/api/reports/no-such-run/policy-maker").status_code == 404
