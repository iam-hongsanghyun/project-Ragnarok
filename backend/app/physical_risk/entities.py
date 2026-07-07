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


class Portfolio(BaseModel):
    """The session model — a named set of assets keyed by session id."""

    sessionId: str = Field(default_factory=_new_id)
    assets: list[Asset] = Field(default_factory=list)


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


class PhysicalRunOutput(BaseModel):
    """The full engine output for one run (one result per requested peril)."""

    currency: str = "USD"
    perils: list[PhysicalRunResult] = Field(default_factory=list)


class Scenario(BaseModel):
    """The scenario context a run is evaluated under."""

    rcp: str = "rcp45"
    horizon: int = 2050


class Run(BaseModel):
    """A submitted physical-risk run and (once finished) its engine output."""

    id: str = Field(default_factory=_new_id)
    status: str = RunStatus.QUEUED.value
    result: PhysicalRunOutput | None = None
    error: str | None = None
