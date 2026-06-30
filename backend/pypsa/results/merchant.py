"""Merchant / price-taker optimisation (B1) — most-profitable for one owner.

The system solve answers *least-cost for the whole system*. An investor asks a
different question: given a price signal, how should **my** assets dispatch (and
how much should I build) to maximise **my** profit? That is the merchant /
price-taker model.

Two stages:

1. **Price** — π(t). Either the system locational marginal price from the
   stage-1 cost-min run (``buses_t.marginal_price``) — the standard
   merchant-investor model — or a user-supplied exogenous price.
2. **Owner optimise** — a reduced network holding only the owner's assets, each
   connected to a *price-taker market node* (a generator priced at π(t) with
   ``p_min_pu = -1`` so the owner can both sell into and buy from the market).
   Minimising ``Σ mc·p + Σ π·p_market`` over that network is exactly maximising
   the owner's profit, because the market term equals ``−(revenue − purchase)``.

Single-level LP/MILP on the existing PyPSA + linopy + HiGHS stack — no new
solver. Storage arbitrage, hydro and build-vs-retire timing all fall out of the
LP; an unconstrained single generator degenerates to the threshold rule
(dispatch when π > marginal cost).
"""
from __future__ import annotations

import logging
from typing import Any

import pypsa

_log = logging.getLogger("pypsa.solver")

# The market node must be able to absorb / supply any owner volume at π(t).
_MARKET_P_NOM = 1.0e7
_MARKET_PREFIX = "__market_"


def owner_assets_from_model(
    model: dict[str, list[dict[str, Any]]], owner: str,
) -> dict[str, list[str]]:
    """Names of the generators / storage units tagged with ``owner``.

    The ``owner`` tag lives on the model rows (a custom column); PyPSA drops
    unknown columns at build time, so we read ownership from the model, not the
    network.
    """
    want = owner.strip()
    out: dict[str, list[str]] = {"generators": [], "storage_units": []}
    for sheet, key in (("generators", "generators"), ("storage_units", "storage_units")):
        for row in model.get(sheet, []) or []:
            name = str(row.get("name", "")).strip()
            if name and str(row.get("owner", "")).strip() == want:
                out[key].append(name)
    return out


def distinct_owners(model: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Every distinct non-blank ``owner`` tag across generators and storage."""
    seen: list[str] = []
    for sheet in ("generators", "storage_units"):
        for row in model.get(sheet, []) or []:
            owner = str(row.get("owner", "")).strip()
            if owner and owner not in seen:
                seen.append(owner)
    return seen


def _price_by_bus(
    network: pypsa.Network,
    buses: list[str],
    *,
    price_source: str,
    flat_price: float,
    price_series: list[float] | None,
) -> dict[str, list[float]] | None:
    """π(t) per owner bus. ``None`` if LMPs were requested but unavailable."""
    n_snap = len(network.snapshots)
    if price_source == "series":
        if price_series and len(price_series) == n_snap:
            series = [float(v) for v in price_series]
        else:
            series = [float(flat_price)] * n_snap
        return {bus: list(series) for bus in buses}
    # LMP: the shadow price of each bus's energy balance from stage 1.
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    out: dict[str, list[float]] = {}
    for bus in buses:
        if bus not in mp.columns:
            return None
        out[bus] = [float(v) for v in mp[bus].to_numpy()]
    return out


def build_merchant(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner: str,
    price_source: str,
    flat_price: float,
    price_series: list[float] | None,
    currency: str,
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Optimise one owner's assets against a price signal; return their economics.

    Args:
        network: A network already solved by ``n.optimize()`` (stage 1).
        model: The raw model dict — source of the ``owner`` tags.
        owner: Which owner to analyse.
        price_source: ``"lmp"`` (stage-1 marginal price) or ``"series"`` (exogenous).
        flat_price: Flat price for ``"series"`` mode (per MWh, run currency).
        price_series: Optional hourly price overriding ``flat_price`` in series mode.
        currency: Currency symbol (passthrough for the UI).
        solver_options: HiGHS options mirrored from the main solve.
        io_api: linopy IO api mirrored from the main solve.

    Returns:
        ``{owner, priceSource, currency, priceStats, assets, totals, notes}`` or
        ``None`` when there is nothing to analyse (owner has no assets, network
        unsolved, or LMPs requested but unavailable).
    """
    if not getattr(network, "is_solved", False):
        return None
    assets = owner_assets_from_model(model, owner)
    own_gens = [g for g in assets["generators"] if g in network.generators.index]
    own_storage = [s for s in assets["storage_units"] if s in network.storage_units.index]
    if not own_gens and not own_storage:
        return None

    buses = sorted({
        *(str(network.generators.at[g, "bus"]) for g in own_gens),
        *(str(network.storage_units.at[s, "bus"]) for s in own_storage),
    })
    price = _price_by_bus(
        network, buses,
        price_source=price_source, flat_price=flat_price, price_series=price_series,
    )
    if price is None:
        _log.warning("merchant: LMPs unavailable for owner %r — skipping", owner)
        return None

    weights = network.snapshot_weightings["objective"].to_numpy()

    # ``copy()`` refuses with a solver model attached; the app reads every number
    # from solved dataframes, so detaching is side-effect-free downstream.
    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001
        pass

    work = network.copy()
    # Strip everything that is not the owner's assets: the owner trades only with
    # the price-taker market node, not with the rest of the system.
    drop_gens = [g for g in work.generators.index if g not in own_gens]
    if drop_gens:
        work.remove("Generator", drop_gens)
    drop_storage = [s for s in work.storage_units.index if s not in own_storage]
    if drop_storage:
        work.remove("StorageUnit", drop_storage)
    for comp, attr in (("Load", "loads"), ("Line", "lines"), ("Link", "links"),
                       ("Transformer", "transformers"), ("Store", "stores")):
        idx = list(getattr(work, attr).index)
        if idx:
            work.remove(comp, idx)

    # One price-taker market node per owner bus: a generator priced at π(t) that
    # can supply (owner buys) or absorb (owner sells, p < 0) any volume.
    for bus in buses:
        name = f"{_MARKET_PREFIX}{bus}"
        work.add("Generator", name, bus=bus, carrier="market",
                 p_nom=_MARKET_P_NOM, p_min_pu=-1.0, p_max_pu=1.0)
        work.generators_t.marginal_cost[name] = price[bus]

    try:
        result = work.optimize(
            solver_name="highs",
            solver_options=solver_options or {},
            io_api=io_api,
            include_objective_constant=False,
        )
    except Exception as exc:  # noqa: BLE001 — never sink the run over the merchant extra
        _log.warning("merchant optimise failed for owner %r: %s", owner, exc)
        return None
    status = str(result[0]) if isinstance(result, tuple) else str(result)
    if status not in ("ok", "optimal"):
        _log.warning("merchant optimise non-optimal for owner %r: %s", owner, status)
        return None

    asset_rows: list[dict[str, Any]] = []
    tot_rev = tot_cost = tot_capex = tot_energy = 0.0

    def _capex(comp: str, name: str) -> float:
        df = work.generators if comp == "Generator" else work.storage_units
        ext_col = "p_nom_extendable"
        if ext_col in df.columns and bool(df.at[name, ext_col]):
            return float(df.at[name, "capital_cost"]) * float(df.at[name, "p_nom_opt"])
        return 0.0

    for g in own_gens:
        bus = str(work.generators.at[g, "bus"])
        p = work.generators_t.p[g].to_numpy()
        pi = price[bus]
        energy = float((p * weights).sum())
        revenue = float((p * pi * weights).sum())
        mc = float(work.generators.at[g, "marginal_cost"])
        op_cost = float((mc * p * weights).sum())
        capex = _capex("Generator", g)
        cap = float(work.generators.at[g, "p_nom_opt"])
        asset_rows.append({
            "name": g, "type": "generator", "bus": bus,
            "carrier": str(work.generators.at[g, "carrier"]),
            "capacityMW": round(cap, 3),
            "energyMWh": round(energy, 2),
            "revenue": round(revenue, 2),
            "operatingCost": round(op_cost, 2),
            "capex": round(capex, 2),
            "profit": round(revenue - op_cost - capex, 2),
            "capturePrice": round(revenue / energy, 2) if energy > 1e-9 else None,
        })
        tot_rev += revenue
        tot_cost += op_cost
        tot_capex += capex
        tot_energy += energy

    for s in own_storage:
        bus = str(work.storage_units.at[s, "bus"])
        pd_ = work.storage_units_t.p_dispatch[s].to_numpy()
        pc = work.storage_units_t.p_store[s].to_numpy()
        pi = price[bus]
        net = pd_ - pc
        energy = float((pd_ * weights).sum())  # energy sold
        revenue = float((net * pi * weights).sum())
        mc = float(work.storage_units.at[s, "marginal_cost"]) if "marginal_cost" in work.storage_units.columns else 0.0
        op_cost = float((mc * pd_ * weights).sum())
        capex = _capex("StorageUnit", s)
        cap = float(work.storage_units.at[s, "p_nom_opt"])
        asset_rows.append({
            "name": s, "type": "storage", "bus": bus,
            "carrier": str(work.storage_units.at[s, "carrier"]),
            "capacityMW": round(cap, 3),
            "energyMWh": round(energy, 2),
            "revenue": round(revenue, 2),
            "operatingCost": round(op_cost, 2),
            "capex": round(capex, 2),
            "profit": round(revenue - op_cost - capex, 2),
            "capturePrice": round(revenue / energy, 2) if energy > 1e-9 else None,
        })
        tot_rev += revenue
        tot_cost += op_cost
        tot_capex += capex
        tot_energy += energy

    flat_prices = [v for series in price.values() for v in series]
    price_stats = {
        "mean": round(sum(flat_prices) / len(flat_prices), 2) if flat_prices else None,
        "min": round(min(flat_prices), 2) if flat_prices else None,
        "max": round(max(flat_prices), 2) if flat_prices else None,
    }
    _log.info(
        "merchant: owner=%r assets=%d profit=%.1f (source=%s)",
        owner, len(asset_rows), tot_rev - tot_cost - tot_capex, price_source,
    )
    return {
        "owner": owner,
        "priceSource": price_source,
        "currency": currency,
        "priceStats": price_stats,
        "assets": asset_rows,
        "totals": {
            "revenue": round(tot_rev, 2),
            "operatingCost": round(tot_cost, 2),
            "capex": round(tot_capex, 2),
            "profit": round(tot_rev - tot_cost - tot_capex, 2),
            "energyMWh": round(tot_energy, 2),
        },
    }
