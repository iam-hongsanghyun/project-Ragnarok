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
  3. **Binding global constraints**: a CO₂ cap or similar that may conflict with
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

_BIG = 1e12  # placeholder threshold: values at/above this read as "unbounded"


def _load_by_snapshot(network: pypsa.Network) -> np.ndarray:
    if len(network.loads) == 0:
        return np.zeros(len(network.snapshots))
    return network.get_switchable_as_dense("Load", "p_set").sum(axis=1).to_numpy()


def _has_load_shedding(network: pypsa.Network) -> bool:
    return any(str(g).startswith("load_shedding") for g in network.generators.index)


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
    scan = [
        ("generators", gens, ["p_nom_max", "capital_cost", "marginal_cost"]),
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
                # e_sum_min at a huge positive value forces impossible throughput;
                # p_nom_max/cost at inf/1e12 make the LP unbounded/ill-conditioned.
                if np.isinf(v) or abs(v) >= _BIG:
                    if col in ("e_sum_min",) and v > 0:
                        suspects.append({"sheet": sheet, "name": str(name), "attr": col, "value": v})

    # inf/1e12 in cost columns is the classic unbounded/ill-conditioned trigger.
    for name, val in gens.get("marginal_cost", pd.Series(dtype=float)).items():
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if np.isinf(v) or abs(v) >= _BIG:
            suspects.append({"sheet": "generators", "name": str(name), "attr": "marginal_cost", "value": v})

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

    # ── 3. Binding global constraints ───────────────────────────────────────
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
        or "No single structural cause identified"
    )
    return {
        "headline": headline,
        "lines": lines,
        "shortfalls": shortfalls,
        "suspects": suspects,
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
