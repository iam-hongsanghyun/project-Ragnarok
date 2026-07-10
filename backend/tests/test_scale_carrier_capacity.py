"""Unit tests for the scale-carrier-capacity transform (pure function)."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from backend.app.routers.transforms import scale_carrier_capacity


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "generators": [
            {"name": "W1", "carrier": "wind", "p_nom": 30.0},
            {"name": "W2", "carrier": "wind", "p_nom": 10.0},
            {"name": "G1", "carrier": "gas", "p_nom": 100.0},
        ],
    }


def _by_name(model: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    return {g["name"]: g for g in model["generators"]}


def test_proportional_cap_preserves_ratio_and_hits_target():
    m = _model()
    r = scale_carrier_capacity(m, carrier="wind", target_mw=100.0, method="proportional", mode="cap")
    g = _by_name(r["model"])
    assert r["before"] == pytest.approx(40.0)
    assert r["after"] == pytest.approx(100.0)
    # 30:10 → 75:25, written to p_nom_max, marked extendable.
    assert g["W1"]["p_nom_max"] == pytest.approx(75.0)
    assert g["W2"]["p_nom_max"] == pytest.approx(25.0)
    assert g["W1"]["p_nom_extendable"] is True and g["W2"]["p_nom_extendable"] is True
    # Other carriers are untouched.
    assert g["G1"]["p_nom"] == 100.0 and "p_nom_max" not in g["G1"]


def test_fix_mode_sets_p_nom_exactly():
    m = _model()
    r = scale_carrier_capacity(m, carrier="wind", target_mw=50.0, method="proportional", mode="fix")
    g = _by_name(r["model"])
    assert g["W1"]["p_nom"] == pytest.approx(37.5)
    assert g["W2"]["p_nom"] == pytest.approx(12.5)
    assert g["W1"]["p_nom_extendable"] is False
    assert g["W1"]["p_nom"] + g["W2"]["p_nom"] == pytest.approx(50.0)


def test_equal_method_splits_evenly():
    m = _model()
    r = scale_carrier_capacity(m, carrier="wind", target_mw=80.0, method="equal", mode="fix")
    g = _by_name(r["model"])
    assert g["W1"]["p_nom"] == pytest.approx(40.0)
    assert g["W2"]["p_nom"] == pytest.approx(40.0)


def test_zero_total_proportional_falls_back_to_equal():
    m = {"generators": [
        {"name": "W1", "carrier": "wind", "p_nom": 0.0},
        {"name": "W2", "carrier": "wind", "p_nom": 0.0},
    ]}
    r = scale_carrier_capacity(m, carrier="wind", target_mw=100.0, method="proportional", mode="fix")
    g = _by_name(r["model"])
    assert g["W1"]["p_nom"] == pytest.approx(50.0)
    assert g["W2"]["p_nom"] == pytest.approx(50.0)
    assert any("equally" in n for n in r["notes"])


def test_custom_shares_assigned():
    m = _model()
    r = scale_carrier_capacity(
        m, carrier="wind", target_mw=100.0, method="custom",
        mode="fix", shares={"W1": 60.0, "W2": 40.0},
    )
    g = _by_name(r["model"])
    assert g["W1"]["p_nom"] == pytest.approx(60.0)
    assert g["W2"]["p_nom"] == pytest.approx(40.0)


def test_custom_shares_must_sum_to_target():
    with pytest.raises(HTTPException):
        scale_carrier_capacity(
            _model(), carrier="wind", target_mw=100.0, method="custom",
            mode="fix", shares={"W1": 60.0, "W2": 30.0},  # sums to 90, not 100
        )


def test_custom_shares_reject_unknown_generator():
    with pytest.raises(HTTPException):
        scale_carrier_capacity(
            _model(), carrier="wind", target_mw=100.0, method="custom",
            mode="fix", shares={"W1": 100.0, "NOPE": 0.0},
        )


def test_unknown_carrier_raises():
    with pytest.raises(HTTPException):
        scale_carrier_capacity(_model(), carrier="coal", target_mw=50.0)


def test_bad_method_and_mode_raise():
    with pytest.raises(HTTPException):
        scale_carrier_capacity(_model(), carrier="wind", target_mw=10.0, method="nope")
    with pytest.raises(HTTPException):
        scale_carrier_capacity(_model(), carrier="wind", target_mw=10.0, mode="nope")
