"""Result-mapper registry (H2′) — import third-party result layouts.

The canonical reconstruction in :mod:`project_workbook` understands Ragnarok's
own workbook layout. A third-party tool's export names its sheets differently;
a **result mapper** teaches the importer one such format:

    mapper.name                          — identifier for provenance/logs
    mapper.matches(sheet_names) -> bool  — cheap recognition on sheet names
    mapper.map(sheets, filename) -> bundle — {model, scenario, options, result}

``workbook_to_bundle`` consults the registry *before* the canonical
reconstruction; the first matching mapper wins. Backend plugins participate by
exposing two hooks::

    def result_mapper_matches(sheet_names: list[str]) -> bool: ...
    def result_mapper_map(sheets: dict[str, list[dict]], filename: str) -> dict: ...

so a real third-party format can be supported by dropping in a plugin — no core
change. Sheets the canonical path does not recognise are no longer folded into
the model; they are stored verbatim on ``result["rawSheets"]`` and surfaced as
raw tables.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

Sheets = dict[str, list[dict[str, Any]]]


@dataclass(frozen=True)
class ResultMapper:
    """One recognised third-party result layout."""

    name: str
    matches: Callable[[list[str]], bool]
    map: Callable[[Sheets, str], dict[str, Any]]


_MAPPERS: list[ResultMapper] = []


def register_result_mapper(mapper: ResultMapper) -> None:
    """Register a mapper (first match wins, registration order)."""
    _MAPPERS.append(mapper)


def clear_result_mappers() -> None:
    _MAPPERS.clear()


def _plugin_mappers() -> list[ResultMapper]:
    """Backend plugins exposing the result-mapper hook pair."""
    try:
        from . import plugins
    except Exception:  # noqa: BLE001 — mapper lookup must never break imports
        return []
    out: list[ResultMapper] = []
    try:
        registry = list(plugins.registry().values())
    except Exception:  # noqa: BLE001
        return []
    for plugin in registry:
        matches = getattr(plugin.module, "result_mapper_matches", None)
        mapper = getattr(plugin.module, "result_mapper_map", None)
        if callable(matches) and callable(mapper):
            out.append(ResultMapper(name=f"plugin:{plugin.id}", matches=matches, map=mapper))
    return out


def find_result_mapper(sheet_names: list[str]) -> ResultMapper | None:
    """First registered (then plugin-provided) mapper matching the sheet names."""
    for mapper in [*_MAPPERS, *_plugin_mappers()]:
        try:
            if mapper.matches(list(sheet_names)):
                return mapper
        except Exception:  # noqa: BLE001 — one broken mapper must not block import
            logger.warning("result mapper %s matches() raised — skipped", mapper.name)
    return None
