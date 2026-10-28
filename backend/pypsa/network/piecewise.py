"""Piecewise-linear cost / efficiency curves (PyPSA >= 1.3) as workbook sheets.

PyPSA stores a curve as ``c.piecewise[attr]``: a frame with one breakpoint per row
and ``(name, attribute)`` columns, where ``attribute`` is the x axis (``p_pu``,
``p_dispatch_pu``, ``p_nom``, ``s_nom`` or ``e_nom``) and the y attribute itself
(``marginal_cost``, ``capital_cost``, ``efficiency``, ``rate0`` ...). Which
attributes accept a curve is PyPSA's own table (``pypsa/data/piecewise.csv``);
nothing is hardcoded here.

Workbook representation
-----------------------
One sheet per ``<list_name>-<attribute>-pw`` (the name PyPSA itself uses for its
CSV/Excel files, e.g. ``generators-marginal_cost-pw``), in LONG form: one row per
breakpoint of one component::

    name | breakpoint | p_pu | marginal_cost
    g1   | 0          | 0    | 0
    g1   | 1          | 0.5  | 10
    g1   | 2          | 1    | 40

``breakpoint`` is informational; rows of one ``name`` are sorted by the x column.

Meaning of y (PyPSA convention, ``cumulative_attr``)
----------------------------------------------------
Cost curves (``marginal_cost``, ``capital_cost``): the y at breakpoint ``i >= 1``
is the price per unit of x on the segment ``(x_{i-1}, x_i]``. The cost of
operating at ``x`` is

    C(x) = sum_i y_i * (min(x, x_i) - x_{i-1})+          [y_0 is ignored]

so a cost curve is convex (an LP, tangent cuts) iff ``y_1 <= y_2 <= ...``; any
other shape needs binaries/SOS2 (a MIP). ``efficiency`` / ``rate`` curves give the
operating value at each breakpoint and are an equality, so they are a MIP unless
the curve is a straight line.

``capital_cost`` curves go to PyPSA exactly as written, and PyPSA requires them to be
already periodised (per modelled horizon): a curve combined with ``overnight_cost`` is
refused (pypsa.optimization.optimize). Ragnarok neither annuitises nor window-scales them.

Carbon price is added to every segment price of a ``marginal_cost`` curve on an
emitting generator: ``y_i += price * co2 / eta`` for ``i >= 1``.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pypsa
from fastapi import HTTPException

PW_SUFFIX = "-pw"

# Default sign of the piecewise formulation per curve kind (PyPSA's own choice;
# a user override must repeat it because ``PiecewiseOptions.sign`` is mandatory).
_COST_ATTRS = ("marginal_cost", "capital_cost")
_METHODS = ("auto", "lp", "incremental", "sos2")


# ── Catalogue (PyPSA's piecewise.csv) ─────────────────────────────────────────


@lru_cache(maxsize=1)
def piecewise_catalog() -> tuple[dict[str, Any], ...]:
    """Every curve PyPSA supports, from ``pypsa/data/piecewise.csv``.

    Returns:
        Rows ``{component, list_name, attribute, x, ported, allow_extendable,
        kind, sheet, aux_variable, output}``. ``ported`` means the y attribute
        carries a port number (``efficiency2``, ``rate1``); ``kind`` is ``cost``
        or ``efficiency``; ``output`` is the ``*_piecewise_opt`` result name for
        cost curves.
    """
    from pypsa.constants import PYPSA_DATA_DIR

    table = pd.read_csv(PYPSA_DATA_DIR / "piecewise.csv")
    _n = pypsa.Network()
    list_names = {_n.components[k].name: k for k in _n.components.keys()}
    out: list[dict[str, Any]] = []
    for row in table.itertuples(index=False):
        list_name = list_names.get(row.component)
        if not list_name:
            continue
        is_cost = row.y in _COST_ATTRS
        out.append(
            {
                "component": row.component,
                "list_name": list_name,
                "attribute": row.y,
                "x": row.x,
                "ported": "{port}" in str(row.aux_variable),
                "allow_extendable": bool(row.allow_extendable),
                "kind": "cost" if is_cost else "efficiency",
                "sheet": piecewise_sheet_name(list_name, row.y),
                "aux_variable": row.aux_variable,
                "output": f"{row.y}_piecewise_opt" if is_cost else None,
            }
        )
    return tuple(out)


def piecewise_sheet_name(list_name: str, attribute: str) -> str:
    """``generators`` + ``marginal_cost`` -> ``generators-marginal_cost-pw``."""
    return f"{list_name}-{attribute}{PW_SUFFIX}"


def parse_piecewise_sheet_name(sheet: str) -> tuple[str, str] | None:
    """``generators-marginal_cost-pw`` -> ``("generators", "marginal_cost")`` or None."""
    if not isinstance(sheet, str) or not sheet.endswith(PW_SUFFIX):
        return None
    list_name, dash, attr = sheet[: -len(PW_SUFFIX)].partition("-")
    if not dash or not attr:
        return None
    return list_name, attr


def _spec(network: pypsa.Network, list_name: str, attr: str) -> pd.Series:
    """PyPSA's piecewise definition row for ``attr`` (empty Series when none)."""
    comp = network.components[list_name]
    return comp._piecewise_schema(attr)


def _base_attr(attr: str) -> str:
    """``efficiency2`` -> ``efficiency``; ``rate1`` -> ``rate``; ``marginal_cost`` unchanged."""
    return attr.rstrip("0123456789") if attr.rstrip("0123456789") in ("efficiency", "rate") else attr


# ── Curve maths (mirrored by frontend/src/lib/forge/piecewise.ts) ─────────────


def curve_shape(kind: str, xs: Iterable[float], ys: Iterable[float], *, invert: bool = False) -> str:
    """Classify a curve as ``convex`` (LP), ``linear`` (LP) or ``nonconvex`` (MIP).

    Algorithm:
        Cost curves ($y_i$ = price on segment $(x_{i-1}, x_i]$):
        $$ s_i = y_i \\quad (i \\ge 1),\\qquad \\text{convex} \\iff s_1 \\le s_2 \\le \\dots $$
        Efficiency / rate curves are equalities $Y(x_i) = y_i x_i$ (generator
        primary energy: $x_i / y_i$); with slopes
        $s_i = (Y_i - Y_{i-1})/(x_i - x_{i-1})$ the curve is LP-expressible only
        when all $s_i$ are equal (``linear``); otherwise ``nonconvex`` (MIP).
        ASCII: convex iff y1 <= y2 <= ...; efficiency: linear iff constant slope.

    Args:
        kind: ``"cost"`` or ``"efficiency"``.
        xs: breakpoint x values (any order).
        ys: breakpoint y values aligned with ``xs``.
        invert: efficiency of a Generator (primary energy is ``x / y``).

    Returns:
        ``"convex"``, ``"linear"`` or ``"nonconvex"``.
    """
    pts = sorted(zip((float(v) for v in xs), (float(v) for v in ys)))
    if len(pts) < 2:
        return "linear"
    tol = 1e-9
    if kind == "cost":
        slopes = [y for _, y in pts[1:]]
        if all(abs(s - slopes[0]) <= tol for s in slopes):
            return "linear"
        return "convex" if all(b >= a - tol for a, b in zip(slopes, slopes[1:])) else "nonconvex"
    values = []
    for x, y in pts:
        if invert:
            values.append(0.0 if x == 0 or y == 0 else x / y)
        else:
            values.append(x * y)
    slopes = [
        (v1 - v0) / (x1 - x0)
        for (x0, _), (x1, _), v0, v1 in zip(pts, pts[1:], values, values[1:])
        if x1 > x0
    ]
    if not slopes or all(abs(s - slopes[0]) <= 1e-9 * max(1.0, abs(slopes[0])) for s in slopes):
        return "linear"
    return "nonconvex"


# ── Sheet rows <-> PyPSA frames ───────────────────────────────────────────────


def _num(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"non-numeric breakpoint value {value!r}") from None
    if math.isnan(out):
        return None
    return out


def rows_to_frame(
    rows: list[dict[str, Any]], x_attr: str, attr: str, valid_names: set[str]
) -> tuple[pd.DataFrame, list[str]]:
    """Turn long-form sheet rows into PyPSA's ``(name, attribute)`` breakpoint frame.

    Args:
        rows: sheet rows ``{name, [breakpoint], <x_attr>, <attr>}`` (``x`` / ``y``
            are accepted as aliases for the two value columns).
        x_attr: x-axis attribute from PyPSA's catalogue.
        attr: y attribute (sheet attribute).
        valid_names: component names that exist; rows naming others are dropped.

    Returns:
        ``(frame, dropped)``: the frame (breakpoint index, columns
        ``MultiIndex[name, attribute]``, ragged curves NaN-padded at the end) and
        the names dropped for not existing.

    Raises:
        ValueError: on a non-numeric cell, a half-filled row, duplicate x values
            for one name, or a curve with fewer than two breakpoints.
    """
    curves: dict[str, list[tuple[float, float]]] = {}
    dropped: list[str] = []
    for i, row in enumerate(rows):
        name = str(row.get("name") if row.get("name") is not None else "").strip()
        if not name:
            continue
        x_raw = row[x_attr] if x_attr in row else row.get("x")
        y_raw = row[attr] if attr in row else row.get("y")
        x, y = _num(x_raw), _num(y_raw)
        if x is None and y is None:
            continue
        if x is None or y is None:
            raise ValueError(f"row {i + 1} ({name}) has only one of {x_attr!r} / {attr!r} filled")
        if name not in valid_names:
            if name not in dropped:
                dropped.append(name)
            continue
        curves.setdefault(name, []).append((x, y))
    if not curves:
        return pd.DataFrame(), dropped
    columns: dict[tuple[str, str], list[float]] = {}
    depth = 0
    for name, pts in curves.items():
        pts = sorted(pts)
        xs = [p[0] for p in pts]
        if len(set(xs)) != len(xs):
            raise ValueError(f"{name}: duplicate {x_attr} values - breakpoints must be strictly increasing")
        if len(pts) < 2:
            raise ValueError(f"{name}: a curve needs at least 2 breakpoints (start at {x_attr}=0)")
        columns[(name, x_attr)] = xs
        columns[(name, attr)] = [p[1] for p in pts]
        depth = max(depth, len(pts))
    data = {k: v + [np.nan] * (depth - len(v)) for k, v in columns.items()}
    frame = pd.DataFrame(data)
    frame.columns = pd.MultiIndex.from_tuples(list(data), names=["name", "attribute"])
    frame.index.name = "breakpoint"
    return frame, dropped


def network_piecewise_rows(network: pypsa.Network) -> dict[str, list[dict[str, Any]]]:
    """Every populated curve of ``network`` as ``{<list>-<attr>-pw: long rows}``."""
    out: dict[str, list[dict[str, Any]]] = {}
    for list_name in network.components.keys():
        comp = network.components[list_name]
        store = getattr(comp, "piecewise", None)
        if not store:
            continue
        for attr, frame in store.items():
            if frame is None or frame.empty:
                continue
            spec = _spec(network, list_name, attr)
            if spec.empty:
                continue
            x_attr = spec.x
            rows: list[dict[str, Any]] = []
            for name in frame.columns.unique("name"):
                xs = frame[(name, x_attr)]
                ys = frame[(name, attr)]
                k = 0
                for x, y in zip(xs, ys):
                    if pd.isna(x) or pd.isna(y):
                        continue
                    rows.append({"name": str(name), "breakpoint": k, x_attr: float(x), attr: float(y)})
                    k += 1
            if rows:
                out[piecewise_sheet_name(list_name, attr)] = rows
    return out


# ── Build ─────────────────────────────────────────────────────────────────────


def apply_piecewise_sheets(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    notes: list[str],
    *,
    stochastic: bool = False,
) -> int:
    """Attach every ``<list>-<attr>-pw`` sheet of ``model`` to ``network``.

    Must run after the components exist (curves are keyed by component name).

    Returns:
        The number of curves attached.

    Raises:
        HTTPException: 400 naming the sheet and component when PyPSA or the
            validation rejects a curve (extendable component on a per-unit axis,
            curve not starting at 0 / ending at 1, mixed signs, ...), and when
            curves are combined with stochastic scenarios (PyPSA does not
            support that yet).
    """
    attached = 0
    shapes: dict[str, int] = {"convex": 0, "linear": 0, "nonconvex": 0}
    for sheet, rows in model.items():
        parsed = parse_piecewise_sheet_name(sheet)
        if parsed is None or not rows:
            continue
        list_name, attr = parsed
        if list_name not in network.components.keys():
            notes.append(f"Piecewise sheet '{sheet}' names an unknown component list - ignored.")
            continue
        comp = network.components[list_name]
        spec = _spec(network, list_name, attr)
        if spec.empty:
            known = sorted({r["attribute"] for r in piecewise_catalog() if r["list_name"] == list_name})
            raise HTTPException(
                status_code=400,
                detail=f"Sheet '{sheet}': {attr!r} cannot be a piecewise curve on {comp.name}. "
                f"Supported: {known or 'none'}.",
            )
        if stochastic:
            raise HTTPException(
                status_code=400,
                detail=f"Piecewise curves ('{sheet}') cannot be combined with stochastic scenarios "
                "(PyPSA does not support piecewise data in stochastic networks).",
            )
        try:
            frame, dropped = rows_to_frame(
                rows, str(spec.x), attr, set(map(str, comp.static.index))
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Sheet '{sheet}': {exc}.") from exc
        if dropped:
            notes.append(
                f"Piecewise sheet '{sheet}': dropped curves for unknown component(s) {', '.join(dropped)}."
            )
        if frame.empty:
            continue
        try:
            network._import_piecewise_from_df(frame, comp.name, attr, overwrite=True)
        except (ValueError, TypeError, NotImplementedError) as exc:
            raise HTTPException(status_code=400, detail=f"Sheet '{sheet}': {exc}") from exc
        for name in frame.columns.unique("name"):
            pts = frame[name].dropna()
            shape = curve_shape(
                spec_kind(spec),
                pts[str(spec.x)],
                pts[attr],
                invert=(comp.name == "Generator" and _base_attr(attr) == "efficiency"),
            )
            shapes[shape] += 1
            attached += 1
    if attached:
        mip = shapes["nonconvex"]
        notes.append(
            f"Attached {attached} piecewise-linear curve(s) ({shapes['convex']} convex, "
            f"{shapes['linear']} linear, {mip} non-convex). "
            + (
                f"{mip} non-convex curve(s) need binaries - the run becomes a MIP."
                if mip
                else "All curves are LP-expressible."
            )
            + " A scalar marginal_cost / capital_cost on a component with a curve is ignored by PyPSA."
        )
    return attached


def spec_kind(spec: pd.Series) -> str:
    """``cost`` for marginal/capital cost curves, ``efficiency`` otherwise."""
    return "cost" if spec.y in _COST_ATTRS else "efficiency"


def has_piecewise(network: pypsa.Network, list_name: str, attr: str) -> bool:
    """True when ``list_name`` carries a curve for ``attr``."""
    if list_name not in network.components.keys():
        return False
    return bool(network.components[list_name].has_piecewise(attr))


def apply_carbon_to_curves(
    network: pypsa.Network,
    price_per_tonne: float,
    emission_factor: pd.Series,
    notes: list[str],
) -> int:
    """Add the carbon adder to every segment price of emitting generators' curves.

    ``y_i += price * ef`` for ``i >= 1`` (``ef`` is the electrical-basis factor
    ``co2 / eta``). ``y_0`` is ignored by PyPSA and left alone.
    """
    if price_per_tonne <= 0 or not has_piecewise(network, "generators", "marginal_cost"):
        return 0
    frame = network.components["generators"].piecewise["marginal_cost"]
    touched = 0
    for name in frame.columns.unique("name"):
        ef = float(emission_factor.get(name, 0.0) or 0.0)
        if ef <= 0:
            continue
        col = (name, "marginal_cost")
        values = frame[col].copy()
        values.iloc[1:] = values.iloc[1:] + price_per_tonne * ef
        frame[col] = values
        touched += 1
    if touched:
        notes.append(
            f"Added the carbon price ({price_per_tonne:g}/t) to every segment of {touched} "
            "generator marginal-cost curve(s)."
        )
    return touched


# ── Run options ───────────────────────────────────────────────────────────────


def parse_piecewise_options(raw: Any) -> tuple[dict[str, Any], ...]:
    """Validate the ``piecewiseOptions`` run option into ``PiecewiseOptions`` kwargs.

    Each entry: ``{"component": "Generator", "attribute": "marginal_cost",
    "method": "auto|lp|incremental|sos2", "name": ["g1", ...], "sign": ">="}``.
    ``component`` and ``attribute`` are required; ``sign`` defaults to PyPSA's own
    (``>=`` for cost curves, ``=`` for efficiency / rate curves); ``name`` limits
    the override to those components; ``method`` defaults to ``auto``.

    Raises:
        HTTPException: 400 on a malformed entry or an unsupported combination.
    """
    if raw in (None, "", [], ()):
        return ()
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise HTTPException(status_code=400, detail="piecewiseOptions must be a list of objects.")
    catalog = piecewise_catalog()
    out: list[dict[str, Any]] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"piecewiseOptions[{i}] must be an object.")
        component = str(entry.get("component") or "").strip()
        attribute = str(entry.get("attribute") or "").strip()
        rows = [r for r in catalog if r["component"] == component and r["attribute"] == _base_attr(attribute)]
        if not rows:
            raise HTTPException(
                status_code=400,
                detail=f"piecewiseOptions[{i}]: no piecewise curve {component}.{attribute}. Supported: "
                + ", ".join(sorted(f"{r['component']}.{r['attribute']}" for r in catalog)),
            )
        method = str(entry.get("method") or "auto").strip().lower()
        if method not in _METHODS:
            raise HTTPException(
                status_code=400, detail=f"piecewiseOptions[{i}].method must be one of {_METHODS}, got {method!r}."
            )
        default_sign = ">=" if rows[0]["kind"] == "cost" else "="
        sign = str(entry.get("sign") or default_sign).strip()
        if sign not in ("=", "<=", ">="):
            raise HTTPException(status_code=400, detail=f"piecewiseOptions[{i}].sign must be '=', '<=' or '>='.")
        names = entry.get("name") or entry.get("names") or []
        names = [names] if isinstance(names, str) else list(names)
        out.append(
            {
                "component": component,
                "attribute": attribute,
                "sign": sign,
                "method": method,
                "name": tuple(str(n) for n in names),
            }
        )
    return tuple(out)


# ── Results ───────────────────────────────────────────────────────────────────


def build_piecewise_results(network: pypsa.Network) -> dict[str, Any] | None:
    """Solved view of every piecewise curve: the curve plus its ``*_piecewise_opt``.

    ``marginal_cost_piecewise_opt`` is the realised average cost per MWh (the
    solved ``y / x`` of the auxiliary variable) per snapshot; ``capital_cost_piecewise_opt``
    is the realised average annual cost per unit of the optimal capacity.

    Returns:
        ``{"curves": [...], "totalOperatingCost", "totalCapitalCost"}`` or
        ``None`` when the network has no curves. Operating cost uses the
        ``objective`` snapshot weighting, so it adds into the LP objective.
    """
    rows: list[dict[str, Any]] = []
    weights = network.snapshot_weightings["objective"]
    total_opex = 0.0
    total_capex = 0.0
    for list_name in network.components.keys():
        comp = network.components[list_name]
        store = getattr(comp, "piecewise", None)
        if not store:
            continue
        for attr, frame in store.items():
            if frame is None or frame.empty:
                continue
            spec = _spec(network, list_name, attr)
            if spec.empty:
                continue
            x_attr = str(spec.x)
            kind = spec_kind(spec)
            for name in frame.columns.unique("name"):
                pts = frame[name].dropna()
                xs, ys = pts[x_attr].tolist(), pts[attr].tolist()
                invert = comp.name == "Generator" and _base_attr(attr) == "efficiency"
                row: dict[str, Any] = {
                    "component": comp.name,
                    "list": list_name,
                    "name": str(name),
                    "attribute": attr,
                    "xAttribute": x_attr,
                    "shape": curve_shape(kind, xs, ys, invert=invert),
                    "breakpoints": [{"x": float(x), "y": float(y)} for x, y in zip(xs, ys)],
                }
                solved: dict[str, Any] | None = None
                try:
                    if attr == "marginal_cost":
                        solved, cost = _solved_marginal(network, comp, str(name), weights)
                        total_opex += cost
                    elif attr == "capital_cost" and "capital_cost_piecewise_opt" in comp.static.columns:
                        opt = float(comp.static.at[name, "capital_cost_piecewise_opt"])
                        nom = float(comp.static.at[name, _nominal(comp.name) + "_opt"])
                        solved = {"averagePerUnit": opt, "capacityOpt": nom, "annualCost": opt * nom}
                        total_capex += opt * nom
                except Exception:  # noqa: BLE001 - a reporting extra must not sink the run
                    solved = None
                if solved is not None:
                    row["solved"] = solved
                rows.append(row)
    if not rows:
        return None
    return {
        "curves": rows,
        "totalOperatingCost": float(total_opex),
        "totalCapitalCost": float(total_capex),
    }


def _nominal(component: str) -> str:
    from pypsa.descriptors import nominal_attrs

    return nominal_attrs[component]


def _solved_marginal(
    network: pypsa.Network, comp: Any, name: str, weights: pd.Series
) -> tuple[dict[str, Any] | None, float]:
    """Statistics of ``marginal_cost_piecewise_opt`` and the curve's operating cost."""
    opt = comp.dynamic.get("marginal_cost_piecewise_opt")
    if opt is None or name not in opt.columns:
        return None, 0.0
    avg = opt[name].astype(float).fillna(0.0)
    p = _dispatch(comp, name)
    energy = (p * weights.reindex(avg.index).fillna(1.0)) if p is not None else None
    cost = float((avg * energy).sum()) if energy is not None else 0.0
    mwh = float(energy.sum()) if energy is not None else 0.0
    active = avg[(p.abs() > 1e-9)] if p is not None else avg
    return (
        {
            "averagePerMWh": cost / mwh if mwh > 1e-9 else 0.0,
            "minPerMWh": float(active.min()) if len(active) else 0.0,
            "maxPerMWh": float(active.max()) if len(active) else 0.0,
            "energyMWh": mwh,
            "operatingCost": cost,
        },
        cost,
    )


def _dispatch(comp: Any, name: str) -> pd.Series | None:
    """The x variable of a marginal-cost curve (positive part for storage dispatch)."""
    if comp.name == "StorageUnit":
        frame = comp.dynamic.get("p_dispatch")
    elif comp.name == "Store":
        frame = comp.dynamic.get("p")
    else:
        frame = comp.dynamic.get("p")
    if frame is None or name not in frame.columns:
        return None
    series = frame[name].astype(float)
    return series.clip(lower=0.0) if comp.name in ("Store", "Generator") else series


# ── Reporting helpers (cost breakdown, merit order, economics) ────────────────


def overlay_piecewise_marginal_cost(network: pypsa.Network, mc_dense: pd.DataFrame) -> pd.DataFrame:
    """Replace the scalar cost of curve-priced generators by their realised average.

    ``get_switchable_as_dense("Generator", "marginal_cost")`` returns the scalar
    cost, which PyPSA ignores for a generator that has a curve (so reporting built
    on it prices that generator at 0). The solved ``marginal_cost_piecewise_opt``
    is the per-snapshot average cost per MWh, so ``opt * p * w`` reproduces the
    LP's operating cost for the generator exactly.

    Returns:
        A copy of ``mc_dense`` with those columns overwritten (unchanged when no
        generator has a curve or the network is unsolved).
    """
    gens = network.components["generators"]
    if not gens.has_piecewise("marginal_cost"):
        return mc_dense
    opt = gens.dynamic.get("marginal_cost_piecewise_opt")
    if opt is None or opt.empty:
        return mc_dense
    out = mc_dense.copy()
    for name in gens.piecewise["marginal_cost"].columns.unique("name"):
        if name in opt.columns and name in out.columns:
            out[name] = opt[name].reindex(out.index).astype(float).fillna(0.0)
    return out


def representative_marginal_costs(network: pypsa.Network) -> dict[str, float]:
    """One number per curve-priced generator for a supply stack: ``name -> currency/MWh``.

    The dispatch-weighted solved average when the network has been solved, else
    the first segment's price (the cost of the first MWh).
    """
    gens = network.components["generators"]
    if not gens.has_piecewise("marginal_cost"):
        return {}
    frame = gens.piecewise["marginal_cost"]
    out: dict[str, float] = {}
    weights = network.snapshot_weightings["objective"]
    for name in frame.columns.unique("name"):
        pts = frame[name].dropna()
        first = float(pts["marginal_cost"].iloc[1]) if len(pts) > 1 else 0.0
        stats, _ = _solved_marginal(network, gens, str(name), weights)
        out[str(name)] = float(stats["averagePerMWh"]) if stats and stats["energyMWh"] > 1e-9 else first
    return out
