from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "config" / "pypsa_schema.json"


def _network_import_policy_path() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "config" / "network_import_policy.json"


@lru_cache(maxsize=1)
def load_pypsa_schema() -> dict[str, Any]:
    return json.loads(_schema_path().read_text())


@lru_cache(maxsize=1)
def load_network_import_policy() -> dict[str, Any]:
    return json.loads(_network_import_policy_path().read_text())


def component_schema(sheet_name: str) -> dict[str, Any] | None:
    return load_pypsa_schema().get("components", {}).get(sheet_name)


def component_sheets() -> list[str]:
    return list(load_pypsa_schema().get("components", {}).keys())


def non_component_sheets() -> set[str]:
    """Sheets recorded in schema metadata as non-component workbook sheets."""
    meta = load_pypsa_schema().get("meta", {})
    return set(meta.get("non_component_sheets", []))


def network_runtime_import_fields() -> list[dict[str, Any]]:
    return [
        field
        for field in load_network_import_policy().get("fields", [])
        if field.get("enabled_for_runtime_import")
    ]


def input_static_attributes(sheet_name: str) -> set[str]:
    """Return attributes that may appear as a static column in the workbook.

    Includes both `storage="static"` and `storage="static_or_series"` attributes —
    the latter (e.g. `marginal_cost`, `efficiency`) can be supplied as a scalar in
    the static sheet or as a column in the time-series sheet. The pre-computed
    `input_static_attributes` field in the schema JSON only captures pure-static
    attributes, so we re-derive from the canonical `attributes` array.
    """
    component = component_schema(sheet_name)
    if not component:
        return set()
    return {
        attr["attribute"]
        for attr in component.get("attributes", [])
        if attr.get("status") == "input"
        and attr.get("storage") in ("static", "static_or_series")
    }


def input_temporal_attributes(sheet_name: str) -> set[str]:
    """Return attributes that may appear as a time-series sheet column.

    Includes both `storage="series"` and `storage="static_or_series"` attributes.
    """
    component = component_schema(sheet_name)
    if not component:
        return set()
    return {
        attr["attribute"]
        for attr in component.get("attributes", [])
        if attr.get("status") == "input"
        and attr.get("storage") in ("series", "static_or_series")
    }


def output_attributes(sheet_name: str) -> set[str]:
    component = component_schema(sheet_name)
    if not component:
        return set()
    return set(component.get("output_attributes", []))


def required_input_static_attributes(sheet_name: str) -> set[str]:
    component = component_schema(sheet_name)
    if not component:
        return set()
    return {
        attr["attribute"]
        for attr in component.get("attributes", [])
        if attr.get("status") == "input"
        and attr.get("required")
        and attr.get("storage") != "series"
    }


def bus_reference_attributes(sheet_name: str) -> list[dict[str, Any]]:
    component = component_schema(sheet_name)
    if not component:
        return []
    attrs = []
    for attr in component.get("attributes", []):
        name = str(attr.get("attribute", ""))
        if attr.get("status") != "input" or attr.get("storage") == "series":
            continue
        if name == "bus" or (name.startswith("bus") and name[3:].isdigit()):
            attrs.append(attr)
    return attrs
