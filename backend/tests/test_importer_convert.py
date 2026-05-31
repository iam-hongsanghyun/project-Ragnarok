"""Shared convert helpers — slug / dedupe / carriers / standard types."""
from __future__ import annotations

import pytest

from backend.app.importers.convert import (
    carrier_defaults_for,
    dedupe_name,
    default_line_type_for_voltage,
    line_params_for_voltage,
    load_carrier_defaults,
    map_fuel_to_carrier,
    merge_carriers_into_fragment,
    slugify_name,
)
from backend.app.importers.protocol import WorkbookFragment


def test_slugify_normalises_unicode_and_punctuation():
    assert slugify_name("Seoul HV / 220 kV", fallback="bus") == "Seoul_HV_220_kV"
    assert slugify_name("   ") == "asset"
    assert slugify_name(None, fallback="x") == "x"


def test_dedupe_name_assigns_suffix():
    taken: set[str] = set()
    assert dedupe_name("bus", taken) == "bus"
    assert dedupe_name("bus", taken) == "bus_2"
    assert dedupe_name("bus", taken) == "bus_3"
    assert dedupe_name("other", taken) == "other"


def test_carrier_defaults_for_known_and_unknown():
    coal = carrier_defaults_for("Coal")
    assert coal["co2_emissions"] > 0
    other = carrier_defaults_for("NonexistentCarrier")
    # Falls back to the "Other" entry, which is present in the catalogue.
    assert other["marginal_cost"] >= 0


def test_map_fuel_to_carrier_case_insensitive():
    mapping = {"Coal": "Coal", "Gas": "Gas", "Hydro": "Hydro"}
    assert map_fuel_to_carrier("coal", mapping=mapping) == "Coal"
    assert map_fuel_to_carrier("  HYDRO  ", mapping=mapping) == "Hydro"
    assert map_fuel_to_carrier("petrol", mapping=mapping) == "Other"
    assert map_fuel_to_carrier(None, mapping=mapping) == "Other"


def test_merge_carriers_into_fragment_dedupes_by_name():
    frag = WorkbookFragment(sheets={"carriers": [{"name": "Coal"}]})
    merge_carriers_into_fragment(
        frag,
        [
            {"name": "Coal", "co2_emissions": 0.34},
            {"name": "Wind", "co2_emissions": 0.0},
            {"name": "Wind", "co2_emissions": 0.0},
        ],
    )
    names = [r["name"] for r in frag.sheets["carriers"]]
    assert names == ["Coal", "Wind"]


def test_line_params_for_voltage_220kv_positive():
    params = line_params_for_voltage(220.0, length_km=100.0, num_parallel=1)
    assert params["r"] > 0
    assert params["x"] > params["r"]
    assert params["s_nom"] > 0


def test_default_line_type_falls_back_gracefully():
    # 999 kV is not in the catalogue; helper still returns None, callers fall back.
    assert default_line_type_for_voltage(999.0) is None


def test_carrier_defaults_loadable():
    defaults = load_carrier_defaults()
    assert "Coal" in defaults
    assert "Other" in defaults
