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


# ── the visible action: write the weightings from the timestamp spacing ────────────────

WEIGHT_COLUMNS = ("objective", "stores", "generators")


def spacing_weights(stamps: Sequence[Any], periods: Sequence[Any] | None = None) -> tuple[list[float], list[str]]:
    """Weight in hours of each snapshot = the time to the NEXT snapshot of the same period (irregular spacing allowed).

    A snapshot stands for the interval it starts, so its weight is the forward gap. The last snapshot of a period (or of
    the whole axis) has no next one and repeats the previous gap of its period; a period with a single snapshot takes the
    median gap of the axis. The jump from one investment period to the next is never a snapshot's weight. A gap that is
    not positive (a duplicate or unsorted stamp) is replaced by the median gap and reported.

    Algorithm:
        $$ w_i = (t_{i+1} - t_i) / 1\\,\\mathrm{h},\\quad i \\text{ not last in its period};\\qquad w_{last} = w_{last-1} $$

    ASCII: w[i] = hours(t[i+1] - t[i]); the last of a period repeats w[last-1].

    Returns:
        ``(weights_hours, notes)``.

    Raises:
        ValueError: the labels are not timestamps.
    """
    try:
        ts = pd.DatetimeIndex(pd.to_datetime(list(stamps)))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("The snapshot labels are not timestamps, so there is no spacing to read.") from exc
    n = len(ts)
    if n == 0:
        return [], []
    groups = list(periods) if periods is not None else [0] * n
    gaps = np.full(n, np.nan)
    for i in range(n - 1):
        if groups[i] == groups[i + 1]:
            gaps[i] = (ts[i + 1] - ts[i]).total_seconds() / 3600.0
    valid = gaps[np.isfinite(gaps) & (gaps > 0)]
    median = float(np.median(valid)) if valid.size else 1.0
    notes: list[str] = []
    bad = np.isfinite(gaps) & (gaps <= 0)
    if bad.any():
        notes.append(f"{int(bad.sum())} snapshot(s) have a duplicate or out-of-order timestamp: they take the median spacing ({median:g} h).")
        gaps[bad] = median
    out = gaps.copy()
    for i in range(n):
        if not np.isfinite(out[i]):  # last of its period
            j = i - 1
            while j >= 0 and groups[j] == groups[i] and not np.isfinite(gaps[j]):
                j -= 1
            out[i] = gaps[j] if j >= 0 and groups[j] == groups[i] and np.isfinite(gaps[j]) else median
    if valid.size and (valid.max() - valid.min()) > TOLERANCE * median:
        notes.append(f"The spacing is irregular ({valid.min():g}-{valid.max():g} h): each snapshot carries the gap to the next.")
    return [float(x) for x in out], notes


def set_weightings_from_spacing(model: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The workbook with ``objective`` / ``stores`` / ``generators`` of the ``snapshots`` sheet filled from the timestamps.

    Visible and explicit (the model-check warning ``weighting_spacing`` offers it): the three columns are the weights of
    :func:`spacing_weights`; a pathway workbook (a ``period`` column) is read inside each period. The input is not
    mutated. Returns ``(model, report)`` with ``report`` = ``{changed, rows, medianSpacingHours, before, notes}``.

    Raises:
        ValueError: no ``snapshots`` sheet, or its labels are not timestamps.
    """
    rows = [dict(r) if isinstance(r, dict) else r for r in model.get("snapshots") or []]
    labelled = [r for r in rows if isinstance(r, dict) and str(r.get("snapshot", "")).strip()]
    if len(labelled) < 1:
        raise ValueError("The workbook has no snapshots sheet to read a spacing from.")
    has_period = any(str(r.get("period", "")).strip() for r in labelled)
    periods = [str(r.get("period", "")).strip() for r in labelled] if has_period else None
    weights, notes = spacing_weights([_norm_label(r["snapshot"]) for r in labelled], periods)
    before = [next((r.get(c) for c in WEIGHT_COLUMNS if r.get(c) not in (None, "")), None) for r in labelled]
    changed = 0
    for r, w, b in zip(labelled, weights, before):
        for col in WEIGHT_COLUMNS:
            r[col] = w
        if b is None or abs(float(b) - w) > 1e-12:
            changed += 1
    out = dict(model)
    out["snapshots"] = rows
    report = {
        "changed": changed, "rows": len(labelled), "medianSpacingHours": float(np.median(weights)) if weights else None,
        "totalHours": float(sum(weights)), "notes": notes,
    }
    return out, report


def _norm_label(value: Any) -> str:
    return str(value).strip().replace("T", " ")


def median_weighting_hours(rows: Sequence[dict[str, Any]] | None) -> float | None:
    """Median authored weighting of a ``snapshots`` sheet in hours (generators, then objective, then stores); ``None`` if none."""
    for col in ("generators", "objective", "stores"):
        values: list[float] = []
        for r in rows or []:
            try:
                v = float(r.get(col))
            except (TypeError, ValueError):
                continue
            if np.isfinite(v) and v > 0:
                values.append(v)
        if values:
            return float(np.median(values))
    return None
