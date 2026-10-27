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

import numpy as np
import pypsa

from ..utils.emissions import primary_energy_emissions
from .finance import storage_assets

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
        emissions_factors: carrier -> tCO2/MWh_thermal; emissions follow the
            ``primary_energy`` accounting of ``utils.emissions.primary_energy_emissions``.

    Returns:
        ``{ownerColumn, currency, companies: [...], untaggedCount, unassignedEmissionsTonnes}`` or ``None``
        when no asset carries an owner tag (nothing to break down).
    """
    if not getattr(network, "is_solved", False):
        return None
    column = (owner_column or "owner").strip() or "owner"
    gen_owner = _owner_map(model, "generators", column)
    sto_owner = _owner_map(model, "storage_units", column)
    store_owner = _owner_map(model, "stores", column)
    if not gen_owner and not sto_owner and not store_owner:
        return None

    weights = network.snapshot_weightings["objective"].to_numpy()
    # Emissions on PyPSA's primary_energy basis (RB10): generators p/η·ef (signed, period-weighted)
    # plus non-cyclic StorageUnit/Store depletion, each allocated to its owner, so the company
    # figures plus ``unassignedEmissionsTonnes`` equal the system total exactly.
    pe = primary_energy_emissions(network, emissions_factors)
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
            "storageEnergyMWh": 0.0,
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
        b["generatorCount"] += 1

    # Storage: StorageUnit and Store + Link, through the one shared rule.
    def _storage_price(bus: str) -> np.ndarray | None:
        return mp[bus].to_numpy() if has_lmp and bus in mp.columns else None

    for a in storage_assets(
        network, _storage_price, weights, storage_units=list(network.storage_units.index),
        stores=list(network.stores.index),
    ):
        owner = (sto_owner if a.sheet == "storage_units" else store_owner).get(a.name)
        if not owner:
            untagged += 1
            continue
        b = _bucket(owner)
        b["capacityMW"] += a.capacity_mw
        b["energyMWh"] += a.discharged_mwh
        b["revenue"] += a.revenue
        b["storageCount"] += 1
        b["storageEnergyMWh"] += a.energy_mwh

    # Emissions: every emitting asset's primary-energy term goes to its owner (a stock that
    # depletes is the owner's emission even if the asset has no price signal).
    unassigned = 0.0
    for series, owners in (
        (pe.generators, gen_owner), (pe.storage_units, sto_owner), (pe.stores, store_owner),
    ):
        for name, tco2 in series.items():
            owner = owners.get(str(name))
            if owner:
                _bucket(owner)["emissionsTonnes"] += float(tco2)
            else:
                unassigned += float(tco2)

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
            "storageEnergyMWh": round(v["storageEnergyMWh"], 2),
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
        "unassignedEmissionsTonnes": round(unassigned, 2),
    }
