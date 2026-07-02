"""I5 fuel-price importer — unit conversions to €/MWh thermal.

The conversions are the whole point (users hand-type €/MWh from $/MMBtu etc.),
so pin them against the documented energy contents.
"""
from __future__ import annotations

import pytest

from backend.app.importers.databases.fuel_prices import MMBTU_PER_MWH, convert_fuel_prices
from backend.app.importers.registry import registered_databases


def test_gas_mmbtu_to_mwh_thermal() -> None:
    rows = convert_fuel_prices({"gas_price": 10.0})
    gas = next(r for r in rows if r["name"] == "gas")
    assert gas["marginal_cost"] == pytest.approx(10.0 * MMBTU_PER_MWH, abs=1e-3)  # ≈ 34.12
    assert gas["raw_unit"] == "$/MMBtu"


def test_coal_oil_biomass_divide_by_energy_content() -> None:
    rows = {r["name"]: r for r in convert_fuel_prices(
        {"coal_price": 120.0, "oil_price": 85.0, "biomass_price": 150.0})}
    assert rows["coal"]["marginal_cost"] == pytest.approx(120.0 / 6.978, abs=1e-2)
    assert rows["oil"]["marginal_cost"] == pytest.approx(85.0 / 1.699, abs=1e-2)
    assert rows["biomass"]["marginal_cost"] == pytest.approx(150.0 / 4.900, abs=1e-2)


def test_uranium_passes_through_as_thermal() -> None:
    rows = convert_fuel_prices({"uranium_cost": 6.0})
    assert next(r for r in rows if r["name"] == "nuclear")["marginal_cost"] == pytest.approx(6.0)


def test_zero_or_missing_fuels_are_skipped() -> None:
    rows = convert_fuel_prices({"gas_price": 0.0, "coal_price": 100.0})
    names = {r["name"] for r in rows}
    assert names == {"coal"}  # gas at 0 dropped, others absent


def test_registered_and_global() -> None:
    dbs = registered_databases()
    assert "fuel_prices" in dbs
    assert dbs["fuel_prices"].meta.targets == ["carriers"]
