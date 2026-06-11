"""Regression tests for ``backend.pypsa.results.dispatch.build_curtailment_series``.

The Result dashboard's temporal curtailment chart and the Carrier performance
table read per-carrier curtailment. Curtailment is only meaningful for
generators with a time-varying ``p_max_pu`` (renewables):

    curtailment_g(t) = max(p_max_pu_g(t) * p_nom_g - p_g(t), 0)   [MW]

Thermal units at static availability running below ``p_nom`` are part-loaded,
not curtailed, and the load-shedding backstop (which also gets a time-varying
``p_max_pu``) must be excluded by name prefix.
"""
from __future__ import annotations

import pandas as pd
import pypsa

from backend.pypsa.results.dispatch import build_curtailment_series


def _toy_network() -> tuple[pypsa.Network, pd.DataFrame]:
    network = pypsa.Network()
    network.set_snapshots(pd.date_range("2025-01-01", periods=3, freq="h"))
    network.add("Bus", "b")
    network.add("Carrier", "solar")
    network.add("Carrier", "gas")
    network.add(
        "Generator", "pv", bus="b", carrier="solar", p_nom=100.0,
        p_max_pu=pd.Series([0.5, 1.0, 0.2], index=network.snapshots),
    )
    network.add("Generator", "ccgt", bus="b", carrier="gas", p_nom=100.0)
    network.add(
        "Generator", "load_shedding_b", bus="b", carrier="shed", p_nom=1e3,
        p_max_pu=pd.Series(1.0, index=network.snapshots),
    )
    dispatch = pd.DataFrame(
        {"pv": [30.0, 80.0, 20.0], "ccgt": [50.0] * 3, "load_shedding_b": [0.0] * 3},
        index=network.snapshots,
    )
    return network, dispatch


def test_renewable_curtailment_by_carrier() -> None:
    """Solar curtails avail - dispatch = 20/20/0 MW; zero rows stay sparse."""
    network, dispatch = _toy_network()
    out = build_curtailment_series(network, dispatch)
    assert [row["values"] for row in out] == [{"solar": 20.0}, {"solar": 20.0}, {}]


def test_thermal_part_load_and_shed_backstop_excluded() -> None:
    """No carrier other than the renewable one ever appears."""
    network, dispatch = _toy_network()
    out = build_curtailment_series(network, dispatch)
    carriers = {key for row in out for key in row["values"]}
    assert carriers <= {"solar"}


def test_no_time_varying_generators_yields_empty_values() -> None:
    """All-thermal networks produce rows with empty values dicts."""
    network = pypsa.Network()
    network.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    network.add("Bus", "b")
    network.add("Carrier", "gas")
    network.add("Generator", "ccgt", bus="b", carrier="gas", p_nom=100.0)
    dispatch = pd.DataFrame({"ccgt": [40.0, 60.0]}, index=network.snapshots)
    out = build_curtailment_series(network, dispatch)
    assert len(out) == 2
    assert all(row["values"] == {} for row in out)


def test_storage_soc_by_carrier() -> None:
    """SoC sums per carrier; SoC is a stock (MWh) — no snapshot weighting."""
    from backend.pypsa.results.dispatch import build_storage_soc_series

    network = pypsa.Network()
    network.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    network.add("Bus", "b")
    network.add("Carrier", "battery")
    network.add("Carrier", "phs")
    network.add("StorageUnit", "bat1", bus="b", carrier="battery", p_nom=10.0)
    network.add("StorageUnit", "bat2", bus="b", carrier="battery", p_nom=10.0)
    network.add("StorageUnit", "pump1", bus="b", carrier="phs", p_nom=50.0)
    network.storage_units_t.state_of_charge = pd.DataFrame(
        {"bat1": [5.0, 8.0], "bat2": [3.0, 0.0], "pump1": [100.0, 90.0]},
        index=network.snapshots,
    )
    out = build_storage_soc_series(network)
    assert [row["values"] for row in out] == [
        {"battery": 8.0, "phs": 100.0},
        {"battery": 8.0, "phs": 90.0},
    ]


def test_storage_soc_no_units_yields_empty_values() -> None:
    from backend.pypsa.results.dispatch import build_storage_soc_series

    network = pypsa.Network()
    network.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    network.add("Bus", "b")
    out = build_storage_soc_series(network)
    assert len(out) == 2
    assert all(row["values"] == {} for row in out)
