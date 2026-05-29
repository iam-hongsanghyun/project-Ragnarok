"""Carbon-price schedule pins."""
from __future__ import annotations

from typing import Any

import pytest

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
