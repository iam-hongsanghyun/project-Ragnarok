"""Rolling horizon with line losses keeps every window's line flows (PyPSA post_processing alignment fix).

Captured baseline: a one-shot solve of the same network. With losses, the lossy flow p0 = delivered + loss/2,
so a rolling run must give the same p0, p1 and bus injections in every snapshot, not only the last window.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pypsa

import backend.pypsa.rolling  # noqa: F401  (applies keep_results_outside_window)

logging.disable(logging.WARNING)

_KW = dict(
    solver_name="highs",
    transmission_losses={"mode": "tangents", "segments": 3},
    solver_options={"output_flag": False},
)


def _network() -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2025-01-01", periods=12, freq="h"))
    n.add("Carrier", "AC")
    n.add("Bus", "a", carrier="AC", v_nom=345.0)
    n.add("Bus", "b", carrier="AC", v_nom=345.0)
    n.add("Line", "l", bus0="a", bus1="b", x=0.1, r=5.0, s_nom=200.0, carrier="AC")
    n.add("Generator", "g", bus="a", p_nom=300.0, marginal_cost=1.0)
    load = pd.Series(np.linspace(20.0, 130.0, 12), index=n.snapshots)
    n.add("Load", "d", bus="b", p_set=load)
    return n


def test_rolling_keeps_line_flows_of_every_window() -> None:
    one = _network()
    one.optimize(**_KW)
    roll = _network()
    roll.optimize.optimize_with_rolling_horizon(horizon=4, overlap=1, **_KW)

    for frame in ("p0", "p1"):
        got = roll.lines_t[frame]["l"]
        assert not got.isna().any(), f"lines {frame} has NaN outside the last window"
        np.testing.assert_allclose(got.to_numpy(), one.lines_t[frame]["l"].to_numpy(), rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(
        roll.buses_t.p.to_numpy(), one.buses_t.p[roll.buses_t.p.columns].to_numpy(), rtol=1e-6, atol=1e-6
    )
