"""Carbon-price schedule support.

The deterministic single-scalar carbon price still works (back-compat).
When the user provides a year→price schedule, the backend builds a
per-snapshot adder series and writes it onto every emitting generator's
``marginal_cost`` time series. Each snapshot picks the most-recent
schedule entry whose year is ≤ the snapshot's year, so a schedule like

    2025 →  30
    2030 →  60
    2040 → 120

applies $30/t through 2029, $60/t through 2039, and $120/t from 2040.

For pathway mode the "year" is read off the snapshot ``period`` level;
for single-period mode it's the calendar year of each snapshot
timestamp.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pypsa

from .utils.coerce import number


@dataclass(frozen=True)
class CarbonPriceScheduleEntry:
    year: int
    price: float


@dataclass(frozen=True)
class CarbonPriceConfig:
    scalar: float
    schedule: tuple[CarbonPriceScheduleEntry, ...]

    @property
    def is_scheduled(self) -> bool:
        return len(self.schedule) > 0


def parse_carbon_price_config(scalar: float, raw_schedule: Any) -> CarbonPriceConfig:
    """Build a config from the per-request ``carbonPrice`` scalar plus the
    optional ``carbonPriceSchedule`` array.

    Rows with missing/non-numeric year or price are dropped; the rest are
    deduplicated by year (last-write-wins) and sorted ascending.
    """
    entries: dict[int, float] = {}
    for raw in raw_schedule or []:
        try:
            year_val = int(number(raw.get("year"), float("nan")))
        except (TypeError, ValueError):
            continue
        if year_val <= 0:
            continue
        price_val = float(number(raw.get("price"), 0.0))
        entries[year_val] = price_val
    sorted_entries = tuple(
        CarbonPriceScheduleEntry(year=y, price=p)
        for y, p in sorted(entries.items())
    )
    return CarbonPriceConfig(scalar=float(scalar or 0.0), schedule=sorted_entries)


def _snapshot_years(snapshots: pd.Index) -> pd.Index:
    if isinstance(snapshots, pd.MultiIndex) and "period" in (snapshots.names or []):
        return pd.Index(snapshots.get_level_values("period"))
    if isinstance(snapshots, pd.MultiIndex):
        ts = snapshots.get_level_values(-1)
    else:
        ts = snapshots
    try:
        return pd.to_datetime(ts).year
    except Exception:
        return pd.Index([0] * len(snapshots))


def build_price_series(network: pypsa.Network, config: CarbonPriceConfig) -> pd.Series:
    """Per-snapshot carbon price ($/tCO₂) — constant if scalar-only, varying
    if a schedule is provided. Returns a Series indexed by ``network.snapshots``."""
    snapshots = network.snapshots
    if not config.is_scheduled:
        return pd.Series(config.scalar, index=snapshots, dtype=float)

    years = [entry.year for entry in config.schedule]
    prices = [entry.price for entry in config.schedule]
    snap_years = _snapshot_years(snapshots)
    values: list[float] = []
    for raw_year in snap_years:
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


def apply_carbon_price(
    network: pypsa.Network,
    config: CarbonPriceConfig,
    notes: list[str],
    currency_symbol: str,
) -> None:
    """Add the carbon adder to every emitting generator's marginal cost."""
    if "co2_emissions" not in network.carriers.columns:
        return
    series = build_price_series(network, config)
    if (series <= 0).all():
        return

    ef_per_carrier = network.carriers["co2_emissions"]
    if isinstance(ef_per_carrier.index, pd.MultiIndex) and "name" in ef_per_carrier.index.names:
        ef_per_carrier = ef_per_carrier.groupby(level="name").first()

    gen_ef = network.generators["carrier"].map(ef_per_carrier).fillna(0.0)
    emitting = gen_ef[gen_ef > 0]
    if emitting.empty:
        return

    is_varying = config.is_scheduled and series.nunique(dropna=False) > 1

    if not is_varying:
        # Constant scalar — preserve the historical static + dynamic-merge
        # behaviour so generators using static `marginal_cost` aren't forced
        # onto the per-snapshot path.
        constant = float(series.iloc[0])
        network.generators["marginal_cost"] = (
            network.generators["marginal_cost"].fillna(0.0) + constant * gen_ef
        )
        mc_t = network.generators_t.marginal_cost
        for gen in mc_t.columns.intersection(emitting.index):
            mc_t[gen] = mc_t[gen].fillna(0.0) + constant * float(emitting[gen])
        notes.append(
            f"Applied carbon price {constant:.2f} {currency_symbol}/t to "
            f"{len(emitting)} emitting generator(s)."
        )
        return

    # Schedule with varying values — always write to the time-varying frame so
    # the per-snapshot precision survives. PyPSA prefers the `_t` column over
    # the static value when both are present, so no double-counting.
    mc_t = network.generators_t.marginal_cost
    for gen in emitting.index:
        adder = series * float(emitting[gen])
        if gen in mc_t.columns:
            mc_t[gen] = mc_t[gen].fillna(0.0) + adder
        else:
            base_static = float(network.generators.at[gen, "marginal_cost"]) if "marginal_cost" in network.generators.columns else 0.0
            mc_t[gen] = base_static + adder

    schedule_summary = ", ".join(f"{e.year}→{e.price:.0f}" for e in config.schedule)
    notes.append(
        f"Applied carbon price schedule [{schedule_summary}] {currency_symbol}/t "
        f"to {len(emitting)} emitting generator(s)."
    )
