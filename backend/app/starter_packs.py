"""Country starter-pack framework (W2).

A starter pack is a **recipe** — ``starter_packs/<ISO3>/<year>/recipe.json`` —
that names, per model slot (network, demand, renewable capacity, renewable
profile, …), which importer dataset(s) assemble it and with what filters. The
executor runs each step's importer(s) for the chosen country and folds every
fragment into one runnable workbook — generalising the hand-wired KPG193/Korea
pack to "state a country + year, get a model" for any recipe.

Zero new data-source code: it sequences the shipped importer registry. The
executor's dependencies (dataset registry, region, HTTP/secrets) are injectable
so the orchestration is unit-tested offline with a fake registry.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable

_RECIPES_DIR = Path(__file__).parent / "starter_packs"


def _recipe_path(iso3: str, year: int | str) -> Path:
    return _RECIPES_DIR / str(iso3).upper() / str(year) / "recipe.json"


def list_recipes() -> list[dict[str, Any]]:
    """Discover every ``<ISO3>/<year>/recipe.json`` under the packs dir."""
    out: list[dict[str, Any]] = []
    if not _RECIPES_DIR.exists():
        return out
    for path in sorted(_RECIPES_DIR.glob("*/*/recipe.json")):
        try:
            r = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "iso3": str(r.get("iso3", path.parent.parent.name)).upper(),
            "year": r.get("year", path.parent.name),
            "label": r.get("label", ""),
            "description": r.get("description", ""),
            "slots": [s.get("slot") for s in r.get("steps", [])],
        })
    return out


def load_recipe(iso3: str, year: int | str) -> dict[str, Any] | None:
    path = _recipe_path(iso3, year)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


async def build_from_recipe(
    recipe: dict[str, Any],
    *,
    dbs: dict[str, Any],
    region: Any,
    ctx: Any,
    options: Any,
    combine: Callable[..., Any],
) -> tuple[Any, list[str], list[Any]]:
    """Run a recipe's steps and fold their fragments into one workbook.

    Args:
        recipe: The parsed recipe dict.
        dbs: dataset-id → Database (the registry, injectable for tests).
        region: Resolved import Region for the country.
        ctx: ImportContext (http + secrets).
        options: ConvertOptions.
        combine: ``combine_fragments`` (injected to avoid a hard import here).

    Returns:
        ``(fragment, dataset_ids, previews)``.

    Raises:
        KeyError: a recipe dataset id is not in the registry.
    """
    fragments: list[Any] = []
    previews: list[Any] = []
    all_ids: list[str] = []
    for step in recipe.get("steps", []):
        filters = dict(step.get("filters") or {})
        for did in step.get("datasets", []):
            if did not in dbs:
                raise KeyError(f"recipe dataset {did!r} is not registered")
            db = dbs[did]
            result = await db.fetch(region, filters, ctx)
            previews.append(db.preview(result))
            fragments.append(db.to_sheets(result, options))
            all_ids.append(did)

    fragment = combine(
        fragments,
        source_id=f"starter:{str(recipe.get('iso3', '')).upper()}",
        country_iso=region.country_iso,
        country_name=region.country_name,
        filters={"recipe": f"{recipe.get('iso3')}/{recipe.get('year')}"},
        dataset_ids=all_ids,
    )
    return fragment, all_ids, previews


def new_request_id() -> str:
    return str(uuid.uuid4())[:8]


# ── I1: auto-recipe for an arbitrary location ────────────────────────────────

# Keyless, broad-coverage datasets composed for a one-click "pick a location →
# runnable model", in slot order. Each is included only if it's registered,
# available, and covers the requested country.
_AUTO_SLOTS = [
    ("network", "osm"),
    ("power_plants", "osm_powerplants"),
    ("fleet", "wri_gppd"),
    ("demand", "worldbank_demand"),
]


def _covers(meta: Any, iso3: str) -> bool:
    cov = getattr(meta, "country_coverage", "global")
    return cov == "global" or iso3.upper() in {str(c).upper() for c in cov}


def auto_recipe(iso3: str, dbs: dict[str, Any]) -> dict[str, Any]:
    """Assemble a recipe for any country from the keyless global importers.

    Selects the network / plants / fleet / demand datasets that are registered,
    available, and cover ``iso3`` — the reliable no-API-key first cut of a
    runnable model. Steps referencing an absent/uncovered dataset are dropped.
    """
    iso = iso3.upper()
    steps: list[dict[str, Any]] = []
    for slot, did in _AUTO_SLOTS:
        db = dbs.get(did)
        if db is None:
            continue
        meta = db.meta
        if not getattr(meta, "available", True) or not _covers(meta, iso):
            continue
        steps.append({"slot": slot, "datasets": [did], "filters": {}})
    return {"iso3": iso, "year": "auto", "label": f"{iso} — one-click model", "steps": steps}
