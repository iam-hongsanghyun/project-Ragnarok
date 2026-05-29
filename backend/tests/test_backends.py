"""Pin the backend abstraction layer.

The seam must: default to PyPSA, resolve a backend by name, reject unknown
names, expose capabilities, and run an end-to-end case through the adapter
producing the same result contract as calling ``run_pypsa`` directly.
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.lib.backends import (
    DEFAULT_BACKEND,
    Backend,
    BackendError,
    available_backends,
    get_backend,
)


def _two_bus_model() -> dict[str, list[dict[str, Any]]]:
    """Minimal solvable single-period case."""
    return {
        "buses": [
            {"name": "A", "v_nom": 380.0},
            {"name": "B", "v_nom": 380.0},
        ],
        "snapshots": [
            {"snapshot": "2025-01-01T00:00:00"},
            {"snapshot": "2025-01-01T01:00:00"},
        ],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "generators": [
            {"name": "gA", "bus": "A", "carrier": "gas", "p_nom": 300.0, "marginal_cost": 20.0},
        ],
        "lines": [
            {"name": "L1", "bus0": "A", "bus1": "B", "x": 0.1, "s_nom": 300.0},
        ],
        "loads": [{"name": "LB", "bus": "B", "p_set": 100.0}],
        "loads-p_set": [
            {"snapshot": "2025-01-01T00:00:00", "LB": 100.0},
            {"snapshot": "2025-01-01T01:00:00", "LB": 100.0},
        ],
    }


def test_default_backend_is_pypsa() -> None:
    assert DEFAULT_BACKEND == "pypsa"
    assert get_backend().name == "pypsa"
    assert get_backend(None).name == "pypsa"
    assert get_backend("").name == "pypsa"


def test_get_backend_by_name_is_case_insensitive() -> None:
    assert get_backend("pypsa").name == "pypsa"
    assert get_backend("PyPSA").name == "pypsa"


def test_unknown_backend_raises() -> None:
    with pytest.raises(BackendError):
        get_backend("does-not-exist")


def test_pypsa_satisfies_backend_protocol() -> None:
    backend = get_backend("pypsa")
    assert isinstance(backend, Backend)


def test_capabilities_describe_pypsa() -> None:
    caps = {c["name"]: c for c in available_backends()}
    assert "pypsa" in caps
    pypsa = caps["pypsa"]
    assert pypsa["label"] == "PyPSA"
    assert "optimize" in pypsa["studyModes"]
    assert pypsa["features"]["pathway"] is True


def test_run_through_adapter_matches_run_pypsa_contract() -> None:
    """Running via the adapter produces the same result keys as run_pypsa."""
    from backend.lib.results import run_pypsa

    model = _two_bus_model()
    scenario: dict[str, Any] = {"discountRate": 0.05}

    adapter_result = get_backend("pypsa").run(model, scenario, {})
    direct_result = run_pypsa(_two_bus_model(), scenario, {})

    assert set(adapter_result.keys()) == set(direct_result.keys())
    # Core contract the frontend depends on.
    assert "outputs" in adapter_result
    assert "summary" in adapter_result
    assert adapter_result["outputs"].keys() == direct_result["outputs"].keys()
