"""Physical-risk engine — Phase 0 STUB.

Returns deterministic canned results in the exact :class:`PhysicalRunOutput`
shape, so the frontend and orchestration can be built end-to-end before the real
CLIMADA compute exists. There is NO randomness: every number is a pure function
of the asset's value, its index in the portfolio, and a per-peril factor.

The real compute will run in a separate conda env (CLIMADA cannot be imported
here), invoked over a request.json / result.json contract — see the ``_run_engine``
seam below and climaterisk ``engines/base.py`` for the shapes to mirror.
"""
from __future__ import annotations

import os

from .entities import (
    AssetImpact,
    FreqCurve,
    PhysicalRunOutput,
    PhysicalRunResult,
    Portfolio,
    Scenario,
)

# Per-peril severity multipliers applied to each asset's value to get its EAI in
# the stub. Ordering is stable so results are reproducible run-to-run.
_PERIL_FACTOR: dict[str, float] = {
    "tropical_cyclone": 0.0120,
    "river_flood": 0.0085,
    "wildfire": 0.0060,
    "earthquake": 0.0040,
    "windstorm": 0.0070,
}
_DEFAULT_FACTOR = 0.0050

# Return periods (years) for the exceedance curve, shared across perils.
_RETURN_PERIODS: tuple[float, ...] = (2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0)

# A monotone loss-vs-EAI shape: loss at return period ``rp`` = eai * this factor.
# Rises with the return period (rarer events, larger loss).
_RP_LOSS_SHAPE: tuple[float, ...] = (0.5, 1.5, 3.0, 6.0, 10.0, 16.0, 30.0)

# Future-vs-present climate uplift per peril (percent), for ``deltaPct``.
_PERIL_DELTA_PCT: dict[str, float] = {
    "tropical_cyclone": 18.0,
    "river_flood": 12.0,
    "wildfire": 22.0,
    "earthquake": 0.0,  # not climate-driven
    "windstorm": 8.0,
}


def _asset_eai(value: float, index: int, factor: float) -> float:
    """Deterministic per-asset expected annual impact.

    The ``index`` term gives inter-asset variation WITHOUT randomness: a small,
    bounded, reproducible spread around the value × peril-factor baseline.
    """
    spread = 1.0 + 0.05 * (index % 5)  # 1.00 … 1.20, cycling by position
    return round(max(0.0, value) * factor * spread, 2)


def _run_engine(portfolio: Portfolio, perils: list[str], scenario: Scenario) -> PhysicalRunOutput:
    """Compute the run output.

    STUB implementation. The seam:

    # TODO(worker): replace with conda CLIMADA worker call over request.json/
    # result.json (see climaterisk engines/base.py). Env gate:
    # RAGNAROK_CLIMADA_WORKER. When set, serialise ``portfolio`` + ``scenario``
    # to request.json, spawn the worker subprocess, and read back result.json in
    # this same PhysicalRunOutput shape instead of the canned numbers below.
    """
    if os.environ.get("RAGNAROK_CLIMADA_WORKER"):
        # Real worker path is not wired in Phase 0; fall through to the stub so
        # the capability degrades gracefully rather than erroring.
        pass

    results: list[PhysicalRunResult] = []
    for peril in perils:
        factor = _PERIL_FACTOR.get(peril, _DEFAULT_FACTOR)
        per_asset = [
            AssetImpact(assetId=a.id, eai=_asset_eai(a.value, i, factor))
            for i, a in enumerate(portfolio.assets)
        ]
        aai_agg = round(sum(p.eai for p in per_asset), 2)
        losses = [round(aai_agg * shape, 2) for shape in _RP_LOSS_SHAPE]
        results.append(
            PhysicalRunResult(
                peril=peril,
                perAsset=per_asset,
                aaiAgg=aai_agg,
                freqCurve=FreqCurve(returnPeriods=list(_RETURN_PERIODS), losses=losses),
                deltaPct=_PERIL_DELTA_PCT.get(peril, 0.0),
            )
        )

    currency = portfolio.assets[0].currency if portfolio.assets else "USD"
    return PhysicalRunOutput(currency=currency, perils=results)


def run_physical(
    portfolio: Portfolio, perils: list[str], scenario: Scenario
) -> PhysicalRunOutput:
    """Run the physical-risk analysis for a portfolio under one scenario.

    Args:
        portfolio: The session portfolio (one exposure point per asset).
        perils: Peril ids to evaluate (values of :class:`Peril`).
        scenario: Climate scenario context (``rcp`` + ``horizon``).

    Returns:
        A :class:`PhysicalRunOutput` with one :class:`PhysicalRunResult` per peril.
    """
    return _run_engine(portfolio, perils, scenario)
