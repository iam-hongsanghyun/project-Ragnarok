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


def test_hipo_is_capability_gated_and_falls_back():
    """Selecting HiPO must be safe on any machine: use it where the HiGHS build
    has it, fall back to IPM where it doesn't — never error."""
    from backend.pypsa.results import _highs_has_hipo

    opts = _build_solver_options({"solverType": "hipo"})
    if _highs_has_hipo():
        assert opts == {"solver": "hipo"}
    else:
        assert opts == {"solver": "ipm"}


def test_threads_pinned_only_when_positive():
    assert _build_solver_options({"solverThreads": 0}) == {}      # 0 = all cores
    assert _build_solver_options({"solverThreads": 4}) == {"threads": 4}
    assert _build_solver_options({"solverType": "ipm", "solverThreads": 8}) == {
        "solver": "ipm", "threads": 8,
    }


def test_objective_auto_scale_is_opt_in_and_results_neutral():
    """The 'Auto-scale objective' toggle adds HiGHS' recommended
    ``user_objective_scale=-1`` (results-neutral). Absent ⇒ off, so a bare
    options dict stays identical to a plain HiGHS optimize."""
    assert _build_solver_options({}) == {}                              # absent → off
    assert _build_solver_options({"objectiveAutoScale": False}) == {}
    assert _build_solver_options({"objectiveAutoScale": True}) == {
        "user_objective_scale": -1,
    }
    # composes with a pinned method and threads
    assert _build_solver_options(
        {"solverType": "pdlp", "solverThreads": 4, "objectiveAutoScale": True}
    ) == {"solver": "pdlp", "threads": 4, "user_objective_scale": -1}


def test_solve_rejected_acceptance_modes():
    from backend.pypsa.results import _solve_rejected

    # optimal always passes, both modes
    assert _solve_rejected("ok", "optimal", strict=False) is False
    assert _solve_rejected("ok", "optimal", strict=True) is False

    # linopy-accepted interior-point solve without crossover: condition
    # 'unknown' with status 'ok' — lenient keeps it, strict rejects it.
    assert _solve_rejected("ok", "unknown", strict=False) is False
    assert _solve_rejected("warning", "unknown", strict=False) is False
    assert _solve_rejected("ok", "unknown", strict=True) is True

    # definite failures are rejected in BOTH modes
    for cond in ("infeasible", "unbounded", "infeasible_or_unbounded"):
        assert _solve_rejected("ok", cond, strict=False) is True
        assert _solve_rejected("ok", cond, strict=True) is True

    # solver crash (status not ok/warning) is rejected even in lenient mode
    assert _solve_rejected("error", "unknown", strict=False) is True
    assert _solve_rejected("unknown", "unknown", strict=False) is True
