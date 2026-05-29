from __future__ import annotations

from typing import Any

import pypsa


def apply_custom_constraints(
    n: pypsa.Network,
    constraints: list[dict[str, Any]],
    emissions_factors: dict[str, float],
    notes: list[str],
) -> None:
    """Apply all enabled custom constraints to the linopy model.

    Called inside extra_functionality, so n.model is available.
    Silently skips any constraint that fails (logs a note instead).
    """
    if not constraints:
        return

    gen_p = n.model["Generator-p"]
    # PyPSA/linopy uses 'name' as the generator dimension, not 'Generator'
    dim = [d for d in gen_p.dims if d != "snapshot"][0]
    weights = n.snapshot_weightings["generators"]

    # Pre-build generator index sets used repeatedly
    supply_gens = [
        g for g in n.generators.index
        if not g.startswith("load_shedding_")
    ]
    shed_gens = [g for g in n.generators.index if g.startswith("load_shedding_")]
    modeled_hours = float(weights.sum())

    cap_var = None
    cap_dim = None
    try:
        cap_var = n.model["Generator-p_nom"]
        cap_dim = cap_var.dims[0]
    except Exception:
        cap_var = None
        cap_dim = None

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
            # where the sum runs over all non-shedding generators.
            if metric == "co2_cap":
                # value is in kg CO₂e/MWh; emissions_factors are in tCO₂/MWh
                # Convert: value_tco2 = value_kg / 1000
                value_tco2 = value / 1000.0
                emitters = [
                    (g, emissions_factors.get(n.generators.at[g, "carrier"], 0.0))
                    for g in n.generators.index
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
                notes.append(f"Constraint '{label}': CO₂ intensity ≤ {value} kg CO₂e/MWh added.")

            # ── Maximum load shedding ────────────────────────────────────────
            elif metric == "max_load_shed":
                if not shed_gens:
                    notes.append(f"Constraint '{label}': no load-shedding generators — skipped.")
                    continue
                total_shed = (gen_p.sel({dim: shed_gens}) * weights).sum()
                n.model.add_constraints(total_shed <= value, name=cname)
                notes.append(f"Constraint '{label}': load shedding ≤ {value} MWh added.")

            # ── Carrier generation cap / floor (MWh) ─────────────────────────
            elif metric in ("carrier_max_gen", "carrier_min_gen"):
                cgens = n.generators.index[n.generators.carrier == carrier].tolist()
                if not cgens:
                    notes.append(f"Constraint '{label}': no generators with carrier '{carrier}' — skipped.")
                    continue
                total = (gen_p.sel({dim: cgens}) * weights).sum()
                if metric == "carrier_max_gen":
                    n.model.add_constraints(total <= value, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} generation ≤ {value} MWh added.")
                else:
                    n.model.add_constraints(total >= value, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} generation ≥ {value} MWh added.")

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
                extendable = [
                    g for g in cgens
                    if "p_nom_extendable" in n.generators.columns and bool(n.generators.at[g, "p_nom_extendable"])
                ]
                fixed = [g for g in cgens if g not in extendable]
                fixed_capacity = float(
                    n.generators.loc[fixed, "p_nom"].fillna(0.0).sum()
                )

                capacity_total = fixed_capacity
                if extendable and cap_var is not None and cap_dim is not None:
                    capacity_total = capacity_total + cap_var.sel({cap_dim: extendable}).sum()
                elif extendable:
                    capacity_total = capacity_total + float(
                        n.generators.loc[extendable, "p_nom"].fillna(0.0).sum()
                    )

                frac = value / 100.0
                rhs = frac * capacity_total * modeled_hours
                if metric == "carrier_max_cf":
                    n.model.add_constraints(carrier_total <= rhs, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity factor ≤ {value}% added.")
                else:
                    n.model.add_constraints(carrier_total >= rhs, name=cname)
                    notes.append(f"Constraint '{label}': {carrier} capacity factor ≥ {value}% added.")

            else:
                notes.append(f"Constraint '{label}': unknown metric '{metric}' — skipped.")

        except Exception as exc:
            notes.append(f"Constraint '{label}' could not be added: {exc}")
