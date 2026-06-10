"""Smoke tests for backend/app/config_provider.py.

Verifies that the three shared JSON configs load from backend/data/config/
(not the frontend directory the legacy code reached into), and that the
bundle's build_id is deterministic + flips when content changes.
"""
from __future__ import annotations

import json

from backend.app.config_provider import (
    ConfigBundle,
    _backend_config_dir,
    _build_id,
    load_bundle,
    reset_cache,
)


def test_bundle_loads_from_backend_data_config():
    reset_cache()
    bundle = load_bundle()
    assert isinstance(bundle, ConfigBundle)
    # All four required payloads are populated.
    assert bundle.schema, "schema is empty"
    assert "components" in bundle.schema
    assert bundle.standard_types, "standard_types is empty"
    assert bundle.network_import_policy, "network_import_policy is empty"
    # capabilities can legitimately be an empty list in test envs; just
    # confirm the field exists and is a list.
    assert isinstance(bundle.capabilities, list)
    # build_id has the version-then-hash shape.
    assert "-" in bundle.build_id
    assert len(bundle.build_id) > 12
    assert bundle.backend_version


def test_config_files_resolve_under_backend_data():
    config_dir = _backend_config_dir()
    # Path lives under backend/data/config (NOT frontend/.../src/config).
    assert config_dir.name == "config"
    assert config_dir.parent.name == "data"
    assert config_dir.parent.parent.name == "backend"
    # Only the curated rule table lives here as a file — the PyPSA schema
    # and standard-types are built live from the installed pypsa package
    # by `pypsa_schema_builder.py`, not read from JSON.
    assert (config_dir / "network_import_policy.json").exists()
    assert not (config_dir / "pypsa_schema.json").exists()
    assert not (config_dir / "pypsa_standard_types.json").exists()


def test_build_id_is_deterministic():
    schema = {"a": 1}
    types = {"line_types": []}
    policy = {"fields": []}
    a = _build_id(schema, types, policy, "1.0")
    b = _build_id(schema, types, policy, "1.0")
    assert a == b


def test_build_id_flips_on_content_change():
    base_schema = {"a": 1}
    types = {"line_types": []}
    policy = {"fields": []}
    a = _build_id(base_schema, types, policy, "1.0")
    b = _build_id({**base_schema, "b": 2}, types, policy, "1.0")
    assert a != b


def test_build_id_flips_on_version_change():
    schema = {"a": 1}
    types = {"line_types": []}
    policy = {"fields": []}
    a = _build_id(schema, types, policy, "1.0")
    b = _build_id(schema, types, policy, "1.1")
    assert a != b


def test_bundle_to_json_roundtrips():
    reset_cache()
    bundle = load_bundle()
    payload = bundle.to_json()
    # Must be JSON-serialisable as-is — this is what GET /api/config
    # will return.
    json.dumps(payload)
    assert set(payload.keys()) == {
        "schema",
        "standard_types",
        "network_import_policy",
        "capabilities",
        "simulation_defaults",
        "build_id",
        "backend_version",
    }


def test_legacy_loader_reads_same_live_schema():
    """``backend.pypsa.pypsa_schema.load_pypsa_schema`` and the bundle's
    ``schema`` field must agree — they share the same builder.
    """
    from backend.pypsa.pypsa_schema import load_pypsa_schema, reset_cache as _legacy_reset

    _legacy_reset()
    reset_cache()
    schema_via_legacy = load_pypsa_schema()
    schema_via_bundle = load_bundle().schema
    assert schema_via_legacy == schema_via_bundle
    # The schema carries provenance pointing at the installed package,
    # not a stale JSON file.
    assert schema_via_legacy["meta"]["source"] == "installed pypsa package"
    assert "pypsa_version" in schema_via_legacy["meta"]
