"""Infeasibility & solver diagnostics (Q2).

When a solve comes back infeasible / unbounded, a raw solver string ("Model
status: Infeasible") tells the user nothing actionable. This inspects the
network *structure* — no solve needed — and explains the likely cause in the
terms a modeller can fix:

  1. **Capacity adequacy** (copper-plate): can total available generation meet
     load every snapshot? The dominant cause of infeasibility is a peak load
     that no combination of bounded capacity can serve, with load shedding off.
  2. **Suspect coefficients**: placeholder ``inf`` / ``≥1e12`` values in
     ``p_nom_max`` / ``e_sum_*`` / ``lifetime`` / cost columns that make the LP
     unbounded or ill-conditioned.
  3. **Starved energy budgets**: ``e_sum_max`` is an ANNUAL budget that
     ``build_network`` scales to the modelled window (× window_hours / 8760).
     A generous-looking 8000 MWh/yr becomes ~21.9 MWh on a 24 h window —
     starving supply without tripping the power-based check above.
  4. **Binding global constraints**: a CO₂ cap or similar that may conflict with
     the only capacity able to serve load.

It returns human-readable lines + concrete suggestions (enable load shedding,
raise a cap, add capacity), surfaced in the solver error instead of the raw
string. Pure and unit-tested.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ...app.config import load_system_defaults

_BIG = 1e12  # placeholder threshold: values at/above this read as "unbounded"

# Per-column PyPSA defaults for the suspect-coefficient scan: bound columns
# default to ±inf (Generator/StorageUnit p_nom_max, Store e_nom_max and
# Generator e_sum_max default +inf; Generator e_sum_min defaults -inf), so an
# inf of the DEFAULT sign is normal and must never be flagged — only an inf of
# the opposite sign, or a finite >= _BIG placeholder standing in for inf, is
# suspect. Cost columns default to 0.0, so any inf (and any |v| >= _BIG, since
# a huge NEGATIVE cost unbounds the objective just as surely) is suspect.
_POS_INF_DEFAULT_COLS = ("p_nom_max", "e_nom_max", "e_sum_max")
_NEG_INF_DEFAULT_COLS = ("e_sum_min",)
_COST_COLS = ("capital_cost", "marginal_cost")


def _is_suspect_value(col: str, v: float) -> bool:
    """True when ``v`` in column ``col`` reads as a placeholder/extreme value.

    Flags only NON-DEFAULT extremes: ``inf`` where inf is not that column's
    PyPSA default (see the column groups above), plus any finite magnitude at
    or above ``_BIG`` (for bound columns only a huge POSITIVE value — a
    finite stand-in for +inf, or an ``e_sum_min`` that forces impossible
    throughput; a huge negative bound just mimics its unbounded default).
    """
    if np.isnan(v):
        return False
    if np.isinf(v):
        if col in _POS_INF_DEFAULT_COLS:
            return v < 0  # +inf IS the default; -inf is a pathological bound
        if col in _NEG_INF_DEFAULT_COLS:
            return v > 0  # -inf IS the default; +inf forces impossible throughput
        return True  # inf is never a default in cost columns
    if col in _COST_COLS:
        return abs(v) >= _BIG
    return v >= _BIG

# A window-scaled e_sum_max below this fraction of BOTH the window's load
# energy and the generator's own capacity-bound energy reads as "starved":
# the budget, not capacity, is what pins the generator.
_STARVED_BUDGET_FRACTION = 0.2


def _load_by_snapshot(network: pypsa.Network) -> np.ndarray:
    if len(network.loads) == 0:
        return np.zeros(len(network.snapshots))
    return network.get_switchable_as_dense("Load", "p_set").sum(axis=1).to_numpy()


def _has_load_shedding(network: pypsa.Network) -> bool:
    return any(str(g).startswith("load_shedding") for g in network.generators.index)


def _period_factor(network: pypsa.Network) -> float:
    """Annual→window factor applied to ``e_sum_*`` budgets at build time.

    Mirrors the "Period-factor scaling" block in ``backend/pypsa/network``:
    the network arriving here already carries e_sum_max × factor, so the
    annual figure the user typed is ``e_sum_max / factor``.

    Algorithm:
        $$f = \\min\\left(1, \\frac{\\sum_t w_t}{H_{yr}}\\right)$$
        f = min(1, sum(objective weights) / hours_in_year)

    where $w_t$ is the objective snapshot weighting (h represented per
    snapshot) and $H_{yr}$ is ``simulation.hours_in_year`` (h, default 8760).
    Pathway (multi-period) runs use the smallest per-period weight sum.
    """
    try:
        sim_cfg = load_system_defaults().get("simulation", {})
        hours_in_year = float(sim_cfg.get("hours_in_year", 8760.0))
    except Exception:  # diagnostics must never fail on config I/O
        hours_in_year = 8760.0
    weights = network.snapshot_weightings["objective"]
    if isinstance(network.snapshots, pd.MultiIndex):
        period_sizes = weights.groupby(level="period").sum()
        if len(period_sizes) == 0:
            return 1.0
        return min(float(period_sizes.min()) / hours_in_year, 1.0)
    modelled_hours = float(weights.sum())
    return min(1.0, modelled_hours / hours_in_year) if modelled_hours > 0 else 1.0


def diagnose_infeasibility(network: pypsa.Network, *, currency: str = "$") -> dict[str, Any]:
    """Structure-level diagnosis of an infeasible / unbounded model."""
    lines: list[str] = []
    suggestions: list[str] = []
    shortfalls: list[dict[str, Any]] = []
    suspects: list[dict[str, Any]] = []

    snapshots = list(network.snapshots)
    T = len(snapshots)
    load = _load_by_snapshot(network)
    gens = network.generators

    # ── 1. Suspect placeholder coefficients ─────────────────────────────────
    # e_sum_min at a huge positive value forces impossible throughput;
    # p_nom_max/e_nom_max/cost at (non-default) inf or >= 1e12 make the LP
    # unbounded or ill-conditioned. Per-column default awareness lives in
    # _is_suspect_value — PyPSA's own ±inf defaults are never flagged.
    scan = [
        ("generators", gens, ["p_nom_max", "e_sum_min", "e_sum_max", "capital_cost", "marginal_cost"]),
        ("storage_units", network.storage_units, ["p_nom_max", "e_sum_min", "e_sum_max", "capital_cost"]),
        ("stores", network.stores, ["e_nom_max", "e_sum_min", "e_sum_max"]),
    ]
    for sheet, df, cols in scan:
        for col in cols:
            if col not in getattr(df, "columns", []):
                continue
            for name, val in df[col].items():
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                if _is_suspect_value(col, v):
                    suspects.append({"sheet": sheet, "name": str(name), "attr": col, "value": v})

    if suspects:
        lines.append(
            f"{len(suspects)} placeholder/extreme coefficient(s) found (inf or ≥1e12) — "
            "these make the LP unbounded or ill-conditioned."
        )
        suggestions.append(
            "Replace inf / 1e12 placeholders in p_nom_max, e_sum_min/max, lifetime "
            "and cost columns with finite values (or leave them unset)."
        )

    # ── 2. Copper-plate capacity adequacy ───────────────────────────────────
    unlimited = _has_load_shedding(network)
    pmax = network.get_switchable_as_dense("Generator", "p_max_pu") if len(gens) else pd.DataFrame()
    ext = gens.get("p_nom_extendable", pd.Series(False, index=gens.index))
    available = np.zeros(T)
    for g in gens.index:
        if str(g).startswith("load_shedding"):
            unlimited = True
            continue
        if bool(ext.get(g, False)):
            cap = float(gens.at[g, "p_nom_max"]) if "p_nom_max" in gens.columns else float("inf")
            if np.isinf(cap) or cap >= _BIG:
                unlimited = True  # can build without bound → capacity is not the cause
                continue
        else:
            cap = float(gens.at[g, "p_nom"])
        col = pmax[g].to_numpy() if g in getattr(pmax, "columns", []) else np.ones(T)
        available += cap * col
    # Storage discharge + firm store capacity add headroom (rough, copper-plate).
    for s in network.storage_units.index:
        available += float(network.storage_units.at[s, "p_nom"])

    if not unlimited and T:
        deficit = load - available
        for i in np.argsort(-deficit)[:5]:
            if deficit[i] > 1e-6:
                shortfalls.append({
                    "snapshot": str(snapshots[i]), "loadMW": round(float(load[i]), 2),
                    "availableMW": round(float(available[i]), 2),
                    "deficitMW": round(float(deficit[i]), 2),
                })
        if shortfalls:
            worst = shortfalls[0]
            lines.append(
                f"Capacity shortfall: at {worst['snapshot']} load is "
                f"{worst['loadMW']:,.0f} MW but only {worst['availableMW']:,.0f} MW "
                f"of generation is available ({worst['deficitMW']:,.0f} MW short). "
                f"No combination of the bounded capacity can serve this."
            )
            suggestions.append(
                "Enable load shedding (Settings → adds an unserved-energy backstop "
                "so the model stays feasible and shows where it falls short)."
            )
            suggestions.append(
                "Or add capacity / make a generator extendable, or reduce the peak load."
            )

    # ── 3. Annual e_sum_max budgets starved by window scaling ───────────────
    # build_network treats e_sum_max/e_sum_min as ANNUAL budgets and scales
    # them onto the modelled window (× Σw/8760, see _period_factor). The
    # network here already carries the scaled value, so a generous-looking
    # annual cap can be a sliver of the window's load energy — an energy
    # starvation the power-based copper-plate check above cannot see.
    starved: list[dict[str, Any]] = []
    factor = _period_factor(network)
    weights = network.snapshot_weightings["objective"].to_numpy()
    window_hours = float(weights.sum())
    window_load_mwh = float((load * weights).sum())
    if factor < 1.0 and window_load_mwh > 0 and "e_sum_max" in gens.columns:
        for g in gens.index:
            if str(g).startswith("load_shedding"):
                continue
            try:
                budget = float(gens.at[g, "e_sum_max"])  # already window-scaled
            except (TypeError, ValueError):
                continue
            if not np.isfinite(budget) or budget >= _BIG or budget < 0:
                continue
            # (b) energy the generator could deliver were only capacity binding:
            # p_nom (or p_nom_max when extendable) × Σ w·p_max_pu.
            if bool(ext.get(g, False)):
                cap = float(gens.at[g, "p_nom_max"]) if "p_nom_max" in gens.columns else float("inf")
            else:
                cap = float(gens.at[g, "p_nom"])
            profile = pmax[g].to_numpy() if g in getattr(pmax, "columns", []) else np.ones(T)
            potential_mwh = cap * float((profile * weights).sum())
            if (budget < _STARVED_BUDGET_FRACTION * window_load_mwh
                    and budget < _STARVED_BUDGET_FRACTION * potential_mwh):
                starved.append({
                    "name": str(g),
                    "annualBudgetMWh": round(budget / factor, 2),
                    "scaledBudgetMWh": round(budget, 2),
                    "windowHours": round(window_hours, 2),
                    "windowLoadMWh": round(window_load_mwh, 2),
                    "shareOfWindowLoad": round(budget / window_load_mwh, 4),
                })
        for st in starved:
            lines.append(
                f"{st['name']}: e_sum_max {st['annualBudgetMWh']:g}/yr scales to "
                f"{st['scaledBudgetMWh']:g} MWh over this {st['windowHours']:g} h window "
                f"({st['shareOfWindowLoad']:.1%} of window load energy) — likely "
                f"starving supply; e_sum_max is an ANNUAL budget."
            )
        if starved:
            suggestions.append(
                "e_sum_max / e_sum_min are annual energy budgets, scaled by "
                "window_hours / 8760 at build time. If the number was meant for "
                "this window, multiply it by 8760 / window_hours — otherwise "
                "raise or clear it."
            )

    # ── 4. Binding global constraints ───────────────────────────────────────
    gc = network.global_constraints
    if len(gc):
        for name in gc.index:
            sense = str(gc.at[name, "sense"]) if "sense" in gc.columns else ""
            const = float(gc.at[name, "constant"]) if "constant" in gc.columns else float("nan")
            gc_type = str(gc.at[name, "type"]) if "type" in gc.columns else ""
            lines.append(
                f"Global constraint '{name}' ({gc_type} {sense} {const:g}) is active — "
                "if it caps the only capacity able to serve load it can force infeasibility."
            )
        suggestions.append(
            "If a CO₂ / energy global constraint is binding, relax its limit or add "
            "low-carbon capacity that can meet it."
        )

    if not lines:
        lines.append(
            "No structural cause found from the inputs (capacity looks adequate and no "
            "extreme coefficients). The infeasibility may come from transmission limits, "
            "unit-commitment minimums, or cyclic storage constraints."
        )

    headline = (
        shortfalls and f"Capacity shortfall of {shortfalls[0]['deficitMW']:,.0f} MW at peak"
        or suspects and f"{len(suspects)} extreme coefficient(s)"
        or starved and f"{len(starved)} generator(s) starved by annual e_sum_max window scaling"
        or "No single structural cause identified"
    )
    return {
        "headline": headline,
        "lines": lines,
        "shortfalls": shortfalls,
        "suspects": suspects,
        "starvedBudgets": starved,
        "suggestions": suggestions,
        "loadSheddingEnabled": _has_load_shedding(network),
    }


def diagnosis_text(diag: dict[str, Any]) -> str:
    """One-string rendering for a solver error message."""
    parts = ["  • " + ln for ln in diag["lines"]]
    if diag["suggestions"]:
        parts.append("Suggested fixes:")
        parts.extend("  → " + s for s in diag["suggestions"])
    return "\n".join(parts)
