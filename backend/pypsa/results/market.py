"""Market analysis helpers — merit order and CO₂ shadow price.

Both are pure post-processing on the solved network; no extra LP solve needed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..constants import carrier_color, generator_color
from ..utils.series import weighted_sum

# System generators (reliability backstops, not merchant assets) — excluded from
# the supply stack and the profit analytics by name prefix.
SYSTEM_GEN_PREFIXES = ("load_shedding_", "system_bess")

# Calendar hours per year. Converts an annualised ``capital_cost`` ($/MW/yr) onto
# the modeled-horizon basis for capex recovery. A unit-conversion constant (not a
# tunable parameter), so it lives in code rather than .env.
HOURS_PER_YEAR = 8760.0


# ── Merit order ───────────────────────────────────────────────────────────────


def build_merit_order(network: pypsa.Network) -> list[dict[str, Any]]:
    """Return the supply-stack (merit order) sorted by marginal cost.

    System generators (load_shedding_*) are excluded — they exist as
    reliability backstops and would distort the supply curve.

    Each dict:
        name          – generator name
        carrier       – carrier string
        bus           – bus name
        marginal_cost – $/MWh
        p_nom         – capacity (MW); p_nom_opt where a solve produced one
                        (>0), else the installed p_nom — an extendable unit on
                        a never-optimised network (market-sim study) keeps its
                        installed capacity instead of vanishing from the stack
        cumulative_mw – left edge of this generator's block on the x-axis
        color         – hex colour for the carrier
    """
    capacity = installed_capacity_series(network.generators)
    rows: list[dict[str, Any]] = []
    for name in network.generators.index:
        if any(name.startswith(pfx) for pfx in SYSTEM_GEN_PREFIXES):
            continue
        gen = network.generators.loc[name]
        p_nom = float(capacity.get(name, 0.0))
        if p_nom <= 0:
            continue
        carrier = str(gen.get("carrier", ""))
        rows.append(
            {
                "name": name,
                "carrier": carrier,
                "bus": str(gen.get("bus", "")),
                "marginal_cost": round(float(gen.get("marginal_cost", 0.0)), 2),
                "p_nom": round(p_nom, 1),
                "color": generator_color(network, name),
            }
        )

    # Sort by marginal cost ascending (merit order)
    rows.sort(key=lambda r: (r["marginal_cost"], r["name"]))

    # Add cumulative MW (x-axis position)
    cumulative = 0.0
    for row in rows:
        row["cumulative_mw"] = round(cumulative, 1)
        cumulative += row["p_nom"]

    return rows


# ── Applied (non-native) constraints ─────────────────────────────────────────

# PyPSA/linopy assembles many internal constraints; anything starting with one
# of these is part of the standard model, not a user/plugin addition.
_NATIVE_CONSTRAINT_PREFIXES = (
    "Generator-",
    "Link-",
    "Line-",
    "Bus-",
    "StorageUnit-",
    "Store-",
    "Transformer-",
    "Kirchhoff",
    "GlobalConstraint-",
    "Carrier-",
)


def build_applied_constraints(network: pypsa.Network) -> list[dict[str, Any]]:
    """List user/plugin linopy constraints actually applied to the model.

    Filters out PyPSA-native constraints by name prefix, leaving the ones added
    by the structured table (``cc_*``), the DSL box (``dsl_*``) and plugins
    (any other name, e.g. ``cf_max_coal``). Read-only — surfaced so the GUI can
    show what was applied, including plugin contributions that are otherwise
    invisible. Each entry: ``{name, source, shadowPrice}``.
    """
    try:
        names = list(network.model.constraints)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for name in names:
        if name.startswith(_NATIVE_CONSTRAINT_PREFIXES):
            continue
        if name.startswith("cc_"):
            source = "custom"
        elif name.startswith("dsl_") or name.startswith("spec_"):
            source = "dsl"
        else:
            source = "plugin"
        out.append(
            {"name": name, "source": source, "shadowPrice": _linopy_dual(network, name)}
        )
    return out


# ── CO₂ shadow price ─────────────────────────────────────────────────────────


def _linopy_dual(network: pypsa.Network, cname: str) -> float:
    """Extract the dual variable of a linopy constraint by name.

    Custom constraints added via n.model.add_constraints() live in the linopy
    model, not in network.global_constraints.  PyPSA writes duals back after
    the solve via n.model.constraints[name].dual (a DataArray).
    """
    try:
        model = network.model
        if cname not in model.constraints:
            return 0.0
        dual = model.constraints[cname].dual
        # dual is a DataArray; for a scalar constraint squeeze to a float
        val = float(dual.values.squeeze())
        return val if not (val != val) else 0.0  # guard NaN
    except Exception:
        return 0.0


def build_co2_shadow(
    network: pypsa.Network, carbon_price: float, currency: str = "$"
) -> dict[str, Any]:
    """Return CO₂ shadow price information from the solved network.

    Checks two sources in order:
    1. PyPSA GlobalConstraints (workbook global_constraints sheet)
    2. Custom linopy constraints added via the Constraints panel
       (named cc_<i>_co2_cap by custom_constraints.py)

    The shadow price is the dual variable of the binding CO₂ constraint.
    For the intensity form (tCO₂/MWh): shadow price units are $/tCO₂.

    Returns a dict:
        found           – bool, whether a CO₂ constraint was found
        constraint_name – name of the constraint
        shadow_price    – $/tCO₂ (absolute value of dual)
        explicit_price  – carbon price set in scenario ($/tCO₂)
        cap_value       – constraint RHS value (intensity or budget)
        cap_unit        – unit string for cap_value
        status          – 'binding' | 'slack' | 'none'
        note            – human-readable explanation
    """
    result: dict[str, Any] = {
        "found": False,
        "constraint_name": None,
        "shadow_price": 0.0,
        "explicit_price": round(float(carbon_price), 2),
        "cap_value": None,
        "cap_unit": "kg CO₂e/MWh",
        "status": "none",
        "note": "No CO₂ constraint active in this run.",
    }

    # ── 1. PyPSA GlobalConstraints (workbook sheet) ───────────────────────────
    if not network.global_constraints.empty:
        gc = network.global_constraints
        co2_gc = gc[
            (gc.get("carrier_attribute", "") == "co2_emissions")
            | gc.index.str.contains("co2", case=False)
        ]
        if not co2_gc.empty:
            name = co2_gc.index[0]
            result["found"] = True
            result["constraint_name"] = name
            result["cap_unit"] = "ktCO₂e"

            if "constant" in gc.columns:
                result["cap_value"] = round(float(gc.at[name, "constant"]) / 1000.0, 1)

            mu = 0.0
            if "mu" in gc.columns:
                try:
                    mu = float(gc.at[name, "mu"])
                except (TypeError, ValueError):
                    mu = 0.0

            result["shadow_price"] = round(abs(mu), 4)
            if abs(mu) > 0:
                result["status"] = "binding"
                result["note"] = (
                    f"GlobalConstraint '{name}' is binding. "
                    f"Shadow price = {currency}{abs(mu):.4f}/tCO₂."
                )
            else:
                result["status"] = "slack"
                result["note"] = (
                    f"GlobalConstraint '{name}' exists but is not binding — "
                    f"emissions are below the cap."
                )
            return result

    # ── 2. Custom linopy constraints (scenario constraints panel) ─────────────
    # Named cc_<i>_co2_cap by apply_custom_constraints()
    try:
        model_cnames = list(network.model.constraints)
    except Exception:
        model_cnames = []

    co2_cnames = [n for n in model_cnames if "co2_cap" in n]

    if not co2_cnames:
        return result

    name = co2_cnames[0]
    mu = _linopy_dual(network, name)

    result["found"] = True
    result["constraint_name"] = name
    result["cap_unit"] = "kg CO₂e/MWh"
    result["shadow_price"] = round(abs(mu), 4)

    if abs(mu) > 0:
        result["status"] = "binding"
        result["note"] = (
            f"CO₂ intensity constraint is binding. "
            f"Shadow price = {currency}{abs(mu):.4f}/tCO₂ — relaxing the intensity cap "
            f"by 1 kg CO₂e/MWh would reduce system cost by {currency}{abs(mu) / 1000:.6f} per MWh dispatched."
        )
    else:
        result["status"] = "slack"
        result["note"] = (
            f"CO₂ intensity constraint exists but is not binding — "
            f"actual intensity is below the cap. Shadow price ≈ {currency}0."
        )

    return result


# ── Asset economics (revenue / margin / capex recovery) ───────────────────────


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce to float, mapping None / NaN / non-numeric to ``default``."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if f == f else default  # NaN guard (NaN != NaN)


def installed_capacity_series(df: pd.DataFrame) -> pd.Series:
    """Resolve the effective installed/optimised capacity per component.

    Uses ``p_nom_opt`` where the solve produced one (>0), else falls back to the
    input ``p_nom`` — ``p_nom_opt`` exists with a 0.0 default for non-extendable
    components on some PyPSA versions, so a bare read would zero them out.
    """
    p_nom_in = (
        df["p_nom"].fillna(0.0)
        if "p_nom" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    if "p_nom_opt" in df.columns:
        opt = df["p_nom_opt"].fillna(0.0)
        return opt.where(opt > 0, p_nom_in)
    return p_nom_in


def build_generator_economics(
    network: pypsa.Network, currency: str = "$"
) -> dict[str, Any]:
    """Per-asset revenue, gross margin and capex recovery from a solved network.

    Pure post-processing — reads dispatch, locational marginal prices (LMPs) and
    costs already on the solved network; **no extra solve**. Under the least-cost
    LP the optimal dispatch *is* the perfectly-competitive profit-maximising
    equilibrium (welfare theorem), so these are the **competitive-benchmark**
    economics of each asset. They do **not** model market power — that is the
    deferred strategic adapter (B4).

    Algorithm:
        For asset i at bus b(i), over snapshots t with weights w(t) (represented
        hours), price π_b(t) = LMP dual on the nodal balance ($/MWh), dispatch
        p_i(t) (MW) and effective marginal cost c_i(t) ($/MWh, carbon adder
        folded in by build_network):

        $$ R_i = \\sum_t w(t)\\,\\pi_{b(i)}(t)\\,p_i(t) $$
        $$ M_i = R_i - \\sum_t w(t)\\,c_i(t)\\,p_i(t) $$
        $$ \\text{capture}_i = R_i \\big/ \\sum_t w(t)\\,p_i(t) $$

        The annual fixed cost is K_i = capital_cost_i · p_nom_opt_i ($/yr). To
        compare it with a margin earned over H = Σ_t w(t) hours, pro-rate it onto
        the window (H/8760 years):

        $$ F_i = K_i \\cdot H / 8760, \\qquad \\text{recovery}_i = 100\\,M_i / F_i $$

        ASCII: R = sum_t w*price*p ; M = R - sum_t w*mc*p ;
        capture = R / sum_t w*p ; recovery% = 100 * M / (capital_cost *
        p_nom_opt * H/8760).

    Symbols/units: π, c, capture in {currency}/MWh; p in MW; w, H in h; R, M, F
    in {currency}; capital_cost in {currency}/MW/yr; recovery dimensionless (%).

    The recovery ratio is scale-invariant in H, so a sub-annual window still
    reports a meaningful "did the margin cover the fixed cost?" figure; every
    absolute money column is on the modeled-horizon basis (``fixedCostAnnual`` is
    additionally exposed on the native annual basis). Storage revenue is the net
    arbitrage value (Σ w·π·p, negative while charging). System generators
    (``load_shedding_*``, ``system_bess*``) are excluded as reliability backstops.

    Returns:
        Dict with ``currency``, ``modeledHours``, ``horizonYears``,
        ``generators`` / ``storage`` / ``byCarrier`` (lists, sorted by gross
        margin descending) and ``system`` (totals).
    """
    weights = (
        network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    )
    modeled_hours = float(weights.sum())
    horizon_years = modeled_hours / HOURS_PER_YEAR if HOURS_PER_YEAR > 0 else 0.0

    mp = network.buses_t.marginal_price
    have_prices = not mp.empty
    zero = pd.Series(0.0, index=network.snapshots)

    def price_at(bus: str) -> pd.Series:
        return mp[bus] if (have_prices and bus in mp.columns) else zero

    def recovery_pct(margin: float, fixed_horizon: float) -> float | None:
        return (
            round(100.0 * margin / fixed_horizon, 1) if fixed_horizon > 1e-9 else None
        )

    # ── Generators ────────────────────────────────────────────────────────────
    gens: list[dict[str, Any]] = []
    gen_p = network.generators_t.p
    if not gen_p.empty and len(network.generators):
        mc_dense = network.get_switchable_as_dense("Generator", "marginal_cost")
        p_nom_opt_s = installed_capacity_series(network.generators)
        for name in network.generators.index:
            if any(str(name).startswith(pfx) for pfx in SYSTEM_GEN_PREFIXES):
                continue
            if name not in gen_p.columns:
                continue
            row = network.generators.loc[name]
            bus = str(row.get("bus", ""))
            p = gen_p[name]
            price = price_at(bus)
            mc = mc_dense[name] if name in mc_dense.columns else zero

            energy = weighted_sum(p.clip(lower=0.0), weights)
            p_nom_opt = float(p_nom_opt_s.get(name, 0.0))
            if energy <= 1e-9 and p_nom_opt <= 1e-9:
                continue  # neither dispatched nor built — nothing to report
            revenue = weighted_sum(price * p, weights)
            variable_cost = weighted_sum(mc * p, weights)
            gross_margin = revenue - variable_cost
            fixed_annual = _num(row.get("capital_cost", 0.0)) * p_nom_opt
            fixed_horizon = fixed_annual * horizon_years
            carrier = str(row.get("carrier", ""))
            gens.append(
                {
                    "name": str(name),
                    "carrier": carrier,
                    "bus": bus,
                    "color": generator_color(network, name),
                    "energyMwh": round(energy, 1),
                    "capacityMw": round(p_nom_opt, 1),
                    "revenue": round(revenue),
                    "variableCost": round(variable_cost),
                    "grossMargin": round(gross_margin),
                    "capturePrice": round(revenue / energy, 2)
                    if energy > 1e-9
                    else None,
                    "fixedCostAnnual": round(fixed_annual),
                    "fixedCostHorizon": round(fixed_horizon),
                    "netHorizon": round(gross_margin - fixed_horizon),
                    "recoveryPct": recovery_pct(gross_margin, fixed_horizon),
                }
            )
    gens.sort(key=lambda r: r["grossMargin"], reverse=True)

    # ── Storage units (net arbitrage value) ──────────────────────────────────
    storage: list[dict[str, Any]] = []
    su = network.storage_units
    su_t = getattr(network, "storage_units_t", None)
    if su_t is not None and not su_t.p.empty and len(su):
        try:
            mc_dense_su = network.get_switchable_as_dense(
                "StorageUnit", "marginal_cost"
            )
        except Exception:
            mc_dense_su = pd.DataFrame(0.0, index=network.snapshots, columns=su.index)
        p_nom_opt_su = installed_capacity_series(su)
        for name in su.index:
            if name not in su_t.p.columns:
                continue
            row = su.loc[name]
            bus = str(row.get("bus", ""))
            p = su_t.p[name]  # +discharge, -charge
            price = price_at(bus)
            mc = mc_dense_su[name] if name in mc_dense_su.columns else zero

            discharged = weighted_sum(p.clip(lower=0.0), weights)
            charged = weighted_sum((-p).clip(lower=0.0), weights)
            p_nom_opt = float(p_nom_opt_su.get(name, 0.0))
            if discharged <= 1e-9 and charged <= 1e-9 and p_nom_opt <= 1e-9:
                continue
            revenue = weighted_sum(price * p, weights)  # net of charging spend
            variable_cost = weighted_sum(mc * p.clip(lower=0.0), weights)
            gross_margin = revenue - variable_cost
            fixed_annual = _num(row.get("capital_cost", 0.0)) * p_nom_opt
            fixed_horizon = fixed_annual * horizon_years
            carrier = str(row.get("carrier", ""))
            storage.append(
                {
                    "name": str(name),
                    "carrier": carrier,
                    "bus": bus,
                    "color": carrier_color(network, carrier),
                    "energyDischargedMwh": round(discharged, 1),
                    "energyChargedMwh": round(charged, 1),
                    "capacityMw": round(p_nom_opt, 1),
                    "revenue": round(revenue),
                    "variableCost": round(variable_cost),
                    "grossMargin": round(gross_margin),
                    "fixedCostAnnual": round(fixed_annual),
                    "fixedCostHorizon": round(fixed_horizon),
                    "netHorizon": round(gross_margin - fixed_horizon),
                    "recoveryPct": recovery_pct(gross_margin, fixed_horizon),
                }
            )
    storage.sort(key=lambda r: r["grossMargin"], reverse=True)

    # ── Per-carrier rollup (generators) ───────────────────────────────────────
    agg: dict[str, dict[str, float]] = {}
    for g in gens:
        a = agg.setdefault(
            g["carrier"],
            dict.fromkeys(
                (
                    "energyMwh",
                    "capacityMw",
                    "revenue",
                    "variableCost",
                    "grossMargin",
                    "fixedCostAnnual",
                    "fixedCostHorizon",
                ),
                0.0,
            ),
        )
        for k in a:
            a[k] += g[k]
    by_carrier: list[dict[str, Any]] = []
    for carrier, a in agg.items():
        by_carrier.append(
            {
                "carrier": carrier,
                "color": carrier_color(network, carrier),
                "energyMwh": round(a["energyMwh"], 1),
                "capacityMw": round(a["capacityMw"], 1),
                "revenue": round(a["revenue"]),
                "variableCost": round(a["variableCost"]),
                "grossMargin": round(a["grossMargin"]),
                "capturePrice": round(a["revenue"] / a["energyMwh"], 2)
                if a["energyMwh"] > 1e-9
                else None,
                "fixedCostAnnual": round(a["fixedCostAnnual"]),
                "fixedCostHorizon": round(a["fixedCostHorizon"]),
                "netHorizon": round(a["grossMargin"] - a["fixedCostHorizon"]),
                "recoveryPct": recovery_pct(a["grossMargin"], a["fixedCostHorizon"]),
            }
        )
    by_carrier.sort(key=lambda r: r["grossMargin"], reverse=True)

    # ── System totals (generators) ────────────────────────────────────────────
    sys_margin = float(sum(g["grossMargin"] for g in gens))
    sys_fixed_horizon = float(sum(g["fixedCostHorizon"] for g in gens))
    system = {
        "revenue": round(sum(g["revenue"] for g in gens)),
        "variableCost": round(sum(g["variableCost"] for g in gens)),
        "grossMargin": round(sys_margin),
        "fixedCostAnnual": round(sum(g["fixedCostAnnual"] for g in gens)),
        "fixedCostHorizon": round(sys_fixed_horizon),
        "netHorizon": round(sys_margin - sys_fixed_horizon),
        "recoveryPct": recovery_pct(sys_margin, sys_fixed_horizon),
        "generatorsModeled": len(gens),
        "generatorsRecovered": sum(
            1
            for g in gens
            if g["recoveryPct"] is not None and g["recoveryPct"] >= 100.0
        ),
    }

    return {
        "currency": currency,
        "modeledHours": round(modeled_hours, 1),
        "horizonYears": round(horizon_years, 4),
        "generators": gens,
        "storage": storage,
        "byCarrier": by_carrier,
        "system": system,
    }
