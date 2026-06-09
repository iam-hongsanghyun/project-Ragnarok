"""Tests for the backend plugin framework (backend/app/plugins.py + router).

Covers discovery + hard isolation, the unified hook runners (transform /
contribute / analyze), and the install (upload .zip) / uninstall lifecycle
including zip-slip rejection. Ragnarok ships NO plugins — they are installed at
runtime, so these tests build their own plugin zips / dirs.
"""
from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import UploadFile

from backend.app import model_store, plugins, session_store
from backend.app.routers import plugins as plugins_router

GOOD = "def transform(model, config):\n    return {'buses': [{'name': 'b'}]}\n"


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def _upload(data: bytes, name: str) -> UploadFile:
    return UploadFile(io.BytesIO(data), filename=name)


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


@pytest.fixture()
def _plugins_dir(tmp_path, monkeypatch):
    d = tmp_path / "plugins"
    d.mkdir()
    monkeypatch.setattr(plugins, "BACKEND_PLUGINS_DIR", d)
    monkeypatch.setattr(plugins, "PLUGIN_FILES_DIR", tmp_path / "plugin_files")
    plugins._REGISTRY = None
    return d


# ── Discovery + isolation ─────────────────────────────────────────────────────


def test_discover_skips_broken_and_keeps_good(tmp_path) -> None:
    _write_plugin(tmp_path, "good", GOOD)
    _write_plugin(tmp_path, "boom", "import this_module_does_not_exist_xyz\n")
    _write_plugin(tmp_path, "nohook", "X = 1\n")
    (tmp_path / "no-plugin-py").mkdir()
    (tmp_path / "no-plugin-py" / "manifest.json").write_text("{}", encoding="utf-8")

    found = plugins.discover(tmp_path)

    assert set(found) == {"good"}
    assert found["good"].has_transform and not found["good"].has_analyze


def test_discover_missing_dir_returns_empty(tmp_path) -> None:
    assert plugins.discover(tmp_path / "does-not-exist") == {}


# ── Hook runners ──────────────────────────────────────────────────────────────


def test_run_transform_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        plugins.run_transform("nope", {}, {})


def test_run_transform_bad_return_is_valueerror(_plugins_dir) -> None:
    _write_plugin(_plugins_dir, "bad", "def transform(model, config):\n    return 42\n")
    plugins._REGISTRY = None
    with pytest.raises(ValueError):
        plugins.run_transform("bad", {}, {})


def test_contribute_merges_sheets_and_constraints_into_session(_plugins_dir, tmp_path, monkeypatch) -> None:
    # Production goes through model_store (the active store); set up + assert via
    # the same facade so the test follows the configured backend (sqlite default).
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    model_store.save_model("default", {"buses": [{"name": "b0"}]}, filename="x.xlsx", scenario_name="")
    _write_plugin(
        _plugins_dir,
        "contrib",
        "def contribute(model, config):\n"
        "    return {'sheets': {'carriers': [{'name': 'wind'}]}, 'constraints': ['cf(\"wind\") <= 0.5']}\n",
    )
    plugins._REGISTRY = None

    plugins_router.contribute_plugin("contrib", plugins_router.TransformRequest(sessionId="default"))

    full = model_store.load_full_model("default") or {}
    assert any(r.get("name") == "wind" for r in full.get("carriers", []))
    assert full.get("RAGNAROK_CustomDSL")  # constraints landed in the DSL sheet


# ── Install / uninstall lifecycle ─────────────────────────────────────────────


def test_install_then_transform_into_session_then_uninstall(_plugins_dir, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    data = _make_zip(
        {
            "manifest.json": json.dumps(
                {"id": "mini", "name": "Mini", "kind": "backend", "config": {}}
            ),
            "plugin.py": "def transform(model, config):\n    return {'buses': [{'name': 'n1'}]}\n",
        }
    )

    manifest = asyncio.run(plugins_router.install_plugin(_upload(data, "mini.zip")))
    assert manifest["id"] == "mini" and manifest["hooks"]["transform"] is True
    assert (_plugins_dir / "mini" / "plugin.py").exists()
    assert any(p["id"] == "mini" for p in plugins_router.get_plugins()["plugins"])

    meta = plugins_router.transform_plugin("mini", plugins_router.TransformRequest(sessionId="default"))
    assert meta["componentCounts"].get("buses") == 1

    res = plugins_router.uninstall_plugin("mini")
    assert res["removed"] is True
    assert not (_plugins_dir / "mini").exists()
    assert not any(p["id"] == "mini" for p in plugins_router.get_plugins()["plugins"])


def test_install_rejects_zip_slip(_plugins_dir) -> None:
    data = _make_zip(
        {
            "manifest.json": json.dumps({"id": "evil", "name": "Evil"}),
            "plugin.py": "def transform(model, config):\n    return {}\n",
            "../escape.txt": "pwned",
        }
    )
    with pytest.raises(plugins_router.HTTPException) as exc:
        asyncio.run(plugins_router.install_plugin(_upload(data, "evil.zip")))
    assert exc.value.status_code == 400


def test_install_rejects_missing_plugin_py(_plugins_dir) -> None:
    data = _make_zip({"manifest.json": json.dumps({"id": "x", "name": "X"})})
    with pytest.raises(plugins_router.HTTPException) as exc:
        asyncio.run(plugins_router.install_plugin(_upload(data, "x.zip")))
    assert exc.value.status_code == 400


def test_uninstall_unknown_is_404(_plugins_dir) -> None:
    with pytest.raises(plugins_router.HTTPException) as exc:
        plugins_router.uninstall_plugin("ghost")
    assert exc.value.status_code == 404


# ── Per-plugin server-side file store ─────────────────────────────────────────


def test_file_store_upload_list_delete_and_inject(_plugins_dir) -> None:
    # A plugin whose transform surfaces the injected data dir + chosen filename,
    # proving the file lives server-side and is referenced by NAME only.
    _write_plugin(
        _plugins_dir,
        "fp",
        "import os\n"
        "def transform(model, config):\n"
        "    d = config.get('__plugin_data_dir__', '')\n"
        "    return {'buses': [{'name': os.path.basename(d)}], 'meta': [{'file': config.get('model_file', '')}]}\n",
    )
    plugins._REGISTRY = None

    saved = asyncio.run(plugins_router.upload_plugin_file("fp", _upload(b"xlsx-bytes", "model.xlsx")))
    assert saved["name"] == "model.xlsx" and saved["size"] == len(b"xlsx-bytes")
    assert (_plugins_dir.parent / "plugin_files" / "fp" / "model.xlsx").exists()
    assert [f["name"] for f in plugins_router.get_plugin_files("fp")["files"]] == ["model.xlsx"]

    # transform: framework injects the data dir; the model references the file by name.
    model = plugins.run_transform("fp", {}, {"model_file": "model.xlsx"})
    assert model["buses"][0]["name"] == "fp"          # data dir basename == plugin id
    assert model["meta"][0]["file"] == "model.xlsx"   # only a filename, never bytes

    plugins_router.delete_plugin_file("fp", "model.xlsx")
    assert plugins_router.get_plugin_files("fp")["files"] == []


def test_uninstall_removes_uploaded_files(_plugins_dir) -> None:
    _write_plugin(_plugins_dir, "fp2", GOOD)
    plugins._REGISTRY = None
    plugins.save_plugin_file("fp2", "data.bin", b"123")
    assert (_plugins_dir.parent / "plugin_files" / "fp2").is_dir()
    plugins_router.uninstall_plugin("fp2")
    assert not (_plugins_dir.parent / "plugin_files" / "fp2").exists()


# ── The shipped EXAMPLE backend plugin (installed from its zip) ───────────────


def test_install_example_dashboard_importer(_plugins_dir) -> None:
    # Install the example backend plugin and confirm it loads + its engine is
    # reachable (no model workbook → CLEAN domain error, not an ImportError).
    zip_path = Path(__file__).resolve().parents[2] / "example_plugins" / "zips" / "dashboard-importer.zip"
    if not zip_path.exists():
        pytest.skip("example dashboard-importer.zip not built")

    manifest = asyncio.run(plugins_router.install_plugin(_upload(zip_path.read_bytes(), "dashboard-importer.zip")))
    assert manifest["id"] == "dashboard-importer" and manifest["hooks"]["transform"] is True

    with pytest.raises(ValueError) as exc:
        plugins.run_transform("dashboard-importer", {}, {})
    assert "model" in str(exc.value).lower()  # "No model workbook specified…"
