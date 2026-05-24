from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .utils.coerce import number


@dataclass
class PathwayPeriod:
    period: int
    objective_weight: float
    years_weight: float


@dataclass
class PathwayConfig:
    enabled: bool
    planning_mode: str
    snapshot_mapping_mode: str
    periods: list[PathwayPeriod]
    selected_period: int | None


def parse_pathway_config(raw: dict[str, Any] | None) -> PathwayConfig:
    raw = raw or {}
    enabled = bool(raw.get("enabled")) or str(raw.get("planningMode")) == "pathway"
    periods: list[PathwayPeriod] = []
    for item in raw.get("periods") or []:
      try:
        period = int(number(item.get("period")))
      except Exception:
        continue
      periods.append(
        PathwayPeriod(
          period=period,
          objective_weight=float(number(item.get("objectiveWeight"), 1.0)),
          years_weight=float(number(item.get("yearsWeight"), 1.0)),
        )
      )
    periods.sort(key=lambda row: row.period)
    selected_raw = raw.get("selectedPeriod")
    selected_period = None
    if selected_raw not in (None, ""):
      try:
        selected_period = int(number(selected_raw))
      except Exception:
        selected_period = None
    return PathwayConfig(
      enabled=enabled,
      planning_mode="pathway" if enabled else "single_period",
      snapshot_mapping_mode=str(raw.get("snapshotMappingMode") or "explicit_period_column"),
      periods=periods,
      selected_period=selected_period,
    )


def pathway_period_index(config: PathwayConfig) -> pd.Index:
    return pd.Index([row.period for row in config.periods], name="period", dtype="int64")
