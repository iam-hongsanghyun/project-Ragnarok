"""Fuel-costs module: the edit endpoints write the sheets the module reads, validated with its own readers.

Analytical anchors: gas $/MMBtu x 3.412142 = currency/MWh_thermal (the fuel-price importer's factor), and a unit's marginal
cost is fuel / efficiency + VOM, so the preview after an edit equals that closed form.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import fuel_costs as fc
from backend.app import model_store
from backend.app.importers.databases.fuel_prices import (
    MMBTU_PER_MWH,
    native_unit,
    to_thermal,
)
from backend.app.main import app
from backend.tests.test_fuel_costs import ETA_COAL, STAMPS, _model

SID = "test-fuel-costs-edit"


@pytest.fixture()
def client():
    c = TestClient(app)
    model_store.save_model(SID, _model(sheets=False))
    try:
        yield c
    finally:
        model_store.clear(SID)


def _post(c: TestClient, path: str, **body: Any):
    return c.post(f"/api/fuel-costs/{path}", json={"sessionId": SID, **body})


def _sheet(name: str) -> list[dict[str, Any]]:
    return (model_store.get_sheet_page(SID, name, 0, 10_000) or {}).get("rows") or []


# ── the converters are the importer's ───────────────────────────────────────────────

def test_to_thermal_uses_the_importer_factors_and_names_valid_units() -> None:
    assert to_thermal("gas", 10.0, "MMBtu") == pytest.approx(10.0 * MMBTU_PER_MWH)
    assert to_thermal("coal", 69.78, "tonne") == pytest.approx(10.0)       # 6.978 MWh/t
    assert to_thermal("oil", 16.99, "bbl") == pytest.approx(10.0)          # 1.699 MWh/bbl
    assert to_thermal("gas", 12.0, "MWh_th") == 12.0
    assert native_unit("gas") == "MMBtu" and native_unit("hydrogen") is None
    with pytest.raises(ValueError, match=r"valid: MWh_th or MMBtu"):
        to_thermal("gas", 1.0, "tonne")


# ── constants ───────────────────────────────────────────────────────────────────────

def test_constant_price_in_native_unit_lands_in_the_carriers_column(client: TestClient) -> None:
    r = _post(client, "price/set", carrier="gas", price=8.0, unit="MMBtu")
    assert r.status_code == 200, r.text
    assert r.json()["thermalPrice"] == pytest.approx(8.0 * MMBTU_PER_MWH)
    gas = next(c for c in model_store.load_full_model(SID, static_only=True)["carriers"] if c["name"] == "gas")
    assert gas[fc.FLAT_COLUMN] == pytest.approx(27.297136)
    assert gas["co2_emissions"] == 0.2          # the rest of the row is untouched


def test_constant_for_a_carrier_that_only_units_use_adds_a_carriers_row(client: TestClient) -> None:
    model = _model(sheets=False)
    model["carriers"] = [c for c in model["carriers"] if c["name"] != "coal"]
    model_store.save_model(SID, model)
    assert _post(client, "price/set", carrier="coal", price=20.0).status_code == 200
    assert {"name": "coal", fc.FLAT_COLUMN: 20.0} in model_store.load_full_model(SID, static_only=True)["carriers"]


def test_bad_inputs_are_sentences_that_name_the_valid_choices(client: TestClient) -> None:
    r = _post(client, "price/set", carrier="power", price=10.0)
    assert r.status_code == 400 and "unknown carrier 'power'; valid:" in r.json()["detail"] and "'gas'" in r.json()["detail"]
    r = _post(client, "price/set", carrier="gas", price=10.0, unit="tonne")
    assert r.status_code == 400 and "valid: MWh_th or MMBtu" in r.json()["detail"]
    r = _post(client, "price/set", carrier="gas")
    assert r.status_code == 400 and "exactly one of price" in r.json()["detail"]
    r = _post(client, "price/set", carrier="gas", price=1.0, series=[{"snapshot": STAMPS[0], "price": 1.0}])
    assert r.status_code == 400
    r = _post(client, "price/set", carrier="gas", series=[{"snapshot": "2031-05-05T00:00:00", "price": 1.0}])
    assert r.status_code == 400 and "not on the model's axis" in r.json()["detail"] and "4 snapshots" in r.json()["detail"]
    r = _post(client, "price/set", carrier="gas", series=[{"snapshot": STAMPS[0], "price": 1.0}, {"snapshot": STAMPS[0], "price": 2.0}])
    assert r.status_code == 400 and "twice" in r.json()["detail"]
    r = _post(client, "price/remove", carrier="gas")
    assert r.status_code == 400 and "no fuel price to remove" in r.json()["detail"]
    assert _sheet(fc.SHEET_PRICES) == []        # nothing was written by any refused call


# ── series ──────────────────────────────────────────────────────────────────────────

def test_series_writes_the_wide_sheet_and_the_preview_follows_it(client: TestClient) -> None:
    gas = [50.0, 30.0, 50.0, 30.0]
    r = _post(client, "price/set", carrier="coal", series=[{"snapshot": s, "price": p} for s, p in zip(STAMPS, [20.0, 20.0, 40.0, 40.0])])
    assert r.status_code == 200, r.text
    assert r.json()["snapshots"] == 4 and r.json()["min"] == 20.0 and r.json()["mode"] == "replace"
    assert _post(client, "price/set", carrier="gas", series=[{"snapshot": s, "price": p} for s, p in zip(STAMPS, gas)]).status_code == 200
    rows = _sheet(fc.SHEET_PRICES)
    assert [r["snapshot"] for r in rows] == STAMPS and rows[2] == {"snapshot": STAMPS[2], "coal": 40.0, "gas": 50.0}
    assert model_store.get_meta(SID)["sheets"] and any(s["name"] == fc.SHEET_PRICES and s["kind"] == "series" for s in model_store.get_meta(SID)["sheets"])
    assert _post(client, "vom/set", component="Generator", name="coal", vom=3.0).status_code == 200
    body = client.post("/api/fuel-costs/preview", json={"sessionId": SID}).json()
    coal = next(u for u in body["units"] if u["name"] == "coal")
    assert coal["marginalCost"]["newMean"] == pytest.approx((20 / ETA_COAL + 3 + 20 / ETA_COAL + 3 + 40 / ETA_COAL + 3 + 40 / ETA_COAL + 3) / 4)


def test_series_in_native_unit_is_converted_per_value(client: TestClient) -> None:
    r = _post(client, "price/set", carrier="gas", unit="MMBtu", series=[{"snapshot": STAMPS[0], "price": 10.0}, {"snapshot": STAMPS[1], "price": 5.0}])
    assert r.status_code == 200
    vals = {row["snapshot"]: row["gas"] for row in _sheet(fc.SHEET_PRICES)}
    assert vals == {STAMPS[0]: pytest.approx(34.12142), STAMPS[1]: pytest.approx(17.06071)}


def test_replace_blanks_the_other_snapshots_and_merge_keeps_them(client: TestClient) -> None:
    full = [{"snapshot": s, "price": 10.0 + i} for i, s in enumerate(STAMPS)]
    _post(client, "price/set", carrier="gas", series=full)
    _post(client, "price/set", carrier="gas", merge=True, series=[{"snapshot": STAMPS[1], "price": 99.0}])
    assert [r["gas"] for r in _sheet(fc.SHEET_PRICES)] == [10.0, 99.0, 12.0, 13.0]
    r = _post(client, "price/set", carrier="gas", series=[{"snapshot": STAMPS[2], "price": 7.0}])   # replace: the rest is "no price"
    assert r.json()["sheetRows"] == 1
    assert _sheet(fc.SHEET_PRICES) == [{"snapshot": STAMPS[2], "gas": 7.0}]


def test_a_second_carrier_keeps_the_first_and_label_spelling_follows_the_snapshots_sheet(client: TestClient) -> None:
    _post(client, "price/set", carrier="gas", series=[{"snapshot": "2030-01-01 00:00", "price": 30.0}])
    _post(client, "price/set", carrier="coal", series=[{"snapshot": "2030-01-01T00:00:00", "price": 20.0}])
    assert _sheet(fc.SHEET_PRICES) == [{"snapshot": STAMPS[0], "gas": 30.0, "coal": 20.0}]


def test_constant_and_series_do_not_silently_shadow_each_other(client: TestClient) -> None:
    _post(client, "price/set", carrier="gas", series=[{"snapshot": STAMPS[0], "price": 30.0}])
    r = _post(client, "price/set", carrier="gas", price=25.0)
    assert r.status_code == 400 and "supersedes the constant" in r.json()["detail"]
    removed = _post(client, "price/remove", carrier="gas").json()
    assert removed["removed"] == {"series": True, "flat": False} and _sheet(fc.SHEET_PRICES) == []
    assert _post(client, "price/set", carrier="gas", price=25.0).status_code == 200


def test_remove_drops_the_column_and_the_flat_price(client: TestClient) -> None:
    _post(client, "price/set", carrier="coal", price=20.0)
    _post(client, "price/set", carrier="gas", series=[{"snapshot": STAMPS[0], "price": 30.0}])
    assert _post(client, "price/remove", carrier="coal").json()["removed"] == {"series": False, "flat": True}
    assert all(fc.FLAT_COLUMN not in c for c in model_store.load_full_model(SID, static_only=True)["carriers"])
    assert _post(client, "price/remove", carrier="gas").json()["removed"]["series"] is True
    assert client.get("/api/fuel-costs/inputs", params={"session_id": SID}).json()["active"] is False


def test_inputs_read_back_what_was_written(client: TestClient) -> None:
    _post(client, "price/set", carrier="coal", price=20.0)
    _post(client, "price/set", carrier="gas", series=[{"snapshot": s, "price": p} for s, p in zip(STAMPS, [10.0, 20.0, 30.0, 40.0])])
    _post(client, "vom/set", component="Link", carrier="CCGT", vom=2.0)
    _post(client, "scenario-price/set", scenario="high", carrier="gas", multiplier=1.5)
    body = client.get("/api/fuel-costs/inputs", params={"session_id": SID}).json()
    by = {p["carrier"]: p for p in body["prices"]}
    assert by["coal"] == {"carrier": "coal", "source": "flat", "value": 20.0}
    assert by["gas"]["source"] == "series" and by["gas"]["mean"] == 25.0 and by["gas"]["snapshots"] == 4
    assert body["vom"] == [{"component": "Link", "carrier": "CCGT", "vom": 2.0}]
    assert body["scenarioPrices"][0]["scenario"] == "high" and body["nativeUnits"]["gas"] == "MMBtu"
    assert body["active"] is True


# ── VOM ─────────────────────────────────────────────────────────────────────────────

def test_vom_set_replaces_the_same_key_and_remove_deletes_it(client: TestClient) -> None:
    _post(client, "vom/set", component="Generator", name="coal", vom=3.0)
    _post(client, "vom/set", component="Generator", carrier="coal", vom=4.0)
    _post(client, "vom/set", component="Generator", name="coal", vom=5.0)
    assert _sheet(fc.SHEET_VOM) == [{"component": "Generator", "carrier": "coal", "vom": 4.0}, {"component": "Generator", "name": "coal", "vom": 5.0}]
    assert _post(client, "vom/remove", component="Generator", name="coal").status_code == 200
    assert _sheet(fc.SHEET_VOM) == [{"component": "Generator", "carrier": "coal", "vom": 4.0}]


def test_vom_refusals(client: TestClient) -> None:
    for body, needle in [
        ({"component": "Store", "name": "coal", "vom": 1.0}, "component must be one of Generator, Link"),
        ({"component": "Generator", "vom": 1.0}, "either name"),
        ({"component": "Generator", "name": "coal", "carrier": "coal", "vom": 1.0}, "either name"),
        ({"component": "Generator", "name": "nope", "vom": 1.0}, "no Generator named 'nope'; valid: 'coal'"),
        ({"component": "Link", "carrier": "oil", "vom": 1.0}, "no Link has carrier 'oil'; carriers in use: 'CCGT'"),
        ({"component": "Generator", "name": "coal", "vom": -1.0}, "vom must be a finite number >= 0"),
    ]:
        r = _post(client, "vom/set", **body)
        assert r.status_code == 400 and needle in r.json()["detail"], (body, r.text)
    r = _post(client, "vom/remove", component="Generator", name="coal")
    assert r.status_code == 400 and "no VOM row" in r.json()["detail"]
    assert _sheet(fc.SHEET_VOM) == []


# ── scenario prices ─────────────────────────────────────────────────────────────────

def test_scenario_price_rows_set_replace_and_remove(client: TestClient) -> None:
    _post(client, "price/set", carrier="gas", series=[{"snapshot": s, "price": 10.0} for s in STAMPS])
    assert _post(client, "scenario-price/set", scenario="high", carrier="gas", multiplier=2.0).status_code == 200
    assert _post(client, "scenario-price/set", scenario="high", carrier="gas", multiplier=3.0).status_code == 200  # same key: replaced
    r = _post(client, "scenario-price/set", scenario="high", carrier="gas", snapshot="2030-01-01 02:00", price=1.0, unit="MMBtu")
    rows = r.json()["rows"]
    assert len(rows) == 2 and rows[0]["multiplier"] == 3.0
    assert rows[1] == {"scenario": "high", "carrier": "gas", "snapshot": STAMPS[2], "price": pytest.approx(MMBTU_PER_MWH)}
    scen = fc.read_price_scenarios({fc.SHEET_PRICE_SCENARIOS: _sheet(fc.SHEET_PRICE_SCENARIOS)})
    assert [c.multiplier for c in scen] == [3.0, None]
    assert _post(client, "scenario-price/remove", scenario="high", carrier="gas").status_code == 200
    assert len(_sheet(fc.SHEET_PRICE_SCENARIOS)) == 1


def test_scenario_price_refusals(client: TestClient) -> None:
    for body, needle in [
        ({"scenario": "", "carrier": "gas", "price": 1.0}, "give a scenario"),
        ({"scenario": "s", "carrier": "gas"}, "give a price"),
        ({"scenario": "s", "carrier": "gas", "multiplier": -1.0}, "multiplier must be"),
        ({"scenario": "s", "carrier": "steam", "price": 1.0}, "unknown carrier 'steam'"),
        ({"scenario": "s", "carrier": "gas", "snapshot": "2031-01-01", "price": 1.0}, "not on the model's axis"),
    ]:
        r = _post(client, "scenario-price/set", **body)
        assert r.status_code == 400 and needle in r.json()["detail"], (body, r.text)
    r = _post(client, "scenario-price/remove", scenario="s", carrier="gas")
    assert r.status_code == 400 and "no scenario price row" in r.json()["detail"]


def test_edit_without_a_model_is_a_400() -> None:
    c = TestClient(app)
    r = c.post("/api/fuel-costs/price/set", json={"sessionId": "test-fuel-costs-none", "carrier": "gas", "price": 1.0})
    assert r.status_code == 400 and "No model loaded" in r.json()["detail"]


def test_a_stochastic_preview_uses_an_authored_scenario_row(client: TestClient) -> None:
    _post(client, "price/set", carrier="gas", series=[{"snapshot": s, "price": 30.0} for s in STAMPS])
    _post(client, "vom/set", component="Generator", name="coal", vom=0.0)
    _post(client, "price/set", carrier="coal", price=20.0)
    _post(client, "scenario-price/set", scenario="high", carrier="coal", multiplier=2.0)
    cfg = {"enabled": True, "scenarios": [{"name": "base", "weight": 0.5}, {"name": "high", "weight": 0.5}]}
    body = client.post("/api/fuel-costs/preview", json={"sessionId": SID, "stochasticConfig": cfg}).json()
    assert body["scenarios"], body


def test_stochastic_preview_of_a_model_without_links_after_an_authored_scenario_row(client: TestClient) -> None:
    """Regression: a stochastic network with no Link rows has plain empty Link frames; the per-scenario split used to KeyError (HTTP 500)."""
    model = _model(sheets=False)
    model["links"] = []
    model_store.save_model(SID, model)
    _post(client, "price/set", carrier="coal", price=20.0)
    _post(client, "scenario-price/set", scenario="high", carrier="coal", multiplier=2.0)
    cfg = {"enabled": True, "scenarios": [{"name": "low", "weight": 0.5}, {"name": "high", "weight": 0.5}]}
    r = client.post("/api/fuel-costs/preview", json={"sessionId": SID, "stochasticConfig": cfg})
    assert r.status_code == 200, r.text
    sc = {s["name"]: {u["name"]: u for u in s["units"]} for s in r.json()["scenarios"]}
    assert sc["high"]["coal"]["marginalCost"]["newMean"] == pytest.approx(2 * 20.0 / ETA_COAL)
    assert sc["low"]["coal"]["marginalCost"]["newMean"] == pytest.approx(20.0 / ETA_COAL)


def test_inputs_read_caps_long_vom_lists_with_a_notice(client: TestClient) -> None:
    model = _model(sheets=False)
    model[fc.SHEET_VOM] = [{"component": "Generator", "name": f"g{i}", "vom": 1.0} for i in range(250)]
    model_store.save_model(SID, model)
    body = client.get("/api/fuel-costs/inputs", params={"session_id": SID}).json()
    assert len(body["vom"]) == 200 and "showing 200 of 250 rows" in body["truncated"]
