"""Registry loads ``databases.json`` and instantiates enabled modules."""
from __future__ import annotations

from backend.app.importers.registry import (
    available_databases,
    get_database,
    registered_databases,
)


def test_registry_lists_mvp_modules():
    registered_databases.cache_clear()
    ids = set(registered_databases().keys())
    assert {"osm", "wri_gppd", "worldbank_demand"} <= ids


def test_subcategories_round_trip_to_json():
    from backend.app.importers.registry import available_databases

    metas = {m["id"]: m for m in available_databases()}
    assert metas["osm"]["subcategory"] == "Live grid topology"
    assert metas["wri_gppd"]["subcategory"] == "Power plants (per-asset)"
    assert metas["worldbank_demand"]["subcategory"] == "Annual aggregates"


def test_available_databases_json_shape():
    registered_databases.cache_clear()
    metas = available_databases()
    by_id = {m["id"]: m for m in metas}
    assert by_id["osm"]["category"] == "transmission"
    assert by_id["wri_gppd"]["category"] == "generation"
    # Filter schemas are present for the right rail.
    assert any(f["id"] == "min_voltage_kv" for f in by_id["osm"]["filters"])
    assert any(f["id"] == "fuels" for f in by_id["wri_gppd"]["filters"])


def test_get_database_resolves_by_id():
    db = get_database("osm")
    assert db.meta.id == "osm"
    assert callable(db.fetch)
    assert callable(db.preview)
    assert callable(db.to_sheets)


def test_get_database_unknown_raises():
    import pytest

    with pytest.raises(KeyError):
        get_database("not-a-real-module")
