"""Demand response as visible workbook rows: the explicit apply step and what the build reads back.

The module writes its ``dr_*`` components into the model sheets instead of creating them inside the run:

* ``buses``      ``dr_<load>``        the demand bus (carrier of the parent bus)
* ``links``      ``drlink_<load>``    parent bus -> demand bus, ``p_nom`` = peak + buffer power, efficiency 1
* ``stores``     ``drstore_<load>``   cyclic buffer on the demand bus, ``e_nom`` = buffer power x hours
* ``loads``      the shiftable load's ``bus`` set to ``dr_<load>``
* ``generators`` ``load_shedding_elastic_<load>_<k>`` price-elastic blocks (carrier ``elastic_demand``)
* ``carriers``   ``elastic_demand`` when elastic blocks are written and the sheet lacks it

The rows are computed by the SAME functions the build used to run (:func:`.shift.apply_demand_response`,
:func:`.shift.apply_price_elastic`) on the workbook built 1:1 (:func:`backend.pypsa.network.build_components`),
and read back as rows, so a run built from them is the run the build-time rewiring solved. Peaks are taken over
the workbook's whole time axis (the rows are a workbook property, not a property of one run's window).

Applying again first removes the module's previous rows (loads back on their parent bus), so a new config replaces
the old one; an empty / disabled config only removes them.
"""
from __future__ import annotations

from typing import Any

import pypsa

from .shift import _ELASTIC_PREFIX, apply_demand_response, apply_price_elastic

Model = dict[str, Any]

BUS_PREFIX = "dr_"
LINK_PREFIX = "drlink_"
STORE_PREFIX = "drstore_"
ELASTIC_PREFIX = _ELASTIC_PREFIX
ELASTIC_CARRIER = "elastic_demand"

#: sheets the apply step may write
SHEETS = ("buses", "carriers", "loads", "links", "stores", "generators")


def shift_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """``options.demandResponseConfig`` -> :func:`.shift.apply_demand_response` keyword arguments."""
    return {
        "enabled": bool(config.get("enabled")),
        "loads": config.get("loads") or None,
        "shift_fraction": float(config.get("shiftFraction", 0.2) or 0.0),
        "max_shift_hours": float(config.get("maxShiftHours", 4.0) or 0.0),
    }


def elastic_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """``options.demandResponseConfig`` -> :func:`.shift.apply_price_elastic` keyword arguments."""
    return {
        "enabled": bool(config.get("elasticEnabled")),
        "loads": config.get("loads") or None,
        "fraction": float(config.get("elasticFraction", 0.2) or 0.0),
        "wtp_max": float(config.get("wtpMax", 200.0) or 0.0),
    }


# ── what the workbook / a built network already carries ──────────────────────────

def _names(model: Model, sheet: str) -> list[str]:
    return [str(r.get("name")) for r in model.get(sheet) or [] if isinstance(r, dict) and r.get("name") not in (None, "")]


def workbook_rows(model: Model) -> dict[str, list[str]]:
    """Names of the module's rows in ``model``, by sheet (only sheets that have some).

    A ``dr_`` bus counts only when a ``drlink_`` link feeds it, so a user's own bus that happens to start with
    ``dr_`` is never taken for the module's.
    """
    links = [r for r in model.get("links") or [] if isinstance(r, dict) and str(r.get("name", "")).startswith(LINK_PREFIX)]
    found = {
        "links": [str(r["name"]) for r in links],
        "buses": sorted({str(r.get("bus1")) for r in links if str(r.get("bus1", "")).startswith(BUS_PREFIX)} & set(_names(model, "buses"))),
        "stores": [n for n in _names(model, "stores") if n.startswith(STORE_PREFIX)],
        "generators": [n for n in _names(model, "generators") if n.startswith(ELASTIC_PREFIX)],
    }
    return {sheet: names for sheet, names in found.items() if names}


def network_has_shift(network: pypsa.Network) -> int:
    """Number of shiftable-load links (``drlink_*``) a built network carries."""
    return sum(1 for n in network.links.index if str(n).startswith(LINK_PREFIX))


def network_has_elastic(network: pypsa.Network) -> int:
    """Number of price-elastic blocks (``load_shedding_elastic_*``) a built network carries."""
    return sum(1 for n in network.generators.index if str(n).startswith(ELASTIC_PREFIX))


# ── remove / compute the rows ─────────────────────────────────────────────────────

def remove_rows(model: Model) -> tuple[Model, dict[str, list[str]]]:
    """A copy of ``model`` without the module's rows, every shifted load back on its parent bus.

    Returns:
        ``(model, removed)`` where ``removed`` lists the names taken out, by sheet.
    """
    out: Model = {s: [dict(r) for r in rows] if isinstance(rows, list) else rows for s, rows in model.items()}
    removed = workbook_rows(model)
    parent_of = {
        str(r.get("bus1")): str(r.get("bus0"))
        for r in model.get("links") or [] if isinstance(r, dict) and str(r.get("name", "")).startswith(LINK_PREFIX)
    }
    for row in out.get("loads") or []:
        bus = str(row.get("bus"))
        if bus in parent_of and str(row.get("name")) == bus[len(BUS_PREFIX):]:
            row["bus"] = parent_of[bus]
    for sheet, names in removed.items():
        drop = set(names)
        out[sheet] = [r for r in out.get(sheet) or [] if str(r.get("name")) not in drop]
    return out, removed


def _num(value: Any) -> float:
    return float(value)


def compute_rows(
    model: Model,
    config: dict[str, Any] | None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The workbook with the module's rows for ``config`` (previous rows replaced), and a report.

    Args:
        model: the full workbook (static and series sheets; the load peaks come from ``loads-p_set``).
        config: ``options.demandResponseConfig`` (``enabled`` / ``shiftFraction`` / ``maxShiftHours`` /
            ``elasticEnabled`` / ``elasticFraction`` / ``wtpMax`` / ``loads``).
        options: only ``pathwayConfig`` is read (it shapes the snapshot index of the 1:1 build).

    Returns:
        ``{"model", "rows": {sheet: [row, ...]} (the module's rows written), "removed": {sheet: [name]},
        "sheets": [sheets changed], "notes": [...]}``.
    """
    from backend.pypsa.network import build_components

    cfg = dict(config or {})
    base, removed = remove_rows(model)
    notes: list[str] = []
    rows: dict[str, list[dict[str, Any]]] = {}
    out = base
    shift, elastic = shift_kwargs(cfg), elastic_kwargs(cfg)
    if shift["enabled"] or elastic["enabled"]:
        pathway = (options or {}).get("pathwayConfig")
        net, _ = build_components(base, {"pathwayConfig": pathway} if pathway else {})
        before = {c: set(map(str, net.components[c].static.index)) for c in ("buses", "links", "stores", "generators")}
        load_bus = {str(k): str(v) for k, v in net.loads["bus"].items()}
        apply_demand_response(net, notes, **shift)
        apply_price_elastic(net, notes, **elastic)
        new = {c: [n for n in map(str, net.components[c].static.index) if n not in before[c]] for c in before}
        if new["buses"]:
            rows["buses"] = [{"name": b, "carrier": str(net.buses.at[b, "carrier"])} for b in new["buses"]]
        if new["links"]:
            rows["links"] = [
                {"name": n, "bus0": str(net.links.at[n, "bus0"]), "bus1": str(net.links.at[n, "bus1"]),
                 "p_nom": _num(net.links.at[n, "p_nom"]), "efficiency": _num(net.links.at[n, "efficiency"]),
                 "marginal_cost": _num(net.links.at[n, "marginal_cost"])}
                for n in new["links"]
            ]
        if new["stores"]:
            rows["stores"] = [
                {"name": n, "bus": str(net.stores.at[n, "bus"]), "e_nom": _num(net.stores.at[n, "e_nom"]),
                 "e_cyclic": bool(net.stores.at[n, "e_cyclic"]), "marginal_cost": _num(net.stores.at[n, "marginal_cost"])}
                for n in new["stores"]
            ]
        if new["generators"]:
            rows["generators"] = [
                {"name": n, "bus": str(net.generators.at[n, "bus"]), "carrier": str(net.generators.at[n, "carrier"]),
                 "p_nom": _num(net.generators.at[n, "p_nom"]), "marginal_cost": _num(net.generators.at[n, "marginal_cost"]),
                 "p_max_pu": 1.0}
                for n in new["generators"]
            ]
        moved = {str(k): str(v) for k, v in net.loads["bus"].items() if load_bus.get(str(k)) != str(v)}
        for sheet, sheet_rows in rows.items():
            out[sheet] = [*(out.get(sheet) or []), *sheet_rows]
        if moved:
            for row in out.get("loads") or []:
                if str(row.get("name")) in moved:
                    row["bus"] = moved[str(row.get("name"))]
            rows["loads"] = [dict(r) for r in out.get("loads") or [] if str(r.get("name")) in moved]
        if new["generators"] and ELASTIC_CARRIER not in _names(out, "carriers"):
            carrier_row = {"name": ELASTIC_CARRIER}
            out["carriers"] = [*(out.get("carriers") or []), carrier_row]
            rows["carriers"] = [dict(carrier_row)]
    else:
        notes.append("Demand response is not enabled in this config: only the module's previous rows are removed."
                     if removed else "Demand response is not enabled in this config: nothing to write.")
    sheets = sorted(s for s in SHEETS if (out.get(s) or []) != (model.get(s) or []))
    return {"model": out, "rows": rows, "removed": removed, "sheets": sheets, "notes": notes}
