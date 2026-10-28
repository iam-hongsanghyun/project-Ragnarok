"""Hot / warm / cold start costs of a committable plant: the sheet, the plan and the constraint rows.

PyPSA has one ``start_up_cost`` per unit. This module adds the start TYPE, keyed on how long the unit was offline before the
start. It is off unless a plant sets a warm or cold cost (spec ``startCostWarm`` / ``startCostCold``); a plant without them keeps
PyPSA's single ``start_up_cost`` and every number it had.

Sheet ``RAGNAROK_StartCosts`` (visible, round-tripping, one row per value; same layout as ``RAGNAROK_TimeUnits``): ``component``
(``generators`` / ``links``), ``name``, ``attribute`` (``hot_cost`` / ``warm_cost`` / ``cold_cost`` in currency per start; ``warm_after`` /
``cold_after`` offline durations), ``value``, ``unit`` (``currency_per_start`` / ``hours`` or ``minutes``).

No double counting: the native ``start_up_cost`` of the component is the HOT cost, so PyPSA charges every start the hot cost and the
hook below adds only the increments of the warm and cold tiers. If the hook is off (module not loaded) the unit is charged the hot cost
on every start, the lowest of the three.

Algorithm (per unit, snapshots t = 0..T-1, binary status u_t and start-up v_t are PyPSA's ``status`` and ``start_up``):
    Tier thresholds :math:`T_j` (hours) are converted by the time-units module with the run's step :math:`w` (hours, the smallest
    ``stores`` weighting): :math:`K_j = \\lceil T_j / w \\rceil` snapshots. With :math:`c_0` (hot) :math:`\\le c_1 \\le \\dots`
    the costs of the tiers, a start at t is of tier :math:`\\ge j` iff the unit was OFF in all :math:`K_j` snapshots before t. For
    each tier one continuous variable :math:`y^j_t \\ge 0`:
    $$ y^j_t \\;\\ge\\; v_t - \\sum_{k=1}^{K_j} u_{t-k}, \\qquad \\min\\; \\sum_t \\Big(\\sum_j (c_j - c_{j-1})\\, y^j_t\\Big) $$
    Because :math:`c_j \\ge c_{j-1}` the cost pushes :math:`y^j_t` down onto its bound, so it equals 1 exactly for a start after at least
    :math:`K_j` snapshots off and is 0 otherwise (the u's are binary in a MIP, so no further binary is needed). The charge of a start
    is :math:`c_0 + \\sum_{j: \\text{off} \\ge K_j}(c_j - c_{j-1}) = c_{tier}` with the native :math:`c_0 v_t` included.
    Snapshots before the horizon use PyPSA's own history rule (``up_time_before`` / ``down_time_before``: on for ``lag <= up`` or off for
    ``lag <= down`` and on beyond it).
    ASCII: y[j,t] >= v[t] - sum_{k=1..K_j} u[t-k];  obj += sum_j (c_j - c_(j-1)) * sum_t y[j,t];  K_j = ceil(T_j / w).

The costs are per start and unweighted, like PyPSA's own ``start_up_cost``.

Applies to: fixed-size committable Generators and Links on a contiguous single-period run. Refused (400) with stochastic scenarios, a
rolling horizon, sampled blocks (snapshots not adjacent in time) and a multi-period pathway. With Force-LP (``linearized_unit_commitment``)
the statuses are continuous: the rows stay valid and the tiers are a consistent relaxation (a fractional status can lower the charge), the
run note says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np

SHEET = "RAGNAROK_StartCosts"
COSTS = ("hot_cost", "warm_cost", "cold_cost")
AFTER = ("warm_after", "cold_after")
COST_UNIT = "currency_per_start"
DURATION_UNITS = {"hours": 1.0, "minutes": 1.0 / 60.0}
COMPONENTS = {"generators": "Generator", "links": "Link"}
TIER_NAMES = ("hot", "warm", "cold")


@dataclass(frozen=True)
class Plan:
    """One unit's tiers: ``hot`` (currency per start) and ``tiers`` = ``[(after_hours, cost), ...]`` with rising hours and cost."""

    component: str
    name: str
    hot: float
    tiers: tuple[tuple[float, float], ...]
    labels: tuple[str, ...]


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def rows_for(component: str, name: str, *, hot: float, warm: float | None, cold: float | None, warm_after_h: float | None,
             cold_after_h: float | None) -> list[dict[str, Any]]:
    """The sheet rows of one unit (costs in currency per start, durations in hours)."""
    out = [{"component": component, "name": name, "attribute": "hot_cost", "value": hot, "unit": COST_UNIT}]
    if warm is not None:
        out += [{"component": component, "name": name, "attribute": "warm_cost", "value": warm, "unit": COST_UNIT},
                {"component": component, "name": name, "attribute": "warm_after", "value": warm_after_h, "unit": "hours"}]
    if cold is not None:
        out += [{"component": component, "name": name, "attribute": "cold_cost", "value": cold, "unit": COST_UNIT},
                {"component": component, "name": name, "attribute": "cold_after", "value": cold_after_h, "unit": "hours"}]
    return out


def check_spec(hot: float, warm: float | None, cold: float | None, warm_after_h: float | None, cold_after_h: float | None) -> None:
    """Validate a plant's tier inputs (``ValueError`` with the reason).

    Costs must not fall as the unit stays offline longer (a falling cost would be bought by idling: the increment would be negative and
    the variable unbounded), each cost needs its offline threshold and the thresholds must rise.
    """
    if hot < 0 or (warm is not None and warm < 0) or (cold is not None and cold < 0):
        raise ValueError("Start costs must be >= 0.")
    for label, cost, after in (("warm", warm, warm_after_h), ("cold", cold, cold_after_h)):
        if cost is not None and (after is None or after <= 0):
            raise ValueError(f"A {label} start cost needs {label}After (hours offline before a start counts as {label}), > 0.")
        if cost is None and after is not None:
            raise ValueError(f"{label}After is set without a {label} start cost.")
    chain = [("hot", hot)] + [(n, c) for n, c in (("warm", warm), ("cold", cold)) if c is not None]
    for (n0, c0), (n1, c1) in pairwise(chain):
        if c1 < c0 - 1e-12:
            raise ValueError(f"Start costs must not fall with the offline time: {n1} {c1:g} < {n0} {c0:g}.")
    if warm is not None and cold is not None and not warm_after_h < cold_after_h:  # type: ignore[operator]
        raise ValueError(f"warmAfter ({warm_after_h:g} h) must be shorter than coldAfter ({cold_after_h:g} h).")


def read_plans(model: dict[str, Any]) -> list[Plan]:
    """Every unit's plan from the model sheet. Raises ``ValueError`` naming each unreadable row."""
    by_unit: dict[tuple[str, str], dict[str, float]] = {}
    problems: list[str] = []
    for i, row in enumerate(model.get(SHEET) or []):
        if not isinstance(row, dict):
            continue
        comp, name, attr = (str(row.get(k, "")).strip() for k in ("component", "name", "attribute"))
        value = _f(row.get("value"))
        if not (comp or name or attr) and value is None:
            continue
        unit = str(row.get("unit") or "").strip()
        where = f"row {i + 1}"
        if comp not in COMPONENTS:
            problems.append(f"{where}: component {comp!r} must be one of {', '.join(COMPONENTS)}")
        elif attr not in COSTS + AFTER:
            problems.append(f"{where}: attribute {attr!r} must be one of {', '.join(COSTS + AFTER)}")
        elif not name:
            problems.append(f"{where}: no name")
        elif value is None or value < 0:
            problems.append(f"{where}: value must be a number >= 0")
        elif attr in COSTS and unit not in ("", COST_UNIT):
            problems.append(f"{where}: unit {unit!r} for {attr} must be {COST_UNIT}")
        elif attr in AFTER and unit not in DURATION_UNITS:
            problems.append(f"{where}: unit {unit!r} for {attr} must be one of {', '.join(DURATION_UNITS)}")
        else:
            seen = by_unit.setdefault((comp, name), {})
            if attr in seen:
                problems.append(f"{where}: {comp}.{name}.{attr} appears twice")
            else:
                seen[attr] = value * (DURATION_UNITS[unit] if attr in AFTER else 1.0)
    if problems:
        raise ValueError(f"{SHEET}: " + "; ".join(problems))
    plans: list[Plan] = []
    for (comp, name), v in by_unit.items():
        hot = v.get("hot_cost", 0.0)
        warm, cold = v.get("warm_cost"), v.get("cold_cost")
        try:
            check_spec(hot, warm, cold, v.get("warm_after"), v.get("cold_after"))
        except ValueError as exc:
            raise ValueError(f"{SHEET} {comp}.{name}: {exc}") from exc
        tiers = [(v["warm_after"], warm, "warm")] if warm is not None else []
        if cold is not None:
            tiers.append((v["cold_after"], cold, "cold"))
        if tiers:
            plans.append(Plan(comp, name, hot, tuple((h, c) for h, c, _ in tiers), tuple(lbl for _, _, lbl in tiers)))
    return plans


# ── history, classification (pure numpy: used by the constraint rows, the results and the tests) ─────────────


def pre_horizon_status(up_time_before: float, down_time_before: float, length: int) -> np.ndarray:
    """Status at lags ``1..length`` before the horizon (index 0 = the snapshot right before it), PyPSA's rule.

    ``down_time_before > 0``: off for ``lag <= down``, on beyond; otherwise on for ``lag <= up_time_before`` and off beyond.
    """
    lag = np.arange(1, length + 1)
    return ((lag > down_time_before) if down_time_before > 0 else (lag <= up_time_before)).astype(float)


def classify_starts(status: np.ndarray, thresholds: list[int], up_time_before: float = 0.0, down_time_before: float = 0.0) -> list[int]:
    """Tier of every start in ``status`` (0 = hot, 1 = warm, 2 = cold ...), in time order.

    A start at t is of tier j when the unit was off in all ``thresholds[j-1]`` snapshots before it (thresholds in snapshots, rising).
    """
    u = (np.asarray(status, dtype=float) > 0.5).astype(float)
    reach = max(thresholds) if thresholds else 1
    hist = pre_horizon_status(up_time_before, down_time_before, reach + 1)
    ext = np.concatenate([hist[::-1], u])
    base = len(hist)
    tiers: list[int] = []
    for t in range(len(u)):
        i = base + t
        if ext[i] > 0.5 and ext[i - 1] < 0.5:
            tiers.append(sum(1 for k in thresholds if ext[i - k:i].sum() < 0.5))
    return tiers


def snapshot_thresholds(hours: list[float], step_h: float, name: str, component: str) -> tuple[list[int], list[str]]:
    """Offline durations in hours to snapshots with the time-units module's rule (``ceil(hours / w)``) and its rounding notes."""
    from ...pypsa.network import time_units as tu

    counts: list[int] = []
    notes: list[str] = []
    for h in hours:
        value, note = tu.convert(tu.TimeRow(component, name, "min_down_time", float(h), "hours"), step_h)
        counts.append(int(value))
        if note:
            notes.append(note.replace("min_down_time", "start-cost tier"))
    return counts, notes


# ── the constraint rows ────────────────────────────────────────────────────────────────────────────────────


def _tier_deltas(plan: Plan) -> list[tuple[str, float]]:
    """``(label, delta)`` of each tier charged on top of the hot cost: its cost minus the previous tier's (skipped when not higher)."""
    out: list[tuple[str, float]] = []
    prev_cost = plan.hot
    for (_, cost), label in zip(plan.tiers, plan.labels):
        delta = cost - prev_cost
        prev_cost = cost
        if delta > 0:
            out.append((label, delta))
    return out


def _var_name(plan: Plan, label: str) -> str:
    return f"startcost-{plan.component}-{plan.name}-{label}"


def tier_increment(n: Any, plans: list[Plan]) -> float | None:
    r"""The tier objective term at the solution, ``sum_j delta_j sum_t y_j[t]`` (currency); ``None`` when the solved model is gone.

    Algorithm: $$C = \sum_j \Delta_j \sum_t y_{j,t}$$ with $\Delta_j$ the cost step of tier j over the previous tier (currency per start)
    and $y_{j,t} \ge 0$ the solved tier variable. ASCII: C = sum_j delta_j * sum_t y_j[t].
    """
    m = getattr(n, "model", None)
    if m is None:
        return None
    total = 0.0
    for plan in plans:
        for label, delta in _tier_deltas(plan):
            name = _var_name(plan, label)
            if name in m.variables:
                total += delta * float(m.variables[name].solution.sum())
    return total


def apply_start_cost_tiers(n: Any, plans: list[Plan], snapshots: Any, notes: list[str]) -> None:
    """Add the tier variables, rows and objective term to ``n.model`` (call inside ``extra_functionality``, once per model)."""
    from linopy import merge

    from ...pypsa.network import time_units as tu

    if not plans:
        return
    m = n.model
    step_h, uniform = tu.step_hours(n)
    declared: list[str] = []
    for plan in plans:
        cname = COMPONENTS[plan.component]
        comp = n.components[plan.component]
        status_key, start_key = f"{cname}-status", f"{cname}-start_up"
        if plan.name not in comp.static.index:
            raise ValueError(f"{SHEET} names {plan.component}.{plan.name}, which is not in the model.")
        if status_key not in m.variables or plan.name not in m[status_key].indexes["name"]:
            notes.append(f"Start-cost tiers: {plan.component}.{plan.name} is not committable in this run, so only its native start_up_cost applies.")
            continue
        status = m[status_key].sel(name=plan.name, drop=True)
        start = m[start_key].sel(name=plan.name, drop=True)
        idx = status.indexes["snapshot"]
        up_b = float(comp.static.at[plan.name, "up_time_before"])
        down_b = float(comp.static.at[plan.name, "down_time_before"])
        counts, rounding = snapshot_thresholds([h for h, _ in plan.tiers], step_h, plan.name, plan.component)
        notes.extend(f"Time units: {r}." for r in rounding)
        deltas = dict(_tier_deltas(plan))
        for (hours, cost), k_j, label in zip(plan.tiers, counts, plan.labels):
            if label not in deltas:
                continue
            delta = deltas[label]
            hist = pre_horizon_status(up_b, down_b, k_j)                      # lags 1..K_j before the horizon
            before = np.array([hist[: max(k_j - t, 0)].sum() for t in range(len(idx))], dtype=float)
            y = m.add_variables(lower=0, coords=[idx], name=_var_name(plan, label))
            lhs = y - start
            if k_j >= 1:
                shifted = [status.to_linexpr().shift(snapshot=k).fillna(0) for k in range(1, k_j + 1)]
                lhs = lhs + merge(shifted)
            import xarray as xr

            rhs = xr.DataArray(-before, coords={"snapshot": idx}, dims=["snapshot"])
            m.add_constraints(lhs >= rhs, name=f"startcost-{plan.component}-{plan.name}-{label}-lower")
            m.objective.expression = m.objective.expression + delta * y.sum()
            declared.append(f"{plan.component}.{plan.name} {label} {cost:g} (hot {plan.hot:g}) after {hours:g} h = {k_j} snapshot(s) off")
    if declared:
        notes.append(
            "Start-cost tiers (plants module): per start, the native start_up_cost is the HOT cost and a start after a long outage is charged the "
            "difference to the warm / cold cost as an extra objective term (nothing is counted twice); offline hours -> snapshots with the run's "
            f"{step_h:g} h step. Units: " + "; ".join(declared) + "."
        )
        if not uniform:
            notes.append(f"Start-cost tiers: the snapshot weights are not uniform; the smallest step ({step_h:g} h) was used (thresholds are at least the stated hours).")
        if getattr(n, "_linearized_uc", False):
            notes.append("Start-cost tiers under Force-LP: the status variables are continuous, so the tier rows are a consistent relaxation (a fractional "
                         "status can lower the charge); the MIP gives the exact cost.")
