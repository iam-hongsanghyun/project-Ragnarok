"""Market simulation adapter (B2) — time-stepped, non-optimization.

Steps the system through the horizon under explicit dispatch rules instead of
solving an optimization: generators bid a price (their ``marginal_cost`` unless
overridden), each snapshot clears a single-market merit order against demand,
and storage follows a price-threshold arbitrage rule. Reports dispatch, clearing
prices, per-unit revenues/profits, price-setting hours, unserved energy and
storage behaviour.

Deliberately a **copper-plate market** (single clearing zone, no network limits):
network physics is B3's power-flow study; the LP/MILP optimum is B1's
optimization. This mode answers "what happens under these *rules*", e.g. a fixed
bidding strategy under uniform vs pay-as-bid settlement — and is the clearing
engine B4's strategic best-response sweeps drive.

Algorithm (per snapshot t):
    $$ P_t = \\text{bid of the marginal unit at } L_t \\quad (\\text{VOLL if } L_t > \\textstyle\\sum \\bar{p}_{i,t}) $$
    ASCII: sort units by bid; dispatch up the stack until load is met; the last
    (marginal) unit's bid sets the uniform price; unmet load prices at VOLL.

Storage rule (two passes): pass 1 clears without storage to get a price shape;
storage then charges in hours priced at/below the charge quantile and
discharges at/above the discharge quantile (chronologically, SoC-bounded);
pass 2 re-clears with storage charge added to load and discharge as zero-bid
supply.

Settlement:
    uniform      — every dispatched unit is paid the clearing price.
    payAsBid     — every dispatched unit is paid its own bid.
Profit is always revenue − true marginal cost × energy (bids may differ).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa

DEFAULT_VOLL = 3000.0  # €/MWh price applied to unserved energy
_EPS = 1e-9


def _as_series(
    network: pypsa.Network, component_t: Any, attr: str, index: list[str], static: pd.Series
) -> pd.DataFrame:
    """Dense per-snapshot frame of ``attr`` for ``index`` (series over static)."""
    snapshots = network.snapshots
    tv = getattr(component_t, attr, pd.DataFrame())
    out = pd.DataFrame(
        {name: np.full(len(snapshots), float(static.get(name, 0.0))) for name in index},
        index=snapshots,
    )
    for name in tv.columns.intersection(index):
        out[name] = tv[name].reindex(snapshots).fillna(float(static.get(name, 0.0)))
    return out


def _load_profile(network: pypsa.Network) -> pd.Series:
    """Total demand (MW) per snapshot from static + time-varying p_set."""
    if len(network.loads) == 0:
        return pd.Series(0.0, index=network.snapshots)
    dense = network.get_switchable_as_dense("Load", "p_set")
    return dense.sum(axis=1).reindex(network.snapshots).fillna(0.0)


def _clear_market(
    load: np.ndarray,
    avail: np.ndarray,  # (T, G) available MW per unit
    bids: np.ndarray,  # (G,) bid €/MWh per unit
    voll: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Merit-order clearing. Returns (dispatch (T,G), price (T,), unserved (T,),
    marginal-unit index (T,), −1 when VOLL sets the price)."""
    T, G = avail.shape
    order = np.argsort(bids, kind="stable")
    dispatch = np.zeros((T, G))
    price = np.zeros(T)
    unserved = np.zeros(T)
    marginal = np.full(T, -1)
    for t in range(T):
        remaining = float(load[t])
        if remaining <= _EPS:
            # No load: price at the cheapest bid (nothing dispatched).
            price[t] = float(bids[order[0]]) if G else 0.0
            continue
        for g in order:
            cap = float(avail[t, g])
            if cap <= _EPS:
                continue
            take = min(cap, remaining)
            dispatch[t, g] = take
            remaining -= take
            if remaining <= _EPS:
                price[t] = float(bids[g])
                marginal[t] = g
                break
        else:
            unserved[t] = remaining
            price[t] = voll
    return dispatch, price, unserved, marginal


def _storage_schedule(
    prices: np.ndarray,
    power_mw: float,
    energy_mwh: float,
    eta_round: float,
    q_charge: float,
    q_discharge: float,
) -> np.ndarray:
    """Chronological price-threshold arbitrage. Positive = discharge (MW),
    negative = charge. Only acts when the spread beats round-trip losses."""
    if power_mw <= _EPS or energy_mwh <= _EPS or len(prices) == 0:
        return np.zeros(len(prices))
    lo = float(np.quantile(prices, q_charge))
    hi = float(np.quantile(prices, q_discharge))
    if hi * eta_round <= lo:  # spread can't pay for the losses — stay idle
        return np.zeros(len(prices))
    schedule = np.zeros(len(prices))
    soc = 0.0
    for t, p in enumerate(prices):
        if p <= lo and soc < energy_mwh - _EPS:
            take = min(power_mw, energy_mwh - soc)
            schedule[t] = -take
            soc += take * np.sqrt(eta_round)  # charge-side losses
        elif p >= hi and soc > _EPS:
            give = min(power_mw, soc * np.sqrt(eta_round))  # discharge-side losses
            schedule[t] = give
            soc -= give / np.sqrt(eta_round)
    return schedule


def run_market_simulation(network: pypsa.Network, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Simulate the market over the network's snapshots under explicit rules.

    ``config`` keys (all optional):
        pricing        — "uniform" (default) | "payAsBid"
        voll           — €/MWh for unserved energy (default 3000)
        bids           — {generator_name: bid €/MWh} overriding marginal_cost
        withheldMw     — {generator_name: MW withheld from every hour} (B4)
        chargeQuantile / dischargeQuantile — storage thresholds (0.25 / 0.75)
    """
    cfg = config or {}
    pricing = str(cfg.get("pricing") or "uniform")
    voll = float(cfg.get("voll") or DEFAULT_VOLL)
    bid_overrides = {str(k): float(v) for k, v in (cfg.get("bids") or {}).items()}
    withheld = {str(k): float(v) for k, v in (cfg.get("withheldMw") or {}).items()}
    q_charge = float(cfg.get("chargeQuantile") or 0.25)
    q_discharge = float(cfg.get("dischargeQuantile") or 0.75)

    snapshots = network.snapshots
    T = len(snapshots)
    gens = network.generators
    names = [str(g) for g in gens.index]
    G = len(names)

    mc = np.array([float(gens.at[g, "marginal_cost"]) for g in gens.index]) if G else np.zeros(0)
    bids = np.array([bid_overrides.get(n, mc[i]) for i, n in enumerate(names)])
    p_nom = np.array([float(gens.at[g, "p_nom"]) for g in gens.index]) if G else np.zeros(0)
    pmax = _as_series(network, network.generators_t, "p_max_pu", names,
                      gens.get("p_max_pu", pd.Series(1.0, index=gens.index))).to_numpy()
    avail = pmax * p_nom[None, :]
    for n, w in withheld.items():
        if n in names:
            avail[:, names.index(n)] = np.clip(avail[:, names.index(n)] - w, 0.0, None)

    load = _load_profile(network).to_numpy()

    # Pass 1: clear without storage → the price shape the storage rule reads.
    dispatch, price, unserved, marginal = _clear_market(load, avail, bids, voll)

    # Storage responds to pass-1 prices; pass 2 re-clears with it in the market.
    storage_rows: list[dict[str, Any]] = []
    su = network.storage_units
    if len(su.index) and T:
        extra_load = np.zeros(T)
        extra_supply = np.zeros(T)
        for s in su.index:
            power = float(su.at[s, "p_nom"])
            hours = float(su.get("max_hours", pd.Series(dtype=float)).get(s, 6.0) or 6.0)
            eta_store = float(su.get("efficiency_store", pd.Series(dtype=float)).get(s, 1.0) or 1.0)
            eta_disp = float(su.get("efficiency_dispatch", pd.Series(dtype=float)).get(s, 1.0) or 1.0)
            sched = _storage_schedule(price, power, power * hours, eta_store * eta_disp,
                                      q_charge, q_discharge)
            extra_load += np.clip(-sched, 0.0, None)
            extra_supply += np.clip(sched, 0.0, None)
            charged = float(np.clip(-sched, 0, None).sum())
            discharged = float(np.clip(sched, 0, None).sum())
            storage_rows.append({
                "name": str(s), "energyChargedMWh": round(charged, 3),
                "energyDischargedMWh": round(discharged, 3),
                "arbitrageRevenue": round(float((np.clip(sched, 0, None) * price).sum()
                                                - (np.clip(-sched, 0, None) * price).sum()), 2),
            })
        if extra_load.any() or extra_supply.any():
            net_load = np.clip(load + extra_load - extra_supply, 0.0, None)
            dispatch, price, unserved, marginal = _clear_market(net_load, avail, bids, voll)

    # Settlement + per-unit economics.
    if pricing == "payAsBid":
        revenue_per_unit = dispatch * bids[None, :]
    else:
        revenue_per_unit = dispatch * price[:, None]
    cost_per_unit = dispatch * mc[None, :]

    labels = [pd.Timestamp(s).strftime("%H:%M") for s in snapshots]
    stamps = [pd.Timestamp(s).isoformat() for s in snapshots]
    carriers = [str(gens.at[g, "carrier"]) for g in gens.index] if G else []

    # Same row shape as the optimise-path series (period=None: single-period),
    # so the standard dispatch/price charts render simulation output directly.
    price_series = [
        {"label": labels[t], "timestamp": stamps[t], "period": None,
         "value": round(float(price[t]), 4)}
        for t in range(T)
    ]
    dispatch_series = []
    for t in range(T):
        values: dict[str, float] = {}
        for i in range(G):
            if dispatch[t, i] > _EPS:
                values[carriers[i]] = values.get(carriers[i], 0.0) + float(dispatch[t, i])
        if unserved[t] > _EPS:
            values["unserved"] = float(unserved[t])
        dispatch_series.append({"label": labels[t], "timestamp": stamps[t], "period": None,
                                "values": {k: round(v, 4) for k, v in values.items()},
                                "total": round(float(load[t]), 4)})

    units = []
    for i, n in enumerate(names):
        energy = float(dispatch[:, i].sum())
        units.append({
            "name": n, "carrier": carriers[i],
            "bid": round(float(bids[i]), 4), "marginalCost": round(float(mc[i]), 4),
            "energyMWh": round(energy, 3),
            "revenue": round(float(revenue_per_unit[:, i].sum()), 2),
            "cost": round(float(cost_per_unit[:, i].sum()), 2),
            "profit": round(float(revenue_per_unit[:, i].sum() - cost_per_unit[:, i].sum()), 2),
            "capacityFactor": round(energy / (float(p_nom[i]) * T), 4) if p_nom[i] > _EPS and T else 0.0,
            "priceSettingHours": int((marginal == i).sum()),
        })

    served = load - unserved
    total_cost = float((served * price).sum()) if pricing == "uniform" else float(revenue_per_unit.sum())
    return {
        "pricing": pricing,
        "voll": voll,
        "summary": {
            "avgPrice": round(float(price.mean()), 4) if T else 0.0,
            "peakPrice": round(float(price.max()), 4) if T else 0.0,
            "totalLoadMWh": round(float(load.sum()), 3),
            "totalCost": round(total_cost, 2),
            "unservedMWh": round(float(unserved.sum()), 3),
            "unservedHours": int((unserved > _EPS).sum()),
        },
        "priceSeries": price_series,
        "dispatchSeries": dispatch_series,
        "units": sorted(units, key=lambda u: -u["energyMWh"]),
        "storage": storage_rows,
    }


def run_market_sim_study(
    network: pypsa.Network,
    config: dict[str, Any],
    *,
    currency: str,
    snapshot_count: int,
    snapshot_weight: float,
    notes: list[str],
    model: dict[str, Any] | None = None,
    owner_column: str = "owner",
) -> dict[str, Any]:
    """The market-simulation STUDY payload (mirrors ``run_power_flow``'s shape).

    Like the power-flow study, this replaces the optimization: the payload keeps
    every optimise-only field (empty) so the frontend renders any run — but the
    dispatch and system-price series are filled from the simulation, so the
    standard charts show the simulated market directly.
    """
    from .full_outputs import build_full_outputs
    from .market import build_merit_order
    from .power_flow import EMPTY_OPTIMISE_FIELDS

    sim = run_market_simulation(network, config)
    s = sim["summary"]

    summary = [
        {"label": "Average price", "value": f"{currency}{s['avgPrice']:,.2f}/MWh",
         "detail": f"{sim['pricing']} settlement"},
        {"label": "Peak price", "value": f"{currency}{s['peakPrice']:,.2f}/MWh",
         "detail": f"VOLL {currency}{sim['voll']:,.0f}/MWh"},
        {"label": "Cost to load", "value": f"{currency}{s['totalCost']:,.0f}",
         "detail": f"{s['totalLoadMWh']:,.0f} MWh served"},
    ]
    if s["unservedMWh"] > 0:
        summary.append({"label": "Unserved energy", "value": f"{s['unservedMWh']:,.1f} MWh",
                        "detail": f"{s['unservedHours']} hour(s) short"})
    setters = [u for u in sim["units"] if u["priceSettingHours"] > 0]
    if setters:
        top = max(setters, key=lambda u: u["priceSettingHours"])
        summary.append({"label": "Price setter", "value": top["name"],
                        "detail": f"marginal in {top['priceSettingHours']} hour(s)"})

    narrative = [
        *notes,
        f"Market simulation (rule-based, not optimised): merit-order clearing with "
        f"{sim['pricing']} settlement on a single zone (copper plate — network limits "
        f"are not enforced; run a power-flow study for physics).",
    ]
    if sim["storage"]:
        cycled = sum(r["energyDischargedMWh"] for r in sim["storage"])
        narrative.append(f"Storage followed a price-threshold arbitrage rule "
                         f"({cycled:,.0f} MWh discharged).")

    # Strategic price-maker analysis (B4) rides the same clearing engine.
    strategic_cfg = config.get("strategic") or {}
    strategic = None
    if bool(strategic_cfg.get("enabled")) and model is not None:
        from .strategic import build_strategic_bidding

        strategic = build_strategic_bidding(
            network, model,
            config=strategic_cfg, sim_config=config,
            owner_column=owner_column, currency=currency,
        )
        if strategic is None:
            narrative.append(
                f"Strategic bidding was enabled but owner "
                f"{strategic_cfg.get('owner')!r} has no generators (column "
                f"'{owner_column}') — analysis skipped."
            )
        else:
            narrative.extend(strategic["notes"])

    return {
        **EMPTY_OPTIMISE_FIELDS,
        "dispatchSeries": sim["dispatchSeries"],
        "systemPriceSeries": sim["priceSeries"],
        "meritOrder": build_merit_order(network),
        "summary": summary,
        "marketSimulation": {
            "pricing": sim["pricing"],
            "voll": sim["voll"],
            "currency": currency,
            "summary": s,
            "units": sim["units"],
            "storage": sim["storage"],
        },
        "strategicBidding": strategic,
        "narrative": narrative,
        "runMeta": {
            "snapshotCount": snapshot_count,
            "snapshotWeight": snapshot_weight,
            "modeledHours": snapshot_count * snapshot_weight,
            "studyMode": "marketSim",
        },
        "outputs": build_full_outputs(network),
    }
