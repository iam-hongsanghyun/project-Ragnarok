"""Domain entities for the native physical-risk capability.

Ported and trimmed from climaterisk ``core/entities.py`` + ``core/enums.py`` and
``engines/base.py``. Field names follow the SHARED CONTRACT so the frontend, this
backend, and the eventual real CLIMADA worker all line up. The ``Portfolio`` is
the canonical session document — the frontend persists only a ``sessionId`` and
syncs the whole document back via PUT.
"""
from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid.uuid4().hex


class Peril(StrEnum):
    """Physical climate hazards. Values align with CLIMADA hazard types."""

    TROPICAL_CYCLONE = "tropical_cyclone"
    RIVER_FLOOD = "river_flood"
    WILDFIRE = "wildfire"
    EARTHQUAKE = "earthquake"
    WINDSTORM = "windstorm"


class VulnerabilityClass(StrEnum):
    """Physical vulnerability class — maps to a per-peril damage-curve set.

    Energy-asset flavoured (the portfolio is seeded from a PyPSA network), with a
    generic default that always resolves.
    """

    THERMAL = "thermal"
    RENEWABLE = "renewable"
    HYDRO = "hydro"
    GRID = "grid"
    DEFAULT = "default"


class RunStatus(StrEnum):
    """Lifecycle of a submitted physical-risk run."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class RatingThreshold(BaseModel):
    """One row of a DSCR-to-rating grid: a rating applies when DSCR >= ``dscrMin``."""

    dscrMin: float = Field(description="Minimum DSCR for this rating (descending grid).")
    rating: str = Field(description="Credit rating label, e.g. 'AA'.")


class FinancialProfile(BaseModel):
    """Project economics for the climate-risk-premium engine.

    Used as a portfolio-level default (``Portfolio.scenario.financialProfile``) and
    optionally overridden per asset. Unset fields fall back to the cited
    ``finance_reference.json`` financing defaults. Ported from climaterisk
    ``core/entities.py::FinancialProfile`` (fields camelCased).
    """

    capex: float | None = Field(default=None, ge=0.0, description="Total capital outlay.")
    annualEbitda: float | None = Field(default=None, description="Baseline annual EBITDA.")
    horizonYears: int | None = Field(default=None, ge=1, le=60)
    debtFraction: float | None = Field(default=None, ge=0.0, le=1.0)
    debtTenorYears: int | None = Field(default=None, ge=1, le=60)
    riskFreeRate: float | None = Field(default=None, ge=0.0, le=1.0)
    baselineSpreadBps: float | None = Field(default=None, ge=0.0)
    baselineEquityRate: float | None = Field(default=None, ge=0.0, le=1.0)
    ratingMethod: str | None = Field(
        default=None,
        description="Single DSCR-to-rating methodology id (primary). Superseded by "
        "ratingMethods when set. None uses the library default.",
    )
    ratingMethods: list[str] | None = Field(
        default=None,
        description="Methodology ids to compare (from finance reference ratingMethods, plus "
        "'custom'). The first is the primary used for the headline and per-asset ratings.",
    )
    customRatingThresholds: list[RatingThreshold] | None = Field(
        default=None, description="User-defined DSCR-to-rating grid, used when 'custom' selected."
    )
    financialModel: str | None = Field(
        default=None,
        description="'generic' (default, any sector) or 'power_gen' (power plant — uses the "
        "generation fields and operational channels below).",
    )
    # --- power_gen generation economics (only used when financialModel == 'power_gen') ---
    capacityMw: float | None = Field(default=None, ge=0.0, description="Nameplate capacity (MW).")
    powerPrice: float | None = Field(default=None, ge=0.0, description="Realised price per MWh.")
    capacityFactor: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Baseline (no-stress) capacity factor."
    )
    plantFuel: str | None = Field(
        default=None, description="Fuel/type (coal, lng, nuclear, ...) — seeds a default CF."
    )
    fixedOpex: float | None = Field(default=None, ge=0.0, description="Annual fixed O&M.")
    opexPerMwh: float | None = Field(default=None, ge=0.0, description="Variable O&M per MWh.")
    # --- power_gen stressed-scenario channel magnitudes (fractions in [0, 1]) ---
    dispatchPenalty: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Policy capacity-factor reduction (dispatch)."
    )
    outageRate: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Forced-outage fraction (wildfire/storm)."
    )
    capacityDerate: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Capacity/water derate (drought)."
    )
    efficiencyLoss: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Efficiency derate (heat)."
    )


class Asset(BaseModel):
    """A located facility — one CLIMADA exposure point.

    Seeded one-per generator / storage_unit from the current Ragnarok model.
    """

    id: str = Field(default_factory=_new_id)
    name: str = "Untitled asset"
    kind: str = Field(default="generator", description="'generator' | 'storage'.")
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    value: float = Field(default=0.0, ge=0.0, description="Asset value at risk, in `currency`.")
    currency: str = "USD"
    vulnerabilityClass: str = Field(
        default=VulnerabilityClass.DEFAULT.value,
        description="Vulnerability-class id (peril-agnostic).",
    )
    carrier: str = Field(default="", description="Source PyPSA carrier (provenance).")
    sector: str = Field(
        default="utilities",
        description="Sector id (libraries.sectors) — drives the emissions proxy and the "
        "supply-chain grouping. PyPSA-seeded assets are power assets, hence 'utilities'.",
    )
    annualEmissionsTco2e: float | None = Field(
        default=None,
        ge=0.0,
        description="Reported Scope-1 emissions (tCO2e/yr); if None, proxied from the sector "
        "emission intensity in the transition run.",
    )
    financialProfile: FinancialProfile | None = Field(
        default=None, description="Per-asset climate-risk-premium override (optional)."
    )


class VulnerabilityOverride(BaseModel):
    """User edits to a vulnerability class (impact-function studio).

    Unset fields fall back to the bundled library curve values.
    """

    tcVHalf: float | None = Field(default=None, gt=0.0)
    wfMaxMdd: float | None = Field(default=None, ge=0.0, le=1.0)
    floodMdr: list[float] | None = None
    eqMdr: list[float] | None = Field(
        default=None, description="Earthquake: mean damage ratio at each MMI breakpoint."
    )


class ScenarioConfig(BaseModel):
    """Persisted scenario + run configuration for a portfolio.

    Merges climaterisk's ``Scenario`` and ``RunConfig`` session fields (camelCased).
    Every field has a default so Phase-0 documents (no ``scenario`` key) still validate.
    """

    perils: list[str] = Field(
        default_factory=lambda: [Peril.TROPICAL_CYCLONE.value],
        description="Selected peril ids (libraries.perils).",
    )
    climate: str = Field(default="rcp45", description="Climate scenario id (RCP/SSP).")
    transition: str = Field(
        default="net_zero_2050", description="NGFS transition scenario id (carbon prices)."
    )
    horizonYear: int = Field(default=2050, description="Future horizon the run targets.")
    anchorYears: list[int] = Field(default_factory=lambda: [2030, 2040, 2050])
    discountRate: float = Field(default=0.05, ge=0.0, le=1.0)
    sector: str = Field(
        default="utilities", description="Default sector id for assets that carry none."
    )
    vulnerabilityOverrides: dict[str, VulnerabilityOverride] = Field(
        default_factory=dict, description="Per-class curve overrides (class id -> override)."
    )
    financialProfile: FinancialProfile | None = Field(
        default=None, description="Portfolio-level CRP project economics."
    )


class Portfolio(BaseModel):
    """The session model — a named set of assets keyed by session id."""

    sessionId: str = Field(default_factory=_new_id)
    assets: list[Asset] = Field(default_factory=list)
    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)


class AssetImpact(BaseModel):
    """Per-asset expected annual impact (the ``eai_exp`` map layer)."""

    assetId: str
    eai: float = Field(description="Expected annual impact, in the run's currency.")


class FreqCurve(BaseModel):
    """Exceedance / return-period curve (CLIMADA ``calc_freq_curve``).

    ``returnPeriods`` and ``losses`` are always equal length (one loss per RP).
    """

    returnPeriods: list[float] = Field(default_factory=list)
    losses: list[float] = Field(default_factory=list)


class PhysicalRunResult(BaseModel):
    """Engine output for one peril within a run."""

    peril: str
    perAsset: list[AssetImpact] = Field(default_factory=list)
    aaiAgg: float = Field(default=0.0, description="Average annual impact over the portfolio.")
    freqCurve: FreqCurve = Field(default_factory=FreqCurve)
    deltaPct: float | None = Field(
        default=None, description="(future - present) / present, in %, vs the present-day baseline."
    )
    detail: str | None = Field(
        default=None,
        description="Per-peril engine note — set when this peril FAILED on the worker, so its "
        "zeroed losses read as 'not modeled' rather than 'modeled as zero'. None for a clean block.",
    )


class PhysicalRunOutput(BaseModel):
    """The full engine output for one run (one result per requested peril)."""

    kind: Literal["physical"] = "physical"
    currency: str = "USD"
    perils: list[PhysicalRunResult] = Field(default_factory=list)
    detail: str | None = Field(
        default=None,
        description="Engine note (e.g. the worker-fallback reason); None for a clean stub run.",
    )


class Scenario(BaseModel):
    """The scenario context a run is evaluated under."""

    rcp: str = "rcp45"
    horizon: int = 2050


# ── worker-gated run kinds (request params + result shapes) ───────────────────
# Field names mirror climaterisk ``engines/base.py`` (camelCased) so the real CLIMADA
# worker slots in later without an API change. Multi-peril outputs wrap the upstream
# single-peril result in a ``perils`` list, matching PhysicalRunOutput's layout.


class MeasureSpec(BaseModel):
    """A user-defined adaptation measure (cost-benefit input; base.py ``MeasureSpec``)."""

    name: str
    cost: float = Field(default=0.0, ge=0.0)
    damageReduction: float = Field(default=0.0, ge=0.0, le=1.0, description="Fractional MDD cut.")
    hazardFreqCutoff: float = Field(default=0.0, ge=0.0)
    riskTransfAttach: float = Field(default=0.0, ge=0.0, description="Insurance deductible.")
    riskTransfCover: float = Field(default=0.0, ge=0.0, description="Insurance cover/limit.")


class UncertaintyPerilBand(BaseModel):
    """Monte-Carlo AAI bands for one peril (base.py ``UncertaintyResult``, per peril)."""

    peril: str
    futureYear: int | None = None
    aaiMean: float = 0.0
    aaiStd: float = 0.0
    aaiP5: float = 0.0
    aaiP50: float = 0.0
    aaiP95: float = 0.0
    distribution: list[float] = Field(default_factory=list)
    sensitivity: dict[str, float] = Field(default_factory=dict)
    sensitivityS1: dict[str, float] = Field(default_factory=dict)
    sensitivitySt: dict[str, float] = Field(default_factory=dict)
    sensitivityMethod: str = "sobol"
    presentAai: float | None = None
    deltaMean: float | None = None
    deltaP5: float | None = None
    deltaP95: float | None = None
    detail: str | None = None


class UncertaintyResult(BaseModel):
    """Engine output for a Monte-Carlo uncertainty run (one band per requested peril)."""

    kind: Literal["uncertainty"] = "uncertainty"
    status: str = "ok"
    currency: str = "USD"
    nSamples: int = 0
    perils: list[UncertaintyPerilBand] = Field(default_factory=list)
    detail: str | None = None


class MeasureResult(BaseModel):
    """Per-measure cost-benefit outcome (base.py ``MeasureResult``)."""

    name: str
    cost: float
    benefit: float = Field(description="NPV of averted damage over the horizon.")
    benefitCostRatio: float | None = None


class CostBenefitResult(BaseModel):
    """Engine output for an adaptation cost-benefit run (base.py ``CostBenefitResult``)."""

    kind: Literal["cost-benefit"] = "cost-benefit"
    status: str = "ok"
    peril: str = "tropical_cyclone"
    futureYear: int | None = None
    discountRate: float = 0.05
    currency: str = "USD"
    totClimateRisk: float = Field(default=0.0, description="NPV of unaverted climate risk.")
    measures: list[MeasureResult] = Field(default_factory=list)
    detail: str | None = None


class SupplyChainSector(BaseModel):
    """Indirect (rippled) loss attributed to one sector."""

    sector: str
    indirect: float


class SupplyChainResult(BaseModel):
    """Engine output for a supply-chain indirect-impact run (base.py ``SupplyChainResult``)."""

    kind: Literal["supply-chain"] = "supply-chain"
    status: str = "ok"
    mriot: str = ""
    currency: str = "USD"
    totalDirect: float = Field(default=0.0, description="Direct AAI on the portfolio.")
    totalIndirect: float = Field(default=0.0, description="Indirect impact via the I/O table.")
    amplification: float | None = Field(default=None, description="indirect / direct.")
    bySector: list[SupplyChainSector] = Field(default_factory=list)
    detail: str | None = None


class CalibrationResult(BaseModel):
    """Engine output for an impact-function calibration run (base.py ``CalibrationResult``)."""

    kind: Literal["calibration"] = "calibration"
    status: str = "ok"
    peril: str = "tropical_cyclone"
    country: str = ""
    param: str = "v_half"
    initial: float = 0.0
    calibrated: float = 0.0
    observedAnnualLoss: float = 0.0
    detail: str | None = None


class ForecastSeriesPoint(BaseModel):
    """One step of the near-term expected-impact series."""

    label: str
    value: float


class ForecastResult(BaseModel):
    """Engine output for an operational forecast run (base.py ``ForecastResult`` + series)."""

    kind: Literal["forecast"] = "forecast"
    status: str = "ok"
    peril: str = "tropical_cyclone"
    nTracks: int = 0
    totalImpact: float = Field(default=0.0, description="Ensemble-mean forecast impact.")
    currency: str = "USD"
    perAsset: list[AssetImpact] = Field(default_factory=list)
    series: list[ForecastSeriesPoint] = Field(
        default_factory=list, description="Near-term expected impact per season."
    )
    detail: str | None = None


RunResult = Annotated[
    Union[
        PhysicalRunOutput,
        UncertaintyResult,
        CostBenefitResult,
        SupplyChainResult,
        CalibrationResult,
        ForecastResult,
    ],
    Field(discriminator="kind"),
]

RUN_KINDS: tuple[str, ...] = (
    "physical",
    "uncertainty",
    "cost-benefit",
    "supply-chain",
    "calibration",
    "forecast",
)


class Run(BaseModel):
    """A submitted physical-risk run and (once finished) its engine output."""

    id: str = Field(default_factory=_new_id)
    kind: str = "physical"
    status: str = RunStatus.QUEUED.value
    result: RunResult | None = None
    error: str | None = None
