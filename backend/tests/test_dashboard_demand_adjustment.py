"""Demand adjustment (scale / add) rules of the dashboard-importer plugin.

Loads the plugin's dashboard_lib package directly (the same files the plugin
runs) and pins the three modes against hand-computed numbers:

* ``multiply`` — every member cell × factor.
* ``add_mw``   — group total +A MW at every snapshot, split across members by
                 their share of the group's annual energy.
* ``add_mwh``  — group annual energy +A MWh via one uniform factor.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

_PLUGIN = Path(__file__).resolve().parents[2] / "example_plugins" / "dashboard-importer"
_LIB = _PLUGIN / "dashboard_lib"
_PKG = "dashboard_lib_adjust_test"  # unique alias — don't collide with other tests


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
        "adjust": importlib.import_module(f"{_PKG}.demand_adjustment"),
    }


def _network() -> Any:
    """2 buses with time-series loads (annual shares 75% / 25%) + 1 static load.

    b1: flat 300 MW over 4 h → 1200 MWh; b2: flat 100 MW → 400 MWh;
    b3: static-only 50 MW (broadcast) → 200 MWh.
    """
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=4, freq="h"))
    for b in ("b1", "b2", "b3"):
        n.add("Bus", b)
    n.add("Load", "L1", bus="b1", p_set=0.0)
    n.add("Load", "L2", bus="b2", p_set=0.0)
    n.add("Load", "L3", bus="b3", p_set=50.0)  # static-only member
    n.loads_t.p_set["L1"] = 300.0
    n.loads_t.p_set["L2"] = 100.0
    n.buses["province"] = ["P1", "P1", "P2"]
    return n


def _dashboard(libs: dict[str, Any], rules: list[dict[str, Any]], *, enabled: bool = True) -> Any:
    s = libs["settings"].Settings(
        model="",
        base_year=2025,
        target_year=2030,
        target_load_twh=0,
        snapshot_start="01/01/2025 00:00",
        snapshot_length=4,
        demand_adjustment=enabled,
    )
    return libs["settings"].Dashboard(
        settings=s,
        cc_rules=None,
        cf_constraints=pd.DataFrame(),
        carbon_price_usd=0.0,
        emission_intensity=pd.Series(dtype=float),
        province_mapping=None,
        demand_adjust_rules=pd.DataFrame(rules) if rules else None,
    )


def _rule(resolution: str, value: str, mode: str, amount: float) -> dict[str, Any]:
    return {"resolution": resolution, "value": value, "mode": mode, "amount": amount}


def test_multiply_scales_only_selected_bus(libs) -> None:
    n = _network()
    libs["adjust"].adjust_demand(n, _dashboard(libs, [_rule("bus", "b1", "multiply", 1.1)]))
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 330.0, rtol=1e-12)
    np.testing.assert_allclose(n.loads_t.p_set["L2"], 100.0, rtol=1e-12)  # untouched
    assert float(n.loads.at["L3", "p_set"]) == pytest.approx(50.0)


def test_add_mw_splits_by_annual_share_across_region(libs) -> None:
    """+100 MW on province P1 (b1+b2): shares 1200/1600 and 400/1600 → +75/+25."""
    n = _network()
    libs["adjust"].adjust_demand(n, _dashboard(libs, [_rule("province", "P1", "add_mw", 100.0)]))
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 375.0, rtol=1e-12)
    np.testing.assert_allclose(n.loads_t.p_set["L2"], 125.0, rtol=1e-12)
    # Group total rises by exactly +100 MW at every snapshot.
    np.testing.assert_allclose(
        n.loads_t.p_set["L1"] + n.loads_t.p_set["L2"], 500.0, rtol=1e-12
    )
    assert float(n.loads.at["L3", "p_set"]) == pytest.approx(50.0)  # other region untouched


def test_add_mw_static_only_member(libs) -> None:
    """A static-only load (P2 = b3 alone) gets the full flat adder on p_set."""
    n = _network()
    libs["adjust"].adjust_demand(n, _dashboard(libs, [_rule("province", "P2", "add_mw", 20.0)]))
    assert float(n.loads.at["L3", "p_set"]) == pytest.approx(70.0)


def test_add_mwh_proportional_scale(libs) -> None:
    """+400 MWh on P1 (E=1600): f = 2000/1600 = 1.25 on every member cell."""
    n = _network()
    libs["adjust"].adjust_demand(n, _dashboard(libs, [_rule("province", "P1", "add_mwh", 400.0)]))
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 375.0, rtol=1e-12)
    np.testing.assert_allclose(n.loads_t.p_set["L2"], 125.0, rtol=1e-12)
    total = float((n.loads_t.p_set[["L1", "L2"]]).sum().sum())
    assert total == pytest.approx(2000.0)


def test_negative_amounts_decrease_demand(libs) -> None:
    n = _network()
    libs["adjust"].adjust_demand(n, _dashboard(libs, [_rule("bus", "b1", "add_mw", -50.0)]))
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 250.0, rtol=1e-12)

    n2 = _network()
    libs["adjust"].adjust_demand(n2, _dashboard(libs, [_rule("bus", "b2", "add_mwh", -200.0)]))
    np.testing.assert_allclose(n2.loads_t.p_set["L2"], 50.0, rtol=1e-12)  # ×0.5


def test_rules_apply_sequentially(libs) -> None:
    """×1.1 then +100 MW on the same bus compounds: (300×1.1)+100 = 430."""
    n = _network()
    libs["adjust"].adjust_demand(
        n,
        _dashboard(libs, [
            _rule("bus", "b1", "multiply", 1.1),
            _rule("bus", "b1", "add_mw", 100.0),
        ]),
    )
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 430.0, rtol=1e-12)


@pytest.mark.parametrize(
    "rule, match",
    [
        (_rule("bus", "b1", "multiply", 0.0), "factor must be > 0"),
        (_rule("bus", "b1", "multiply", -1.0), "factor must be > 0"),
        (_rule("bus", "b1", "shift", 1.0), "mode must be one of"),
        (_rule("bus", "b1", "add_mw", -400.0), "below zero"),
        (_rule("bus", "b1", "add_mwh", -2000.0), "exceeds"),
        (_rule("bus", "ghost", "multiply", 1.1), "not found"),
    ],
)
def test_invalid_rules_raise(libs, rule, match) -> None:
    n = _network()
    with pytest.raises(ValueError, match=match):
        libs["adjust"].adjust_demand(n, _dashboard(libs, [rule]))


def test_missing_amount_raises(libs) -> None:
    n = _network()
    rules = pd.DataFrame([{"resolution": "bus", "value": "b1", "mode": "multiply", "amount": None}])
    dash = _dashboard(libs, [])
    dash.demand_adjust_rules = rules
    with pytest.raises(ValueError, match="amount is required"):
        libs["adjust"].adjust_demand(n, dash)


def test_gate_off_and_empty_rules_are_noops(libs) -> None:
    n = _network()
    libs["adjust"].adjust_demand(n, _dashboard(libs, [_rule("bus", "b1", "multiply", 2.0)], enabled=False))
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 300.0, rtol=1e-12)

    libs["adjust"].adjust_demand(n, _dashboard(libs, []))  # enabled, no rules
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 300.0, rtol=1e-12)


def test_blank_rows_are_skipped(libs) -> None:
    n = _network()
    rules = [
        _rule("bus", "b1", "multiply", 1.5),
        {"resolution": "", "value": "", "mode": "", "amount": None},  # trailing empty
    ]
    libs["adjust"].adjust_demand(n, _dashboard(libs, rules))
    np.testing.assert_allclose(n.loads_t.p_set["L1"], 450.0, rtol=1e-12)
