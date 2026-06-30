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


def _follow_dashboard(
    libs: dict[str, Any],
    *,
    include_existing: bool,
    full_additions: dict | None,
    max_close_year: int = 0,
) -> Any:
    s = libs["settings"].Settings(
        model="", base_year=2025, target_year=2038, target_load_twh=0,
        snapshot_start="01/01/2038 00:00", snapshot_length=3,
        replace_generators=True, replace_build_year=2025,
        replace_include_existing=include_existing, replace_follow=True,
        replace_max_close_year=max_close_year,
        replace_all_carriers=True, replace_carriers=("coal",),
    )
    d = libs["settings"].Dashboard(
        settings=s, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0,
    )
    d.renewable_additions_by_year = full_additions
    return d


def test_existing_plant_close_year_capped_at_target(libs: dict[str, Any]) -> None:
    """Default cap: a far-future close year is clamped to the target year's mix."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2038-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    n.add("Carrier", "coal")
    n.add("Generator", "coal_old", bus="b1", carrier="coal", p_nom=1000.0, build_year=2010)
    n.generators["close_year"] = 2040  # after the target year (2038)
    n.generators["province"] = ""
    # close 2040 >= max (default = target 2038) → use the 2038 mix (600:200 = 75/25),
    # NOT the 2050 entry (which a naive close-year follow might pick up).
    dash = _follow_dashboard(
        libs, include_existing=True,
        full_additions={2038: (600.0, 200.0), 2050: (100.0, 900.0)},
    )
    libs["generator_replacement"].replace_generators(n, dash)
    assert n.generators.at["coal_old_solar_2010", "p_nom"] == pytest.approx(750.0)
    assert n.generators.at["coal_old_wind_2010", "p_nom"] == pytest.approx(250.0)


def test_existing_plant_uses_close_year_within_cap(libs: dict[str, Any]) -> None:
    """A raised cap lets the actual close year (below the cap) drive the split."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2038-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    n.add("Carrier", "coal")
    n.add("Generator", "coal_old", bus="b1", carrier="coal", p_nom=1000.0, build_year=2010)
    n.generators["close_year"] = 2042
    n.generators["province"] = ""
    # max_close_year 2045 > close 2042 → use the 2042 mix (600:200 = 75/25), NOT 2038.
    dash = _follow_dashboard(
        libs, include_existing=True, max_close_year=2045,
        full_additions={2038: (100.0, 900.0), 2042: (600.0, 200.0)},
    )
    libs["generator_replacement"].replace_generators(n, dash)
    assert n.generators.at["coal_old_solar_2010", "p_nom"] == pytest.approx(750.0)
    assert n.generators.at["coal_old_wind_2010", "p_nom"] == pytest.approx(250.0)


def test_default_follows_build_year_when_not_including_existing(libs: dict[str, Any]) -> None:
    """Include-existing OFF: split follows each plant's BUILD year, not close year."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2038-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    for c in ("coal", "solar", "wind"):
        n.add("Carrier", c)
    n.add("Generator", "coal_new", bus="b1", carrier="coal", p_nom=1000.0, build_year=2030)
    # Renewables added in 2030 (the build year): 200:600 solar:wind in the network.
    n.add("Generator", "solar30", bus="b1", carrier="solar", p_nom=200.0, build_year=2030)
    n.add("Generator", "wind30", bus="b1", carrier="wind", p_nom=600.0, build_year=2030)
    n.generators["close_year"] = 2045
    n.generators["province"] = ""
    # The close-year (2045) mix is 900:100 — must be ignored when include-existing is off.
    dash = _follow_dashboard(libs, include_existing=False, full_additions={2045: (900.0, 100.0)})
    libs["generator_replacement"].replace_generators(n, dash)
    # 25/75 of 1000 from the build-year (2030) mix, not 90/10 from the close year.
    assert n.generators.at["coal_new_solar_2030", "p_nom"] == pytest.approx(250.0)
    assert n.generators.at["coal_new_wind_2030", "p_nom"] == pytest.approx(750.0)


def test_include_existing_makes_all_plants_share_one_close_year_mix(libs: dict[str, Any]) -> None:
    """Regression (삼척#1/#2): with include-existing on, plants of different build
    years all follow the SAME capped close-year mix — the build year is irrelevant."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2038-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    n.add("Carrier", "coal")
    n.add("Generator", "samcheok1", bus="b1", carrier="coal", p_nom=1050.0, build_year=2024)
    n.add("Generator", "samcheok2", bus="b1", carrier="coal", p_nom=1050.0, build_year=2025)
    n.generators["close_year"] = [2040, 2041]  # both after the target year (2038)
    n.generators["province"] = ""
    # Default cap = target 2038 → both plants use the 2038 mix (300:100 = 75/25),
    # regardless of the 2024 vs 2025 build year that previously split them.
    dash = _follow_dashboard(libs, include_existing=True, full_additions={2038: (300.0, 100.0)})
    libs["generator_replacement"].replace_generators(n, dash)
    for solar in ("samcheok1_solar_2024", "samcheok2_solar_2025"):
        assert n.generators.at[solar, "p_nom"] == pytest.approx(787.5)
    for wind in ("samcheok1_wind_2024", "samcheok2_wind_2025"):
        assert n.generators.at[wind, "p_nom"] == pytest.approx(262.5)


def test_frozen_split_used_verbatim_and_bypasses_base_year(libs: dict[str, Any]) -> None:
    """A row with frozen solar_mw/wind_mw is replaced with exactly those MW, even
    when the plant is below the base year and include-existing is off."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2038-01-01", periods=3, freq="h"))
    n.add("Bus", "b1")
    n.add("Carrier", "coal")
    n.add("Generator", "coal_old", bus="b1", carrier="coal", p_nom=1000.0, build_year=2010)
    n.generators["province"] = ""
    s = libs["settings"].Settings(
        model="", base_year=2025, target_year=2038, target_load_twh=0,
        snapshot_start="01/01/2038 00:00", snapshot_length=3,
        replace_generators=True, replace_build_year=2025,
        replace_include_existing=False, replace_follow=True,  # would normally reject 2010
    )
    rules = pd.DataFrame([{"generator": "coal_old", "total_mw": 1000, "solar_mw": 700, "wind_mw": 300}])
    dash = libs["settings"].Dashboard(
        settings=s, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0,
        generator_replacements=rules,
    )
    replaced = libs["generator_replacement"].replace_generators(n, dash)
    assert replaced == {"b1": 1000.0}  # built despite being below the base year
    assert n.generators.at["coal_old_solar_2010", "p_nom"] == pytest.approx(700.0)
    assert n.generators.at["coal_old_wind_2010", "p_nom"] == pytest.approx(300.0)


def test_frozen_split_helper() -> None:
    """The pipeline's frozen-split parser accepts numeric/string, rejects blanks."""
    pl = _load_pipeline()
    assert pl._frozen_split({"generator": "x", "solar_mw": 700, "wind_mw": 300}) == (700.0, 300.0)
    assert pl._frozen_split({"generator": "x", "solar_mw": "700", "wind_mw": "300"}) == (700.0, 300.0)
    assert pl._frozen_split({"generator": "x"}) is None
    assert pl._frozen_split({"generator": "x", "solar_mw": "", "wind_mw": ""}) is None
    assert pl._frozen_split({"generator": "x", "solar_mw": None, "wind_mw": 5}) is None


def test_additions_helpers() -> None:
    """The pipeline's full-model additions + latest-nonzero fallback are correct."""
    pl = _load_pipeline()
    df = pd.DataFrame({
        "name": ["s1", "w1", "s2", "c1"],
        "carrier": ["solar", "wind", "Solar", "coal"],  # mixed case must still match
        "build_year": [2030, 2030, 2040, 2010],
        "p_nom": [100, 50, 300, 999],
    })
    adds = pl._additions_by_year(df)
    assert adds[2030] == (100.0, 50.0)
    assert adds[2040] == (300.0, 0.0)
    assert 2010 not in adds  # coal is not solar/wind
    # latest-nonzero walks back to the most recent earlier year with additions.
    assert pl._latest_nonzero(adds, 2045) == (300.0, 0.0)   # 2040 is the latest <= 2045
    assert pl._latest_nonzero(adds, 2035) == (100.0, 50.0)  # 2030 is the latest <= 2035
    assert pl._latest_nonzero(adds, 2000) == (0.0, 0.0)     # nothing <= 2000


def test_config_flag_flows_into_settings() -> None:
    """The GUI flag maps through both Settings constructors in the pipeline."""
    pl = _load_pipeline()
    s = _load("settings")
    built = pl._settings_from_config(
        s, {"replace_include_existing": True, "replace_max_close_year": 2045}
    )
    assert built.replace_include_existing is True
    assert built.replace_max_close_year == 2045
    # Overlay path (xlsx-derived settings + GUI overrides).
    base = s.Settings(
        model="", base_year=2025, target_year=2030, target_load_twh=0,
        snapshot_start="01/01/2030 00:00", snapshot_length=3,
    )
    assert base.replace_include_existing is False  # default
    assert base.replace_max_close_year == 0  # default → target year at use-time
    pl._apply_config_to_settings(
        base, {"replace_include_existing": True, "replace_max_close_year": 2045}
    )
    assert base.replace_include_existing is True
    assert base.replace_max_close_year == 2045
