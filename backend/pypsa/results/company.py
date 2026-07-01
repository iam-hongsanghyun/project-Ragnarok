"""Company / owner dimension (F1) — per-owner KPIs from a solved network.

Every analytics surface otherwise treats the system as one consolidated entity.
This groups the solved assets by their owner tag (a user-chosen model column —
``owner``, ``Company``, …) and reports each company's capacity, energy,
competitive-benchmark revenue (LMP × dispatch, the same signal as F0) and
emissions. It bridges dispatch results to the company-level financial model (F2).
"""
from __future__ import annotations

import logging
from typing import Any

import pypsa

from ..utils.emissions import per_generator_emission_factor

_log = logging.getLogger("pypsa.solver")

_UNASSIGNED = "(unassigned)"


def _owner_map(
    model: dict[str, list[dict[str, Any]]], sheet: str, column: str,
) -> dict[str, str]:
    """name -> owner tag for one component sheet (blank tags omitted)."""
    out: dict[str, str] = {}
    for row in model.get(sheet, []) or []:
        name = str(row.get("name", "")).strip()
        owner = str(row.get(column, "")).strip()
        if name and owner:
            out[name] = owner
    return out


def build_company_breakdown(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner_column: str,
    currency: str,
    emissions_factors: dict[str, float],
) -> dict[str, Any] | None:
    """Per-company capacity / energy / revenue / emissions from the solved network.

    Args:
        network: A solved network.
        model: The raw model dict — source of the owner tags.
        owner_column: Which model column holds the owner tag.
        currency: Currency symbol (passthrough for the UI).
        emissions_factors: carrier -> tCO2/MWh, for generator emissions.

    Returns:
        ``{ownerColumn, currency, companies: [...], untaggedCount}`` or ``None``
        when no asset carries an owner tag (nothing to break down).
    """
    if not getattr(network, "is_solved", False):
        return None
    column = (owner_column or "owner").strip() or "owner"
    gen_owner = _owner_map(model, "generators", column)
    sto_owner = _owner_map(model, "storage_units", column)
    if not gen_owner and not sto_owner:
        return None

    weights = network.snapshot_weightings["objective"].to_numpy()
    # Per-generator co2_emissions / η (thermal basis, M3).
    eff_ef = per_generator_emission_factor(network, emissions_factors)
    mp = network.buses_t.marginal_price
    has_lmp = mp is not None and not mp.empty

    def _price(bus: str):
        if has_lmp and bus in mp.columns:
            return mp[bus].to_numpy()
        return None

    # company -> accumulator
    acc: dict[str, dict[str, float]] = {}

    def _bucket(name: str) -> dict[str, float]:
        return acc.setdefault(name, {
            "capacityMW": 0.0, "energyMWh": 0.0, "revenue": 0.0,
            "emissionsTonnes": 0.0, "generatorCount": 0.0, "storageCount": 0.0,
        })

    untagged = 0

    for g in network.generators.index:
        owner = gen_owner.get(str(g))
        if not owner:
            untagged += 1
            continue
        b = _bucket(owner)
        bus = str(network.generators.at[g, "bus"])
        p = network.generators_t.p[g].to_numpy() if g in network.generators_t.p.columns else None
        energy = float((p * weights).sum()) if p is not None else 0.0
        pi = _price(bus)
        b["capacityMW"] += float(network.generators.at[g, "p_nom_opt"])
        b["energyMWh"] += energy
        if pi is not None and p is not None:
            b["revenue"] += float((p * pi * weights).sum())
        b["emissionsTonnes"] += energy * float(eff_ef.get(g, 0.0))
        b["generatorCount"] += 1

    for s in network.storage_units.index:
        owner = sto_owner.get(str(s))
        if not owner:
            untagged += 1
            continue
        b = _bucket(owner)
        bus = str(network.storage_units.at[s, "bus"])
        pd_ = network.storage_units_t.p_dispatch[s].to_numpy() if s in network.storage_units_t.p_dispatch.columns else None
        pc = network.storage_units_t.p_store[s].to_numpy() if s in network.storage_units_t.p_store.columns else None
        energy = float((pd_ * weights).sum()) if pd_ is not None else 0.0
        pi = _price(bus)
        b["capacityMW"] += float(network.storage_units.at[s, "p_nom_opt"])
        b["energyMWh"] += energy
        if pi is not None and pd_ is not None and pc is not None:
            b["revenue"] += float(((pd_ - pc) * pi * weights).sum())
        b["storageCount"] += 1

    if not acc:
        return None

    companies = [
        {
            "company": name,
            "capacityMW": round(v["capacityMW"], 3),
            "energyMWh": round(v["energyMWh"], 2),
            "revenue": round(v["revenue"], 2) if has_lmp else None,
            "emissionsTonnes": round(v["emissionsTonnes"], 2),
            "generatorCount": int(v["generatorCount"]),
            "storageCount": int(v["storageCount"]),
        }
        for name, v in acc.items()
    ]
    # Most material companies first (by capacity).
    companies.sort(key=lambda c: c["capacityMW"], reverse=True)
    _log.info("company breakdown: %d companies on column %r (%d untagged)", len(companies), column, untagged)
    return {
        "ownerColumn": column,
        "currency": currency,
        "companies": companies,
        "untaggedCount": untagged,
    }
