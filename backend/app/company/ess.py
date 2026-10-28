"""ESS business-case builder (DW3) — is a battery viable, and at what size?

Sweep storage power sizes; for each, optimise a price-taker battery against the
system marginal price (energy arbitrage — charge cheap, discharge dear) and turn
its revenue into project finance: NPV, IRR, payback. Report the sweep and the
NPV-maximising size.

Arbitrage is priced against the *base* run's LMP, i.e. the battery is a price
taker — a standard business-case screen. Only the energy-arbitrage revenue
stream is modelled here; capacity value and ancillary/reserve are not.

Basis: the study covers the modelled window of ``H = Σ_t w_t`` represented
hours (on a pathway run, all periods together: the annual figure is the
average over periods), so the arbitrage revenue is a window total. The annual
margin that feeds NPV / IRR / payback is annualised by ``× 8760 / H``:

    $$M = R_H \\cdot 8760 / H - o\\,P, \\qquad C_0 = \\frac{(c_P P + c_E E)}{\\mathrm{CRF}(r, L)},
      \\qquad CF_0 = -C_0,\\; CF_{1..L} = M$$
    ASCII: M = revenue_H*8760/H - fixed_om*P ; C0 = (cP*P + cE*E)/CRF(r,L) ; CF_t = M.

Symbols: ``R_H`` window arbitrage revenue (currency); ``P`` power (MW); ``E = P·max_hours``
energy (MWh); ``c_P`` capital cost per MW **per year** (annualised — the PyPSA
``capital_cost`` convention) and ``c_E`` per MWh **per year**; ``o`` fixed O&M
(currency/MW/yr); ``r`` discount rate; ``L`` lifetime (years); CRF the capital
recovery factor, so the overnight cost ``C_0`` is the annualised cost divided by CRF.

``arbitrageRevenue`` and ``energyMWh`` in the per-size rows stay on the
window basis (what the sweep actually simulated); ``annualArbitrageRevenue``
and ``annualMargin`` are the annualised figures that feed the NPV.

Capex basis: the capital costs here are user inputs on an ANNUAL basis and never
read the base network's ``capital_cost`` (which the builder may have scaled to the
modelled window), so the window-scaling contract does not apply and nothing is
pro-rated twice: capex enters NPV as an overnight amount at year 0.

The battery is simulated in a reduced single-bus network rebuilt from the
base run's snapshot weights and prices (positional snapshots), so pathway
(period, timestep) runs and plain runs take the same path.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import pandas as pd
import pypsa

from backend.app.adequacy.adequacy import electricity_buses
from backend.app.company.finance import _crf, _irr, _npv, _payback
from backend.pypsa.results.market import HOURS_PER_YEAR

_log = logging.getLogger("pypsa.solver")

_DEFAULT_LIFETIME = 15.0
_MAX_STEPS = 12
_MARKET = "__ess_market"
_EPS = 1e-9


def ess_cost_kwargs(cfg: dict[str, Any]) -> dict[str, Any]:
    """Keyword arguments for the cost / lifetime / loss inputs of ``essConfig``.

    The original keys (``bus``, ``maxHours``, ``capitalCostPerMW``, ``minSizeMW``,
    ``maxSizeMW``, ``steps``, ``roundTripEfficiency``) keep their meaning; these
    are additive and every one is optional::

        capitalCostPerMWh   annualised capital cost of energy capacity, per MWh per year
        fixedOmPerMWYear    fixed O&M, per MW per year
        variableCostPerMWh  cost per MWh discharged
        lifetimeYears       project life (absent / 0: 15 y default, reported in ``notes``)
        standingLoss        fraction of stored energy lost per hour (0-1)
    """
    def _num(key: str) -> float:
        try:
            return float(cfg.get(key) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "capital_cost_per_mwh": _num("capitalCostPerMWh"),
        "fixed_om_per_mw_year": _num("fixedOmPerMWYear"),
        "variable_cost_per_mwh": _num("variableCostPerMWh"),
        "lifetime_years": _num("lifetimeYears") or None,
        "standing_loss": _num("standingLoss"),
    }


def _electricity_candidates(base_network: pypsa.Network, columns: list[str]) -> list[str]:
    """Priced buses that belong to the electricity system (H2/gas/heat buses excluded)."""
    elec = electricity_buses(base_network)
    return [c for c in columns if str(c) in elec]


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
    capital_cost_per_mwh: float = 0.0,
    fixed_om_per_mw_year: float = 0.0,
    variable_cost_per_mwh: float = 0.0,
    lifetime_years: float | None = None,
    standing_loss: float = 0.0,
) -> dict[str, Any] | None:
    """Size sweep of a price-taker battery's arbitrage business case.

    Args:
        capital_cost_per_mw: annualised capital cost, currency per MW per year.
        capital_cost_per_mwh: annualised capital cost of energy capacity,
            currency per MWh per year (0 = none).
        fixed_om_per_mw_year: fixed O&M, currency per MW per year.
        variable_cost_per_mwh: cost per MWh discharged (PyPSA ``marginal_cost``).
        lifetime_years: project life; ``None`` / 0 uses ``_DEFAULT_LIFETIME``
            and says so in ``notes``.
        standing_loss: fraction of stored energy lost per hour (0-1).

    Returns:
        ``None`` when there are no marginal prices (a non-LP run) or the
        parameters are degenerate. Otherwise the sweep, plus ``notes`` listing
        any default or simplification applied.
    """
    if not getattr(base_network, "is_solved", False):
        return None
    mp = base_network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    notes: list[str] = []
    # Default to the most volatile *electricity* bus (best arbitrage) if none/invalid given.
    if not bus or bus not in mp.columns:
        candidates = _electricity_candidates(base_network, [str(c) for c in mp.columns])
        if not candidates:
            return None
        bus = str(mp[candidates].std().idxmax())
    if not bus or bus not in mp.columns:
        return None

    max_size_mw = max(0.0, float(max_size_mw))
    min_size_mw = max(0.0, float(min_size_mw))
    if max_size_mw <= 0:
        return None
    n_steps = max(1, min(int(steps or 6), _MAX_STEPS))
    eta = max(0.05, min(1.0, float(round_trip_efficiency or 0.9)))
    r = float(discount_rate or 0.0)
    if lifetime_years and float(lifetime_years) > 0:
        life = float(lifetime_years)
    else:
        life = _DEFAULT_LIFETIME
        notes.append(f"No lifetime given: {life:g} years assumed.")
    loss = max(0.0, min(0.99, float(standing_loss or 0.0)))
    fixed_om = max(0.0, float(fixed_om_per_mw_year or 0.0))
    energy_capex_rate = max(0.0, float(capital_cost_per_mwh or 0.0))
    var_cost = max(0.0, float(variable_cost_per_mwh or 0.0))
    hours_per_mw = float(max_hours)
    price_values = mp[bus].to_numpy(dtype=float)
    w_values = base_network.snapshot_weightings["objective"].to_numpy(dtype=float)
    # Modelled window (represented hours): window revenue × 8760/H = annual.
    H = float(w_values.sum())
    if H <= 0 or len(price_values) != len(w_values):
        return None
    annualize = HOURS_PER_YEAR / H
    pathway = isinstance(base_network.snapshots, pd.MultiIndex)
    if pathway:
        notes.append(
            "Pathway run: periods are concatenated into one dispatch; annual figures "
            "are the average over the modelled periods."
        )

    # One reduced network built from scratch: the chosen bus, a price-taker
    # market node and the battery, on positional snapshots carrying the base
    # run's weights. No component copying, so pathway runs are not a special case.
    try:
        net = pypsa.Network()
        net.set_snapshots(pd.RangeIndex(len(w_values)))
        for col in ("objective", "generators", "stores"):
            if col in base_network.snapshot_weightings.columns:
                net.snapshot_weightings[col] = base_network.snapshot_weightings[col].to_numpy(dtype=float)
        net.add("Bus", bus)
        net.add("Carrier", ["market", "battery"])
        net.add("Generator", _MARKET, bus=bus, carrier="market", p_nom=1.0e7, p_min_pu=-1.0, p_max_pu=1.0)
        net.generators_t.marginal_cost[_MARKET] = pd.Series(price_values, index=net.snapshots)
        net.add(
            "StorageUnit", "ess", bus=bus, carrier="battery", p_nom=1.0, max_hours=hours_per_mw,
            efficiency_store=math.sqrt(eta), efficiency_dispatch=math.sqrt(eta),
            standing_loss=loss, marginal_cost=var_cost, cyclic_state_of_charge=True,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("ESS: could not build reduced network: %s", exc)
        return None
    w = net.snapshot_weightings["objective"].to_numpy()

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
        revenue = float(((pd_ - pc) * price_values * w).sum())
        discharged = float((pd_ * w).sum())
        charged = float((pc * w).sum())
        energy_mwh = size * hours_per_mw
        avg_charge = float((pc * price_values * w).sum()) / charged if charged > _EPS else None
        avg_discharge = float((pd_ * price_values * w).sum()) / discharged if discharged > _EPS else None
        annualised_capex = capital_cost_per_mw * size + energy_capex_rate * energy_mwh
        overnight = annualised_capex / _crf(r, life) if annualised_capex > 0 else 0.0
        annual_revenue = revenue * annualize
        margin = annual_revenue - fixed_om * size
        cashflows = [-overnight] + [margin] * int(round(life))
        npv = _npv(r, cashflows)
        irr = _irr(cashflows)
        sizes.append({
            # energyMWh / arbitrageRevenue / throughputMWh are WINDOW totals
            # (H represented hours), not annual figures.
            "sizeMW": round(size, 2),
            "energyMWh": round(discharged, 1),
            "arbitrageRevenue": round(revenue, 2),
            "annualArbitrageRevenue": round(annual_revenue, 2),
            "annualFixedOm": round(fixed_om * size, 2),
            "annualMargin": round(margin, 2),
            "annualisedCapex": round(annualised_capex, 2),
            "npv": round(npv, 2),
            "irr": round(irr, 5) if irr is not None else None,
            "paybackYears": _payback(cashflows),
            "energyCapacityMWh": round(energy_mwh, 2),
            "chargedMWh": round(charged, 1),
            "throughputMWh": round(discharged, 1),
            "equivalentFullCycles": round(discharged / energy_mwh, 2) if energy_mwh > _EPS else 0.0,
            "annualEquivalentFullCycles": round(discharged * annualize / energy_mwh, 1) if energy_mwh > _EPS else 0.0,
            "avgChargePrice": round(avg_charge, 3) if avg_charge is not None else None,
            "avgDischargePrice": round(avg_discharge, 3) if avg_discharge is not None else None,
            "priceSpread": round(avg_discharge - avg_charge, 3)
            if avg_charge is not None and avg_discharge is not None else None,
        })

    if not sizes:
        return None
    best = max(sizes, key=lambda s: s["npv"])
    _log.info("ESS business case: %d sizes on bus %r, best %.1f MW (NPV %.0f)", len(sizes), bus, best["sizeMW"], best["npv"])
    return {
        "bus": bus,
        "maxHours": float(max_hours),
        "roundTripEfficiency": eta,
        "standingLoss": loss,
        "discountRate": r,
        "lifetimeYears": life,
        "currency": currency,
        "windowHours": round(H, 2),
        "annualisationFactor": round(annualize, 4),
        "pathway": pathway,
        "notes": notes,
        "sizes": sizes,
        "bestSizeMW": best["sizeMW"],
        "bestNpv": best["npv"],
    }
