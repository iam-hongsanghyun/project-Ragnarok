"""Consolidated per-company financial statement (F1+F2 → one P&L).

F1 (``company.py``) gives per-company capacity / energy / revenue / emissions;
F2 (``finance.py``) gives NPV / IRR / payback / DSCR. Neither shows the *annual
operating statement* an analyst reads top-to-bottom:

    revenue
      − carbon cost           (emissions × carbon price)
      − fuel + variable O&M    (dispatch cost with carbon backed out)
      = gross margin
      − annualised capex / fixed O&M
      = EBIT
      − interest               (on the debt share, if any)
      = net operating result

This builder produces exactly that line-item statement per company, from the
solved network — no extra solve. Revenue and dispatch are the competitive
benchmark (LMP × dispatch), consistent with F0/F1/F2. The fuel / variable
cost is PyPSA's ``n.statistics.opex(marginal_cost)`` and the carbon cost is the carbon-pricing module's
declared objective term evaluated at the solution (with each generator's own, possibly
time-varying, efficiency), so the two are separate quantities and never double-count.

Algorithm (per company, summed over its assets and snapshots t with weights w):
    $$\\text{rev} = \\frac{8760}{H} \\sum_t w_t\\, \\pi_{b(a),t}\\, p_{a,t}, \\quad
      \\text{carbon} = \\frac{8760}{H} \\sum_t w_t\\, p_{a,t}\\, \\frac{e_c}{\\eta_{a,t}}\\, P_{CO_2,t},
      \\quad \\text{fuelVom} = \\frac{8760}{H}\\,\\text{opex}^{PyPSA}_{marginal\\_cost}$$
    ASCII: rev = (8760/H)·Σ w·π·p ; carbon = (8760/H)·Σ w·p·(co2/η_t)·co2price_t (the carbon-pricing
    module's objective term at the solution) ; fuelVom = (8760/H)·n.statistics.opex(marginal_cost) ; interest = gearing·(capex_annual/CRF(i,tenor))·i.

    Symbols: π = nodal price [currency/MWh], p = dispatch [MW], e_a = electrical
    emission factor [tCO2/MWh] (co2/η), P_CO2 = carbon price [currency/tCO2],
    opex = (8760/H)·Σ w·mc·p [currency/yr], capex_annual = (n.statistics.capex +
    n.statistics.fom) / n.nyears [currency/yr], H = Σ w [h], i = interest rate [-].

Basis: the solve covers a window of H represented hours, not a year, so every
flow line (revenue, carbon, fuel/VOM, energy, emissions) is annualised by
× 8760/H to sit on the same **annual** basis as ``capexAnnual`` — the statement
is a genuine annual P&L as titled. Interest is charged on the outstanding debt
principal (gearing × overnight capex ≈ gearing × capexAnnual / CRF(i, tenor)),
not on the annuity itself; it needs ``tenorYears`` > 0 to reconstruct the
principal and is otherwise omitted (0).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from backend.app import carbon_pricing

from backend.app.emissions.accounting import primary_energy_emissions
from backend.app.company.finance import _crf, storage_assets
from backend.pypsa.results.market import HOURS_PER_YEAR
from backend.pypsa.results.stat_metrics import fixed_cost_of, fixed_cost_table, generator_operating_cost

_log = logging.getLogger("pypsa.solver")


def _owner_map(model: dict[str, list[dict[str, Any]]], sheet: str, column: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in model.get(sheet, []) or []:
        name = str(row.get("name", "")).strip()
        owner = str(row.get(column, "")).strip()
        if name and owner:
            out[name] = owner
    return out


def build_company_statement(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner_column: str,
    currency: str,
    emissions_factors: dict[str, float],
    debt: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Per-company annual P&L from the solved network.

    Args:
        network: A solved network with nodal prices (an LP run).
        model: Raw model dict — source of the owner tags.
        owner_column: Which model column holds the owner tag.
        currency: Currency symbol (passthrough).
        emissions_factors: carrier → tCO2/MWh (fuel basis), for the emissions line.
        debt: Optional ``{gearing, interestRate, tenorYears}`` for the interest line.

    Returns:
        ``{ownerColumn, currency, carbonPrice, companies: [...], totals}`` or
        ``None`` when no owner-tagged asset has a price signal.
    """
    if not getattr(network, "is_solved", False):
        return None
    column = (owner_column or "owner").strip() or "owner"
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    weights = network.snapshot_weightings["objective"].to_numpy()
    # Modelled window (represented hours): window flows × 8760/H = annual, the
    # basis capexAnnual is already on.
    H = float(weights.sum())
    if H <= 0:
        return None
    annualize = HOURS_PER_YEAR / H
    # Fuel / variable cost is PyPSA's `n.statistics.opex` (marginal_cost only); the carbon cost is the
    # carbon-pricing module's declared objective term evaluated at the solution, with the generator's
    # OWN (possibly time-varying) efficiency. Both on the modelled-window basis, as every line here.
    cfg = carbon_pricing.plan_of(network)
    co2_price = (
        float(carbon_pricing.price_series(cfg, network.snapshots).mean()) if cfg is not None else 0.0
    )
    fuel_by_gen = generator_operating_cost(network, weighted=False)
    carbon_by_gen = carbon_pricing.carbon_cost_by_generator(network, cfg, period_weighted=False)
    gen_fixed = fixed_cost_table(network, ["Generator"])

    gearing = float((debt or {}).get("gearing", 0.0) or 0.0)
    interest = float((debt or {}).get("interestRate", 0.0) or 0.0)
    tenor = float((debt or {}).get("tenorYears", 0.0) or 0.0)

    gen_owner = _owner_map(model, "generators", column)
    sto_owner = _owner_map(model, "storage_units", column)
    store_owner = _owner_map(model, "stores", column)
    if not gen_owner and not sto_owner and not store_owner:
        return None

    def _bucket() -> dict[str, float]:
        return {
            "revenue": 0.0, "energyMWh": 0.0, "carbonCost": 0.0, "fuelVomCost": 0.0,
            "capexAnnual": 0.0, "emissionsTonnes": 0.0,
        }

    acc: dict[str, dict[str, float]] = {}

    for g in network.generators.index:
        company = gen_owner.get(str(g))
        if not company:
            continue
        bus = str(network.generators.at[g, "bus"])
        if bus not in mp.columns:
            continue
        if g not in network.generators_t.p.columns:
            continue
        b = acc.setdefault(company, _bucket())
        p = network.generators_t.p[g].to_numpy()
        pi = mp[bus].to_numpy()
        energy = float((p * weights).sum())
        b["revenue"] += float((p * pi * weights).sum())
        b["energyMWh"] += energy
        b["carbonCost"] += float(carbon_by_gen.get(str(g), 0.0))
        b["fuelVomCost"] += float(fuel_by_gen.get(str(g), 0.0))
        # n.statistics: (capex + fom) / n.nyears, installed and expanded capacity alike.
        b["capexAnnual"] += fixed_cost_of(gen_fixed, "Generator", str(g))["annual"]

    # Storage: StorageUnit and Store + Link on the same rule finance.py uses —
    # capex only for extendable components, marginal_cost_storage and spill_cost
    # counted in the variable cost.
    def _price(bus: str) -> np.ndarray | None:
        return mp[bus].to_numpy() if bus in mp.columns else None

    for a in storage_assets(
        network, _price, weights, storage_units=list(sto_owner), stores=list(store_owner),
    ):
        company = (sto_owner if a.sheet == "storage_units" else store_owner).get(a.name)
        if not company:
            continue
        b = acc.setdefault(company, _bucket())
        b["revenue"] += a.revenue
        b["energyMWh"] += a.discharged_mwh
        b["fuelVomCost"] += a.op_cost
        b["capexAnnual"] += a.capex_annual

    # Emissions line (RB10): PyPSA primary_energy accounting - generators p/eta*ef (signed) plus
    # non-cyclic storage depletion - allocated to the owners, so the company lines plus
    # ``unassignedEmissionsTonnes`` equal the system total x 8760/H. The carbon COST line above
    # stays on the clipped per-generator adder the solve priced.
    pe = primary_energy_emissions(network, emissions_factors)
    unassigned = 0.0
    for series, owners in ((pe.generators, gen_owner), (pe.storage_units, sto_owner), (pe.stores, store_owner)):
        for name, tco2 in series.items():
            company = owners.get(str(name))
            if company and company in acc:
                acc[company]["emissionsTonnes"] += float(tco2)
            elif company:
                acc.setdefault(company, _bucket())["emissionsTonnes"] += float(tco2)
            else:
                unassigned += float(tco2)

    if not acc:
        return None

    # Annualise the window flow lines onto capexAnnual's basis (× 8760/H).
    for v in acc.values():
        for key in ("revenue", "energyMWh", "carbonCost", "fuelVomCost", "emissionsTonnes"):
            v[key] *= annualize

    companies: list[dict[str, Any]] = []
    for company, v in acc.items():
        variable_cost = v["carbonCost"] + v["fuelVomCost"]
        gross_margin = v["revenue"] - variable_cost
        ebit = gross_margin - v["capexAnnual"]
        # Interest is rate × outstanding principal, not rate × annuity. The
        # debt principal is reconstructed from the annualised capex via the
        # inverse capital recovery factor over the loan tenor (year-1 proxy,
        # mirroring finance.py's DSCR); without a tenor the principal is
        # unknowable, so the line is omitted.
        if gearing > 0 and tenor > 0:
            principal = gearing * v["capexAnnual"] / _crf(interest, tenor)
            interest_annual = principal * interest
        else:
            interest_annual = 0.0
        net = ebit - interest_annual
        companies.append({
            "company": company,
            "revenue": round(v["revenue"], 2),
            "energyMWh": round(v["energyMWh"], 2),
            "carbonCost": round(v["carbonCost"], 2),
            "fuelVomCost": round(v["fuelVomCost"], 2),
            "variableCost": round(variable_cost, 2),
            "grossMargin": round(gross_margin, 2),
            "capexAnnual": round(v["capexAnnual"], 2),
            "ebit": round(ebit, 2),
            "interest": round(interest_annual, 2),
            "netMargin": round(net, 2),
            "emissionsTonnes": round(v["emissionsTonnes"], 2),
        })

    companies.sort(key=lambda c: c["netMargin"], reverse=True)

    def _tot(key: str) -> float:
        return round(sum(c[key] for c in companies), 2)

    totals = {
        k: _tot(k) for k in
        ("revenue", "carbonCost", "fuelVomCost", "variableCost", "grossMargin",
         "capexAnnual", "ebit", "interest", "netMargin", "emissionsTonnes", "energyMWh")
    }
    _log.info("company statement: %d companies (carbon=%.1f)", len(companies), co2_price)
    return {
        "ownerColumn": column,
        "currency": currency,
        "carbonPrice": co2_price,
        "companies": companies,
        "totals": totals,
        "unassignedEmissionsTonnes": round(unassigned * annualize, 2),
    }
