"""Physical-risk engine — real CLIMADA worker when attached, deterministic stub otherwise.

The stub returns deterministic canned results in the exact result shapes of
climaterisk ``engines/base.py`` (camelCased — see :mod:`.entities`), so the
frontend and orchestration work end-to-end without conda. There is NO randomness:
every stub number is a pure function of the asset's value, its index in the
portfolio, and a per-peril factor.

The REAL compute runs in a separate Python 3.11 conda env (CLIMADA cannot be
imported here), invoked over a request.json / result.json subprocess contract —
see :mod:`.worker`. All run kinds (physical, uncertainty, cost-benefit,
supply-chain, calibration, forecast) funnel through :func:`run_kind`, the single
seam where the worker takes over: when the worker env exists (and the
``RAGNAROK_CLIMADA_WORKER`` gate allows it) the run goes to CLIMADA; on ANY
worker failure the run falls back to the stub with the reason recorded on the
result's ``detail``.
"""
from __future__ import annotations

from typing import Any

from . import worker
from .entities import (
    RUN_KINDS,
    AssetImpact,
    CalibrationResult,
    CostBenefitResult,
    ForecastResult,
    ForecastSeriesPoint,
    FreqCurve,
    MeasureResult,
    MeasureSpec,
    PhysicalRunOutput,
    PhysicalRunResult,
    Portfolio,
    Scenario,
    SupplyChainResult,
    SupplyChainSector,
    UncertaintyPerilBand,
    UncertaintyResult,
)

# Note appended to every worker-gated stub result so the frontend can flag it.
_STUB_DETAIL = "Deterministic stub result — CLIMADA worker not attached."

# Per-peril severity multipliers applied to each asset's value to get its EAI in
# the stub. Ordering is stable so results are reproducible run-to-run. Covers the
# Phase-0 ids plus the vendored perils library; anything else takes the default.
_PERIL_FACTOR: dict[str, float] = {
    "tropical_cyclone": 0.0120,
    "river_flood": 0.0085,
    "wildfire": 0.0060,
    "earthquake": 0.0040,
    "windstorm": 0.0070,
    "european_windstorm": 0.0070,
    "coastal_flood": 0.0080,
    "heatwave": 0.0030,
    "drought": 0.0035,
    "crop_yield": 0.0025,
    "low_flow": 0.0020,
    "hail": 0.0045,
    "tc_surge": 0.0090,
    "landslide": 0.0030,
    "tc_rain": 0.0055,
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
    "european_windstorm": 8.0,
    "coastal_flood": 25.0,
    "heatwave": 30.0,
    "drought": 20.0,
    "crop_yield": 15.0,
    "low_flow": 18.0,
    "hail": 6.0,
    "tc_surge": 20.0,
    "landslide": 10.0,
    "tc_rain": 14.0,
}


def _asset_eai(value: float, index: int, factor: float) -> float:
    """Deterministic per-asset expected annual impact.

    The ``index`` term gives inter-asset variation WITHOUT randomness: a small,
    bounded, reproducible spread around the value × peril-factor baseline.
    """
    spread = 1.0 + 0.05 * (index % 5)  # 1.00 … 1.20, cycling by position
    return round(max(0.0, value) * factor * spread, 2)


def _run_engine(portfolio: Portfolio, perils: list[str], scenario: Scenario) -> PhysicalRunOutput:
    """Compute the STUB run output (the worker path lives in :func:`run_kind`)."""
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


# ── worker-gated run kinds (STUB results, shapes faithful to engines/base.py) ──

# Trajectory base year for NPV horizons (matches the vendored NGFS price base year).
_BASE_YEAR = 2025

# Default adaptation-measure set when a cost-benefit run supplies none: (name,
# cost as a fraction of total portfolio value, fractional damage reduction).
_DEFAULT_MEASURES: tuple[tuple[str, float, float], ...] = (
    ("Flood defences", 0.005, 0.25),
    ("Structural retrofit", 0.015, 0.40),
    ("Early-warning system", 0.001, 0.10),
    ("Parametric insurance", 0.008, 0.30),
)

# Deterministic Sobol-style sensitivity shares for the uncertainty stub. Keys are
# engine parameter ids (matching the worker's calibratable parameters).
_SENSITIVITY_ST: dict[str, float] = {"v_half": 0.42, "exposure_value": 0.33, "hazard_frequency": 0.25}
_SENSITIVITY_S1: dict[str, float] = {"v_half": 0.34, "exposure_value": 0.26, "hazard_frequency": 0.20}

# Forecast stub: share of the near-term expected impact landing in each season.
_FORECAST_WEIGHTS: tuple[float, ...] = (0.10, 0.25, 0.30, 0.20, 0.15)

# Emanuel (2011) TC default v_half (m/s) — the calibration stub's starting point.
_TC_V_HALF_INITIAL = 74.7


def run_uncertainty(
    portfolio: Portfolio, perils: list[str], scenario: Scenario, n_samples: int
) -> UncertaintyResult:
    """STUB Monte-Carlo uncertainty: p5/p50/p95 bands derived from the physical stub.

    Bands are fixed fractions of the deterministic AAI (p5 = 80%, p95 = 140%), with a
    linearly spaced ``distribution`` of ``n_samples`` values between them.
    """
    physical = _run_engine(portfolio, perils, scenario)
    n = max(2, n_samples)
    bands: list[UncertaintyPerilBand] = []
    for block in physical.perils:
        aai = block.aaiAgg
        p5 = round(0.8 * aai, 2)
        p95 = round(1.4 * aai, 2)
        delta = block.deltaPct if block.deltaPct is not None else 0.0
        bands.append(
            UncertaintyPerilBand(
                peril=block.peril,
                futureYear=scenario.horizon,
                aaiMean=aai,
                aaiStd=round(0.15 * aai, 2),
                aaiP5=p5,
                aaiP50=aai,
                aaiP95=p95,
                distribution=[round(p5 + (p95 - p5) * i / (n - 1), 2) for i in range(n)],
                sensitivity=dict(_SENSITIVITY_ST),
                sensitivityS1=dict(_SENSITIVITY_S1),
                sensitivitySt=dict(_SENSITIVITY_ST),
                sensitivityMethod="sobol",
                presentAai=round(aai / (1.0 + delta / 100.0), 2) if delta > -100.0 else aai,
                deltaMean=delta,
                deltaP5=delta - 5.0,
                deltaP95=delta + 5.0,
            )
        )
    return UncertaintyResult(
        status="ok",
        currency=physical.currency,
        nSamples=n_samples,
        perils=bands,
        detail=_STUB_DETAIL,
    )


def _default_measure_specs(portfolio: Portfolio) -> list[MeasureSpec]:
    """The default adaptation-measure set, costed as fractions of portfolio value."""
    total_value = sum(a.value for a in portfolio.assets)
    return [
        MeasureSpec(name=name, cost=round(frac * total_value, 2), damageReduction=dr)
        for name, frac, dr in _DEFAULT_MEASURES
    ]


def _pv_annuity_factor(rate: float, n_years: int) -> float:
    """Present value of 1/yr for ``n_years`` at ``rate``: (1 - (1+r)^-N) / r (N when r=0)."""
    if n_years <= 0:
        return 0.0
    if rate <= 0:
        return float(n_years)
    return (1.0 - (1.0 + rate) ** (-n_years)) / rate


def run_cost_benefit(
    portfolio: Portfolio,
    peril: str,
    scenario: Scenario,
    measures: list[MeasureSpec],
    discount_rate: float,
) -> CostBenefitResult:
    """STUB adaptation cost-benefit: benefit = averted share of the NPV of climate risk.

    ``totClimateRisk`` is the physical stub AAI annuitised to the scenario horizon at the
    discount rate; each measure averts its ``damageReduction`` share of it.
    """
    physical = _run_engine(portfolio, [peril], scenario)
    aai = physical.perils[0].aaiAgg if physical.perils else 0.0
    n_years = max(1, scenario.horizon - _BASE_YEAR)
    tot_climate_risk = round(aai * _pv_annuity_factor(discount_rate, n_years), 2)

    if not measures:
        measures = _default_measure_specs(portfolio)

    results: list[MeasureResult] = []
    for m in measures:
        benefit = round(tot_climate_risk * m.damageReduction, 2)
        results.append(
            MeasureResult(
                name=m.name,
                cost=m.cost,
                benefit=benefit,
                benefitCostRatio=round(benefit / m.cost, 3) if m.cost > 0 else None,
            )
        )
    return CostBenefitResult(
        status="ok",
        peril=peril,
        futureYear=scenario.horizon,
        discountRate=discount_rate,
        currency=physical.currency,
        totClimateRisk=tot_climate_risk,
        measures=results,
        detail=_STUB_DETAIL,
    )


def _sector_multiplier(sector: str) -> float:
    """Deterministic indirect-loss amplification per sector, in [1.25, 1.60]."""
    return 1.25 + 0.05 * (sum(ord(c) for c in sector) % 8)


def run_supply_chain(
    portfolio: Portfolio,
    perils: list[str],
    scenario: Scenario,
    mriot_type: str,
    mriot_year: int,
) -> SupplyChainResult:
    """STUB supply-chain indirect impact: direct AAI grouped by sector x a fixed multiplier."""
    physical = _run_engine(portfolio, perils, scenario)
    sector_by_asset = {a.id: (a.sector or "utilities") for a in portfolio.assets}
    direct_by_sector: dict[str, float] = {}
    for block in physical.perils:
        for pa in block.perAsset:
            sector = sector_by_asset.get(pa.assetId, "utilities")
            direct_by_sector[sector] = direct_by_sector.get(sector, 0.0) + pa.eai

    by_sector = [
        SupplyChainSector(sector=s, indirect=round(d * _sector_multiplier(s), 2))
        for s, d in sorted(direct_by_sector.items())
    ]
    total_direct = round(sum(direct_by_sector.values()), 2)
    total_indirect = round(sum(s.indirect for s in by_sector), 2)
    return SupplyChainResult(
        status="ok",
        mriot=f"{mriot_type} {mriot_year}",
        currency=physical.currency,
        totalDirect=total_direct,
        totalIndirect=total_indirect,
        amplification=round(total_indirect / total_direct, 3) if total_direct > 0 else None,
        bySector=by_sector,
        detail=_STUB_DETAIL,
    )


def run_calibration(portfolio: Portfolio, scenario: Scenario) -> CalibrationResult:
    """STUB impact-function calibration: nudge TC v_half toward a synthetic observed loss.

    The synthetic observation is 90% of the stub-modelled AAI; a higher v_half means less
    damage, so the calibrated value moves up by the square-root of the modelled/observed
    ratio (deterministic, plausible direction).
    """
    physical = _run_engine(portfolio, ["tropical_cyclone"], scenario)
    modeled = physical.perils[0].aaiAgg if physical.perils else 0.0
    observed = round(0.9 * modeled, 2)
    if observed > 0:
        calibrated = round(_TC_V_HALF_INITIAL * (modeled / observed) ** 0.5, 1)
    else:
        calibrated = _TC_V_HALF_INITIAL
    return CalibrationResult(
        status="ok",
        peril="tropical_cyclone",
        country="",
        param="v_half",
        initial=_TC_V_HALF_INITIAL,
        calibrated=calibrated,
        observedAnnualLoss=observed,
        detail=_STUB_DETAIL,
    )


def run_forecast(portfolio: Portfolio) -> ForecastResult:
    """STUB operational forecast: near-term expected impact = half the present TC EAI.

    Emits a 5-season expected-impact series whose weights sum to 1.0, so the series total
    reproduces ``totalImpact`` (up to rounding).
    """
    physical = _run_engine(portfolio, ["tropical_cyclone"], Scenario(rcp="rcp45", horizon=2050))
    block = physical.perils[0] if physical.perils else None
    per_asset = [
        AssetImpact(assetId=pa.assetId, eai=round(0.5 * pa.eai, 2))
        for pa in (block.perAsset if block else [])
    ]
    total = round(sum(pa.eai for pa in per_asset), 2)
    series = [
        ForecastSeriesPoint(label=f"Season +{i + 1}", value=round(total * w, 2))
        for i, w in enumerate(_FORECAST_WEIGHTS)
    ]
    return ForecastResult(
        status="ok",
        peril="tropical_cyclone",
        nTracks=10 + len(portfolio.assets) % 10,
        totalImpact=total,
        currency=physical.currency,
        perAsset=per_asset,
        series=series,
        detail=_STUB_DETAIL,
    )


def _stub_run_kind(
    kind: str,
    portfolio: Portfolio,
    perils: list[str],
    scenario: Scenario,
    options: dict[str, Any],
) -> Any:
    """Dispatch one run to its deterministic STUB implementation."""
    if kind == "physical":
        return run_physical(portfolio, perils, scenario)
    if kind == "uncertainty":
        return run_uncertainty(portfolio, perils, scenario, int(options.get("nSamples", 50)))
    if kind == "cost-benefit":
        peril = options.get("peril") or (perils[0] if perils else "tropical_cyclone")
        return run_cost_benefit(
            portfolio,
            peril,
            scenario,
            list(options.get("measures") or []),
            float(options.get("discountRate", 0.05)),
        )
    if kind == "supply-chain":
        return run_supply_chain(
            portfolio,
            perils,
            scenario,
            str(options.get("mriotType", "WIOD16")),
            int(options.get("mriotYear", 2010)),
        )
    if kind == "calibration":
        return run_calibration(portfolio, scenario)
    if kind == "forecast":
        return run_forecast(portfolio)
    raise ValueError(f"unknown run kind '{kind}'")


def run_kind(
    kind: str,
    portfolio: Portfolio,
    perils: list[str],
    scenario: Scenario,
    options: dict[str, Any],
) -> Any:
    """Dispatch one run — the single seam where the CLIMADA worker takes over.

    Engine selection (see :mod:`.worker` for the env vars):

    * worker selected (gate allows it AND its conda env exists) — run on CLIMADA;
      on ANY worker failure (spawn error, timeout, bad result) fall back to the
      stub and record the reason on the result's ``detail``.
    * worker forced on (``RAGNAROK_CLIMADA_WORKER=1``) but env missing — stub,
      with the missing-env reason on ``detail``.
    * otherwise (gate off, or ``auto`` with no env) — the stub, unchanged.

    Args:
        kind: One of :data:`~.entities.RUN_KINDS`.
        portfolio: The session portfolio.
        perils: Peril ids for peril-driven kinds.
        scenario: Climate scenario context (``rcp`` + ``horizon``).
        options: Kind-specific parameters (``nSamples``, ``measures``, ``peril``,
            ``discountRate``, ``mriotType``, ``mriotYear``).

    Returns:
        The kind's result model (see the ``RunResult`` union in :mod:`.entities`).
    """
    if kind not in RUN_KINDS:
        raise ValueError(f"unknown run kind '{kind}'")
    options = dict(options)
    if kind == "cost-benefit" and not options.get("measures"):
        # Resolve the default measure set ONCE so the worker and the stub price
        # the same measures (the worker has no default of its own).
        options["measures"] = _default_measure_specs(portfolio)

    if worker.selected():
        try:
            return worker.run(kind, portfolio, perils, scenario, options)
        except worker.WorkerError as exc:
            result = _stub_run_kind(kind, portfolio, perils, scenario, options)
            result.detail = f"{_STUB_DETAIL} Worker fallback: {exc}"
            return result

    result = _stub_run_kind(kind, portfolio, perils, scenario, options)
    if worker.forced_but_missing():
        result.detail = (
            f"{_STUB_DETAIL} Worker fallback: RAGNAROK_CLIMADA_WORKER is enabled "
            f"but no worker env was found at {worker.env_dir()}."
        )
    return result
