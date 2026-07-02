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
from fastapi import HTTPException, UploadFile

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


def test_hooks_receive_a_copy_in_place_mutation_never_persists(_plugins_dir) -> None:
    """transform/contribute get a defensive copy of the session model: mutating
    the ``model`` argument in place (cells, rows, sheets) must not leak back to
    the caller's dict — the contract is return-value only, so a contribute
    plugin can't smuggle session changes past the merge."""
    _write_plugin(
        _plugins_dir,
        "mutator",
        "def transform(model, config):\n"
        "    model['buses'][0]['name'] = 'HACKED'\n"
        "    model['buses'].append({'name': 'smuggled'})\n"
        "    model['injected'] = [{'x': 1}]\n"
        "    return {'carriers': [{'name': 'ok'}]}\n"
        "def contribute(model, config):\n"
        "    model['buses'][0]['name'] = 'HACKED'\n"
        "    del model['buses'][0]\n"
        "    return {'sheets': {'extra': [{'name': 'e'}]}}\n",
    )
    plugins._REGISTRY = None

    current = {"buses": [{"name": "b1"}]}
    assert plugins.run_transform("mutator", current, {}) == {"carriers": [{"name": "ok"}]}
    assert current == {"buses": [{"name": "b1"}]}

    assert plugins.run_contribute("mutator", current, {}) == {"sheets": {"extra": [{"name": "e"}]}}
    assert current == {"buses": [{"name": "b1"}]}


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


def test_install_rejects_oversize_zip_with_413(_plugins_dir, monkeypatch) -> None:
    """The upload is read chunked and aborted past the limit — nothing installs."""
    monkeypatch.setattr(plugins, "MAX_PLUGIN_ZIP_BYTES", 1024)
    big = _make_zip({"manifest.json": json.dumps({"id": "big"}), "plugin.py": GOOD, "pad.bin": "x" * 10_000})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(plugins_router.install_plugin(_upload(big, "big.zip")))
    assert exc.value.status_code == 413
    assert not (plugins.BACKEND_PLUGINS_DIR / "big").exists()


def test_install_rejects_zip_bomb_before_extraction(_plugins_dir, monkeypatch) -> None:
    """A small archive that EXPANDS past the uncompressed cap is refused."""
    monkeypatch.setattr(plugins, "MAX_PLUGIN_UNZIPPED_BYTES", 1024)
    bomb = _make_zip({"manifest.json": json.dumps({"id": "bomb"}), "plugin.py": GOOD, "pad.bin": "0" * 10_000})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(plugins_router.install_plugin(_upload(bomb, "bomb.zip")))
    assert exc.value.status_code == 413
    assert not (plugins.BACKEND_PLUGINS_DIR / "bomb").exists()


def test_file_upload_rejects_oversize_with_413(_plugins_dir, monkeypatch) -> None:
    _write_plugin(_plugins_dir, "p1", GOOD)
    plugins._REGISTRY = None
    monkeypatch.setattr(plugins, "MAX_PLUGIN_FILE_BYTES", 1024)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(plugins_router.upload_plugin_file("p1", _upload(b"x" * 5000, "big.bin")))
    assert exc.value.status_code == 413
    assert plugins.list_plugin_files("p1") == []


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


# ── options() hook (on-demand dropdowns) ──────────────────────────────────────


def test_options_returns_rows_and_reports_capability(_plugins_dir) -> None:
    _write_plugin(
        _plugins_dir,
        "opt",
        "def transform(model, config):\n    return {}\n"
        "def options(name, config, ctx):\n"
        "    if name == '/scalars':\n        return ['a', 'b']\n"
        "    return [{'name': name, 'echo': config.get('x')}]\n",
    )
    plugins._REGISTRY = None

    assert plugins.get("opt").to_dict()["hooks"]["options"] is True
    # dict rows pass through; the form's `config` reaches the hook
    rows = plugins.run_options("opt", "/things", {"x": 7})
    assert rows == [{"name": "/things", "echo": 7}]
    # scalars are wrapped to {name: value} so the default column 'name' resolves
    assert plugins.run_options("opt", "/scalars", {}) == [{"name": "a"}, {"name": "b"}]


def test_options_router_shape_and_errors(_plugins_dir) -> None:
    _write_plugin(
        _plugins_dir,
        "opt2",
        "def transform(model, config):\n    return {}\n"
        "def options(name, config, ctx):\n    return [{'name': 'x'}]\n",
    )
    _write_plugin(_plugins_dir, "noopt", GOOD)  # transform only, no options
    plugins._REGISTRY = None

    out = plugins_router.options_plugin("opt2", plugins_router.OptionsRequest(name="/q"))
    assert out == {"name": "/q", "rows": [{"name": "x"}]}

    with pytest.raises(plugins_router.HTTPException) as missing:
        plugins_router.options_plugin("ghost", plugins_router.OptionsRequest(name="/q"))
    assert missing.value.status_code == 404

    with pytest.raises(plugins_router.HTTPException) as nohook:
        plugins_router.options_plugin("noopt", plugins_router.OptionsRequest(name="/q"))
    assert nohook.value.status_code == 400


def test_options_ctx_distinct_reads_session(_plugins_dir, tmp_path, monkeypatch) -> None:
    # The plugin answers a dropdown from the SESSION via ctx.distinct (generic,
    # SQL-backed) — Ragnarok owns no plugin-specific filter logic.
    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    model_store.save_model(
        "default",
        {"generators": [{"name": "g0", "carrier": "wind"}, {"name": "g1", "carrier": "gas"}]},
    )
    _write_plugin(
        _plugins_dir,
        "ctxopt",
        "def transform(model, config):\n    return {}\n"
        "def options(name, config, ctx):\n"
        "    return [{'name': c} for c in ctx.distinct('generators', 'carrier')]\n",
    )
    plugins._REGISTRY = None

    rows = plugins.run_options("ctxopt", "/carriers", {}, session_id="default")
    assert rows == [{"name": "gas"}, {"name": "wind"}]


def test_run_action_named_hook_contract(_plugins_dir) -> None:
    """run_action calls the named plugin.py function with the config (plus the
    injected scratch dir) and normalises {ok, message, config}. Reserved,
    private, and missing hook names are rejected as ValueError (clean 400)."""
    _write_plugin(
        _plugins_dir,
        "actor",
        "def transform(model, config):\n    return {}\n"
        "def fillTable(config):\n"
        "    assert '__plugin_data_dir__' in config\n"
        "    return {'ok': True, 'message': 'filled', 'config': {'rows': [{'generator': 'g1'}]}}\n"
        "def badReturn(config):\n    return 'nope'\n",
    )
    plugins._REGISTRY = None

    res = plugins.run_action("actor", "fillTable", {"x": 1})
    assert res == {"ok": True, "message": "filled", "config": {"rows": [{"generator": "g1"}]}}

    for bad in ("transform", "options", "_private", "", "missing"):
        with pytest.raises(ValueError):
            plugins.run_action("actor", bad, {})
    with pytest.raises(ValueError):
        plugins.run_action("actor", "badReturn", {})
    with pytest.raises(KeyError):
        plugins.run_action("ghost", "fillTable", {})


# ── The shipped EXAMPLE backend plugin (installed from its zip) ───────────────


def test_install_example_dashboard_importer(_plugins_dir) -> None:
    # Install the example backend plugin and confirm it loads + its engine is
    # reachable (no model workbook → CLEAN domain error, not an ImportError).
    zip_path = Path(__file__).resolve().parents[2] / "example_plugins" / "zips" / "dashboard-importer.zip"
    if not zip_path.exists():
        pytest.skip("example dashboard-importer.zip not built")

    manifest = asyncio.run(plugins_router.install_plugin(_upload(zip_path.read_bytes(), "dashboard-importer.zip")))
    assert manifest["id"] == "dashboard-importer" and manifest["hooks"]["transform"] is True
    assert manifest["hooks"]["options"] is True  # serves its own dropdowns on demand
    assert manifest["hooks"]["analyze"] is True  # Output tab: capacity by year

    # analyze degrades to an actionable note (never raises) when no model is picked.
    note = plugins.run_analyze("dashboard-importer", {}, {})
    assert "note" in note

    with pytest.raises(ValueError) as exc:
        plugins.run_transform("dashboard-importer", {}, {})
    assert "model" in str(exc.value).lower()  # "No model workbook specified…"

    # An unknown option-set returns [] cleanly (the dropdown shows static options).
    assert plugins.run_options("dashboard-importer", "/nope", {}) == []


def test_dashboard_lib_loads_under_plugin_alias_not_bare_name(_plugins_dir) -> None:
    """The importer's bundled dashboard_lib registers in sys.modules under a
    plugin-unique alias — never as bare 'dashboard_lib' (two installed plugins
    shipping a same-named lib would silently swap each other's code) — and the
    loader never mutates sys.path."""
    import sys

    pytest.importorskip("pandas")
    pytest.importorskip("pypsa")

    zip_path = _EXAMPLES / "zips" / "dashboard-importer.zip"
    if not zip_path.exists():
        pytest.skip("example dashboard-importer.zip not built")
    asyncio.run(plugins_router.install_plugin(_upload(zip_path.read_bytes(), "dashboard-importer.zip")))
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()

    path_before = list(sys.path)
    settings_mod = engine._lib("settings")
    # A submodule with a package-relative import — must resolve inside the alias.
    redist_mod = engine._lib("demand_redistribution")
    assert sys.path == path_before
    assert "dashboard_lib" not in sys.modules
    assert engine._LIB_ALIAS in sys.modules
    assert settings_mod.__name__ == f"{engine._LIB_ALIAS}.settings"
    assert redist_mod.region_mod.__name__ == f"{engine._LIB_ALIAS}.region"


_EXAMPLES = Path(__file__).resolve().parents[2] / "example_plugins"


def _install_example(zip_name: str) -> dict:
    zip_path = _EXAMPLES / "zips" / zip_name
    if not zip_path.exists():
        pytest.skip(f"example {zip_name} not built")
    return asyncio.run(plugins_router.install_plugin(_upload(zip_path.read_bytes(), zip_name)))


def test_region_analyzer_analyzes_stored_run(_plugins_dir, tmp_path, monkeypatch) -> None:
    """End-to-end: store a tiny solved run, then the backend region analyzer
    aggregates it into chart specs — including the flow MAP with located nodes
    and a net-flow edge. Numbers are checked against hand computation:
    energy = sum(max(p, 0)) * weight, net flow = signed sum of p0 * weight."""
    from backend.app import run_store

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")

    manifest = _install_example("ragnarok-region-analyzer.zip")
    assert manifest["id"] == "ragnarok-region-analyzer"
    assert manifest["hooks"]["analyze"] is True and manifest["hooks"]["options"] is True
    # Its analyze is expensive (reads a full year of dispatch) → not auto-run.
    assert manifest["analyzeOnDemand"] is True

    # No stored runs yet → actionable note, never an exception.
    note = plugins.run_analyze("ragnarok-region-analyzer", {}, {})
    assert "note" in note and "stored" in note["note"].lower()

    # Two generators on buses in different provinces (embedded KR lookup:
    # bus 9 → 서울특별시, bus 194 → 제주특별자치도) + one inter-region line.
    model = {
        "generators": [
            {"name": "g1", "bus": "9", "carrier": "coal", "p_nom": 500},
            {"name": "g2", "bus": "194", "carrier": "solar", "p_nom": 300},
        ],
        "lines": [{"name": "l1", "bus0": "9", "bus1": "194", "s_nom": 100}],
    }
    result = {
        "outputs": {
            "static": {},
            "series": {
                "generators-p": [
                    {"snapshot": "2024-01-01T00:00:00", "g1": 100.0, "g2": 50.0},
                    {"snapshot": "2024-01-01T01:00:00", "g1": 120.0, "g2": 60.0},
                ],
                "lines-p0": [
                    {"snapshot": "2024-01-01T00:00:00", "l1": 30.0},
                    {"snapshot": "2024-01-01T01:00:00", "l1": -10.0},
                ],
            },
        },
    }
    meta = run_store.store_run(model, {}, {"snapshotWeight": 2, "filename": "tiny.xlsx"}, result)
    assert meta is not None

    out = plugins.run_analyze("ragnarok-region-analyzer", {}, {})
    assert "note" not in out, out.get("note")
    # Energy: g1 (100+120)*2 = 440 MWh, g2 (50+60)*2 = 220 MWh → 0.66 GWh total.
    assert out["Total generation (GWh)"] == pytest.approx(0.66)

    fmap = out["Inter-region flow map"]
    assert fmap["kind"] == "map"
    assert {n["id"] for n in fmap["nodes"]} == {"서울특별시", "제주특별자치도"}
    mixes = {n["id"]: {s["label"]: s["value"] for s in n["mix"]} for n in fmap["nodes"]}
    assert mixes["서울특별시"] == {"coal": pytest.approx(0.44)}
    assert mixes["제주특별자치도"] == {"solar": pytest.approx(0.22)}
    # Net flow (30 - 10) * 2 = 40 MWh = 0.04 GWh, direction 서울 → 제주.
    assert len(fmap["edges"]) == 1
    edge = fmap["edges"][0]
    assert (edge["from"], edge["to"]) == ("서울특별시", "제주특별자치도")
    assert edge["value"] == pytest.approx(0.04)

    donut = out["Carrier mix (system)"]
    assert donut["kind"] == "donut"
    assert {s["label"]: s["value"] for s in donut["slices"]} == {
        "coal": pytest.approx(0.44),
        "solar": pytest.approx(0.22),
    }

    # Capacity table uses the input p_nom when no p_nom_opt was solved.
    cap = {r["region"]: r["Total_MW"] for r in out["Capacity by region — table (MW)"]}
    assert cap == {"서울특별시": 500, "제주특별자치도": 300}

    # The /runs dropdown lists the stored run, newest first.
    rows = plugins.run_options("ragnarok-region-analyzer", "/runs", {})
    assert rows and rows[0]["name"] == meta["name"]


def test_region_analyzer_groups_new_bus_via_model_province(_plugins_dir, tmp_path, monkeypatch) -> None:
    """A bus OUTSIDE the hardcoded reference grid (1..204) is grouped by its OWN
    ``Province`` column from the run's buses sheet — not left unmapped.

    Regression: the analyzer previously mapped buses only via the embedded
    BUS_PROVINCE dict, so any new bus (e.g. "999", or a plant-named bus) fell to
    per-bus / UNMAPPED even when it carried a perfectly good province.
    """
    from backend.app import run_store

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    _install_example("ragnarok-region-analyzer.zip")

    model = {
        "buses": [{"name": "999", "Province": "강원특별자치도", "x": 128.2, "y": 37.8}],
        "generators": [{"name": "g1", "bus": "999", "carrier": "wind", "p_nom": 200}],
    }
    result = {
        "outputs": {
            "static": {},
            "series": {
                "generators-p": [
                    {"snapshot": "2024-01-01T00:00:00", "g1": 100.0},
                    {"snapshot": "2024-01-01T01:00:00", "g1": 120.0},
                ],
            },
        },
    }
    run_store.store_run(model, {}, {"snapshotWeight": 1, "filename": "new_bus.xlsx"}, result)

    cfg = {
        "aggregate_by_region": True,
        "region_column": "group1",
        "province_mapping": [{"short": "강원", "official": "강원특별자치도", "group1": "East"}],
    }
    out = plugins.run_analyze("ragnarok-region-analyzer", {}, cfg)
    assert "note" not in out, out.get("note")
    # Bus 999's province → group1 "East"; never per-bus / unmapped.
    regions = {r["region"] for r in out["Generation by region — table (GWh)"]}
    assert regions == {"East"}
    assert "UNMAPPED" not in out["Settings"]


def test_region_analyzer_curtailment_by_region(_plugins_dir, tmp_path, monkeypatch) -> None:
    """Per-generator curtailment folds onto each generator's region, with a
    total and a per-region table."""
    from backend.app import run_store

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    _install_example("ragnarok-region-analyzer.zip")

    model = {
        "generators": [
            {"name": "g1", "bus": "9", "carrier": "solar", "p_nom": 500},   # 서울특별시
            {"name": "g2", "bus": "194", "carrier": "wind", "p_nom": 300},  # 제주특별자치도
        ],
    }
    result = {
        "outputs": {
            "static": {},
            "series": {
                "generators-p": [
                    {"snapshot": "2024-01-01T00:00:00", "g1": 100.0, "g2": 50.0},
                    {"snapshot": "2024-01-01T01:00:00", "g1": 120.0, "g2": 60.0},
                ],
            },
        },
        # Pre-computed per-generator energy + curtailment (the run store passes
        # an existing generatorEnergy through untouched).
        "generatorEnergy": [
            {"name": "g1", "value": 440.0, "carrier": "solar", "curtailmentMwh": 60.0},
            {"name": "g2", "value": 220.0, "carrier": "wind", "curtailmentMwh": 40.0},
        ],
    }
    run_store.store_run(model, {}, {"snapshotWeight": 2}, result)

    out = plugins.run_analyze("ragnarok-region-analyzer", {}, {})
    assert "note" not in out, out.get("note")
    # 60 + 40 = 100 MWh = 0.1 GWh, split onto the two regions.
    assert out["Total curtailment (GWh)"] == pytest.approx(0.1)
    cur = {r["region"]: r["curtailment_GWh"] for r in out["Curtailment by region — table (GWh)"]}
    assert cur == {"서울특별시": pytest.approx(0.06), "제주특별자치도": pytest.approx(0.04)}
    assert out["Curtailment by region"]["kind"] == "bar"


def test_dashboard_manifest_actions_all_have_server_hooks(_plugins_dir) -> None:
    """Every `action` field's hook must be runnable server-side: transform/
    contribute (build path) or a same-named function exported by plugin.py
    (run via POST /action). v3.1 shipped fillReallocation/clearReallocation
    WITHOUT the plugin.py functions, dead-ending in a "no server-side hook"
    toast — this pins that every declared hook actually exists."""
    manifest = _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    actions = {k: f for k, f in manifest["config"].items() if f.get("type") == "action"}
    assert {"fill_reallocation", "clear_reallocation"} <= set(actions)
    for key, field in actions.items():
        hook = field.get("hook")
        assert hook in ("transform", "contribute") or callable(getattr(plugin.module, hook, None)), (
            f"action {key!r} declares hook {hook!r} with no server-side implementation"
        )


def test_dashboard_fill_and_clear_reallocation_actions(_plugins_dir, tmp_path) -> None:
    """'Fill table from carriers' (the working frontend plugin's workflow, run
    server-side): adds every replaceable plant of the checked carriers to the
    generator_replacements table via a config patch, keeping existing picks.
    'Clear table' empties it."""
    pd = pytest.importorskip("pandas")

    _install_example("dashboard-importer.zip")

    xlsx = tmp_path / "fleet.xlsx"
    pd.DataFrame(
        [
            {"name": "coal_new", "carrier": "coal", "p_nom": 100, "build_year": 2030, "close_year": 2060},
            {"name": "coal_old", "carrier": "coal", "p_nom": 400, "build_year": 2010, "close_year": 2060},
            {"name": "gas_new", "carrier": "gas", "p_nom": 300, "build_year": 2030, "close_year": 2060},
        ]
    ).to_excel(xlsx, sheet_name="generators", index=False)

    cfg = {
        "model_path": str(xlsx),
        "target_year": "2035",
        "replace_generators": True,
        "replace_carriers": ["coal"],
        "replace_build_year": 2025,
        # An existing manual pick must be kept (and not duplicated).
        "generator_replacements": [{"generator": "gas_new"}],
    }
    res = plugins.run_action("dashboard-importer", "fillReallocation", cfg)
    assert res["ok"], res["message"]
    rows = res["config"]["generator_replacements"]
    # Existing picks are kept verbatim; newly-added plants carry the solar/wind
    # split frozen at the current settings (default 50/50 of the plant's p_nom).
    assert rows == [
        {"generator": "gas_new"},
        {"generator": "coal_new", "total_mw": 100.0, "solar_mw": 50.0, "wind_mw": 50.0},
    ]  # coal_old filtered out (built before the replacement base year)

    # No carriers checked → actionable error, no patch applied.
    res = plugins.run_action("dashboard-importer", "fillReallocation", {**cfg, "replace_carriers": []})
    assert res["ok"] is False and "carrier" in res["message"].lower()

    res = plugins.run_action("dashboard-importer", "clearReallocation", cfg)
    assert res["ok"] and res["config"]["generator_replacements"] == []

    # Reserved/unknown hooks are rejected cleanly (400 at the router).
    with pytest.raises(ValueError):
        plugins.run_action("dashboard-importer", "transform", cfg)
    with pytest.raises(ValueError):
        plugins.run_action("dashboard-importer", "nope", cfg)


def test_dashboard_bulk_replacement_plan_payload(_plugins_dir, tmp_path) -> None:
    """Bulk mode (`replace_all_carriers`) selects every checked-carrier plant
    passing the base-year filter — no table rows — and splits by the fixed
    shares: solar = C·60%, wind = C·40%."""
    pd = pytest.importorskip("pandas")

    _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()

    xlsx = tmp_path / "fleet.xlsx"
    pd.DataFrame(
        [
            {"name": "coal_new", "carrier": "coal", "p_nom": 100, "build_year": 2030, "close_year": 2060},
            {"name": "coal_new2", "carrier": "coal", "p_nom": 200, "build_year": 2031, "close_year": 2060},
            {"name": "coal_old", "carrier": "coal", "p_nom": 400, "build_year": 2010, "close_year": 2060},
            {"name": "gas_new", "carrier": "gas", "p_nom": 300, "build_year": 2030, "close_year": 2060},
        ]
    ).to_excel(xlsx, sheet_name="generators", index=False)

    cfg = {
        "model_path": str(xlsx),
        "target_year": "2035",
        "replace_generators": True,
        # The transient probe flag the fill button sets — bulk plan of every
        # checked-carrier plant. The stored config never carries it.
        "replace_all_carriers": True,
        "replace_carriers": ["coal"],
        "replace_build_year": 2025,
        "replace_solar_pct": 60,
        "replace_wind_pct": 40,
        "generator_replacements": [],
    }
    rows = {r["generator"]: r for r in engine.replacement_plan_payload(cfg)}
    # gas_new (carrier) and coal_old (build_year < 2025) are excluded.
    assert set(rows) == {"coal_new", "coal_new2"}
    assert rows["coal_new"]["solar_mw"] == pytest.approx(60.0)
    assert rows["coal_new"]["wind_mw"] == pytest.approx(40.0)
    assert rows["coal_new2"]["solar_mw"] == pytest.approx(120.0)
    assert rows["coal_new2"]["wind_mw"] == pytest.approx(80.0)

    # No probe flag + empty table → nothing planned (build replaces table rows only).
    assert engine.replacement_plan_payload({**cfg, "replace_all_carriers": False}) == []


def test_dashboard_follow_mode_uses_yearly_additions_ratio(_plugins_dir, tmp_path) -> None:
    """Follow mode splits by the solar:wind capacity ADDED in each plant's build
    year — A_solar(y) : A_wind(y) — falling back to the latest earlier year with
    nonzero additions. Carrier matching is case-insensitive ('Solar' == 'solar')."""
    pd = pytest.importorskip("pandas")

    _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()

    xlsx = tmp_path / "fleet.xlsx"
    pd.DataFrame(
        [
            # 2030 additions: solar 300, wind 100 → 75:25. Mixed-case carriers on
            # purpose — they must still count as solar/wind additions.
            {"name": "s30", "carrier": "Solar", "p_nom": 300, "build_year": 2030, "close_year": 2060},
            {"name": "w30", "carrier": "Wind", "p_nom": 100, "build_year": 2030, "close_year": 2060},
            {"name": "coalA", "carrier": "coal", "p_nom": 100, "build_year": 2030, "close_year": 2060},
            # 2031 has NO solar/wind additions → coalB follows 2030's 75:25.
            {"name": "coalB", "carrier": "coal", "p_nom": 200, "build_year": 2031, "close_year": 2060},
        ]
    ).to_excel(xlsx, sheet_name="generators", index=False)

    cfg = {
        "model_path": str(xlsx),
        "target_year": "2035",
        "replace_generators": True,
        "replace_all_carriers": True,
        "replace_carriers": ["coal"],
        "replace_follow": True,
        # Fixed shares must be IGNORED in follow mode.
        "replace_solar_pct": 10,
        "replace_wind_pct": 90,
        "generator_replacements": [],
    }
    rows = {r["generator"]: r for r in engine.replacement_plan_payload(cfg)}
    assert set(rows) == {"coalA", "coalB"}
    assert rows["coalA"]["solar_mw"] == pytest.approx(75.0)  # 100 · 300/400
    assert rows["coalA"]["wind_mw"] == pytest.approx(25.0)
    assert rows["coalB"]["solar_mw"] == pytest.approx(150.0)  # fallback to 2030 ratio
    assert rows["coalB"]["wind_mw"] == pytest.approx(50.0)

    # Follow OFF → the user's fixed shares apply (direct % of capacity).
    fixed = {r["generator"]: r for r in engine.replacement_plan_payload({**cfg, "replace_follow": False})}
    assert fixed["coalA"]["solar_mw"] == pytest.approx(10.0)
    assert fixed["coalA"]["wind_mw"] == pytest.approx(90.0)


def test_dashboard_carbon_price_folds_into_marginal_cost(_plugins_dir) -> None:
    """Carbon price reaches the solve as a marginal-cost adder baked into the
    built model (Ragnarok runs no plugin code in-solve): for carrier c,
    mc += intensity_c[kg/MWh] x price[per tCO2] x fx[model-currency per
    carbon-price-currency] / 1000 — no currency is hardcoded. Zero-intensity
    carriers and disabled toggle leave costs untouched."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pypsa")
    import pypsa

    _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()
    settings_mod = engine._lib("settings")

    def _network() -> "pypsa.Network":
        n = pypsa.Network()
        n.add("Bus", "B1")
        n.add("Generator", "coal1", bus="B1", carrier="coal", p_nom=100, marginal_cost=50.0)
        n.add("Generator", "gas1", bus="B1", carrier="gas", p_nom=100, marginal_cost=80.0)
        n.add("Generator", "wind1", bus="B1", carrier="wind", p_nom=100, marginal_cost=0.0)
        return n

    def _dashboard(enabled: bool) -> object:
        settings = settings_mod.Settings(
            model="",
            base_year=2024,
            target_year=2030,
            target_load_twh=0.0,
            snapshot_start="01/01/2030 00:00",
            snapshot_length=24,
            carbonprice=enabled,
            carbonprice_scenario="NGFS",
            currency_exchange=1000.0,
        )
        return settings_mod.Dashboard(
            settings=settings,
            cc_rules=None,
            cf_constraints=pd.DataFrame(),
            carbon_price_usd=30.0,
            emission_intensity=pd.Series({"coal": 900.0, "gas": 400.0, "wind": 0.0}),
        )

    network = _network()
    engine._apply_carbon_price_marginal_cost(network, _dashboard(enabled=True))
    gens = network.generators
    # coal: 900 kg/MWh x 30 per tCO2 x 1000 fx / 1000 = 27000 per MWh
    assert gens.at["coal1", "marginal_cost"] == pytest.approx(50.0 + 27_000.0)
    assert gens.at["gas1", "marginal_cost"] == pytest.approx(80.0 + 12_000.0)
    assert gens.at["wind1", "marginal_cost"] == pytest.approx(0.0)  # zero intensity

    untouched = _network()
    engine._apply_carbon_price_marginal_cost(untouched, _dashboard(enabled=False))
    assert untouched.generators.at["coal1", "marginal_cost"] == pytest.approx(50.0)


def test_dashboard_lib_alias_purged_on_engine_reload(_plugins_dir) -> None:
    """Re-executing pipeline.py (what a reinstall / registry refresh triggers
    via the plugin.py reload) must drop the previous install's lib modules from
    sys.modules, so changed vendored files take effect without a backend
    restart."""
    import importlib.util
    import sys

    pytest.importorskip("pandas")
    pytest.importorskip("pypsa")

    _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()
    first = engine._lib("settings")
    assert engine._LIB_ALIAS in sys.modules

    # Simulate the reinstall path: a fresh exec of pipeline.py.
    spec = importlib.util.spec_from_file_location("_test_engine_reload", plugin.directory / "pipeline.py")
    assert spec is not None and spec.loader is not None
    engine2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine2)

    assert engine2._LIB_ALIAS == engine._LIB_ALIAS
    assert engine._LIB_ALIAS not in sys.modules  # purged at exec time
    second = engine2._lib("settings")
    assert second is not first  # re-imported from disk, not served stale


def test_dashboard_bulk_replacement_applies_to_network(_plugins_dir) -> None:
    """Build-time bulk replacement on a real network: with carriers={coal} and a
    60/40 split, each coal plant of capacity C is removed and replaced by
    C·0.6 solar + C·0.4 wind at the same bus; gas is untouched."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pypsa")
    import pypsa

    _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()
    settings_mod = engine._lib("settings")
    gen_replace_mod = engine._lib("generator_replacement")

    network = pypsa.Network()
    network.add("Bus", "B1")
    network.add("Generator", "coal1", bus="B1", carrier="coal", p_nom=100, build_year=2030)
    network.add("Generator", "gas1", bus="B1", carrier="gas", p_nom=300, build_year=2030)

    settings = settings_mod.Settings(
        model="",
        base_year=2024,
        target_year=2035,
        target_load_twh=0.0,
        snapshot_start="01/01/2035 00:00",
        snapshot_length=24,
        replace_generators=True,
        replace_all_carriers=True,
        replace_carriers=("coal",),
        replace_solar_pct=60.0,
        replace_wind_pct=40.0,
    )
    dashboard = settings_mod.Dashboard(
        settings=settings, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0
    )
    gen_replace_mod.replace_generators(network, dashboard)

    gens = network.generators
    assert "coal1" not in gens.index and "gas1" in gens.index
    assert gens.at["coal1_solar_2030", "p_nom"] == pytest.approx(60.0)
    assert gens.at["coal1_wind_2030", "p_nom"] == pytest.approx(40.0)
    assert gens.at["coal1_solar_2030", "bus"] == "B1"
    assert gens.at["coal1_wind_2030", "carrier"] == "wind"

    # Follow mode on a fresh network: 2030 additions Solar 300 / Wind 100 (mixed
    # case on purpose) → each replaced coal plant splits 75:25, fixed shares ignored.
    network2 = pypsa.Network()
    network2.add("Bus", "B1")
    network2.add("Generator", "s30", bus="B1", carrier="Solar", p_nom=300, build_year=2030)
    network2.add("Generator", "w30", bus="B1", carrier="Wind", p_nom=100, build_year=2030)
    network2.add("Generator", "coal1", bus="B1", carrier="coal", p_nom=100, build_year=2030)
    # 2031 has no solar/wind additions → falls back to 2030's ratio.
    network2.add("Generator", "coal2", bus="B1", carrier="coal", p_nom=200, build_year=2031)

    follow_settings = settings_mod.Settings(
        model="",
        base_year=2024,
        target_year=2035,
        target_load_twh=0.0,
        snapshot_start="01/01/2035 00:00",
        snapshot_length=24,
        replace_generators=True,
        replace_all_carriers=True,
        replace_carriers=("coal",),
        replace_follow=True,
        replace_solar_pct=10.0,
        replace_wind_pct=90.0,
    )
    dashboard2 = settings_mod.Dashboard(
        settings=follow_settings, cc_rules=None, cf_constraints=pd.DataFrame(), carbon_price_usd=0.0
    )
    gen_replace_mod.replace_generators(network2, dashboard2)

    gens2 = network2.generators
    assert gens2.at["coal1_solar_2030", "p_nom"] == pytest.approx(75.0)  # 100 · 300/400
    assert gens2.at["coal1_wind_2030", "p_nom"] == pytest.approx(25.0)
    assert gens2.at["coal2_solar_2031", "p_nom"] == pytest.approx(150.0)  # 2030 fallback
    assert gens2.at["coal2_wind_2031", "p_nom"] == pytest.approx(50.0)


def test_dashboard_capacity_spans_from_earliest_build_year(_plugins_dir, tmp_path) -> None:
    """The capacity-by-year output must cover the whole fleet history
    (build_year ≤ Y < close_year), not start at the GUI base year — with
    base_year == target_year it previously collapsed to a single year."""
    pd = pytest.importorskip("pandas")

    _install_example("dashboard-importer.zip")
    plugin = plugins.get("dashboard-importer")
    assert plugin is not None
    engine = plugin.module._load_engine()

    xlsx = tmp_path / "fleet.xlsx"
    pd.DataFrame(
        [
            {"name": "old", "carrier": "coal", "p_nom": 100, "build_year": 2025, "close_year": 2040},
            {"name": "always", "carrier": "hydro", "p_nom": 50},
        ]
    ).to_excel(xlsx, sheet_name="generators", index=False)

    rows = engine._capacity_by_carrier_year(str(xlsx), 2038)
    assert rows is not None
    years = [r["year"] for r in rows]
    assert years[0] == 2025 and years[-1] == 2040  # earliest build → latest close
    by_year = {r["year"]: r["total"] for r in rows}
    assert by_year[2025] == 150  # both active
    assert by_year[2039] == 150  # close_year 2040 exclusive: still active in 2039
    assert by_year[2040] == 50  # coal closed (Y < close_year), hydro never closes


# ── Contract v2 (X6): multi-run input + composite layout output ──────────────

MULTIRUN = """
def analyze(result, config, runs):
    return {
        "count": {"kind": "table", "rows": [{"runs": len(runs)}]},
        "names": {"kind": "table", "rows": [{"name": r["name"]} for r in runs]},
        "layout": {"rows": [["count", "names"]]},
    }
"""

LAYOUT_BAD = """
def analyze(result, config):
    return {"a": 1, "layout": {"rows": [["a", "missing_output"]]}}
"""


def test_multirun_plugin_receives_runs_and_layout_passes(_plugins_dir) -> None:
    _write_plugin(_plugins_dir, "multi", MULTIRUN, {"multiRun": True, "contractVersion": 2})
    meta = plugins.get("multi").to_dict()
    assert meta["multiRun"] is True and meta["contractVersion"] == 2
    out = plugins.run_analyze("multi", {}, {}, runs=[
        {"name": "run_a", "analytics": {}}, {"name": "run_b", "analytics": {}},
    ])
    assert out["count"]["rows"] == [{"runs": 2}]
    assert [r["name"] for r in out["names"]["rows"]] == ["run_a", "run_b"]
    assert out["layout"]["rows"] == [["count", "names"]]


def test_multirun_plugin_gets_empty_list_when_no_runs(_plugins_dir) -> None:
    _write_plugin(_plugins_dir, "multi", MULTIRUN, {"multiRun": True})
    out = plugins.run_analyze("multi", {}, {})
    assert out["count"]["rows"] == [{"runs": 0}]


SINGLE_ANALYZE = "def analyze(result, config):\n    return {'ok': {'kind': 'table', 'rows': []}}\n"


def test_single_run_plugin_unchanged_and_ignores_runs(_plugins_dir) -> None:
    _write_plugin(_plugins_dir, "single", SINGLE_ANALYZE)
    meta = plugins.get("single").to_dict()
    assert meta["multiRun"] is False and meta["contractVersion"] == 1
    # v1 plugins keep the two-arg call even when the endpoint resolves runs.
    plugins.run_analyze("single", {"x": 1}, {}, runs=[{"name": "r", "analytics": {}}])


def test_layout_referencing_unknown_output_is_rejected(_plugins_dir) -> None:
    _write_plugin(_plugins_dir, "badlayout", LAYOUT_BAD)
    with pytest.raises(ValueError, match="unknown output"):
        plugins.run_analyze("badlayout", {}, {})
