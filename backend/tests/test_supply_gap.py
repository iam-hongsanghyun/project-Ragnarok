"""Energy-balance gate — a reported run must actually supply its load.

Regression: HiGHS' interior-point path (no crossover) returned a point linopy
accepted (status='ok', condition='unknown') in which EVERY dispatch variable was
zero while load was ~95 GW. Lenient acceptance passed it through, so the run
looked successful while every KPI was zero — no dispatch, no emissions, zero
price, and extendable capacity "optimised" to 0.
"""
from __future__ import annotations

import pandas as pd
import pypsa
import pytest

from backend.pypsa.results import _rolling_suspect_note, _supply_gap

SNAPS = pd.date_range("2030-01-01", periods=4, freq="h")


def _network(dispatch: float) -> pypsa.Network:
    """One bus, one 100 MW load, one generator dispatching ``dispatch`` MW."""
    n = pypsa.Network()
    n.set_snapshots(SNAPS)
    n.add("Bus", "b")
    n.add("Carrier", "gas")
    n.add("Generator", "g", bus="b", carrier="gas", p_nom=200.0)
    n.add("Load", "L", bus="b", p_set=100.0)
    # Stand in for a solved network: PyPSA writes dispatch into generators_t.p.
    n.generators_t.p = pd.DataFrame({"g": [dispatch] * len(SNAPS)}, index=SNAPS)
    return n


def test_flags_load_served_by_nothing() -> None:
    # The reported failure: positive load, zero dispatch everywhere.
    gap = _supply_gap(_network(0.0))
    assert gap is not None
    count, total, _first, _last = gap
    assert (count, total) == (4, 4)


def test_healthy_solve_has_no_gap() -> None:
    assert _supply_gap(_network(100.0)) is None


def test_storage_discharge_counts_as_supply() -> None:
    """A storage-backed hour must NOT be mistaken for a failed solve — the
    reported model leaned on 24 GW of storage."""
    n = _network(0.0)
    n.add("StorageUnit", "s", bus="b", p_nom=150.0)
    n.storage_units_t.p = pd.DataFrame({"s": [100.0] * len(SNAPS)}, index=SNAPS)
    assert _supply_gap(n) is None


def test_partial_gap_reports_only_the_bad_snapshots() -> None:
    n = _network(0.0)
    n.generators_t.p = pd.DataFrame({"g": [100.0, 0.0, 0.0, 100.0]}, index=SNAPS)
    gap = _supply_gap(n)
    assert gap is not None
    count, total, first, last = gap
    assert (count, total) == (2, 4)
    assert (first, last) == (SNAPS[1], SNAPS[3 - 1])


def test_zero_load_is_not_a_gap() -> None:
    n = _network(0.0)
    n.loads_t.p_set = pd.DataFrame({"L": [0.0] * len(SNAPS)}, index=SNAPS)
    assert _supply_gap(n) is None


def test_rolling_note_degrades_rather_than_raising() -> None:
    # Rolling horizon keeps reporting (solved windows stay usable) — it must
    # still describe the bad stretch.
    note = _rolling_suspect_note(_network(0.0))
    assert note is not None
    assert "zero recorded supply" in note
    assert _rolling_suspect_note(_network(100.0)) is None


@pytest.mark.parametrize("dispatch", [1e-9, 0.0])
def test_numerically_zero_dispatch_still_counts_as_a_gap(dispatch: float) -> None:
    assert _supply_gap(_network(dispatch)) is not None
