"""Persistent server-side store for completed optimisation runs.

Every successful solve is persisted automatically: the solve worker hands the
finished bundle to :func:`store_run`, which writes two files to
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

# Stem-only file extensions stripped before a filename becomes a run label, so a
# run is never named ``...ragnarok_case.xlsx`` (which then yields a double
# ``.xlsx.xlsx`` on download). Generic default filenames carry no information —
# they're dropped so the run name stays a clean timestamp.
_LABEL_EXTENSIONS = (".xlsx", ".xls", ".nc", ".h5", ".hdf5", ".zip")
_DEFAULT_FILENAME_STEMS = {"ragnarok_case", "ragnarok_project", "ragnarok"}


def _filename_label_stem(filename: str) -> str:
    """Filename → label stem: lowercase-extension stripped; '' for generic defaults.

    ``ragnarok_case.xlsx`` → ``''`` (a meaningless default, so no label),
    ``north-sea-2030.xlsx`` → ``north-sea-2030``.
    """
    stem = filename.strip()
    lowered = stem.lower()
    for ext in _LABEL_EXTENSIONS:
        if lowered.endswith(ext):
            stem = stem[: -len(ext)]
            break
    return "" if stem.lower() in _DEFAULT_FILENAME_STEMS else stem


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
    (from ``options['runLabel']``, the scenario label, or the model filename
    with its extension stripped) is appended when one is available. A generic
    default filename (``ragnarok_case.xlsx`` etc.) contributes no label, so a
    plain run keeps a clean timestamp name.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    raw_label = (
        (options.get("runLabel") if isinstance(options, dict) else None)
        or (scenario.get("label") if isinstance(scenario, dict) else None)
        or ""
    )
    if not raw_label and isinstance(options, dict) and options.get("filename"):
        raw_label = _filename_label_stem(str(options["filename"]))
    label = _sanitise_label(str(raw_label)) if raw_label else ""
    return f"{stamp}_{label}" if label else stamp


def _label_for_bundle(scenario: dict[str, Any], options: dict[str, Any], filename: str) -> str:
    """Human-facing label for the meta sidecar (falls back to the filename)."""
    if isinstance(options, dict) and options.get("runLabel"):
        return str(options["runLabel"])
    if isinstance(scenario, dict) and scenario.get("label"):
        return str(scenario["label"])
    return _filename_label_stem(filename) or "Run"


def build_run_meta(name: str, bundle: dict[str, Any], size_bytes: int = 0) -> dict[str, Any]:
    """Compute the lightweight meta sidecar from a run bundle.

    Shared by :func:`store_run` (persisted alongside the bundle) and the project
    export path (so an exported package's ``.meta.json`` matches a stored run's).
    Carries only the small fields History + Analytics→Comparison read — never a
    time series.
    """
    scenario = bundle.get("scenario") or {}
    options = bundle.get("options") or {}
    result = bundle.get("result") or {}

    run_meta = result.get("runMeta") if isinstance(result, dict) else None
    component_counts = (run_meta.get("componentCounts", {}) if isinstance(run_meta, dict) else {}) or {}

    summary = result.get("summary") if isinstance(result, dict) else None
    summary = summary if isinstance(summary, list) else []

    carrier_mix = result.get("carrierMix") if isinstance(result, dict) else None
    carrier_mix = carrier_mix if isinstance(carrier_mix, list) else []

    pathway_src = result.get("pathway") if isinstance(result, dict) else None
    pathway_meta: dict[str, Any] | None = None
    if isinstance(pathway_src, dict):
        pathway_meta = {
            "enabled": pathway_src.get("enabled"),
            "periods": pathway_src.get("periods"),
            "selectedPeriod": pathway_src.get("selectedPeriod"),
            "summaries": pathway_src.get("summaries"),
        }

    rolling_src = result.get("rolling") if isinstance(result, dict) else None
    rolling_meta: dict[str, Any] | None = None
    if isinstance(rolling_src, dict):
        rolling_meta = {
            "enabled": rolling_src.get("enabled"),
            "horizonSnapshots": rolling_src.get("horizonSnapshots"),
            "overlapSnapshots": rolling_src.get("overlapSnapshots"),
            "windowCount": rolling_src.get("windowCount"),
        }

    scenario_label = (
        (scenario.get("label") if isinstance(scenario, dict) else None)
        or (options.get("scenarioLabel") if isinstance(options, dict) else None)
        or None
    )
    filename = str(options.get("filename") or bundle.get("filename") or "")

    return {
        "name": name,
        "savedAt": bundle.get("savedAt"),
        "label": bundle.get("label") or _label_for_bundle(scenario, options, filename),
        "filename": filename,
        "snapshotStart": options.get("snapshotStart"),
        "snapshotEnd": options.get("snapshotEnd"),
        "snapshotWeight": options.get("snapshotWeight"),
        "componentCounts": component_counts,
        "kpis": summary[:4],
        "sizeBytes": size_bytes,
        "summary": summary,
        "carrierMix": carrier_mix,
        "pathway": pathway_meta,
        "rolling": rolling_meta,
        "scenarioLabel": scenario_label,
    }


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

        bundle = {
            "savedAt": saved_at,
            "label": label,
            "filename": filename,
            "snapshotStart": options.get("snapshotStart"),
            "snapshotEnd": options.get("snapshotEnd"),
            "snapshotWeight": options.get("snapshotWeight"),
            "model": model,
            "scenario": scenario,
            "options": options,
            "result": result,
        }

        bundle_path = RUNS_DIR / f"{name}.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        size_bytes = bundle_path.stat().st_size

        meta = build_run_meta(name, bundle, size_bytes)
        (RUNS_DIR / f"{name}.meta.json").write_text(json.dumps(meta), encoding="utf-8")

        # Pre-build the xlsx now (server-side) so a later download serves a ready
        # file instead of rebuilding a large workbook on every request. The JSON
        # bundle is the canonical form, so an xlsx-build failure is non-fatal.
        try:
            from . import project_workbook

            (RUNS_DIR / f"{name}.xlsx").write_bytes(project_workbook.bundle_to_workbook(bundle))
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
                meta = json.loads(path.read_text(encoding="utf-8"))
                # The xlsx is pre-built AFTER the meta sidecar, so a run can be
                # listed before its workbook is ready. Surface readiness so the
                # UI can show "Preparing…" until the export package can be built.
                name = str(meta.get("name", ""))
                meta["xlsxReady"] = bool(name) and (RUNS_DIR / f"{name}.xlsx").exists()
                runs.append(meta)
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
        from . import project_workbook

        return project_workbook.bundle_to_workbook(bundle)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to build xlsx for backend run %s", name)
        return None


def run_to_package(name: str) -> bytes | None:
    """Return a Ragnarok Project ``.zip`` for ``name`` — ALL THREE files.

    Bundles the three on-disk artefacts so the export is complete:

    * ``<name>.json``       — the canonical bundle (lossless source of truth),
    * ``<name>.meta.json``  — the lightweight meta sidecar (History/Comparison),
    * ``<name>.xlsx``       — the human-readable workbook.

    ``None`` if the run does not exist. The xlsx is built on demand if its
    pre-built file is somehow missing, so the package is always complete.
    """
    if not _is_safe_name(name):
        return None
    bundle = get_run(name)
    if bundle is None:
        return None

    meta_path = RUNS_DIR / f"{name}.meta.json"
    meta_bytes = meta_path.read_bytes() if meta_path.exists() else None
    xlsx_bytes = run_to_xlsx(name)

    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.json", json.dumps(bundle))
        if meta_bytes is not None:
            zf.writestr(f"{name}.meta.json", meta_bytes)
        if xlsx_bytes is not None:
            zf.writestr(f"{name}.xlsx", xlsx_bytes)
    return buffer.getvalue()
