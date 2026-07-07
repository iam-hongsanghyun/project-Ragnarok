"""Climate-risk financial model — cashflow to NPV/IRR/DSCR to credit rating to CRP.

REAL math, ported from climaterisk ``finance/{core,channels,models,service}.py`` into one
module (section-per-source below), adapted to this package's camelCase entities. Pure
functions, no I/O, no CLIMADA. The reference grids (DSCR-to-rating, rating-to-spread) and
financing defaults come from the vendored ``finance_reference.json`` / ``finance_channels.json``
so every number is citable and overridable.

Algorithm (annual, constant-EBITDA project — the standard project-finance skeleton):
    $$NPV = \\sum_{t=1}^{N} \\frac{EBITDA}{(1+wacc)^t} - CAPEX$$
    $$DSCR = CFADS / DS, \\quad DS = \\text{annuity}(debt, r_d, tenor)$$
    $$CRP_{bps} = spread(\\text{stressed}) - spread(\\text{baseline})$$
    ASCII: discount EBITDA at WACC minus capex; debt-service coverage sets the rating; the
    Climate Risk Premium is the extra credit spread the climate cashflow shock costs.

where ``EBITDA`` is annual operating cashflow (currency/yr), ``CAPEX`` total capital outlay
(currency), ``wacc`` the weighted average cost of capital (1/yr), ``DS`` annual debt service
(currency/yr), ``r_d`` the cost of debt (1/yr) and spreads are in basis points. A stressed
run reduces EBITDA by the expected annual climate loss (physical AAI + carbon cost); the
``power_gen`` model instead rebuilds EBITDA from generation with a stressed capacity factor:
    $$CF_{eff} = CF_0 (1-d)(1-o)(1-c)(1-e)$$
    ASCII: effective CF = baseline CF times (1 - channel) for dispatch d, outage o,
    water/capacity derate c and heat efficiency loss e.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .entities import FinancialProfile, PhysicalRunOutput, Portfolio

HOURS_PER_YEAR = 8760.0

GENERIC = "generic"
POWER_GEN = "power_gen"

# Serialization guard: an unlevered project (debtFraction = 0) has no debt service, so the
# DSCR is unbounded. JSON cannot carry inf — cap at this sentinel (still reads as "no risk").
_DSCR_CAP = 1e9


# ── result models (the FinanceResult contract served to the frontend) ─────────


class FinanceOutcome(BaseModel):
    """NPV/IRR/DSCR/rating/spread for one cashflow scenario (baseline or stressed)."""

    npv: float
    irr: float | None
    minDscr: float
    rating: str
    spreadBps: float
    wacc: float


class FinanceAssessment(BaseModel):
    """Baseline-vs-stressed comparison for one entity (portfolio or asset)."""

    baseline: FinanceOutcome
    stressed: FinanceOutcome
    annualClimateLoss: float
    npvLoss: float
    npvLossPctCapex: float
    crpBps: float
    downgrade: bool


class MethodComparison(BaseModel):
    """The portfolio assessment under one DSCR-to-rating methodology."""

    method: str
    label: str
    code: str
    source: str
    scenario: FinanceAssessment


class AssetFinance(BaseModel):
    """Per-asset CRP result (only assets carrying their own financial profile)."""

    assetId: str
    name: str
    model: str | None = None
    assessment: FinanceAssessment


class FinanceResult(BaseModel):
    """The full climate-risk-premium output (climaterisk ``finance/service.py`` shape)."""

    currency: str = "USD"
    totalPhysicalAai: float = 0.0
    transitionAnnualCost: float = 0.0
    ratingMethod: str = ""
    ratingMethodLabel: str = ""
    ratingMethodSource: str = ""
    ratingThresholds: list[dict[str, Any]] = Field(default_factory=list)
    methodsCompared: list[MethodComparison] = Field(default_factory=list)
    financialModel: str | None = None
    portfolioBreakdown: dict[str, Any] = Field(default_factory=dict)
    portfolio: FinanceAssessment
    perAsset: list[AssetFinance] = Field(default_factory=list)
    detail: str | None = None


# ── core (climaterisk finance/core.py) ────────────────────────────────────────


@dataclass
class ResolvedProfile:
    """Fully-resolved project economics for one entity (no None fields)."""

    capex: float
    annual_ebitda: float
    horizon_years: int = 25
    debt_fraction: float = 0.70
    debt_tenor_years: int = 18
    risk_free_rate: float = 0.03
    baseline_spread_bps: float = 150.0
    baseline_equity_rate: float = 0.12


def annuity_payment(principal: float, rate: float, n: int) -> float:
    """Level annual payment that amortises ``principal`` over ``n`` years at ``rate``."""
    if n <= 0:
        return 0.0
    if rate <= 0:
        return principal / n
    return principal * rate / (1.0 - (1.0 + rate) ** (-n))


def npv(rate: float, cashflows: list[float]) -> float:
    """NPV of ``cashflows`` (t=0,1,2,...) discounted at ``rate`` (cashflows[0] is t=0)."""
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cashflows))


def irr(cashflows: list[float], lo: float = -0.95, hi: float = 1.0) -> float | None:
    """Internal rate of return via bisection on NPV sign; None if no sign change in range."""
    f_lo, f_hi = npv(lo, cashflows), npv(hi, cashflows)
    if f_lo == 0:
        return lo
    if f_lo * f_hi > 0:
        return None  # no root bracketed (e.g. all-negative cashflows)
    for _ in range(100):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid, cashflows)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def rating_from_dscr(dscr: float, thresholds: list[dict[str, Any]]) -> str:
    """Map a DSCR to a credit rating using the descending ``dscr_min`` grid."""
    for entry in sorted(thresholds, key=lambda e: e["dscr_min"], reverse=True):
        if dscr >= entry["dscr_min"]:
            return str(entry["rating"])
    return str(thresholds[-1]["rating"])


def spread_from_rating(rating: str, spreads: list[dict[str, Any]]) -> float:
    """Credit spread (bps) for a rating from the ``rating_spreads_bps`` table."""
    table = {row["rating"]: float(row["spread_bps"]) for row in spreads}
    return table.get(rating, 250.0)


def _scenario(p: ResolvedProfile, annual_ebitda: float, ref: dict[str, Any]) -> FinanceOutcome:
    """NPV/IRR/DSCR/rating/spread for one EBITDA level (baseline or climate-stressed)."""
    debt = p.capex * p.debt_fraction
    equity = p.capex - debt
    debt_rate = p.risk_free_rate + p.baseline_spread_bps / 1e4
    wacc = (
        (debt / p.capex) * debt_rate + (equity / p.capex) * p.baseline_equity_rate
        if p.capex > 0
        else p.baseline_equity_rate
    )
    cashflows = [-p.capex] + [annual_ebitda] * p.horizon_years
    debt_service = annuity_payment(debt, debt_rate, p.debt_tenor_years)
    min_dscr = (annual_ebitda / debt_service) if debt_service > 0 else math.inf
    rating = rating_from_dscr(min_dscr, ref["rating_dscr_thresholds"])
    spread = spread_from_rating(rating, ref["rating_spreads_bps"])
    return FinanceOutcome(
        npv=npv(wacc, cashflows),
        irr=irr(cashflows),
        minDscr=min(min_dscr, _DSCR_CAP),
        rating=rating,
        spreadBps=spread,
        wacc=wacc,
    )


def assess_ebitda(
    profile: ResolvedProfile,
    baseline_ebitda: float,
    stressed_ebitda: float,
    ref: dict[str, Any],
) -> FinanceAssessment:
    """Assess a (baseline, stressed) EBITDA pair — NPV/IRR/DSCR/rating plus the CRP.

    The sector-agnostic engine: an asset financial model decides how the two EBITDA levels
    are produced; this runs the same cashflow-to-rating-to-spread chain on each.
    """
    baseline = _scenario(profile, baseline_ebitda, ref)
    stressed = _scenario(profile, stressed_ebitda, ref)
    crp_bps = stressed.spreadBps - baseline.spreadBps  # counterfactual climate premium
    npv_loss = baseline.npv - stressed.npv
    return FinanceAssessment(
        baseline=baseline,
        stressed=stressed,
        annualClimateLoss=float(baseline_ebitda - stressed_ebitda),
        npvLoss=float(npv_loss),
        npvLossPctCapex=float(npv_loss / profile.capex * 100.0) if profile.capex > 0 else 0.0,
        crpBps=float(crp_bps),
        downgrade=baseline.rating != stressed.rating,
    )


# ── channels (climaterisk finance/channels.py) ────────────────────────────────


def _clamp01(x: float) -> float:
    """Clamp a fraction to the closed interval [0, 1]."""
    return max(0.0, min(1.0, x))


def outage_rate(
    event_freq_per_yr: float,
    failure_rate_per_hour: float,
    exposure_hours: float,
    outage_duration_hours: float,
) -> float:
    """Annual fraction of time the plant is forced offline by a hazard.

    Algorithm:
        $$o = f \\cdot (1 - e^{-\\lambda t_{exp}}) \\cdot t_{dur} / 8760$$
        ASCII: outage = freq * (1 - exp(-lambda*exposure)) * duration / 8760.

    where ``f`` is expected hazard events/yr, ``lambda`` the per-hour failure hazard (1/h)
    during exposure, ``t_exp`` exposure hours per event and ``t_dur`` downtime per failure (h).
    """
    if event_freq_per_yr <= 0 or failure_rate_per_hour <= 0:
        return 0.0
    p_fail = 1.0 - math.exp(-failure_rate_per_hour * max(0.0, exposure_hours))
    rate = event_freq_per_yr * p_fail * max(0.0, outage_duration_hours) / HOURS_PER_YEAR
    return _clamp01(rate)


def efficiency_loss(ambient_temp_c: float, design_temp_c: float, loss_per_degc: float) -> float:
    """Output derate fraction from ambient temperature above the design point.

    ``max(0, T - T_design) * k`` clamped to [0, 1] (no gain below design), with ``T`` in
    degrees C and ``k`` the fractional output loss per degree C.
    """
    excess = max(0.0, ambient_temp_c - design_temp_c)
    return _clamp01(excess * max(0.0, loss_per_degc))


def effective_capacity_factor(
    cf_baseline: float,
    dispatch_penalty: float = 0.0,
    outage: float = 0.0,
    capacity_derate: float = 0.0,
    efficiency: float = 0.0,
    water_constrained_cf: float | None = None,
) -> float:
    """Compose the channels into the stressed effective capacity factor.

    Each channel is a fraction in [0, 1]; they reduce the baseline CF multiplicatively. An
    optional ``water_constrained_cf`` hard-caps the result (drought cooling limit).
    """
    cf = _clamp01(cf_baseline)
    for channel in (dispatch_penalty, outage, capacity_derate, efficiency):
        cf *= 1.0 - _clamp01(channel)
    if water_constrained_cf is not None:
        cf = min(cf, _clamp01(water_constrained_cf))
    return _clamp01(cf)


# ── models (climaterisk finance/models.py) ────────────────────────────────────


@dataclass
class GenerationInputs:
    """Generation economics for a power plant (all per-year, asset currency)."""

    capacity_mw: float
    power_price: float
    capacity_factor: float
    fixed_opex: float = 0.0
    opex_per_mwh: float = 0.0


@dataclass
class ChannelMagnitudes:
    """Stressed-scenario channel fractions in [0, 1] (0 = channel inactive)."""

    dispatch_penalty: float = 0.0
    outage_rate: float = 0.0
    capacity_derate: float = 0.0
    efficiency_loss: float = 0.0
    water_constrained_cf: float | None = None


@dataclass
class EbitdaPair:
    """Baseline vs climate-stressed annual EBITDA, plus a channel breakdown for display."""

    baseline: float
    stressed: float
    breakdown: dict[str, Any] = field(default_factory=dict)


def generic_pair(annual_ebitda: float, annual_climate_loss: float) -> EbitdaPair:
    """Generic model: stressed EBITDA = baseline - expected annual climate loss."""
    loss = max(0.0, annual_climate_loss)
    return EbitdaPair(
        baseline=annual_ebitda,
        stressed=annual_ebitda - loss,
        breakdown={"model": GENERIC, "annualClimateLoss": loss},
    )


def power_gen_pair(
    gen: GenerationInputs,
    ch: ChannelMagnitudes,
    annual_aai: float = 0.0,
    carbon_cost: float = 0.0,
) -> EbitdaPair:
    """Power-generation model: build EBITDA from generation; stress the capacity factor.

    Baseline is the unstressed plant (CF_baseline, no carbon, no damage). The stressed run
    applies the operational channels to the capacity factor, then subtracts the transition
    carbon cost and the physical-damage AAI.
    """
    cf0 = effective_capacity_factor(gen.capacity_factor)
    cf1 = effective_capacity_factor(
        gen.capacity_factor,
        dispatch_penalty=ch.dispatch_penalty,
        outage=ch.outage_rate,
        capacity_derate=ch.capacity_derate,
        efficiency=ch.efficiency_loss,
        water_constrained_cf=ch.water_constrained_cf,
    )
    gen0 = gen.capacity_mw * HOURS_PER_YEAR * cf0
    gen1 = gen.capacity_mw * HOURS_PER_YEAR * cf1
    rev0 = gen0 * gen.power_price
    rev1 = gen1 * gen.power_price
    opex0 = gen.fixed_opex + gen.opex_per_mwh * gen0
    opex1 = gen.fixed_opex + gen.opex_per_mwh * gen1
    ebitda0 = rev0 - opex0
    ebitda1 = rev1 - opex1 - max(0.0, carbon_cost) - max(0.0, annual_aai)
    return EbitdaPair(
        baseline=ebitda0,
        stressed=ebitda1,
        breakdown={
            "model": POWER_GEN,
            "cfBaseline": cf0,
            "cfEffective": cf1,
            "generationMwhBaseline": gen0,
            "generationMwhStressed": gen1,
            "revenueBaseline": rev0,
            "revenueStressed": rev1,
            "carbonCost": max(0.0, carbon_cost),
            "annualAai": max(0.0, annual_aai),
            "channels": {
                "dispatchPenalty": ch.dispatch_penalty,
                "outageRate": ch.outage_rate,
                "capacityDerate": ch.capacity_derate,
                "efficiencyLoss": ch.efficiency_loss,
            },
        },
    )


# ── service (climaterisk finance/service.py) ──────────────────────────────────


def _defaults(ref: dict[str, Any]) -> dict[str, float]:
    return {k: float(v["value"]) for k, v in ref["financing_defaults"].items()}


def _pick(attr: str, *sources: FinancialProfile | None) -> Any:
    """First non-None value of ``attr`` across the profiles (override, then fallback)."""
    for s in sources:
        v = getattr(s, attr, None) if s else None
        if v is not None:
            return v
    return None


def resolve_profile(
    primary: FinancialProfile | None,
    fallback: FinancialProfile | None,
    ref: dict[str, Any],
) -> ResolvedProfile:
    """Field-by-field: per-asset override, then portfolio default, then cited defaults."""
    d = _defaults(ref)

    def pick(attr: str, default: float) -> float:
        v = _pick(attr, primary, fallback)
        return float(v) if v is not None else float(default)

    return ResolvedProfile(
        capex=pick("capex", 0.0),
        annual_ebitda=pick("annualEbitda", 0.0),
        horizon_years=int(pick("horizonYears", d["horizon_years"])),
        debt_fraction=pick("debtFraction", d["debt_fraction"]),
        debt_tenor_years=int(pick("debtTenorYears", d["debt_tenor_years"])),
        risk_free_rate=pick("riskFreeRate", d["risk_free_rate"]),
        baseline_spread_bps=pick("baselineSpreadBps", d["baseline_spread_bps"]),
        baseline_equity_rate=pick("baselineEquityRate", d["baseline_equity_rate"]),
    )


def resolve_generation(
    primary: FinancialProfile | None,
    fallback: FinancialProfile | None,
    channels_ref: dict[str, Any],
) -> GenerationInputs | None:
    """Build generation economics (override, fallback, then fuel/library defaults).

    Returns None if capacity, price or capacity factor cannot be resolved (so the caller
    falls back to the generic model).
    """
    gd = channels_ref.get("generation_defaults", {})
    cap = _pick("capacityMw", primary, fallback)
    price = _pick("powerPrice", primary, fallback)
    cf = _pick("capacityFactor", primary, fallback)
    if cf is None:
        fuel = _pick("plantFuel", primary, fallback)
        if fuel:
            cf = gd.get("capacity_factor_by_fuel", {}).get(fuel)
    if cap is None or price is None or cf is None:
        return None
    var = _pick("opexPerMwh", primary, fallback)
    if var is None:
        var = float(gd.get("opex_per_mwh", {}).get("value", 0.0))
    return GenerationInputs(
        capacity_mw=float(cap),
        power_price=float(price),
        capacity_factor=float(cf),
        fixed_opex=float(_pick("fixedOpex", primary, fallback) or 0.0),
        opex_per_mwh=float(var),
    )


def resolve_channels(
    primary: FinancialProfile | None,
    fallback: FinancialProfile | None,
    channels_ref: dict[str, Any],
) -> ChannelMagnitudes:
    """Resolve stressed-scenario channel magnitudes (override, fallback, cited defaults)."""
    ch = channels_ref.get("channels", {})

    def resolve(attr: str, group: str, key: str) -> float:
        v = _pick(attr, primary, fallback)
        if v is not None:
            return float(v)
        return float(ch.get(group, {}).get(key, 0.0))

    return ChannelMagnitudes(
        dispatch_penalty=resolve("dispatchPenalty", "dispatch", "default_penalty"),
        outage_rate=resolve("outageRate", "outage", "default_rate"),
        capacity_derate=resolve("capacityDerate", "water_derate", "default_derate"),
        efficiency_loss=resolve("efficiencyLoss", "efficiency", "default_loss"),
    )


def ebitda_pair(
    primary: FinancialProfile | None,
    fallback: FinancialProfile | None,
    core_profile: ResolvedProfile,
    annual_aai: float,
    carbon_cost: float,
    channels_ref: dict[str, Any],
) -> EbitdaPair:
    """Produce the (baseline, stressed) EBITDA pair via the selected asset financial model.

    ``power_gen`` builds EBITDA from generation and stresses the capacity factor; any other
    model (or incomplete generation inputs) falls back to ``generic``.
    """
    model = _pick("financialModel", primary, fallback) or GENERIC
    if model == POWER_GEN:
        gen = resolve_generation(primary, fallback, channels_ref)
        if gen is not None:
            ch = resolve_channels(primary, fallback, channels_ref)
            return power_gen_pair(gen, ch, annual_aai=annual_aai, carbon_cost=carbon_cost)
    return generic_pair(core_profile.annual_ebitda, annual_aai + carbon_cost)


def selected_method_ids(profile: FinancialProfile | None, ref: dict[str, Any]) -> list[str]:
    """Ordered methodology ids to compare (multi-select, single, else library default)."""
    default_id = str(ref.get("default_rating_method", "moodys_sp"))
    if profile and profile.ratingMethods:
        ids = [m for m in profile.ratingMethods if m]
        if ids:
            return ids
    if profile and profile.ratingMethod:
        return [profile.ratingMethod]
    return [default_id]


def resolve_rating_method(
    profile: FinancialProfile | None, ref: dict[str, Any], method_id: str
) -> dict[str, Any]:
    """Resolve one methodology id to its DSCR-to-rating grid plus display metadata.

    'custom' uses the profile's editable grid; an unknown id falls back to the library
    default.
    """
    methods: dict[str, Any] = ref.get("rating_methods", {})
    default_id = str(ref.get("default_rating_method", "moodys_sp"))

    if method_id == "custom":
        thresholds = (
            [{"dscr_min": t.dscrMin, "rating": t.rating} for t in profile.customRatingThresholds]
            if profile and profile.customRatingThresholds
            else list(ref.get("rating_dscr_thresholds", []))
        )
        return {
            "method": "custom",
            "label": "Custom (user-defined)",
            "code": "Custom",
            "source": "User-defined DSCR-to-rating grid",
            "thresholds": thresholds,
        }

    method = methods.get(method_id) or methods.get(default_id)
    if method is not None:
        resolved_id = method_id if method_id in methods else default_id
        return {
            "method": resolved_id,
            "label": method.get("label", resolved_id),
            "code": method.get("code", method.get("short", resolved_id)),
            "source": method.get("source", ""),
            "thresholds": method["thresholds"],
        }
    # Last-resort fallback for older libraries without rating_methods.
    return {
        "method": "moodys_sp",
        "label": "Moody's / S&P",
        "code": "Agency",
        "source": "",
        "thresholds": ref["rating_dscr_thresholds"],
    }


def per_asset_aai(run_output: PhysicalRunOutput) -> dict[str, float]:
    """Sum each asset's expected annual impact across all perils in a physical run."""
    loss: dict[str, float] = {}
    for block in run_output.perils:
        for pa in block.perAsset:
            loss[pa.assetId] = loss.get(pa.assetId, 0.0) + float(pa.eai or 0.0)
    return loss


def _camel_thresholds(thresholds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rating-threshold rows for the response: dscr_min -> dscrMin, keep rating/source."""
    out: list[dict[str, Any]] = []
    for t in thresholds:
        row: dict[str, Any] = {"dscrMin": float(t["dscr_min"]), "rating": str(t["rating"])}
        if t.get("source"):
            row["source"] = t["source"]
        out.append(row)
    return out


def compute_finance(
    portfolio: Portfolio,
    run_output: PhysicalRunOutput,
    transition_annual_cost: float,
    ref: dict[str, Any],
    channels_ref: dict[str, Any] | None = None,
) -> FinanceResult:
    """Portfolio-level + per-asset-override climate-risk-premium assessment for a run.

    ``channels_ref`` is the ``finance_channels`` library, needed only by the power-generation
    model; the generic model ignores it.
    """
    channels_ref = channels_ref or {}
    aai = per_asset_aai(run_output)
    total_physical = sum(aai.values())
    port_ep = portfolio.scenario.financialProfile
    transition = max(0.0, transition_annual_cost)
    port_profile = resolve_profile(port_ep, None, ref)

    # The asset financial model decides the (baseline, stressed) EBITDA pair — generic
    # (EBITDA - AAI - carbon) or power_gen (generation through the operational channels).
    # Compute it once; the rating methodology only changes the DSCR-to-rating grid downstream.
    port_pair = ebitda_pair(port_ep, None, port_profile, total_physical, transition, channels_ref)

    # The user may select several DSCR-to-rating "house views" to compare. Assess the
    # portfolio under each (swapping the grid into an effective ref); the first selected
    # method is the primary used for the headline and per-asset ratings.
    method_ids = selected_method_ids(port_ep, ref)
    methods_compared: list[MethodComparison] = []
    for mid in method_ids:
        r = resolve_rating_method(port_ep, ref, mid)
        eff = {**ref, "rating_dscr_thresholds": r["thresholds"]}
        methods_compared.append(
            MethodComparison(
                method=r["method"],
                label=r["label"],
                code=r["code"],
                source=r["source"],
                scenario=assess_ebitda(port_profile, port_pair.baseline, port_pair.stressed, eff),
            )
        )

    primary = resolve_rating_method(port_ep, ref, method_ids[0])
    eff_ref = {**ref, "rating_dscr_thresholds": primary["thresholds"]}
    portfolio_result = methods_compared[0].scenario

    per_asset: list[AssetFinance] = []
    for a in portfolio.assets:
        if a.financialProfile is None:
            continue  # only assets with their own profile get a per-asset CRP (primary method)
        a_profile = resolve_profile(a.financialProfile, port_ep, ref)
        # Per-asset carbon is not split out of the portfolio total yet -> 0 here.
        a_pair = ebitda_pair(
            a.financialProfile, port_ep, a_profile, aai.get(a.id, 0.0), 0.0, channels_ref
        )
        res = assess_ebitda(a_profile, a_pair.baseline, a_pair.stressed, eff_ref)
        per_asset.append(
            AssetFinance(
                assetId=a.id, name=a.name, model=a_pair.breakdown.get("model"), assessment=res
            )
        )

    cur = portfolio.assets[0].currency if portfolio.assets else "USD"
    return FinanceResult(
        currency=cur,
        totalPhysicalAai=total_physical,
        transitionAnnualCost=transition,
        ratingMethod=primary["method"],
        ratingMethodLabel=primary["label"],
        ratingMethodSource=primary["source"],
        ratingThresholds=_camel_thresholds(primary["thresholds"]),
        methodsCompared=methods_compared,
        financialModel=port_pair.breakdown.get("model"),
        portfolioBreakdown=port_pair.breakdown,
        portfolio=portfolio_result,
        perAsset=per_asset,
        detail=(
            f"Climate risk premium {portfolio_result.crpBps:+.0f} bps "
            f"({portfolio_result.baseline.rating} to {portfolio_result.stressed.rating})"
        ),
    )
