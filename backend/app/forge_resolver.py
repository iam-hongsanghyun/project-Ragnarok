"""Forge **Query & Edit** — the pure resolver behind ``/api/forge/query``.

A query selects a component's rows with ANDed filters (each filter tested on the
target component *or* on a one-hop-linked component reached through a reference
column such as ``bus``/``bus0``), then edits one attribute — static or temporal.

The logic here is **pure** (no I/O, no FastAPI, no store) so it is unit-tested
directly against an in-memory ``model: dict[str, list[dict]]`` (the same shape
``model_store.load_full_model`` returns, series sheets included). The router in
``routers/forge_query.py`` is the thin session-loading wrapper that executes the
actions this module returns.

Bounds: one target component, one target attribute, ANDed filters, joins are
one hop only. Static edits: set / add / multiply / derive (``coef·src + const``).
Temporal edits: set (constant) / multiply / add — where **add** carries demand-
adjustment semantics (unit MW-per-snapshot or MWh-over-period; applied to each
matched series or split across them, equally or proportionally to current
energy). Derive is static-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .timeseries import series_index_col

# Bus-reference columns a one-hop join may traverse (mirrors ``_BUS_REFS`` in
# routers/transforms.py). These are the natural ``target → buses`` links.
BUS_REFS = {"bus", "bus0", "bus1", "bus2", "bus3", "bus4"}

# Operators a filter may use. String operators compare on the stringified,
# stripped cell (matching the frontend ``rowMatches`` and ``distinct_values``);
# ordinal operators compare numerically via ``float()``.
STRING_OPS = {"eq", "ne", "contains", "in"}
ORDINAL_OPS = {"gt", "lt", "ge", "le"}
VALID_OPS = STRING_OPS | ORDINAL_OPS

EDIT_OPS = {"set", "add", "multiply", "derive"}

# Temporal `add` semantics (ignored for every other op / static edits).
ADD_UNITS = {"mw", "mwh"}
ADD_SCOPES = {"each", "total"}
ADD_SPLITS = {"proportional", "equal"}


class ForgeQueryError(ValueError):
    """A query the user can fix (missing join component/column, temporal derive,
    absent series sheet). The router surfaces this as an HTTP 400.
    """


@dataclass
class JoinPath:
    """One-hop link: the filter is evaluated on ``component`` (e.g. ``buses``),
    whose matching names are tested against the target's ``ref_column`` (e.g.
    ``bus``). So ``generators`` with ``ref_column="bus"`` keeps generators whose
    bus matches the filtered buses.
    """

    component: str
    ref_column: str


@dataclass
class Filter:
    column: str
    op: str
    value: Any = None
    values: list[Any] | None = None
    join: JoinPath | None = None


@dataclass
class Edit:
    op: str
    amount: float | None = None
    # derive (static only): new = coefficient * <source_attr> + constant.
    source_attr: str | None = None
    coefficient: float = 1.0
    constant: float = 0.0
    # temporal `add` semantics (see module docstring):
    #   unit   'mw'  — amount is MW at every snapshot
    #          'mwh' — amount is energy over the whole series window
    #   scope  'each'  — every matched series gets the full amount
    #          'total' — the amount is the change of the GROUP total, divided
    #   split  how a 'total' amount divides across the matched series:
    #          'proportional' (by current period energy) or 'equal'
    unit: str = "mw"
    scope: str = "each"
    split: str = "proportional"


@dataclass
class Query:
    target: str
    attribute: str
    temporal: bool = False
    filters: list[Filter] = field(default_factory=list)
    edit: Edit | None = None


# ── small coercion helpers ──────────────────────────────────────────────────────

def _s(value: Any) -> str:
    """Stringify + strip, treating ``None`` as empty (matches the frontend)."""
    return "" if value is None else str(value).strip()


def _to_float(value: Any) -> float | None:
    """Parse ``value`` to float, or ``None`` when it isn't a finite number."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _valid_name(name: Any) -> bool:
    return name is not None and _s(name) != ""


def coerce_compare(cell: Any, op: str, value: Any = None, values: list[Any] | None = None) -> bool:
    """Evaluate one predicate against a cell.

    String ops (``eq``/``ne``/``contains``/``in``) compare stringified+stripped;
    a missing cell is the empty string. Ordinal ops (``gt``/``lt``/``ge``/``le``)
    compare numerically and never match (never raise) on non-numeric cells.
    """
    if op == "in":
        wanted = {_s(v) for v in (values or [])}
        return _s(cell) in wanted
    if op in ("eq", "ne", "contains"):
        c, v = _s(cell), _s(value)
        if op == "eq":
            return c == v
        if op == "ne":
            return c != v
        return v in c  # contains
    cf, vf = _to_float(cell), _to_float(value)
    if cf is None or vf is None:
        return False
    if op == "gt":
        return cf > vf
    if op == "lt":
        return cf < vf
    if op == "ge":
        return cf >= vf
    if op == "le":
        return cf <= vf
    raise ForgeQueryError(f"Unknown filter operator {op!r}.")


# ── filtering + joins ───────────────────────────────────────────────────────────

def _linked_hits(model: dict[str, list[dict]], f: Filter) -> set[str]:
    """Names on the linked component that satisfy the filter predicate.

    Raises when the linked component is absent, or its filter column exists on no
    row (mirrors ``_busmap_by_column``'s "No bus has a 'X' column" guard).
    """
    assert f.join is not None
    linked = model.get(f.join.component)
    if linked is None:
        raise ForgeQueryError(f"No component sheet '{f.join.component}' to join on.")
    if not any(f.column in r for r in linked if isinstance(r, dict)):
        raise ForgeQueryError(
            f"No '{f.column}' column on '{f.join.component}' to filter by."
        )
    return {
        _s(r.get("name"))
        for r in linked
        if isinstance(r, dict)
        and _valid_name(r.get("name"))
        and coerce_compare(r.get(f.column), f.op, f.value, f.values)
    }


def match_target_names(
    model: dict[str, list[dict]], target: str, filters: list[Filter]
) -> list[str]:
    """Names of the target rows passing every filter (ANDed), in sheet order.

    A filter with no ``join`` tests a target column directly. A filter with a
    ``join`` resolves the predicate on the linked component, then keeps target
    rows whose ``join.ref_column`` value is one of the linked matches.
    """
    rows = [
        r for r in (model.get(target) or [])
        if isinstance(r, dict) and _valid_name(r.get("name"))
    ]
    for f in filters:
        if f.op not in VALID_OPS:
            raise ForgeQueryError(f"Unknown filter operator {f.op!r}.")
        if f.join is None:
            rows = [r for r in rows if coerce_compare(r.get(f.column), f.op, f.value, f.values)]
        else:
            hits = _linked_hits(model, f)
            ref = f.join.ref_column
            rows = [r for r in rows if _s(r.get(ref)) in hits]
    return [_s(r.get("name")) for r in rows]


def name_to_index(model: dict[str, list[dict]], target: str) -> dict[str, int]:
    """Map each valid component name to its integer row position (first wins).

    ``patch_sheet`` addresses cells by index, and ``load_full_model`` returns rows
    in stable ``ORDER BY __row`` order, so these indices line up with the store.
    """
    out: dict[str, int] = {}
    for i, r in enumerate(model.get(target) or []):
        if isinstance(r, dict) and _valid_name(r.get("name")):
            out.setdefault(_s(r.get("name")), i)
    return out


# ── edit maths ──────────────────────────────────────────────────────────────────

def apply_edit(current: float | None, row: dict[str, Any], edit: Edit) -> float:
    """New scalar value for a static cell. ``multiply``/``add`` callers must skip
    rows whose ``current`` is ``None`` (see :func:`resolve_static_ops`)."""
    if edit.op == "set":
        return float(edit.amount or 0.0)
    if edit.op == "add":
        return (current or 0.0) + float(edit.amount or 0.0)
    if edit.op == "multiply":
        return (current or 0.0) * float(edit.amount or 0.0)
    if edit.op == "derive":
        if not edit.source_attr:
            raise ForgeQueryError("Derive needs a source attribute.")
        src = _to_float(row.get(edit.source_attr)) or 0.0
        return edit.coefficient * src + edit.constant
    raise ForgeQueryError(f"Unknown edit op {edit.op!r}.")


def resolve_static_ops(
    model: dict[str, list[dict]], target: str, attribute: str, names: list[str], edit: Edit
) -> list[dict[str, Any]]:
    """``patch_sheet`` set-ops for a static attribute over the matched names.

    ``multiply``/``add`` skip a row whose attribute isn't a finite number (a blank
    stays blank rather than becoming a spurious 0); ``set``/``derive`` always write.
    """
    idx = name_to_index(model, target)
    rows = model.get(target) or []
    ops: list[dict[str, Any]] = []
    for name in names:
        i = idx.get(name)
        if i is None:
            continue
        row = rows[i]
        current = _to_float(row.get(attribute))
        if edit.op in ("multiply", "add") and current is None:
            continue
        ops.append({"op": "set", "row": i, "column": attribute, "value": apply_edit(current, row, edit)})
    return ops


def series_sheet_name(target: str, attribute: str) -> str:
    return f"{target}-{attribute}"


# ── temporal planning ───────────────────────────────────────────────────────────
#
# A temporal edit is planned as one primitive per matched series column —
# scale (×factor), offset (+delta MW) or set (constant MW) — from the edit's
# op / unit / scope / split. Planning computes each column's period energy, so
# preview can show MWh before → after and apply emits exact per-column steps.

_TS_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


def _parse_ts(value: Any) -> datetime | None:
    s = _s(value)
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _step_hours(rows: list[dict], index_col: str) -> float:
    """Snapshot step Δt [h] from the first two parseable index values (1.0 when
    the index isn't timestamps — e.g. integer periods — matching the app's
    hourly-snapshot convention)."""
    stamps = [t for r in rows[:3] if (t := _parse_ts(r.get(index_col))) is not None]
    if len(stamps) >= 2 and stamps[1] > stamps[0]:
        return (stamps[1] - stamps[0]).total_seconds() / 3600.0
    return 1.0


@dataclass
class ColumnPlan:
    """The primitive one series column receives, with its period energy.

    Attributes:
        column:   Series column (component name).
        kind:     'scale' | 'offset' | 'set' | 'none' (no-op).
        value:    factor [-] (scale), delta [MW] (offset), constant [MW] (set).
        e_before: Period energy before the edit [MWh].
        e_after:  Period energy after the edit [MWh].
    """

    column: str
    kind: str
    value: float
    e_before: float
    e_after: float


@dataclass
class TemporalPlan:
    sheet: str
    present: list[str]
    dt_hours: float
    n_rows: int
    columns: list[ColumnPlan]

    @property
    def energy_before(self) -> float:
        return sum(c.e_before for c in self.columns)

    @property
    def energy_after(self) -> float:
        return sum(c.e_after for c in self.columns)


def _column_stats(
    rows: list[dict], columns: list[str]
) -> dict[str, tuple[float, float, int]]:
    """Per column: (sum, min, count) over its finite-numeric cells."""
    stats = {c: [0.0, float("inf"), 0] for c in columns}
    for r in rows:
        if not isinstance(r, dict):
            continue
        for c in columns:
            v = _to_float(r.get(c))
            if v is None:
                continue
            s = stats[c]
            s[0] += v
            if v < s[1]:
                s[1] = v
            s[2] += 1
    return {c: (s[0], (s[1] if s[2] else 0.0), s[2]) for c, s in stats.items()}


_EPS = 1e-9


def _delta_energy(
    e_by_col: dict[str, float], amount: float, scope: str, split: str
) -> dict[str, float]:
    """Target energy change ΔE_i [MWh] per column for a temporal ``add``.

    Algorithm:
        each               ΔE_i = A
        total + equal      ΔE_i = A / n
        total + proportional  ΔE_i = A · E_i / E   (E = Σ E_i > 0)

        $$ \\Delta E_i = A,\\quad \\frac{A}{n},\\quad A\\frac{E_i}{E} $$

    Symbols: A entered amount [MWh]; n matched-series count [-]; E_i column i's
    period energy [MWh].
    """
    n = len(e_by_col)
    if scope == "each":
        return {c: amount for c in e_by_col}
    if split == "equal":
        return {c: amount / n for c in e_by_col}
    total = sum(e_by_col.values())
    if total <= _EPS:
        raise ForgeQueryError(
            "The matched series carry no energy to split proportionally — "
            "use an equal split or 'each'."
        )
    return {c: amount * e / total for c, e in e_by_col.items()}


def plan_temporal(
    model: dict[str, list[dict]], target: str, attribute: str, names: list[str], edit: Edit
) -> TemporalPlan:
    """Plan a temporal edit as per-column primitives with energy accounting.

    Algorithm (add; A = amount, Δt snapshot step [h], k_i numeric-cell count,
    E_i = Σ_t p_i(t)·Δt the column's period energy [MWh]):

        unit = mw   each column gets a flat adder δ_i [MW]:
                    each → δ_i = A; total/equal → δ_i = A/n;
                    total/proportional → δ_i = A·E_i/E

                    $$ p_i(t) \\leftarrow p_i(t) + \\delta_i $$

        unit = mwh  each column's energy target rises by ΔE_i (see
                    :func:`_delta_energy`), realised shape-preservingly as a
                    scale when E_i > 0, else as a flat adder:

                    $$ f_i = \\frac{E_i + \\Delta E_i}{E_i} \\quad (E_i > 0);
                       \\qquad \\delta_i = \\frac{\\Delta E_i}{k_i\\,\\Delta t}
                       \\quad (E_i = 0) $$

                    f_i = (E_i + dE_i)/E_i  or  delta_i = dE_i/(k_i*dt)

    Negative amounts must not push any cell below zero (offset: min+δ ≥ 0) nor
    remove more energy than a column has (scale: f_i ≥ 0) — mirroring the
    dashboard demand-adjustment guards. Raises :class:`ForgeQueryError` on
    violation, unknown unit/scope/split, a missing series sheet, or derive.
    """
    if edit.op == "derive":
        raise ForgeQueryError("Derive-from-attribute is supported for static attributes only.")
    if edit.op not in EDIT_OPS:
        raise ForgeQueryError(f"Unknown edit op {edit.op!r}.")
    sheet = series_sheet_name(target, attribute)
    rows = model.get(sheet)
    if not rows:
        raise ForgeQueryError(
            f"No series sheet '{sheet}' in the session — attach or import the time-series first."
        )
    cols = list(rows[0].keys())
    index_col = series_index_col(cols)
    value_cols = {c for c in cols if c != index_col}
    present = [n for n in names if n in value_cols]
    dt = _step_hours(rows, index_col)
    n_rows = len(rows)
    if not present:
        return TemporalPlan(sheet=sheet, present=[], dt_hours=dt, n_rows=n_rows, columns=[])

    stats = _column_stats(rows, present)
    e_by_col = {c: stats[c][0] * dt for c in present}
    amount = float(edit.amount or 0.0)
    plans: list[ColumnPlan] = []

    if edit.op == "multiply":
        for c in present:
            e = e_by_col[c]
            plans.append(ColumnPlan(c, "scale", amount, e, e * amount))
    elif edit.op == "set":
        # `set` overwrites EVERY cell (blanks included) with a constant MW.
        for c in present:
            plans.append(ColumnPlan(c, "set", amount, e_by_col[c], amount * n_rows * dt))
    else:  # add
        if edit.unit not in ADD_UNITS:
            raise ForgeQueryError(f"Unknown add unit {edit.unit!r} (expected mw|mwh).")
        if edit.scope not in ADD_SCOPES:
            raise ForgeQueryError(f"Unknown add scope {edit.scope!r} (expected each|total).")
        if edit.split not in ADD_SPLITS:
            raise ForgeQueryError(
                f"Unknown add split {edit.split!r} (expected proportional|equal)."
            )
        if edit.unit == "mw":
            if edit.scope == "each":
                deltas = {c: amount for c in present}
            elif edit.split == "equal":
                deltas = {c: amount / len(present) for c in present}
            else:
                total = sum(e_by_col.values())
                if total <= _EPS:
                    raise ForgeQueryError(
                        "The matched series carry no energy to split proportionally — "
                        "use an equal split or 'each'."
                    )
                deltas = {c: amount * e_by_col[c] / total for c in present}
            for c in present:
                delta = deltas[c]
                _sum, mn, k = stats[c]
                if delta < 0 and mn + delta < -_EPS:
                    raise ForgeQueryError(
                        f"Adding {delta:.3f} MW would push '{c}' below zero "
                        f"(min {mn + delta:.3f} MW)."
                    )
                plans.append(ColumnPlan(c, "offset", delta, e_by_col[c], e_by_col[c] + delta * k * dt))
        else:  # mwh over the period
            d_energy = _delta_energy(e_by_col, amount, edit.scope, edit.split)
            for c in present:
                e, de = e_by_col[c], d_energy[c]
                _sum, _mn, k = stats[c]
                if abs(de) <= _EPS:
                    plans.append(ColumnPlan(c, "none", 0.0, e, e))
                    continue
                if e > _EPS:
                    factor = (e + de) / e
                    if factor < -_EPS:
                        raise ForgeQueryError(
                            f"Removing {-de:.1f} MWh exceeds the {e:.1f} MWh "
                            f"available on '{c}'."
                        )
                    plans.append(ColumnPlan(c, "scale", factor, e, e + de))
                else:
                    # Zero-energy series can't be scaled into shape — fall back
                    # to a flat adder achieving the same ΔE over its k cells.
                    if k == 0:
                        raise ForgeQueryError(
                            f"'{c}' has no numeric cells in '{sheet}' to receive energy."
                        )
                    if de < 0:
                        raise ForgeQueryError(
                            f"Removing {-de:.1f} MWh exceeds the 0.0 MWh available on '{c}'."
                        )
                    plans.append(ColumnPlan(c, "offset", de / (k * dt), e, e + de))

    return TemporalPlan(sheet=sheet, present=present, dt_hours=dt, n_rows=n_rows, columns=plans)


def resolve_temporal(
    model: dict[str, list[dict]], target: str, attribute: str, names: list[str], edit: Edit
) -> dict[str, Any]:
    """A ``transform_seq`` action over the matched component-name columns.

    The plan's per-column primitives map onto the vetted vectorised
    ``transform_series`` steps — scale / offset / set — grouped so columns
    sharing the same value ride one step (a uniform edit stays a single step;
    a proportional split emits one step per distinct value). Raises when the
    series sheet is absent (don't invent a snapshot index).
    """
    plan = plan_temporal(model, target, attribute, names, edit)
    grouped: dict[tuple[str, float], list[str]] = {}
    for cp in plan.columns:
        if cp.kind == "none":
            continue
        grouped.setdefault((cp.kind, cp.value), []).append(cp.column)
    param_key = {"scale": "factor", "offset": "delta", "set": "value"}
    steps = [
        (kind, {"columns": cols, param_key[kind]: value})
        for (kind, value), cols in grouped.items()
    ]
    return {
        "kind": "transform_seq",
        "sheet": plan.sheet,
        "steps": steps,
        "present": len(plan.present),
    }


# ── preview (pure; no writes) ────────────────────────────────────────────────────

_SAMPLE = 20


def preview(model: dict[str, list[dict]], query: Query) -> dict[str, Any]:
    """Match count + a before/after sample, without mutating anything.

    Temporal previews report PERIOD ENERGY [MWh] per matched series (before →
    after) plus the group total, so the add/split semantics are visible before
    apply. A plan that would fail (below-zero push, missing sheet, …) previews
    as a warning instead of an error.
    """
    if query.edit is None:
        raise ForgeQueryError("An edit is required.")
    names = match_target_names(model, query.target, query.filters)
    target_total = len(model.get(query.target) or [])
    sample: list[dict[str, Any]] = []
    warnings: list[str] = []

    if query.temporal:
        sheet = series_sheet_name(query.target, query.attribute)
        plan: TemporalPlan | None = None
        try:
            plan = plan_temporal(model, query.target, query.attribute, names, query.edit)
        except ForgeQueryError as exc:
            warnings.append(str(exc))
        present = len(plan.present) if plan else 0
        if plan:
            for cp in plan.columns[:_SAMPLE]:
                sample.append({"name": cp.column, "before": cp.e_before, "after": cp.e_after})
            if present < len(names):
                warnings.append(
                    f"{len(names)} matched, but {present} have a column in '{sheet}'."
                )
        return {
            "matched": len(names),
            "targetTotal": target_total,
            "temporal": True,
            "seriesSheet": sheet,
            "seriesColumnsPresent": present,
            "sample": sample,
            "sampleKind": "energyMwh",
            "energyBeforeMwh": plan.energy_before if plan else None,
            "energyAfterMwh": plan.energy_after if plan else None,
            "warnings": warnings,
        }

    idx = name_to_index(model, query.target)
    rows = model.get(query.target) or []
    for n in names[:_SAMPLE]:
        i = idx.get(n)
        row = rows[i] if i is not None else {}
        before = _to_float(row.get(query.attribute))
        if query.edit.op in ("multiply", "add") and before is None:
            after: float | None = None
        else:
            after = apply_edit(before, row, query.edit)
        sample.append({"name": n, "before": row.get(query.attribute), "after": after})
    return {
        "matched": len(names),
        "targetTotal": target_total,
        "temporal": False,
        "seriesSheet": None,
        "seriesColumnsPresent": None,
        "sample": sample,
        "sampleKind": "value",
        "energyBeforeMwh": None,
        "energyAfterMwh": None,
        "warnings": warnings,
    }
