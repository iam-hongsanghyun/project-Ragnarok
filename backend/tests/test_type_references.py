"""End-to-end import tests for ``line_types`` and ``transformer_types``.

These two PyPSA components are type catalogues that ``lines`` /
``transformers`` reference by name to pull in pre-set electrical
parameters. They flow through the generic schema-driven import path
(``backend/pypsa/network/__init__.py``); these tests pin that the
round-trip actually works on real PyPSA versions — i.e. the type rows
are added to the catalogue *and* the referencing line carries the
type-derived attributes when the network is built.
"""
from __future__ import annotations

import pytest

from backend.pypsa.network import build_network


@pytest.fixture
def scenario() -> dict[str, object]:
    return {"discountRate": 0.05, "carbonPrice": 0.0}


def _two_buses() -> list[dict[str, object]]:
    return [
        {"name": "bus_a", "v_nom": 380.0},
        {"name": "bus_b", "v_nom": 380.0},
    ]


def _hourly_snapshots(n: int = 2) -> list[dict[str, object]]:
    import pandas as pd

    base = pd.Timestamp("2025-01-01 00:00")
    return [
        {"snapshot": (base + pd.Timedelta(hours=i)).isoformat()}
        for i in range(n)
    ]


def test_line_types_round_trip(scenario: dict[str, object]) -> None:
    """A ``line_types`` row plus a ``lines`` row that references it must end up
    in the built network with both pieces present and linked."""
    model = {
        "buses": _two_buses(),
        "snapshots": _hourly_snapshots(2),
        "line_types": [
            {
                "name": "ACSR-300",
                "r_per_length": 0.05,
                "x_per_length": 0.30,
                "c_per_length": 12.0,
                "i_nom": 1.0,
                "f_nom": 50.0,
            }
        ],
        "lines": [
            {
                "name": "L1",
                "bus0": "bus_a",
                "bus1": "bus_b",
                "type": "ACSR-300",
                "length": 100.0,
                "s_nom": 500.0,
            }
        ],
    }
    network, _ = build_network(model, scenario)

    assert "ACSR-300" in network.line_types.index, (
        "Expected line_types row to be imported through the generic loop"
    )
    assert "L1" in network.lines.index
    assert str(network.lines.at["L1", "type"]) == "ACSR-300"
    assert float(network.line_types.at["ACSR-300", "r_per_length"]) == pytest.approx(0.05)


def test_transformer_types_round_trip(scenario: dict[str, object]) -> None:
    """Same round-trip guarantee for ``transformer_types`` → ``transformers``."""
    model = {
        "buses": _two_buses(),
        "snapshots": _hourly_snapshots(2),
        "transformer_types": [
            {
                "name": "T-380-110",
                "s_nom": 600.0,
                "v_nom_0": 380.0,
                "v_nom_1": 110.0,
                "vsc": 12.0,
                "vscr": 0.5,
            }
        ],
        "transformers": [
            {
                "name": "TX1",
                "bus0": "bus_a",
                "bus1": "bus_b",
                "type": "T-380-110",
                "s_nom": 600.0,
            }
        ],
    }
    network, _ = build_network(model, scenario)

    assert "T-380-110" in network.transformer_types.index
    assert "TX1" in network.transformers.index
    assert str(network.transformers.at["TX1", "type"]) == "T-380-110"
    assert float(network.transformer_types.at["T-380-110", "s_nom"]) == pytest.approx(600.0)
