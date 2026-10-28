"""Parity tests for backend/app/forge_helpers.py against the fixtures of the TS
suites (lib/forge/forge.test.ts, lib/forge/adjust.test.ts, lib/build/conversions.test.ts),
plus the /api/forge/*, /api/build/* and /api/session/merge-fragment endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import forge_helpers as fh


# ── snap (forge.test.ts) ─────────────────────────────────────────────────────


def test_haversine_one_degree_at_equator() -> None:
    assert fh.haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.5)


def test_snap_assigns_nearest_and_reports_outside() -> None:
    targets = fh.build_targets([{"name": "A", "x": 0, "y": 0}, {"name": "B", "x": 1, "y": 0}])
    assert [t["name"] for t in targets] == ["A", "B"]
    assert targets[1]["lat"] == 0 and targets[1]["lon"] == 1
    overlay = [
        {"name": "g1", "x": 0.1, "y": 0, "bus": ""},
        {"name": "g2", "x": 0.9, "y": 0, "bus": ""},
        {"name": "far", "x": 5, "y": 0, "bus": ""},
        {"name": "nogeo", "bus": ""},
    ]
    r = fh.snap_sheet(overlay, targets, 50)
    assert [row["bus"] for row in r["rows"]] == ["A", "B", "", ""]
    assert r["assigned"] == 2 and r["noCoords"] == 1 and r["anchors"] == ["bus"]
    assert len(r["outside"]) == 1
    assert r["outside"][0]["name"] == "far" and r["outside"][0]["nearest"] == "B" and r["outside"][0]["field"] == "bus"
    assert overlay[0]["bus"] == ""  # input not mutated


def test_snap_branch_endpoints() -> None:
    targets = fh.build_targets([{"name": "A", "x": 0, "y": 0}, {"name": "B", "x": 1, "y": 0}])
    r = fh.snap_sheet([{"name": "L", "x0": 0, "y0": 0, "x1": 1, "y1": 0, "bus0": "", "bus1": ""}], targets, 50)
    assert r["rows"][0]["bus0"] == "A" and r["rows"][0]["bus1"] == "B"
    assert r["assigned"] == 2 and sorted(r["anchors"]) == ["bus0", "bus1"]


# ── conversions (conversions.test.ts) ────────────────────────────────────────


def _base() -> dict:
    return {"buses": [{"name": "elec", "carrier": "AC", "x": 10, "y": 20}], "carriers": [{"name": "AC"}],
            "generators": [], "links": []}


def _frag(template: str, model: dict | None = None, **kw):
    opts = {"anchor_bus": "elec", "p_nom": 100, "extendable": False, "name": None, **kw}
    return fh.build_conversion_fragment(fh.get_template(template), model=model or _base(), **opts)["sheets"]


def test_default_anchor_prefers_electricity_bus() -> None:
    assert fh.default_anchor_bus({"buses": [{"name": "h2bus", "carrier": "hydrogen"}, {"name": "grid", "carrier": "AC"}]}) == "grid"
    assert fh.default_anchor_bus({"buses": []}) is None


def test_electrolyser_creates_hydrogen_bus_without_fuel_supply() -> None:
    s = _frag("electrolyser")
    assert s["buses"] == [{"name": "H2", "carrier": "hydrogen", "x": 10, "y": 20}]
    names = [c["name"] for c in s["carriers"]]
    assert "electrolysis" in names and "hydrogen" in names and "AC" not in names
    assert s["links"][0] | {} == s["links"][0]
    assert {"bus0": "elec", "bus1": "H2", "carrier": "electrolysis", "efficiency": 0.7, "p_nom": 100}.items() <= s["links"][0].items()
    assert "generators" not in s


def test_ccgt_has_fuel_supply_and_gas_co2() -> None:
    s = _frag("ccgt", p_nom=250)
    assert s["buses"][0]["name"] == "gas"
    assert {"name": "gas", "co2_emissions": 0.2} in s["carriers"]
    assert {"bus": "gas", "carrier": "gas", "p_nom_extendable": True, "capital_cost": 0, "marginal_cost": 25}.items() <= s["generators"][0].items()
    assert {"bus0": "gas", "bus1": "elec", "carrier": "CCGT", "efficiency": 0.55, "p_nom": 250}.items() <= s["links"][0].items()


def test_chp_has_heat_coproduct() -> None:
    s = _frag("chp")
    link = s["links"][0]
    assert (link["bus0"], link["bus1"], link["bus2"], link["efficiency2"]) == ("gas", "elec", "heat", 0.45)
    assert {"gas", "heat"} <= {b["name"] for b in s["buses"]}


def test_second_electrolyser_reuses_bus_and_dedupes_name() -> None:
    model = {"buses": [{"name": "elec", "carrier": "AC", "x": 10, "y": 20}, {"name": "H2", "carrier": "hydrogen"}],
             "carriers": [{"name": "AC"}, {"name": "hydrogen"}, {"name": "electrolysis"}],
             "generators": [], "links": [{"name": "electrolyser"}]}
    s = _frag("electrolyser", model, p_nom=50)
    assert "buses" not in s and "carriers" not in s
    assert s["links"][0]["bus1"] == "H2" and s["links"][0]["name"] == "electrolyser_2"


def test_extendable_and_unknown_anchor() -> None:
    link = _frag("heat_pump", extendable=True, discount_rate=0.05)["links"][0]
    assert link["p_nom_extendable"] is True and link["overnight_cost"] == 60000 and "p_nom" not in link and link["efficiency"] == 3.0
    assert link["discount_rate"] == 0.05 and link["lifetime"] == 20 and "capital_cost" not in link
    with pytest.raises(ValueError):
        _frag("electrolyser", anchor_bus="nope")


# ── adjust (adjust.test.ts) ──────────────────────────────────────────────────

MODEL = {
    "generators": [
        {"name": "g1", "carrier": "gas", "province": "경상남도", "p_nom": 100},
        {"name": "g2", "carrier": "gas", "province": "서울", "p_nom": 200},
        {"name": "g3", "carrier": "coal", "province": "경상남도", "p_nom": 300},
        {"name": "g4", "carrier": "gas", "province": "경상남도"},
    ]
}


def _adj(filters, attribute="p_nom", action="multiply", amount=50, sheet="generators") -> dict:
    return {"sheet": sheet, "filters": [{"column": c, "value": v} for c, v in filters],
            "attribute": attribute, "action": action, "amount": amount}


def _by(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_multiply_leaves_others_untouched() -> None:
    out = fh.apply_adjustments(MODEL, [_adj([("carrier", "gas"), ("province", "경상남도")])])
    gens = out["sheets"]["generators"]
    assert _by(gens, "g1")["p_nom"] == 50 and _by(gens, "g2")["p_nom"] == 200 and _by(gens, "g3")["p_nom"] == 300
    assert out["changed"] == 1 and out["perAdjustment"] == [1]
    assert _by(MODEL["generators"], "g1")["p_nom"] == 100


def test_add_skips_non_numeric_attribute() -> None:
    out = fh.apply_adjustments(MODEL, [_adj([("carrier", "gas")], action="add", amount=10)])
    assert out["changed"] == 2
    assert "p_nom" not in _by(out["sheets"]["generators"], "g4")


def test_set_writes_missing_attribute() -> None:
    out = fh.apply_adjustments(MODEL, [_adj([("name", "g4")], action="set", amount=5)])
    assert _by(out["sheets"]["generators"], "g4")["p_nom"] == 5 and out["changed"] == 1


def test_stacked_adjustments_compose() -> None:
    out = fh.apply_adjustments(MODEL, [
        _adj([("carrier", "gas")], action="set", amount=100),
        _adj([("province", "경상남도")], action="multiply", amount=200),
    ])
    assert _by(out["sheets"]["generators"], "g1")["p_nom"] == 200


def test_match_count() -> None:
    assert fh.match_count(MODEL, "generators", [{"column": "carrier", "value": "gas"}]) == 3
    assert fh.match_count(MODEL, "generators", [{"column": "carrier", "value": "gas"}, {"column": "province", "value": "경상남도"}]) == 2


def test_revert_goes_to_original_not_previous_step() -> None:
    half = _adj([("carrier", "gas")])
    r1 = fh.apply_adjustments(MODEL, [half, half])
    assert _by(r1["sheets"]["generators"], "g1")["p_nom"] == 25
    rev = fh.revert_adjustments({"generators": r1["sheets"]["generators"]}, [half], r1["baseline"])
    assert _by(rev["sheets"]["generators"], "g1")["p_nom"] == 100
    assert _by(rev["sheets"]["generators"], "g2")["p_nom"] == 200
    assert rev["reverted"] == 2


def test_revert_of_set_on_missing_attribute_removes_it() -> None:
    set_adj = _adj([("name", "g4")], action="set", amount=5)
    r1 = fh.apply_adjustments(MODEL, [set_adj])
    rev = fh.revert_adjustments({"generators": r1["sheets"]["generators"]}, [set_adj], r1["baseline"])
    assert "p_nom" not in _by(rev["sheets"]["generators"], "g4")


def test_revert_without_baseline_is_noop() -> None:
    rev = fh.revert_adjustments(MODEL, [_adj([("carrier", "gas")])], {})
    assert rev["reverted"] == 0 and rev["sheets"] == {}


# ── endpoints ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend.app import session_store
    from backend.app.main import app

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")

    return TestClient(app)


def _load(client, sid, model):
    assert client.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200


def test_snap_endpoint_apply_writes_session(client) -> None:
    sid = "t-snap"
    _load(client, sid, {"buses": [{"name": "A", "x": 0, "y": 0}, {"name": "B", "x": 1, "y": 0}],
                        "generators": [{"name": "g1", "x": 0.1, "y": 0, "bus": ""}]})
    r = client.post("/api/forge/snap", json={"sessionId": sid, "sheet": "generators", "bufferKm": 50, "apply": True}).json()
    assert r["assigned"] == 1 and r["applied"] is True
    page = client.get(f"/api/session/sheet/generators", params={"session_id": sid}).json()
    assert page["rows"][0]["bus"] == "A"


def test_adjust_and_revert_endpoints_round_trip(client) -> None:
    sid = "t-adj"
    _load(client, sid, MODEL)
    body = {"sessionId": sid, "adjustments": [_adj([("carrier", "gas")])], "apply": True}
    r = client.post("/api/forge/adjust", json=body).json()
    assert r["changed"] == 2 and r["applied"] is True
    rows = client.get("/api/session/sheet/generators", params={"session_id": sid}).json()["rows"]
    assert _by(rows, "g1")["p_nom"] == 50
    rev = client.post("/api/forge/adjust/revert", json={**body, "baseline": r["baseline"]}).json()
    assert rev["reverted"] == 2
    rows = client.get("/api/session/sheet/generators", params={"session_id": sid}).json()["rows"]
    assert _by(rows, "g1")["p_nom"] == 100


def test_conversion_endpoints(client) -> None:
    sid = "t-conv"
    _load(client, sid, _base())
    listing = client.get("/api/build/conversions", params={"session_id": sid}).json()
    assert listing["total"] == 9 and listing["defaultAnchorBus"] == "elec"
    r = client.post("/api/build/conversion", json={"sessionId": sid, "templateId": "electrolyser", "apply": True}).json()
    assert r["applied"] is True and r["fragment"]["sheets"]["links"][0]["bus1"] == "H2"
    links = client.get("/api/session/sheet/links", params={"session_id": sid}).json()["rows"]
    assert links[0]["name"] == "electrolyser"
    bad = client.post("/api/build/conversion", json={"sessionId": sid, "templateId": "nope"})
    assert bad.status_code == 400


def test_merge_fragment_endpoint_stateless_and_session(client) -> None:
    frag = {"sheets": {"buses": [{"name": "b1"}]}}
    out = client.post("/api/session/merge-fragment", json={"model": {"buses": [{"name": "b1"}]}, "fragment": frag}).json()
    assert [b["name"] for b in out["model"]["buses"]] == ["b1", "b1_2"] and out["applied"] is False
    sid = "t-merge"
    _load(client, sid, {"buses": [{"name": "b1"}]})
    out = client.post("/api/session/merge-fragment", json={"sessionId": sid, "fragment": frag, "apply": True}).json()
    assert out["applied"] is True and out["sheets"]["buses"] == 2 and "model" not in out
    rows = client.get("/api/session/sheet/buses", params={"session_id": sid}).json()["rows"]
    assert [b["name"] for b in rows] == ["b1", "b1_2"]


def test_snap_endpoint_inline_rows_and_target_rows(client) -> None:
    r = client.post("/api/forge/snap", json={
        "rows": [{"name": "g1", "x": 0.1, "y": 0, "bus": ""}],
        "targetRows": [{"name": "A", "x": 0, "y": 0}, {"name": "B", "x": 1, "y": 0}],
        "bufferKm": 50,
    }).json()
    assert r["rows"][0]["bus"] == "A" and r["applied"] is False and r["targets"] == 2
