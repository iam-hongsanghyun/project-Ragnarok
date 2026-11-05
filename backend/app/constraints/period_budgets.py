"""Period budgets: energy or emission limits over a stated period (a month, a year, any range), right in every
run mode that dispatches window by window.

Two sources become the same budget:

* the ``RAGNAROK_PeriodBudgets`` sheet (one row per limit: a month's hydro generation, a year's CO2 ...);
* under rolling horizon, the model's own WHOLE-RUN limits, which PyPSA would otherwise apply in full to every
  window: a ``primary_energy`` CO2 ``GlobalConstraint``, an ``operational_limit`` ``GlobalConstraint`` on a
  generator carrier, and a generator's finite ``e_sum_max`` / ``e_sum_min`` (:func:`carry_whole_run_limits`).

Sheet columns (one row per budget):

=============  ===================================================================================
``name``       label used in the constraint name and the notes (optional)
``measure``    ``energy`` (MWh of generator output, default) or ``emissions`` (tCO2)
``carrier``    generator carrier(s), comma separated; blank = every generator (``emissions`` only)
``generator``  generator name(s), comma separated; when given it replaces ``carrier``
``period``     ``YYYY-MM`` (a month), ``YYYY`` (a year) or blank with ``start`` / ``end``
``start``      first instant of the period (inclusive); blank = start of the run
``end``        end of the period (exclusive); blank = end of the run
``sense``      ``<=`` (default), ``>=`` or ``==``
``value``      the period TOTAL: MWh for ``energy``, tCO2 for ``emissions``
=============  ===================================================================================

Algorithm:
    For a budget with total :math:`B` over period :math:`P` and the window :math:`W` being optimised:

    $$ \\sum_{t\\in P\\cap W} w_t \\sum_{g\\in G} a_g\\, p_{g,t} \\;\\lessgtr\\; B_W,\\qquad
       B_W = (B - U_W)\\,\\frac{H_{P\\cap W}}{H_{P,\\,t\\ge t_0(W)}} $$

    ASCII: sum_{t in P and W} w[t] * sum_g a[g] * p[g,t]  (<=, >=, ==)  (B - U) * H(P in W) / H(P from window start)

    * :math:`w_t` the ``generators`` snapshot weighting (h), :math:`p_{g,t}` generator dispatch (MW);
    * :math:`a_g = 1` for ``energy`` (MWh) or :math:`a_g = e_{c(g)}/\\eta_g` for ``emissions`` (tCO2/MWh_el, the
      carrier's ``co2_emissions`` over the efficiency - PyPSA's ``primary_energy`` rule for generators);
    * :math:`U_W` what the period has already used in the snapshots before the window, from the dispatch the
      earlier windows committed; :math:`H` weighted hours.

    A single solve has one window covering the run: :math:`U = 0`, :math:`B_W = B`, the exact period constraint.
    Under rolling horizon each window gets what is LEFT of the budget in proportion to the hours of the period it
    sees, so what a window under-spends carries over to the next and the run never overspends; a period that lies
    inside one window (monthly windows, monthly budgets) is constrained exactly as in a single solve. A ``<=`` share
    is never below 0. Overlapping rows are re-solved by the next window and counted only once they are committed.

Pathway (multi-period) and stochastic runs are refused (the dispatch carries a period / scenario index), as are
power-flow and contingency modes, which solve no LP.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

from backend.app import module_hooks as mh
from backend.app.emissions.accounting import (
    carrier_emission_factors,
    thermal_basis_factor,
)
from backend.pypsa.network.snapshots import parse_snapshot_labels

SHEET = "RAGNAROK_PeriodBudgets"
CONSTRAINT_PREFIX = "period_budget_"
META_KEY = "ragnarok_period_budgets"
_SENSES = {"<=": "<=", "≤": "<=", "max": "<=", ">=": ">=", "≥": ">=", "min": ">=", "==": "==", "=": "==", "eq": "=="}


@dataclass
class Budget:
    """One limit, resolved to generator names and a time range (``start`` inclusive, ``end`` exclusive)."""

    name: str
    measure: str  # "energy" | "emissions"
    generators: list[str]
    sense: str  # "<=" | ">=" | "=="
    value: float
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    source: str = SHEET
    label: str = field(default="")


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, float) and math.isnan(value))


def _names(value: Any) -> list[str]:
    return [] if _blank(value) else [s.strip() for s in str(value).split(",") if s.strip()]


def _period_bounds(row: dict[str, Any], where: str) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    period = row.get("period")
    if not _blank(period):
        text = str(period).strip()
        try:
            if len(text) == 4 and text.isdigit():
                start = pd.Timestamp(f"{text}-01-01")
                return start, start + pd.DateOffset(years=1)
            start = pd.Timestamp(f"{text}-01") if len(text) == 7 else pd.Timestamp(text)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"{where}: period {period!r} is not YYYY-MM or YYYY.") from None
        if len(text) == 7:
            return start, start + pd.DateOffset(months=1)
        raise HTTPException(status_code=400, detail=f"{where}: period {period!r} is not YYYY-MM or YYYY; use start/end for other ranges.")
    bounds: list[pd.Timestamp | None] = []
    for key in ("start", "end"):
        raw = row.get(key)
        if _blank(raw):
            bounds.append(None)
            continue
        try:
            bounds.append(pd.Timestamp(parse_snapshot_labels([str(raw)])[0]))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"{where}: {key} {raw!r} is not a date/time.") from None
    if bounds[0] is not None and bounds[1] is not None and bounds[1] <= bounds[0]:
        raise HTTPException(status_code=400, detail=f"{where}: end must be after start.")
    return bounds[0], bounds[1]


def read_sheet(model: dict[str, Any] | None, generators: pd.DataFrame | None = None) -> list[Budget]:
    """The sheet's rows as budgets. With ``generators`` (the built network's table) carriers are resolved to names.

    Raises ``HTTPException(400)`` on a row that cannot be read: a limit that is mis-read must stop the run, not
    loosen it.
    """
    rows = [r for r in ((model or {}).get(SHEET) or []) if isinstance(r, dict)]
    out: list[Budget] = []
    for i, r in enumerate(rows):
        if all(_blank(v) for v in r.values()):
            continue
        where = f"{SHEET} row {i + 1}"
        measure = str(r.get("measure") or "energy").strip().lower()
        if measure not in ("energy", "emissions"):
            raise HTTPException(status_code=400, detail=f"{where}: measure must be energy or emissions, got {r.get('measure')!r}.")
        sense = _SENSES.get(str(r.get("sense") or "<=").strip().lower())
        if sense is None:
            raise HTTPException(status_code=400, detail=f"{where}: sense must be <=, >= or ==, got {r.get('sense')!r}.")
        try:
            value = float(r.get("value"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"{where}: value {r.get('value')!r} is not a number.") from None
        if not math.isfinite(value):
            raise HTTPException(status_code=400, detail=f"{where}: value must be finite.")
        start, end = _period_bounds(r, where)
        carriers, gens = _names(r.get("carrier")), _names(r.get("generator"))
        if measure == "energy" and not carriers and not gens:
            raise HTTPException(status_code=400, detail=f"{where}: an energy budget needs a carrier or a generator.")
        names: list[str] = gens
        if generators is not None:
            if gens:
                missing = [g for g in gens if g not in generators.index]
                if missing:
                    raise HTTPException(status_code=400, detail=f"{where}: no generator named {', '.join(missing)}.")
            elif carriers:
                names = generators.index[generators["carrier"].astype(str).isin(carriers)].tolist()
            else:
                names = generators.index.tolist()
        label = str(r.get("name") or "").strip() or f"row{i + 1}"
        out.append(Budget(
            name=label, measure=measure, generators=names, sense=sense, value=value, start=start, end=end,
            label=f"{label} ({measure} {sense} {value:g} {'MWh' if measure == 'energy' else 'tCO2'}"
            f" over {_describe(start, end)}; {', '.join(gens or carriers) or 'all generators'})",
        ))
    return out


def _describe(start: pd.Timestamp | None, end: pd.Timestamp | None) -> str:
    if start is None and end is None:
        return "the whole run"
    return f"{'' if start is None else start}..{'' if end is None else end}"


def has_rows(model: dict[str, Any] | None) -> bool:
    return any(isinstance(r, dict) and any(not _blank(v) for v in r.values()) for r in ((model or {}).get(SHEET) or []))


def refused_modes(ctx: mh.RunContext) -> list[str]:
    modes = []
    if ctx.pathway is not None and bool(getattr(ctx.pathway, "enabled", False)):
        modes.append("multi-investment-period pathway")
    if ctx.stochastic is not None and bool(getattr(ctx.stochastic, "enabled", False)):
        modes.append("stochastic")
    if ctx.pf_enabled:
        modes.append("power-flow")
    if ctx.contingency_enabled:
        modes.append("contingency")
    return modes


def guard(ctx: mh.RunContext) -> None:
    if not has_rows(ctx.model):
        return
    modes = refused_modes(ctx)
    if modes:
        raise HTTPException(
            status_code=400,
            detail=f"{SHEET} holds period budgets, which cannot be applied in {', '.join(modes)} mode. "
            "Clear the sheet or run single-period / rolling-horizon.",
        )
    read_sheet(ctx.model)  # a malformed row is a 400 before anything is built


def to_meta(b: Budget) -> dict[str, Any]:
    """A budget as plain data (``n.meta`` is exported with the network)."""
    return {
        "name": b.name, "measure": b.measure, "generators": list(b.generators), "sense": b.sense, "value": b.value,
        "start": None if b.start is None else b.start.isoformat(), "end": None if b.end is None else b.end.isoformat(),
        "source": b.source, "label": b.label,
    }


def from_meta(d: dict[str, Any]) -> Budget:
    return Budget(
        name=str(d["name"]), measure=str(d["measure"]), generators=list(d["generators"]), sense=str(d["sense"]),
        value=float(d["value"]), start=None if d.get("start") is None else pd.Timestamp(d["start"]),
        end=None if d.get("end") is None else pd.Timestamp(d["end"]), source=str(d.get("source", SHEET)),
        label=str(d.get("label", "")),
    )


# ── whole-run limits under rolling horizon ────────────────────────────────────────


def _emitting_non_generators(n: Any) -> list[str]:
    """Components other than generators whose carrier has a CO2 factor (PyPSA's primary_energy counts them too)."""
    factors = carrier_emission_factors(n)
    out = []
    for list_name in ("storage_units", "stores", "links"):
        frame = getattr(n, list_name, None)
        if frame is None or not len(frame) or "carrier" not in frame.columns:
            continue
        hit = [str(c) for c in frame["carrier"].unique() if abs(float(factors.get(str(c), 0.0) or 0.0)) > 0]
        if hit:
            out.append(f"{list_name} ({', '.join(sorted(set(hit)))})")
    return out


def carry_whole_run_limits(n: Any, notes: list[str]) -> list[Budget]:
    """Rolling horizon: turn the model's whole-run limits into tracked budgets, so each window gets its share.

    Converted (and removed from the PyPSA tables, so PyPSA does not also apply them to every window):

    * ``primary_energy`` ``GlobalConstraint`` on ``co2_emissions`` without an ``investment_period`` -> an
      ``emissions`` budget on every generator, when no storage / store / link carries an emitting carrier
      (PyPSA would count those too);
    * ``operational_limit`` ``GlobalConstraint`` on a carrier that only generators carry -> an ``energy`` budget;
    * a generator's finite ``e_sum_max`` / ``e_sum_min`` -> an ``energy`` budget on that generator.

    Anything else is left in place, and the rolling check reports it.
    """
    budgets: list[Budget] = []
    gc = n.global_constraints
    drop: list[str] = []
    for name, row in gc.iterrows():
        kind = str(row.get("type", ""))
        attr = str(row.get("carrier_attribute", ""))
        period = row.get("investment_period")
        if period is not None and not (isinstance(period, float) and math.isnan(period)) and str(period).strip():
            continue
        sense = _SENSES.get(str(row.get("sense", "<=")).strip())
        try:
            value = float(row.get("constant"))
        except (TypeError, ValueError):
            continue
        if sense is None or not math.isfinite(value):
            continue
        if kind == "primary_energy" and attr == "co2_emissions":
            others = _emitting_non_generators(n)
            if others:
                notes.append(
                    f"Rolling horizon: CO2 limit '{name}' also counts {'; '.join(others)}, which a window budget does not "
                    "track - it is left as a PyPSA constraint (and refused)."
                )
                continue
            budgets.append(Budget(name=str(name), measure="emissions", generators=n.generators.index.tolist(), sense=sense,
                                  value=value, source="global_constraints",
                                  label=f"{name} (CO2 {sense} {value:g} t over the whole run)"))
            drop.append(str(name))
        elif kind == "operational_limit" and attr:
            carried_elsewhere = [
                ln for ln in ("storage_units", "stores", "links")
                if len(getattr(n, ln)) and "carrier" in getattr(n, ln).columns and (getattr(n, ln)["carrier"].astype(str) == attr).any()
            ]
            if carried_elsewhere:
                continue
            gens = n.generators.index[n.generators["carrier"].astype(str) == attr].tolist()
            budgets.append(Budget(name=str(name), measure="energy", generators=gens, sense=sense, value=value,
                                  source="global_constraints",
                                  label=f"{name} ({attr} energy {sense} {value:g} MWh over the whole run)"))
            drop.append(str(name))
    if drop:
        n.remove("GlobalConstraint", drop)
    gens = n.generators
    for col, sense in (("e_sum_max", "<="), ("e_sum_min", ">=")):
        if col not in gens.columns:
            continue
        values = pd.to_numeric(gens[col], errors="coerce")
        for gname, v in values.items():
            if v is None or not np.isfinite(v):
                continue
            budgets.append(Budget(name=f"{gname}-{col}", measure="energy", generators=[str(gname)], sense=sense, value=float(v),
                                  source="generators", label=f"{gname}.{col} ({sense} {float(v):g} MWh over the whole run)"))
            n.generators.loc[gname, col] = np.inf if col == "e_sum_max" else -np.inf
    if budgets:
        n.meta[META_KEY] = [*(n.meta.get(META_KEY) or []), *(to_meta(b) for b in budgets)]
        notes.append(
            "Rolling horizon: " + "; ".join(b.label for b in budgets[:6]) + (" ..." if len(budgets) > 6 else "")
            + " applied per window from what is left of each limit (period budget rule), not in full to every window."
        )
    return budgets


# ── the constraint ──────────────────────────────────────────────────────────────


def _factors(n: Any, budget: Budget) -> pd.Series:
    names = [g for g in budget.generators if g in n.generators.index]
    if budget.measure == "energy":
        return pd.Series(1.0, index=names, dtype=float)
    ef = carrier_emission_factors(n)
    co2 = n.generators.loc[names, "carrier"].map(lambda c: float(ef.get(str(c), 0.0) or 0.0)).astype(float)
    eta = n.generators.loc[names, "efficiency"] if "efficiency" in n.generators.columns else pd.Series(1.0, index=names)
    return thermal_basis_factor(co2, eta).astype(float)


def _in_period(index: pd.Index, budget: Budget) -> np.ndarray:
    times = index if isinstance(index, pd.DatetimeIndex) else pd.DatetimeIndex(parse_snapshot_labels(list(map(str, index))))
    mask = np.ones(len(times), dtype=bool)
    if budget.start is not None:
        mask &= np.asarray(times >= budget.start)
    if budget.end is not None:
        mask &= np.asarray(times < budget.end)
    return mask


def window_rhs(n: Any, budget: Budget, window: pd.Index, factors: pd.Series) -> tuple[float, float] | None:
    """``(right-hand side for this window, weighted hours of the period inside it)``; ``None`` when the window holds
    none of the period. See the module docstring for the rule."""
    w = n.snapshot_weightings["generators"].astype(float)
    full_mask = _in_period(n.snapshots, budget)
    win_set = set(window)
    in_window = np.array([s in win_set for s in n.snapshots]) & full_mask
    h_window = float(w[in_window].sum())
    if h_window <= 0:
        return None
    first = int(np.flatnonzero(np.array([s in win_set for s in n.snapshots]))[0])
    before = full_mask.copy()
    before[first:] = False
    from_start = full_mask.copy()
    from_start[:first] = False
    used = 0.0
    if before.any() and len(factors):
        p = n.generators_t.p.reindex(columns=factors.index).fillna(0.0)
        rows = p.loc[n.snapshots[before]]
        used = float((rows.mul(w[before], axis=0) * factors).to_numpy().sum())
    h_left = float(w[from_start].sum())
    rhs = (budget.value - used) * (h_window / h_left if h_left > 0 else 1.0)
    if budget.sense == "<=":
        rhs = max(rhs, 0.0)
    return rhs, h_window


def prepare(ctx: mh.RunContext) -> Callable[[Any, Any], None] | None:
    n = ctx.network
    if n is None:
        return None
    budgets = [from_meta(d) for d in (n.meta.get(META_KEY, []) if isinstance(n.meta, dict) else [])]
    if has_rows(ctx.model):
        if refused_modes(ctx):
            guard(ctx)
        sheet = read_sheet(ctx.model, n.generators)
        for b in sheet:
            if not b.generators:
                ctx.notes.append(f"{SHEET}: {b.label} - no generator matches, not applied.")
                continue
            if not _in_period(n.snapshots, b).any():
                ctx.notes.append(f"{SHEET}: {b.label} - the period holds none of the modelled snapshots, not applied.")
                continue
            budgets.append(b)
        if sheet:
            ctx.notes.append(f"{SHEET}: {len(budgets)} period budget(s) applied" + (
                " per rolling window from what is left of each" if getattr(ctx.rolling, "enabled", False) else "") + ".")
    if not budgets:
        return None

    def contribute(net: Any, snapshots: Any) -> None:
        import xarray as xr

        p = net.model["Generator-p"]
        if "scenario" in p.dims or isinstance(p.coords["snapshot"].to_index(), pd.MultiIndex):
            raise HTTPException(status_code=400, detail="Period budgets cannot be applied to a multi-period or stochastic model.")
        dim = next(d for d in p.dims if d != "snapshot")
        index = p.coords["snapshot"].to_index()
        w = net.snapshot_weightings["generators"].reindex(index).astype(float)
        for i, b in enumerate(budgets):
            factors = _factors(net, b)
            factors = factors[factors.index.isin(p.coords[dim].to_index())]
            if not len(factors):
                continue
            share = window_rhs(net, b, index, factors)
            if share is None:
                continue
            rhs, _hours = share
            mask = _in_period(index, b)
            weights = xr.DataArray(np.where(mask, w.to_numpy(), 0.0), coords={"snapshot": index}, dims="snapshot")
            a = xr.DataArray(factors.to_numpy(), coords={dim: factors.index}, dims=dim)
            lhs = (p.sel({dim: factors.index.tolist()}) * a * weights).sum()
            safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in b.name)
            cname = f"{CONSTRAINT_PREFIX}{i}_{safe}"
            if b.sense == "<=":
                net.model.add_constraints(lhs <= rhs, name=cname)
            elif b.sense == ">=":
                net.model.add_constraints(lhs >= rhs, name=cname)
            else:
                net.model.add_constraints(lhs == rhs, name=cname)

    return contribute
