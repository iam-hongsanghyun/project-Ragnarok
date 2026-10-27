"""``/api/piecewise`` - the piecewise-curve catalogue and a no-build curve check (P10).

The catalogue is PyPSA's own ``piecewise.csv`` (which components accept which
curve, on which x axis, and whether the component may be extendable). The check
runs the same row parsing ``build_network`` applies to a ``<list>-<attr>-pw``
sheet and classifies each curve as convex / linear (LP) or non-convex (MIP), so
the MCP tools can report problems before a solve. Importing this module also
registers the ``options.piecewiseOptions`` run option in the run-options reference.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ...pypsa.network.piecewise import (
    curve_shape,
    parse_piecewise_options,
    piecewise_catalog,
    rows_to_frame,
)
from ..run_options_reference import RunOption, register_options

router = APIRouter(prefix="/api/piecewise", tags=["piecewise"])

_NETWORK = "backend/pypsa/network/piecewise.py"
register_options(
    [
        RunOption(
            "options.piecewiseOptions[]",
            "object[]",
            "Formulation override per piecewise curve (PyPSA 1.3+). Without it PyPSA picks tangent cuts "
            "(LP) for convex cost curves and binaries (MIP) otherwise. Curves themselves live on the "
            "<list>-<attr>-pw sheets (generators-marginal_cost-pw ...).",
            [],
            reader=_NETWORK + " (parse_piecewise_options), backend/pypsa/optimise_options.py",
            source="api",
        ),
        RunOption(
            "options.piecewiseOptions[].component", "string",
            "PyPSA component class: Generator, Link, Process, StorageUnit, Store, Line or Transformer.",
            None, reader=_NETWORK, source="api", required=True,
        ),
        RunOption(
            "options.piecewiseOptions[].attribute", "string",
            "Curve attribute: marginal_cost, capital_cost, efficiency (Generator/Link, efficiency2.. for ports) "
            "or rate0/rate1.. (Process).",
            None, reader=_NETWORK, source="api", required=True,
        ),
        RunOption(
            "options.piecewiseOptions[].method", "string",
            "linopy formulation. auto: LP for convex cost curves, else incremental binaries. sos2 is "
            "reformulated with binaries on HiGHS (no native SOS2).",
            "auto", allowed=["auto", "lp", "incremental", "sos2"], reader=_NETWORK, source="api",
        ),
        RunOption(
            "options.piecewiseOptions[].name", "string[]",
            "Limit the override to these component names (default: every component with that curve).",
            None, reader=_NETWORK, source="api",
        ),
        RunOption(
            "options.piecewiseOptions[].sign", "string",
            "Constraint sign y <sign> f(x). Default: '>=' for cost curves, '=' for efficiency/rate curves.",
            None, allowed=["=", "<=", ">="], reader=_NETWORK, source="api",
        ),
    ]
)


class CheckBody(BaseModel):
    listName: str
    attribute: str
    rows: list[dict[str, Any]]


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    """Every curve PyPSA supports, plus the run-option key and its methods."""
    return {
        "curves": list(piecewise_catalog()),
        "optionKey": "options.piecewiseOptions",
        "methods": ["auto", "lp", "incremental", "sos2"],
        "sheetFormat": "<list>-<attribute>-pw: one row per breakpoint {name, [breakpoint], <x>, <attribute>}",
    }


@router.post("/check")
def check_curve(body: CheckBody) -> dict[str, Any]:
    """Parse + classify the rows of one ``<list>-<attr>-pw`` sheet without building a network."""
    base = body.attribute.rstrip("0123456789") if body.attribute.rstrip("0123456789") in ("efficiency", "rate") else body.attribute
    spec = next(
        (r for r in piecewise_catalog() if r["list_name"] == body.listName and r["attribute"] == base),
        None,
    )
    if spec is None:
        return {"ok": False, "errors": [f"{body.listName} has no piecewise curve {body.attribute!r}"], "curves": []}
    names = {str(r.get("name")).strip() for r in body.rows if str(r.get("name") or "").strip()}
    try:
        frame, _ = rows_to_frame(body.rows, spec["x"], body.attribute, names)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)], "curves": [], "x": spec["x"]}
    curves = []
    for name in frame.columns.unique("name") if not frame.empty else []:
        pts = frame[name].dropna()
        shape = curve_shape(
            spec["kind"], pts[spec["x"]], pts[body.attribute],
            invert=(spec["component"] == "Generator" and base == "efficiency"),
        )
        curves.append({"name": str(name), "points": len(pts), "shape": shape, "mip": shape == "nonconvex"})
    return {"ok": True, "errors": [], "x": spec["x"], "allowExtendable": spec["allow_extendable"], "curves": curves}


@router.post("/options/check")
def check_options(body: dict[str, Any]) -> dict[str, Any]:
    """Validate ``{"piecewiseOptions": [...]}`` and return the normalised list."""
    parsed = parse_piecewise_options(body.get("piecewiseOptions"))
    return {"piecewiseOptions": [{**o, "name": list(o["name"])} for o in parsed]}
