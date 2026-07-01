"""Synthetic hourly demand importer (temperature-driven)."""
from __future__ import annotations

import pytest
from shapely.geometry import box

from backend.app.importers.databases.openmeteo_demand import build
from backend.app.importers.databases.openmeteo_demand.demand import demand_shape, scale_to_annual
from backend.app.importers.protocol import ConvertOptions, Database, FetchResult, Region


def test_demand_shape_responds_to_temperature() -> None:
    # comfort 18: 30°C (cooling) and 0°C (heating) exceed a mild 18°C day.
    shape = demand_shape([18.0, 30.0, 0.0], base_fraction=0.5, cool_coef=0.03, heat_coef=0.02, t_comfort=18.0)
    assert len(shape) == 3
    assert sum(shape) == pytest.approx(3.0)          # mean 1 (sum = n)
    assert shape[1] > shape[0] and shape[2] > shape[0]  # hot & cold above the comfort hour


def test_demand_shape_flat_when_all_comfort() -> None:
    assert demand_shape([18.0, 18.0, 18.0], t_comfort=18.0) == [1.0, 1.0, 1.0]


def test_scale_to_annual_uses_mean_power_basis() -> None:
    # a flat mean-1 shape over 8760 h scaled to 8760 MWh → 1 MW every hour
    pset = scale_to_annual([1.0] * 8760, 8760.0)
    assert pset[0] == pytest.approx(1.0)
    assert sum(pset) == pytest.approx(8760.0)


def _result() -> FetchResult:
    region = Region("USA", "United States", box(-120.0, 30.0, -100.0, 40.0))
    payload = {
        "lat": 35.0, "lon": -110.0,
        "time": ["2022-01-01 00:00", "2022-01-01 01:00", "2022-01-01 02:00"],
        "temp": [18.0, 30.0, 0.0],
    }
    filters = {"annual_demand_gwh": 10.0, "base_fraction": 0.5, "t_comfort": 18.0}
    return FetchResult("openmeteo_demand", region, filters, payload)


def test_to_sheets_builds_a_load_with_profile() -> None:
    frag = build().to_sheets(_result(), ConvertOptions())
    assert set(frag.sheets) == {"carriers", "buses", "loads", "loads-p_set"}
    assert [b["name"] for b in frag.sheets["buses"]] == ["load_USA"]
    assert [load["name"] for load in frag.sheets["loads"]] == ["demand_USA"]
    rows = frag.sheets["loads-p_set"]
    assert [r["snapshot"] for r in rows] == ["2022-01-01 00:00", "2022-01-01 01:00", "2022-01-01 02:00"]
    # hot & cold hours draw more than the comfort hour
    assert rows[1]["demand_USA"] > rows[0]["demand_USA"]
    assert rows[2]["demand_USA"] > rows[0]["demand_USA"]
    assert frag.provenance is not None


def test_module_conforms_and_keyless() -> None:
    db = build()
    assert isinstance(db, Database)
    assert db.meta.id == "openmeteo_demand" and not db.meta.requires_secrets
