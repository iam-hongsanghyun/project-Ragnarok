"""ESS business-case builder (DW3) — is a battery viable, and at what size?

Sweep storage power sizes; for each, optimise a price-taker battery against the
system marginal price (energy arbitrage — charge cheap, discharge dear) and turn
its revenue into project finance: NPV, IRR, payback. Report the sweep and the
NPV-maximising size.

Arbitrage is priced against the *base* run's LMP, i.e. the battery is a price
taker — a standard business-case screen. Only the energy-arbitrage revenue
stream is modelled here; capacity value and ancillary/reserve are not.

Basis: the study covers the modelled window of ``H = Σ_t w_t`` represented
hours, so the arbitrage revenue is a window total. The annual cashflow that
feeds NPV / IRR / payback is annualised by ``× 8760 / H``:

    $$M = R_H \\cdot 8760 / H, \\qquad CF_0 = -C,\\; CF_{1..L} = M$$
    ASCII: M = revenue_H * 8760/H ; CF_0 = -overnight ; CF_t = M.

``arbitrageRevenue`` and ``energyMWh`` in the per-size rows stay on the
window basis (what the sweep actually simulated).
"""
from __future__ import annotations

import logging
import math
from typing import Any

import pypsa

from .finance import _crf, _irr, _npv, _payback
from .market import HOURS_PER_YEAR

_log = logging.getLogger("pypsa.solver")

_DEFAULT_LIFETIME = 15.0
_MAX_STEPS = 12
_MARKET = "__ess_market"


def build_ess_business_case(
    base_network: pypsa.Network,
    *,
    bus: str,
    max_hours: float,
    capital_cost_per_mw: float,
    min_size_mw: float,
    max_size_mw: float,
    steps: int,
    round_trip_efficiency: float,
    discount_rate: float,
    currency: str,
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
) -> dict[str, Any] | None:
    """Size sweep of a price-taker battery's arbitrage business case.

    Returns ``None`` when there are no marginal prices (a non-LP run) or the
    parameters are degenerate.
    """
    if not getattr(base_network, "is_solved", False):
        return None
    mp = base_network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    # Default to the most volatile bus (best arbitrage) if none/invalid given.
    if not bus or bus not in mp.columns:
        bus = str(mp.std().idxmax()) if len(mp.columns) else ""
    if not bus or bus not in mp.columns:
        return None

    max_size_mw = max(0.0, float(max_size_mw))
    min_size_mw = max(0.0, float(min_size_mw))
    if max_size_mw <= 0:
        return None
    n_steps = max(1, min(int(steps or 6), _MAX_STEPS))
    eta = max(0.05, min(1.0, float(round_trip_efficiency or 0.9)))
    r = float(discount_rate or 0.0)
    life = _DEFAULT_LIFETIME
    price = mp[bus]
    w = base_network.snapshot_weightings["objective"]
    # Modelled window (represented hours): window revenue × 8760/H = annual.
    H = float(w.sum())
    if H <= 0:
        return None
    annualize = HOURS_PER_YEAR / H

    # One reduced network: the chosen bus, a price-taker market node, and the
    # battery. We resize the battery and re-solve per step.
    try:
        if base_network.model is not None:
            base_network.model.solver_model = None
    except Exception:  # noqa: BLE001
        pass
    try:
        net = base_network.copy()
    except Exception as exc:  # noqa: BLE001
        _log.warning("ESS: could not copy network: %s", exc)
        return None
    for comp, attr in (("Generator", "generators"), ("StorageUnit", "storage_units"),
                       ("Store", "stores"), ("Load", "loads"), ("Line", "lines"),
                       ("Link", "links"), ("Transformer", "transformers")):
        idx = list(getattr(net, attr).index)
        if idx:
            net.remove(comp, idx)
    net.add("Generator", _MARKET, bus=bus, carrier="market", p_nom=1.0e7, p_min_pu=-1.0, p_max_pu=1.0)
    net.generators_t.marginal_cost[_MARKET] = price.values
    net.add(
        "StorageUnit", "ess", bus=bus, carrier="battery", p_nom=1.0, max_hours=float(max_hours),
        efficiency_store=math.sqrt(eta), efficiency_dispatch=math.sqrt(eta),
        marginal_cost=0.0, cyclic_state_of_charge=True,
    )

    sizes: list[dict[str, Any]] = []
    for i in range(n_steps):
        size = min_size_mw + (max_size_mw - min_size_mw) * (i / (n_steps - 1)) if n_steps > 1 else max_size_mw
        if size <= 0:
            continue
        net.storage_units.at["ess", "p_nom"] = size
        try:
            if net.model is not None:
                net.model.solver_model = None
        except Exception:  # noqa: BLE001
            pass
        try:
            result = net.optimize(
                solver_name="highs", solver_options=solver_options or {},
                io_api=io_api, include_objective_constant=False,
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning("ESS size %.1f MW failed: %s", size, exc)
            continue
        status = str(result[0]) if isinstance(result, tuple) else str(result)
        if status not in ("ok", "optimal"):
            continue
        pd_ = net.storage_units_t.p_dispatch["ess"].to_numpy()
        pc = net.storage_units_t.p_store["ess"].to_numpy()
        revenue = float(((pd_ - pc) * price.to_numpy() * w.to_numpy()).sum())
        annualised_capex = capital_cost_per_mw * size
        overnight = annualised_capex / _crf(r, life) if annualised_capex > 0 else 0.0
        # Window revenue annualised (× 8760/H) — the yearly cashflow; opex ~0
        # for a battery.
        margin = revenue * annualize
        cashflows = [-overnight] + [margin] * int(round(life))
        npv = _npv(r, cashflows)
        irr = _irr(cashflows)
        sizes.append({
            # energyMWh / arbitrageRevenue are WINDOW totals (H represented
            # hours), not annual figures.
            "sizeMW": round(size, 2),
            "energyMWh": round(float((pd_ * w.to_numpy()).sum()), 1),
            "arbitrageRevenue": round(revenue, 2),
            "annualisedCapex": round(annualised_capex, 2),
            "npv": round(npv, 2),
            "irr": round(irr, 5) if irr is not None else None,
            "paybackYears": _payback(cashflows),
        })

    if not sizes:
        return None
    best = max(sizes, key=lambda s: s["npv"])
    _log.info("ESS business case: %d sizes on bus %r, best %.1f MW (NPV %.0f)", len(sizes), bus, best["sizeMW"], best["npv"])
    return {
        "bus": bus,
        "maxHours": float(max_hours),
        "roundTripEfficiency": eta,
        "discountRate": r,
        "lifetimeYears": life,
        "currency": currency,
        "sizes": sizes,
        "bestSizeMW": best["sizeMW"],
        "bestNpv": best["npv"],
    }
