"""In-solve operating-reserve (spinning reserve) co-optimization.

Adds a reserve dispatch variable and headroom/requirement constraints to the
linopy model *inside* ``extra_functionality`` — i.e. before the solve, so the
reserve requirement competes with energy dispatch for capacity in the same LP
that clears the market. This is what makes the reserve price a genuine
opportunity cost (the dual of the requirement constraint) rather than a
post-hoc derived number.

Algorithm:
    Decision variable (added to the model, not derived after the solve):
        $$ r_{g,t} \\ge 0 \\quad \\forall g \\in \\text{eligible}, \\; t \\in \\text{snapshots} $$
        ASCII: r[g,t] >= 0, MW of reserve held by generator g at snapshot t.

    Headroom constraint (``reserve_headroom``) — dispatch plus reserve must
    fit under available capacity:
        $$ p_{g,t} + r_{g,t} \\le p_{nom,g} \\cdot pmax_{g,t} \\quad (\\text{fixed } g) $$
        $$ p_{g,t} + r_{g,t} - p_{nom,g}^{var} \\cdot pmax_{g,t} \\le 0 \\quad (\\text{extendable } g) $$
        ASCII: p[g,t] + r[g,t] <= p_nom[g] * p_max_pu[g,t]  (fixed capacity)
               p[g,t] + r[g,t] - p_nom_var[g] * p_max_pu[g,t] <= 0  (extendable)
        Units: p, r in MW; p_nom in MW; p_max_pu dimensionless in [0, 1].

    Requirement constraint (``reserve_requirement``) — the reserve pool must
    cover the configured product at every snapshot:
        $$ \\sum_{g \\in \\text{eligible}} r_{g,t} \\ge R_t \\quad \\forall t $$
        $$ R_t = \\text{fraction} \\cdot \\text{load}_t + \\text{largest\\_unit\\_mw} $$
        ASCII: sum_g r[g,t] >= R_t, R_t = fraction*load_t + largest_unit_mw
        Units: r, R_t, largest_unit_mw in MW; fraction dimensionless; load_t in MW.

    Optional reserve cost term added to the objective (only when
    ``reserveCost > 0`` — the default is 0, in which case the reserve price
    is purely the headroom constraint's shadow cost):
        $$ \\text{extra cost} = \\text{reserveCost} \\cdot \\sum_{g,t} w_t \\cdot r_{g,t} $$
        ASCII: extra_cost = reserveCost * sum_{g,t} weight_t * r[g,t]
        Units: reserveCost in currency/MW; w_t dimensionless (snapshot weight,
        hours); extra_cost in currency.

Eligibility: ``eligible = supply_gens - shed_gens`` (never let the
load-shedding backstop provide reserve), further restricted to
non-variable-renewable carriers when ``providers == "thermal"``.

Reading the solution back (rolling-horizon safe): the variable is named
``Generator-r`` (``<Component>-<attr>`` naming), so PyPSA's own
``assign_solution()`` generically persists it into ``n.generators_t.r`` the
same way it persists ``Generator-p`` — including across rolling-horizon
windows, where each window's ``extra_functionality`` call gets a *fresh*
``n.model`` (linopy rebuilds the model from scratch per window) and therefore
cannot see a prior window's solved ``Generator-r``. ``extract_reserve_results``
reads provision from ``n.generators_t.r`` for this reason, not from
``n.model`` directly.

The reserve price ($/MW-reserve at each snapshot) is the dual of
``reserve_requirement`` — read from ``n.model.constraints["reserve_requirement"].dual``.
Unlike the primal, PyPSA has no persistent per-snapshot dual dataframe, so
after a rolling-horizon run ``n.model`` only reflects the *last* window: the
price series only covers that window's snapshots and a note says so. On
MILP / committable runs (or any solve where linopy has no dual), the price
series comes back empty rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..constants import carrier_color

_log = logging.getLogger("pypsa.solver")

# Carrier-name substrings treated as variable (non-dispatchable) renewables —
# excluded from the reserve pool when providers == "thermal". Matched
# case-insensitively against the generator's carrier label.
_VARIABLE_RENEWABLE_MARKERS = ("solar", "pv", "wind")

_EPS = 1e-6


def _snapshot_label(snapshot: Any) -> str:
    """ISO-format a snapshot, handling multi-investment-period tuples."""
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        _period, timestep = snapshot
        return pd.Timestamp(timestep).isoformat() if not isinstance(timestep, str) else timestep
    try:
        return pd.Timestamp(snapshot).isoformat()
    except Exception:
        return str(snapshot)


def _is_variable_renewable(carrier: str) -> bool:
    key = str(carrier).strip().lower()
    return any(marker in key for marker in _VARIABLE_RENEWABLE_MARKERS)


def _eligible_generators(
    n: pypsa.Network,
    supply_gens: list[str],
    shed_gens: list[str],
    providers: str,
) -> list[str]:
    """Reserve-eligible generators: supply gens minus shed gens, minus
    variable-renewable carriers when ``providers == "thermal"``."""
    shed_set = set(shed_gens)
    eligible = [g for g in supply_gens if g not in shed_set]
    if providers == "thermal":
        carriers = n.generators["carrier"] if "carrier" in n.generators.columns else pd.Series(dtype=str)
        eligible = [g for g in eligible if not _is_variable_renewable(carriers.get(g, ""))]
    return eligible


def _largest_installed_unit(gens: pd.DataFrame, eligible: list[str]) -> float:
    """Largest INSTALLED unit (``p_nom``) among eligible generators — the N-1
    "largest unit" reserve target.

    Keyed to installed capacity (a build-time constant) rather than an
    extendable unit's ``p_nom_max`` (buildable ceiling, which can balloon the
    requirement toward infeasibility) or the post-solve ``p_nom_opt`` (a
    variable, unknown when the constraint is built). Using the same constant in
    the constraint and the reported series guarantees they never diverge; for a
    fixed fleet (``p_nom == p_nom_opt``) it is exact. Expansion beyond ``p_nom``
    is not tracked by the N-1 target in v1.
    """
    if not eligible:
        return 0.0
    p_nom = gens["p_nom"].reindex(eligible).fillna(0.0)
    return float(p_nom.max()) if len(p_nom) else 0.0


def apply_reserve_constraints(
    n: pypsa.Network,
    reserve_cfg: dict[str, Any],
    snapshots: Any,
    notes: list[str],
) -> None:
    """Add the reserve variable + headroom/requirement constraints to ``n.model``.

    Called from ``extra_functionality`` (so ``n.model`` — the linopy Model —
    is available) for every optimize path: single-shot, rolling-horizon
    window, and SCLOPF. ``snapshots`` is the window currently being
    optimised; the reserve requirement is scoped to it exactly like the
    energy balance is.

    Never raises: any failure is caught and reported via ``notes`` so it
    cannot take down the solve.
    """
    if not reserve_cfg or not bool(reserve_cfg.get("enabled")):
        return

    try:
        requirement_type = str(reserve_cfg.get("requirementType", "fraction") or "fraction")
        fraction = float(reserve_cfg.get("fraction", 0.1) if reserve_cfg.get("fraction") is not None else 0.1)
        providers = str(reserve_cfg.get("providers", "all") or "all")
        reserve_cost = float(reserve_cfg.get("reserveCost", 0.0) or 0.0)

        use_fraction = requirement_type in ("fraction", "both")
        use_largest_unit = requirement_type in ("largestUnit", "both")
        if not use_fraction and not use_largest_unit:
            # Spec: at least one of fraction/largestUnit must contribute —
            # default to fraction if the configured type is unrecognised.
            use_fraction = True

        gens = n.generators
        supply_gens = [g for g in gens.index if not str(g).startswith("load_shedding_")]
        shed_gens = [g for g in gens.index if str(g).startswith("load_shedding_")]
        eligible = _eligible_generators(n, supply_gens, shed_gens, providers)

        if not eligible:
            notes.append(
                "Operating reserve: no reserve-eligible generators found — skipped."
            )
            return

        gen_p = n.model["Generator-p"]
        dim = [d for d in gen_p.dims if d != "snapshot"][0]

        # p_max_pu per (snapshot, generator) — get_switchable_as_dense resolves
        # static + time-varying inputs uniformly (every generator gets a
        # column, static default already filled in), same source
        # apply_custom_constraints uses.
        p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu").reindex(
            index=snapshots, columns=eligible
        )

        extendable_col = gens["p_nom_extendable"] if "p_nom_extendable" in gens.columns else pd.Series(False, index=gens.index)
        extendable = [g for g in eligible if bool(extendable_col.get(g, False))]
        fixed = [g for g in eligible if g not in extendable]

        r = n.model.add_variables(
            lower=0,
            coords=[snapshots, eligible],
            dims=["snapshot", dim],
            name="Generator-r",
        )

        # ── Headroom: p + r <= available capacity ───────────────────────────
        if fixed:
            p_nom_fixed = gens.loc[fixed, "p_nom"].fillna(0.0)
            headroom_rhs_fixed = p_max_pu[fixed] * p_nom_fixed
            lhs_fixed = gen_p.sel({dim: fixed}) + r.sel({dim: fixed})
            n.model.add_constraints(
                lhs_fixed <= headroom_rhs_fixed, name="reserve_headroom_fixed"
            )

        if extendable:
            try:
                cap_var = n.model["Generator-p_nom"]
                cap_dim = cap_var.dims[0]
            except Exception:
                cap_var = None
                cap_dim = None
            if cap_var is not None and cap_dim is not None:
                pmax_extendable = p_max_pu[extendable]
                lhs_ext = (
                    gen_p.sel({dim: extendable})
                    + r.sel({dim: extendable})
                    - cap_var.sel({cap_dim: extendable}) * pmax_extendable
                )
                n.model.add_constraints(lhs_ext <= 0, name="reserve_headroom_extendable")
            else:
                # No extendable capacity variable available (shouldn't happen
                # if p_nom_extendable is set) — fall back to the static p_nom
                # so the constraint still bounds reserve provision.
                p_nom_ext_static = gens.loc[extendable, "p_nom"].fillna(0.0)
                headroom_rhs_ext = p_max_pu[extendable] * p_nom_ext_static
                lhs_ext = gen_p.sel({dim: extendable}) + r.sel({dim: extendable})
                n.model.add_constraints(
                    lhs_ext <= headroom_rhs_ext, name="reserve_headroom_extendable"
                )

        # ── Requirement: sum_g r[g,t] >= R_t ─────────────────────────────────
        load_dense = n.get_switchable_as_dense("Load", "p_set").reindex(snapshots)
        load_t = load_dense.sum(axis=1).fillna(0.0)

        requirement = pd.Series(0.0, index=snapshots)
        parts: list[str] = []
        if use_fraction:
            requirement = requirement + fraction * load_t
            parts.append(f"{fraction:.1%} of load")
        if use_largest_unit:
            largest_unit_mw = _largest_installed_unit(gens, eligible)
            requirement = requirement + largest_unit_mw
            parts.append(f"largest unit ({largest_unit_mw:.4g} MW)")

        if float(requirement.abs().sum()) <= _EPS:
            notes.append(
                "Operating reserve: requirement evaluates to zero at every "
                "snapshot (no load and no eligible capacity) — reserve "
                "variable added but the requirement constraint is a no-op."
            )

        total_r = r.sum(dim)
        n.model.add_constraints(
            total_r >= requirement, name="reserve_requirement"
        )

        if reserve_cost > 0:
            weights = n.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0)
            n.model.objective.expression = (
                n.model.objective.expression + reserve_cost * (r * weights).sum()
            )

        providers_note = "all supply generators" if providers != "thermal" else "thermal generators only"
        notes.append(
            f"Operating reserve co-optimized: requirement = {' + '.join(parts)}, "
            f"providers = {providers_note} ({len(eligible)} eligible)."
            + (f" Reserve cost {reserve_cost:g}/MW added to the objective." if reserve_cost > 0 else "")
        )
    except Exception as exc:  # never let reserve co-optimization break the solve
        notes.append(f"Operating reserve could not be added: {exc}")


def extract_reserve_results(
    n: pypsa.Network,
    reserve_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Read back the reserve variable, requirement and price after the solve.

    Returns the ``"reserve"`` payload dict (see module docstring / the
    formulation note above for the underlying LP). ``enabled: False`` with a
    ``note`` when reserves were not configured, not added (no eligible
    generators), or the model doesn't expose a ``Generator-r`` variable
    (e.g. the config was toggled off, or the solve failed before reserves
    were built).
    """
    enabled = bool((reserve_cfg or {}).get("enabled"))
    requirement_type = str((reserve_cfg or {}).get("requirementType", "fraction") or "fraction")

    base: dict[str, Any] = {
        "enabled": False,
        "requirementType": requirement_type,
        "requirementMwSeries": [],
        "providedMwSeries": [],
        "priceSeries": [],
        "byCarrier": [],
        "byGenerator": [],
        "summary": [],
        "scarcityHours": 0,
        "note": None,
    }
    if not enabled:
        return base

    try:
        # Provision is read from n.generators_t.r, not n.model directly: the
        # variable is named "Generator-r" ("<Component>-<attr>"), so PyPSA's
        # assign_solution() generically persists it there — the same
        # mechanism that persists Generator-p — and unlike n.model it survives
        # across rolling-horizon windows (each window rebuilds n.model from
        # scratch, so a later window's extra_functionality call never sees an
        # earlier window's solved Generator-r).
        r_t = getattr(n.generators_t, "r", None)
        if r_t is None or r_t.empty:
            base["note"] = "Operating reserve was enabled but not added to the solve (see run notes)."
            return base

        snapshots = n.snapshots
        labels = [_snapshot_label(s) for s in snapshots]
        gen_names = [str(g) for g in r_t.columns if g in n.generators.index]
        provided = r_t.reindex(index=snapshots, columns=gen_names).fillna(0.0)
        provided_total = provided.sum(axis=1)

        # ── Requirement series (recompute the RHS the same way it was built) ──
        cfg = reserve_cfg or {}
        fraction = float(cfg.get("fraction", 0.1) if cfg.get("fraction") is not None else 0.1)
        providers = str(cfg.get("providers", "all") or "all")
        use_fraction = requirement_type in ("fraction", "both")
        use_largest_unit = requirement_type in ("largestUnit", "both")
        if not use_fraction and not use_largest_unit:
            use_fraction = True

        gens = n.generators
        supply_gens = [g for g in gens.index if not str(g).startswith("load_shedding_")]
        shed_gens = [g for g in gens.index if str(g).startswith("load_shedding_")]
        eligible = _eligible_generators(n, supply_gens, shed_gens, providers)

        load_dense = n.get_switchable_as_dense("Load", "p_set").reindex(snapshots)
        load_t = load_dense.sum(axis=1).fillna(0.0)
        requirement = pd.Series(0.0, index=snapshots)
        if use_fraction:
            requirement = requirement + fraction * load_t
        if use_largest_unit and eligible:
            # Same build-time constant the constraint enforced (installed p_nom),
            # so the displayed requirement never diverges from what the LP used.
            requirement = requirement + _largest_installed_unit(gens, eligible)

        requirement_mw_series = [
            {"label": lbl, "value": float(requirement.iloc[i])} for i, lbl in enumerate(labels)
        ]
        provided_mw_series = [
            {"label": lbl, "value": float(provided_total.iloc[i])} for i, lbl in enumerate(labels)
        ]

        # ── Price: dual of the requirement constraint ───────────────────────
        # n.model only reflects the LAST solved window (rolling horizon
        # rebuilds it from scratch every window, and each window's
        # extra_functionality call cannot see a prior window's constraints) —
        # the dual therefore only ever covers, at most, the snapshots of the
        # most recent solve. Align by position via get_indexer so a partial
        # (rolling-horizon) dual still lands on the right snapshots instead of
        # silently misaligning.
        price_by_position: dict[int, float] = {}
        try:
            model = n.model
            if model is not None and "reserve_requirement" in model.constraints:
                dual = model.constraints["reserve_requirement"].dual
                dual_snapshots = dual.coords["snapshot"].values
                dual_values = dual.values
                positions = snapshots.get_indexer(dual_snapshots)
                for pos, val in zip(positions, dual_values):
                    if pos >= 0 and not np.isnan(val):
                        price_by_position[int(pos)] = float(val)
        except Exception:
            price_by_position = {}

        dual_partial = 0 < len(price_by_position) < len(snapshots)
        price_series = [
            {"label": labels[i], "value": price_by_position[i]}
            for i in sorted(price_by_position)
        ]
        price_values: np.ndarray | None = (
            np.array([price_by_position.get(i, np.nan) for i in range(len(snapshots))])
            if price_by_position
            else None
        )

        # ── Per-carrier / per-generator aggregates ──────────────────────────
        carriers = gens["carrier"].reindex(gen_names).fillna("")
        by_carrier_mw: dict[str, float] = {}
        for g in gen_names:
            c = str(carriers.get(g, ""))
            by_carrier_mw[c] = by_carrier_mw.get(c, 0.0) + float(provided[g].mean())
        by_carrier = [
            {"label": c, "value": v, "color": carrier_color(n, c)}
            for c, v in sorted(by_carrier_mw.items(), key=lambda kv: kv[1], reverse=True)
            if v > 0.0
        ]

        mean_price = float(np.nanmean(price_values)) if price_values is not None and len(price_values) else 0.0
        by_generator = []
        for g in gen_names:
            mean_r = float(provided[g].mean())
            if mean_r <= 0.0:
                continue
            weights = n.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0)
            revenue = 0.0
            if price_values is not None:
                revenue = float((provided[g].to_numpy() * np.nan_to_num(price_values) * weights.to_numpy()).sum())
            by_generator.append(
                {
                    "name": g,
                    "carrier": str(carriers.get(g, "")),
                    "meanReserveMw": mean_r,
                    "meanReservePriceRevenue": revenue,
                }
            )
        by_generator.sort(key=lambda row: row["meanReserveMw"], reverse=True)

        eps = 1e-6
        scarcity_hours = (
            int(np.sum(np.nan_to_num(price_values) > eps)) if price_values is not None else 0
        )

        mean_requirement = float(requirement.mean()) if len(requirement) else 0.0
        mean_provided = float(provided_total.mean()) if len(provided_total) else 0.0
        summary = [
            {
                "label": "Mean reserve requirement",
                "value": f"{mean_requirement:,.1f} MW",
                "detail": f"requirement type: {requirement_type}",
            },
            {
                "label": "Mean reserve provided",
                "value": f"{mean_provided:,.1f} MW",
                "detail": f"{len(eligible)} eligible generator(s)",
            },
            {
                "label": "Mean reserve price",
                "value": f"{mean_price:,.4f} /MW",
                "detail": "dual of the reserve_requirement constraint",
            },
            {
                "label": "Scarcity hours",
                "value": f"{scarcity_hours} of {len(snapshots)}",
                "detail": "snapshots where the reserve requirement is binding",
            },
        ]

        note = None
        if price_values is None:
            note = (
                "Reserve price unavailable: this run has no linopy dual for "
                "reserve_requirement (typical for MILP/committable solves). "
                "Provision (MW) is still reported."
            )
        elif dual_partial:
            note = (
                "Reserve price only covers the last solved window "
                f"({len(price_by_position)} of {len(snapshots)} snapshots) — "
                "rolling horizon rebuilds the linopy model per window, so an "
                "earlier window's dual is not retained. Provision (MW) covers "
                "the full horizon."
            )

        return {
            "enabled": True,
            "requirementType": requirement_type,
            "requirementMwSeries": requirement_mw_series,
            "providedMwSeries": provided_mw_series,
            "priceSeries": price_series,
            "byCarrier": by_carrier,
            "byGenerator": by_generator,
            "summary": summary,
            "scarcityHours": scarcity_hours,
            "note": note,
        }
    except Exception as exc:
        base["note"] = f"Operating reserve results could not be extracted: {exc}"
        _log.warning("reserve extraction failed: %s", exc)
        return base
