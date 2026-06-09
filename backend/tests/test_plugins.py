"""Tests for the backend plugin framework (backend/app/plugins.py + router).

Covers discovery, hard isolation (a broken plugin can't break the registry or
the app), the build/analyze runners, and the HTTP endpoints (list / build into
session / errors).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app import plugins, session_store
from backend.app.routers import plugins as plugins_router


def _write_plugin(root: Path, pid: str, plugin_py: str, manifest: dict | None = None) -> None:
    d = root / pid
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"id": pid, "name": pid, **(manifest or {})}), encoding="utf-8")
    (d / "plugin.py").write_text(plugin_py, encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_registry():
    plugins._REGISTRY = None
    yield
    plugins._REGISTRY = None


def test_discover_skips_broken_and_keeps_good(tmp_path) -> None:
    # A good plugin, one that explodes on import, one with no hook, one missing
    # plugin.py. Discovery must return only the good one and never raise.
    _write_plugin(tmp_path, "good", "def build(config):\n    return {'buses': [{'name': 'b'}]}\n")
    _write_plugin(tmp_path, "boom", "import this_module_does_not_exist_xyz\n")
    _write_plugin(tmp_path, "nohook", "X = 1\n")
    (tmp_path / "no-plugin-py").mkdir()
    (tmp_path / "no-plugin-py" / "manifest.json").write_text("{}", encoding="utf-8")

    found = plugins.discover(tmp_path)

    assert set(found) == {"good"}
    assert found["good"].has_build and not found["good"].has_analyze


def test_discover_missing_dir_returns_empty(tmp_path) -> None:
    # Isolation: no plugins dir at all -> empty, no error (app still starts).
    assert plugins.discover(tmp_path / "does-not-exist") == {}


def test_reference_demo_plugin_builds_valid_model() -> None:
    # The shipped reference plugin builds via the bundled PyPSA source.
    reg = plugins.discover()
    assert "demo-network-builder" in reg
    model = plugins.run_build("demo-network-builder", {"buses": 2, "snapshots": 6, "peak_load_mw": 120})
    assert len(model["buses"]) == 2
    assert len(model["snapshots"]) == 6
    assert len(model["generators"]) == 2
    assert set(model["loads-p_set"][0]) == {"snapshot", "load0", "load1"}


def test_run_build_unknown_plugin_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        plugins.run_build("nope", {})


def test_run_build_bad_return_is_valueerror(tmp_path, monkeypatch) -> None:
    _write_plugin(tmp_path, "bad", "def build(config):\n    return 42\n")
    monkeypatch.setattr(plugins, "BACKEND_PLUGINS_DIR", tmp_path)
    plugins._REGISTRY = None
    with pytest.raises(ValueError):
        plugins.run_build("bad", {})


def test_router_lists_and_builds_into_session(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    listed = plugins_router.get_plugins()["plugins"]
    assert any(p["id"] == "demo-network-builder" and p["kind"] == "backend" for p in listed)

    body = plugins_router.BuildRequest(config={"buses": 1, "snapshots": 4}, sessionId="default")
    meta = plugins_router.build_plugin("demo-network-builder", body)
    assert meta["componentCounts"].get("buses") == 1
    assert session_store.get_meta("default") is not None


def test_router_build_unknown_is_404() -> None:
    body = plugins_router.BuildRequest(config={})
    with pytest.raises(plugins_router.HTTPException) as exc:
        plugins_router.build_plugin("nope", body)
    assert exc.value.status_code == 404
