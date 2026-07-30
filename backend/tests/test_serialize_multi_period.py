"""Serialising a MULTI-PERIOD network back to the workbook model.

``network_to_model`` addresses each snapshot by a workbook cell. A
multi-investment-period network indexes its snapshots by a ``(period, timestep)``
MultiIndex, so pandas hands each entry over as a tuple — and ``str(tuple)``
writes the Python repr (``"(2030, Timestamp('2030-01-01 00:00:00'))"``) into the
sheet. That is not a date: the reduced/imported model can no longer be parsed as
multi-period, and a pathway plan silently reverts to a single period.

These tests pin the ``period`` + ``snapshot`` column pair that
``_snapshots_index`` reads back, and prove the index survives a full
serialise → rebuild round-trip.
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model

PERIODS = [2030, 2035]
SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.0}
_PATHWAY_OPTIONS: dict[str, Any] = {
    "enableLoadShedding": False,
    "currencySymbol": "$",
    "pathwayConfig": {
        "enabled": True,
        "snapshotMappingMode": "explicit_period_column",
        "periods": [
            {"period": p, "objectiveWeight": 1.0, "yearsWeight": 5.0} for p in PERIODS
        ],
    },
}


def _multi_period_network() -> pypsa.Network:
    """Two investment periods × two hours, with a load profile per snapshot."""
    n = pypsa.Network()
    hours = pd.date_range("2030-01-01", periods=2, freq="h")
    n.set_snapshots(pd.MultiIndex.from_product([PERIODS, hours], names=["period", "timestep"]))
    n.investment_periods = PERIODS
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=500.0, marginal_cost=10.0)
    n.add("Load", "l", bus="b", p_set=pd.Series(100.0, index=n.snapshots))
    return n


def test_snapshots_sheet_splits_period_and_timestamp() -> None:
    model = network_to_model(_multi_period_network())
    rows = model["snapshots"]
    assert len(rows) == 4
    assert [row["period"] for row in rows] == [2030, 2030, 2035, 2035]
    for row in rows:
        # A parseable ISO timestamp, never a tuple repr.
        assert "(" not in str(row["snapshot"])
        assert pd.notna(pd.to_datetime(row["snapshot"]))


def test_temporal_sheets_carry_the_period_column() -> None:
    model = network_to_model(_multi_period_network())
    rows = model["loads-p_set"]
    assert len(rows) == 4
    assert {row["period"] for row in rows} == set(PERIODS)
    for row in rows:
        assert "(" not in str(row["snapshot"])
        assert row["l"] == 100.0


def test_multi_period_index_survives_serialise_then_rebuild() -> None:
    native = _multi_period_network()
    rebuilt, _notes = build_network(
        network_to_model(native), SCENARIO, _PATHWAY_OPTIONS
    )
    assert isinstance(rebuilt.snapshots, pd.MultiIndex)
    assert list(rebuilt.snapshots.get_level_values(0).unique()) == PERIODS
    assert len(rebuilt.snapshots) == len(native.snapshots)
