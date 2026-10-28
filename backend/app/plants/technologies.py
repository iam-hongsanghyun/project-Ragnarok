"""Technology data for the Build plant templates (CCGT, OCGT, gas + H2 co-firing, BESS): loader and unit helpers.

The defaults live in ``technologies.json`` (nothing is hard-coded in Python). Every parameter carries ``value``,
``unit``, ``source`` (document, locator, year), ``costYear`` / ``currency`` where it is a price, and ``verified``:

* ``file``       read from the pinned upstream file (PyPSA technology-data v0.15.0, ``costs_2030.csv`` or the DEA
                 workbooks in its ``inputs`` folder);
* ``derived``    computed from file values or from literature inputs (the derivation is in the note);
* ``literature`` recalled from a published source and not re-fetched in this build;
* ``assumption`` a Ragnarok default with no source file; replace it with plant data.

``RAGNAROK_PLANTS_TECHNOLOGIES_FILE`` points the app at another file with the same schema. The P2X file
(``backend/app/p2x/technologies.json``) is separate and untouched. Templates write PyPSA's own cost split (``overnight_cost``,
``fom_cost``, ``lifetime``); nothing is annuitised or folded here (:func:`overnight_equivalent` is re-exported only for the P2X files).
"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..p2x.technologies import overnight_equivalent  # noqa: F401  (re-exported: one fixed-cost convention)

BUNDLED_FILE = Path(__file__).with_name("technologies.json")
ENV_FILE = "RAGNAROK_PLANTS_TECHNOLOGIES_FILE"
FUELS = "fuels"


def technologies_path() -> Path:
    """The data file in use: ``RAGNAROK_PLANTS_TECHNOLOGIES_FILE`` or the bundled one."""
    named = os.environ.get(ENV_FILE, "").strip()
    return Path(named).expanduser() if named else BUNDLED_FILE


@lru_cache(maxsize=4)
def _load(path: str, stamp: float) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("schema") != 1 or "technologies" not in data or "fuels" not in data:
        raise ValueError(f"{path}: not a plant technologies file (schema 1 with technologies and fuels expected).")
    return data


def load() -> dict[str, Any]:
    """The parsed data file (cached per path and modification time)."""
    path = technologies_path()
    return _load(str(path), path.stat().st_mtime)


def constants() -> dict[str, float]:
    """Numeric constants of the data file keyed by name (unit in the file)."""
    return {k: float(v["value"]) for k, v in load()["constants"].items()}


def default_discount_rate() -> float:
    """Default discount rate (1/a) when the caller gives none."""
    return float(load()["defaults"]["discount_rate"]["value"])


def parameter_defaults() -> dict[str, dict[str, float]]:
    """``{technology: {parameter: value}}``; the fuels are the pseudo-technology ``fuels``."""
    data = load()
    out = {t: {n: float(p["value"]) for n, p in body["parameters"].items()} for t, body in data["technologies"].items()}
    out[FUELS] = {n: float(p["value"]) for n, p in data["fuels"].items()}
    return out


def resolve_parameters(overrides: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    """Defaults with dotted-key overrides applied (``"ccgt.efficiency": 0.6``, ``"fuels.gas_price": 35``).

    Raises:
        ValueError: unknown technology or parameter, or a non-finite / non-numeric value.
    """
    params = parameter_defaults()
    for key, raw in (overrides or {}).items():
        tech, _, name = str(key).partition(".")
        if tech not in params or name not in params[tech]:
            raise ValueError(f"Unknown plant parameter {key!r}. See GET /api/build/plant/technologies for the keys.")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter {key!r} must be a number, got {raw!r}.") from exc
        if not math.isfinite(value):
            raise ValueError(f"Parameter {key!r} must be finite.")
        params[tech][name] = value
    return params


def catalogue(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The whole data file for the API (``value`` = effective, ``default`` = file value)."""
    data = load()
    eff = resolve_parameters(overrides)

    def entries(group: dict[str, Any], key: str) -> dict[str, Any]:
        return {n: {**p, "default": p["value"], "value": eff[key][n]} for n, p in group.items()}

    return {
        "schema": data["schema"], "title": data.get("title"), "file": str(technologies_path()), "basis": data["basis"],
        "sources": data["sources"], "constants": data["constants"], "defaults": data.get("defaults", {}),
        "fuels": entries(data["fuels"], FUELS),
        "technologies": {t: {**{k: v for k, v in body.items() if k != "parameters"}, "parameters": entries(body["parameters"], t)}
                         for t, body in data["technologies"].items()},
    }
