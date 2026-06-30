"""Modelling-to-Generate-Alternatives (MGA) — the near-optimal capacity space.

A single cost-optimal plan hides the fact that many *structurally different*
systems cost almost the same. MGA maps that ambiguity: for each technology it
asks "how little / how much of this carrier can the system build while staying
within ``slack`` of optimal cost?". The min/max pair per carrier traces the
near-optimal corridor — the decision-relevant spread, not a single point.

We delegate the optimisation to PyPSA's ``n.optimize.optimize_mga`` verbatim
(engine-feature parity). Each direction runs on a fresh ``network.copy()`` of
the *solved* optimum so the budget constraint
(``total_cost <= (1 + slack) * optimal_cost``) is always rebuilt from the true
optimum rather than drifting onto a previous alternative.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pypsa

_log = logging.getLogger("pypsa.solver")

# Each selected carrier costs two LP solves (min + max). Cap the number of
# carriers explored so a single run cannot fan out into an unbounded solve
# count; anything dropped is logged, never silently truncated.
_DEFAULT_MAX_CARRIERS = 6


def _capacity_by_carrier(network: pypsa.Network) -> dict[str, float]:
    """Optimised generator capacity (MW) summed per carrier."""
    gens = network.generators
    if gens.empty:
        return {}
    grouped = gens.groupby("carrier")["p_nom_opt"].sum()
    return {str(c): round(float(v), 3) for c, v in grouped.items()}


def _solution_cost(network: pypsa.Network) -> float:
    """Total system cost (capex + opex) of the network's current solution."""
    return float(network.statistics.capex().sum() + network.statistics.opex().sum())


def build_mga(
    network: pypsa.Network,
    *,
    slack: float,
    carriers: list[str] | None,
    currency: str,
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
    multi_investment_periods: bool = False,
    max_carriers: int = _DEFAULT_MAX_CARRIERS,
) -> dict[str, Any] | None:
    """Map the near-optimal capacity corridor for each selected carrier.

    Runs ``optimize_mga`` twice (min, max) per carrier on copies of the solved
    optimum and returns the optimum mix plus every alternative's full capacity
    mix and cost. Returns ``None`` when there is nothing meaningful to explore
    (unsolved network, no extendable generators) — never raises into the run.

    Args:
        network: A network already solved by ``n.optimize()``.
        slack: Cost relaxation; alternatives stay within ``1 + slack`` of the
            optimal cost (e.g. ``0.05`` = within 5%).
        carriers: Carriers to vary; ``None``/empty = every extendable-generator
            carrier, capped at ``max_carriers``.
        currency: Currency symbol for the cost figures (passthrough for the UI).
        solver_options: HiGHS options mirrored from the main solve.
        io_api: linopy IO api, mirrored from the main solve.
        multi_investment_periods: Pass-through for pathway (multi-period) runs.
        max_carriers: Hard cap on carriers explored (each costs two solves).

    Returns:
        ``{slack, currency, optimum: {cost, capacityByCarrier},
        carriers, alternatives: [{carrier, sense, status, cost, costRatio,
        capacityByCarrier}], droppedCarriers}`` or ``None``.
    """
    if not getattr(network, "is_solved", False):
        return None

    gens = network.generators
    if gens.empty:
        return None
    # MGA only moves *extendable* capacity; carriers with no extendable
    # generator have a fixed p_nom and cannot vary in the near-optimal space.
    extendable = gens[gens["p_nom_extendable"]] if "p_nom_extendable" in gens.columns else gens.iloc[0:0]
    if extendable.empty:
        return None
    extendable_carriers = [str(c) for c in pd.unique(extendable["carrier"]) if str(c)]
    if not extendable_carriers:
        return None

    requested = [str(c) for c in (carriers or []) if str(c)]
    selected = [c for c in requested if c in extendable_carriers] or extendable_carriers
    dropped = selected[max_carriers:]
    selected = selected[:max_carriers]
    if dropped:
        _log.warning(
            "MGA: exploring %d carriers (cap=%d); dropped %d: %s",
            len(selected), max_carriers, len(dropped), dropped,
        )

    optimum_cost = _solution_cost(network)
    optimum_mix = _capacity_by_carrier(network)

    # ``network.copy()`` refuses while a solver model is attached; detach it once
    # on the base. The app recomputes every reported number from solved
    # dataframes, never from the live solver model, so this is side-effect-free
    # for the rest of the run.
    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001 — best effort; copy() will report if it still fails
        pass

    solver_options = solver_options or {}
    alternatives: list[dict[str, Any]] = []
    for carrier in selected:
        weights = {
            "Generator": {
                "p_nom": pd.Series(
                    [1.0 if str(c) == carrier else 0.0 for c in gens["carrier"]],
                    index=gens.index,
                )
            }
        }
        for sense in ("min", "max"):
            try:
                work = network.copy()
                status, condition = work.optimize.optimize_mga(
                    weights=weights,
                    sense=sense,
                    slack=slack,
                    multi_investment_periods=multi_investment_periods,
                    # Match the main solve: keep the objective constant out of the
                    # LP (a fixed offset that changes no reported number, only
                    # improves conditioning) and pin to the PyPSA v2.0 default.
                    model_kwargs={"include_objective_constant": False},
                    solver_name="highs",
                    solver_options=solver_options,
                    io_api=io_api,
                )
            except Exception as exc:  # noqa: BLE001 — one direction failing must not sink the table
                _log.warning("MGA %s/%s failed: %s", carrier, sense, exc)
                continue
            if str(status) != "ok":
                _log.warning("MGA %s/%s non-optimal: %s/%s", carrier, sense, status, condition)
                continue
            cost = _solution_cost(work)
            alternatives.append(
                {
                    "carrier": carrier,
                    "sense": sense,
                    "status": str(status),
                    "cost": round(cost, 2),
                    "costRatio": round(cost / optimum_cost, 4) if optimum_cost else None,
                    "capacityByCarrier": _capacity_by_carrier(work),
                }
            )

    if not alternatives:
        return None
    _log.info("MGA: %d alternatives across %d carriers (slack=%.3f)", len(alternatives), len(selected), slack)
    return {
        "slack": round(float(slack), 4),
        "currency": currency,
        "optimum": {"cost": round(optimum_cost, 2), "capacityByCarrier": optimum_mix},
        "carriers": selected,
        "alternatives": alternatives,
        "droppedCarriers": dropped,
    }
