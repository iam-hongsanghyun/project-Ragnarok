"""Regression tests pinning the backend workbook → ``pypsa.Network`` import contract.

The contract has exactly three rules:

1. ``network`` sheet — only fields whitelisted by
   :func:`backend.pypsa.pypsa_schema.network_runtime_import_fields` are applied
   (name, srid, crs, now). Unknown columns must be ignored.
2. ``snapshots`` sheet — bypasses the generic component loop and builds the
   snapshot index. In single-period runs the index is a flat ``DatetimeIndex``;
   under pathway planning it is a ``MultiIndex`` of (period, timestep).
3. Every other schema-defined sheet — buses, generators, processes, line_types,
   global_constraints, shunt_impedances, … — flows through the generic loop in
   :func:`backend.pypsa.network.build_network` via
   ``_ordered_component_sheets`` → ``input_static_attributes`` → ``network.add()``.
   Time-series sheets follow the ``<list_name>-<attr>`` naming convention and
   are wired up through ``_apply_ts_sheet``.

These tests freeze that contract so future refactors can't silently
re-introduce per-sheet branches or break the two real special cases.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from backend.pypsa.network import build_network


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def scenario() -> dict[str, Any]:
    """Minimal scenario dict accepted by ``build_network``."""
    return {"discountRate": 0.05, "carbonPrice": 0.0}


def _two_bus_buses() -> list[dict[str, Any]]:
    return [
        {"name": "bus_a", "v_nom": 380.0},
        {"name": "bus_b", "v_nom": 380.0},
    ]


def _hourly_snapshots(n: int = 3) -> list[dict[str, Any]]:
    base = pd.Timestamp("2025-01-01 00:00")
    return [
        {"snapshot": (base + pd.Timedelta(hours=i)).isoformat()}
        for i in range(n)
    ]


# ── Rule 1: `network` sheet → runtime import allow-list ─────────────────────

def test_network_sheet_unknown_column_ignored(scenario: dict[str, Any]) -> None:
    """Unknown columns in the `network` sheet must NOT become network attributes.

    The runtime import policy is an allow-list; new schema fields should never
    leak into the live network until they are explicitly enabled in
    ``network_import_policy.json``.
    """
    model = {
        "network": [
            {
                "name": "test-net",
                "totally_unknown_attr": "should_be_ignored",
                "investment_periods": "should_also_be_ignored",
            }
        ],
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(3),
    }
    network, _ = build_network(model, scenario)

    assert network.name == "test-net"
    assert not hasattr(network, "totally_unknown_attr")
    # `investment_periods` is in the policy but disabled — must not be applied
    # via the network-sheet path.
    assert len(network.investment_periods) == 0


def test_network_sheet_known_fields_applied(scenario: dict[str, Any]) -> None:
    """name / srid / now from the `network` sheet must propagate to the network."""
    model = {
        "network": [
            {
                "name": "iso-net",
                "srid": 4326,
                "now": "2025-06-01 12:00",
            }
        ],
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(2),
    }
    network, _ = build_network(model, scenario)

    assert network.name == "iso-net"
    assert network.crs.to_epsg() == 4326
    # `now` is preserved as-is on the network object.
    assert str(network.now) == "2025-06-01 12:00"


# ── Rule 2: `snapshots` sheet → index special case ──────────────────────────

def test_snapshots_single_period_builds_flat_datetime_index(
    scenario: dict[str, Any],
) -> None:
    """Single-period runs produce a flat (non-MultiIndex) datetime index."""
    model = {
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(4),
    }
    network, _ = build_network(model, scenario)

    assert not isinstance(network.snapshots, pd.MultiIndex)
    assert len(network.snapshots) == 4
    # ISO strings parse to DatetimeIndex.
    assert pd.api.types.is_datetime64_any_dtype(network.snapshots)


def test_snapshots_pathway_builds_multi_period_index(
    scenario: dict[str, Any],
) -> None:
    """Pathway mode stacks an investment-period level onto the snapshot index."""
    model = {
        "buses": _two_bus_buses(),
        "snapshots": [
            {"snapshot": "2025-01-01 00:00", "period": 2025},
            {"snapshot": "2025-01-01 01:00", "period": 2025},
            {"snapshot": "2025-01-01 00:00", "period": 2030},
            {"snapshot": "2025-01-01 01:00", "period": 2030},
        ],
    }
    options = {
        "pathwayConfig": {
            "enabled": True,
            "periods": [
                {"period": 2025, "objectiveWeight": 1.0, "yearsWeight": 5.0},
                {"period": 2030, "objectiveWeight": 1.0, "yearsWeight": 5.0},
            ],
        }
    }
    network, _ = build_network(model, scenario, options)

    assert isinstance(network.snapshots, pd.MultiIndex)
    assert network.snapshots.names == ["period", "timestep"]
    assert set(network.snapshots.get_level_values("period").unique()) == {2025, 2030}
    assert list(network.investment_periods) == [2025, 2030]


# ── Rule 3: every other sheet → generic schema-driven loop ──────────────────

def test_generic_loop_imports_processes(scenario: dict[str, Any]) -> None:
    """`processes` rows flow through the generic loop into ``network.processes``.

    No per-sheet branch in ``build_network`` should exist for processes; if
    this test fails because someone added one, the contract is broken.
    """
    model = {
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(2),
        "carriers": [{"name": "h2"}],
        "processes": [
            {
                "name": "electrolyser",
                "bus0": "bus_a",
                "bus1": "bus_b",
                "carrier": "h2",
                "p_nom": 100.0,
            }
        ],
    }
    network, _ = build_network(model, scenario)

    assert "electrolyser" in network.processes.index
    assert network.processes.at["electrolyser", "bus0"] == "bus_a"
    assert network.processes.at["electrolyser", "bus1"] == "bus_b"
    assert float(network.processes.at["electrolyser", "p_nom"]) == 100.0


def test_generic_loop_imports_line_types(scenario: dict[str, Any]) -> None:
    """`line_types` is a non-bus-referencing sheet that still flows through the
    generic loop and lands in ``network.line_types``."""
    model = {
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(2),
        "line_types": [
            {
                "name": "ACSR-test",
                "r_per_length": 0.1,
                "x_per_length": 0.3,
                "i_nom": 1.0,
            }
        ],
    }
    network, _ = build_network(model, scenario)

    assert "ACSR-test" in network.line_types.index
    assert float(network.line_types.at["ACSR-test", "r_per_length"]) == pytest.approx(0.1)
    assert float(network.line_types.at["ACSR-test", "x_per_length"]) == pytest.approx(0.3)


def test_timeseries_sheet_wires_to_dynamic_attribute(
    scenario: dict[str, Any],
) -> None:
    """`generators-p_max_pu` wires onto ``network.generators_t.p_max_pu``.

    Confirms the ``<list_name>-<attr>`` convention for time-series sheets.
    """
    snaps = _hourly_snapshots(3)
    iso_labels = [r["snapshot"] for r in snaps]
    model = {
        "buses": _two_bus_buses(),
        "snapshots": snaps,
        "carriers": [{"name": "solar"}],
        "generators": [
            {
                "name": "solar_a",
                "bus": "bus_a",
                "carrier": "solar",
                "p_nom": 50.0,
            }
        ],
        "generators-p_max_pu": [
            {"snapshot": iso_labels[0], "solar_a": 0.1},
            {"snapshot": iso_labels[1], "solar_a": 0.6},
            {"snapshot": iso_labels[2], "solar_a": 0.9},
        ],
    }
    network, _ = build_network(model, scenario)

    p_max_pu = network.generators_t.p_max_pu
    assert "solar_a" in p_max_pu.columns
    assert len(p_max_pu) == 3
    assert float(p_max_pu["solar_a"].iloc[0]) == pytest.approx(0.1)
    assert float(p_max_pu["solar_a"].iloc[2]) == pytest.approx(0.9)


def test_generic_loop_imports_global_constraints_without_bus(
    scenario: dict[str, Any],
) -> None:
    """`global_constraints` declares ``bus`` as optional in the schema; rows
    without a bus column must still be imported through the generic loop."""
    model = {
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(2),
        "carriers": [{"name": "coal", "co2_emissions": 0.9}],
        "global_constraints": [
            {
                "name": "co2_cap_native",
                "type": "primary_energy",
                "sense": "<=",
                "constant": 1000.0,
                "carrier_attribute": "co2_emissions",
            }
        ],
    }
    network, _ = build_network(model, scenario)

    assert "co2_cap_native" in network.global_constraints.index
    row = network.global_constraints.loc["co2_cap_native"]
    assert str(row["type"]) == "primary_energy"
    assert str(row["sense"]) == "<="
    assert float(row["constant"]) == pytest.approx(1000.0)


def test_broken_bus_reference_is_dropped(scenario: dict[str, Any]) -> None:
    """Rows whose required bus reference points to a missing bus must be
    dropped and reported in ``notes``, never silently passed to PyPSA."""
    model = {
        "buses": _two_bus_buses(),
        "snapshots": _hourly_snapshots(2),
        "carriers": [{"name": "wind"}],
        "generators": [
            {"name": "ok", "bus": "bus_a", "carrier": "wind", "p_nom": 10.0},
            {"name": "dangling", "bus": "nonexistent_bus", "carrier": "wind", "p_nom": 10.0},
        ],
    }
    network, notes = build_network(model, scenario)

    assert "ok" in network.generators.index
    assert "dangling" not in network.generators.index
    assert any("dangling" in note for note in notes), (
        "Expected the dropped row to be surfaced in notes; got: " + repr(notes)
    )
