"""Helpers for loading per-module ``config.json`` files.

Each database module under ``databases/<id>/`` ships a ``config.json``
declaring its metadata + filter schema. The module's ``build()`` factory
calls :func:`load_module_config` to read it; this module exists so the path-
juggling is in one place rather than duplicated across modules.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .protocol import DatabaseMeta, Filter


def load_module_config_dict(module_file: str) -> dict[str, Any]:
    """Return the raw ``config.json`` dict for the given module.

    Args:
        module_file: ``__file__`` of the calling module's package
            (``backend/app/importers/databases/<id>/__init__.py``).
    """
    cfg_path = Path(module_file).resolve().parent / "config.json"
    with cfg_path.open() as f:
        return json.load(f)


def meta_from_config(
    config: dict[str, Any],
    *,
    available: bool = True,
    unavailable_reason: str | None = None,
) -> DatabaseMeta:
    """Build a :class:`DatabaseMeta` from a ``config.json`` dict."""
    filters = [
        Filter(
            id=str(f["id"]),
            label=str(f["label"]),
            kind=str(f["kind"]),
            default=f.get("default"),
            options=f.get("options"),
            min=f.get("min"),
            max=f.get("max"),
            step=f.get("step"),
            unit=f.get("unit"),
            description=f.get("description"),
        )
        for f in config.get("filters", [])
    ]
    coverage_raw = config.get("country_coverage", "global")
    country_coverage: list[str] | str
    if isinstance(coverage_raw, list):
        country_coverage = [str(x).upper() for x in coverage_raw]
    else:
        country_coverage = str(coverage_raw)

    return DatabaseMeta(
        id=str(config["id"]),
        name=str(config["name"]),
        category=str(config["category"]),
        subcategory=str(config.get("subcategory", "")),
        license=str(config.get("license", "")),
        homepage=str(config.get("homepage", "")),
        version_hint=str(config.get("version_hint", "")),
        targets=list(config.get("targets", [])),
        filters=filters,
        available=available,
        unavailable_reason=unavailable_reason,
        description=str(config.get("description", "")),
        country_coverage=country_coverage,
    )
