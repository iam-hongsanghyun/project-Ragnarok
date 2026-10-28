"""Plant routes, change sets (edit / delete keep shared buses and carriers), the `plant` column round trip, MCP tools, results groupby."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from numpy.testing import assert_allclose

from backend.app import main, run_store, session_store
from backend.app.plants import registry
from backend.app.routers import results_derived as rd_router
from backend.mcp import server, tools_plants
from backend.mcp.client import Config, RagnarokClient
from backend.pypsa.network import build_components
from backend.pypsa.network.pypsa_io import export_network_bytes, network_from_csv_zip
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results import run_pypsa

from ._plants_fixtures import SCENARIO, add_plant, grid, with_h2_window

SID = "plants-t"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    rd_router._BUNDLE_CACHE.clear()
    return TestClient(main.app)


def _load(client: TestClient, model: dict[str, Any], sid: str = SID) -> None:
    assert client.post("/api/session/model", json={"model": model, "sessionId": sid}).status_code == 200


def _rows(client: TestClient, sheet: str, sid: str = SID) -> list[dict[str, Any]]:
    r = client.get(f"/api/session/sheet/{sheet}", params={"session_id": sid})
    return [] if r.status_code == 404 else r.json()["rows"]


def _names(client: TestClient, sheet: str, sid: str = SID) -> set[str]:
    return {r["name"] for r in _rows(client, sheet, sid)}


def test_types_technologies_and_defaults(client: TestClient) -> None:
    types = client.get("/api/build/plant/types").json()["types"]
    assert [t["id"] for t in types] == ["generator", "bess", "ccgt", "ocgt", "cofiring_simple", "cofiring_network", "p2x"]
    ccgt = next(t for t in types if t["id"] == "ccgt")
    keys = {f["key"]: f for f in ccgt["fields"]}
    assert {"bus", "pNom", "extendable", "committable"} <= set(keys) and keys["params"]["advanced"] is True
    assert keys["pNom"]["advanced"] is False and ccgt["defaults"]["pNom"] == 100.0
    tech = client.get("/api/build/plant/technologies").json()
    assert tech["sources"]["technology-data"]["version"] == "v0.15.0"
    p = tech["technologies"]["ccgt"]["parameters"]["min_load"]
    assert p["verified"] == "file" and "row 19" in p["source"]["locator"] and p["default"] == p["value"]


def test_preview_writes_nothing_apply_writes_one_plant(client: TestClient) -> None:
    _load(client, grid())
    body = {"sessionId": SID, "type": "ccgt", "spec": {"pNom": 400, "committable": True}}
    prev = client.post("/api/build/plant", json=body).json()
    assert prev["applied"] is False and prev["plantId"] == "ccgt" and prev["rowCounts"]["links"] == 1
    assert _names(client, "links") == set()
    done = client.post("/api/build/plant", json={**body, "apply": True}).json()
    assert done["applied"] is True
    link = _rows(client, "links")[0]
    assert link["name"] == "ccgt" and link["plant"] == "ccgt" and link["committable"] is True
    assert {r["name"] for r in _rows(client, "buses")} == {"grid", "ccgt_bus_gas"}
    plants = client.get("/api/build/plants", params={"session_id": SID}).json()["plants"]
    assert [p["plantId"] for p in plants] == ["ccgt"] and plants[0]["editable"] is True
    assert {c["name"] for c in plants[0]["components"]} >= {"ccgt", "ccgt_gas_supply", "ccgt_bus_gas", "gas"}
    meta = client.get("/api/session/meta", params={"session_id": SID}).json()
    cols = {s["name"]: s.get("columns", []) for s in meta["sheets"]}
    assert "plant" in cols["links"] and "plant" in cols["buses"]          # a column only some rows carry is still a column
    assert client.post("/api/build/plant", json={**body, "type": "nope"}).status_code == 400
    assert client.post("/api/build/plant", json={**body, "spec": {"bus": "zz"}}).status_code == 400


def test_edit_rederives_the_components_under_the_same_id(client: TestClient) -> None:
    model = grid()
    model["generators"] = [{"name": "other", "bus": "grid", "carrier": "AC", "p_nom": 5}]
    _load(client, model)
    client.post("/api/build/plant", json={"sessionId": SID, "type": "cofiring_network", "spec": {"pNom": 200, "plantId": "hyb", "blendMax": 0.3, "blendUnit": "vol"}, "apply": True})
    before = {s: _names(client, s) for s in ("buses", "generators", "links", "carriers")}
    prev = client.post("/api/build/plant/edit", json={"sessionId": SID, "plantId": "hyb", "spec": {"pNom": 350, "blendMax": 0.2}}).json()
    assert prev["applied"] is False and prev["spec"]["pNom"] == 350 and prev["removed"]["links"] == 3 and prev["label"].endswith("hyb")
    assert {s: _names(client, s) for s in before} == before                         # preview wrote nothing
    done = client.post("/api/build/plant/edit", json={"sessionId": SID, "plantId": "hyb", "spec": {"pNom": 350, "blendMax": 0.2}, "apply": True}).json()
    assert done["applied"] is True
    assert {s: _names(client, s) for s in before} == before                         # same components, same names
    assert "other" in _names(client, "generators")
    turbine = next(r for r in _rows(client, "links") if r["name"] == "hyb")
    assert_allclose(turbine["p_nom"], 350 / 0.58, rtol=1e-6)
    reg = json.loads(next(r for r in _rows(client, "RAGNAROK_PLANTS") if r["name"] == "hyb")["json"])
    assert reg["spec"]["pNom"] == 350 and reg["spec"]["blendMax"] == 0.2 and len(_rows(client, "RAGNAROK_PLANTS")) == 1
    assert client.post("/api/build/plant/edit", json={"sessionId": SID, "plantId": "ghost", "spec": {}}).status_code == 400


def test_delete_removes_every_component_of_the_plant_and_nothing_else(client: TestClient) -> None:
    model = with_h2_window(grid())
    model["generators"].append({"name": "keepme", "bus": "grid", "carrier": "AC", "p_nom": 1})
    _load(client, model)
    before = {s: _names(client, s) for s in ("buses", "generators", "links", "loads", "carriers")}
    for t, spec in (("bess", {"plantId": "bat"}), ("cofiring_simple", {"plantId": "simple"}), ("p2x", {"plantId": "ely", "product": "NH3"})):
        assert client.post("/api/build/plant", json={"sessionId": SID, "type": t, "spec": spec, "apply": True}).status_code == 200
    ids = {p["plantId"] for p in client.get("/api/build/plants", params={"session_id": SID}).json()["plants"]}
    assert ids == {"bat", "simple", "ely"}
    for pid in ("ely", "simple", "bat"):
        out = client.post("/api/build/plant/delete", json={"sessionId": SID, "plantId": pid, "apply": True}).json()
        assert out["applied"] is True
    after = {s: _names(client, s) for s in before}
    assert after == before                                                          # exactly the original model again
    assert _rows(client, "RAGNAROK_PLANTS") == [] and _rows(client, "RAGNAROK_P2X") == []
    assert _names(client, "processes") == set() and _names(client, "storage_units") == set()
    assert client.post("/api/build/plant/delete", json={"sessionId": SID, "plantId": "ely"}).status_code == 404


def test_shared_buses_and_carriers_other_components_use_are_kept() -> None:
    model, _ = add_plant(grid(), "ccgt", {"pNom": 100})                             # creates bus ccgt_bus_gas, carrier gas, supplier
    model, _ = add_plant(model, "ocgt", {"pNom": 50})                               # a second plant on the same gas bus
    model["generators"].append({"name": "user_gas_unit", "bus": "ccgt_bus_gas", "carrier": "gas", "p_nom": 10})
    change = registry.delete_change(model, "ccgt")
    assert "ccgt_bus_gas" in change["kept"]["buses"] and "gas" in change["kept"]["carriers"]
    assert "buses" not in change["remove"] and "gas" not in change["remove"].get("carriers", [])
    assert change["remove"]["carriers"] == ["CCGT"]                                 # its own link carrier nothing else uses goes
    assert set(change["remove"]["links"]) == {"ccgt"} and "ccgt_gas_supply" in change["remove"]["generators"]
    out = registry.apply_change(model, change)
    assert "ccgt_bus_gas" in {b["name"] for b in out["buses"]} and "gas" in {c["name"] for c in out["carriers"]}
    assert not any(r.get("plant") == "ccgt" for sheet in registry.component_sheets(out) for r in out[sheet])      # released, no stale id
    assert {r["name"] for r in out["links"]} == {"ocgt"} and any(g["name"] == "user_gas_unit" for g in out["generators"])
    assert any("nothing feeds" in w for w in change["warnings"]) is False           # user_gas_unit still feeds the bus
    # an unshared plant takes its bus and carrier with it
    solo, _ = add_plant(grid(), "ocgt", {"pNom": 50})
    solo_out = registry.apply_change(solo, registry.delete_change(solo, "ocgt"))
    assert [b["name"] for b in solo_out["buses"]] == ["grid"] and [c["name"] for c in solo_out["carriers"]] == [c["name"] for c in grid()["carriers"]]
    # the second plant's gas supplier is gone with the first: the bus it uses is reported as unfed
    two, _ = add_plant(grid(), "ccgt", {"pNom": 10})
    two, _ = add_plant(two, "ocgt", {"pNom": 10})
    assert any("nothing feeds" in w for w in registry.delete_change(two, "ccgt")["warnings"])


def test_inline_model_is_stateless_and_apply_with_inline_model_is_refused(client: TestClient) -> None:
    m = grid()
    out = client.post("/api/build/plant", json={"type": "bess", "spec": {"plantId": "b1"}, "model": m}).json()
    assert out["change"]["remove"] == {} and out["change"]["fragment"]["sheets"]["storage_units"][0]["plant"] == "b1"
    assert client.post("/api/build/plant", json={"type": "bess", "model": m, "apply": True}).status_code == 400
    merged = registry.apply_change(m, out["change"])
    delete = client.post("/api/build/plant/delete", json={"plantId": "b1", "model": merged}).json()
    assert registry.apply_change(merged, delete["change"])["storage_units"] == []


@pytest.mark.parametrize("fmt", ["csv", "netcdf"])
def test_plant_column_survives_a_pypsa_export_and_import(fmt: str, tmp_path: Path) -> None:
    import pypsa

    model, _ = add_plant(grid(), "cofiring_network", {"pNom": 100, "plantId": "hyb"})
    net, _ = build_components(model)
    data, _m, _n = export_network_bytes(net, fmt)
    if fmt == "csv":
        back = network_from_csv_zip(data)
    else:
        f = tmp_path / "n.nc"
        f.write_bytes(data)
        back = pypsa.Network(str(f))
    rows = network_to_model(back)
    tagged = {s: {r["name"] for r in rs if r.get("plant") == "hyb"} for s, rs in rows.items() if isinstance(rs, list) and rs and "plant" in rs[0]}
    want = {s: {r["name"] for r in model[s] if r.get("plant") == "hyb"} for s in ("buses", "generators", "links", "carriers")}
    assert {s: tagged.get(s, set()) for s in want} == want
    assert not any(r.get("plant") for r in rows["loads"])                           # the user's load was never part of the plant
    # without the registry (it is not a PyPSA table) the plant is still listed and can be deleted
    imported = {s: rs for s, rs in rows.items() if isinstance(rs, list)}
    card = registry.list_plants(imported)[0]
    assert card["plantId"] == "hyb" and card["editable"] is False
    gone = registry.apply_change(imported, registry.delete_change(imported, "hyb"))
    assert not gone.get("links")


def test_session_save_load_keeps_the_plant_column_and_registry(client: TestClient) -> None:
    model, _ = add_plant(grid(), "ccgt", {"pNom": 100})
    _load(client, model, "plants-rt")
    full = client.get("/api/session/model", params={"session_id": "plants-rt"})
    sheets = full.json().get("model") if full.status_code == 200 and "model" in full.json() else None
    rows = _rows(client, "links", "plants-rt")
    assert rows[0]["plant"] == "ccgt"
    assert json.loads(_rows(client, "RAGNAROK_PLANTS", "plants-rt")[0]["json"])["type"] == "ccgt"
    assert sheets is None or sheets["links"][0]["plant"] == "ccgt"


# ── results groupby ──────────────────────────────────────────────────────────────


def test_results_endpoint_groups_by_plant(client: TestClient) -> None:
    model = with_h2_window(grid(hours=24), price=10.0)
    model, _ = add_plant(model, "cofiring_network", {"plantId": "hyb", "pNom": 150, "h2Bus": "h2", "blendMax": 0.3, "blendUnit": "vol"})
    model, _ = add_plant(model, "bess", {"plantId": "bat", "pNom": 10})
    res = run_pypsa(model, SCENARIO, {})
    name = run_store.store_run(model, dict(SCENARIO), {}, res)["name"]
    out = client.get(f"/api/build/plant/results/{name}").json()
    by = {p["plantId"]: p for p in out["plants"]}
    assert set(by) == {"hyb", "bat"}
    hyb = by["hyb"]
    assert_allclose(hyb["generationMwh"], 2400.0, rtol=1e-6)
    assert hyb["emissions"]["avoidedT"] > 0 and len(hyb["series"]["h2VolShare"]) == 24
    assert max(hyb["series"]["h2VolShare"]) == pytest.approx(0.30, rel=1e-6)
    assert_allclose(out["totals"]["totalCost"], sum(p["totalCost"] for p in out["plants"]), rtol=1e-12)            # groupby sums to the total
    assert_allclose(out["totals"]["emissionsAvoidedT"], hyb["emissions"]["avoidedT"], rtol=1e-12)
    one = client.get(f"/api/build/plant/results/{name}", params={"plant": "hyb", "include_series": "false"}).json()
    assert [p["plantId"] for p in one["plants"]] == ["hyb"] and "series" not in one["plants"][0]
    assert client.get(f"/api/build/plant/results/{name}", params={"plant": "zz"}).status_code == 400
    assert client.get("/api/build/plant/results/nope").status_code == 404
    plain = run_store.store_run(grid(4), dict(SCENARIO), {}, run_pypsa({**grid(4), "generators": [{"name": "g", "bus": "grid", "carrier": "AC", "p_nom": 200, "marginal_cost": 1}]}, SCENARIO, {}))
    assert client.get(f"/api/build/plant/results/{plain['name']}").status_code == 400


# ── MCP ──────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def wired(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> RagnarokClient:
    monkeypatch.setenv("RAGNAROK_MCP_AUTONOMY", "guided")
    c = RagnarokClient(Config(api_base="http://test", session_id="plants-mcp", timeout=60.0), transport=httpx.ASGITransport(app=main.app))
    monkeypatch.setattr(server, "_client", c)
    _load(client, grid(), "plants-mcp")
    return c


def test_mcp_tools_registered_with_read_only_flags() -> None:
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    expected = {"list_plant_types": True, "get_plant_results": True, "add_plant": False, "edit_plant": False, "remove_plant": False}
    for name, read_only in expected.items():
        assert name in tools and tools[name].annotations.readOnlyHint is read_only
    assert "add_conversion" in tools                                                # the existing conversion tool keeps working


def test_mcp_add_edit_remove_are_gated_and_write_one_plant(wired: RagnarokClient, client: TestClient) -> None:
    sid = "plants-mcp"

    async def go() -> None:
        types = await tools_plants.list_plant_types()
        assert {t["id"] for t in types["types"]} >= {"ccgt", "cofiring_network"}
        gated = await tools_plants.add_plant("ocgt", {"pNom": 80})
        assert gated["status"] == "preview" and _names(client, "links", sid) == set()
        done = await tools_plants.add_plant("ocgt", {"pNom": 80, "plantId": "peaker"}, confirm=True)
        assert done["applied"] is True and done["plantId"] == "peaker"
        g2 = await tools_plants.edit_plant("peaker", {"pNom": 120})
        assert g2["status"] == "preview"
        assert next(r for r in _rows(client, "links", sid) if r["name"] == "peaker")["p_nom"] == pytest.approx(80 / 0.41, rel=1e-6)
        await tools_plants.edit_plant("peaker", {"pNom": 120}, confirm=True)
        assert next(r for r in _rows(client, "links", sid) if r["name"] == "peaker")["p_nom"] == pytest.approx(120 / 0.41, rel=1e-6)
        assert (await tools_plants.remove_plant("peaker"))["status"] == "preview" and "peaker" in _names(client, "links", sid)
        gone = await tools_plants.remove_plant("peaker", confirm=True)
        assert gone["applied"] is True and _names(client, "links", sid) == set() and _names(client, "buses", sid) == {"grid"}

    asyncio.run(go())


def test_mcp_get_plant_results_is_read_only_and_drops_series_by_default(wired: RagnarokClient, client: TestClient) -> None:
    model = with_h2_window(grid(hours=24), price=10.0)
    model, _ = add_plant(model, "cofiring_network", {"plantId": "hyb", "pNom": 150, "h2Bus": "h2", "blendMax": 0.3, "blendUnit": "vol"})
    res = run_pypsa(model, SCENARIO, {})
    name = run_store.store_run(model, dict(SCENARIO), {}, res)["name"]

    async def go() -> None:
        lean = await tools_plants.get_plant_results(name, plant_id="hyb")
        assert [p["plantId"] for p in lean["plants"]] == ["hyb"] and "seriesHint" in lean
        full = await tools_plants.get_plant_results(name, plant_id="hyb", include_series=True)
        assert len(full["plants"][0]["series"]["h2VolShare"]) == 24
        assert_allclose(max(full["plants"][0]["series"]["h2VolShare"]), 0.30, rtol=1e-6)

    asyncio.run(go())


def test_extras_apply_edit_and_delete_through_the_session(client: TestClient) -> None:
    """Part-load curve rows, start-cost rows and time-units rows are written with the plant, replaced by an edit and removed by a delete."""
    _load(client, grid())
    spec = {"pNom": 58, "committable": True, "minLoadEfficiency": 0.52, "startCostWarm": 120, "startWarmAfterHours": 8, "startCostCold": 200,
            "startColdAfterHours": 48, "startUpMinutes": 30}
    done = client.post("/api/build/plant", json={"sessionId": SID, "type": "ccgt", "spec": spec, "apply": True}).json()
    assert done["applied"] is True and done["registry"]["partLoad"]["route"] == "piecewise-link"
    assert next(s for s in done["summary"] if s["sheet"] == "links")["partLoad"]["noLoadFuelMw"] > 0        # derived values in the preview
    assert [r["breakpoint"] for r in _rows(client, "links-efficiency-pw")] == [0, 1, 2]
    assert {r["attribute"] for r in _rows(client, "RAGNAROK_StartCosts")} == {"hot_cost", "warm_cost", "warm_after", "cold_cost", "cold_after"}
    assert "ramp_limit_start_up" in {r["attribute"] for r in _rows(client, "RAGNAROK_TimeUnits")}
    edited = client.post("/api/build/plant/edit", json={"sessionId": SID, "plantId": "ccgt", "spec": {"minLoadEfficiency": 0.5, "startCostCold": None, "startColdAfterHours": None}, "apply": True})
    assert edited.status_code == 200, edited.text
    assert [r["efficiency"] for r in _rows(client, "links-efficiency-pw")][1] == 0.5
    assert {r["attribute"] for r in _rows(client, "RAGNAROK_StartCosts")} == {"hot_cost", "warm_cost", "warm_after"}
    off = client.post("/api/build/plant/edit", json={"sessionId": SID, "plantId": "ccgt", "spec": {"minLoadEfficiency": None}, "apply": True})
    assert off.status_code == 200 and _rows(client, "links-efficiency-pw") == []                              # the curve is removed, not orphaned
    gone = client.post("/api/build/plant/delete", json={"sessionId": SID, "plantId": "ccgt", "apply": True})
    assert gone.status_code == 200
    assert _rows(client, "RAGNAROK_StartCosts") == [] and _rows(client, "RAGNAROK_TimeUnits") == [] and _names(client, "links") == set()
