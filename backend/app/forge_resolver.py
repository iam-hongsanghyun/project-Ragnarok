"""Forge **Query & Edit** — the pure resolver behind ``/api/forge/query``.

A query selects a component's rows with ANDed filters (each filter tested on the
target component *or* on a one-hop-linked component reached through a reference
column such as ``bus``/``bus0``), then edits one attribute — static or temporal.

The logic here is **pure** (no I/O, no FastAPI, no store) so it is unit-tested
directly against an in-memory ``model: dict[str, list[dict]]`` (the same shape
``model_store.load_full_model`` returns, series sheets included). The router in
``routers/forge_query.py`` is the thin session-loading wrapper that executes the
actions this module returns.

Bounds (v1): one target component, one target attribute, ANDed filters, joins are
one hop only. Static edits: set / add / multiply / derive (``coef·src + const``).
Temporal edits: set / add / multiply by a constant only — derive is static-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


def _temporal_after(before: float | None, edit: Edit) -> float | None:
    """Preview value for one temporal cell (blank stays blank for multiply/add)."""
    if edit.op == "set":
        return float(edit.amount or 0.0)
    if before is None:
        return None
    if edit.op == "add":
        return before + float(edit.amount or 0.0)
    if edit.op == "multiply":
        return before * float(edit.amount or 0.0)
    raise ForgeQueryError("Derive-from-attribute is supported for static attributes only.")


def resolve_temporal(
    model: dict[str, list[dict]], target: str, attribute: str, names: list[str], edit: Edit
) -> dict[str, Any]:
    """A ``transform_seq`` action over the matched component-name columns.

    Temporal ops map onto the vetted vectorised ``transform_series`` primitive:
    multiply→``scale``, add→``offset``, set→``set`` (one atomic transform that
    overwrites every matched cell with the constant, blanks included — so a
    "set = 7" fills the whole series and preview matches apply). Derive is
    rejected. Raises when the series sheet is absent (don't invent a snapshot
    index).
    """
    if edit.op == "derive":
        raise ForgeQueryError("Derive-from-attribute is supported for static attributes only.")
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
    if not present:
        return {"kind": "transform_seq", "sheet": sheet, "steps": [], "present": 0}
    amount = float(edit.amount or 0.0)
    if edit.op == "multiply":
        steps = [("scale", {"columns": present, "factor": amount})]
    elif edit.op == "add":
        steps = [("offset", {"columns": present, "delta": amount})]
    else:  # set: one atomic overwrite of every matched cell with the constant
        steps = [("set", {"columns": present, "value": amount})]
    return {"kind": "transform_seq", "sheet": sheet, "steps": steps, "present": len(present)}


# ── preview (pure; no writes) ────────────────────────────────────────────────────

_SAMPLE = 20


def preview(model: dict[str, list[dict]], query: Query) -> dict[str, Any]:
    """Match count + a before/after sample, without mutating anything."""
    if query.edit is None:
        raise ForgeQueryError("An edit is required.")
    names = match_target_names(model, query.target, query.filters)
    target_total = len(model.get(query.target) or [])
    sample: list[dict[str, Any]] = []
    warnings: list[str] = []

    if query.temporal:
        sheet = series_sheet_name(query.target, query.attribute)
        rows = model.get(sheet) or []
        if not rows:
            warnings.append(f"No series sheet '{sheet}' in the session yet.")
            present = 0
        else:
            cols = list(rows[0].keys())
            index_col = series_index_col(cols)
            value_cols = {c for c in cols if c != index_col}
            present_names = [n for n in names if n in value_cols]
            present = len(present_names)
            first = rows[0]
            for n in present_names[:_SAMPLE]:
                before = _to_float(first.get(n))
                sample.append({"name": n, "before": before, "after": _temporal_after(before, query.edit)})
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
        "warnings": warnings,
    }
