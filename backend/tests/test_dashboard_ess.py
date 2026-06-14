"""ESS (energy storage) added at generator-replacement buses (dashboard-importer).

Loads the plugin's dashboard_lib modules directly (the same files the plugin
runs) and pins: replace_generators reports the replaced capacity per bus, and
ess.add_storage_at_replaced_buses sizes + configures the StorageUnits from it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

_PLUGIN = Path(__file__).resolve().parents[2] / "example_plugins" / "dashboard-importer"
_LIB = _PLUGIN / "dashboard_lib"


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"dashboard_lib.{name}", _LIB / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass needs the module registered
    spec.loader.exec_module(module)
    return module


def _load_pipeline() -> Any:
    spec = importlib.util.spec_from_file_location("dashboard_pipeline_under_test", _PLUGIN / "pipeline.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def libs() -> dict[str, Any]:
    return {n: _load(n) for n in ("settings", "generator_replacement", "ess")}


def _network() -> Any:
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    n.add("Bus", "b2")
    n.add("Carrier", "coal")
    n.add("Generator", "coalA", bus="b1", carrier="coal", p_nom=400.0, build_year=2030)
    n.add("Generator", "coalB", bus="b1", carrier="coal", p_nom=200.0, build_year=2030)
    n.add("Generator", "coalC", bus="b2", carrier="coal", p_nom=300.0, build_year=2030)
    n.generators["province"] = ""
    return n


def _dashboard(libs: dict[str, Any], **ess_kwargs: Any) -> Any:
    s = libs["settings"].Settings(
        model="", base_year=2025, target_year=2030, target_load_twh=0,
        snapshot_start="01/01/2025 00:00", snapshot_length=3,
        replace_generators=True, replace_all_carriers=True, replace_carriers=("coal",),
        replace_solar_pct=60, replace_wind_pct=40, **ess_kwargs,
    )
    return libs["settings"].Dashboard(
        settings=s, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0,
    )


def test_replace_generators_reports_capacity_per_bus(libs: dict[str, Any]) -> None:
    n = _network()
    replaced = libs["generator_replacement"].replace_generators(n, _dashboard(libs))
    # b1 had 400 + 200 replaced, b2 had 300.
    assert replaced == {"b1": 600.0, "b2": 300.0}


def test_ess_proportional_with_expansion(libs: dict[str, Any]) -> None:
    n = _network()
    dash = _dashboard(
        libs, add_ess=True, ess_carrier="MyBattery", ess_hours=4, ess_efficiency=0.81,
        ess_sizing_mode="proportional", ess_proportion_pct=30, ess_capital_cost=12345,
        ess_expandable=True, ess_expansion_mode="fixed", ess_p_nom_min=10, ess_p_nom_max=500,
    )
    replaced = libs["generator_replacement"].replace_generators(n, dash)
    libs["ess"].add_storage_at_replaced_buses(n, dash, replaced)

    assert "MyBattery" in n.carriers.index  # carrier auto-added
    su = n.storage_units
    assert set(su.index) == {"ESS_b1", "ESS_b2"}
    # 30% of the replaced capacity at each bus.
    assert su.at["ESS_b1", "p_nom"] == pytest.approx(180.0)
    assert su.at["ESS_b2", "p_nom"] == pytest.approx(90.0)
    # Round-trip 0.81 → √ = 0.9 each way.
    assert su.at["ESS_b1", "efficiency_store"] == pytest.approx(0.9)
    assert su.at["ESS_b1", "efficiency_dispatch"] == pytest.approx(0.9)
    assert su.at["ESS_b1", "max_hours"] == pytest.approx(4.0)
    assert bool(su.at["ESS_b1", "p_nom_extendable"]) is True
    assert su.at["ESS_b1", "p_nom_min"] == pytest.approx(10.0)
    assert su.at["ESS_b1", "p_nom_max"] == pytest.approx(500.0)
    assert su.at["ESS_b1", "carrier"] == "MyBattery"
    # A finite lifetime is set so the backend can annuitise capital_cost
    # (PyPSA's default +inf has no annuity → would zero the CAPEX).
    assert su.at["ESS_b1", "lifetime"] == pytest.approx(15.0)


def test_ess_proportional_expansion_bounds(libs: dict[str, Any]) -> None:
    """Expansion min/max can be a % of the bus's (summed) replaced capacity."""
    n = _network()
    dash = _dashboard(
        libs, add_ess=True, ess_sizing_mode="proportional", ess_proportion_pct=30,
        ess_expandable=True, ess_expansion_mode="proportional",
        ess_p_nom_min=10, ess_p_nom_max=200,
    )
    replaced = libs["generator_replacement"].replace_generators(n, dash)  # b1=600, b2=300
    libs["ess"].add_storage_at_replaced_buses(n, dash, replaced)

    su = n.storage_units
    # b1: 10%..200% of 600 → [60, 1200]; b2: of 300 → [30, 600].
    assert su.at["ESS_b1", "p_nom_min"] == pytest.approx(60.0)
    assert su.at["ESS_b1", "p_nom_max"] == pytest.approx(1200.0)
    assert su.at["ESS_b2", "p_nom_min"] == pytest.approx(30.0)
    assert su.at["ESS_b2", "p_nom_max"] == pytest.approx(600.0)


def test_ess_fixed_expansion_bounds_are_mw(libs: dict[str, Any]) -> None:
    """In fixed mode the min/max are MW, identical on every bus."""
    n = _network()
    dash = _dashboard(
        libs, add_ess=True, ess_sizing_mode="fixed", ess_fixed_mw=100,
        ess_expandable=True, ess_expansion_mode="fixed", ess_p_nom_min=50, ess_p_nom_max=300,
    )
    replaced = libs["generator_replacement"].replace_generators(n, dash)
    libs["ess"].add_storage_at_replaced_buses(n, dash, replaced)
    su = n.storage_units
    assert su.at["ESS_b1", "p_nom_min"] == pytest.approx(50.0)
    assert su.at["ESS_b1", "p_nom_max"] == pytest.approx(300.0)
    assert su.at["ESS_b2", "p_nom_max"] == pytest.approx(300.0)


def test_ess_fixed_mw_no_expansion(libs: dict[str, Any]) -> None:
    n = _network()
    dash = _dashboard(
        libs, add_ess=True, ess_carrier="ESS", ess_hours=2, ess_efficiency=1.0,
        ess_sizing_mode="fixed", ess_fixed_mw=100, ess_expandable=False,
    )
    replaced = libs["generator_replacement"].replace_generators(n, dash)
    libs["ess"].add_storage_at_replaced_buses(n, dash, replaced)

    su = n.storage_units
    assert set(su.index) == {"ESS_b1", "ESS_b2"}
    # Flat 100 MW per bus regardless of replaced capacity.
    assert su.at["ESS_b1", "p_nom"] == pytest.approx(100.0)
    assert su.at["ESS_b2", "p_nom"] == pytest.approx(100.0)
    assert bool(su.at["ESS_b1", "p_nom_extendable"]) is False


def test_ess_off_adds_nothing(libs: dict[str, Any]) -> None:
    n = _network()
    dash = _dashboard(libs, add_ess=False)
    replaced = libs["generator_replacement"].replace_generators(n, dash)
    libs["ess"].add_storage_at_replaced_buses(n, dash, replaced)
    assert len(n.storage_units) == 0


def test_config_float_zero_is_not_reverted_to_default() -> None:
    """Regression: a user-entered 0 must survive the GUI-config → Settings map.

    The old ``str(cfg.get(k, '') or '')`` collapsed a numeric ``0`` to '' (0 is
    falsy), so 0 MW silently became the field default (100 MW). Cover both the
    numeric (JSON-number) and string forms, and confirm blank still defaults.
    """
    pl = _load_pipeline()
    # numeric 0 (what the GUI number input actually sends) → 0, not the default.
    assert pl._as_float({"ess_fixed_mw": 0}, "ess_fixed_mw", 100.0) == 0.0
    assert pl._as_float({"ess_fixed_mw": 0.0}, "ess_fixed_mw", 100.0) == 0.0
    assert pl._as_float({"ess_fixed_mw": "0"}, "ess_fixed_mw", 100.0) == 0.0
    # genuinely absent / blank still falls back to the default.
    assert pl._as_float({}, "ess_fixed_mw", 100.0) == 100.0
    assert pl._as_float({"ess_fixed_mw": ""}, "ess_fixed_mw", 100.0) == 100.0
    assert pl._as_float({"ess_fixed_mw": "  "}, "ess_fixed_mw", 100.0) == 100.0

    class _S:
        ess_fixed_mw = 100.0

    s = _S()
    pl._override_float(s, {"ess_fixed_mw": 0}, "ess_fixed_mw")
    assert s.ess_fixed_mw == 0.0  # 0 overrides; was kept at 100 by the bug
    s2 = _S()
    pl._override_float(s2, {"ess_fixed_mw": ""}, "ess_fixed_mw")
    assert s2.ess_fixed_mw == 100.0  # blank leaves the prior value untouched


def test_config_zero_fixed_mw_yields_no_storage_end_to_end(libs: dict[str, Any]) -> None:
    """0 MW fixed, expansion off → built model has no ESS (not a 100 MW unit)."""
    pl = _load_pipeline()
    cfg = {
        "add_ess": True,
        "ess_sizing_mode": "fixed",
        "ess_fixed_mw": 0,  # the user's exact input
        "ess_expandable": False,
        "replace_generators": True,
        "replace_all_carriers": True,
        "replace_carriers": "coal",
        "replace_solar_pct": 60,
        "replace_wind_pct": 40,
    }
    settings = pl._settings_from_config(libs["settings"], cfg)
    assert settings.ess_fixed_mw == 0.0
    dash = libs["settings"].Dashboard(
        settings=settings, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0,
    )
    n = _network()
    replaced = libs["generator_replacement"].replace_generators(n, dash)
    libs["ess"].add_storage_at_replaced_buses(n, dash, replaced)
    assert len(n.storage_units) == 0
