"""Control-panel module: switch PyPSA attributes off for a filtered set of components without touching their values.

A PyPSA constraint such as a ramp limit is on when its attribute holds a value and off when it is blank. Turning it
off used to mean deleting the value. A *switch rule* instead names the rows and attributes to neutralise; at submit
time the rule is applied to the run's own copy of the model, so the workbook keeps every value and the next run with
the switch back on uses them again.

Rule (one entry of the app-state value under :data:`STATE_KEY`, ``{"version": 1, "rules": [...]}``)::

    {"id": "r1", "component": "generators", "attributes": ["ramp_limit_up", "ramp_limit_down"],
     "column": "carrier", "values": ["coal", "gas"], "on": false, "label": "no coal/gas ramps"}

* ``component``  - a PyPSA component sheet (``generators``, ``links``, ``processes``, ``storage_units``, ...).
* ``attributes`` - input attributes of that component. Group names (:data:`GROUPS`) expand to their attributes.
* ``column`` / ``values`` - the filter: rows whose ``column`` value (as text) is one of ``values``. An empty
  ``values`` list matches every row of the component.
* ``on`` - the switch. ``true`` (the default) leaves the model as it is; only a rule switched off changes the run.

What "off" writes, per matched row and attribute:

* the static cell, when the row has it, becomes PyPSA's own default for the attribute (blank for a ``NaN`` default
  such as ``ramp_limit_up``; ``False`` for ``committable``; ``0`` for ``p_min_pu`` or ``min_up_time``);
* the row's column in the time-series sheet ``<component>-<attribute>`` is dropped (the static value applies);
* rows of ``RAGNAROK_TimeUnits`` for that component, name and attribute are dropped (they would otherwise write
  the attribute again at build time).

No I/O here: :func:`apply_rules` maps a model dict to a new model dict and a summary.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from ...pypsa import pypsa_schema
from ...pypsa.network import time_units

#: The app-state key the browser writes (a ``ragnarok:`` key, so it travels with the project).
STATE_KEY = "ragnarok:control-panel:rules"
#: The run option that, when a submitter states it, replaces the project's rules for that run.
OPTION_KEY = "controlSwitches"
#: Where the submit hook records what it switched off (kept with the run's options).
APPLIED_KEY = "controlSwitchesApplied"

#: Named attribute groups the UI offers; a rule may name a group instead of listing its attributes.
GROUPS: dict[str, tuple[str, ...]] = {
    "ramps": time_units.RAMP_ATTRS,
    "ramp_up_down": ("ramp_limit_up", "ramp_limit_down"),
    "ramp_start_shut": time_units.START_STOP_ATTRS,
    "uc_times": time_units.TIME_ATTRS,
    "unit_commitment": ("committable",),
    "min_load": ("p_min_pu",),
}


@dataclass
class Rule:
    """One switch rule, validated (see the module docstring for the fields)."""

    id: str
    component: str
    attributes: tuple[str, ...]
    column: str
    values: tuple[str, ...]
    on: bool = True
    label: str = ""


@dataclass
class RuleEffect:
    """What one switched-off rule changed in a model."""

    id: str
    label: str
    component: str
    attributes: list[str]
    column: str
    values: list[str]
    names: list[str] = field(default_factory=list)
    cells: int = 0
    series_columns: int = 0
    time_unit_rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "component": self.component, "attributes": self.attributes,
                "column": self.column, "values": self.values, "matched": len(self.names), "names": self.names,
                "cells": self.cells, "seriesColumns": self.series_columns, "timeUnitRows": self.time_unit_rows}


def _text(value: Any) -> str:
    """A cell as the text a filter compares: blank for None / NaN, ``1`` for ``1.0``."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        if value.is_integer():
            return str(int(value))
    return str(value).strip()


def input_attributes(component: str) -> set[str]:
    """The input attributes of a component sheet (static or time-varying), from the PyPSA schema."""
    return pypsa_schema.input_static_attributes(component) | pypsa_schema.input_temporal_attributes(component)


def off_value(component: str, attribute: str) -> Any:
    """PyPSA's default for ``component.attribute``: what a cell switched off holds (``None`` = blank / NaN)."""
    schema = pypsa_schema.component_schema(component) or {}
    for attr in schema.get("attributes", []):
        if attr.get("attribute") != attribute:
            continue
        raw = str(attr.get("default", "")).strip()
        kind = str(attr.get("type", "")).lower()
        if raw.lower() in ("", "nan", "n/a", "none"):
            return None
        if raw in ("True", "False") or kind == "boolean":
            return raw == "True"
        try:
            number = float(raw)
        except ValueError:
            return raw
        return int(number) if kind == "int" and number.is_integer() else number
    return None


def expand_attributes(names: list[Any]) -> tuple[str, ...]:
    """Attribute names with group names expanded, de-duplicated in order."""
    out: list[str] = []
    for raw in names:
        name = str(raw or "").strip()
        for attr in GROUPS.get(name, (name,)):
            if attr and attr not in out:
                out.append(attr)
    return tuple(out)


def parse_rules(raw: Any) -> list[Rule]:
    """Validate a rule list (or the app-state ``{"version", "rules"}`` object, or its JSON string).

    Raises:
        TypeError: when ``raw`` is not a list of rules.
        ValueError: naming every rule that cannot be used (unknown component or attribute, no column).
    """
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else []
    if isinstance(raw, dict):
        raw = raw.get("rules") or []
    if not isinstance(raw, list):
        raise TypeError("control-panel rules must be a list")
    components = set(pypsa_schema.component_sheets())
    rules: list[Rule] = []
    problems: list[str] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            problems.append(f"rule {i + 1}: not an object")
            continue
        rid = str(item.get("id") or f"rule{i + 1}")
        where = f"rule {rid!r}"
        component = str(item.get("component") or "").strip()
        attrs = expand_attributes(list(item.get("attributes") or []))
        column = str(item.get("column") or "").strip()
        if component not in components:
            problems.append(f"{where}: component {component!r} is not a PyPSA component sheet")
            continue
        if not attrs:
            problems.append(f"{where}: no attributes")
            continue
        unknown = [a for a in attrs if a not in input_attributes(component)]
        if unknown:
            problems.append(f"{where}: {', '.join(unknown)} not an input attribute of {component}")
            continue
        if not column:
            problems.append(f"{where}: no filter column")
            continue
        values = tuple(dict.fromkeys(_text(v) for v in (item.get("values") or [])))
        rules.append(Rule(id=rid, component=component, attributes=attrs, column=column, values=values,
                          on=bool(item.get("on", True)), label=str(item.get("label") or "")))
    if problems:
        raise ValueError("; ".join(problems))
    return rules


def matching_names(model: dict[str, Any], rule: Rule) -> list[str]:
    """Names of the component rows the rule's filter selects, in sheet order."""
    wanted = set(rule.values)
    out: list[str] = []
    for row in model.get(rule.component) or []:
        if not isinstance(row, dict):
            continue
        name = _text(row.get("name"))
        if name and (not wanted or _text(row.get(rule.column)) in wanted):
            out.append(name)
    return out


def apply_rules(model: dict[str, Any], rules: list[Rule]) -> tuple[dict[str, Any], list[RuleEffect]]:
    """Return ``(model with every switched-off rule applied, one effect per such rule)``.

    The input model is not modified; only the sheets a rule touches are copied.

    Algorithm:
        For a rule :math:`r` that is off, with filter set :math:`V_r` on column :math:`c_r` and attributes
        :math:`A_r`, let :math:`G_r = \\{g : V_r = \\emptyset \\lor c_r(g) \\in V_r\\}`. Then for every
        :math:`g \\in G_r, a \\in A_r`: :math:`a_g \\leftarrow d_a` (PyPSA's default :math:`d_a`), the series
        :math:`a_{g,t}` is removed and the time-unit row :math:`(g, a)` is removed.

        ASCII: for g in matches(r), a in attrs(r): static[g][a] = default(a); drop series[a][g]; drop timeunits(g, a)
    """
    out = dict(model)
    effects: list[RuleEffect] = []
    for rule in rules:
        if rule.on:
            continue
        names = matching_names(out, rule)
        effect = RuleEffect(id=rule.id, label=rule.label, component=rule.component, attributes=list(rule.attributes),
                            column=rule.column, values=list(rule.values), names=names)
        effects.append(effect)
        if not names:
            continue
        chosen = set(names)
        static_rows: list[Any] = []
        for row in out.get(rule.component) or []:
            if isinstance(row, dict) and _text(row.get("name")) in chosen:
                row = dict(row)
                for attr in rule.attributes:
                    if attr in row:
                        new = off_value(rule.component, attr)
                        if _text(row[attr]) != _text(new):
                            effect.cells += 1
                        row[attr] = new
            static_rows.append(row)
        out[rule.component] = static_rows
        for attr in rule.attributes:
            sheet = f"{rule.component}-{attr}"
            rows = out.get(sheet)
            if not rows:
                continue
            present = {k for r in rows if isinstance(r, dict) for k in r} & chosen
            if present:
                effect.series_columns += len(present)
                out[sheet] = [{k: v for k, v in r.items() if k not in chosen} if isinstance(r, dict) else r for r in rows]
        tu_rows = out.get(time_units.SHEET)
        if tu_rows:
            attrs = set(rule.attributes)
            kept = [r for r in tu_rows if not (
                isinstance(r, dict) and _text(r.get("component")) == rule.component
                and _text(r.get("name")) in chosen and _text(r.get("attribute")) in attrs)]
            effect.time_unit_rows += len(tu_rows) - len(kept)
            out[time_units.SHEET] = kept
    return out, effects


def describe(effect: dict[str, Any]) -> str:
    """One line for the run's notes: what a switched-off rule did."""
    where = f"{effect['column']} in {', '.join(effect['values'])}" if effect.get("values") else "all rows"
    head = f"Control panel: {', '.join(effect['attributes'])} OFF for {effect['matched']} {effect['component']} ({where})"
    return f"{head} - '{effect['label']}'" if effect.get("label") else head


def column_values(model: dict[str, Any], component: str, column: str) -> list[dict[str, Any]]:
    """The distinct values of ``column`` in a component sheet with their row counts (blank shown as ``""``)."""
    counts: dict[str, int] = {}
    for row in model.get(component) or []:
        if isinstance(row, dict):
            key = _text(row.get(column))
            counts[key] = counts.get(key, 0) + 1
    return [{"value": v, "count": n} for v, n in sorted(counts.items(), key=lambda kv: (kv[0] == "", kv[0]))]


def component_columns(model: dict[str, Any], component: str) -> list[str]:
    """The columns a component sheet has in this model, in first-seen order (the filter candidates)."""
    seen: dict[str, None] = {}
    for row in model.get(component) or []:
        if isinstance(row, dict):
            seen.update(dict.fromkeys(row))
    return list(seen)
