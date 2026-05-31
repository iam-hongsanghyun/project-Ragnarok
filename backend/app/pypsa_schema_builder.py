"""Build the PyPSA component schema from the installed ``pypsa`` package.

Replaces the JS generator at
``frontend/Ragnarok_default/scripts/generate-pypsa-schema.mjs``, which
fetched the CSV definitions from
``raw.githubusercontent.com/PyPSA/PyPSA/master/pypsa/data/...`` at frontend
build time. With the backend owning the schema, we read the SAME files
straight out of the installed ``pypsa`` package (they ship inside it as
``<pypsa>/data/components.csv`` and ``<pypsa>/data/component_attrs/*.csv``).

That means:

* No network fetch at backend startup — the data ships with the lib.
* Always in sync with the installed PyPSA version. If we bump PyPSA, the
  schema bumps automatically the next time the backend boots.
* Same output shape as the JS generator, so frontend consumers (the
  ``src/lib/constants/pypsa_schema.ts`` getter and every component
  iterator downstream) need no changes.

Two related builders live alongside:

* ``build_pypsa_schema()`` — components and their attributes.
* ``build_standard_types()`` — the line / transformer catalogues PyPSA
  ships in ``pypsa.Network().line_types`` / ``.transformer_types``.

Both are pure, deterministic functions over the installed package. The
runtime config bundle in ``backend/app/config_provider.py`` calls each
once at startup and caches the result for the life of the process.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable


# ── Configuration ────────────────────────────────────────────────────────────

SHEET_NAME_OVERRIDES: dict[str, str] = {
    # PyPSA's component list calls the Network attribute table "networks"
    # (plural) in components.csv, but the workbook uses the singular
    # "network" sheet name. Mirrors the JS generator's override table.
    "networks": "network",
}

# Sheets that exist in the workbook but are NOT user-editable component
# tables. The component iterator loop in both frontend and backend skips
# these and handles them via dedicated codepaths.
NON_COMPONENT_SHEETS: list[str] = ["network", "snapshots", "shapes", "sub_networks"]


# ── Locating the installed PyPSA package's data directory ───────────────────


def _pypsa_data_dir() -> Path:
    """Return ``<site-packages>/pypsa/data`` for the active interpreter.

    Raises ``ImportError`` if ``pypsa`` is not importable, with a clear
    message — the backend cannot serve a config bundle without PyPSA
    installed in any case (the solver also needs it).
    """
    import pypsa  # noqa: F401  — proves PyPSA is importable

    package_dir = Path(pypsa.__file__).resolve().parent
    return package_dir / "data"


def _pypsa_version() -> str:
    import pypsa

    return str(getattr(pypsa, "__version__", "unknown"))


# ── CSV helpers (pure stdlib; same shape as the JS parseCsv) ────────────────


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV with header row → list of dicts keyed by column name.

    Strips surrounding whitespace on cell values for resilience to minor
    formatting differences across PyPSA releases.
    """
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]


# ── Attribute normalisation (mirrors the JS generator semantics) ────────────


def _normalize_status(status: str) -> str:
    """``Input (required)`` / ``Input (optional)`` → ``input``; else ``output``."""
    return "input" if status.startswith("Input") else "output"


def _normalize_storage(type_str: str) -> str:
    """``static or series`` → ``static_or_series``; ``series`` → ``series``;
    everything else → ``static``. Matches the JS generator's mapping.
    """
    lowered = (type_str or "").lower()
    if "static or series" in lowered:
        return "static_or_series"
    if "series" in lowered:
        return "series"
    return "static"


def _title_case(value: str) -> str:
    """Snake case → Title Case (e.g. ``storage_units`` → ``Storage Units``)."""
    return " ".join(part.capitalize() for part in value.replace("_", " ").split())


# ── Public builders ─────────────────────────────────────────────────────────


def _build_attribute(record: dict[str, str]) -> dict[str, Any]:
    raw_status = record.get("status", "")
    type_str = record.get("type", "")
    storage = _normalize_storage(type_str)
    return {
        "attribute": record.get("attribute", ""),
        "type": type_str,
        "unit": record.get("unit", ""),
        "default": record.get("default", ""),
        "description": record.get("description", ""),
        "status": _normalize_status(raw_status),
        "raw_status": raw_status,
        "required": "(required)" in raw_status,
        "storage": storage,
    }


def _filter_attribute_names(
    attributes: Iterable[dict[str, Any]],
    *,
    status: str | None = None,
    storage_in: set[str] | None = None,
    storage_not_in: set[str] | None = None,
) -> list[str]:
    out: list[str] = []
    for attr in attributes:
        if status is not None and attr["status"] != status:
            continue
        if storage_in is not None and attr["storage"] not in storage_in:
            continue
        if storage_not_in is not None and attr["storage"] in storage_not_in:
            continue
        out.append(attr["attribute"])
    return out


def build_pypsa_schema() -> dict[str, Any]:
    """Build the schema dict the frontend + backend share.

    Identical output shape to ``scripts/generate-pypsa-schema.mjs``:
    ``{meta: {...}, components: {<sheet>: {...}}}``.
    """
    data_dir = _pypsa_data_dir()
    components_csv = data_dir / "components.csv"
    attrs_dir = data_dir / "component_attrs"

    component_rows = _read_csv_rows(components_csv)
    components_by_list_name = {row["list_name"]: row for row in component_rows}
    list_name_order = [row["list_name"] for row in component_rows]

    components: dict[str, Any] = {}
    for attr_path in sorted(attrs_dir.glob("*.csv")):
        list_name = attr_path.stem
        attribute_records = _read_csv_rows(attr_path)
        attributes = [_build_attribute(r) for r in attribute_records]
        component_meta = components_by_list_name.get(list_name, {})
        component_name = component_meta.get("component") or _title_case(list_name)
        sheet_name = SHEET_NAME_OVERRIDES.get(list_name, list_name)

        components[sheet_name] = {
            "unique_id": sheet_name,
            "component_name": component_name,
            "list_name": list_name,
            "sheet_name": sheet_name,
            "label": component_name,
            "category": component_meta.get("category", ""),
            "source_file": f"pypsa/data/component_attrs/{list_name}.csv",
            "attributes": attributes,
            "input_attributes": _filter_attribute_names(attributes, status="input"),
            "output_attributes": _filter_attribute_names(attributes, status="output"),
            # `static_or_series` attributes belong to BOTH lists — they can be
            # entered as a static scalar in the component sheet, or as a column
            # in the matching time-series sheet (marginal_cost, efficiency,
            # p_max_pu, …).
            "temporal_attributes": _filter_attribute_names(
                attributes, storage_not_in={"static"},
            ),
            "static_attributes": _filter_attribute_names(
                attributes, storage_not_in={"series"},
            ),
            "input_temporal_attributes": _filter_attribute_names(
                attributes, status="input", storage_not_in={"static"},
            ),
            "input_static_attributes": _filter_attribute_names(
                attributes, status="input", storage_not_in={"series"},
            ),
            "order": (
                list_name_order.index(list_name)
                if list_name in list_name_order else -1
            ),
        }

    # ``snapshots`` is not a PyPSA component, but the workbook treats it as
    # a sheet that holds the time index. We synthesise a minimal entry so
    # downstream consumers can find it in the same component table.
    components["snapshots"] = {
        "unique_id": "snapshots",
        "component_name": "Snapshots",
        "list_name": "snapshots",
        "sheet_name": "snapshots",
        "label": "Snapshots",
        "category": "system",
        "source_file": "pypsa/data/component_attrs/networks.csv",
        "attributes": [
            {
                "attribute": "snapshot",
                "type": "string",
                "unit": "n/a",
                "default": "now",
                "description": (
                    "Snapshot label or timestamp used by the workbook "
                    "snapshot index."
                ),
                "status": "input",
                "raw_status": "Input (required)",
                "required": True,
                "storage": "static",
            },
        ],
        "input_attributes": ["snapshot"],
        "output_attributes": [],
        "temporal_attributes": [],
        "static_attributes": ["snapshot"],
        "input_temporal_attributes": [],
        "input_static_attributes": ["snapshot"],
        "order": -1,
    }

    return {
        "meta": {
            "source": "installed pypsa package",
            "pypsa_version": _pypsa_version(),
            "generator": "backend/app/pypsa_schema_builder.py",
            "note": (
                "Built at backend startup from "
                "<site-packages>/pypsa/data/component_attrs/*.csv. Always in "
                "sync with the installed PyPSA version."
            ),
            "non_component_sheets": NON_COMPONENT_SHEETS,
        },
        "components": components,
    }


def build_standard_types() -> dict[str, Any]:
    """Capture PyPSA's built-in line + transformer catalogues.

    Same output shape as ``scripts/generate-pypsa-standard-types.mjs``:
    ``{line_types: [...], transformer_types: [...]}``, with each row a
    dict of column name → value, ``name`` carrying the catalogue key.
    """
    import pypsa

    network = pypsa.Network()

    def _frame_to_rows(frame: Any) -> list[dict[str, Any]]:
        # frame.index → name; frame.columns → fields.
        rows: list[dict[str, Any]] = []
        for name, row in frame.iterrows():
            entry: dict[str, Any] = {"name": str(name)}
            for col, val in row.items():
                # PyPSA cells may be numpy scalars; convert to native types
                # so json.dumps doesn't choke.
                if hasattr(val, "item"):
                    val = val.item()
                entry[str(col)] = val
            rows.append(entry)
        return rows

    return {
        "meta": {
            "source": "pypsa.Network().line_types / .transformer_types",
            "pypsa_version": _pypsa_version(),
            "generator": "backend/app/pypsa_schema_builder.py",
            "note": (
                "Built at backend startup from the live PyPSA Network's "
                "default type catalogues. Always in sync with the installed "
                "PyPSA version."
            ),
        },
        "line_types": _frame_to_rows(network.line_types),
        "transformer_types": _frame_to_rows(network.transformer_types),
    }
