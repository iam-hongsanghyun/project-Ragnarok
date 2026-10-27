"""Phase-shifting transformer view (PyPSA >= 1.4): the optimised angle per snapshot.

A transformer with ``phase_shift_min < phase_shift_max`` has its phase shift
optimised as a per-snapshot decision variable by ``n.optimize()``; the chosen
value lands in ``transformers_t.phase_shift_opt`` (degrees). This summarises it:
bounds, mean / min / max chosen angle, the share of snapshots at a bound (a
binding PST), and the series itself for charting.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pypsa


def optimised_phase_shifters(network: pypsa.Network) -> list[str]:
    """Names of transformers whose phase shift is a decision variable."""
    t = network.transformers
    if t.empty or "phase_shift_min" not in t.columns or "phase_shift_max" not in t.columns:
        return []
    mask = t["phase_shift_min"].astype(float) < t["phase_shift_max"].astype(float)
    return [str(x) for x in t.index[mask]]


def build_phase_shifters(network: pypsa.Network, max_points: int = 500) -> dict[str, Any] | None:
    """Per-PST optimised-angle summary, or ``None`` when no PST is optimised/solved."""
    names = optimised_phase_shifters(network)
    opt = getattr(network.transformers_t, "phase_shift_opt", None)
    if not names or opt is None or getattr(opt, "empty", True):
        return None
    rows: list[dict[str, Any]] = []
    tol = 1e-6
    for name in names:
        if name not in opt.columns:
            continue
        lo = float(network.transformers.at[name, "phase_shift_min"])
        hi = float(network.transformers.at[name, "phase_shift_max"])
        s = opt[name].astype(float)
        at_bound = float(((s - lo).abs() <= tol).mean() + ((s - hi).abs() <= tol).mean())
        step = max(1, int(np.ceil(len(s) / max_points)))
        rows.append({
            "name": name,
            "phaseShiftMinDeg": lo,
            "phaseShiftMaxDeg": hi,
            "meanDeg": round(float(s.mean()), 6),
            "minDeg": round(float(s.min()), 6),
            "maxDeg": round(float(s.max()), 6),
            "shareAtBound": round(at_bound, 4),
            "series": [
                {"snapshot": str(ts), "phaseShiftDeg": round(float(v), 6)}
                for ts, v in list(s.items())[::step]
            ],
        })
    return {"unit": "degrees", "transformers": rows} if rows else None
