"""HiGHS solver-option gating.

The default `solverType="auto"` must NOT pin a HiGHS method — so the solve
runs `n.optimize(solver_name="highs")` with HiGHS choosing the fastest path
(the fast default, matching a bare script run). A method is pinned only when
the user explicitly selects simplex / ipm / pdlp.
"""
from __future__ import annotations

from backend.pypsa.results import _build_solver_options


def test_auto_default_omits_method():
    # default (no solverType) → auto → no `solver` key, no threads
    assert _build_solver_options({}) == {}
    assert _build_solver_options({"solverType": "auto"}) == {}
    # "highs"/"choose"/unknown are treated as auto (HiGHS chooses)
    assert _build_solver_options({"solverType": "highs"}) == {}
    assert _build_solver_options({"solverType": "choose"}) == {}


def test_explicit_method_is_pinned():
    assert _build_solver_options({"solverType": "simplex"}) == {"solver": "simplex"}
    assert _build_solver_options({"solverType": "ipm"}) == {"solver": "ipm"}
    assert _build_solver_options({"solverType": "pdlp"}) == {"solver": "pdlp"}
    # case-insensitive
    assert _build_solver_options({"solverType": "IPM"}) == {"solver": "ipm"}


def test_threads_pinned_only_when_positive():
    assert _build_solver_options({"solverThreads": 0}) == {}      # 0 = all cores
    assert _build_solver_options({"solverThreads": 4}) == {"threads": 4}
    assert _build_solver_options({"solverType": "ipm", "solverThreads": 8}) == {
        "solver": "ipm", "threads": 8,
    }
