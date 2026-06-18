"""Generator-replacement eligibility (dashboard-importer).

Pins the "Include existing plants (whole fleet)" toggle: with it OFF the
replacement honours the build-year filter (only new builds are swapped); with
it ON the build-year filter is bypassed so the entire fleet of the selected
carriers is replaced (existing units included).

Loads the plugin's own dashboard_lib / pipeline modules directly — the same
files the plugin runs in the backend.
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
    return {n: _load(n) for n in ("settings", "generator_replacement")}


def _network() -> Any:
    """One bus with a mixed-vintage coal fleet: one old (pre-base), one new."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    n.add("Carrier", "coal")
    n.add("Generator", "coal_old", bus="b1", carrier="coal", p_nom=500.0, build_year=2010)
    n.add("Generator", "coal_new", bus="b1", carrier="coal", p_nom=300.0, build_year=2028)
    n.generators["province"] = ""
    return n


def _dashboard(
    libs: dict[str, Any],
    *,
    include_existing: bool,
    rules: pd.DataFrame | None = None,
    bulk: bool = True,
) -> Any:
    s = libs["settings"].Settings(
        model="", base_year=2025, target_year=2030, target_load_twh=0,
        snapshot_start="01/01/2030 00:00", snapshot_length=3,
        replace_generators=True, replace_build_year=2025,
        replace_include_existing=include_existing,
        replace_all_carriers=bulk, replace_carriers=("coal",),
        replace_solar_pct=60, replace_wind_pct=40,
    )
    return libs["settings"].Dashboard(
        settings=s, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0,
        generator_replacements=rules,
    )


def test_bulk_excludes_existing_by_default(libs: dict[str, Any]) -> None:
    """OFF: build_year < base year stays as-is; only the new build is replaced."""
    n = _network()
    replaced = libs["generator_replacement"].replace_generators(
        n, _dashboard(libs, include_existing=False)
    )
    # Only coal_new (300 MW) replaced; coal_old (500 MW, build 2010) untouched.
    assert replaced == {"b1": 300.0}
    assert "coal_old" in n.generators.index
    assert "coal_new" not in n.generators.index
    assert {"coal_new_solar_2028", "coal_new_wind_2028"} <= set(n.generators.index)


def test_bulk_includes_existing_when_on(libs: dict[str, Any]) -> None:
    """ON: the whole coal fleet is replaced regardless of build year."""
    n = _network()
    replaced = libs["generator_replacement"].replace_generators(
        n, _dashboard(libs, include_existing=True)
    )
    # Both plants replaced: 500 + 300 at the shared bus.
    assert replaced == {"b1": 800.0}
    assert "coal_old" not in n.generators.index and "coal_new" not in n.generators.index
    # The existing unit's renewables carry its own (old) build year.
    assert {"coal_old_solar_2010", "coal_old_wind_2010"} <= set(n.generators.index)
    # 60/40 split of the 500 MW existing plant.
    assert n.generators.at["coal_old_solar_2010", "p_nom"] == pytest.approx(300.0)
    assert n.generators.at["coal_old_wind_2010", "p_nom"] == pytest.approx(200.0)


def test_table_pick_of_existing_plant_raises_when_off(libs: dict[str, Any]) -> None:
    """An explicit pick of a pre-base-year plant is rejected unless include-existing is on."""
    rules = pd.DataFrame({"generator": ["coal_old"]})
    with pytest.raises(ValueError, match="before the replacement base year"):
        libs["generator_replacement"].replace_generators(
            _network(), _dashboard(libs, include_existing=False, rules=rules, bulk=False)
        )


def test_table_pick_of_existing_plant_allowed_when_on(libs: dict[str, Any]) -> None:
    """The same pick succeeds when include-existing is on."""
    rules = pd.DataFrame({"generator": ["coal_old"]})
    n = _network()
    replaced = libs["generator_replacement"].replace_generators(
        n, _dashboard(libs, include_existing=True, rules=rules, bulk=False)
    )
    assert replaced == {"b1": 500.0}
    assert "coal_old" not in n.generators.index
    assert "coal_new" in n.generators.index  # bulk off → the new plant is untouched


def test_config_flag_flows_into_settings() -> None:
    """The GUI flag maps through both Settings constructors in the pipeline."""
    pl = _load_pipeline()
    s = _load("settings")
    built = pl._settings_from_config(s, {"replace_include_existing": True})
    assert built.replace_include_existing is True
    # Overlay path (xlsx-derived settings + GUI overrides).
    base = s.Settings(
        model="", base_year=2025, target_year=2030, target_load_twh=0,
        snapshot_start="01/01/2030 00:00", snapshot_length=3,
    )
    assert base.replace_include_existing is False  # default
    pl._apply_config_to_settings(base, {"replace_include_existing": True})
    assert base.replace_include_existing is True
