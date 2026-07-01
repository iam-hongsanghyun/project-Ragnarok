"""Climate Watch policy importer (I8) — emissions → CO₂ cap global constraint."""
from __future__ import annotations

import asyncio
from typing import Any

from shapely.geometry import box

from backend.app.importers.context import ImportContext
from backend.app.importers.databases.climatewatch_policy import ClimateWatchPolicy, _pick_series
from backend.app.importers.protocol import ConvertOptions, Region


def _region() -> Region:
    return Region("GBR", "United Kingdom", box(-8.0, 50.0, 2.0, 59.0))


class _FakeHttp:
    def __init__(self, body: Any) -> None:
        self.body = body

    async def get_json(self, url: str, *, params=None, headers=None) -> Any:
        return self.body


_BODY = {"data": [
    {"sector": "Electricity/Heat", "gas": "CO2", "unit": "MtCO₂e", "emissions": [
        {"year": 2020, "value": 120.0}, {"year": 2021, "value": 110.0}, {"year": 2022, "value": 100.0},
    ]},
    {"sector": "Electricity/Heat", "gas": "All GHG", "unit": "MtCO₂e", "emissions": [
        {"year": 2022, "value": 105.0}]},
]}


def test_pick_series_prefers_co2() -> None:
    series, gas = _pick_series(_BODY["data"], "Electricity/Heat")
    assert gas == "CO2"
    assert series == {2020: 120.0, 2021: 110.0, 2022: 100.0}


def test_net_zero_cap_is_zero() -> None:
    db = ClimateWatchPolicy()
    ctx = ImportContext(secrets={}, http=_FakeHttp(_BODY))
    result = asyncio.run(db.fetch(_region(), {"sector": "electricity", "base_year": 2022, "target_year": 2050, "reduction_pct": 100}, ctx))
    frag = db.to_sheets(result, ConvertOptions())
    gc = frag.sheets["global_constraints"][0]
    assert gc["name"] == "co2_limit_2050"
    assert gc["type"] == "primary_energy" and gc["carrier_attribute"] == "co2_emissions" and gc["sense"] == "<="
    assert gc["constant"] == 0.0  # 100% reduction


def test_partial_cut_uses_baseline_year_in_tonnes() -> None:
    db = ClimateWatchPolicy()
    ctx = ImportContext(secrets={}, http=_FakeHttp(_BODY))
    result = asyncio.run(db.fetch(_region(), {"sector": "electricity", "base_year": 2022, "target_year": 2035, "reduction_pct": 60}, ctx))
    frag = db.to_sheets(result, ConvertOptions())
    gc = frag.sheets["global_constraints"][0]
    # 100 MtCO2 baseline × (1 - 0.6) = 40 MtCO2 = 40e6 tCO2.
    assert gc["constant"] == 40_000_000.0
    assert gc["name"] == "co2_limit_2035"


def test_nearest_baseline_year_when_exact_missing() -> None:
    db = ClimateWatchPolicy()
    ctx = ImportContext(secrets={}, http=_FakeHttp(_BODY))
    # base_year 2025 not present → nearest ≤ is 2022 (100 Mt).
    result = asyncio.run(db.fetch(_region(), {"sector": "electricity", "base_year": 2025, "target_year": 2050, "reduction_pct": 0}, ctx))
    cap = db._cap(result)
    assert cap["base_year_used"] == 2022 and cap["constant_t"] == 100_000_000.0
