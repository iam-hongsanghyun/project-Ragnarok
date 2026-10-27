"""Store + Link storage and storage costs in merchant / finance / company / statement.

All four read storage through ``finance.storage_assets``, so they must agree:
the same capex rule (extendable only) and the same cost terms
(``marginal_cost``, ``marginal_cost_storage``, ``spill_cost``).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pypsa
import pytest

from backend.pypsa.results.company import build_company_breakdown
from backend.pypsa.results.company_statement import build_company_statement
from backend.pypsa.results.finance import _crf, build_company_finance
from backend.pypsa.results.merchant import build_merchant

logging.disable(logging.CRITICAL)
LOAD = [60, 200, 60, 200, 60, 200, 60, 200]


def _network(kind: str, **storage_kwargs: Any) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(range(8))
    n.add("Bus", "b")
    n.add("Carrier", ["gas", "peak", "battery"])
    n.add("Load", "L", bus="b", p_set=LOAD)
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=120, marginal_cost=20)
    n.add("Generator", "pk", bus="b", carrier="peak", p_nom=300, marginal_cost=150)
    if kind == "unit":
        n.add("StorageUnit", "st", bus="b", carrier="battery", cyclic_state_of_charge=True, **storage_kwargs)
    else:
        n.add("Bus", "bb")
        n.add("Store", "st", bus="bb", carrier="battery", e_cyclic=True, **storage_kwargs)
        n.add("Link", "chg", bus0="b", bus1="bb", p_nom=20, efficiency=0.95)
        n.add("Link", "dis", bus0="bb", bus1="b", p_nom=20, efficiency=0.95)
    n.optimize(solver_name="highs", include_objective_constant=False)
    return n


def _model(sheet: str) -> dict[str, list[dict[str, Any]]]:
    return {"generators": [], sheet: [{"name": "st", "owner": "Acme"}]}


def _flows(n: pypsa.Network) -> tuple[np.ndarray, np.ndarray]:
    price = n.buses_t.marginal_price["b"].to_numpy()
    if len(n.storage_units):
        net = (n.storage_units_t.p_dispatch["st"] - n.storage_units_t.p_store["st"]).to_numpy()
    else:
        net = (-n.links_t.p1["dis"] - n.links_t.p0["chg"]).to_numpy()
    return net, price


def test_store_with_links_counts_in_company_finance_and_statement() -> None:
    n = _network("store", e_nom=40)
    net, price = _flows(n)
    window_revenue = float((net * price).sum())
    assert window_revenue > 0  # the battery really arbitrages
    annualise = 8760 / 8
    stmt = build_company_statement(
        n, _model("stores"), owner_column="owner", currency="$", emissions_factors={}, carbon_price=0.0,
    )
    assert stmt is not None
    row = stmt["companies"][0]
    assert row["revenue"] == pytest.approx(window_revenue * annualise, rel=1e-6)
    fin = build_company_finance(n, _model("stores"), owner_column="owner", discount_rate=0.05, currency="$")
    assert fin is not None
    assert fin["companies"][0]["annualMargin"] == pytest.approx(row["grossMargin"], rel=1e-9)
    comp = build_company_breakdown(
        n, _model("stores"), owner_column="owner", currency="$", emissions_factors={},
    )
    assert comp is not None
    c = comp["companies"][0]
    assert c["storageCount"] == 1
    assert c["storageEnergyMWh"] == pytest.approx(40.0)
    assert c["capacityMW"] == pytest.approx(20 * 0.95)  # discharger delivers eff x p_nom
    assert c["revenue"] == pytest.approx(window_revenue, rel=1e-6)


def test_finance_and_statement_charge_storage_capex_by_one_rule() -> None:
    # Extendable: both charge capital_cost x p_nom_opt. Fixed size: neither does,
    # whatever capital_cost says (the solve never charged it).
    for extendable in (True, False):
        kwargs: dict[str, Any] = {"capital_cost": 3.0, "max_hours": 4.0}
        kwargs.update({"p_nom_extendable": True, "p_nom_max": 30.0} if extendable else {"p_nom": 25.0})
        n = _network("unit", **kwargs)
        stmt = build_company_statement(
            n, _model("storage_units"), owner_column="owner", currency="$", emissions_factors={},
            carbon_price=0.0,
        )
        fin = build_company_finance(
            n, _model("storage_units"), owner_column="owner", discount_rate=0.05, currency="$",
        )
        assert stmt is not None
        statement_capex = stmt["companies"][0]["capexAnnual"]
        finance_capex = fin["companies"][0]["overnightCapex"] * _crf(0.05, 25.0) if fin else 0.0
        if extendable:
            built = float(n.storage_units.at["st", "p_nom_opt"])
            assert built > 0
            assert statement_capex == pytest.approx(3.0 * built, rel=1e-9)
            assert finance_capex == pytest.approx(statement_capex, rel=1e-4)  # overnight is rounded to 0.01
        else:
            assert statement_capex == 0.0 and finance_capex == 0.0


def test_storage_holding_cost_enters_the_variable_cost() -> None:
    n = _network("unit", p_nom=25.0, max_hours=4.0, marginal_cost_storage=2.0)
    soc_hours = float(n.storage_units_t.state_of_charge["st"].sum())  # w = 1 h
    stmt = build_company_statement(
        n, _model("storage_units"), owner_column="owner", currency="$", emissions_factors={},
        carbon_price=0.0,
    )
    assert stmt is not None
    assert stmt["companies"][0]["fuelVomCost"] == pytest.approx(2.0 * soc_hours * 8760 / 8, rel=1e-9)


def test_merchant_keeps_the_owners_store() -> None:
    n = _network("store", e_nom=40)
    out = build_merchant(
        n, _model("stores"), owner="Acme", price_source="lmp", flat_price=0.0, price_series=None, currency="$",
    )
    assert out is not None
    row = next(a for a in out["assets"] if a["name"] == "st")
    assert row["type"] == "storage" and row["revenue"] > 0
    assert row["capacityMW"] == pytest.approx(19.0)
    # The price-taker re-solve cannot beat the system's own storage dispatch at these prices.
    net, price = _flows(n)
    assert row["revenue"] >= float((net * price).sum()) - 1e-6
