"""Every connection a composite asset offers ends up as the bus / generator names in the rows it creates."""
from __future__ import annotations

import json
from typing import Any

import pytest

from backend.app.plants import catalog
from backend.app.plants.registry import PlantError

from ._plants_fixtures import grid

Model = dict[str, list[dict[str, Any]]]


def _model() -> Model:
    m = grid()
    m["buses"] = [*m["buses"], {"name": "KR-1", "carrier": "AC"}, {"name": "ng", "carrier": "gas"}, {"name": "hyd", "carrier": "H2"},
                  {"name": "prod", "carrier": "NH3"}]
    m["carriers"] = [*m["carriers"], {"name": "gas"}, {"name": "H2"}, {"name": "NH3"}]
    m["generators"] = [{"name": "solar", "bus": "grid", "carrier": "solar", "p_nom": 50},
                       {"name": "wind", "bus": "KR-1", "carrier": "wind", "p_nom": 50},
                       {"name": "ng_src", "bus": "ng", "carrier": "gas", "p_nom": 900, "marginal_cost": 30}]
    return m


def _rows(built: dict[str, Any], sheet: str) -> list[dict[str, Any]]:
    return built["fragment"]["sheets"].get(sheet, [])


def test_types_mark_every_port_and_order_the_electricity_port() -> None:
    types = {t["id"]: t for t in catalog.list_types()}
    ports = {k: {f["key"]: f["port"] for f in t["fields"] if f.get("port")} for k, t in types.items()}
    assert ports["generator"] == {"bus": "electricity"} and ports["bess"] == {"bus": "electricity"}
    assert ports["ccgt"] == {"bus": "electricity", "gasBus": "gas"} and ports["ocgt"] == ports["ccgt"]
    assert ports["cofiring_network"] == {"bus": "electricity", "gasBus": "gas", "h2Bus": "h2"}
    assert ports["cofiring_simple"] == {"bus": "electricity"} and types["cofiring_simple"]["portNote"]
    assert ports["p2x"] == {"bus": "electricity", "h2Bus": "h2", "productBus": "product", "designatedGenerators": "generators"}
    assert all(f["advanced"] is False for t in types.values() for f in t["fields"] if f.get("port"))


def test_generator_and_bess_use_the_chosen_bus() -> None:
    m = _model()
    assert _rows(catalog.build_plant("generator", {"bus": "KR-1", "pNom": 10}, m), "generators")[0]["bus"] == "KR-1"
    assert _rows(catalog.build_plant("bess", {"bus": "KR-1", "pNom": 10}, m), "storage_units")[0]["bus"] == "KR-1"


@pytest.mark.parametrize("kind", ["ccgt", "ocgt"])
def test_turbine_reads_the_chosen_gas_bus_and_delivers_to_the_chosen_electricity_bus(kind: str) -> None:
    built = catalog.build_plant(kind, {"bus": "KR-1", "gasBus": "ng", "pNom": 100}, _model())
    link = _rows(built, "links")[0]
    assert (link["bus0"], link["bus1"]) == ("ng", "KR-1")
    assert not _rows(built, "buses")                       # the chosen gas bus was reused, none created


def test_blank_gas_bus_creates_one_and_says_so_in_the_rows() -> None:
    m = grid()
    built = catalog.build_plant("ccgt", {"pNom": 100}, m)
    assert [b["name"] for b in _rows(built, "buses")] == ["ccgt_bus_gas"]
    assert _rows(built, "links")[0]["bus0"] == "ccgt_bus_gas"


def test_cofiring_simple_has_only_the_electricity_port() -> None:
    gen = _rows(catalog.build_plant("cofiring_simple", {"bus": "KR-1", "pNom": 100}, _model()), "generators")[0]
    assert gen["bus"] == "KR-1"


def test_cofiring_network_wires_gas_and_h2_buses_through_a_fuel_bus() -> None:
    built = catalog.build_plant("cofiring_network", {"bus": "KR-1", "gasBus": "ng", "h2Bus": "hyd", "pNom": 100}, _model())
    pid = built["plantId"]
    by_name = {r["name"]: r for r in _rows(built, "links")}
    fuel = f"{pid}_bus_fuel"
    assert (by_name[f"{pid}_gas_feed"]["bus0"], by_name[f"{pid}_gas_feed"]["bus1"]) == ("ng", fuel)
    assert (by_name[f"{pid}_h2_feed"]["bus0"], by_name[f"{pid}_h2_feed"]["bus1"]) == ("hyd", fuel)
    assert (by_name[pid]["bus0"], by_name[pid]["bus1"]) == (fuel, "KR-1")


def test_p2x_ports_reach_the_rows() -> None:
    built = catalog.build_plant("p2x", {"bus": "KR-1", "h2Bus": "hyd", "designatedGenerators": ["solar", "wind"], "pNom": 20, "offtakeMw": 5,
                                        "extendable": False, "storage": "none"}, _model())
    ely = next(r for r in _rows(built, "links") if r["name"].endswith("electrolyser"))
    assert (ely["bus0"], ely["bus1"]) == ("KR-1", "hyd")
    assert [r["bus"] for r in _rows(built, "loads")] == ["hyd"]
    assert not _rows(built, "buses")
    chain = json.loads(_rows(built, "RAGNAROK_P2X")[0]["json"])
    assert chain["designatedGenerators"] == ["solar", "wind"]
    assert chain["buses"]["h2"] == "hyd" and chain["anchorBus"] == "KR-1"


def test_p2x_product_bus_is_used_for_a_derivative() -> None:
    built = catalog.build_plant("p2x", {"bus": "KR-1", "product": "NH3", "productBus": "prod", "pNom": 50, "offtakeMw": 5}, _model())
    synth = next(r for r in [*_rows(built, "processes"), *_rows(built, "links")] if "synth_NH3" in r["name"])
    assert "prod" in {synth.get(c) for c in ("bus0", "bus1", "bus2", "bus3")}
    assert "prod" not in {b["name"] for b in _rows(built, "buses")}
    assert next(r for r in _rows(built, "loads") if r["name"].endswith("load_NH3"))["bus"] == "prod"


def test_unknown_port_targets_are_refused() -> None:
    m = _model()
    with pytest.raises(PlantError):
        catalog.build_plant("p2x", {"designatedGenerators": ["nope"]}, m)
    with pytest.raises(PlantError):
        catalog.build_plant("p2x", {"h2Bus": "nope"}, m)
    with pytest.raises(PlantError):
        catalog.build_plant("p2x", {"product": "NH3", "productBus": "nope"}, m)
    with pytest.raises(PlantError):
        catalog.build_plant("ccgt", {"gasBus": "nope"}, m)
    with pytest.raises(PlantError):
        catalog.build_plant("generator", {"bus": "nope"}, m)


def test_build_reports_the_technology_keys_it_read() -> None:
    m = _model()
    assert catalog.build_plant("ccgt", {"pNom": 10}, m)["technologies"] == {"plants": ["ccgt", "fuels"], "p2x": []}
    assert catalog.build_plant("bess", {"pNom": 10}, m)["technologies"]["plants"] == ["bess"]
    assert catalog.build_plant("generator", {"pNom": 10}, m)["technologies"] == {"plants": [], "p2x": []}
    t = catalog.build_plant("p2x", {"pNom": 10}, m)["technologies"]
    assert t["plants"] == [] and "electrolyser_aec" in t["p2x"]


def test_bess_soc_loss_and_efficiency_are_plain_fields_written_to_the_row() -> None:
    row = _rows(catalog.build_plant("bess", {"pNom": 10, "maxHours": 4, "efficiency": 0.9, "standingLoss": 0.001, "cyclicSoc": False,
                                             "initialSoc": 0.5}, _model()), "storage_units")[0]
    assert row["cyclic_state_of_charge"] is False and row["standing_loss"] == 0.001
    assert row["efficiency_store"] == row["efficiency_dispatch"] == 0.9
    assert row["state_of_charge_initial"] == pytest.approx(0.5 * 4 * 10)
    default = _rows(catalog.build_plant("bess", {"pNom": 10}, _model()), "storage_units")[0]
    assert default["cyclic_state_of_charge"] is True and "standing_loss" not in default and "state_of_charge_initial" not in default
    with pytest.raises(PlantError):
        catalog.build_plant("bess", {"pNom": 10, "standingLoss": 1.5}, _model())
