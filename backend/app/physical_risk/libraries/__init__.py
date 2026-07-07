"""Bundled methodology libraries, vendored verbatim from climaterisk ``assets/libraries``.

Two access levels:

* :func:`load_libraries` — the RAW parsed JSON (snake_case, ``_meta`` intact), keyed the
  same way as climaterisk's ``data/libraries.py`` loader. The compute modules
  (:mod:`..transition`, :mod:`..finance`, :mod:`..engine`) consume this, so the ported
  math reads exactly the fields the upstream code reads.
* :func:`libraries_payload` — the camelCased ``Libraries`` object served by
  ``GET /api/physical-risk/libraries``. Id-keyed dicts (scenario ids, fuel ids, rating
  method ids, …) keep their keys verbatim; only field-name keys are camelised.

The JSON files are frozen, citable reference data — read-only at runtime and cached for
the process lifetime.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DIR = Path(__file__).resolve().parent

# Same names as climaterisk data/libraries.py so the ported modules line up 1:1.
_FILES = {
    "sectors": "sectors.json",
    "perils": "perils.json",
    "scenarios": "scenarios.json",
    "impact_functions": "impact_functions.json",
    "impf_presets": "impact_function_presets.json",
    "carbon_prices": "ngfs_carbon_prices.json",
    "data_sources": "data_sources.json",
    "finance_reference": "finance_reference.json",
    "finance_channels": "finance_channels.json",
}


@lru_cache(maxsize=1)
def load_libraries() -> dict[str, dict[str, Any]]:
    """Load and cache all vendored libraries (raw JSON), keyed by name."""
    out: dict[str, dict[str, Any]] = {}
    for name, filename in _FILES.items():
        with (_DIR / filename).open(encoding="utf-8") as fh:
            out[name] = json.load(fh)
    return out


# ── camelCase payload for the /libraries endpoint ─────────────────────────────

# Dict keys under these field names are DATA IDS (scenario ids, fuel ids, asset types,
# rating-method ids, trajectory ids) — preserved verbatim, never camelised.
_ID_KEYED_FIELDS = {
    "prices",
    "capacity_factor_by_fuel",
    "by_asset_type",
    "rating_methods",
    "trajectories",
    "by_fuel",
}


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _camelize(node: Any, preserve_keys: bool = False) -> Any:
    """Recursively camelise dict keys; one level of key-preservation under id-keyed dicts.

    Keys starting with ``_`` (``_meta``, ``_source``) are dropped unless preserved.
    """
    if isinstance(node, dict):
        out: dict[Any, Any] = {}
        for k, v in node.items():
            if isinstance(k, str) and k.startswith("_") and not preserve_keys:
                continue
            new_key = k if preserve_keys or not isinstance(k, str) else _camel(k)
            out[new_key] = _camelize(v, preserve_keys=isinstance(k, str) and k in _ID_KEYED_FIELDS)
        return out
    if isinstance(node, list):
        return [_camelize(x) for x in node]
    return node


# Phase-0 energy-flavoured vulnerability classes (what the PyPSA seed assigns) mapped to
# the vendored building-class whose curves they borrow, plus their display labels.
_ENERGY_CLASS_BASE: dict[str, tuple[str, str]] = {
    "thermal": ("industrial_heavy", "Thermal plant"),
    "renewable": ("infrastructure", "Renewable (wind / solar)"),
    "hydro": ("infrastructure", "Hydro"),
    "grid": ("infrastructure", "Grid / storage"),
    "default": ("commercial", "Generic"),
}


def _vulnerability_classes(raw: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Vendored building classes + the Phase-0 energy classes with borrowed curve data."""
    classes = [
        {**_camelize(c), "group": "building"} for c in raw["impact_functions"]["classes"]
    ]
    by_id = {c["id"]: c for c in classes}
    for energy_id, (base_id, label) in _ENERGY_CLASS_BASE.items():
        base = by_id.get(base_id)
        if base is None:  # defensive: vendored library must carry the base class
            continue
        classes.append(
            {
                "id": energy_id,
                "label": label,
                "group": "energy",
                "tcVHalf": base["tcVHalf"],
                "wfMaxMdd": base["wfMaxMdd"],
                "floodMdr": list(base["floodMdr"]),
                "eqMdr": list(base["eqMdr"]),
            }
        )
    return classes


def _ngfs_scenarios(raw: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """NGFS carbon-price scenarios as a list, labelled from the transition scenario list."""
    carbon = raw["carbon_prices"]
    meta = carbon.get("_meta", {})
    labels = {s["id"]: s.get("label", s["id"]) for s in raw["scenarios"].get("transition", [])}
    return {
        "units": meta.get("units", ""),
        "model": meta.get("model", ""),
        "source": meta.get("source", ""),
        "scenarios": [
            {"id": sid, "label": labels.get(sid, sid), "prices": dict(prices)}
            for sid, prices in carbon.get("prices", {}).items()
        ],
    }


@lru_cache(maxsize=1)
def libraries_payload() -> dict[str, Any]:
    """The ``Libraries`` object served by ``GET /api/physical-risk/libraries``.

    Keys: ``perils, scenarios, sectors, vulnerabilityClasses, impactFunctions,
    ngfsScenarios, financeChannels, dataSources``. The finance reference framework
    (rating grids, spreads, financing defaults) is nested at ``financeChannels.reference``.
    """
    raw = load_libraries()
    perils = [
        # Every physical peril is computed by the CLIMADA worker in Phase 2; until it is
        # attached, the deterministic stub serves them — flag that for the frontend.
        {**_camelize(p), "workerGated": True}
        for p in raw["perils"]["perils"]
    ]
    impf = raw["impact_functions"]
    return {
        "perils": perils,
        "scenarios": _camelize(raw["scenarios"]),
        "sectors": _camelize(raw["sectors"])["sectors"],
        "vulnerabilityClasses": _vulnerability_classes(raw),
        "impactFunctions": {
            "floodDepthM": list(impf["flood_depth_m"]),
            "eqMmi": list(impf["eq_mmi"]),
            "presets": _camelize(raw["impf_presets"])["presets"],
        },
        "ngfsScenarios": _ngfs_scenarios(raw),
        "financeChannels": {
            **_camelize(raw["finance_channels"]),
            "reference": _camelize(raw["finance_reference"]),
        },
        "dataSources": _camelize(raw["data_sources"]),
    }
