"""ESS placement rules (add storage at hand-picked buses/regions).

Loads the plugin's dashboard_lib package directly (the same files the plugin
runs) and pins :func:`ess.add_storage_at_selected_buses`: one StorageUnit per
bus of the selected group, fixed capacity at EVERY bus (0 allowed as an
editable placeholder), or extendable from 0 with the entered MW as each
unit's p_nom_max ceiling (0 = unbounded).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

_PLUGIN = Path(__file__).resolve().parents[2] / "example_plugins" / "dashboard-importer"
_LIB = _PLUGIN / "dashboard_lib"
_PKG = "dashboard_lib_ess_placement_test"  # unique alias — no cross-test collisions


@pytest.fixture(scope="module")
def libs() -> dict[str, Any]:
    """Load dashboard_lib as a real package so relative imports resolve."""
    spec = importlib.util.spec_from_file_location(
        _PKG, _LIB / "__init__.py", submodule_search_locations=[str(_LIB)]
    )
    assert spec and spec.loader
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[_PKG] = pkg
    spec.loader.exec_module(pkg)
    return {
        "settings": importlib.import_module(f"{_PKG}.settings"),
        "ess": importlib.import_module(f"{_PKG}.ess"),
    }


def _network() -> Any:
    """3 buses in 2 provinces, with loads so /demand-style groups resolve."""
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=3, freq="h"))
    for b in ("b1", "b2", "b3"):
        n.add("Bus", b)
    n.add("Load", "L1", bus="b1", p_set=100.0)
    n.add("Load", "L2", bus="b2", p_set=50.0)
    n.buses["province"] = ["P1", "P1", "P2"]
    return n


def _dashboard(
    libs: dict[str, Any],
    rules: list[dict[str, Any]] | None,
    *,
    enabled: bool = True,
    **overrides: Any,
) -> Any:
    s = libs["settings"].Settings(
        model="",
        base_year=2025,
        target_year=2030,
        target_load_twh=0,
        snapshot_start="01/01/2025 00:00",
        snapshot_length=3,
        ess_placement=enabled,
        **overrides,
    )
    return libs["settings"].Dashboard(
        settings=s,
        cc_rules=None,
        cf_constraints=pd.DataFrame(),
        carbon_price_usd=0.0,
        emission_intensity=pd.Series(dtype=float),
        province_mapping=None,
        ess_placement_rules=pd.DataFrame(rules) if rules else None,
    )


def _rule(resolution: str, value: str, mode: str, capacity: float | None) -> dict[str, Any]:
    return {"resolution": resolution, "value": value, "mode": mode, "capacity_mw": capacity}


def test_fixed_full_amount_at_every_bus_of_region(libs) -> None:
    """300 MW fixed on province P1 (b1+b2): EACH bus gets its own 300 MW unit."""
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n, _dashboard(libs, [_rule("province", "P1", "fixed", 300.0)])
    )
    su = n.storage_units
    assert set(su.index) == {"ESS_b1", "ESS_b2"}
    assert float(su.at["ESS_b1", "p_nom"]) == pytest.approx(300.0)
    assert float(su.at["ESS_b2", "p_nom"]) == pytest.approx(300.0)
    assert not su["p_nom_extendable"].any()
    assert (su["carrier"] == "ESS").all()
    assert float(su.at["ESS_b1", "max_hours"]) == pytest.approx(4.0)
    # Round-trip 0.9 split as sqrt per direction.
    assert float(su.at["ESS_b1", "efficiency_store"]) == pytest.approx(0.9 ** 0.5)


def test_fixed_zero_capacity_creates_placeholder_units(libs) -> None:
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n, _dashboard(libs, [_rule("bus", "b3", "fixed", 0.0)])
    )
    assert "ESS_b3" in n.storage_units.index
    assert float(n.storage_units.at["ESS_b3", "p_nom"]) == pytest.approx(0.0)
    assert not bool(n.storage_units.at["ESS_b3", "p_nom_extendable"])


def test_extendable_starts_at_zero_with_capacity_as_ceiling(libs) -> None:
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n, _dashboard(libs, [_rule("province", "P1", "extendable", 500.0)],
                      ess_capital_cost=120_000.0)
    )
    su = n.storage_units
    for name in ("ESS_b1", "ESS_b2"):
        assert float(su.at[name, "p_nom"]) == pytest.approx(0.0)
        assert bool(su.at[name, "p_nom_extendable"])
        assert float(su.at[name, "p_nom_max"]) == pytest.approx(500.0)  # per unit
        assert float(su.at[name, "capital_cost"]) == pytest.approx(120_000.0)


def test_extendable_zero_capacity_is_unbounded(libs) -> None:
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n, _dashboard(libs, [_rule("bus", "b1", "extendable", 0.0)])
    )
    su = n.storage_units
    assert bool(su.at["ESS_b1", "p_nom_extendable"])
    assert float(su.at["ESS_b1", "p_nom_max"]) == float("inf")  # PyPSA default


def test_name_collision_gets_suffixed(libs) -> None:
    """Two rules hitting the same bus produce ESS_b1 and ESS_b1_2."""
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n,
        _dashboard(libs, [
            _rule("bus", "b1", "fixed", 100.0),
            _rule("bus", "b1", "extendable", 0.0),
        ]),
    )
    assert {"ESS_b1", "ESS_b1_2"} <= set(n.storage_units.index)
    assert not bool(n.storage_units.at["ESS_b1", "p_nom_extendable"])
    assert bool(n.storage_units.at["ESS_b1_2", "p_nom_extendable"])


def test_missing_capacity_defaults_to_zero(libs) -> None:
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n, _dashboard(libs, [_rule("bus", "b1", "fixed", None)])
    )
    assert float(n.storage_units.at["ESS_b1", "p_nom"]) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "rule, match",
    [
        (_rule("bus", "b1", "expansion", 10.0), "mode must be one of"),
        (_rule("bus", "b1", "fixed", -5.0), "must be >= 0"),
        (_rule("bus", "ghost", "fixed", 10.0), "not found"),
        (_rule("", "b1", "fixed", 10.0), "resolution and value are required"),
    ],
)
def test_invalid_rules_raise(libs, rule, match) -> None:
    n = _network()
    with pytest.raises(ValueError, match=match):
        libs["ess"].add_storage_at_selected_buses(n, _dashboard(libs, [rule]))


def test_gate_off_and_empty_rules_are_noops(libs) -> None:
    n = _network()
    libs["ess"].add_storage_at_selected_buses(
        n, _dashboard(libs, [_rule("bus", "b1", "fixed", 100.0)], enabled=False)
    )
    assert n.storage_units.empty

    libs["ess"].add_storage_at_selected_buses(n, _dashboard(libs, None))  # on, no rules
    assert n.storage_units.empty


def test_blank_rows_are_skipped(libs) -> None:
    n = _network()
    rules = [
        _rule("bus", "b1", "fixed", 100.0),
        {"resolution": "", "value": "", "mode": "", "capacity_mw": None},  # trailing empty
    ]
    libs["ess"].add_storage_at_selected_buses(n, _dashboard(libs, rules))
    assert list(n.storage_units.index) == ["ESS_b1"]
