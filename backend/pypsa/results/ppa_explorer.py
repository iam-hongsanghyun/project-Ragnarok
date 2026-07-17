"""PPA opportunity explorer (DW4) — rank contract shapes by capture price.

A companion to the single-PPA valuation (PP1): using the same owner / block /
strike the user picked, this values the *alternative* contract shapes against the
run's LMP and ranks them, so a seller (or buyer) can see which shape captures the
most value:

  • Generation (as-produced) — the owner's hourly output, priced at its bus LMP.
    A weather-driven asset captures the price in the hours it actually runs.
  • Flat block (24/7)         — a constant block, priced at the mean nodal price.
  • Peak block (top hours)    — the same block delivered only in the highest-price
    quartile, so it captures the peak.

The discriminator is the **capture price** (volume-weighted average spot the
shape earns): a solar generation PPA captures less than a peak block, so its fair
strike is lower. No new solve — a read on the solved LMP; composes with PP1.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pypsa

from .ppa import build_ppa


def _peak_block(
    network: pypsa.Network, flat_mw: float, strike: float, quantile: float = 0.75
) -> dict[str, Any] | None:
    """A flat block delivered only in the top-``(1-quantile)`` price hours.

    "Top hours" is on the represented-hours basis: snapshots are taken in
    descending price order until they cover ``(1-quantile)`` of the total
    snapshot weight, so a weighted (stride/segment) run still delivers into
    25% of the modeled hours rather than 25% of the snapshot count.

    Algorithm:
        $$ S^* = \\min k : \\sum_{j \\le k} w_{(j)} \\ge (1 - q) \\sum_t w_t $$
        ASCII: sort snapshots by price descending; accumulate weights until
        cum >= (1-q) * W; deliver only in those snapshots.
        Symbols: w_t snapshot weight (h), q the quantile (-), W = Σ w_t (h),
        (j) the j-th snapshot in descending price order.
    """
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    vol = max(0.0, float(flat_mw or 0.0))
    if vol <= 0:
        return None
    w = network.snapshot_weightings["objective"].to_numpy(dtype=float)
    price = mp.mean(axis=1).to_numpy()
    if price.size == 0:
        return None
    # Weighted quantile: top price hours until 25% of the total weight is covered.
    order = np.argsort(-price, kind="stable")
    target = (1.0 - float(quantile)) * float(w.sum())
    cum = np.cumsum(w[order])
    k = int(np.searchsorted(cum, target - 1e-9)) + 1
    mask = np.zeros(price.size)
    mask[order[:k]] = 1.0
    energy = float((vol * w * mask).sum())
    if energy <= 1e-9:
        return None
    spot_value = float((vol * price * w * mask).sum())
    avg_spot = spot_value / energy
    seller = strike * energy - spot_value
    return {
        "energyMWh": round(energy, 2),
        "avgSpotPrice": round(avg_spot, 2),
        "sellerNet": round(seller, 2),
        "buyerNet": round(-seller, 2),
    }


def build_ppa_explorer(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner: str,
    owner_column: str,
    flat_mw: float,
    strike_price: float,
    currency: str,
) -> dict[str, Any] | None:
    """Value + rank candidate PPA shapes at the given strike. ``None`` if none valuable."""
    if not getattr(network, "is_solved", False):
        return None
    strike = float(strike_price or 0.0)

    shapes: list[dict[str, Any]] = []

    def _add(label: str, valuation: dict[str, Any] | None) -> None:
        if valuation:
            shapes.append({
                "shape": label,
                "energyMWh": valuation["energyMWh"],
                "avgSpotPrice": valuation["avgSpotPrice"],
                "sellerNet": valuation["sellerNet"],
                "buyerNet": valuation["buyerNet"],
            })

    _add(
        "Generation (as-produced)",
        build_ppa(network, model, owner=owner, owner_column=owner_column,
                  volume_type="generation", flat_mw=0.0, strike_price=strike, currency=currency),
    )
    _add(
        "Flat block (24/7)",
        build_ppa(network, model, owner=owner, owner_column=owner_column,
                  volume_type="flat", flat_mw=flat_mw, strike_price=strike, currency=currency),
    )
    _add("Peak block (top 25% hours)", _peak_block(network, flat_mw, strike))

    if not shapes:
        return None
    # Rank by capture price (volume-weighted spot earned): the seller's discriminator.
    shapes.sort(key=lambda s: s["avgSpotPrice"], reverse=True)
    return {"currency": currency, "strikePrice": round(strike, 2), "shapes": shapes}
