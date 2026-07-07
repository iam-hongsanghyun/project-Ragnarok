"""Transition-risk carbon-cost passthrough — REAL math, ported from climaterisk
``transition/carbon.py`` (field names camelCased to the shared contract).

Algorithm:
    $$E_i = \\text{reported Scope-1}, \\; \\text{else} \\; (V_i / 10^6) \\cdot f_{sector}$$
    $$C_i(t) = E_i \\cdot p(s, t)$$
    $$NPV_i = \\sum_t C_i(t) / (1 + r)^{t - t_0}$$
    ASCII: emissions_i = reported, else proxy = (value_i / 1e6) * sector_factor;
    carbon_cost_i(t) = emissions_i * carbon_price(scenario, t);
    NPV_i = sum_t cost_i(t) / (1 + r)^(t - base_year).

where ``E_i`` is annual Scope-1 emissions (tCO2e/yr), ``V_i`` the asset value (USD),
``f_sector`` the sector emission intensity (tCO2e per million USD), ``p(s, t)`` the NGFS
shadow carbon price for scenario ``s`` in year ``t`` (USD2010/tCO2, linearly interpolated
between the vendored trajectory anchors), ``r`` the discount rate (1/yr) and ``t_0`` the
trajectory base year. All values are treated in USD.
"""
from __future__ import annotations

from itertools import pairwise

from pydantic import BaseModel, Field

from .entities import Portfolio
from .libraries import load_libraries


class AssetCarbon(BaseModel):
    """Per-asset transition (carbon-cost) result."""

    assetId: str
    name: str
    emissionsTco2e: float
    emissionsSource: str = Field(description="'reported' | 'sector_proxy'.")
    annualCostByYear: dict[int, float]
    npv: float


class TransitionResult(BaseModel):
    """Portfolio transition-risk result for one NGFS scenario."""

    scenario: str
    discountRate: float
    baseYear: int
    years: list[int]
    totalCostByYear: list[float] = Field(default_factory=list)
    totalNpv: float = 0.0
    perAsset: list[AssetCarbon] = Field(default_factory=list)
    method: str = ""
    detail: str | None = None


def _interpolate(points: dict[int, float], year: int) -> float:
    """Linear interpolation of a {year: price} series, clamped at the ends."""
    years = sorted(points)
    if year <= years[0]:
        return points[years[0]]
    if year >= years[-1]:
        return points[years[-1]]
    for lo, hi in pairwise(years):
        if lo <= year <= hi:
            frac = (year - lo) / (hi - lo)
            return points[lo] + frac * (points[hi] - points[lo])
    return points[years[-1]]


def compute_transition_risk(
    portfolio: Portfolio,
    scenario: str | None = None,
    discount_rate: float | None = None,
) -> TransitionResult:
    """Compute the portfolio's carbon-cost trajectory and NPV under an NGFS scenario.

    Args:
        portfolio: The session portfolio (assets carry reported emissions or a sector).
        scenario: NGFS scenario id; defaults to ``portfolio.scenario.transition``.
        discount_rate: Discount rate (1/yr); defaults to ``portfolio.scenario.discountRate``.

    Returns:
        A :class:`TransitionResult` with per-asset and aggregate carbon costs by year.
    """
    libraries = load_libraries()
    scenario_id = scenario or portfolio.scenario.transition
    r = portfolio.scenario.discountRate if discount_rate is None else discount_rate

    price_table = libraries["carbon_prices"]["prices"]
    if scenario_id not in price_table:
        return TransitionResult(
            scenario=scenario_id,
            discountRate=r,
            baseYear=0,
            years=[],
            detail=f"no carbon-price trajectory for scenario '{scenario_id}'",
        )
    points = {int(y): float(p) for y, p in price_table[scenario_id].items()}
    base_year = min(points)
    end_year = max(points)
    years = list(range(base_year, end_year + 1))

    factors = {
        s["id"]: float(s["emission_intensity_tco2e_per_musd"])
        for s in libraries["sectors"]["sectors"]
    }

    per_asset: list[AssetCarbon] = []
    total_by_year = [0.0 for _ in years]
    total_npv = 0.0
    for asset in portfolio.assets:
        if asset.annualEmissionsTco2e is not None:
            emissions = asset.annualEmissionsTco2e
            source = "reported"
        else:
            sector = asset.sector or portfolio.scenario.sector
            emissions = (asset.value / 1_000_000.0) * factors.get(sector, 0.0)
            source = "sector_proxy"

        annual_cost: dict[int, float] = {}
        npv = 0.0
        for i, year in enumerate(years):
            cost = emissions * _interpolate(points, year)
            annual_cost[year] = cost
            total_by_year[i] += cost
            npv += cost / ((1.0 + r) ** (year - base_year))
        total_npv += npv
        per_asset.append(
            AssetCarbon(
                assetId=asset.id,
                name=asset.name,
                emissionsTco2e=emissions,
                emissionsSource=source,
                annualCostByYear=annual_cost,
                npv=npv,
            )
        )

    return TransitionResult(
        scenario=scenario_id,
        discountRate=r,
        baseYear=base_year,
        years=years,
        totalCostByYear=total_by_year,
        totalNpv=total_npv,
        perAsset=per_asset,
        method=(
            "Carbon-cost passthrough: emissions x NGFS shadow carbon price, "
            f"NPV discounted at {r:.1%}. Emissions reported where given, "
            "else proxied from sector intensity."
        ),
    )
