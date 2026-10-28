"""Time-units module: ramps and unit-commitment times stated in hours / per hour, written for PyPSA per snapshot.

PyPSA 1.4 counts snapshots, not hours, in these attributes (their docs say "Does not consider snapshot
weightings"):

* ``ramp_limit_up`` / ``ramp_limit_down`` / ``ramp_limit_start_up`` / ``ramp_limit_shut_down``
  - a fraction of ``p_nom`` PER SNAPSHOT;
* ``min_up_time`` / ``min_down_time`` / ``up_time_before`` / ``down_time_before`` - a NUMBER OF SNAPSHOTS.

A workbook value is therefore only right for the snapshot length it was typed for. This module keeps the
user's value in time units in the model sheet ``RAGNAROK_TimeUnits`` (visible and round-tripping like
``RAGNAROK_AnnualBudgets``) and, at solve time, writes the PyPSA per-snapshot value from the weights the
solve ACTUALLY uses (not from the timestamp spacing of the workbook). The constraints themselves are PyPSA's:
window coupling under rolling horizon, the committable formulation and the start / shut-down limits are native.

Sheet ``RAGNAROK_TimeUnits``: one row per value, columns ``component`` (``generators`` / ``links`` /
``processes``), ``name``, ``attribute``, ``value``, ``unit``.

==========================================  ================================  ==========================
attribute                                   value                             unit
==========================================  ================================  ==========================
``ramp_limit_up`` / ``_down``               fraction of p_nom per time unit   ``per_hour`` / ``per_minute``
``ramp_limit_start_up`` / ``_shut_down``    fraction of p_nom per time unit   ``per_hour`` / ``per_minute``
``min_up_time`` / ``min_down_time``         duration                          ``hours`` / ``minutes``
``up_time_before`` / ``down_time_before``   duration                          ``hours`` / ``minutes``
==========================================  ================================  ==========================

Algorithm:
    Let :math:`w` be the time step of the solve in hours (the smallest ``stores`` snapshot weighting: the hours
    that elapse between two snapshots, which test-run sampling leaves physical while it scales ``objective`` /
    ``generators`` to the represented window), :math:`r` a rate in fraction of p_nom per hour (a per-minute rate
    times 60) and :math:`T` a duration in hours.

    $$ \\text{ramp\\_limit} = \\min(1,\\; r\\,w) \\quad (\\text{blank when } r\\,w \\ge 1) $$
    $$ \\text{time} = \\lceil T / w \\rceil $$
    $$ \\text{ramp\\_limit\\_start\\_up} = \\min\\bigl(1,\\; \\max(r\\,w,\\; p^{min}_{pu})\\bigr) $$

    ASCII: ramp = min(1, rate_per_h * w), blank if >= 1; snapshots = ceil(hours / w);
    start/shut = min(1, max(rate_per_h * w, p_min_pu)).

    Start-up / shut-down convention: PyPSA bounds the output of the snapshot in which a unit starts to
    ``ramp_limit_start_up * p_nom`` (and of the last running snapshot before it shuts to ``ramp_limit_shut_down
    * p_nom``). It is the fraction of p_nom reachable from standstill within ONE snapshot, i.e. the same linear
    ramp as ``ramp_limit_up`` over one step. It is never set below ``p_min_pu``: a unit cannot start at an output
    smaller than its minimum load, so a lower value would forbid the start altogether (the note says so).

    Non-uniform weights: a PyPSA attribute is one number per component, so the smallest step is used. That keeps
    every ramp bound at or below the physical rate and every minimum time at or above the stated duration (the
    note says so).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pypsa

SHEET = "RAGNAROK_TimeUnits"
META_KEY = "ragnarok_time_units"

#: sheet name -> PyPSA component class
COMPONENTS: dict[str, str] = {"generators": "Generator", "links": "Link", "processes": "Process"}
RAMP_ATTRS = ("ramp_limit_up", "ramp_limit_down", "ramp_limit_start_up", "ramp_limit_shut_down")
START_STOP_ATTRS = ("ramp_limit_start_up", "ramp_limit_shut_down")
TIME_ATTRS = ("min_up_time", "min_down_time", "up_time_before", "down_time_before")
#: unit -> multiplier to the base unit (per hour / hours)
RATE_UNITS: dict[str, float] = {"per_hour": 1.0, "per_minute": 60.0}
TIME_UNITS: dict[str, float] = {"hours": 1.0, "minutes": 1.0 / 60.0}
#: PyPSA's defaults of the time attributes (what a migrated row's column is reset to).
_PYPSA_TIME_DEFAULT = {"min_up_time": 0, "min_down_time": 0, "up_time_before": 1, "down_time_before": 0}
DEFAULT_UNIT = {**{a: "per_hour" for a in RAMP_ATTRS}, **{a: "hours" for a in TIME_ATTRS}}

_EPS = 1e-9
_VARIABLE_RENEWABLE_MARKERS = ("solar", "pv", "wind")


@dataclass(frozen=True)
class TimeRow:
    component: str
    name: str
    attribute: str
    value: float
    unit: str

    def per_base(self) -> float:
        """The value in per hour (ramps) or hours (times)."""
        table = RATE_UNITS if self.attribute in RAMP_ATTRS else TIME_UNITS
        return self.value * table[self.unit]


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(out) else out


def read_rows(model: dict[str, Any]) -> list[TimeRow]:
    """The module's rows. Raises ``ValueError`` naming every row that cannot be read."""
    out: list[TimeRow] = []
    problems: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for i, row in enumerate(model.get(SHEET) or []):
        if not isinstance(row, dict):
            continue
        comp = str(row.get("component", "")).strip()
        name = str(row.get("name", "")).strip()
        attr = str(row.get("attribute", "")).strip()
        value = _num(row.get("value"))
        if not (comp or name or attr) and value is None:
            continue
        unit = str(row.get("unit") or "").strip() or DEFAULT_UNIT.get(attr, "")
        where = f"row {i + 1}"
        if comp not in COMPONENTS:
            problems.append(f"{where}: component {comp!r} must be one of {', '.join(COMPONENTS)}")
        elif attr not in RAMP_ATTRS + TIME_ATTRS:
            problems.append(f"{where}: attribute {attr!r} must be one of {', '.join(RAMP_ATTRS + TIME_ATTRS)}")
        elif unit not in (RATE_UNITS if attr in RAMP_ATTRS else TIME_UNITS):
            allowed = RATE_UNITS if attr in RAMP_ATTRS else TIME_UNITS
            problems.append(f"{where}: unit {unit!r} for {attr} must be one of {', '.join(allowed)}")
        elif not name:
            problems.append(f"{where}: no name")
        elif value is None or value < 0:
            problems.append(f"{where}: value must be a number >= 0")
        elif (comp, name, attr) in seen:
            problems.append(f"{where}: {comp}.{name}.{attr} appears twice")
        else:
            seen.add((comp, name, attr))
            out.append(TimeRow(comp, name, attr, float(value), unit))
    if problems:
        raise ValueError(f"{SHEET}: " + "; ".join(problems))
    return out


def is_variable_renewable(carrier: Any) -> bool:
    key = str(carrier).strip().lower()
    return any(marker in key for marker in _VARIABLE_RENEWABLE_MARKERS)


def ramp_config_rows(model: dict[str, Any], cfg: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Rows the ``rampConfig`` run option stands for: a default rate (fraction of p_nom per HOUR) per generator.

    ``rampConfig = {enabled, rampLimitUp, rampLimitDown, appliesTo}`` is a convenience that fills the module's
    rows for every supply generator (``appliesTo = "thermal"``: variable renewables excluded) that has no value of its
    own for that attribute: neither a row nor a number typed in the component column (a generator's own value wins). Load-shedding backstops are never given a ramp. Returns the rows to ADD (empty when the
    option is off); the caller writes them into the workbook or declares them in the run notes.
    """
    if not cfg or not bool(cfg.get("enabled")):
        return []
    existing = {(r.component, r.name, r.attribute) for r in read_rows(model)}
    applies = str(cfg.get("appliesTo", "all") or "all")
    up = _num(cfg.get("rampLimitUp"))
    down = _num(cfg.get("rampLimitDown"))
    out: list[dict[str, Any]] = []
    from ..utils.shedding import is_shedding

    for g in model.get("generators") or []:
        if not isinstance(g, dict) or not str(g.get("name", "")).strip():
            continue
        name = str(g["name"]).strip()
        carrier = g.get("carrier")
        if is_shedding(name, carrier) or (applies == "thermal" and is_variable_renewable(carrier)):
            continue
        for attr, rate in (("ramp_limit_up", up), ("ramp_limit_down", down)):
            if rate is not None and ("generators", name, attr) not in existing and _num(g.get(attr)) is None:
                out.append({"component": "generators", "name": name, "attribute": attr, "value": rate, "unit": "per_hour"})
    return out


def with_rows(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A shallow copy of ``model`` with ``rows`` appended to the module's sheet (existing rows win on a key clash)."""
    if not rows:
        return model
    out = dict(model)
    have = {(str(r.get("component", "")), str(r.get("name", "")), str(r.get("attribute", "")))
            for r in model.get(SHEET) or [] if isinstance(r, dict)}
    fresh = [dict(r) for r in rows if (r["component"], r["name"], r["attribute"]) not in have]
    out[SHEET] = [dict(r) for r in model.get(SHEET) or [] if isinstance(r, dict)] + fresh
    return out


def step_hours(network: pypsa.Network) -> tuple[float, bool]:
    """``(w, uniform)``: the solve's time step in hours (smallest ``stores`` weighting) and whether all steps agree."""
    w = network.snapshot_weightings["stores"].reindex(network.snapshots).astype(float).to_numpy()
    w = w[np.isfinite(w) & (w > 0)]
    if w.size == 0:
        return 1.0, True
    return float(w.min()), bool(np.allclose(w, w.min(), rtol=1e-9))


def convert(row: TimeRow, w: float, p_min_pu: float = 0.0) -> tuple[float, str]:
    """``(PyPSA value, note)`` for one row at time step ``w`` hours. A ramp value of NaN means "blank" (unbounded)."""
    base = row.per_base()
    if row.attribute in TIME_ATTRS:
        raw = base / w
        count = int(math.ceil(raw - _EPS))
        note = ""
        if abs(raw - round(raw)) > 1e-6:
            note = (f"{row.attribute} {row.name}: {base:g} h is {raw:.3g} snapshots of {w:g} h, rounded UP to {count} "
                    f"({count * w:g} h modelled)")
        return float(count), note
    reach = base * w
    note = ""
    if row.attribute in START_STOP_ATTRS and reach < p_min_pu - _EPS:
        note = (f"{row.attribute} {row.name}: {reach:.3g} of p_nom per {w:g} h snapshot is below p_min_pu {p_min_pu:g}, "
                f"so it is raised to {p_min_pu:g} (a unit cannot start below its minimum load)")
        reach = p_min_pu
    if reach >= 1.0 - _EPS:
        return float("nan"), note
    return float(reach), note


def apply_to_network(network: pypsa.Network, model: dict[str, Any], notes: list[str], *, enabled: bool = True) -> list[dict[str, Any]]:
    """Write the PyPSA per-snapshot values of every row into ``network`` and say so in ``notes``.

    A no-op without rows. Returns the table (also kept in ``network.meta["ragnarok_time_units"]``): per row the value in
    time units, the step used and the value written. A row for a component the network does not have is an error.
    """
    rows = read_rows(model) if enabled else []
    if not rows:
        return []
    w, uniform = step_hours(network)
    table: list[dict[str, Any]] = []
    rounding: list[str] = []
    missing: list[str] = []
    overridden = 0
    for r in rows:
        frame = network.components[r.component].static
        if r.name not in frame.index or r.attribute not in frame.columns:
            missing.append(f"{r.component}.{r.name}")
            continue
        p_min = _num(frame.at[r.name, "p_min_pu"]) if "p_min_pu" in frame.columns else 0.0
        value, note = convert(r, w, p_min or 0.0)
        before = frame.at[r.name, r.attribute]
        defaults = network.components[r.component].defaults
        default = defaults.at[r.attribute, "default"] if r.attribute in defaults.index else None
        typed = pd.notna(before) and (default is None or pd.isna(default) or float(before) != float(default))
        if typed and (pd.isna(value) or float(before) != value):
            overridden += 1
        if r.attribute in TIME_ATTRS:
            frame[r.attribute] = frame[r.attribute].astype(float)
            frame.loc[r.name, r.attribute] = value
            frame[r.attribute] = frame[r.attribute].round().astype(int)
        else:
            frame.loc[r.name, r.attribute] = value
        if note:
            rounding.append(note)
        table.append({
            "component": r.component, "name": r.name, "attribute": r.attribute,
            "value": r.value, "unit": r.unit, "stepHours": w,
            "pypsaValue": None if math.isnan(value) else value,
            "blank": bool(math.isnan(value)),
            "note": note,
        })
    if missing:
        raise ValueError(f"{SHEET} names components that are not in the model: {', '.join(sorted(set(missing)))}")
    network.meta[META_KEY] = table
    shown = "; ".join(
        f"{t['component']}.{t['name']}.{t['attribute']} {t['value']:g} {t['unit']} -> "
        + ("blank (>= 1 of p_nom per snapshot)" if t["blank"] else f"{t['pypsaValue']:g}")
        for t in table[:6]
    )
    notes.append(
        f"Time units: {len(table)} value(s) written for PyPSA per snapshot at a {w:g} h step "
        f"(ramp = min(1, rate/h x w), blank when >= 1; times = ceil(hours / w)): {shown}{' ...' if len(table) > 6 else ''}."
    )
    for note in rounding[:6]:
        notes.append("Time units: " + note + ".")
    if not uniform:
        notes.append(
            f"Time units: the snapshot weights are not uniform; the smallest step ({w:g} h) was used, so no ramp "
            "bound exceeds the physical rate and no minimum time falls short of the stated duration."
        )
    if overridden:
        notes.append(f"Time units: {overridden} value(s) replaced a number typed directly in the component column.")
    return table


def preview(model: dict[str, Any], scenario: dict[str, Any] | None, options: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The table a run with ``options`` would write (builds the run network; nothing is solved or stored)."""
    from . import build_network

    network, _notes = build_network(model, scenario or {}, options or {})
    return list(network.meta.get(META_KEY) or [])


def set_rows(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A copy of ``model`` whose sheet holds ``rows`` (validated); an empty list removes the sheet."""
    probe = {SHEET: rows}
    read_rows(probe)
    out = dict(model)
    if rows:
        out[SHEET] = [dict(r) for r in rows]
    else:
        out.pop(SHEET, None)
    return out


def merge_rows(model: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A copy of ``model`` with ``rows`` upserted by ``(component, name, attribute)`` (validated)."""
    keyed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in model.get(SHEET) or []:
        if isinstance(r, dict):
            keyed[(str(r.get("component", "")), str(r.get("name", "")), str(r.get("attribute", "")))] = dict(r)
    for r in rows:
        keyed[(str(r.get("component", "")), str(r.get("name", "")), str(r.get("attribute", "")))] = dict(r)
    return set_rows(model, list(keyed.values()))


# ── migration (schema 3 -> 4) ─────────────────────────────────────────────────────

def _spacing_hours(model: dict[str, Any]) -> float:
    """Median spacing of the workbook's snapshots in hours (1 when unreadable): what the plant templates used."""
    from ..utils.weightings import median_spacing_hours

    stamps = [r.get("snapshot") for r in model.get("snapshots") or [] if isinstance(r, dict) and r.get("snapshot") not in (None, "")]
    if len(stamps) < 2:
        return 1.0
    try:
        gap = median_spacing_hours(pd.Index(pd.to_datetime([str(s) for s in stamps])))
    except Exception:  # noqa: BLE001 - labels that are not dates
        return 1.0
    return gap or 1.0


def _enabled_ramp_presets(model: dict[str, Any]) -> bool:
    import json

    for row in model.get("RAGNAROK_Scenarios") or []:
        payload: Any = row.get("json") or row.get("payload") if isinstance(row, dict) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = None
        if isinstance(payload, dict) and isinstance(payload.get("rampConfig"), dict) and payload["rampConfig"].get("enabled"):
            return True
    return False


def migrate_to_time_units(model: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Schema 3 -> 4: ramps and UC times typed per snapshot become time-unit rows. The input is not mutated.

    * Plant-template rows (a committable generator carrying a ``plant`` tag): the template wrote ``ceil(hours / dt)``
      snapshots and ``rate x dt`` per snapshot with the WORKBOOK's spacing ``dt``. They become ``hours`` =
      ``snapshots x dt`` and ``per_hour`` = ``value / dt`` rows and the columns are blanked / reset.
    * A workbook with a preset whose ``rampConfig`` is enabled: the old ramp module read a generator's own
      ``ramp_limit_up/down`` as a rate PER HOUR; those values become ``per_hour`` rows and the columns are blanked.
      (Without such a preset the column was, and stays, PyPSA's per-snapshot value.)

    Returns ``(model, moved)``; ``moved`` lists ``{component, name, attribute, was, value, unit, why}``.
    """
    out = dict(model)
    dt = _spacing_hours(model)
    ramp_presets = _enabled_ramp_presets(model)
    existing = {(r.component, r.name, r.attribute) for r in _safe_rows(model)}
    moved: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    for sheet in COMPONENTS:
        source = out.get(sheet)
        if not isinstance(source, list):
            continue
        rows = [dict(r) if isinstance(r, dict) else r for r in source]
        changed = False
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("name", "")).strip():
                continue
            name = str(row["name"]).strip()
            plant = bool(str(row.get("plant") or "").strip()) and _truthy(row.get("committable"))
            if not (plant or ramp_presets):
                continue
            for attr in RAMP_ATTRS if ramp_presets or plant else ():
                v = _num(row.get(attr))
                if v is None or (sheet, name, attr) in existing:
                    continue
                if plant and not ramp_presets:
                    value, why = v / dt, f"written per snapshot by the plant template at {dt:g} h"
                else:
                    value, why = v, "was a rate per hour under the ramp-rate module"
                new_rows.append({"component": sheet, "name": name, "attribute": attr, "value": round(value, 9), "unit": "per_hour"})
                moved.append({"component": sheet, "name": name, "attribute": attr, "was": v, "value": round(value, 9), "unit": "per_hour", "why": why})
                row[attr] = None
                changed = True
            if plant:
                for attr in TIME_ATTRS:
                    v = _num(row.get(attr))
                    if v is None or v <= 0 or (sheet, name, attr) in existing:
                        continue
                    hours = v * dt
                    new_rows.append({"component": sheet, "name": name, "attribute": attr, "value": round(hours, 9), "unit": "hours"})
                    moved.append({"component": sheet, "name": name, "attribute": attr, "was": v, "value": round(hours, 9), "unit": "hours",
                                  "why": f"snapshots x {dt:g} h written by the plant template"})
                    row[attr] = _PYPSA_TIME_DEFAULT[attr]  # back to PyPSA's default: the value now lives in the sheet
                    changed = True
        if changed:
            out[sheet] = rows
    if new_rows:
        out[SHEET] = [dict(r) for r in model.get(SHEET) or [] if isinstance(r, dict)] + new_rows
    return out, moved


def _safe_rows(model: dict[str, Any]) -> list[TimeRow]:
    try:
        return read_rows(model)
    except ValueError:
        return []


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) and not (isinstance(value, float) and math.isnan(value))
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t", "on"}
