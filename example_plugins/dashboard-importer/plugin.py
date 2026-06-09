"""Dashboard Importer — backend (server-side) plugin.

The same build engine that previously ran in the plugin's own HTTP server
(`dashboard_lib` + the vendored `pipeline.py`, formerly `main.py`) now runs
**inside the Ragnarok backend**. The model is built server-side and written
straight into the session — it never enters the browser, which is what made the
frontend version slow once a model file was uploaded.

`build(config)` is the backend-plugin hook (see `backend/app/plugins.py`); it
delegates to the engine's `transform(model, scenario, options)`, passing the
config under ``options["moduleConfig"]`` exactly as the old `/build` server did.
The engine reads an uploaded `model_file` (base64) or a server-side
`dashboard_path`, or builds GUI-only from the reference tables.
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
    cfg = dict(config or {})
    data_dir = cfg.pop("__plugin_data_dir__", None)
    selected = cfg.get("model_file")
    # Resolve the chosen uploaded file (a bare filename) to a server path, unless
    # the user gave an explicit model_path. The engine then reads model_path.
    if (
        isinstance(selected, str)
        and selected.strip()
        and not str(cfg.get("model_path") or "").strip()
        and data_dir
    ):
        cfg["model_path"] = str(Path(data_dir) / selected.strip())
    engine = _load_engine()
    return engine.transform({}, {}, {"moduleConfig": cfg})
