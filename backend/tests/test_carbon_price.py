"""Carbon-price schedule pins."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.carbon_price import apply_carbon_price, parse_carbon_price_config
from backend.pypsa.results import run_pypsa


def _two_year_pathway() -> dict[str, list[dict[str, Any]]]:
    """Two pathway periods, one snapshot each, one gas generator."""
    return {
        "buses": [{"name": "b0", "v_nom": 380.0}],
        "snapshots": [
            {"snapshot": "2025-01-01T00:00:00", "period": 2025},
            {"snapshot": "2030-01-01T00:00:00", "period": 2030},
        ],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "generators": [
            {
                "name": "g",
                "bus": "b0",
                "carrier": "gas",
                "p_nom": 100.0,
                "marginal_cost": 20.0,
            }
        ],
        "loads": [{"name": "L", "bus": "b0", "p_set": 80.0}],
        "loads-p_set": [
            {"snapshot": "2025-01-01T00:00:00", "L": 80.0},
            {"snapshot": "2030-01-01T00:00:00", "L": 80.0},
        ],
    }


def _pathway_options() -> dict[str, Any]:
    return {
        "pathwayConfig": {
            "enabled": True,
            "periods": [
                {"period": 2025, "objectiveWeight": 1.0, "yearsWeight": 5.0},
                {"period": 2030, "objectiveWeight": 1.0, "yearsWeight": 5.0},
            ],
        }
    }


def _net(snapshots: list[str]) -> pypsa.Network:
    """Minimal single-bus network: one emitting (gas) + one clean (wind) gen."""
    n = pypsa.Network()
    n.set_snapshots(pd.DatetimeIndex(snapshots))
    n.add("Carrier", "gas", co2_emissions=0.4)   # tCO₂/MWh (output basis)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Bus", "b0")
    n.add("Generator", "g", bus="b0", carrier="gas", marginal_cost=20.0)
    n.add("Generator", "w", bus="b0", carrier="wind", marginal_cost=0.0)
    return n


def test_scalar_price_is_factor_times_price() -> None:
    """marginal_cost += price × co2_emissions; clean generator untouched."""
    n = _net(["2025-01-01"])
    apply_carbon_price(n, parse_carbon_price_config(50.0, None), [], "$")
    assert n.generators.at["g", "marginal_cost"] == pytest.approx(20.0 + 50.0 * 0.4)  # 40
    assert n.generators.at["w", "marginal_cost"] == pytest.approx(0.0)


def test_schedule_adder_is_per_snapshot() -> None:
    """A 2025→30 / 2030→120 schedule prices each snapshot by its year."""
    n = _net(["2025-01-01", "2030-01-01"])
    cfg = parse_carbon_price_config(0.0, [{"year": 2025, "price": 30.0}, {"year": 2030, "price": 120.0}])
    apply_carbon_price(n, cfg, [], "$")
    mc = n.generators_t.marginal_cost["g"]
    # base 20 + price × 0.4  →  [20+12, 20+48]
    assert list(mc.values) == pytest.approx([32.0, 68.0])


def test_varying_schedule_with_missing_static_cost_is_not_nan() -> None:
    """Regression: a blank static marginal_cost must coerce to 0, not NaN."""
    n = _net(["2025-01-01", "2030-01-01"])
    n.generators.loc["g", "marginal_cost"] = np.nan
    cfg = parse_carbon_price_config(0.0, [{"year": 2025, "price": 30.0}, {"year": 2030, "price": 120.0}])
    apply_carbon_price(n, cfg, [], "$")
    mc = n.generators_t.marginal_cost["g"]
    assert mc.notna().all()
    assert list(mc.values) == pytest.approx([12.0, 48.0])  # 0 + price × 0.4


def test_scalar_carbon_price_backwards_compatible() -> None:
    """A bare scalar still applies the adder to the static marginal cost."""
    options = _pathway_options()
    result = run_pypsa(
        _two_year_pathway(),
        {"discountRate": 0.05, "carbonPrice": 50.0},
        options,
    )
    note_text = " ".join(result["narrative"])
    assert "carbon price 50" in note_text.lower()


def test_carbon_price_schedule_varies_by_period() -> None:
    """Two-row schedule applies different prices to each pathway period."""
    options = {
        **_pathway_options(),
        "carbonPriceSchedule": [
            {"year": 2025, "price": 30.0},
            {"year": 2030, "price": 120.0},
        ],
    }
    result = run_pypsa(
        _two_year_pathway(),
        {"discountRate": 0.05, "carbonPrice": 0.0},
        options,
    )
    note_text = " ".join(result["narrative"])
    assert "schedule" in note_text.lower()
    assert "2025→30" in note_text
    assert "2030→120" in note_text


def test_schedule_lookup_uses_latest_year_below_snapshot() -> None:
    """A single-row schedule (2030→90) applied to a 2025+2030 pathway: both
    snapshots resolve to the 90 entry (the early one as the explicit fallback,
    the later one as the matching year). The narrative reports the price
    that was actually applied — single-value schedule collapses to scalar."""
    model = _two_year_pathway()
    options = {
        **_pathway_options(),
        "carbonPriceSchedule": [
            {"year": 2030, "price": 90.0},
        ],
    }
    result = run_pypsa(model, {"discountRate": 0.05}, options)
    note_text = " ".join(result["narrative"])
    assert "carbon price 90" in note_text.lower()


def test_empty_schedule_falls_back_to_scalar() -> None:
    """An empty schedule array behaves identically to no schedule field."""
    options = {
        **_pathway_options(),
        "carbonPriceSchedule": [],
    }
    result = run_pypsa(
        _two_year_pathway(),
        {"discountRate": 0.05, "carbonPrice": 50.0},
        options,
    )
    note_text = " ".join(result["narrative"])
    assert "carbon price 50" in note_text.lower()
    assert "schedule" not in note_text.lower()


def test_schedule_cost_split_backs_out_scheduled_price() -> None:
    """Regression: the fuel/carbon breakdown must back the adder out with the
    per-snapshot schedule actually applied to the solve — the scalar (0 here)
    used to zero the carbon line and lump the adder into fuel.

    Analytical: dispatch 80 MW both periods, ef 0.4, base mc 20.
    carbon = w·80·0.4·(30+120) = 4800·w ; fuel = w·80·20·2 = 3200·w → ratio 1.5.
    """
    options = {
        **_pathway_options(),
        "carbonPriceSchedule": [
            {"year": 2025, "price": 30.0},
            {"year": 2030, "price": 120.0},
        ],
    }
    result = run_pypsa(
        _two_year_pathway(),
        {"discountRate": 0.05, "carbonPrice": 0.0},
        options,
    )
    costs = {row["label"]: row["value"] for row in result["costBreakdown"]}
    assert costs["Carbon cost"] > 0
    assert costs["Carbon cost"] / costs["Fuel cost"] == pytest.approx(1.5, rel=1e-3)
