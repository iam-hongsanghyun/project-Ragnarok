"""Piecewise-linear cost / efficiency curve tools (PyPSA 1.3+, P10/P47).

Registered on the shared ``mcp`` object from :mod:`backend.mcp.server` (one import
line at the end of that file). Thin wrappers over the REST API via
:class:`RagnarokClient`; nothing here imports ``backend.app``.

A curve lives on a ``<list>-<attribute>-pw`` sheet of the working model (for
example ``generators-marginal_cost-pw``): one row per breakpoint,
``{name, breakpoint, <x>, <attribute>}``. ``<x>`` is ``p_pu`` for per-unit curves
(marginal_cost, efficiency, rate), ``p_nom`` / ``e_nom`` / ``s_nom`` for
capital_cost. For a cost curve the y at breakpoint i is the price per unit of x on
the segment ``(x[i-1], x[i]]``: convex (non-decreasing y) means an LP, anything
else becomes a MIP.

Tools:

* ``describe_piecewise``       - read-only: supported curves, sheet format, run-option key.
* ``get_piecewise_curve``      - read-only: curves in the model (+ convex / MIP class).
* ``set_piecewise_curve``      - WRITE: replace one component's curve (validated first).
* ``clear_piecewise_curve``    - WRITE: delete one component's curve.
* ``check_piecewise_options``  - read-only: validate + normalise ``options.piecewiseOptions``
                                 for submit_solve.
"""

from __future__ import annotations

from typing import Any

from .server import _MUT, _RO, _needs_confirm, _preview, get_client, mcp

_COST_NOTE = (
    "Cost curves: y at breakpoint i is the price per unit of x on (x[i-1], x[i]], y[0] is ignored; "
    "non-decreasing y = convex = LP, otherwise binaries (MIP). Per-unit curves (marginal_cost, "
    "efficiency, rate) must start at x=0, end at x=1 and need a fixed, finite nominal size "
    "(p_nom_extendable=false). capital_cost curves take the OVERNIGHT price per MW (MWh, MVA) on x in "
    "absolute units; the build annuitises them like the scalar capital_cost. A scalar marginal_cost / "
    "capital_cost on a component with a curve is ignored."
)


async def _resolve(component: str, attribute: str | None) -> tuple[dict[str, Any] | None, str]:
    """Match ``component`` (``Generator`` or ``generators``) and ``attribute`` in PyPSA's catalogue."""
    catalog = (await get_client().piecewise_catalog())["curves"]
    comp = component.strip().lower()
    base = (attribute or "").rstrip("0123456789")
    base = base if base in ("efficiency", "rate") else (attribute or "")
    for row in catalog:
        if comp in (row["component"].lower(), row["list_name"].lower()) and (
            attribute is None or row["attribute"] == base
        ):
            return row, ""
    known = sorted({f"{r['component']}.{r['attribute']}" for r in catalog})
    return None, f"No piecewise curve {component}.{attribute}. Supported: {', '.join(known)}."


def _to_points(breakpoints: list[Any]) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for bp in breakpoints:
        if isinstance(bp, dict):
            pts.append((float(bp["x"]), float(bp["y"])))
        else:
            pts.append((float(bp[0]), float(bp[1])))
    return pts


@mcp.tool(
    annotations=_RO,
    description=(
        "Reference for piecewise-linear cost / efficiency curves (PyPSA 1.3+): which component attributes "
        "accept a curve (marginal_cost on Generator/Link/Process/StorageUnit/Store; capital_cost also on "
        "Line/Transformer; efficiency on Generator/Link; rate on Process), the x axis of each, the sheet "
        "name (<list>-<attribute>-pw, one row per breakpoint), and the run-option key "
        "options.piecewiseOptions (method auto|lp|incremental|sos2 per curve). " + _COST_NOTE
    ),
)
async def describe_piecewise() -> Any:
    catalog = await get_client().piecewise_catalog()
    catalog["notes"] = [_COST_NOTE]
    return catalog


@mcp.tool(
    annotations=_RO,
    description=(
        "Read piecewise curves from the working model. component: 'Generator' or 'generators' etc.; name and "
        "attribute (marginal_cost | capital_cost | efficiency | rate0..) narrow the result. Returns, per curve, "
        "the breakpoints [{x,y}], the x axis, its shape (convex | linear = LP, nonconvex = MIP) and the sheet. "
        "Solved *_piecewise_opt values are in get_analytics(run).piecewise."
    ),
)
async def get_piecewise_curve(
    component: str, name: str | None = None, attribute: str | None = None
) -> Any:
    client = get_client()
    catalog = (await client.piecewise_catalog())["curves"]
    comp = component.strip().lower()
    out: list[dict[str, Any]] = []
    for row in catalog:
        if comp not in (row["component"].lower(), row["list_name"].lower()):
            continue
        if attribute and attribute.rstrip("0123456789") not in (row["attribute"],) and attribute != row["attribute"]:
            continue
        # a ported curve (efficiency2, rate1 ...) lives on its own sheet: probe the model for them
        sheets = [row["sheet"]]
        if row["ported"]:
            model = await client.load_full_model(static_only=True)
            prefix = f"{row['list_name']}-{row['attribute']}"
            sheets = sorted(s for s in model if s.startswith(prefix) and s.endswith("-pw")) or sheets
        for sheet in sheets:
            rows = await client.get_piecewise_rows(sheet)
            if name:
                rows = [r for r in rows if str(r.get("name")) == name]
            if not rows:
                continue
            attr = sheet[len(row["list_name"]) + 1 : -3]
            checked = await client.piecewise_check(row["list_name"], attr, rows)
            shapes = {c["name"]: c["shape"] for c in checked.get("curves", [])}
            for n in dict.fromkeys(str(r["name"]) for r in rows):
                out.append(
                    {
                        "component": row["component"],
                        "name": n,
                        "attribute": attr,
                        "sheet": sheet,
                        "x": row["x"],
                        "shape": shapes.get(n),
                        "breakpoints": [
                            {"x": r[row["x"]], "y": r[attr]} for r in rows if str(r["name"]) == n
                        ],
                    }
                )
    return {"curves": out, "count": len(out)}


@mcp.tool(
    annotations=_MUT,
    description=(
        "Set (replace) the piecewise curve of ONE component: component 'Generator'|'Link'|'Process'|"
        "'StorageUnit'|'Store' (capital_cost also 'Line'|'Transformer'), name, attribute "
        "('marginal_cost' | 'capital_cost' | 'efficiency' | 'rate0'...) and breakpoints as [{x, y}] or "
        "[[x, y], ...] in PyPSA's convention (per-unit x from 0 to 1 for marginal_cost/efficiency). "
        "The curve is validated (>=2 strictly increasing x, numeric) before it is written and reported as "
        "convex (LP) / linear (LP) / nonconvex (MIP). It replaces the scalar cost of that component. "
        "Gates like other cheap edits - re-call with confirm=true. " + _COST_NOTE
    ),
)
async def set_piecewise_curve(
    component: str,
    name: str,
    attribute: str,
    breakpoints: list[Any],
    confirm: bool = False,
) -> Any:
    spec, err = await _resolve(component, attribute)
    if spec is None:
        return {"error": err}
    try:
        pts = _to_points(breakpoints)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return {"error": f"breakpoints must be [{{x, y}}, ...] or [[x, y], ...]: {exc}"}
    rows = [
        {"name": name, "breakpoint": i, spec["x"]: x, attribute: y}
        for i, (x, y) in enumerate(sorted(pts))
    ]
    client = get_client()
    checked = await client.piecewise_check(spec["list_name"], attribute, rows)
    if not checked.get("ok"):
        return {"error": "; ".join(checked.get("errors") or ["invalid curve"])}
    shape = (checked.get("curves") or [{}])[0].get("shape")
    sheet = f"{spec['list_name']}-{attribute}-pw"
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(
            f"Set the {attribute} curve of {spec['component']} {name!r} ({len(rows)} breakpoints, {shape}).",
            {"sheet": sheet, "rows": rows},
        )
    await client.replace_piecewise_curve(sheet, name, rows)
    return {
        "status": "set",
        "sheet": sheet,
        "name": name,
        "shape": shape,
        "isMip": shape == "nonconvex",
        "breakpoints": len(rows),
        "note": "Extendable components cannot carry per-unit curves; a scalar cost on this component is ignored."
        if not spec["allow_extendable"]
        else "Annuitised at build time like the scalar capital_cost.",
    }


@mcp.tool(
    annotations=_MUT,
    description=(
        "Remove the piecewise curve of one component (the scalar cost / efficiency applies again). "
        "attribute omitted = every curve of that component. Gates like other cheap edits."
    ),
)
async def clear_piecewise_curve(
    component: str, name: str, attribute: str | None = None, confirm: bool = False
) -> Any:
    spec, err = await _resolve(component, attribute)
    if spec is None:
        return {"error": err}
    client = get_client()
    catalog = (await client.piecewise_catalog())["curves"]
    comp = component.strip().lower()
    sheets = (
        [f"{spec['list_name']}-{attribute}-pw"]
        if attribute
        else [r["sheet"] for r in catalog if comp in (r["component"].lower(), r["list_name"].lower())]
    )
    found = [s for s in sheets if any(str(r.get("name")) == name for r in await client.get_piecewise_rows(s))]
    if not found:
        return {"status": "nothing to clear", "name": name, "sheets": sheets}
    if _needs_confirm(cheap=True) and not confirm:
        return _preview(f"Clear the piecewise curve(s) of {spec['component']} {name!r}.", {"sheets": found})
    for sheet in found:
        await client.replace_piecewise_curve(sheet, name, [])
    return {"status": "cleared", "name": name, "sheets": found}


@mcp.tool(
    annotations=_RO,
    description=(
        "Validate and normalise the piecewise run option. Returns {piecewiseOptions: [...]} ready to pass as "
        "submit_solve options.piecewiseOptions. Each entry: {component:'Generator', attribute:'marginal_cost', "
        "method:'auto'|'lp'|'incremental'|'sos2', name?:['g1'], sign?:'>='|'<='|'='}. Default method auto: "
        "tangent-cut LP for convex cost curves, binaries otherwise ('sos2' is reformulated with binaries "
        "because HiGHS has no SOS2). Omit the option entirely for PyPSA's defaults."
    ),
)
async def check_piecewise_options(piecewise_options: list[dict[str, Any]]) -> Any:
    return await get_client().piecewise_options_check(piecewise_options)
