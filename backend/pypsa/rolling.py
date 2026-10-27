from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .utils.coerce import number


@dataclass
class RollingHorizonConfig:
    enabled: bool
    horizon_snapshots: int
    overlap_snapshots: int
    step_snapshots: int


def parse_rolling_config(raw: dict[str, Any] | None) -> RollingHorizonConfig:
    raw = raw or {}
    enabled = bool(raw.get("enabled"))
    horizon = max(1, int(number(raw.get("horizonSnapshots"), 168)))
    overlap = max(0, int(number(raw.get("overlapSnapshots"), 24)))
    step = max(1, horizon - overlap)
    return RollingHorizonConfig(
        enabled=enabled,
        horizon_snapshots=horizon,
        overlap_snapshots=overlap,
        step_snapshots=step,
    )
