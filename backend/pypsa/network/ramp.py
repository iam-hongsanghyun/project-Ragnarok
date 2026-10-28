"""Ramp-rate results: a read-out of PyPSA's NATIVE ramp constraints.

Ragnarok no longer builds a ramp constraint of its own. PyPSA's ``ramp_limit_up`` / ``ramp_limit_down`` /
``ramp_limit_start_up`` / ``ramp_limit_shut_down`` (Generator, Link, Process) are the only ramp rows in the LP, so the
window coupling under rolling horizon, the committable formulation and the start / shut-down limits are PyPSA's.
What PyPSA lacks is the TIME UNIT: its limits are a fraction of ``p_nom`` per snapshot. The time-units module
(``network/time_units.py``) keeps a ramp in %/hour (or per minute) in ``RAGNAROK_TimeUnits`` and writes the per-snapshot
value from the weights the run uses; the ``rampConfig`` run option only fills that sheet with a default rate.

This module only reports: which generators carry a ramp bound in the solved network, how often it binds, and the
swing of the dispatch.

Algorithm:
    For generator :math:`g` with per-snapshot limit :math:`\\rho_g` (the written ``ramp_limit_up``) and capacity
    :math:`P_g`, the bound binds at :math:`t` when

    $$ p_{g,t} - p_{g,t-1} \\ge \\rho_g\\,P_g - \\epsilon $$

    (and the mirror for down). ASCII: delta_p >= rho * P - eps.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..constants import carrier_color
from ..utils.shedding import shedding_names
from . import time_units

_log = logging.getLogger("pypsa.solver")
_EPS = 1e-6


def extract_ramp_results(n: pypsa.Network, ramp_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """The ``"ramp"`` payload: binding snapshots and swings of the generators that carry a native ramp bound.

    ``enabled`` is true when any generator has a finite ``ramp_limit_up`` / ``ramp_limit_down`` in the solved network
    (typed in the column, or written by the time-units module). ``note`` carries the time step the limits were written for.
    """
    base: dict[str, Any] = {"enabled": False, "bindingHours": 0, "byCarrier": [], "summary": [], "note": None}
    try:
        gens = n.generators
        if gens.empty or "ramp_limit_up" not in gens.columns:
            return base
        up = pd.to_numeric(gens["ramp_limit_up"], errors="coerce")
        down = pd.to_numeric(gens["ramp_limit_down"], errors="coerce")
        shed = set(shedding_names(gens))
        bounded = [g for g in gens.index if g not in shed and (pd.notna(up.get(g)) or pd.notna(down.get(g)))]
        if not bounded:
            return base
        p_t = getattr(n.generators_t, "p", None)
        if p_t is None or p_t.empty:
            base.update(enabled=True, note="Ramp limits are set but no generator dispatch is available (see run notes).")
            return base
        bounded = [g for g in bounded if g in p_t.columns]
        dispatch = p_t.reindex(index=n.snapshots, columns=bounded).fillna(0.0)
        p_nom = (gens["p_nom_opt"] if "p_nom_opt" in gens.columns else gens["p_nom"]).reindex(bounded).fillna(0.0)
        p_nom = p_nom.where(p_nom > 0, gens["p_nom"].reindex(bounded).fillna(0.0))
        delta = dispatch.diff().iloc[1:]
        up_limit = (up.reindex(bounded).fillna(np.inf) * p_nom)
        down_limit = (down.reindex(bounded).fillna(np.inf) * p_nom)
        binding = ((delta >= up_limit - _EPS) & np.isfinite(up_limit)) | (((-delta) >= down_limit - _EPS) & np.isfinite(down_limit))
        binding_hours = int(binding.any(axis=1).sum())
        mean_abs = delta.abs().mean(axis=0)
        carriers = gens["carrier"].reindex(bounded).fillna("") if "carrier" in gens.columns else pd.Series("", index=bounded)
        by_carrier_mw: dict[str, float] = {}
        for g in bounded:
            by_carrier_mw[str(carriers.get(g, ""))] = by_carrier_mw.get(str(carriers.get(g, "")), 0.0) + float(mean_abs.get(g, 0.0))
        by_carrier = [
            {"label": c, "value": v, "color": carrier_color(n, c)}
            for c, v in sorted(by_carrier_mw.items(), key=lambda kv: kv[1], reverse=True) if v > 0.0
        ]
        step, uniform = time_units.step_hours(n)
        abs_delta = delta.abs()
        summary = [
            {"label": "Mean |Δp| across ramp-constrained generators",
             "value": f"{float(abs_delta.to_numpy().mean()) if abs_delta.size else 0.0:,.2f} MW",
             "detail": f"{len(bounded)} generator(s) with a ramp bound"},
            {"label": "Max |Δp|", "value": f"{float(abs_delta.to_numpy().max()) if abs_delta.size else 0.0:,.2f} MW",
             "detail": "largest single-snapshot dispatch swing"},
            {"label": "Binding hours", "value": f"{binding_hours} of {len(delta.index)}",
             "detail": "snapshots where an up or down ramp limit binds (PyPSA's native constraint)"},
            {"label": "Time step", "value": f"{step:g} h",
             "detail": "limits are fractions of p_nom per snapshot; the time-units module wrote them for this step"},
        ]
        return {"enabled": True, "bindingHours": binding_hours, "byCarrier": by_carrier, "summary": summary,
                "note": None if uniform else "Snapshot weights are not uniform: the smallest step was used for the limits."}
    except Exception as exc:  # noqa: BLE001 - a read-out must never fail a solved run
        base["note"] = f"Ramp results could not be extracted: {exc}"
        _log.warning("ramp extraction failed: %s", exc)
        return base
