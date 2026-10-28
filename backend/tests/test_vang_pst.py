"""P12/P13: PST bounds, v_ang_max enforced, v_ang_min deprecated and dropped."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pypsa
import pytest

from backend.pypsa.network import build_network
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.results.phase_shift import build_phase_shifters, optimised_phase_shifters


def _ring(**line_kw) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=2, freq="h"))
    n.add("Bus", ["a", "b"], v_nom=110)
    n.add("Generator", "g", bus="a", p_nom=500, marginal_cost=1)
    n.add("Generator", "g2", bus="b", p_nom=500, marginal_cost=100)
    n.add("Load", "L", bus="b", p_set=100)
    n.add("Line", "l1", bus0="a", bus1="b", x=0.1, r=0.01, s_nom=1000, **line_kw)
    return n


def test_v_ang_max_enforced_and_matches_native():
    SC, OP = {"carbonPrice": 0.0, "discountRate": 0.0}, {}
    native = _ring(v_ang_max=0.01)
    native.optimize(solver_name="highs")
    built, _ = build_network(network_to_model(_ring(v_ang_max=0.01)), SC, OP)
    built.optimize(solver_name="highs")
    assert built.objective == pytest.approx(native.objective, rel=1e-9)
    # the cap binds: |theta| = x_pu * f <= 0.01 deg
    x_pu = float(native.lines.at["l1", "x_pu_eff"])
    assert abs(float(native.lines_t.p0.iloc[0, 0])) * x_pu <= np.deg2rad(0.01) + 1e-6
    free = _ring()
    free.optimize(solver_name="highs")
    assert free.objective < native.objective - 1.0


def test_v_ang_min_goes_to_pypsa_as_written_and_the_validator_warns():
    """D14: the build no longer clears a finite v_ang_min; PyPSA warns about it, so does the validator."""
    from backend.app.models import RunPayload
    from backend.pypsa.network import validate_model

    model = network_to_model(_ring())
    model["lines"][0]["v_ang_min"] = -5.0
    net, notes = build_network(model, {"carbonPrice": 0.0, "discountRate": 0.0}, {})
    assert net.lines.at["l1", "v_ang_min"] == -5.0
    assert not any("v_ang_min" in x for x in notes)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        net.optimize(solver_name="highs")
    assert any("v_ang_min" in str(w.message) for w in caught)
    report = validate_model(RunPayload(model=model, scenario={}, options={}))
    assert any("v_ang_min" in w for w in report["warnings"])


def test_phase_shifter_summary_and_pf_uses_opt():
    n = _ring()
    n.add("Bus", "c", v_nom=110)
    n.add("Transformer", "pst", bus0="a", bus1="c", x=0.1, s_nom=1000,
          phase_shift_min=-10, phase_shift_max=10)
    n.add("Line", "l2", bus0="c", bus1="b", x=0.1, r=0.01, s_nom=1000)
    n.optimize(solver_name="highs")
    assert optimised_phase_shifters(n) == ["pst"]
    view = build_phase_shifters(n)
    row = view["transformers"][0]
    assert row["phaseShiftMinDeg"] == -10 and row["phaseShiftMaxDeg"] == 10
    s = n.transformers_t.phase_shift_opt["pst"]
    assert row["minDeg"] == pytest.approx(float(s.min()), abs=1e-5)
