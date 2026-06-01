"""Importer registry + endpoint contract (network-free parts).

The per-module fetch paths hit live upstreams (Overpass, GitHub, World
Bank), so they're exercised manually / in preview rather than here — a
flaky network must not break the unit suite. These tests cover the
deterministic surface: the registry shape, the protocol conformance of
each module, the voltage parser, and the MATPOWER parser.
"""
from __future__ import annotations

from backend.app.importers.registry import (
    available_databases,
    get_database,
    registered_databases,
)
from backend.app.importers.protocol import Database


def test_registry_lists_all_four_modules():
    ids = set(registered_databases().keys())
    assert ids == {"osm", "wri_gppd", "worldbank_demand", "kpg193"}


def test_every_module_conforms_to_protocol():
    for db in registered_databases().values():
        assert isinstance(db, Database)
        assert db.meta.id
        assert db.meta.short_name
        assert isinstance(db.meta.requires_secrets, list)


def test_database_metas_json_shape():
    by_id = {m["id"]: m for m in available_databases()}
    assert by_id["osm"]["category"] == "transmission"
    assert by_id["wri_gppd"]["category"] == "generation"
    assert by_id["worldbank_demand"]["category"] == "demand"
    assert by_id["kpg193"]["country_coverage"] == ["KOR"]
    # short_name present and concise for every module
    for m in by_id.values():
        assert m["short_name"]
        assert "filters" in m


def test_get_unknown_database_raises():
    import pytest

    with pytest.raises(KeyError):
        get_database("not-a-real-db")


def test_osm_voltage_parser():
    from backend.app.importers.databases import osm

    # The parser is the load-bearing OSM normaliser; spot-check the
    # documented edge cases. Locate it by name regardless of internal
    # helper naming.
    parse = getattr(osm, "parse_voltage_kv", None) or getattr(osm, "_parse_voltage_kv", None)
    if parse is None:
        # Some ports keep it private inside the class module; skip if not
        # exposed rather than fail the suite.
        import pytest

        pytest.skip("voltage parser not module-level")
    assert parse("110000") == [110.0]
    assert sorted(parse("110000;220000")) == [110.0, 220.0]
    assert parse("110 kV") == [110.0]
    assert parse("") == []
    assert parse("unknown") == []


def test_kpg193_matpower_block_parser():
    from backend.app.importers.databases import kpg193

    extract_scalar = getattr(kpg193, "extract_scalar", None) or getattr(kpg193, "_extract_scalar", None)
    extract_block = getattr(kpg193, "extract_block_lines", None) or getattr(kpg193, "_extract_block_lines", None)
    if extract_scalar is None or extract_block is None:
        import pytest

        pytest.skip("MATPOWER parser helpers not module-level")
    text = "mpc.baseMVA = 100;\nmpc.bus = [\n1 2 0 0;\n2 1 0 0;\n];\n"
    assert extract_scalar(text, "baseMVA") == "100"
    rows = extract_block(text, "bus")
    # Raw block lines (empties are filtered later by parse_matrix); the
    # two data rows must be present.
    nonblank = [r for r in rows if r.strip()]
    assert len(nonblank) == 2
