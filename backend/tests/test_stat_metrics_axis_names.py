"""Regression: ``n.statistics.revenue`` read as empty on pandas 3.0.5 for unnamed column axes.

PyPSA's revenue does ``static["bus"][df.columns]`` then ``.droplevel("name")``. pandas 3.1
keeps the Series' index name when selected with an unnamed ``Index``; pandas 3.0.5 takes
the key's name (``None``), so ``droplevel`` raises ``KeyError`` that PyPSA swallows into an
empty result. Frames written by hand / from stored outputs have unnamed column axes, so
Ragnarok names them (``name_dynamic_axes``) before reading statistics.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pypsa

from backend.pypsa.results.stat_metrics import asset_statistic, combine_periods, name_dynamic_axes


def _hand_set_network() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=2, freq="h"))
    n.add("Bus", "b")
    n.add("Carrier", "coal")
    n.add("Generator", "g1", bus="b", carrier="coal", marginal_cost=20.0, p_nom=100.0)
    # Unnamed column axes, exactly as a stored-output injection produces.
    n.generators_t["p"] = pd.DataFrame({"g1": [100.0, 80.0]}, index=n.snapshots)
    n.buses_t["marginal_price"] = pd.DataFrame({"b": [30.0, 60.0]}, index=n.snapshots)
    return n


def test_revenue_of_unnamed_axis_frames_is_not_silently_empty():
    n = _hand_set_network()
    assert n.generators_t.p.columns.name is None  # the precondition that broke 3.0.5
    revenue = combine_periods(asset_statistic(n, "revenue", ["Generator", "StorageUnit", "Process"]))
    # 100 MW * 30 + 80 MW * 60 (unit snapshot weights)
    np.testing.assert_allclose(revenue.loc[("Generator", "g1")], 7800.0, rtol=1e-9)


def test_name_dynamic_axes_is_idempotent_and_only_names_unnamed():
    n = _hand_set_network()
    name_dynamic_axes(n)
    name_dynamic_axes(n)
    assert n.generators_t.p.columns.name == "name"
    assert n.buses_t.marginal_price.columns.name == "name"
