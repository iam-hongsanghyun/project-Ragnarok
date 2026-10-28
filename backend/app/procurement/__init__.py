"""Procurement portfolio optimizer (PP2) — pure math, no I/O.

A buyer with an hourly load faces spot-price risk and can hedge with a menu of
instruments: a fixed-price PPA (as-produced or flat profile), a flat forward
block, and a full-requirements retail tariff. The residual is settled at spot
(net: excess contracted energy sells back at spot). Deterministic min-cost is
trivial (100 % on the cheapest instrument) — the substance is RISK: price
scenarios (bootstrap of the observed series + user stress cases) and a CVaR
budget on total spend.

Algorithm (Rockafellar–Uryasev CVaR linearization):
    $$ \\min_{x,\\zeta,u} \\; \\tfrac{1}{S}\\sum_s c_s(x)
       \\;\\; \\text{s.t.} \\;\\; \\zeta + \\tfrac{1}{(1-\\alpha)S}\\sum_s u_s \\le B,
       \\;\\; u_s \\ge c_s(x) - \\zeta, \\; u_s \\ge 0 $$
    ASCII: minimize the mean scenario cost subject to CVaR_alpha(cost) <= B,
    with u_s the excess of scenario s's cost over the VaR proxy zeta.

Per-scenario cost is linear in the decisions (PPA MW ``p``, forward MW ``f``,
retail share ``y``):
    c_s = sum_t L_t P_st                       (full spot exposure)
        + p * sum_t g_t (K - P_st)             (PPA replaces spot at strike K)
        + f * sum_t (F - P_st)                 (forward block at price F)
        + y * sum_t L_t (R - P_st)             (retail tariff at rate R)

Solved with scipy.optimize.linprog (HiGHS) — a tiny LP (3 + S + 1 variables).
Symbols: L_t load (MW), P_st scenario price (currency/MWh), g_t PPA capacity
factor (0–1), K/F/R instrument prices (currency/MWh), alpha CVaR tail level.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import linprog


def empirical_cvar(costs: np.ndarray, alpha: float) -> float:
    """CVaR_alpha = mean of the worst ``(1 − alpha)`` share of scenario costs."""
    if len(costs) == 0:
        return 0.0
    k = max(1, int(round((1.0 - alpha) * len(costs))))
    worst = np.sort(costs)[-k:]
    return float(worst.mean())


def generate_scenarios(
    prices: np.ndarray,
    *,
    n_bootstrap: int = 200,
    block_hours: int = 24,
    stress: list[dict[str, Any]] | None = None,
    seed: int = 7,
) -> tuple[np.ndarray, list[str]]:
    """Price scenarios (S, T): the observed series first (deterministic case),
    then moving-block bootstrap resamples (preserves intra-day shape), then any
    user stress cases (multipliers on the observed series).
    """
    T = len(prices)
    rows: list[np.ndarray] = [prices.astype(float)]
    labels = ["observed"]
    if n_bootstrap > 0 and T > 1:
        rng = np.random.default_rng(seed)
        block = max(1, min(int(block_hours), T))
        n_blocks = int(np.ceil(T / block))
        starts_max = T - block + 1
        for b in range(n_bootstrap):
            starts = rng.integers(0, starts_max, size=n_blocks)
            sample = np.concatenate([prices[s:s + block] for s in starts])[:T]
            rows.append(sample.astype(float))
            labels.append(f"bootstrap_{b + 1}")
    for case in stress or []:
        mult = float(case.get("multiplier", 1.0))
        rows.append(prices.astype(float) * mult)
        labels.append(str(case.get("label") or f"stress ×{mult:g}"))
    return np.vstack(rows), labels


def _cost_coefficients(
    scenario_prices: np.ndarray,  # (S, T)
    load: np.ndarray,  # (T,)
    instruments: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, list[str], list[float]]:
    """Per-scenario constants (full spot) + linear coefficients per instrument.

    Returns (spot_cost (S,), coeff (S, N), names, upper_bounds) where N is the
    number of ENABLED instruments in order [ppa, forward, retail].
    """
    S, T = scenario_prices.shape
    spot_cost = scenario_prices @ load  # (S,)
    coeffs: list[np.ndarray] = []
    names: list[str] = []
    uppers: list[float] = []

    ppa = instruments.get("ppa") or {}
    if ppa.get("enabled"):
        profile = np.asarray(ppa.get("profile") or np.ones(T), dtype=float)[:T]
        if len(profile) < T:
            profile = np.pad(profile, (0, T - len(profile)), constant_values=float(profile.mean() if len(profile) else 1.0))
        strike = float(ppa.get("strike") or 0.0)
        coeffs.append((strike - scenario_prices) @ profile)  # (S,)
        names.append("ppa")
        uppers.append(max(0.0, float(ppa.get("maxMw") or 0.0)))

    fwd = instruments.get("forward") or {}
    if fwd.get("enabled"):
        price = float(fwd.get("price") or 0.0)
        coeffs.append(price * T - scenario_prices.sum(axis=1))
        names.append("forward")
        uppers.append(max(0.0, float(fwd.get("maxMw") or 0.0)))

    retail = instruments.get("retail") or {}
    if retail.get("enabled"):
        rate = float(retail.get("price") or 0.0)
        coeffs.append(rate * float(load.sum()) - spot_cost)
        names.append("retail")
        uppers.append(1.0)  # share of load

    coeff = np.column_stack(coeffs) if coeffs else np.zeros((S, 0))
    return spot_cost, coeff, names, uppers


def _solve(
    spot_cost: np.ndarray,
    coeff: np.ndarray,
    uppers: list[float],
    alpha: float,
    cvar_budget: float | None,
    minimize_cvar: bool = False,
) -> tuple[np.ndarray, np.ndarray] | None:
    """One LP solve. Variables: [decisions (N), zeta, u (S)]. Returns
    (decisions, scenario_costs) or None if infeasible."""
    S, N = coeff.shape
    n_var = N + 1 + S
    tail = 1.0 / ((1.0 - alpha) * S)

    if minimize_cvar:
        c = np.zeros(n_var)
        c[N] = 1.0
        c[N + 1:] = tail
    else:
        c = np.zeros(n_var)
        c[:N] = coeff.mean(axis=0)

    # Tail constraint block: u_s ≥ C_s − ζ where C_s = spot_s + coeff_s·x is the
    # TOTAL scenario cost. Moving the spot constant to the RHS:
    #     coeff_s·x − ζ − u_s ≤ −spot_s
    a_rows = [np.concatenate([coeff[s], [-1.0], -np.eye(S)[s]]) for s in range(S)]
    b_rows = list(-spot_cost)
    if cvar_budget is not None and not minimize_cvar:
        # CVaR_α(total cost) = ζ + tail·Σ u_s ≤ B (Rockafellar–Uryasev).
        row = np.zeros(n_var)
        row[N] = 1.0
        row[N + 1:] = tail
        a_rows.append(row)
        b_rows.append(float(cvar_budget))

    bounds = [(0.0, u) for u in uppers] + [(None, None)] + [(0.0, None)] * S
    res = linprog(c, A_ub=np.vstack(a_rows), b_ub=np.array(b_rows), bounds=bounds, method="highs")
    if not res.success:
        return None
    x = res.x[:N]
    scenario_costs = spot_cost + coeff @ x
    return x, scenario_costs


def optimize_portfolio(
    scenario_prices: np.ndarray,
    load: np.ndarray,
    instruments: dict[str, Any],
    *,
    alpha: float = 0.95,
    cvar_budget: float | None = None,
    frontier_points: int = 8,
) -> dict[str, Any]:
    """Optimal instrument mix + cost-vs-risk efficient frontier.

    Returns a JSON-safe dict: the optimal portfolio under ``cvar_budget`` (or
    the unconstrained expected-cost minimum when None), the spot-only baseline,
    and the efficient frontier from the minimum-CVaR portfolio to the
    unconstrained optimum.
    """
    S, T = scenario_prices.shape
    load = np.asarray(load, dtype=float)[:T]
    spot_cost, coeff, names, uppers = _cost_coefficients(scenario_prices, load, instruments)

    def portfolio(x: np.ndarray, costs: np.ndarray) -> dict[str, Any]:
        mix = {names[i]: round(float(x[i]), 4) for i in range(len(names))}
        return {
            "mix": mix,
            "expectedCost": round(float(costs.mean()), 2),
            "cvar": round(empirical_cvar(costs, alpha), 2),
            "worstCost": round(float(costs.max()), 2),
            "bestCost": round(float(costs.min()), 2),
        }

    baseline_costs = spot_cost
    baseline = {
        "expectedCost": round(float(baseline_costs.mean()), 2),
        "cvar": round(empirical_cvar(baseline_costs, alpha), 2),
        "worstCost": round(float(baseline_costs.max()), 2),
    }

    if coeff.shape[1] == 0:
        return {"baseline": baseline, "optimal": None, "frontier": [],
                "error": "No instruments enabled."}

    # Anchor points: unconstrained expected-cost minimum and minimum-CVaR.
    unc = _solve(spot_cost, coeff, uppers, alpha, None)
    mincv = _solve(spot_cost, coeff, uppers, alpha, None, minimize_cvar=True)
    if unc is None or mincv is None:
        return {"baseline": baseline, "optimal": None, "frontier": [],
                "error": "Portfolio LP infeasible."}
    cvar_hi = empirical_cvar(unc[1], alpha)
    cvar_lo = empirical_cvar(mincv[1], alpha)

    frontier: list[dict[str, Any]] = []
    if cvar_hi - cvar_lo > 1e-6 and frontier_points > 1:
        for budget in np.linspace(cvar_lo, cvar_hi, frontier_points):
            sol = _solve(spot_cost, coeff, uppers, alpha, float(budget))
            if sol is None:
                continue
            frontier.append({"budget": round(float(budget), 2), **portfolio(*sol)})
    else:
        frontier.append({"budget": round(cvar_hi, 2), **portfolio(*unc)})

    if cvar_budget is not None:
        chosen = _solve(spot_cost, coeff, uppers, alpha, float(cvar_budget))
        optimal = portfolio(*chosen) if chosen is not None else None
        if optimal is None:
            optimal = {**portfolio(*mincv), "note": "Risk budget below the minimum achievable CVaR — showing the minimum-risk portfolio."}
    else:
        optimal = portfolio(*unc)

    # Cost distribution of the chosen portfolio (for the histogram).
    x_opt = np.array([optimal["mix"].get(n, 0.0) for n in names])
    dist = spot_cost + coeff @ x_opt

    return {
        "alpha": alpha,
        "instrumentNames": names,
        "baseline": baseline,
        "optimal": optimal,
        "frontier": frontier,
        "scenarioCosts": [round(float(v), 2) for v in dist],
        "riskRange": {"minCvar": round(cvar_lo, 2), "maxCvar": round(cvar_hi, 2)},
    }
