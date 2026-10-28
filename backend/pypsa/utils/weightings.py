"""Snapshot spacing versus snapshot weightings.

PyPSA never reads the timestamps for energy: every energy, cost and budget total is ``sum(w_t * x_t)``
with ``w_t`` the snapshot weighting (hours each snapshot represents). A 4-hourly model whose
weightings are left at the default 1 therefore books a quarter of the real energy, silently. The
check here compares the median spacing of the timestamps with the median weighting and says so.
It only reports; it never changes a weighting.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

#: relative disagreement above which spacing and weighting are reported as different.
TOLERANCE = 0.01


def median_spacing_hours(index: pd.Index) -> float | None:
    """Median gap (hours) between consecutive timestamps; ``None`` when it cannot be read.

    A multi-period index is read inside each period (the jump between periods is not a step).
    """
    try:
        if isinstance(index, pd.MultiIndex):
            stamps = pd.to_datetime(index.get_level_values(-1))
            groups = index.get_level_values(0)
            gaps: list[float] = []
            for g in pd.unique(groups):
                sub = stamps[groups == g]
                if len(sub) > 1:
                    gaps.extend(np.diff(sub.values).astype("timedelta64[s]").astype(float) / 3600.0)
        else:
            stamps = pd.to_datetime(index)
            if len(stamps) < 2:
                return None
            gaps = list(np.diff(stamps.values).astype("timedelta64[s]").astype(float) / 3600.0)
    except Exception:  # noqa: BLE001 - labels that are not dates carry no spacing
        return None
    gaps = [g for g in gaps if g > 0]
    return float(np.median(gaps)) if gaps else None


def spacing_mismatch(index: pd.Index, weights: Sequence[float] | pd.Series, *, where: str = "") -> dict[str, Any] | None:
    """``{spacingHours, weightingHours, message}`` when spacing and weighting disagree, else ``None``."""
    spacing = median_spacing_hours(index)
    w = np.asarray(list(weights), dtype=float)
    w = w[np.isfinite(w) & (w > 0)]
    if spacing is None or w.size == 0:
        return None
    weighting = float(np.median(w))
    if abs(spacing - weighting) <= TOLERANCE * spacing:
        return None
    return {
        "spacingHours": spacing,
        "weightingHours": weighting,
        "message": (
            f"{where}the timestamps are {spacing:g} h apart but the snapshot weighting is {weighting:g}: PyPSA books "
            f"energy, costs and budgets by the weighting, so totals are {weighting / spacing:.3g} x the real ones. "
            "Set the weighting to the spacing in the snapshots sheet (objective / stores / generators columns); "
            "nothing was changed."
        ),
    }
