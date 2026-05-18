"""Market analysis helpers — merit order and CO₂ shadow price.

Both are pure post-processing on the solved network; no extra LP solve needed.
"""
from __future__ import annotations

from typing import Any

import pypsa

from ..constants import carrier_color


# ── Merit order ───────────────────────────────────────────────────────────────

def build_merit_order(network: pypsa.Network) -> list[dict[str, Any]]:
    """Return the supply-stack (merit order) sorted by marginal cost.

    System generators (grid_imports, load_shedding_*) are excluded — they
    exist as reliability backstops and distort the supply curve.

    Each dict:
        name          – generator name
        carrier       – carrier string
        bus           – bus name
        marginal_cost – $/MWh
        p_nom         – installed capacity (MW); uses p_nom_opt for extendable
        cumulative_mw – left edge of this generator's block on the x-axis
        color         – hex colour for the carrier
    """
    SYSTEM_GEN_PREFIXES = ("grid_imports", "load_shedding_", "system_bess")

    rows: list[dict[str, Any]] = []
    for name in network.generators.index:
        if any(name.startswith(pfx) for pfx in SYSTEM_GEN_PREFIXES):
            continue
        gen = network.generators.loc[name]
        # Use optimised capacity for extendable assets, installed otherwise
        extendable = bool(gen.get("p_nom_extendable", False))
        p_nom = float(gen.get("p_nom_opt", 0.0) if extendable else gen.get("p_nom", 0.0))
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
                "color": carrier_color(network, carrier),
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
    BINDING_THRESHOLD = 0.01

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
            if abs(mu) > BINDING_THRESHOLD:
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

    if abs(mu) > BINDING_THRESHOLD:
        result["status"] = "binding"
        result["note"] = (
            f"CO₂ intensity constraint is binding. "
            f"Shadow price = {currency}{abs(mu):.4f}/tCO₂ — relaxing the intensity cap "
            f"by 1 kg CO₂e/MWh would reduce system cost by {currency}{abs(mu)/1000:.6f} per MWh dispatched."
        )
    else:
        result["status"] = "slack"
        result["note"] = (
            f"CO₂ intensity constraint exists but is not binding — "
            f"actual intensity is below the cap. Shadow price ≈ {currency}0."
        )

    return result
