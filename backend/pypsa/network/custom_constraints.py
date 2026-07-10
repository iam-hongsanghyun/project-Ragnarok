from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pypsa

from ..utils.emissions import per_generator_emission_factor


@dataclass
class ModelContext:
    """Shared linopy building blocks for custom + DSL constraints.

    Built once per solve (or once per rolling-horizon *window*) from the
    assembled network so both the structured custom-constraint path and the
    free-text DSL compile against the same variables and weights.

    ``weights`` / ``modeled_hours`` are scoped to the snapshots currently being
    optimised — i.e. the rolling-horizon window, not the full horizon — so the
    dispatch variable (``gen_p``, which PyPSA builds over the window) and the
    RHS use the *same* time span. ``full_horizon_hours`` keeps the whole-run
    span so absolute (MWh) budgets can be apportioned to the window.
    """

    network: pypsa.Network
    gen_p: Any
    dim: str
    weights: Any
    supply_gens: list[str]
    shed_gens: list[str]
    modeled_hours: float
    full_horizon_hours: float
    cap_var: Any | None
    cap_dim: str | None
    emissions_factors: dict[str, float]

    @property
    def window_fraction(self) -> float:
        """Window hours ÷ full-horizon hours (1.0 outside rolling horizon)."""
        if self.full_horizon_hours <= 0:
            return 1.0
        return self.modeled_hours / self.full_horizon_hours


def build_model_context(
    n: pypsa.Network,
    emissions_factors: dict[str, float],
    snapshots: Any | None = None,
) -> ModelContext:
    """Capture the reusable locals needed to express constraints on ``n.model``.

    Args:
        snapshots: the snapshots currently being optimised (the rolling-horizon
            window). When given, weights/hours are restricted to it so the RHS
            matches ``gen_p``'s time span. ``None`` ⇒ the full horizon.
    """
    gen_p = n.model["Generator-p"]
    # PyPSA/linopy uses 'name' as the generator dimension, not 'Generator'
    dim = [d for d in gen_p.dims if d != "snapshot"][0]
    full_weights = n.snapshot_weightings["generators"]
    weights = full_weights
    if snapshots is not None:
        try:
            weights = full_weights.loc[snapshots]
        except Exception:
            weights = full_weights
    supply_gens = [g for g in n.generators.index if not g.startswith("load_shedding_")]
    shed_gens = [g for g in n.generators.index if g.startswith("load_shedding_")]
    modeled_hours = float(weights.sum())
    full_horizon_hours = float(full_weights.sum())
    try:
        cap_var = n.model["Generator-p_nom"]
        cap_dim = cap_var.dims[0]
    except Exception:
        cap_var = None
        cap_dim = None
    return ModelContext(
        network=n,
        gen_p=gen_p,
        dim=dim,
        weights=weights,
        supply_gens=supply_gens,
        shed_gens=shed_gens,
        modeled_hours=modeled_hours,
        full_horizon_hours=full_horizon_hours,
        cap_var=cap_var,
        cap_dim=cap_dim,
        emissions_factors=emissions_factors,
    )


def _carrier_capacity_expr(
    n: pypsa.Network,
    gens: list[str],
    cap_var: Any | None,
    cap_dim: str | None,
) -> Any:
    """Total nameplate capacity (MW) of ``gens`` as a linopy term or float.

    Fixed generators contribute their static ``p_nom``; extendable ones
    contribute the optimisation variable ``Generator-p_nom`` when it exists
    (single-shot expansion), otherwise their static ``p_nom``. Returns a linopy
    expression when at least one generator is extendable *and* the capacity
    variable exists, and a plain ``float`` otherwise — capacity is a stock, so
    (unlike energy) it carries no snapshot weighting. Callers must handle both:
    a float means the capacity is fully determined by the data, so a constraint
    on it has no decision variable to bind.

    Algorithm:
        $$C_\\mathrm{carrier} = \\sum_{g\\in\\mathrm{fixed}} p^{nom}_g
          + \\sum_{g\\in\\mathrm{ext}} P^{nom}_g$$
        ASCII: C = sum(p_nom[fixed]) + sum(P_nom_var[extendable])
        where p_nom is the fixed nameplate (MW) and P_nom_var is the
        extendable-capacity decision variable (MW).
    """
    extendable = [
        g for g in gens
        if "p_nom_extendable" in n.generators.columns
        and bool(n.generators.at[g, "p_nom_extendable"])
    ]
    fixed = [g for g in gens if g not in extendable]
    total: Any = float(n.generators.loc[fixed, "p_nom"].fillna(0.0).sum())
    if extendable and cap_var is not None and cap_dim is not None:
        total = total + cap_var.sel({cap_dim: extendable}).sum()
    elif extendable:
        total = total + float(n.generators.loc[extendable, "p_nom"].fillna(0.0).sum())
    return total


def apply_custom_constraints(
    n: pypsa.Network,
    constraints: list[dict[str, Any]],
    emissions_factors: dict[str, float],
    notes: list[str],
    snapshots: Any | None = None,
) -> None:
    """Apply all enabled custom constraints to the linopy model.

    Called inside extra_functionality, so n.model is available. ``snapshots`` is
    the window being optimised (rolling horizon) — weights/hours are scoped to
    it, and absolute (MWh) budgets are apportioned by the window's hour-share so
    a whole-run cap isn't applied in full to every window.

    Silently skips any constraint that fails (logs a note instead).
    """
    if not constraints:
        return

    ctx = build_model_context(n, emissions_factors, snapshots)
    gen_p = ctx.gen_p
    dim = ctx.dim
    weights = ctx.weights
    supply_gens = ctx.supply_gens
    shed_gens = ctx.shed_gens
    modeled_hours = ctx.modeled_hours
    cap_var = ctx.cap_var
    cap_dim = ctx.cap_dim

    for i, c in enumerate(constraints):
        if not c.get("enabled", False):
            continue

        metric: str = c.get("metric", "")
        value: float = float(c.get("value", 0))
        carrier: str = c.get("carrier", "")
        label: str = c.get("label", metric)
        cname = f"cc_{i}_{metric}"

        try:
            # ── CO₂ emission intensity cap (tCO₂/MWh) ───────────────────────
            # Constraint: Σ(co2_factor_g × dispatch_g) ≤ value × Σ(dispatch_g)
            # where the sum runs over all non-shedding generators. The UI
            # value is in tCO₂/MWh — the same unit PyPSA stores in
            # carriers.co2_emissions, so no conversion is needed.
            if metric == "co2_cap":
                value_tco2 = value
                # Per-generator co2_emissions / η (thermal basis, M3): the cap is
                # on emissions per MWh_electrical delivered, so a lower-efficiency
                # emitter counts more against it.
                eff_ef = per_generator_emission_factor(n, emissions_factors)
                emitters = [
                    (g, float(eff_ef.get(g, 0.0))) for g in n.generators.index
                ]
                emitters = [(g, co2) for g, co2 in emitters if co2 > 0]
                if not emitters:
                    notes.append(f"Constraint '{label}': no CO₂-emitting generators found — skipped.")
                    continue
                if not supply_gens:
                    notes.append(f"Constraint '{label}': no supply generators found — skipped.")
                    continue
                total_emissions = sum(
                    co2 * (gen_p.sel({dim: [g]}) * weights).sum()
                    for g, co2 in emitters
                )
                total_dispatch = (gen_p.sel({dim: supply_gens}) * weights).sum()
                # total_emissions [tCO₂] ≤ value_tco2 [tCO₂/MWh] × total_dispatch [MWh]
                n.model.add_constraints(
                    total_emissions - value_tco2 * total_dispatch <= 0, name=cname
                )
                notes.append(f"Constraint '{label}': CO₂ intensity ≤ {value} tCO₂/MWh added.")

            # ── Maximum load shedding ────────────────────────────────────────
            elif metric == "max_load_shed":
                if not shed_gens:
                    notes.append(f"Constraint '{label}': no load-shedding generators — skipped.")
                    continue
                total_shed = (gen_p.sel({dim: shed_gens}) * weights).sum()
                cap_value = value * ctx.window_fraction
                n.model.add_constraints(total_shed <= cap_value, name=cname)
                msg = f"Constraint '{label}': load shedding ≤ {value} MWh added."
                if ctx.window_fraction < 1.0:
                    msg += f" (apportioned to {cap_value:.4g} MWh for this rolling-horizon window)"
                notes.append(msg)

            # ── Carrier generation cap / floor (MWh) ─────────────────────────
            elif metric in ("carrier_max_gen", "carrier_min_gen"):
                cgens = n.generators.index[n.generators.carrier == carrier].tolist()
                if not cgens:
                    notes.append(f"Constraint '{label}': no generators with carrier '{carrier}' — skipped.")
                    continue
                total = (gen_p.sel({dim: cgens}) * weights).sum()
                budget = value * ctx.window_fraction
                window_note = (
                    f" (apportioned to {budget:.4g} MWh for this rolling-horizon window)"
                    if ctx.window_fraction < 1.0 else ""
                )
                if metric == "carrier_max_gen":
                    n.model.add_constraints(total <= budget, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} generation ≤ {value} MWh added.{window_note}")
                else:
                    n.model.add_constraints(total >= budget, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} generation ≥ {value} MWh added.{window_note}")

            # ── Carrier dispatch share cap / floor (%) ───────────────────────
            elif metric in ("carrier_max_share", "carrier_min_share"):
                cgens = n.generators.index[n.generators.carrier == carrier].tolist()
                if not cgens or not supply_gens:
                    notes.append(f"Constraint '{label}': carrier '{carrier}' or supply gens missing — skipped.")
                    continue
                carrier_total = (gen_p.sel({dim: cgens}) * weights).sum()
                all_total = (gen_p.sel({dim: supply_gens}) * weights).sum()
                frac = value / 100.0
                if metric == "carrier_max_share":
                    n.model.add_constraints(
                        carrier_total - frac * all_total <= 0, name=cname
                    )
                    notes.append(f"Constraint '{label}': {carrier} share ≤ {value}% added.")
                else:
                    n.model.add_constraints(
                        carrier_total - frac * all_total >= 0, name=cname
                    )
                    notes.append(f"Constraint '{label}': {carrier} share ≥ {value}% added.")

            # ── Carrier weighted-average capacity factor cap / floor (%) ─────
            elif metric in ("carrier_max_cf", "carrier_min_cf"):
                cgens = n.generators.index[n.generators.carrier == carrier].tolist()
                if not cgens:
                    notes.append(f"Constraint '{label}': no generators with carrier '{carrier}' — skipped.")
                    continue
                if modeled_hours <= 0:
                    notes.append(f"Constraint '{label}': modeled hours are zero — skipped.")
                    continue

                carrier_total = (gen_p.sel({dim: cgens}) * weights).sum()
                capacity_total = _carrier_capacity_expr(n, cgens, cap_var, cap_dim)

                frac = value / 100.0
                rhs = frac * capacity_total * modeled_hours
                if metric == "carrier_max_cf":
                    n.model.add_constraints(carrier_total <= rhs, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity factor ≤ {value}% added.")
                else:
                    n.model.add_constraints(carrier_total >= rhs, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity factor ≥ {value}% added.")

            # ── Carrier total capacity cap / floor (MW) ──────────────────────
            # Constraint on the carrier's total nameplate capacity (fixed p_nom
            # plus any extendable capacity variable). Capacity is a stock (MW),
            # so there is no snapshot weighting and no rolling-horizon
            # apportioning. If the carrier has no extendable capacity the LHS is
            # a pure constant (no decision variable) and the constraint is
            # skipped with a note rather than added as an infeasible literal.
            elif metric in ("carrier_max_cap", "carrier_min_cap"):
                cgens = n.generators.index[n.generators.carrier == carrier].tolist()
                if not cgens:
                    notes.append(f"Constraint '{label}': no generators with carrier '{carrier}' — skipped.")
                    continue
                cap = _carrier_capacity_expr(n, cgens, cap_var, cap_dim)
                if isinstance(cap, (int, float)):
                    notes.append(
                        f"Constraint '{label}': carrier '{carrier}' has no extendable capacity "
                        f"(fixed at {float(cap):.4g} MW) — nothing to optimise, skipped."
                    )
                    continue
                if metric == "carrier_max_cap":
                    n.model.add_constraints(cap <= value, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity ≤ {value} MW added.")
                else:
                    n.model.add_constraints(cap >= value, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity ≥ {value} MW added.")

            # ── Carrier capacity share cap / floor (% of total MW) ───────────
            # Share of the carrier's capacity in the fleet's total capacity:
            #   carrier_cap − (value/100)·total_cap  {≤,≥}  0
            # total_cap includes the carrier itself, matching the dispatch-share
            # convention above. Skipped (no decision variable) if all capacity in
            # the ratio is fixed.
            elif metric in ("carrier_max_cap_share", "carrier_min_cap_share"):
                cgens = n.generators.index[n.generators.carrier == carrier].tolist()
                if not cgens or not supply_gens:
                    notes.append(f"Constraint '{label}': carrier '{carrier}' or supply gens missing — skipped.")
                    continue
                carrier_cap = _carrier_capacity_expr(n, cgens, cap_var, cap_dim)
                total_cap = _carrier_capacity_expr(n, supply_gens, cap_var, cap_dim)
                frac = value / 100.0
                combined = carrier_cap - frac * total_cap
                if isinstance(combined, (int, float)):
                    notes.append(
                        f"Constraint '{label}': capacity share for '{carrier}' has no extendable "
                        f"capacity (all fixed) — nothing to optimise, skipped."
                    )
                    continue
                if metric == "carrier_max_cap_share":
                    n.model.add_constraints(combined <= 0, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity share ≤ {value}% added.")
                else:
                    n.model.add_constraints(combined >= 0, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity share ≥ {value}% added.")

            else:
                notes.append(f"Constraint '{label}': unknown metric '{metric}' — skipped.")

        except Exception as exc:
            notes.append(f"Constraint '{label}' could not be added: {exc}")
