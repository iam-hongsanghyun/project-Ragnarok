"""Schema builder: PyPSA ``type`` cells -> storage class + piecewise flag.

PyPSA >= 1.3 writes ``static or piecewise or series`` for marginal_cost /
efficiency / rate. Mapping that to ``series`` stripped the static column at
build time and left a zero-cost LP (P1).
"""
from __future__ import annotations

import pytest

from backend.app.pypsa_schema_builder import (
    _is_piecewise,
    _normalize_storage,
    build_pypsa_schema,
)


@pytest.mark.parametrize(
    ("type_str", "storage", "piecewise"),
    [
        ("static or series", "static_or_series", False),
        ("static or piecewise or series", "static_or_series", True),
        ("series", "series", False),
        ("float", "static", False),
        ("string", "static", False),
        ("", "static", False),
    ],
)
def test_type_cell_classification(type_str: str, storage: str, piecewise: bool) -> None:
    assert _normalize_storage(type_str) == storage
    assert _is_piecewise(type_str) is piecewise


def test_installed_schema_marks_cost_and_efficiency_static_or_series() -> None:
    schema = build_pypsa_schema()["components"]
    gens = {a["attribute"]: a for a in schema["generators"]["attributes"]}
    assert gens["marginal_cost"]["storage"] == "static_or_series"
    assert "marginal_cost" in schema["generators"]["input_static_attributes"]
    assert "marginal_cost" in schema["generators"]["input_temporal_attributes"]
    assert gens["p_nom"]["storage"] == "static"
    assert gens["p_max_pu"]["storage"] == "static_or_series"
    assert not gens["p_max_pu"]["piecewise"]
    links = {a["attribute"]: a for a in schema["links"]["attributes"]}
    assert links["efficiency"]["storage"] == "static_or_series"
    # 'piecewise' only exists on PyPSA >= 1.3.
    import pypsa

    if tuple(int(x) for x in pypsa.__version__.split(".")[:2]) >= (1, 3):
        assert gens["marginal_cost"]["piecewise"] is True
