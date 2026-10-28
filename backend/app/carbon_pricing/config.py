"""The carbon-price input: a scalar, or a year -> price schedule, and the per-snapshot series it implies.

Algorithm:
    The price in force at snapshot :math:`t` of calendar (or pathway-period) year :math:`y(t)` is

    $$ \\pi_t = \\begin{cases} \\pi^{sched}_{k(t)}, & k(t) = \\max\\{k : y_k \\le y(t)\\} \\\\
                   \\pi^{sched}_{1}, & y(t) < y_1 \\;(\\text{the first entry is the explicit fallback}) \\\\
                   \\pi^{scalar}, & \\text{no schedule} \\end{cases} $$

    ASCII: price[t] = schedule price of the latest year <= year(t); the first entry before it;
    the scalar when there is no schedule. A schedule supersedes the scalar.

    :math:`\\pi` in currency/tCO2, :math:`y` in years. In a pathway run :math:`y(t)` is the
    snapshot's investment-period label; otherwise the calendar year of the timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ...pypsa.utils.coerce import number

#: ``network.meta`` key under which a built network carries the price it was built for.
PLAN_KEY = "ragnarok_carbon_price"


@dataclass(frozen=True)
class CarbonPriceScheduleEntry:
    """One schedule row: the price that applies from ``year`` on."""

    year: int
    price: float


@dataclass(frozen=True)
class CarbonPriceConfig:
    """Scalar price and optional schedule. ``enabled=False`` keeps the inputs but sends PyPSA nothing."""

    scalar: float
    schedule: tuple[CarbonPriceScheduleEntry, ...]
    enabled: bool = True

    @property
    def is_scheduled(self) -> bool:
        return len(self.schedule) > 0

    @property
    def is_active(self) -> bool:
        """True when some snapshot can carry a positive price."""
        if not self.enabled:
            return False
        if self.is_scheduled:
            return any(entry.price > 0 for entry in self.schedule)
        return self.scalar > 0

    def to_meta(self) -> dict[str, Any]:
        """JSON-safe form stored in ``network.meta`` (and rebuilt by :func:`from_meta`)."""
        return {
            "scalar": self.scalar,
            "schedule": [{"year": e.year, "price": e.price} for e in self.schedule],
            "enabled": self.enabled,
        }


def parse_carbon_price_config(scalar: float, raw_schedule: Any, *, enabled: bool = True) -> CarbonPriceConfig:
    """Build a config from the per-request ``carbonPrice`` scalar plus the optional ``carbonPriceSchedule``.

    Rows with a missing / non-numeric year or price are dropped; the rest are deduplicated by year
    (last write wins) and sorted ascending.
    """
    entries: dict[int, float] = {}
    for raw in raw_schedule or []:
        try:
            year_val = int(number(raw.get("year"), float("nan")))
        except (TypeError, ValueError, AttributeError):
            continue
        if year_val <= 0:
            continue
        entries[year_val] = float(number(raw.get("price"), 0.0))
    return CarbonPriceConfig(
        scalar=float(scalar or 0.0),
        schedule=tuple(CarbonPriceScheduleEntry(year=y, price=p) for y, p in sorted(entries.items())),
        enabled=enabled,
    )


def config_from_run(scenario: dict[str, Any] | None, options: dict[str, Any] | None) -> CarbonPriceConfig:
    """The module's configuration of a run: ``scenario.carbonPrice``, ``options.carbonPriceSchedule``,
    ``options.carbonPricing.enabled``."""
    block = (options or {}).get("carbonPricing")
    enabled = not (isinstance(block, dict) and block.get("enabled") is False)
    return parse_carbon_price_config(
        number((scenario or {}).get("carbonPrice"), 0.0),
        (options or {}).get("carbonPriceSchedule"),
        enabled=enabled,
    )


def from_meta(raw: Any) -> CarbonPriceConfig | None:
    """Inverse of :meth:`CarbonPriceConfig.to_meta`; ``None`` for anything else."""
    if not isinstance(raw, dict):
        return None
    return parse_carbon_price_config(
        number(raw.get("scalar"), 0.0), raw.get("schedule"), enabled=raw.get("enabled") is not False
    )


def snapshot_years(snapshots: pd.Index) -> pd.Index:
    """Year of each snapshot: the ``period`` level in a pathway run, else the calendar year."""
    if isinstance(snapshots, pd.MultiIndex) and "period" in (snapshots.names or []):
        return pd.Index(snapshots.get_level_values("period"))
    ts = snapshots.get_level_values(-1) if isinstance(snapshots, pd.MultiIndex) else snapshots
    try:
        return pd.to_datetime(ts).year
    except Exception:  # noqa: BLE001 - labels that are not dates: no year, the fallback entry applies
        return pd.Index([0] * len(snapshots))


def price_series(config: CarbonPriceConfig, snapshots: pd.Index) -> pd.Series:
    """Per-snapshot carbon price (currency/tCO2), indexed by ``snapshots``."""
    if not config.enabled:
        return pd.Series(0.0, index=snapshots, dtype=float)
    if not config.is_scheduled:
        return pd.Series(config.scalar, index=snapshots, dtype=float)
    years = [entry.year for entry in config.schedule]
    prices = [entry.price for entry in config.schedule]
    values: list[float] = []
    for raw_year in snapshot_years(snapshots):
        try:
            year_val = int(raw_year)
        except (TypeError, ValueError):
            values.append(prices[0])
            continue
        applicable: float | None = None
        for yr, pr in zip(years, prices):
            if yr <= year_val:
                applicable = pr
        values.append(applicable if applicable is not None else prices[0])
    return pd.Series(values, index=snapshots, dtype=float)


def early_snapshots(config: CarbonPriceConfig, snapshots: pd.Index) -> int:
    """Snapshots before the first schedule year (priced at the first entry)."""
    if not (config.enabled and config.is_scheduled):
        return 0
    first = config.schedule[0].year
    return int(sum(1 for y in snapshot_years(snapshots) if int(y) < first))
