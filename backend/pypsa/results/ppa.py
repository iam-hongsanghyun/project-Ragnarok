"""PPA contract modeler (PP1) — value a power purchase agreement against a run.

Attach a fixed-price PPA to an owner's generation (or a flat MW block) and value
it against the run's spot price (LMP): the energy, the spot value, the contract
value at the strike, and the net settlement from both sides. A Contract-for-
Difference view — the physical energy still clears at spot; the PPA is the
financial hedge on top, settling ``(strike − spot) × volume`` to the seller.

Seller gains when the strike beats spot (a price floor); the buyer gains when
spot beats the strike (a price cap). Composes with the owner column (F1/B1).
"""
from __future__ import annotations

import logging
from typing import Any

import pypsa

from .bid_strategy import _owner_generators

_log = logging.getLogger("pypsa.solver")


def build_ppa(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner: str,
    owner_column: str,
    volume_type: str,
    flat_mw: float,
    strike_price: float,
    currency: str,
) -> dict[str, Any] | None:
    """Value a fixed-price PPA against the run's LMP. ``None`` if not valuable.

    ``volume_type``: ``generation`` = the owner's hourly output (priced at its
    own bus); ``flat`` = a constant ``flat_mw`` block (priced at the mean LMP).
    """
    if not getattr(network, "is_solved", False):
        return None
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    w = network.snapshot_weightings["objective"].to_numpy()
    strike = float(strike_price or 0.0)

    energy = 0.0
    spot_value = 0.0
    if volume_type == "generation":
        column = (owner_column or "owner").strip() or "owner"
        gens = [g for g in _owner_generators(model, owner, column) if g in network.generators.index]
        if not gens:
            return None
        for g in gens:
            bus = str(network.generators.at[g, "bus"])
            if g not in network.generators_t.p.columns or bus not in mp.columns:
                continue
            p = network.generators_t.p[g].to_numpy()
            energy += float((p * w).sum())
            spot_value += float((p * mp[bus].to_numpy() * w).sum())
    else:  # flat block priced at the mean nodal price
        vol = max(0.0, float(flat_mw or 0.0))
        if vol <= 0:
            return None
        mean_price = mp.mean(axis=1).to_numpy()
        energy = float((vol * w).sum())
        spot_value = float((vol * mean_price * w).sum())

    if energy <= 1e-9:
        return None
    contract_value = strike * energy
    settlement = contract_value - spot_value  # CfD payment to the seller
    avg_spot = spot_value / energy

    _log.info(
        "PPA: %s vol=%s strike=%.1f energy=%.0f settlement=%.0f",
        owner or "flat", volume_type, strike, energy, settlement,
    )
    return {
        "owner": owner,
        "volumeType": volume_type,
        "currency": currency,
        "strikePrice": round(strike, 2),
        "energyMWh": round(energy, 2),
        "avgSpotPrice": round(avg_spot, 2),
        "spotValue": round(spot_value, 2),
        "contractValue": round(contract_value, 2),
        "sellerNet": round(settlement, 2),
        "buyerNet": round(-settlement, 2),
    }
