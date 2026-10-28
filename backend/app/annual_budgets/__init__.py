"""Annual-budgets module: yearly energy and emission budgets, written into PyPSA as horizon totals.

PyPSA's ``e_sum_min`` / ``e_sum_max`` (generators) and the ``constant`` of a ``GlobalConstraint``
(``primary_energy`` CO2 cap, ``operational_limit``) are TOTALS over the weighted modelled snapshots; they
are never scaled to the horizon. A budget stated per year must therefore be multiplied by the horizon
before PyPSA sees it. This module keeps the per-year value in the model sheet ``RAGNAROK_AnnualBudgets`` and
writes the horizon value into the PyPSA column, visibly: in the run notes, in ``annualBudgets`` of the
results, and in the workbook through the Apply action.

Algorithm:
    For a budget with annual value :math:`A` over a set of snapshots :math:`S`

    $$ V = A \\cdot \\frac{\\sum_{t\\in S} w_t\\, y_{p(t)}}{8760} $$

    ASCII: value = annual * sum_t(w[t] * y[period(t)]) / 8760

    :math:`w_t` is the ``generators`` snapshot weighting (hours each snapshot represents): the weighting
    PyPSA itself applies inside the ``e_sum`` and ``primary_energy`` constraints, and the SAME one the
    spacing check compares with the timestamps. :math:`y_p` is the investment-period ``years`` weighting that
    ``primary_energy`` / ``operational_limit`` apply in a multi-period run (1 for ``e_sum``, which PyPSA does
    not weight by years, and outside pathways).

    * single period: :math:`S` = every modelled snapshot, :math:`y=1` -> ``annual * hours / 8760``;
    * pathway, ``e_sum`` (whole horizon): :math:`S` = all periods -> ``annual * total hours / 8760``;
      PyPSA gives one total for the whole horizon, so energy may move between periods. A per-period
      split needs a global constraint with ``investment_period``;
    * pathway, global constraint with ``investment_period = p``: :math:`S` = that period ->
      ``annual * H_p / 8760 * years_p``, a total over that period's ``years_p`` years;
    * pathway, global constraint without ``investment_period``: all periods, each weighted by its years.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pypsa

from ...pypsa.utils.weightings import spacing_mismatch

SHEET = "RAGNAROK_AnnualBudgets"
META_KEY = "ragnarok_annual_budgets"
HOURS_PER_YEAR = 8760.0

#: sheet -> (PyPSA frame, columns that can carry an annual budget)
TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "generators": ("generators", ("e_sum_min", "e_sum_max")),
    "global_constraints": ("global_constraints", ("constant",)),
}
_PLACEHOLDER = 1e9


@dataclass(frozen=True)
class BudgetRow:
    component: str
    name: str
    attribute: str
    annual: float


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def read_rows(model: dict[str, Any]) -> list[BudgetRow]:
    """The module's rows. Raises ``ValueError`` naming every row that cannot be read."""
    out: list[BudgetRow] = []
    problems: list[str] = []
    for i, row in enumerate(model.get(SHEET) or []):
        if not isinstance(row, dict):
            continue
        comp = str(row.get("component", "")).strip()
        name = str(row.get("name", "")).strip()
        attr = str(row.get("attribute", "")).strip()
        annual = _num(row.get("annual"))
        if not (comp or name or attr) and annual is None:
            continue
        if comp not in TARGETS or attr not in TARGETS[comp][1]:
            problems.append(f"row {i + 1}: {comp}.{attr} is not a budget target (allowed: "
                            + ", ".join(f"{c}.{a}" for c, (_, attrs) in TARGETS.items() for a in attrs) + ")")
        elif not name:
            problems.append(f"row {i + 1}: no name")
        elif annual is None or annual < 0:
            problems.append(f"row {i + 1}: annual must be a number >= 0")
        else:
            out.append(BudgetRow(comp, name, attr, float(annual)))
    if problems:
        raise ValueError(f"{SHEET}: " + "; ".join(problems))
    return out


def _frame(network: pypsa.Network, component: str) -> pd.DataFrame:
    return getattr(network, TARGETS[component][0])


def _weights(network: pypsa.Network) -> pd.Series:
    return network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0).astype(float)


def _pathway(network: pypsa.Network) -> bool:
    s = network.snapshots
    return isinstance(s, pd.MultiIndex) and "period" in (s.names or [])


def horizon_value(network: pypsa.Network, annual: float, *, years_weighted: bool, period: Any = None) -> tuple[float, float]:
    """``(value, equivalent years)`` of an annual budget over the network's snapshots (see module docs)."""
    w = _weights(network)
    if _pathway(network):
        level = network.snapshots.get_level_values("period")
        if period is not None:
            keep = level == int(period)
            w = w[keep]
            level = level[keep]
        if years_weighted:
            y = network.investment_period_weightings["years"].reindex(level).fillna(1.0).to_numpy()
            w = w * y
    years = float(w.sum()) / HOURS_PER_YEAR
    return annual * years, years


def compute_table(network: pypsa.Network, rows: list[BudgetRow]) -> list[dict[str, Any]]:
    """What the module writes: one dict per budget row (``value`` is the horizon value for PyPSA).

    Raises:
        ValueError: a row names a component that is not in the network.
    """
    table: list[dict[str, Any]] = []
    missing: list[str] = []
    gc = network.global_constraints
    for r in rows:
        frame = _frame(network, r.component)
        if r.name not in frame.index:
            missing.append(f"{r.component}.{r.name}")
            continue
        period = None
        years_weighted = r.component == "global_constraints"
        scope = "whole horizon"
        if r.component == "global_constraints" and _pathway(network):
            raw = _num(gc.at[r.name, "investment_period"]) if "investment_period" in gc.columns else None
            if raw is not None:
                period = int(raw)
                scope = f"period {period} (total over its years)"
            else:
                scope = "all periods, each weighted by its years"
        elif _pathway(network):
            scope = "all periods together (PyPSA: one whole-horizon total)"
        value, years = horizon_value(network, r.annual, years_weighted=years_weighted, period=period)
        table.append({
            "component": r.component, "name": r.name, "attribute": r.attribute, "annual": r.annual,
            "horizonYears": years, "value": value, "scope": scope,
        })
    if missing:
        raise ValueError(f"{SHEET} names components that are not in the model: {', '.join(missing)}")
    return table


def apply_to_network(
    network: pypsa.Network, model: dict[str, Any], notes: list[str], *, check_spacing: bool = True, enabled: bool = True,
    rolling: bool = False,
) -> list[dict[str, Any]]:
    """Write the horizon values into the PyPSA columns of ``network`` and say so in ``notes``.

    A no-op without the sheet. Also warns (never changes anything) when the timestamp spacing
    disagrees with the weighting the totals are built on.
    """
    rows = read_rows(model) if enabled else []
    if not rows:
        return []
    table = compute_table(network, rows)
    if rolling:
        # PyPSA's rolling-horizon helper applies e_sum and GlobalConstraint constants to EACH window, so a horizon
        # total written into the column would be spent in full by every window. The module splits it instead.
        gc_rows = [t for t in table if t["component"] == "global_constraints"]
        if gc_rows:
            raise ValueError(
                "Annual budgets on a GlobalConstraint (" + ", ".join(t["name"] for t in gc_rows) + ") cannot be combined with "
                "rolling horizon: PyPSA applies the constant to every window, not to the horizon. Turn rolling horizon off, "
                "or use an e_sum budget on a generator (split per window by committed hours)."
            )
        for t in table:
            t["scope"] += "; split per rolling window by committed hours (declared constraint, e_sum column left unbounded)"
    else:
        for t in table:
            _frame(network, t["component"]).loc[t["name"], t["attribute"]] = t["value"]
    network.meta[META_KEY] = table
    w = _weights(network)
    notes.append(
        f"Annual budgets: {len(table)} value(s) written as horizon totals = annual x sum(w)/8760, with the "
        f"'generators' snapshot weighting (sum {float(w.sum()):g} h over {len(w)} snapshots)"
        + ("; " + "; ".join(f"{t['component']}.{t['name']}.{t['attribute']} {t['annual']:g}/yr -> {t['value']:.6g} ({t['scope']})" for t in table[:6]))
        + (" ..." if len(table) > 6 else "") + "."
    )
    if check_spacing:
        warn = spacing_mismatch(network.snapshots, w.to_numpy(), where="Annual budgets: ")
        if warn:
            notes.append("Warning: " + warn["message"])
    return table


def apply_to_workbook(model: dict[str, Any], table: list[dict[str, Any]]) -> dict[str, Any]:
    """A copy of ``model`` with the table's values written into the component rows (the Apply action)."""
    out = dict(model)
    for sheet in {t["component"] for t in table}:
        rows = [dict(r) if isinstance(r, dict) else r for r in (out.get(sheet) or [])]
        out[sheet] = rows
        for t in (x for x in table if x["component"] == sheet):
            for row in rows:
                if isinstance(row, dict) and str(row.get("name", "")).strip() == t["name"]:
                    row[t["attribute"]] = t["value"]
    return out


def migrate_e_sum(model: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Schema 2 -> 3: ``e_sum_*`` values of generator rows had ANNUAL semantics; move them to the sheet.

    Finite values below the 1e9 placeholder move to ``RAGNAROK_AnnualBudgets`` (blanked in the row);
    inf / placeholders stay. The input is not mutated. Returns ``(model, moved)``.
    """
    out = dict(model)
    moved: list[dict[str, Any]] = []
    rows = [dict(r) if isinstance(r, dict) else r for r in (out.get("generators") or [])]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for attr in ("e_sum_min", "e_sum_max"):
            v = _num(row.get(attr))
            if v is None or math.isinf(v) or abs(v) >= _PLACEHOLDER:
                continue
            moved.append({"component": "generators", "name": str(row.get("name", "")), "attribute": attr, "annual": v})
            row.pop(attr, None)
    if not moved:
        return out, []
    out["generators"] = rows
    existing = [r for r in (out.get(SHEET) or []) if isinstance(r, dict)]
    out[SHEET] = existing + [dict(m) for m in moved]
    return out, moved


def extra_functionality(n: pypsa.Network, snapshots: Any = None) -> None:
    """Rolling horizon only: add each window's share of a generator ``e_sum`` budget as a declared constraint.

    Algorithm:
        $$ \\sum_{t\\in W} w_t\\,p_{g,t} \\le V_g\\,\\frac{H^{commit}_W}{H^{run}} $$
        ASCII: sum_{t in window} w[t] p[g,t] <= value * committed_hours(window) / run_hours

    :math:`V_g` the horizon total written by this module, :math:`H^{commit}_W` the weighted hours the window
    commits (horizon minus overlap), :math:`H^{run}` the run's weighted hours: the shares of the windows add up to
    exactly 1 (the rule ``custom_constraints.ModelContext.window_fraction`` uses for DSL budgets). The reverse
    sense for ``e_sum_min``. A no-op outside rolling horizon.
    """
    step = n.meta.get("ragnarok_rolling_step") if isinstance(n.meta, dict) else None
    table = n.meta.get(META_KEY) if isinstance(n.meta, dict) else None
    if not step or not table:
        return
    m = n.model
    p = m["Generator-p"]
    idx = p.indexes["snapshot"]
    full = _weights(n)
    w = full.reindex(idx).fillna(1.0)
    fraction = float(w.iloc[: int(step)].sum()) / float(full.sum())
    import xarray as xr

    wda = xr.DataArray(w.to_numpy(), coords={"snapshot": idx}, dims=("snapshot",))
    for t in table:
        if t["component"] != "generators" or t["name"] not in set(p.indexes["name"]):
            continue
        energy = (p.sel(name=t["name"]) * wda).sum("snapshot")
        rhs = t["value"] * fraction
        name = f"annual_budget-{t['name']}-{t['attribute']}"
        if t["attribute"] == "e_sum_max":
            m.add_constraints(energy <= rhs, name=name)
        else:
            m.add_constraints(energy >= rhs, name=name)
