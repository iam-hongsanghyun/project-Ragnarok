"""Dashboard Importer — backend (server-side) plugin.

The same build engine that previously ran in the plugin's own HTTP server
(`dashboard_lib` + the vendored `pipeline.py`, formerly `main.py`) now runs
**inside the Ragnarok backend**. The model is built server-side and written
straight into the session — it never enters the browser, which is what made the
frontend version slow once a model file was uploaded.

Hooks (see `backend/app/plugins.py` for the contract):
* ``transform(model, config)`` builds the workbook and replaces the session model,
  delegating to the engine's ``transform(model, scenario, options)`` with the
  config under ``options["moduleConfig"]`` exactly as the old `/build` server did.
* ``options(name, config, ctx)`` answers dropdowns on demand (generator filters,
  demand-move values, replacement plan) by dispatching to the engine's payload
  builders — replacing the old per-plugin HTTP server at ``localhost:8765``.

The engine reads an uploaded `model_file` (a filename into the plugin's scratch
dir) resolved to an absolute `model_path`, or builds GUI-only from the reference
tables.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_HERE = Path(__file__).resolve().parent
_engine: ModuleType | None = None


def _load_engine() -> ModuleType:
    """Load the vendored build engine once, under a unique module name.

    The engine (``pipeline.py``) makes ``dashboard_lib`` importable itself by
    inserting its own directory onto ``sys.path`` (see ``_bundled_lib_path``),
    so we only need to load the top-level module here.
    """
    global _engine
    if _engine is None:
        spec = importlib.util.spec_from_file_location(
            "_dashboard_importer_engine", _HERE / "pipeline.py"
        )
        if spec is None or spec.loader is None:
            raise ImportError("Cannot load dashboard-importer pipeline.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _engine = module
    return _engine


def transform(model: dict[str, list[dict[str, Any]]], config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build the Ragnarok workbook model server-side from GUI config (replace).

    The unified ``transform(model, config)`` hook. The current session ``model``
    is intentionally discarded — the importer builds a fresh workbook from the
    uploaded dashboard model + GUI settings.

    Args:
        model: the current session model (unused; the build replaces it).
        config: the plugin's config. ``model_file`` is now a *filename reference*
            into the plugin's server-side scratch dir (uploaded once, never held
            in the browser); the framework injects ``__plugin_data_dir__`` so we
            resolve it to an absolute ``model_path`` for the engine.

    Returns:
        A model dict ``{sheet: [rows]}`` for the session store (may include a
        ``RAGNAROK_CustomDSL`` sheet carrying CF constraints).
    """
    del model  # the importer replaces the workbook; current model is discarded
    cfg = _resolve_model_path(config)
    engine = _load_engine()
    return engine.transform({}, {}, {"moduleConfig": cfg})


def _resolve_model_path(config: dict[str, Any]) -> dict[str, Any]:
    """Return a config copy with ``model_path`` resolved from the uploaded file.

    The framework injects ``__plugin_data_dir__`` (the plugin's server-side scratch
    dir) and ``model_file`` is a bare filename into it — turn that into an absolute
    ``model_path`` the engine can open. Shared by ``transform`` and ``options`` so
    both read the same uploaded workbook.
    """
    cfg = dict(config or {})
    data_dir = cfg.pop("__plugin_data_dir__", None)
    selected = cfg.get("model_file")
    # The server-side picker is the canonical choice: a picked model_file WINS
    # over any manual model_path (stale text in that field — e.g. a leftover
    # "4019" — must never shadow the file the user explicitly selected).
    if isinstance(selected, str) and selected.strip() and data_dir:
        cfg["model_path"] = str(Path(data_dir) / selected.strip())
    return cfg


# Dropdown name → engine payload builder. The engine's payload functions already
# return option *rows* (filtered/labelled client-side by the manifest's
# optionsFrom specs), so options() just dispatches by name — Ragnarok core stays
# ignorant of what each dropdown means.
_OPTION_BUILDERS = {
    "/generator_filter_values": "generator_filter_values_payload",
    "/demand_values": "demand_values_payload",
    "/replacement_plan": "replacement_plan_payload",
    "/generators": "generator_filter_values_payload",
}


def analyze(result: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any]:
    """Output-tab analytics — capacity by carrier by year + the reallocation plan.

    Port of the frontend importer's ``analyze`` (which POSTed to its own server's
    ``/capacity`` and ``/replacement_plan``): here the engine's payload builders
    run in-process. ``result`` is unused — the output derives from the uploaded
    model + the current GUI config, so it works before any solve.
    """
    del result
    cfg = _resolve_model_path(config)
    engine = _load_engine()
    try:
        rows = engine.capacity_payload(cfg) or []
    except Exception as exc:  # noqa: BLE001 — surface the reason in the Output tab
        return {"note": f"Capacity unavailable: {exc}"}
    if not rows:
        return {"note": "No generators found in the model — pick a model workbook above."}

    carriers = sorted({k for r in rows for k in r if k not in ("year", "total")})
    chart = {
        "kind": "bar",
        "stacked": True,
        "description": "Installed capacity by carrier by year (MW): build_year ≤ year < close_year",
        "xAxisTitle": "year",
        "yAxisTitle": "MW",
        "series": [{"key": c} for c in carriers],
        "rows": [
            {"label": str(r.get("year")), **{c: r.get(c) or 0 for c in carriers}} for r in rows
        ],
    }
    out: dict[str, Any] = {
        "Capacity by carrier by year (MW)": chart,
        "Cumulative capacity by carrier — table (MW)": rows,
    }
    try:  # the plan is optional — never break the capacity output over it
        plan = engine.replacement_plan_payload(cfg) or []
        if plan:
            out["Reallocation plan (MW)"] = [
                {
                    "generator": r.get("generator"),
                    "build_year": r.get("build_year"),
                    "p_nom (MW)": r.get("total_mw"),
                    "solar (MW)": r.get("solar_mw"),
                    "wind (MW)": r.get("wind_mw"),
                }
                for r in plan
            ]
    except Exception:  # noqa: BLE001
        pass
    return out


def options(name: str, config: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
    """On-demand dropdown rows for a backend-plugin select (see backend/app/plugins.py).

    ``name`` is the option-set id from the manifest (e.g. ``/demand_values``);
    ``config`` is the current form state (incl. the chosen ``model_file``); ``ctx``
    gives read-only session access (unused here — this plugin reads its own
    uploaded workbook, which is the plugin's decision, not Ragnarok's).
    """
    del ctx  # this plugin derives options from its own uploaded model, not the session
    builder_name = _OPTION_BUILDERS.get(name)
    if builder_name is None:
        return []
    cfg = _resolve_model_path(config)
    engine = _load_engine()
    builder = getattr(engine, builder_name, None)
    if builder is None:
        return []
    rows = builder(cfg)
    return rows if isinstance(rows, list) else []
