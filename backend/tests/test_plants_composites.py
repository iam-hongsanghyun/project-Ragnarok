"""Composites as ONE asset: the visible instance sheet, shared investment fields, placement on several buses, detach."""
from __future__ import annotations

from typing import Any

import pytest

from backend.app import fragment_merge
from backend.app.plants import catalog, registry
from backend.app.plants.catalog import COMPOSITES_SHEET

from ._plants_fixtures import grid

Model = dict[str, list[dict[str, Any]]]
CHILD_SHEETS = ("generators", "links", "stores", "storage_units", "processes")


def _model() -> Model:
    m = grid()
    m["buses"] = [*m["buses"], {"name": "KR-1", "carrier": "AC"}, {"name": "KR-2", "carrier": "AC"}, {"name": "KR-3", "carrier": "AC"}]
    return m


def _children(model: Model, pid: str) -> list[tuple[str, dict[str, Any]]]:
    return [(s, r) for s in CHILD_SHEETS for r in model.get(s, []) if r.get("plant") == pid]


def _add(model: Model, type_id: str, spec: dict[str, Any]) -> tuple[Model, dict[str, Any]]:
    built = catalog.build_plant(type_id, spec, model)
    return fragment_merge.merge_fragment(model, built["fragment"]), built


@pytest.mark.parametrize("type_id,spec", [
    ("ccgt", {"pNom": 100}), ("cofiring_network", {"pNom": 100}), ("bess", {"pNom": 10}),
    ("p2x", {"pNom": 20, "offtakeMw": 5, "extendable": False}),
])
def test_build_year_and_lifetime_reach_every_child_row(type_id: str, spec: dict[str, Any]) -> None:
    m, built = _add(_model(), type_id, {**spec, "buildYear": 2031, "lifetime": 25})
    kids = _children(m, built["plantId"])
    assert len(kids) >= 1
    assert all(r["build_year"] == 2031 and r["lifetime"] == 25 for _, r in kids), [(s, r["name"]) for s, r in kids if r.get("build_year") != 2031]


def test_the_instance_sheet_row_is_visible_and_editing_it_moves_every_child() -> None:
    m, built = _add(_model(), "cofiring_network", {"pNom": 100, "bus": "KR-1", "buildYear": 2030})
    row = next(r for r in m[COMPOSITES_SHEET] if r["name"] == built["plantId"])
    assert row["type"] == "cofiring_network" and row["bus"] == "KR-1" and row["build_year"] == 2030 and row["p_nom"] == 100
    assert catalog.sync_composites(m)["change"] is None                          # untouched sheet: nothing to do
    row["build_year"] = 2040
    row["p_nom"] = 150
    out = catalog.sync_composites(m)
    assert out["plantIds"] == [built["plantId"]]
    merged = registry.apply_change(m, out["change"])
    kids = _children(merged, built["plantId"])
    assert kids and all(r["build_year"] == 2040 for _, r in kids)
    turbine = next(r for s, r in kids if s == "links" and r["name"] == built["plantId"])
    assert turbine["p_nom"] == pytest.approx(150 / turbine["efficiency"])
    assert catalog.sync_composites(merged)["change"] is None                     # the sheet row now matches again


def test_sheet_edit_of_a_port_rewires_the_children() -> None:
    m = _model()
    m["buses"].append({"name": "ng", "carrier": "gas"})
    m, built = _add(m, "ccgt", {"pNom": 100, "bus": "KR-1"})
    next(r for r in m[COMPOSITES_SHEET])["bus"] = "KR-2"
    merged = registry.apply_change(m, catalog.sync_composites(m)["change"])
    assert next(r for r in merged["links"] if r["name"] == built["plantId"])["bus1"] == "KR-2"


def test_a_bad_cell_is_refused_with_a_message() -> None:
    m, _ = _add(_model(), "ccgt", {"pNom": 100})
    m[COMPOSITES_SHEET][0]["p_nom"] = "lots"
    with pytest.raises(registry.PlantError, match="number"):
        catalog.sync_composites(m)


def test_placing_one_ccgt_on_three_buses_gives_three_independent_instances() -> None:
    m = _model()
    placed = catalog.place_plants("ccgt", {"pNom": 100, "buildYear": 2032}, ["KR-1", "KR-2", "KR-3"], m, prefix="ccgt")
    assert placed["plantIds"] == ["ccgt_KR_1", "ccgt_KR_2", "ccgt_KR_3"]
    merged = fragment_merge.merge_fragment(m, placed["fragment"])
    for bus in ("KR-1", "KR-2", "KR-3"):
        link = next(r for r in merged["links"] if r["name"] == f"ccgt_{bus.replace('-', '_')}")
        assert link["bus1"] == bus and link["build_year"] == 2032
        assert link["bus0"] == f"ccgt_{bus.replace('-', '_')}_bus_gas"              # per-instance fuel bus by default
    assert {r["name"] for r in merged[COMPOSITES_SHEET]} == set(placed["plantIds"])
    assert len({r["name"] for r in merged["links"]}) == 3
    # independent: edit one instance only
    row = next(r for r in merged[COMPOSITES_SHEET] if r["name"] == "ccgt_KR_2")
    row["build_year"] = 2045
    out = catalog.sync_composites(merged)
    assert out["plantIds"] == ["ccgt_KR_2"]
    after = registry.apply_change(merged, out["change"])
    assert {r["name"]: r["build_year"] for r in after["links"] if r["name"].startswith("ccgt_KR")} == {"ccgt_KR_1": 2032, "ccgt_KR_2": 2045, "ccgt_KR_3": 2032}


def test_placement_can_share_the_fuel_bus_and_refuses_bad_input() -> None:
    m = _model()
    placed = catalog.place_plants("ccgt", {"pNom": 50}, ["KR-1", "KR-2"], m, share_ports=True)
    merged = fragment_merge.merge_fragment(m, placed["fragment"])
    assert len({r["bus0"] for r in merged["links"]}) == 1 and len([b for b in merged["buses"] if b["carrier"] == "gas"]) == 1
    with pytest.raises(registry.PlantError):
        catalog.place_plants("ccgt", {"pNom": 50}, [], m)
    with pytest.raises(registry.PlantError):
        catalog.place_plants("ccgt", {"pNom": 50}, ["nope"], m)
    with pytest.raises(registry.PlantError):
        catalog.place_plants("ccgt", {"pNom": 50}, ["KR-1", "KR-1"], m)


def test_detach_keeps_the_rows_and_drops_the_owner_and_the_sheet_rows_and_delete_removes_the_sheet_row() -> None:
    m, built = _add(_model(), "ccgt", {"pNom": 100})
    pid = built["plantId"]
    det = registry.apply_change(m, catalog.detach_change(m, pid))
    assert not det.get(COMPOSITES_SHEET) and not det.get(registry.REGISTRY_SHEET)
    assert any(r["name"] == pid for r in det["links"]) and not _children(det, pid)
    gone = registry.apply_change(m, registry.delete_change(m, pid))
    assert not gone.get(COMPOSITES_SHEET) and not any(r["name"] == pid for r in gone["links"])


def test_an_older_workbook_gets_its_instance_rows_from_the_registry_without_touching_the_children() -> None:
    m, built = _add(_model(), "ccgt", {"pNom": 100, "bus": "KR-1"})
    legacy = {k: v for k, v in m.items() if k != COMPOSITES_SHEET}
    out = catalog.sync_composites(legacy)
    assert out["added"] == [built["plantId"]] and out["plantIds"] == []
    assert list(out["change"]["fragment"]["sheets"]) == [COMPOSITES_SHEET] and not out["change"]["remove"]
    healed = registry.apply_change(legacy, out["change"])
    assert healed["links"] == legacy["links"] and catalog.sync_composites(healed)["change"] is None


def test_template_path_save_an_instance_as_a_template_then_place_from_it() -> None:
    """What the UI does: the template row keeps the instance's type and spec (no plantId / bus), the Place form reads it back."""
    import json

    m, built = _add(_model(), "ccgt", {"pNom": 120, "bus": "KR-1", "buildYear": 2033, "lifetime": 30})
    spec = {k: v for k, v in registry.registry_map(m)[built["plantId"]]["spec"].items() if k not in ("plantId", "bus")}
    template_row = {"name": f"{built['plantId']}_template", "type": "ccgt", "spec": json.dumps(spec)}
    m = fragment_merge.merge_fragment(m, {"sheets": {catalog.TEMPLATES_SHEET: [template_row]}})
    row = m[catalog.TEMPLATES_SHEET][0]
    placed = catalog.place_plants(row["type"], json.loads(row["spec"]), ["KR-2", "KR-3"], m, prefix=row["name"].removesuffix("_template") + "_copy")
    assert placed["plantIds"] == ["ccgt_copy_KR_2", "ccgt_copy_KR_3"]
    merged = fragment_merge.merge_fragment(m, placed["fragment"])
    for pid, bus in zip(placed["plantIds"], ("KR-2", "KR-3")):
        link = next(r for r in merged["links"] if r["name"] == pid)
        assert link["bus1"] == bus and link["build_year"] == 2033 and link["lifetime"] == 30 and link["p_nom"] == pytest.approx(120 / link["efficiency"])
    sheet = {r["name"]: r for r in merged[catalog.COMPOSITES_SHEET]}
    assert sheet["ccgt_copy_KR_2"]["build_year"] == 2033 and sheet["ccgt_copy_KR_2"]["bus"] == "KR-2"


def test_p2x_plant_results_report_the_electrolyser_output_and_capacity_factor() -> None:
    """Output is the H2 the electrolyser makes, capacity factor its electricity input over size x hours; same CF as the P2X results."""
    from backend.app.p2x import results as p2x_results
    from backend.app.plants import results as plant_results
    from backend.pypsa.results import run_pypsa

    from ._p2x_fixtures import SCENARIO
    from ._plants_fixtures import stamps

    snaps = stamps(24)
    base: Model = {"buses": [{"name": "grid", "carrier": "AC"}], "carriers": [{"name": "AC"}, {"name": "gas", "co2_emissions": 0.2}],
                   "snapshots": [{"snapshot": s} for s in snaps],
                   "generators": [{"name": "gas", "bus": "grid", "carrier": "gas", "p_nom": 300, "marginal_cost": 40}]}
    model, _ = _add(base, "p2x", {"plantId": "p2x", "pNom": 10, "extendable": False, "offtakeMw": 5, "storage": "none", "discountRate": 0.05,
                                  "chain": {"electrolyser": {"applyAvailability": False}}})
    res = run_pypsa(model, SCENARIO, {})
    bundle = {"model": model, "result": res, "options": {}, "scenario": {"discountRate": 0.05}}
    plant = next(p for p in plant_results.plant_results(bundle)["plants"] if p["plantId"] == "p2x")
    chain = p2x_results.p2x_results(bundle)
    assert plant["generationMwh"] == pytest.approx(5 * 24, rel=1e-6)                       # 5 MW of H2 for 24 h
    assert plant["capacityMwEl"] == pytest.approx(10.0)
    assert plant["capacityFactor"] == pytest.approx(chain["electrolyser"]["capacityFactor"], rel=1e-6)
    assert plant["fullLoadHours"] == pytest.approx(chain["electrolyser"]["fullLoadHours"], rel=1e-6)
    assert plant["electricityInMwh"] > plant["generationMwh"]


def test_the_instance_sheet_always_has_the_full_column_set_in_a_fixed_order() -> None:
    m, _ = _add(_model(), "ccgt", {"pNom": 100})
    row = m[COMPOSITES_SHEET][0]
    assert list(row) == ["name", "type", "template", "bus", "gas_bus", "h2_bus", "product_bus", "designated_generators", "p_nom",
                         "p_nom_extendable", "p_nom_max", "build_year", "lifetime", "discount_rate", "plant"]
    assert row["build_year"] == "" and row["gas_bus"] == ""                      # blank cells the user can fill
    row["build_year"] = 2040                                                     # filling one is a normal sheet edit
    assert catalog.sync_composites(m)["plantIds"] == ["ccgt"]
