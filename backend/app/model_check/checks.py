"""What the model actually IS — read from the model, not from anyone's intent.

The question this answers is "did I build what I meant to?", and the only honest
way to answer it is from the workbook itself. A summary written from the notes of
whoever made the change re-states the intent, which is precisely the thing under
suspicion; a summary read back from the model can disagree with the intent, which
is the entire point.

Two halves:

* **A back-brief** — counts, the load peak and total energy, each generator's
  capacity and marginal cost, what is extendable, the snapshot span. Enough for a
  modeller to say "no, I asked for 600 MW" in one glance.
* **Trap checks** — the ways a model reads as fine and is not. Every one here has
  actually bitten this project:

  - a temporal sheet whose labels do not match ``snapshots``: the uncovered hours
    solve as ZERO and the run reports Optimal, so the result is confidently wrong
  - ``p_set`` on a generator: dispatch stops being a result and becomes an input
  - ``p_min_pu`` without unit commitment: an unconditional floor, not a
    minimum-when-running
  - extendable capacity with no capital cost: it builds free, up to its bound
  - ``lifetime`` left at inf on an overnight_cost asset: PyPSA's annuity is then only r
  - a bus with nothing attached, or a model with no load at all
  - load shedding present: feasibility bought by not serving load

Findings are *observations*, not errors. Several are legitimate on purpose —
pinning a generator with ``p_set`` is a valid thing to want — so the check reports
and explains rather than blocking. It reads the model only; it changes nothing.
"""
from __future__ import annotations

from backend.pypsa.utils.shedding import is_shedding

import math
from typing import Any

from backend.pypsa.network.validators import _norm_snapshot  # same normalisation the run uses

#: Severity of a finding. `warn` means "this is very likely not what you meant";
#: `note` means "true, deliberate sometimes, worth seeing".
WARN = "warn"
NOTE = "note"


def _rows(model: dict[str, Any], sheet: str) -> list[dict[str, Any]]:
    rows = model.get(sheet)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _finding(level: str, code: str, message: str, fix: str = "", action: dict[str, str] | None = None) -> dict[str, Any]:
    """A finding. ``action`` (optional) is a visible workbook step the user can run from it: ``{id, label, endpoint}``."""
    out: dict[str, Any] = {"level": level, "code": code, "message": message, "fix": fix}
    if action:
        out["action"] = action
    return out


def _snapshot_labels(model: dict[str, Any]) -> list[str]:
    return [
        _norm_snapshot(str(r.get("snapshot", "")))
        for r in _rows(model, "snapshots")
        if str(r.get("snapshot", "")).strip()
    ]


def _temporal_sheets(model: dict[str, Any]) -> list[str]:
    return [k for k in model if isinstance(k, str) and "-" in k and not k.endswith("-pw") and isinstance(model.get(k), list)]


def back_brief(model: dict[str, Any]) -> dict[str, Any]:
    """Counts and headline numbers, read from the workbook."""
    snaps = _snapshot_labels(model)
    generators = _rows(model, "generators")

    loads_ts = _rows(model, "loads-p_set")
    load_names = [str(r.get("name", "")) for r in _rows(model, "loads")]
    peak = 0.0
    energy = 0.0
    for row in loads_ts:
        total = sum(v for v in (_num(row.get(n)) for n in load_names) if v is not None)
        peak = max(peak, total)
        energy += total
    if not loads_ts:
        # Static p_set only: every snapshot carries the same value.
        static = sum(v for v in (_num(r.get("p_set")) for r in _rows(model, "loads")) if v is not None)
        peak = static
        energy = static * len(snaps)

    return {
        "counts": {
            sheet: len(_rows(model, sheet))
            for sheet in ("buses", "generators", "loads", "lines", "links",
                          "storage_units", "stores", "transformers", "carriers")
            if _rows(model, sheet)
        },
        "snapshots": {
            "count": len(snaps),
            "first": snaps[0] if snaps else None,
            "last": snaps[-1] if snaps else None,
        },
        "load": {"peakMW": round(peak, 2), "energyMWh": round(energy, 2)},
        "generators": [
            {
                "name": str(g.get("name", "")),
                "carrier": str(g.get("carrier", "")),
                "p_nom": _num(g.get("p_nom")),
                "marginal_cost": _num(g.get("marginal_cost")),
                "extendable": bool(g.get("p_nom_extendable")),
                "capital_cost": _num(g.get("capital_cost")),
            }
            for g in generators
        ],
        "extendableCount": sum(1 for g in generators if g.get("p_nom_extendable")),
    }


def _check_snapshot_alignment(model: dict[str, Any], out: list[dict[str, Any]]) -> None:
    axis = set(_snapshot_labels(model))
    if not axis:
        return
    for sheet in _temporal_sheets(model):
        rows = _rows(model, sheet)
        labels = {
            _norm_snapshot(str(r.get("snapshot", "")))
            for r in rows if str(r.get("snapshot", "")).strip()
        }
        if not labels:
            continue
        off = labels - axis
        missing = axis - labels
        if off:
            sample = ", ".join(sorted(off)[:3])
            out.append(_finding(
                WARN, "snapshot_off_axis",
                f"{sheet}: {len(off)} row(s) carry a snapshot that is not on the model's "
                f"axis (e.g. {sample}). Those rows are DROPPED at build time.",
                "Match the labels to the snapshots sheet, or add the missing snapshots.",
            ))
        if missing and len(missing) < len(axis):
            out.append(_finding(
                WARN, "snapshot_partial_cover",
                f"{sheet}: covers {len(labels)} of {len(axis)} snapshots. The uncovered "
                f"{len(missing)} solve as ZERO and the run still reports Optimal.",
                "Fill the missing snapshots, or shorten the run window to what is covered.",
            ))


def _check_carrier_output_cap(model: dict[str, Any], out: list[dict[str, Any]]) -> None:
    """RAGNAROK_CarrierOutputCap: a carrier column with no generators, or a snapshot label off the axis, binds nothing."""
    from backend.app.constraints.carrier_output_cap import SHEET

    rows = _rows(model, SHEET)
    if not rows:
        return
    carriers = {str(r.get("carrier", "")) for r in _rows(model, "generators")}
    cols = [k for r in rows for k in r if k != "snapshot"]
    capped = {c for c in cols if any(r.get(c) not in (None, "") for r in rows)}
    for c in sorted(capped - carriers):
        out.append(_finding(
            WARN, "carrier_cap_no_generators",
            f"{SHEET}: carrier '{c}' has caps but no generator carries it - the cap binds nothing.",
            "Fix the column name to a generator carrier, or remove the column.",
        ))
    axis = set(_snapshot_labels(model))
    if axis:
        off = {
            _norm_snapshot(str(r.get("snapshot", ""))) for r in rows if str(r.get("snapshot", "")).strip()
        } - axis
        if off:
            out.append(_finding(
                WARN, "carrier_cap_off_axis",
                f"{SHEET}: {len(off)} row(s) carry a snapshot that is not on the model's axis (e.g. {', '.join(sorted(off)[:3])}); "
                "those caps never bind.",
                "Match the labels to the snapshots sheet.",
            ))


def _check_generators(model: dict[str, Any], out: list[dict[str, Any]]) -> None:
    committable = {
        str(g.get("name", "")) for g in _rows(model, "generators") if g.get("committable")
    }
    pinned = [str(g.get("name", "")) for g in _rows(model, "generators") if _num(g.get("p_set"))]
    if pinned:
        out.append(_finding(
            NOTE, "generator_pinned",
            f"p_set is set on {', '.join(pinned[:4])}: their dispatch is an INPUT, not a "
            "result — the optimiser cannot move them.",
            "Clear p_set unless you meant to fix that injection.",
        ))
    fuel_suppliers = _composite_fuel_suppliers(model)
    for g in _rows(model, "generators"):
        name = str(g.get("name", ""))
        floor = _num(g.get("p_min_pu"))
        if floor and floor > 0 and name not in committable:
            out.append(_finding(
                NOTE, "min_pu_without_commitment",
                f"{name}: p_min_pu={floor:g} without committable=True is an unconditional "
                "floor — it must generate that much in EVERY snapshot, even when off.",
                "Set committable=True for a minimum-when-running, or clear p_min_pu.",
            ))
        if g.get("p_nom_extendable"):
            capex = _num(g.get("capital_cost")) or _num(g.get("overnight_cost"))
            if not capex and name not in fuel_suppliers:
                out.append(_finding(
                    WARN, "free_expansion",
                    f"{name} is extendable with no capital cost: it builds FREE up to its "
                    "bound, so the 'optimal' capacity is meaningless.",
                    "Give it a capital_cost (per horizon) or an overnight_cost, or fix its capacity.",
                ))
            lifetime = _num(g.get("lifetime"))
            if _num(g.get("overnight_cost")) and (lifetime is None or lifetime == float("inf")):
                out.append(_finding(
                    WARN, "infinite_lifetime",
                    f"{name}: overnight_cost with an infinite lifetime: PyPSA's annuity(r, inf) is "
                    "just r, so the cost is the interest on the overnight price and never repaid.",
                    "Set a finite lifetime in years.",
                ))


def _check_structure(model: dict[str, Any], out: list[dict[str, Any]]) -> None:
    buses = {str(b.get("name", "")) for b in _rows(model, "buses")}
    attached: set[str] = set()
    for sheet in ("generators", "loads", "storage_units", "stores"):
        attached |= {str(r.get("bus", "")) for r in _rows(model, sheet)}
    for sheet, ends in (("lines", ("bus0", "bus1")), ("links", ("bus0", "bus1")),
                        ("transformers", ("bus0", "bus1"))):
        for row in _rows(model, sheet):
            attached |= {str(row.get(ends[0], "")), str(row.get(ends[1], ""))}

    orphans = sorted(b for b in buses if b and b not in attached)
    if orphans:
        out.append(_finding(
            NOTE, "isolated_bus",
            f"{len(orphans)} bus(es) have nothing attached: {', '.join(orphans[:4])}.",
            "Attach something, or remove them — they contribute nothing to the solve.",
        ))
    if not _rows(model, "loads"):
        out.append(_finding(
            WARN, "no_load",
            "There is no load in this model, so any dispatch result is zero by construction.",
            "Add a load before solving.",
        ))
    shedding = [
        str(g.get("name", "")) for g in _rows(model, "generators")
        if is_shedding(g.get("name", ""), g.get("carrier"))
        or str(g.get("carrier", "")).lower() in ("load_shedding", "unserved")
    ]
    if shedding:
        out.append(_finding(
            NOTE, "load_shedding_present",
            "Load shedding is available, so the model can always be feasible by NOT "
            "serving load. Check how much it used before reading the result as adequate.",
            "Look at the shedding generator's dispatch in the results.",
        ))


def _check_weighting_vs_spacing(model: dict[str, Any], out: list[dict[str, Any]]) -> None:
    """Timestamp spacing versus the snapshot weighting (default 1 when the sheet has no weighting column)."""
    import pandas as pd

    from backend.pypsa.utils.weightings import spacing_mismatch

    rows = [r for r in _rows(model, "snapshots") if str(r.get("snapshot", "")).strip()]
    if len(rows) < 2:
        return
    try:
        stamps = pd.to_datetime([_norm_snapshot(str(r["snapshot"])) for r in rows])
    except Exception:  # noqa: BLE001 - labels that are not dates have no spacing
        return
    weights: list[float] = []
    for r in rows:
        w = next((_num(r.get(c)) for c in ("generators", "objective", "stores") if _num(r.get(c)) is not None), None)
        weights.append(1.0 if w is None else w)
    found = spacing_mismatch(stamps, weights)
    if found:
        out.append(_finding(
            WARN, "weighting_spacing", found["message"],
            "Set the snapshot weightings to the spacing (a 4-hourly model carries weight 4). Nothing is changed until you run the action.",
            {"id": "set_weightings_from_spacing", "label": "Set weightings from timestamp spacing",
             "endpoint": "POST /api/model/set-weightings-from-spacing"},
        ))


def _check_placeholder_bounds(model: dict[str, Any], out: list[dict[str, Any]]) -> None:
    from backend.pypsa.network.placeholders import PLACEHOLDER_THRESHOLD, find_placeholders

    found = find_placeholders(model)
    if not found:
        return
    sample = ", ".join(f"{sheet}.{name}.{column}" for sheet, name, column, _ in found[:3])
    out.append(_finding(
        WARN, "placeholder_bounds",
        f"{len(found)} bound cell(s) hold a finite value of {PLACEHOLDER_THRESHOLD:.0e} or more (e.g. {sample}). "
        "PyPSA uses them as written, so the LP carries a huge right-hand side (poor conditioning) where "
        "'no limit' was meant.",
        "Run the clean-up: blank cells take PyPSA's default (inf). Nothing is changed until you run the action.",
        {"id": "clean_placeholder_bounds", "label": "Clean placeholder bounds",
         "endpoint": "POST /api/forge/clean-placeholder-bounds"},
    ))


def check_model(model: dict[str, Any]) -> dict[str, Any]:
    """Back-brief plus trap findings for a workbook model. Read-only."""
    findings: list[dict[str, Any]] = []
    _check_snapshot_alignment(model, findings)
    _check_weighting_vs_spacing(model, findings)
    _check_generators(model, findings)
    _check_carrier_output_cap(model, findings)
    _check_placeholder_bounds(model, findings)
    _check_structure(model, findings)
    warnings = [f for f in findings if f["level"] == WARN]
    return {
        "backBrief": back_brief(model),
        "findings": findings,
        "warnCount": len(warnings),
        "noteCount": len(findings) - len(warnings),
        "verdict": (
            "Nothing here contradicts a well-formed model — check the back-brief against "
            "what you asked for."
            if not warnings
            else f"{len(warnings)} thing(s) very likely differ from what you intended."
        ),
    }


def _composite_fuel_suppliers(model: dict[str, Any]) -> set[str]:
    """Generators a composite added as its gas / H2 supplier: extendable at zero capital cost ON PURPOSE (a fuel market priced
    by its marginal cost), so the free-expansion warning does not apply to them."""
    from backend.app.plants.registry import registry_map

    try:
        registry = registry_map(model)
    except Exception:  # noqa: BLE001 - a malformed registry must not break the model check
        return set()
    return {
        str(c.get("name"))
        for reg in registry.values()
        for c in reg.get("components") or []
        if c.get("sheet") == "generators" and c.get("role") in ("gas supply", "H2 supply")
    }
