"""Persistent server-side store for completed optimisation runs.

When the user ticks "Store in backend" in the run dialog, the solve worker
hands the finished bundle to :func:`store_run`, which writes two files to
``backend/data/runs``:

* ``<name>.json`` — the full bundle (model + scenario + options + result).
  This is the canonical form the frontend reopens via ``GET /api/runs/{name}``.
* ``<name>.meta.json`` — a lightweight sidecar listed in the History tab so
  the browser never has to download a full-year result just to enumerate runs.

Storing server-side sidesteps the browser-tab out-of-memory failure that a
full-year (8784 h) xlsx export hits client-side: the heavy bytes stay on disk
and Excel is produced on demand by :func:`run_to_xlsx`.

Every public function is defensive — a storage failure is logged and never
propagates into the solve (a failed store must not fail an otherwise good run).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger("pypsa_gui.run_store")

# Resolve the runs directory relative to the repository root. ``__file__`` is
# ``backend/app/run_store.py`` so ``parents[2]`` is the repo root, mirroring
# the path resolution used by the test conftest and other backend modules.
_REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = _REPO_ROOT / "backend" / "data" / "runs"

# A run name is a sanitised UTC timestamp, optionally suffixed with a label:
# ``2026-06-07T14-30-00`` or ``2026-06-07T14-30-00_my-scenario``. The guard
# rejects anything with path separators or parent-directory traversal.
_NAME_GUARD = re.compile(r"^[A-Za-z0-9._\-T:]+$")
_LABEL_SANITISE = re.compile(r"[^A-Za-z0-9._-]+")
_LABEL_MAX_LEN = 40
_XLSX_SHEET_MAX_LEN = 31


def _is_safe_name(name: str) -> bool:
    """Return True when ``name`` is safe to use as a filesystem stem.

    Guards every name-taking endpoint (get/delete/xlsx) against path
    traversal: rejects empty strings, anything containing ``/`` or ``..``,
    and anything not matching the allowed character class.
    """
    if not name or "/" in name or "\\" in name or ".." in name:
        return False
    return bool(_NAME_GUARD.match(name))


def _sanitise_label(label: str) -> str:
    """Collapse a free-text label into a filesystem-safe, truncated token."""
    cleaned = _LABEL_SANITISE.sub("-", label).strip("-._")
    return cleaned[:_LABEL_MAX_LEN]


def _derive_name(model: dict[str, Any], scenario: dict[str, Any], options: dict[str, Any]) -> str:
    """Build a datetime-based, filesystem-safe run name.

    The stem is a UTC timestamp ``<YYYY-MM-DDTHH-MM-SS>``; a sanitised label
    (from ``options['runLabel']``, the scenario label, or the model filename)
    is appended when one is available.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    raw_label = (
        (options.get("runLabel") if isinstance(options, dict) else None)
        or (scenario.get("label") if isinstance(scenario, dict) else None)
        or (options.get("filename") if isinstance(options, dict) else None)
        or ""
    )
    label = _sanitise_label(str(raw_label)) if raw_label else ""
    return f"{stamp}_{label}" if label else stamp


def _label_for_bundle(scenario: dict[str, Any], options: dict[str, Any], filename: str) -> str:
    """Human-facing label for the meta sidecar (falls back to the filename)."""
    if isinstance(options, dict) and options.get("runLabel"):
        return str(options["runLabel"])
    if isinstance(scenario, dict) and scenario.get("label"):
        return str(scenario["label"])
    return filename or "Run"


def store_run(
    model: dict[str, Any],
    scenario: dict[str, Any],
    options: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any] | None:
    """Persist a finished run as a JSON bundle plus a lightweight meta sidecar.

    Args:
        model: The in-memory workbook submitted for the run (``{sheet: rows[]}``).
        scenario: The scenario blob submitted for the run.
        options: The run options dict (carries snapshot window + an optional
            ``runLabel`` / ``filename``).
        result: The solver result dict returned by ``backend.run(...)``.

    Returns:
        The meta dict that was written to disk, or ``None`` if storage failed
        (the failure is logged — it never raises into the solve).
    """
    try:
        options = options or {}
        scenario = scenario or {}
        RUNS_DIR.mkdir(parents=True, exist_ok=True)

        name = _derive_name(model, scenario, options)
        saved_at = datetime.now(timezone.utc).isoformat()
        filename = str(options.get("filename") or "")
        label = _label_for_bundle(scenario, options, filename)
        snapshot_start = options.get("snapshotStart")
        snapshot_end = options.get("snapshotEnd")
        snapshot_weight = options.get("snapshotWeight")

        run_meta = result.get("runMeta") if isinstance(result, dict) else None
        component_counts = (
            run_meta.get("componentCounts", {}) if isinstance(run_meta, dict) else {}
        ) or {}

        summary = result.get("summary") if isinstance(result, dict) else None
        kpis = summary[:4] if isinstance(summary, list) else []

        bundle = {
            "savedAt": saved_at,
            "label": label,
            "filename": filename,
            "snapshotStart": snapshot_start,
            "snapshotEnd": snapshot_end,
            "snapshotWeight": snapshot_weight,
            "model": model,
            "scenario": scenario,
            "options": options,
            "result": result,
        }

        bundle_path = RUNS_DIR / f"{name}.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        size_bytes = bundle_path.stat().st_size

        meta = {
            "name": name,
            "savedAt": saved_at,
            "label": label,
            "filename": filename,
            "snapshotStart": snapshot_start,
            "snapshotEnd": snapshot_end,
            "snapshotWeight": snapshot_weight,
            "componentCounts": component_counts,
            "kpis": kpis,
            "sizeBytes": size_bytes,
        }
        (RUNS_DIR / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")

        # Pre-build the xlsx now (server-side) so a later download serves a ready
        # file instead of rebuilding a large workbook on every request. The JSON
        # bundle is the canonical form, so an xlsx-build failure is non-fatal.
        try:
            (RUNS_DIR / f"{name}.xlsx").write_bytes(_frames_to_excel(bundle))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to pre-build xlsx for run %s", name)

        logger.info("Stored run %s (%d bytes)", name, size_bytes)
        return meta
    except Exception:  # noqa: BLE001 — storage must never fail the solve
        logger.exception("Failed to store run in backend")
        return None


def list_runs() -> list[dict[str, Any]]:
    """Return every stored run's meta sidecar, newest first.

    Missing or corrupt sidecar files are skipped with a warning so one bad
    file never breaks the History listing.
    """
    runs: list[dict[str, Any]] = []
    try:
        if not RUNS_DIR.exists():
            return runs
        for path in RUNS_DIR.glob("*.meta.json"):
            try:
                runs.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping unreadable run meta: %s", path.name)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to list backend runs")
        return runs
    runs.sort(key=lambda m: str(m.get("savedAt", "")), reverse=True)
    return runs


def get_run(name: str) -> dict[str, Any] | None:
    """Return the full bundle for ``name``, or ``None`` if missing/unsafe."""
    if not _is_safe_name(name):
        logger.warning("Rejected unsafe run name: %r", name)
        return None
    try:
        path = RUNS_DIR / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to read backend run %s", name)
        return None


def delete_run(name: str) -> bool:
    """Delete the bundle and meta sidecar for ``name``.

    Returns True if at least one file was removed, False otherwise (including
    an unsafe name or a non-existent run).
    """
    if not _is_safe_name(name):
        logger.warning("Rejected unsafe run name for delete: %r", name)
        return False
    removed = False
    try:
        for suffix in (".json", ".meta.json", ".xlsx"):
            path = RUNS_DIR / f"{name}{suffix}"
            if path.exists():
                path.unlink()
                removed = True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to delete backend run %s", name)
        return removed
    return removed


def _frames_to_excel(bundle: dict[str, Any]) -> bytes:
    """Build a human-readable xlsx from a stored bundle.

    Input sheets come from ``bundle['model']`` (list-of-dicts → DataFrame).
    Output frames come from ``bundle['result']['outputs']['static']`` and
    ``['outputs']['series']`` (key → DataFrame), prefixed ``OUT_``. Every
    sheet name is truncated to Excel's 31-char limit with collision dedupe.

    This is an export for inspection — it does NOT round-trip back into the
    model. The JSON bundle remains the canonical reopen form.
    """
    import pandas as pd

    used: set[str] = set()

    def _sheet_name(raw: str) -> str:
        base = (raw or "sheet")[:_XLSX_SHEET_MAX_LEN]
        candidate = base
        suffix = 1
        while candidate in used:
            tail = f"_{suffix}"
            candidate = base[: _XLSX_SHEET_MAX_LEN - len(tail)] + tail
            suffix += 1
        used.add(candidate)
        return candidate

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        wrote_any = False

        model = bundle.get("model") or {}
        if isinstance(model, dict):
            for sheet, rows in model.items():
                if not isinstance(rows, list) or not rows:
                    continue
                pd.DataFrame(rows).to_excel(writer, sheet_name=_sheet_name(str(sheet)), index=False)
                wrote_any = True

        result = bundle.get("result") or {}
        outputs = result.get("outputs") if isinstance(result, dict) else None
        outputs = outputs or {}

        static = outputs.get("static") if isinstance(outputs, dict) else None
        if isinstance(static, dict):
            for key, comp_map in static.items():
                if not isinstance(comp_map, dict) or not comp_map:
                    continue
                # comp_map: {component_name: {attr: value}} → rows.
                df = pd.DataFrame.from_dict(comp_map, orient="index")
                df.index.name = "name"
                df.reset_index(inplace=True)
                df.to_excel(writer, sheet_name=_sheet_name(f"OUT_{key}"), index=False)
                wrote_any = True

        series = outputs.get("series") if isinstance(outputs, dict) else None
        if isinstance(series, dict):
            for key, rows in series.items():
                if not isinstance(rows, list) or not rows:
                    continue
                pd.DataFrame(rows).to_excel(writer, sheet_name=_sheet_name(f"OUT_{key}"), index=False)
                wrote_any = True

        if not wrote_any:
            # openpyxl refuses to save a workbook with zero sheets.
            pd.DataFrame([{"info": "No data in this run."}]).to_excel(
                writer, sheet_name=_sheet_name("info"), index=False
            )

    return buffer.getvalue()


def xlsx_path(name: str) -> Path | None:
    """Path to the pre-built xlsx for ``name`` if it exists (and ``name`` is safe).

    The endpoint streams this file directly, so a download serves a ready file
    rather than rebuilding the workbook per request.
    """
    if not _is_safe_name(name):
        return None
    path = RUNS_DIR / f"{name}.xlsx"
    return path if path.exists() else None


def run_to_xlsx(name: str) -> bytes | None:
    """Return the run's xlsx bytes — the pre-built file if present, else built
    on demand (fallback for runs stored before pre-build, or if it failed).
    ``None`` if the run is missing."""
    pre = xlsx_path(name)
    if pre is not None:
        try:
            return pre.read_bytes()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to read pre-built xlsx for %s", name)
    bundle = get_run(name)
    if bundle is None:
        return None
    try:
        return _frames_to_excel(bundle)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build xlsx for backend run %s", name)
        return None
