"""Market analysis helpers — merit order and CO₂ shadow price.

Both are pure post-processing on the solved network; no extra LP solve needed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pypsa
from ..network.piecewise import overlay_piecewise_marginal_cost, representative_marginal_costs

from ..constants import carrier_color, generator_color
from ..utils.series import weighted_sum
from .pathway_periods import is_pathway, period_objective_weights
from .stat_metrics import (
    COMPONENT_LISTS, asset_statistic, asset_value, combine_periods, fixed_cost_of, fixed_cost_table,
    period_hours_mean,
)

# System generators (reliability backstops, not merchant assets) — excluded from
# the supply stack and the profit analytics by name prefix.
SYSTEM_GEN_PREFIXES = ("load_shedding_", "system_bess")

# Calendar hours per year: turns a modelled-hours total into a per-year figure where one is shown.
# A unit-conversion constant (not a tunable parameter), so it lives in code rather than .env.
HOURS_PER_YEAR = 8760.0

_COMPONENT_OF = {lst: comp for comp, lst in COMPONENT_LISTS.items()}


# ── Counterfactual re-solves ──────────────────────────────────────────────────

def freeze_expansion(network: pypsa.Network) -> None:
    """Fix every extendable asset at the capacity the system solve gave it.

    Several studies answer a "what if" by copying the solved network, changing
    one thing and re-optimising — the merchant price-taker, the strategic-bidding
    counterfactual. A copy keeps ``p_nom_extendable``, so those re-solves would
    also re-make the INVESTMENT decision, which is never the question being
    asked and quietly changes the fleet under the answer.

    For the merchant study the consequence was severe: an unconstrained
    price-taker builds until the marginal MW breaks even, so profit came out
    exactly zero by construction and the reported capacity was the break-even
    one rather than the fleet's.

    Mutates ``network`` in place; call it on the copy, never on the solved
    original.
    """
    for attr in ("generators", "storage_units", "links", "lines", "stores"):
        df = getattr(network, attr, None)
        if df is None or not len(df) or "p_nom_extendable" not in df.columns:
            continue
        ext = df.index[df["p_nom_extendable"].astype(bool)]
        if not len(ext) or "p_nom_opt" not in df.columns:
            continue
        df.loc[ext, "p_nom"] = df.loc[ext, "p_nom_opt"].astype(float)
        df.loc[ext, "p_nom_extendable"] = False
    # Lines carry their rating as s_nom rather than p_nom.
    lines = getattr(network, "lines", None)
    if lines is not None and len(lines) and "s_nom_extendable" in lines.columns:
        ext = lines.index[lines["s_nom_extendable"].astype(bool)]
        if len(ext) and "s_nom_opt" in lines.columns:
            lines.loc[ext, "s_nom"] = lines.loc[ext, "s_nom_opt"].astype(float)
            lines.loc[ext, "s_nom_extendable"] = False


# ── Commitment costs ──────────────────────────────────────────────────────────

COMMITTABLE_LISTS = ("generators", "links", "processes")


def event_cost_frame(network: pypsa.Network, list_name: str, status_attr: str) -> pd.DataFrame:
    """Per-snapshot cost of each ``start_up`` / ``shut_down`` event, by unit.

    ``start_up_cost`` / ``shut_down_cost`` are static_or_series in PyPSA >= 1.4,
    so the price at the snapshot of the event comes from
    ``get_switchable_as_dense`` (not the static column). Events are charged once
    per occurrence, never scaled by the snapshot weighting (matches
    ``n.statistics.opex(cost_types=...)``). Empty frame when the component has no
    committable units or no event series.
    """
    cost_col = {"start_up": "start_up_cost", "shut_down": "shut_down_cost"}[status_attr]
    comp = network.components[list_name]
    events = comp.dynamic.get(status_attr)
    if events is None or getattr(events, "empty", True):
        return pd.DataFrame()
    if cost_col not in comp.static.columns or "committable" not in comp.static.columns:
        return pd.DataFrame()
    com_i = comp.static.index[comp.static["committable"].astype(bool)]
    com_i = com_i.intersection(events.columns)
    if len(com_i) == 0:
        return pd.DataFrame()
    cost = network.get_switchable_as_dense(list_name, cost_col, inds=com_i)
    return events.loc[:, com_i].astype(float) * cost.loc[:, com_i].reindex(events.index).fillna(0.0)


def build_commitment_cost(network: pypsa.Network) -> float:
    """Total start-up + shut-down cost actually incurred over the window.

    PyPSA's unit-commitment formulation carries ``start_up`` / ``shut_down``
    status series alongside ``status``; each transition is charged the unit's
    ``start_up_cost`` / ``shut_down_cost`` *at that snapshot* (both attributes
    may be time series). Covers committable Generators, Links and Processes.
    Those are objective terms, but they are per-EVENT rather than per-MWh, so
    nothing in the energy-weighted cost maths sees them.

    Returns 0.0 when nothing is committable, when the run relaxed the integers
    (``forceLp``), or when no unit ever changed state.
    """
    total = 0.0
    for list_name in COMMITTABLE_LISTS:
        if list_name not in network.components.keys():
            continue
        for status_attr in ("start_up", "shut_down"):
            frame = event_cost_frame(network, list_name, status_attr)
            if not frame.empty:
                total += float(frame.to_numpy().sum())
    return total


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
    curve_cost = representative_marginal_costs(network)  # generators priced by a piecewise curve
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
                "marginal_cost": round(float(curve_cost.get(name, gen.get("marginal_cost", 0.0))), 2),
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
    "Process-",
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
            # Several CO₂ constraints can coexist (e.g. a total cap and a
            # per-period cap). Report the binding one — the largest |dual| —
            # rather than whichever happens to be listed first.
            if "mu" in co2_gc.columns:
                mu_abs = pd.to_numeric(co2_gc["mu"], errors="coerce").abs().fillna(0.0)
                name = mu_abs.idxmax() if float(mu_abs.max()) > 0.0 else co2_gc.index[0]
            else:
                name = co2_gc.index[0]
            result["found"] = True
            result["constraint_name"] = name
            # A budget in tCO₂ reads in kt; a constraint merely *named* co2 on
            # another attribute has no known unit, so leave it blank.
            is_co2_attr = (
                "carrier_attribute" in gc.columns
                and str(gc.at[name, "carrier_attribute"]) == "co2_emissions"
            )
            result["cap_unit"] = "ktCO₂e" if is_co2_attr else ""

            if "constant" in gc.columns:
                constant = float(gc.at[name, "constant"])
                result["cap_value"] = round(constant / 1000.0 if is_co2_attr else constant, 1)

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


@dataclass(frozen=True)
class ProcessAsset:
    """One ``Process``'s window economics (P29), currency over the modelled window.

    ``revenue`` is the net value of the ports at the nodal prices (outputs earn,
    inputs cost); ``variable_cost`` is ``marginal_cost x p`` (internal power). ``capacity_mw`` is
    ``p_nom_opt`` and ``capex_annual`` the fixed charge PER YEAR that PyPSA's statistics
    report (``(capex + fom) / n.nyears``; installed and expanded capacity alike), with
    ``capex_sunk`` / ``capex_expanded`` the horizon split of the capex part. ``capital_cost`` is
    PyPSA's periodised cost per MW for the horizon (``c.capital_cost``).
    """

    name: str
    carrier: str
    bus: str
    capacity_mw: float
    energy_mwh: float
    revenue: float
    variable_cost: float
    capital_cost: float
    extendable: bool
    capex_annual: float
    capex_sunk: float = 0.0
    capex_expanded: float = 0.0


def process_assets(
    network: pypsa.Network,
    price_of: Callable[[str], np.ndarray | None],
    weights: np.ndarray,
    *,
    names: Iterable[str] | None = None,
) -> list[ProcessAsset]:
    """Revenue / operating cost / capex of the network's ``Process`` components.

    The one rule for every consumer (generator economics, company finance), so
    they cannot drift apart. ``Process`` is a multi-port conversion (like a
    ``Link``): ``p0`` is withdrawn from ``bus0`` and each further port ``p<i>``
    is the (signed) flow into the process from ``bus<i>`` — a negative value is
    an output that earns the nodal price.

    Algorithm:
        $$R = \\sum_t w_t \\sum_i -p_i(t)\\,\\pi_{b_i}(t), \\qquad
          C = \\sum_t w_t\\,c(t)\\,p(t), \\qquad
          K = \\frac{\\text{capex}^{stat} + \\text{fom}^{stat}}{n_{years}}$$
        ASCII: R = sum_t w * sum_i(-p_i * price_i) ; C = sum_t w*mc*p ;
        K = n.statistics.capex (+ fom) / n.nyears  (per year).

    Symbols: w_t weight (h; objective or objective x period weighting), p_i port
    flow (MW), pi nodal price (currency/MWh), c marginal cost (currency/MWh of
    internal power p), P_opt solved capacity (MW), K annual capex (currency/yr).
    Ports whose bus has no price contribute nothing to ``revenue``; stand-by,
    quadratic and start-up cost terms are not itemised here.
    """
    procs = getattr(network, "processes", None)
    if procs is None or procs.empty:
        return []
    t = network.c.processes.dynamic
    T = len(network.snapshots)
    try:
        mc_dense = network.get_switchable_as_dense("Process", "marginal_cost")
    except Exception:  # noqa: BLE001
        mc_dense = pd.DataFrame(0.0, index=network.snapshots, columns=procs.index)
    ports = sorted(
        int(c[3:]) for c in procs.columns
        if c.startswith("bus") and c[3:].isdigit()
    )
    fixed = fixed_cost_table(network, ["Process"])
    try:
        periodised = network.components.processes.capital_cost
    except Exception:  # noqa: BLE001
        periodised = procs["capital_cost"] if "capital_cost" in procs.columns else pd.Series(dtype=float)
    wanted = set(procs.index) if names is None else {str(n) for n in names}
    out: list[ProcessAsset] = []
    for name in procs.index:
        if name not in wanted:
            continue
        # Internal power p (the unit marginal_cost is quoted in); equals the bus0
        # withdrawal for the default rate0 = -1.
        p_int = t["p"][name].to_numpy(dtype=float) if "p" in t and name in t["p"].columns else np.zeros(T)
        revenue = 0.0
        for i in ports:
            bus = str(procs.at[name, f"bus{i}"] or "")
            frame = t.get(f"p{i}")
            if not bus or frame is None or name not in frame.columns:
                continue
            pi = price_of(bus)
            if pi is None:
                continue
            revenue += float((-frame[name].to_numpy(dtype=float) * pi * weights).sum())
        mc = mc_dense[name].to_numpy(dtype=float) if name in mc_dense.columns else np.zeros(T)
        ext = bool(procs.at[name, "p_nom_extendable"]) if "p_nom_extendable" in procs.columns else False
        cap_cost = float(periodised.get(name, 0.0)) if hasattr(periodised, "get") else 0.0
        fc = fixed_cost_of(fixed, "Process", str(name))
        p_nom_opt = float(installed_capacity_series(procs).get(name, 0.0))
        out.append(ProcessAsset(
            name=str(name),
            carrier=str(procs.at[name, "carrier"]) if "carrier" in procs.columns else "",
            bus=str(procs.at[name, "bus0"]) if "bus0" in procs.columns else "",
            capacity_mw=p_nom_opt,
            energy_mwh=float((np.clip(p_int, 0.0, None) * weights).sum()),
            revenue=revenue,
            variable_cost=float((mc * p_int * weights).sum()),
            capital_cost=cap_cost,
            extendable=ext,
            capex_annual=fc["annual"],
            capex_sunk=fc["capex_sunk"],
            capex_expanded=fc["capex_expanded"],
        ))
    return out


def _process_energy(network: pypsa.Network, name: str, weights: pd.Series) -> float:
    """Σ w · max(p, 0) in MWh for one Process (snapshot-weighted internal throughput)."""
    p = network.c.processes.dynamic.get("p")
    if p is None or name not in p.columns:
        return 0.0
    return float(weighted_sum(p[name].clip(lower=0.0), weights))


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
    costs already on the solved network; **no extra solve**. Revenue, energy
    (supply / withdrawal) and the capture price come from ``n.statistics``
    (``revenue``, ``supply``, ``withdrawal``; P28), read per asset and per
    investment period (:mod:`.stat_metrics`); inactive assets are NaN in PyPSA's
    period-resolved statistics and count as 0. Variable cost stays on the
    app's dense marginal cost (it carries the carbon adder and the piecewise
    overlay, which ``n.statistics.opex`` does not know about). ``capturePrice``
    equals ``n.statistics.market_value`` for a unit that never absorbs power
    (it divides by the output, PyPSA by ``|p|``). PyPSA weights revenue with the
    ``objective`` snapshot weighting, energy with ``generators``; the app sets
    both equal. Under the least-cost
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

        The fixed cost F_i is what PyPSA charged over the modelled horizon:
        n.statistics.capex + n.statistics.fom (periodised capital_cost, or overnight x
        annuity x nyears, plus fom_cost). It is compared with the margin earned over the same
        horizon; ``fixedCostAnnual`` is F_i / n.nyears (a per-year display figure):

        $$ F_i = \\text{capex}^{stat}_i + \\text{fom}^{stat}_i, \\qquad \\text{recovery}_i = 100\\,M_i / F_i $$

        ASCII: R = sum_t w*price*p ; M = R - sum_t w*mc*p ;
        capture = R / sum_t w*p ; recovery% = 100 * M / (n.statistics.capex + n.statistics.fom).

    Symbols/units: π, c, capture in {currency}/MWh; p in MW; w, H in h; R, M, F
    in {currency}; capex / fom are PyPSA's per-horizon statistics; recovery dimensionless (%).

    The recovery ratio is scale-invariant in H, so a sub-annual window still
    reports a meaningful "did the margin cover the fixed cost?" figure; every
    absolute money column is on the modeled-horizon basis (``fixedCostAnnual`` is
    additionally exposed per year). Storage revenue is the net
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

    # Fixed-cost basis: n.statistics.capex + n.statistics.fom, i.e. exactly what PyPSA's objective
    # charges over the modelled horizon (a pathway run: per period, with the investment-period
    # weighting, only while the asset is active). The per-year figure divides by n.nyears.
    pathway = is_pathway(network)
    period_weight = period_objective_weights(network)
    period_level = network.snapshots.get_level_values("period") if pathway else None
    econ_weights = weights
    if pathway:
        econ_weights = weights * pd.Series(
            [period_weight[int(p)] for p in period_level], index=network.snapshots
        )
    fixed_table = fixed_cost_table(network, ["Generator", "StorageUnit", "Process"])

    def fixed_costs(list_name: str, name: str, *_unused: float) -> tuple[float, float]:
        """``(per-year, modelled-horizon)`` fixed cost (capex + fom) of one asset, from n.statistics."""
        fc = fixed_cost_of(fixed_table, _COMPONENT_OF[list_name], name)
        return fc["annual"], fc["capex_horizon"] + fc["fom_horizon"]

    mp = network.buses_t.marginal_price
    have_prices = not mp.empty
    zero = pd.Series(0.0, index=network.snapshots)

    # n.statistics per asset (P28): revenue by period x investment-period weight,
    # energy summed over periods (physical, unweighted) and period-weighted (the
    # capture-price denominator, same basis as the revenue).
    stat_w = period_weight if pathway else None
    stat_components = ["Generator", "StorageUnit"]
    rev_econ = combine_periods(asset_statistic(network, "revenue", [*stat_components, "Process"]), stat_w)
    supply_frame = asset_statistic(network, "supply", stat_components)
    supply = combine_periods(supply_frame)
    supply_econ = combine_periods(supply_frame, stat_w)
    withdrawal = combine_periods(asset_statistic(network, "withdrawal", ["StorageUnit"]))
    # n.statistics.capacity_factor (mean |p| / capacity per period), hours-weighted over
    # the periods the unit exists in; the carrier value is capacity-weighted like PyPSA's.
    hours_by_period = (
        weights.groupby(network.snapshots.get_level_values("period")).sum().to_dict()
        if pathway else {0: modeled_hours}
    )
    cf_num, cf_den = period_hours_mean(asset_statistic(network, "capacity_factor", ["Generator"]), hours_by_period)

    def price_at(bus: str) -> pd.Series:
        return mp[bus] if (have_prices and bus in mp.columns) else zero

    def _cf(num: float, den: float) -> float | None:
        return round(num / den, 4) if den > 1e-9 else None

    def recovery_pct(margin: float, fixed_horizon: float) -> float | None:
        return (
            round(100.0 * margin / fixed_horizon, 1) if fixed_horizon > 1e-9 else None
        )

    # ── Generators ────────────────────────────────────────────────────────────
    gens: list[dict[str, Any]] = []
    gen_p = network.generators_t.p
    if not gen_p.empty and len(network.generators):
        mc_dense = overlay_piecewise_marginal_cost(network, network.get_switchable_as_dense("Generator", "marginal_cost"))
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

            energy = asset_value(supply, "Generator", name)
            energy_econ = asset_value(supply_econ, "Generator", name)  # capture-price basis
            p_nom_opt = float(p_nom_opt_s.get(name, 0.0))
            if energy <= 1e-9 and p_nom_opt <= 1e-9:
                continue  # neither dispatched nor built — nothing to report
            revenue = asset_value(rev_econ, "Generator", name)
            variable_cost = weighted_sum(mc * p, econ_weights)
            gross_margin = revenue - variable_cost
            fixed_annual, fixed_horizon = fixed_costs(
                "generators", name, _num(row.get("capital_cost", 0.0)), p_nom_opt
            )
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
                    "capturePrice": round(revenue / energy_econ, 2)
                    if energy_econ > 1e-9
                    else None,
                    "capacityFactor": _cf(asset_value(cf_num, "Generator", name), asset_value(cf_den, "Generator", name)),
                    "fixedCostAnnual": round(fixed_annual),
                    "fixedCostHorizon": round(fixed_horizon),
                    "netHorizon": round(gross_margin - fixed_horizon),
                    "recoveryPct": recovery_pct(gross_margin, fixed_horizon),
                    # Unrounded values: carrier / system recovery is computed from
                    # these, not from the rounded columns above.
                    "_raw": {
                        "energyMwh": energy,
                        "energyEcon": energy_econ,
                        "capacityMw": p_nom_opt,
                        "cfNum": p_nom_opt * asset_value(cf_num, "Generator", name),
                        "cfDen": p_nom_opt * asset_value(cf_den, "Generator", name),
                        "revenue": revenue,
                        "variableCost": variable_cost,
                        "grossMargin": gross_margin,
                        "fixedCostAnnual": fixed_annual,
                        "fixedCostHorizon": fixed_horizon,
                    },
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

            discharged = asset_value(supply, "StorageUnit", name)
            charged = asset_value(withdrawal, "StorageUnit", name)
            p_nom_opt = float(p_nom_opt_su.get(name, 0.0))
            if discharged <= 1e-9 and charged <= 1e-9 and p_nom_opt <= 1e-9:
                continue
            revenue = asset_value(rev_econ, "StorageUnit", name)  # net of charging spend
            variable_cost = weighted_sum(mc * p.clip(lower=0.0), econ_weights)
            gross_margin = revenue - variable_cost
            fixed_annual, fixed_horizon = fixed_costs(
                "storage_units", name, _num(row.get("capital_cost", 0.0)), p_nom_opt
            )
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

    # ── Processes (P29): net port value, marginal cost and capex ──────────────
    processes_rows: list[dict[str, Any]] = []
    def proc_price(bus: str) -> Any:
        return price_at(bus).to_numpy(dtype=float) if (have_prices and bus in mp.columns) else None

    for a in process_assets(network, proc_price, econ_weights.to_numpy(dtype=float)):
        if a.energy_mwh <= 1e-9 and a.capacity_mw <= 1e-9:
            continue
        fixed_annual, fixed_horizon = fixed_costs("processes", a.name, a.capital_cost, a.capacity_mw)
        proc_revenue = asset_value(rev_econ, "Process", a.name, default=a.revenue)  # n.statistics.revenue
        margin = proc_revenue - a.variable_cost
        processes_rows.append({
            "name": a.name, "carrier": a.carrier, "bus": a.bus,
            "color": carrier_color(network, a.carrier),
            "energyMwh": round(_process_energy(network, a.name, weights), 1),
            "capacityMw": round(a.capacity_mw, 1),
            "revenue": round(proc_revenue),
            "variableCost": round(a.variable_cost),
            "grossMargin": round(margin),
            "fixedCostAnnual": round(fixed_annual),
            "fixedCostHorizon": round(fixed_horizon),
            "netHorizon": round(margin - fixed_horizon),
            "recoveryPct": recovery_pct(margin, fixed_horizon),
        })
    processes_rows.sort(key=lambda r: r["grossMargin"], reverse=True)

    # ── Per-carrier rollup (generators) ───────────────────────────────────────
    agg: dict[str, dict[str, float]] = {}
    for g in gens:
        a = agg.setdefault(
            g["carrier"],
            dict.fromkeys(
                (
                    "energyMwh",
                    "energyEcon",
                    "capacityMw",
                    "cfNum",
                    "cfDen",
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
            a[k] += g["_raw"][k]
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
                "capturePrice": round(a["revenue"] / a["energyEcon"], 2)
                if a["energyEcon"] > 1e-9
                else None,
                "capacityFactor": _cf(a["cfNum"], a["cfDen"]),
                "fixedCostAnnual": round(a["fixedCostAnnual"]),
                "fixedCostHorizon": round(a["fixedCostHorizon"]),
                "netHorizon": round(a["grossMargin"] - a["fixedCostHorizon"]),
                "recoveryPct": recovery_pct(a["grossMargin"], a["fixedCostHorizon"]),
            }
        )
    by_carrier.sort(key=lambda r: r["grossMargin"], reverse=True)

    # ── System totals (generators) ────────────────────────────────────────────
    sys_margin = float(sum(g["_raw"]["grossMargin"] for g in gens))
    sys_fixed_horizon = float(sum(g["_raw"]["fixedCostHorizon"] for g in gens))
    for g in gens:
        g.pop("_raw")
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
        "processes": processes_rows,
        "byCarrier": by_carrier,
        "system": system,
    }
