"""Plant ids, the ``RAGNAROK_PLANTS`` registry, and list / edit / delete as *change sets*.

A plant is the set of rows whose ``plant`` column equals its id, plus one registry row (``name`` = id, ``json`` =
type, normalised spec, components). Membership is the column, not the registry, so a plant imported from a PyPSA
file (the column survives ``export_to_netcdf`` / ``csv`` / ``excel``) can still be listed and deleted; only the
edit needs the registry (the spec to re-derive from).

A **change set** is the one currency of every plant action, so the browser (which holds the working model) and the
session (MCP, API) apply the same thing::

    {"remove":  {sheet: [name, ...]},        # rows to delete
     "release": [{"sheet", "name"}, ...],    # shared rows that stay: their ``plant`` column is cleared
     "fragment": {"sheets": {...}} | None,   # rows to merge afterwards (fragment_merge)
     "kept":    {"buses": [...], "carriers": [...]}}

Deleting never removes a bus or carrier that a remaining row still references (a gas bus two plants share, the
AC bus, a carrier another generator uses): it is *released* from the plant instead.
"""

from __future__ import annotations

import copy
import json
import re
from collections import defaultdict
from typing import Any

from .. import fragment_merge

Row = dict[str, Any]
Model = dict[str, list[Row]]

REGISTRY_SHEET = "RAGNAROK_PLANTS"
P2X_SHEET = "RAGNAROK_P2X"
PLANT_COLUMN = "plant"
BUS_COLUMNS = ("bus", "bus0", "bus1", "bus2", "bus3", "bus4", "bus5")
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_NAME_SHEETS = ("buses", "generators", "loads", "links", "processes", "stores", "storage_units", "lines", "transformers")
_NOT_COMPONENTS = {"snapshots", "network"}


class PlantError(ValueError):
    """A bad plant request (unknown plant, name clash, no registry to edit from)."""


def component_sheets(model: Model) -> list[str]:
    """Static row sheets of ``model`` (no time-series sheets, no snapshots)."""
    return [s for s, rows in model.items() if isinstance(rows, list) and "-" not in s and s not in _NOT_COMPONENTS]


def taken_names(model: Model) -> set[str]:
    """Names a new component or plant id must not reuse."""
    out: set[str] = set()
    for sheet in (*_NAME_SHEETS, REGISTRY_SHEET, P2X_SHEET):
        out.update(str(r.get("name")) for r in model.get(sheet) or [] if r.get("name") not in (None, ""))
    return out


def check_plant_id(plant_id: str, model: Model) -> str:
    """``plant_id`` if it is a valid, unused identifier; else :class:`PlantError`."""
    pid = str(plant_id or "").strip()
    if not _NAME_RE.match(pid):
        raise PlantError(f"plantId {pid!r} must start with a letter and use letters, digits and underscores only.")
    if pid in taken_names(model):
        raise PlantError(f"The name {pid!r} is already used in the model; choose another plantId.")
    return pid


def next_plant_id(base: str, model: Model) -> str:
    """First free ``base``, ``base_2``, ``base_3`` ... (also avoiding ``base_*`` collisions with a prefixed component)."""
    taken = taken_names(model)
    if base not in taken:
        return base
    i = 2
    while f"{base}_{i}" in taken:
        i += 1
    return f"{base}_{i}"


class Ctx:
    """Collects the rows one plant build creates; every row is stamped with the plant id."""

    def __init__(self, model: Model, plant_id: str) -> None:
        self.model = model
        self.pid = plant_id
        self.taken = taken_names(model)
        self.sheets: dict[str, list[Row]] = defaultdict(list)
        self.components: list[dict[str, str]] = []
        self.summary: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self.existing_carriers = {str(c.get("name")): c for c in model.get("carriers") or []}
        self.buses = {str(b.get("name")): b for b in model.get("buses") or []}
        self._new_names: set[str] = set()
        self.extra_fragment: dict[str, Any] = {}      # non-sheet keys of the fragment (snapshots)

    def nm(self, suffix: str | None = None) -> str:
        """A component name: the plant id itself (``suffix`` None) or ``<id>_<suffix>``; must be free."""
        name = self.pid if suffix is None else f"{self.pid}_{suffix}"
        if name in self.taken or name in self._new_names:
            raise PlantError(f"Component name {name!r} is already used in the model; choose another plantId.")
        self._new_names.add(name)
        return name

    def add(self, sheet: str, row: Row, role: str, **summary: Any) -> Row:
        """Stamp and queue a component row; ``summary`` extras go to the preview table."""
        row[PLANT_COLUMN] = self.pid
        self.sheets[sheet].append(row)
        self.components.append({"sheet": sheet, "name": str(row["name"]), "role": role})
        keys = ("name", "bus", "bus0", "bus1", "bus2", "bus3", "carrier", "efficiency", "rate0", "rate1", "p_nom", "p_nom_extendable",
                "e_nom", "e_nom_extendable", "p_set", "capital_cost", "marginal_cost", "committable", "p_min_pu", "max_hours")
        self.summary.append({"role": role, "sheet": sheet, **{k: row[k] for k in keys if k in row}, **summary})
        return row

    def carrier(self, name: str, **attrs: Any) -> None:
        """Ensure a carrier. New: created and owned by the plant. Existing: only fills attributes it lacks (merge rule)."""
        if not name:
            return
        have = self.existing_carriers.get(name)
        if have is None:
            if not any(c["name"] == name for c in self.sheets["carriers"]):
                self.sheets["carriers"].append({"name": name, **attrs, PLANT_COLUMN: self.pid})
                self.components.append({"sheet": "carriers", "name": name, "role": f"carrier {name}"})
            return
        for key, val in attrs.items():
            cur = have.get(key)
            if cur in (None, ""):
                self.sheets["carriers"].append({"name": name, key: val})
            elif isinstance(val, (int, float)) and isinstance(cur, (int, float)) and abs(float(cur) - float(val)) > 1e-9:
                self.warnings.append(f"Carrier {name!r} already has {key} = {cur}; kept (the plant would use {val}).")

    def bus(self, role: str, carrier: str, *, name: str | None = None, like: str | None = None) -> str:
        """A new bus at the location of bus ``like``."""
        bname = name or self.nm(f"bus_{role}")
        row: Row = {"name": bname, "carrier": carrier}
        src = self.buses.get(like or "")
        for key in ("x", "y"):
            if src and src.get(key) not in (None, ""):
                row[key] = src[key]
        self.carrier(carrier)
        self.add("buses", row, f"bus {role}")
        self.buses[bname] = row
        return bname

    def fragment(self) -> dict[str, Any]:
        return {"sheets": {s: rows for s, rows in self.sheets.items() if rows}}


# ── registry rows ────────────────────────────────────────────────────────────────


def registry_row(registry: dict[str, Any]) -> Row:
    return {"name": registry["plantId"], "json": json.dumps(registry, sort_keys=True), PLANT_COLUMN: registry["plantId"]}


def registry_map(model: Model) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in model.get(REGISTRY_SHEET) or []:
        try:
            reg = json.loads(str(row.get("json") or ""))
        except (TypeError, ValueError):
            continue
        if isinstance(reg, dict) and reg.get("plantId"):
            out[str(reg["plantId"])] = reg
    return out


def plant_rows(model: Model, plant_id: str) -> dict[str, list[str]]:
    """``{sheet: [names]}`` of the rows tagged with ``plant_id`` (static sheets only)."""
    out: dict[str, list[str]] = {}
    for sheet in component_sheets(model):
        names = [str(r.get("name")) for r in model[sheet] if str(r.get(PLANT_COLUMN) or "") == plant_id and r.get("name") not in (None, "")]
        if names:
            out[sheet] = names
    return out


def plant_ids(model: Model) -> list[str]:
    """Every plant id present: tagged rows and registry rows, in first-seen order."""
    seen: dict[str, None] = {}
    for sheet in component_sheets(model):
        for r in model[sheet]:
            v = str(r.get(PLANT_COLUMN) or "").strip()
            if v:
                seen.setdefault(v, None)
    for pid in registry_map(model):
        seen.setdefault(pid, None)
    return list(seen)


def list_plants(model: Model) -> list[dict[str, Any]]:
    """One card per plant: type, bus, capacity, components (from the registry when present, else from the column)."""
    regs = registry_map(model)
    out = []
    for pid in plant_ids(model):
        rows = plant_rows(model, pid)
        reg = regs.get(pid)
        comps = (reg or {}).get("components") or [{"sheet": s, "name": n, "role": ""} for s, names in rows.items() for n in names]
        live = {(s, n) for s, names in rows.items() for n in names}
        out.append({
            "plantId": pid, "type": (reg or {}).get("type"), "label": (reg or {}).get("label") or pid,
            "bus": (reg or {}).get("bus"), "capacityMwEl": (reg or {}).get("capacityMwEl"), "extendable": (reg or {}).get("extendable"),
            "editable": reg is not None, "spec": (reg or {}).get("spec"),
            "components": [{**c, "present": (c["sheet"], c["name"]) in live} for c in comps if c["sheet"] != REGISTRY_SHEET],
            "rowCount": sum(len(v) for sheet, v in rows.items() if sheet not in (REGISTRY_SHEET, P2X_SHEET)),
        })
    return out


# ── delete / edit as change sets ─────────────────────────────────────────────────


def _refs(model: Model, exclude: dict[str, set[str]]) -> tuple[set[str], set[str]]:
    """``(buses, carriers)`` referenced by rows that are not in ``exclude`` (a bus row's own name does not count)."""
    buses: set[str] = set()
    carriers: set[str] = set()
    for sheet in component_sheets(model):
        if sheet in (REGISTRY_SHEET, P2X_SHEET, "carriers"):
            continue
        skip = exclude.get(sheet, set())
        for r in model[sheet]:
            if str(r.get("name")) in skip:
                continue
            for col in BUS_COLUMNS:
                v = r.get(col)
                if v not in (None, ""):
                    buses.add(str(v))
            c = r.get("carrier")
            if c not in (None, ""):
                carriers.add(str(c))
    return buses, carriers


def delete_change(model: Model, plant_id: str) -> dict[str, Any]:
    """The change set that deletes plant ``plant_id`` and nothing else (shared buses / carriers are released).

    Raises:
        PlantError: no row carries this plant id.
    """
    cand = {s: set(n) for s, n in plant_rows(model, plant_id).items()}
    if not cand:
        raise PlantError(f"No plant {plant_id!r} in the model. Plants: {plant_ids(model)}.")
    kept: dict[str, list[str]] = {"buses": [], "carriers": []}
    changed = True
    while changed:
        changed = False
        buses, carriers = _refs(model, cand)
        for sheet, refs in (("buses", buses), ("carriers", carriers)):
            for name in sorted(cand.get(sheet, set()) & refs):
                cand[sheet].discard(name)
                kept[sheet].append(name)
                changed = True
        # a kept bus keeps the carrier it carries (it is a remaining row now)
        if kept["buses"]:
            kept_carriers = {str(b.get("carrier")) for b in model.get("buses") or [] if str(b.get("name")) in kept["buses"] and b.get("carrier") not in (None, "")}
            for name in sorted(cand.get("carriers", set()) & kept_carriers):
                cand["carriers"].discard(name)
                kept["carriers"].append(name)
                changed = True
    remove = {s: sorted(n) for s, n in cand.items() if n}
    # module rows keyed by component (RAGNAROK_TimeUnits: ramps / UC times) leave with their component
    for sheet in fragment_merge.KEYED_SHEETS:
        names = {str(r.get("name")) for r in model.get(sheet) or [] if str(r.get("component")) in cand and str(r.get("name")) in cand[str(r.get("component"))]}
        if names:
            remove[sheet] = sorted(names)
    release = [{"sheet": s, "name": n} for s in ("buses", "carriers") for n in kept[s]]
    warnings: list[str] = []
    for bus in kept["buses"]:        # a bus that stays because something still draws from it, but nothing feeds it any more
        fed = any(str(g.get("bus")) == bus and str(g.get("name")) not in cand.get("generators", set()) for g in model.get("generators") or []) or any(
            str(r.get(col)) == bus and str(r.get("name")) not in cand.get(sheet, set())
            for sheet in ("links", "processes") for r in model.get(sheet) or [] for col in ("bus1", "bus2", "bus3"))
        if not fed:
            warnings.append(f"Bus {bus!r} is kept (other components use it) but nothing feeds it after this deletion.")
    return {"plantId": plant_id, "remove": remove, "release": release, "fragment": None, "kept": kept, "warnings": warnings}


def apply_change(model: Model, change: dict[str, Any]) -> Model:
    """A copy of ``model`` with the change set applied (remove, release, then merge the fragment)."""
    out: Model = {s: [dict(r) for r in rows] if isinstance(rows, list) else rows for s, rows in model.items()}
    removed_components: dict[str, set[str]] = {s: set(n) for s, n in (change.get("remove") or {}).items()}
    for sheet, names in removed_components.items():
        if sheet in out:
            out[sheet] = [r for r in out[sheet] if str(r.get("name")) not in names]
    for sheet in list(out):                                         # series columns of removed components
        comp, _, _attr = sheet.partition("-")
        if _attr and comp in removed_components and out[sheet]:
            out[sheet] = [{k: v for k, v in r.items() if k not in removed_components[comp]} for r in out[sheet]]
    for rel in change.get("release") or []:
        for r in out.get(rel["sheet"], []):
            if str(r.get("name")) == rel["name"]:
                r.pop(PLANT_COLUMN, None)
    frag = change.get("fragment")
    if frag and frag.get("sheets"):
        out = fragment_merge.merge_fragment(out, frag)
    return out


def merge_spec(base: dict[str, Any], patch: dict[str, Any] | None) -> dict[str, Any]:
    """``base`` with ``patch`` laid over it (nested dicts merged, scalars and lists replaced)."""
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge_spec(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
