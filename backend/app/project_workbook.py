"""Lossless, round-trippable PyPSA *project* workbook (read + write).

This module reads and writes the **exact xlsx layout** that the Ragnarok
frontend's ``buildProjectWorkbook`` / ``parseProjectWorkbook`` use
(``frontend/.../lib/workbook/workbook.ts``). Producing that layout on the
server means:

* **Export** — a stored run's JSON bundle is rendered to an xlsx the frontend
  can re-open with full analytics, with *no information dropped* (unlike the
  previous ``OUT_*`` inspection sheets, which truncated names and could not be
  re-imported).
* **Import** — an uploaded project xlsx is parsed straight back into a run
  bundle (``{model, scenario, options, result}``) and handed to
  :func:`run_store.store_run`, so it lands in History like any solved run.

Layout (must stay in lock-step with the frontend):

* One sheet per model component (``generators``, ``buses``, …). Solved
  *static* outputs (e.g. ``p_nom_opt``) are merged in as extra columns; the
  importer splits them back out by the schema's input/output classification.
* Input time-series sheets (``generators-p_max_pu``, ``loads-p_set``, …) and
  config sheets (``RAGNAROK_Scenarios`` …) are copied verbatim.
* Output time-series sheets named ``<list>-<attr>`` (``generators-p``,
  ``storage_units-state_of_charge`` …) — never an ``OUT_`` prefix, so the names
  stay inside Excel's 31-char limit and parse cleanly.
* ``RAGNAROK_ResultMeta`` / ``RAGNAROK_Constraints`` / ``RAGNAROK_RunState`` /
  ``RAGNAROK_Settings`` / ``RAGNAROK_PluginAnalytics`` metadata sheets. Long
  JSON payloads are chunked across rows (Excel caps a cell at 32 767 chars).

The input/output column classification comes from PyPSA's own component schema
(``pypsa_schema``) — the same source the frontend schema is generated from — so
the two implementations cannot drift apart.
"""
from __future__ import annotations

import json
import logging
from io import BytesIO
from typing import Any

import pandas as pd

from ..pypsa import pypsa_schema as ps

logger = logging.getLogger("pypsa_gui.project_workbook")

# ── Sheet names — MUST match the frontend constants exactly ──────────────────
RESULT_META_SHEET = "RAGNAROK_ResultMeta"
PLUGIN_ANALYTICS_SHEET = "RAGNAROK_PluginAnalytics"
PLUGIN_CONFIGS_SHEET = "RAGNAROK_PluginConfigs"
SETTINGS_SHEET = "RAGNAROK_Settings"
CONSTRAINTS_SHEET = "RAGNAROK_Constraints"
RUN_STATE_SHEET = "RAGNAROK_RunState"
RUN_HISTORY_SHEET = "RAGNAROK_RunHistory"
PROVENANCE_SHEET = "RAGNAROK_Provenance"

# Config sheets live inside the model dict under these keys (copied verbatim).
_META_SHEETS = {
    RESULT_META_SHEET,
    PLUGIN_ANALYTICS_SHEET,
    PLUGIN_CONFIGS_SHEET,
    SETTINGS_SHEET,
    CONSTRAINTS_SHEET,
    RUN_STATE_SHEET,
    RUN_HISTORY_SHEET,
    PROVENANCE_SHEET,
}

# JSON metadata is chunked at this many chars/row (Excel cell limit is 32 767).
_MAX_CELL_CHARS = 30_000
_EXCEL_SHEET_LIMIT = 31

# result-level keys serialised into RAGNAROK_ResultMeta (chunked JSON).
_RESULT_META_KEYS = ("runMeta", "pathway", "rolling", "co2Shadow", "narrative")


# ── Schema helpers (PyPSA-schema driven; mirror the frontend) ────────────────
def _output_static_attrs(sheet: str) -> set[str]:
    """Output attributes stored as a static column (e.g. ``p_nom_opt``)."""
    comp = ps.component_schema(sheet)
    if comp is None:
        return set()
    return set(comp.get("output_attributes", [])) - set(comp.get("temporal_attributes", []))


def _output_series_attrs(sheet: str) -> set[str]:
    """Output attributes stored as a time series (e.g. ``p``, ``state_of_charge``)."""
    comp = ps.component_schema(sheet)
    if comp is None:
        return set()
    return set(comp.get("output_attributes", [])) & set(comp.get("temporal_attributes", []))


def _chunks(text: str) -> list[str]:
    if len(text) <= _MAX_CELL_CHARS:
        return [text]
    return [text[i : i + _MAX_CELL_CHARS] for i in range(0, len(text), _MAX_CELL_CHARS)]


# ─────────────────────────────────────────────────────────────────────────────
#  WRITE  —  bundle → xlsx bytes
# ─────────────────────────────────────────────────────────────────────────────
def _ordered_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Union of keys across rows, in first-seen order (stable column order)."""
    cols: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                cols.append(key)
    return cols


def _write_rows(
    writer: "pd.ExcelWriter",
    name: str,
    rows: list[dict[str, Any]] | None,
    used: set[str],
) -> bool:
    """Write ``rows`` as a sheet ``name``; return True if a sheet was written.

    Skips empty input. Truncates the name to Excel's 31-char limit and dedupes
    collisions (output series names are <= 29 chars, so this is a safety net).
    """
    if not rows:
        return False
    sheet = name[:_EXCEL_SHEET_LIMIT]
    suffix = 1
    while sheet in used:
        tail = f"_{suffix}"
        sheet = name[: _EXCEL_SHEET_LIMIT - len(tail)] + tail
        suffix += 1
    if sheet != name:
        logger.warning("Sheet name %r truncated/deduped to %r", name, sheet)
    used.add(sheet)
    df = pd.DataFrame(rows, columns=_ordered_columns(rows))
    df.to_excel(writer, sheet_name=sheet, index=False)
    return True


def _merge_static_outputs(
    sheet: str,
    rows: list[dict[str, Any]],
    static_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Strip output-static columns from input rows, then merge solved values in.

    Mirrors the frontend writer: a component row carries only its input columns
    plus the *solved* static outputs (``p_nom_opt`` …) from ``outputs.static``.
    Components that exist only in the outputs (e.g. auto-added load shedding)
    are appended.
    """
    out_attrs = _output_static_attrs(sheet)
    merged: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for row in rows:
        stripped = {k: v for k, v in row.items() if k not in out_attrs}
        name = row.get("name")
        if name is not None:
            seen_names.add(str(name))
            solved = static_map.get(str(name))
            if solved:
                stripped.update(solved)
        merged.append(stripped)
    for name, attrs in static_map.items():
        if name not in seen_names:
            merged.append({"name": name, **attrs})
    return merged


def _result_meta_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in _RESULT_META_KEYS:
        value = result.get(key)
        if value is None or value == [] or value == {}:
            continue
        for part, chunk in enumerate(_chunks(json.dumps(value))):
            rows.append({"key": key, "part": part, "json": chunk})
    return rows


def _plugin_analytics_rows(plugin: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(plugin, dict):
        return rows
    for module_id, entry in plugin.items():
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", module_id))
        for field in ("ui", "data"):
            payload = json.dumps(entry.get(field, {}))
            for part, chunk in enumerate(_chunks(payload)):
                rows.append(
                    {"moduleId": module_id, "name": name, "field": field, "part": part, "value": chunk}
                )
    return rows


def _kv_rows(pairs: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    return [{"key": k, "value": v} for k, v in pairs if v is not None]


def bundle_to_workbook(bundle: dict[str, Any]) -> bytes:
    """Render a run bundle to a round-trippable project xlsx (bytes).

    Args:
        bundle: ``{model, scenario, options, result}`` (as stored by run_store)
            or the lighter ``{model, result}`` posted by Export Project.

    Returns:
        xlsx file bytes the Ragnarok frontend can re-import losslessly.
    """
    model = bundle.get("model") or {}
    result = bundle.get("result") or {}
    scenario = bundle.get("scenario") or {}
    options = bundle.get("options") or {}
    outputs = result.get("outputs") if isinstance(result, dict) else None
    outputs = outputs or {}
    static = outputs.get("static") or {}
    series = outputs.get("series") or {}

    buffer = BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        wrote_any = False
        series_keys = set(series.keys())

        # 1) Model sheets (components + input temporal + config). Component
        #    sheets get their solved static outputs merged in.
        if isinstance(model, dict):
            for sheet, rows in model.items():
                if sheet in series_keys or not isinstance(rows, list):
                    continue
                if ps.component_schema(sheet) is not None:
                    rows = _merge_static_outputs(sheet, rows, static.get(sheet) or {})
                wrote_any |= _write_rows(writer, str(sheet), rows, used)

        # 2) Static outputs for components with no input rows in the model.
        if isinstance(static, dict):
            for sheet, comp_map in static.items():
                if not isinstance(comp_map, dict) or (isinstance(model, dict) and sheet in model):
                    continue
                rows = [{"name": name, **attrs} for name, attrs in comp_map.items()]
                wrote_any |= _write_rows(writer, str(sheet), rows, used)

        # 3) Output time-series sheets (`<list>-<attr>`).
        if isinstance(series, dict):
            for key, rows in series.items():
                if isinstance(rows, list):
                    wrote_any |= _write_rows(writer, str(key), rows, used)

        # 4) Metadata sheets.
        wrote_any |= _write_rows(writer, RESULT_META_SHEET, _result_meta_rows(result), used)

        constraints = scenario.get("constraints") if isinstance(scenario, dict) else None
        if isinstance(constraints, list):
            _write_rows(writer, CONSTRAINTS_SHEET, constraints, used)

        run_state = _kv_rows(
            [
                ("snapshotStart", options.get("snapshotStart")),
                ("snapshotEnd", options.get("snapshotEnd")),
                ("snapshotWeight", options.get("snapshotWeight")),
                ("carbonPrice", scenario.get("carbonPrice") if isinstance(scenario, dict) else None),
                ("forceLp", options.get("forceLp")),
                ("activeScenarioId", options.get("scenarioLabel")),
            ]
        )
        _write_rows(writer, RUN_STATE_SHEET, run_state, used)

        settings = _kv_rows(
            [
                ("currencySymbol", options.get("currencySymbol")),
                ("discountRate", scenario.get("discountRate") if isinstance(scenario, dict) else None),
                ("dateFormat", options.get("dateFormat")),
            ]
        )
        _write_rows(writer, SETTINGS_SHEET, settings, used)

        plugin_rows = _plugin_analytics_rows(result.get("pluginAnalytics") if isinstance(result, dict) else None)
        _write_rows(writer, PLUGIN_ANALYTICS_SHEET, plugin_rows, used)

        if not wrote_any:
            pd.DataFrame([{"info": "No data in this project."}]).to_excel(
                writer, sheet_name="info", index=False
            )

    return buffer.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
#  READ  —  xlsx bytes → bundle
# ─────────────────────────────────────────────────────────────────────────────
def _df_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame → list-of-dicts with NaN → None (column order preserved)."""
    clean = df.where(pd.notnull(df), None)
    return clean.to_dict(orient="records")


def _kv_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in rows:
        key = row.get("key")
        if key is None or str(key).strip() == "":
            continue
        out[str(key)] = row.get("value")
    return out


def _reassemble_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, dict[int, str]] = {}
    for row in rows:
        key = row.get("key")
        if not key or not isinstance(row.get("json"), str):
            continue
        by_key.setdefault(str(key), {})[int(row.get("part") or 0)] = row["json"]
    out: dict[str, Any] = {}
    for key, parts in by_key.items():
        joined = "".join(parts[i] for i in sorted(parts))
        if not joined.strip():
            continue
        try:
            out[key] = json.loads(joined)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed RAGNAROK_ResultMeta key %r", key)
    return out


def _reassemble_plugin(rows: list[dict[str, Any]]) -> dict[str, Any]:
    acc: dict[str, dict[str, Any]] = {}
    for row in rows:
        module_id = row.get("moduleId")
        if not module_id:
            continue
        entry = acc.setdefault(str(module_id), {"name": str(row.get("name") or module_id), "ui": {}, "data": {}})
        field = str(row.get("field") or "")
        if field not in ("ui", "data"):
            continue
        entry.setdefault(f"_{field}_parts", {})[int(row.get("part") or 0)] = (
            row.get("value") if isinstance(row.get("value"), str) else ""
        )
    plugin: dict[str, Any] = {}
    for module_id, entry in acc.items():
        result_entry = {"name": entry["name"], "ui": {}, "data": {}}
        for field in ("ui", "data"):
            parts = entry.get(f"_{field}_parts", {})
            joined = "".join(parts[i] for i in sorted(parts))
            if joined.strip():
                try:
                    result_entry[field] = json.loads(joined)
                except json.JSONDecodeError:
                    pass
        plugin[module_id] = result_entry
    return plugin


def workbook_to_bundle(data: bytes, filename: str = "") -> dict[str, Any]:
    """Parse a project xlsx back into a run bundle ``{model, scenario, options, result}``.

    The reverse of :func:`bundle_to_workbook`. Output static columns inside
    component sheets are split into ``result.outputs.static``; ``<list>-<attr>``
    output series sheets into ``result.outputs.series``. Derived analytics
    (summary, dispatch, …) are intentionally *not* reconstructed here — the
    frontend recomputes them from ``outputs`` when the run is opened.
    """
    model: dict[str, Any] = {}
    static: dict[str, dict[str, Any]] = {}
    series: dict[str, Any] = {}
    result: dict[str, Any] = {"outputs": {"static": static, "series": series}}
    scenario: dict[str, Any] = {}
    options: dict[str, Any] = {}

    excel = pd.ExcelFile(BytesIO(data), engine="openpyxl")
    for sheet in excel.sheet_names:
        rows = _df_rows(excel.parse(sheet))

        if sheet == RESULT_META_SHEET:
            result.update(_reassemble_meta(rows))
            continue
        if sheet == CONSTRAINTS_SHEET:
            if rows:
                scenario["constraints"] = rows
            continue
        if sheet == RUN_STATE_SHEET:
            kv = _kv_map(rows)
            for key in ("snapshotStart", "snapshotEnd", "snapshotWeight", "forceLp"):
                if key in kv:
                    options[key] = kv[key]
            if "carbonPrice" in kv:
                scenario["carbonPrice"] = kv["carbonPrice"]
            if kv.get("activeScenarioId"):
                options["scenarioLabel"] = kv["activeScenarioId"]
            continue
        if sheet == SETTINGS_SHEET:
            kv = _kv_map(rows)
            if "currencySymbol" in kv:
                options["currencySymbol"] = kv["currencySymbol"]
            if "dateFormat" in kv:
                options["dateFormat"] = kv["dateFormat"]
            if "discountRate" in kv:
                scenario["discountRate"] = kv["discountRate"]
            continue
        if sheet == PLUGIN_ANALYTICS_SHEET:
            plugin = _reassemble_plugin(rows)
            if plugin:
                result["pluginAnalytics"] = plugin
            continue
        if sheet in _META_SHEETS:
            continue  # PluginConfigs / Provenance / RunHistory — not needed in the bundle

        # Output time-series sheet?
        comp_sheet, dash, attr = sheet.partition("-")
        if dash and attr in _output_series_attrs(comp_sheet):
            series[sheet] = rows
            continue

        # Static component sheet → split input vs output-static columns.
        comp = ps.component_schema(sheet)
        if comp is not None:
            out_attrs = _output_static_attrs(sheet)
            input_rows: list[dict[str, Any]] = []
            for row in rows:
                input_part: dict[str, Any] = {}
                output_part: dict[str, Any] = {}
                name = row.get("name")
                for key, value in row.items():
                    if key == "name":
                        input_part[key] = value
                    elif key in out_attrs:
                        if value is not None and value != "":
                            output_part[key] = value
                    else:
                        input_part[key] = value
                input_rows.append(input_part)
                if name is not None and output_part:
                    static.setdefault(sheet, {})[str(name)] = output_part
            model[sheet] = input_rows
        else:
            # Input temporal / config sheet — copy verbatim into the model.
            model[sheet] = rows

    options.setdefault("filename", filename)
    return {"model": model, "scenario": scenario, "options": options, "result": result}
