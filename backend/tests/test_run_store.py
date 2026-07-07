"""Tests for the server-side run store (backend/app/run_store.py).

Exercises the full lifecycle — store → list → get → xlsx → delete — against a
temporary RUNS_DIR so nothing is written into the real backend/data/runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import run_store


@pytest.fixture()
def _runs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point RUNS_DIR at a throwaway directory for the duration of a test."""
    target = tmp_path / "runs"
    monkeypatch.setattr(run_store, "RUNS_DIR", target)
    return target


def _sample_result() -> dict:
    return {
        "summary": [
            {"label": "Total cost", "value": "1000"},
            {"label": "Generation", "value": "500"},
            {"label": "Capacity", "value": "200"},
            {"label": "Avg price", "value": "42"},
            {"label": "Emissions", "value": "7"},
        ],
        "runMeta": {"componentCounts": {"generators": 3, "buses": 2}},
        "carrierMix": [
            {"label": "Wind", "value": 100.0, "color": "#0a0"},
            {"label": "Gas", "value": 50.0, "color": "#a00"},
        ],
        "pathway": {
            "enabled": True,
            "periods": [2030, 2040],
            "selectedPeriod": 2030,
            "summaries": [{"period": 2030, "totalDispatch": 1.0}],
            "snapshotMappingMode": "repeat_all_snapshots",
        },
        "rolling": {
            "enabled": False,
            "horizonSnapshots": 24,
            "overlapSnapshots": 6,
            "windowCount": 0,
            "windows": [],
        },
        "outputs": {
            "static": {
                "generators": {
                    "wind": {"p_nom_opt": 100.0},
                    "gas": {"p_nom_opt": 50.0},
                },
            },
            "series": {
                "generators-p": [
                    {"snapshot": "2025-01-01T00:00:00", "wind": 10.0, "gas": 5.0},
                    {"snapshot": "2025-01-01T01:00:00", "wind": 12.0, "gas": 3.0},
                ],
            },
        },
    }


def test_run_store_lifecycle(_runs_dir: Path) -> None:
    model = {"buses": [{"name": "n1"}, {"name": "n2"}], "generators": [{"name": "wind"}]}
    scenario = {"label": "Test scenario"}
    options = {
        "snapshotStart": 0,
        "snapshotEnd": 24,
        "snapshotWeight": 1,
        "runLabel": "My Run",
        "filename": "case.xlsx",
    }
    result = _sample_result()

    meta = run_store.store_run(model, scenario, options, result)
    assert meta is not None
    assert meta["name"]
    assert meta["label"] == "My Run"
    assert meta["componentCounts"] == {"generators": 3, "buses": 2}
    assert len(meta["kpis"]) == 4
    assert meta["sizeBytes"] > 0

    # Enriched light fields that power Analytics → Comparison without a heavy
    # bundle fetch.
    assert meta["summary"] == result["summary"]
    assert meta["carrierMix"] == result["carrierMix"]
    assert meta["scenarioLabel"] == "Test scenario"
    assert meta["pathway"] == {
        "enabled": True,
        "periods": [2030, 2040],
        "selectedPeriod": 2030,
        "summaries": [{"period": 2030, "totalDispatch": 1.0}],
    }
    assert meta["rolling"] == {
        "enabled": False,
        "horizonSnapshots": 24,
        "overlapSnapshots": 6,
        "windowCount": 0,
    }

    # The same enriched fields survive a round-trip through the listing.
    listed_meta = run_store.list_runs()[0]
    assert listed_meta["summary"] == result["summary"]
    assert listed_meta["carrierMix"] == result["carrierMix"]

    name = meta["name"]

    listed = run_store.list_runs()
    assert len(listed) == 1
    assert listed[0]["name"] == name

    bundle = run_store.get_run(name)
    assert bundle is not None
    assert bundle["model"] == model
    assert bundle["scenario"] == scenario
    assert bundle["result"]["summary"] == result["summary"]
    assert bundle["snapshotStart"] == 0
    assert bundle["snapshotEnd"] == 24

    # NO xlsx is pre-built — Excel is derived only on explicit export, so no
    # workbook file exists on disk after a store.
    assert run_store.xlsx_path(name) is None
    assert not (run_store.RUNS_DIR / f"{name}.xlsx").exists()

    # …but it builds on demand from the canonical bundle when downloaded.
    xlsx_bytes = run_store.run_to_xlsx(name)
    assert xlsx_bytes is not None
    assert len(xlsx_bytes) > 0
    # xlsx files are zip archives — they start with the PK signature.
    assert xlsx_bytes[:2] == b"PK"

    # A stored run can always produce a workbook on demand.
    assert run_store.list_runs()[0]["xlsxReady"] is True

    # The export package zips ALL THREE on-disk files.
    import zipfile
    from io import BytesIO

    pkg = run_store.run_to_package(name)
    assert pkg is not None
    members = sorted(zipfile.ZipFile(BytesIO(pkg)).namelist())
    assert members == [f"{name}.json", f"{name}.meta.json", f"{name}.xlsx"]

    assert run_store.delete_run(name) is True
    assert run_store.get_run(name) is None
    assert run_store.list_runs() == []
    assert run_store.xlsx_path(name) is None  # the .xlsx was removed too


def test_get_run_rejects_unsafe_names(_runs_dir: Path) -> None:
    assert run_store.get_run("../secret") is None
    assert run_store.get_run("foo/bar") is None
    assert run_store.get_run("") is None
    assert run_store.run_to_xlsx("../etc/passwd") is None
    assert run_store.delete_run("../x") is False


def test_list_runs_tolerates_corrupt_meta(_runs_dir: Path) -> None:
    _runs_dir.mkdir(parents=True, exist_ok=True)
    (_runs_dir / "broken.meta.json").write_text("{ not json", encoding="utf-8")
    # A corrupt sidecar is skipped, not fatal.
    assert run_store.list_runs() == []


def test_reserve_name_gives_distinct_names_for_same_base(_runs_dir: Path) -> None:
    """Two reservations of the same base (parallel same-label batch runs) must
    get DISTINCT names so neither overwrites the other in History."""
    _runs_dir.mkdir(parents=True, exist_ok=True)
    a = run_store._reserve_name("Scenario-2_2030-01-01T00-00-00")
    b = run_store._reserve_name("Scenario-2_2030-01-01T00-00-00")
    assert a != b
    # Both names are claimed on disk (placeholder files exist).
    assert run_store._db_path(a).exists() and run_store._db_path(b).exists()


def test_get_run_missing_returns_none(_runs_dir: Path) -> None:
    assert run_store.get_run("2025-01-01T00-00-00") is None


def test_solve_worker_always_stores(_runs_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The worker persists every successful solve (no opt-in gate)."""
    import queue as _queue

    from backend.app import main
    from backend.app.models import RunPayload

    result = _sample_result()

    class _FakeBackend:
        def run(self, model, scenario, options):  # noqa: ANN001, ANN201
            return result

    monkeypatch.setattr(main, "get_backend", lambda _name: _FakeBackend())

    payload = RunPayload(
        model={"buses": [{"name": "n1"}]},
        scenario={"label": "Worker scenario"},
        options={},  # note: no storeInBackend flag — auto-store now
    )
    q: "_queue.Queue" = _queue.Queue()
    main._solve_worker(payload, q)

    status, data = q.get_nowait()
    assert status == "ok"
    assert data == result

    runs = run_store.list_runs()
    assert len(runs) == 1
    assert runs[0]["scenarioLabel"] == "Worker scenario"
    assert runs[0]["summary"] == result["summary"]


def test_filename_label_stem_strips_extension_and_drops_defaults() -> None:
    # The model filename loses its extension before becoming a run-name label,
    # so a run is never named "...case.xlsx" (which yields ".xlsx.xlsx" on
    # download). Generic default filenames contribute no label at all.
    assert run_store._filename_label_stem("north-sea-2030.xlsx") == "north-sea-2030"
    assert run_store._filename_label_stem("case.XLSX") == "case"
    assert run_store._filename_label_stem("model.nc") == "model"
    assert run_store._filename_label_stem("ragnarok_case.xlsx") == ""
    assert run_store._filename_label_stem("ragnarok") == ""


def test_unique_name_suffixes_on_collision(_runs_dir: Path) -> None:
    # A free base name is returned unchanged (concurrency=1 / serial path).
    assert run_store._unique_name("north-sea_2026-06-09T14-30-00") == "north-sea_2026-06-09T14-30-00"

    # Two concurrent same-scenario solves finishing in the same second would
    # derive the same base name; each must keep its own .db file rather than
    # overwriting the first (last-writer-wins data loss).
    _runs_dir.mkdir(parents=True, exist_ok=True)
    base = "dup_2026-06-09T14-30-00"
    run_store._db_path(base).write_bytes(b"")
    assert run_store._unique_name(base) == f"{base}-2"
    run_store._db_path(f"{base}-2").write_bytes(b"")
    assert run_store._unique_name(base) == f"{base}-3"


def test_results_split_writes_analytics_and_series(_runs_dir: Path) -> None:
    meta = run_store.store_run(
        {"buses": [{"name": "n1"}]},
        {"label": "split"},
        {"snapshotStart": 0, "snapshotEnd": 2},
        _sample_result(),
    )
    assert meta is not None
    name = meta["name"]

    # analytics bundle: no input model, no heavy series, but a seriesSheets list.
    analytics = run_store.get_run_analytics(name)
    assert analytics is not None
    assert "model" not in analytics
    assert analytics["hasModel"] is True
    assert analytics["result"]["outputs"]["series"] is None
    assert analytics["result"]["outputs"]["seriesSheets"] == ["generators-p"]
    # The lightweight chart fields stay available for instant render.
    assert analytics["result"]["summary"] == _sample_result()["summary"]

    # series window read back from parquet (windowed + column subset).
    win = run_store.run_series_window(name, "generators-p", max_points=100)
    assert win is not None and win["total"] == 2
    assert [r["wind"] for r in win["rows"]] == [10.0, 12.0]
    sub = run_store.run_series_window(name, "generators-p", columns=["gas"], max_points=100)
    assert sub is not None and set(sub["columns"]) == {"snapshot", "gas"}

    # input model paging.
    page = run_store.run_model_sheet_page(name, "buses")
    assert page is not None and page["total"] == 1 and page["rows"][0]["name"] == "n1"


def test_run_series_window_downsamples(_runs_dir: Path) -> None:
    import numpy as np

    res = _sample_result()
    res["outputs"]["series"]["generators-p"] = [
        {"snapshot": f"2025-01-01T{h:02d}:00:00", "wind": float(h)} for h in range(8)
    ]
    meta = run_store.store_run({"buses": [{"name": "n1"}]}, {}, {}, res)
    assert meta is not None
    win = run_store.run_series_window(meta["name"], "generators-p", max_points=4, agg="mean")
    assert win is not None
    np.testing.assert_allclose([r["wind"] for r in win["rows"]], [0.5, 2.5, 4.5, 6.5])


def test_run_is_one_sqlite_file_with_sql_served_reads(_runs_dir: Path) -> None:
    # A stored run is exactly ONE <name>.db (zero scattered files); analytics,
    # the model page, and the series window are all served by SQL queries.
    meta = run_store.store_run({"buses": [{"name": "n1"}]}, {}, {}, _sample_result())
    assert meta is not None
    name = meta["name"]
    assert run_store._db_path(name).exists()
    assert not (run_store.RUNS_DIR / f"{name}.json").exists()
    assert not (run_store.RUNS_DIR / f"{name}.meta.json").exists()
    assert not run_store._analytics_path(name).exists()
    assert not run_store._series_dir(name).exists()

    analytics = run_store.get_run_analytics(name)
    assert analytics is not None
    assert analytics["result"]["outputs"]["seriesSheets"] == ["generators-p"]
    page = run_store.run_model_sheet_page(name, "buses", offset=0, limit=10)
    assert page is not None and page["total"] == 1 and page["rows"][0]["name"] == "n1"
    win = run_store.run_series_window(name, "generators-p", max_points=100)
    assert win is not None and win["total"] == 2

    assert run_store.delete_run(name) is True
    assert not run_store._db_path(name).exists()


def test_legacy_json_run_migrates_to_db_on_read(_runs_dir: Path) -> None:
    # A pre-SQLite run (json bundle + meta sidecar) upgrades to <name>.db on
    # first access and its legacy artefacts are removed.
    import json as _json

    run_store.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    name = "legacy_2026-01-01T00-00-00"
    bundle = {
        "savedAt": "2026-01-01T00:00:00+00:00",
        "label": "legacy",
        "filename": "old.xlsx",
        "snapshotStart": 0,
        "snapshotEnd": 2,
        "snapshotWeight": 1,
        "model": {"buses": [{"name": "n1"}]},
        "scenario": {"label": "legacy"},
        "options": {},
        "result": _sample_result(),
    }
    (run_store.RUNS_DIR / f"{name}.json").write_text(_json.dumps(bundle), encoding="utf-8")
    (run_store.RUNS_DIR / f"{name}.meta.json").write_text(
        _json.dumps(run_store.build_run_meta(name, bundle, 123)), encoding="utf-8"
    )

    got = run_store.get_run(name)
    assert got is not None
    assert got["model"] == bundle["model"]
    assert got["result"]["summary"] == bundle["result"]["summary"]
    assert got["result"]["outputs"]["series"] == bundle["result"]["outputs"]["series"]
    assert run_store._db_path(name).exists()
    assert not (run_store.RUNS_DIR / f"{name}.json").exists()
    assert not (run_store.RUNS_DIR / f"{name}.meta.json").exists()
    # The listing serves it from the db now.
    assert [m["name"] for m in run_store.list_runs()] == [name]


def test_derive_name_default_filename_is_clean_timestamp() -> None:
    # No runLabel / scenario label and the default filename → the name is the
    # bare timestamp (no "_ragnarok_case", no trailing ".xlsx").
    name = run_store._derive_name({}, {}, {"filename": "ragnarok_case.xlsx"})
    assert name.count("_") == 0
    assert ".xlsx" not in name
    # A real filename DOES become a label (extension stripped). The name is
    # scenarioname_datetime, so the label LEADS and the timestamp follows.
    named = run_store._derive_name({}, {}, {"filename": "north-sea.xlsx"})
    assert named.startswith("north-sea_")
    # scenario label wins and also leads.
    scen = run_store._derive_name({}, {"label": "ref-case"}, {})
    assert scen.startswith("ref-case_")


def test_export_parts_select_sheet_groups(_runs_dir: Path) -> None:
    """The Export dialog's Metadata/Model/Result checkboxes map to sheet groups."""
    from io import BytesIO

    model = {
        "buses": [{"name": "n1"}],
        "generators": [{"name": "wind"}],
        "RAGNAROK_Scenarios": [{"id": "s1", "label": "ref"}],  # config sheet → Metadata
    }
    meta = run_store.store_run(
        model,
        {"label": "parts", "carbonPrice": 25.0, "discountRate": 0.05},
        {"runLabel": "parts", "snapshotStart": 0, "snapshotEnd": 24, "currencySymbol": "$"},
        _sample_result(),
    )
    assert meta is not None
    name = meta["name"]

    def sheets(**kw) -> set[str]:
        data = run_store.run_to_xlsx(name, **kw)
        assert data is not None and data[:2] == b"PK"
        import openpyxl

        wb = openpyxl.load_workbook(BytesIO(data), read_only=True)
        try:
            return set(wb.sheetnames)
        finally:
            wb.close()

    full = sheets()
    assert {"buses", "generators", "RAGNAROK_Scenarios", "generators-p", "RAGNAROK_ResultMeta"} <= full

    model_only = sheets(include_meta=False, include_result=False)
    assert {"buses", "generators"} <= model_only
    assert not any(s.startswith("RAGNAROK_") for s in model_only)
    assert "generators-p" not in model_only

    result_only = sheets(include_meta=False, include_model=False)
    assert "generators-p" in result_only and "RAGNAROK_ResultMeta" in result_only
    assert "buses" not in result_only
    # solved static outputs still exported standalone when the model is excluded
    assert "generators" in result_only

    meta_only = sheets(include_model=False, include_result=False)
    assert {"RAGNAROK_Scenarios", "RAGNAROK_RunState", "RAGNAROK_Settings"} <= meta_only
    assert "buses" not in meta_only and "generators-p" not in meta_only


def test_korean_scenario_label_survives_into_run_name() -> None:
    # DENYLIST sanitisation: non-Latin labels are kept, not stripped to nothing.
    name = run_store._derive_name({}, {"label": "이런젠장 시나리오"}, {})
    assert name.startswith("이런젠장-시나리오_")
    assert run_store._is_safe_name(name) is True
    # Traversal/path characters are still rejected.
    assert run_store._is_safe_name("../이런젠장") is False
    assert run_store._is_safe_name("이런/젠장") is False


# ── Rename ─────────────────────────────────────────────────────────────────────


def test_rename_run_moves_db_and_updates_identity_and_labels(_runs_dir: Path) -> None:
    meta = run_store.store_run({"buses": [{"name": "n1"}]}, {"label": "Old"}, {}, _sample_result())
    assert meta is not None
    old = meta["name"]

    renamed, err = run_store.rename_run(old, "high-carbon sensitivity")
    assert err == "" and renamed is not None
    assert renamed["name"] == "high-carbon sensitivity"
    assert renamed["label"] == "high-carbon sensitivity"          # History row
    assert renamed["scenarioLabel"] == "high-carbon sensitivity"  # Comparison pivot
    assert not (_runs_dir / f"{old}.db").exists()
    assert (_runs_dir / "high-carbon sensitivity.db").exists()

    # The renamed run is fully readable under its new identity, gone under the old.
    assert run_store.run_exists("high-carbon sensitivity") is True
    assert run_store.run_exists(old) is False
    listed = run_store.list_runs()
    assert [m["name"] for m in listed] == ["high-carbon sensitivity"]
    assert run_store.get_run_analytics("high-carbon sensitivity") is not None


def test_rename_run_guards(_runs_dir: Path) -> None:
    meta_a = run_store.store_run({"buses": [{"name": "a"}]}, {"label": "A"}, {"runLabel": "A"}, _sample_result())
    meta_b = run_store.store_run({"buses": [{"name": "b"}]}, {"label": "B"}, {"runLabel": "B"}, _sample_result())
    assert meta_a is not None and meta_b is not None

    assert run_store.rename_run("nope", "x") == (None, "not_found")
    assert run_store.rename_run(meta_a["name"], "../escape")[1] == "unsafe"
    assert run_store.rename_run(meta_a["name"], "")[1] == "unsafe"
    assert run_store.rename_run(meta_a["name"], meta_b["name"])[1] == "exists"

    # No-op rename returns the current meta unchanged.
    same, err = run_store.rename_run(meta_a["name"], meta_a["name"])
    assert err == "" and same is not None and same["name"] == meta_a["name"]


def test_get_run_model_returns_input_model_without_output_series(_runs_dir: Path) -> None:
    """The promote source reads the input model (static + INPUT series) and the
    head (scenario / window), but NOT the heavy OUTPUT series."""
    model = {
        "buses": [{"name": "n1"}],
        "loads": [{"name": "L", "bus": "n1"}],
        # An INPUT time-series — part of the editable model, must come through.
        "loads-p_set": [
            {"snapshot": "2025-01-01T00:00:00", "L": 80.0},
            {"snapshot": "2025-01-01T01:00:00", "L": 90.0},
        ],
    }
    # An OUTPUT series lives under result.outputs.series — NOT the model.
    result = {
        "outputs": {
            "static": {},
            "series": {"generators-p": [{"snapshot": "2025-01-01T00:00:00", "g": 5.0}]},
        },
    }
    meta = run_store.store_run(model, {"label": "Promote me", "discountRate": 0.05}, {"snapshotWeight": 2}, result)
    assert meta is not None

    data = run_store.get_run_model(meta["name"])
    assert data is not None
    # Input model incl. the input time-series round-trips.
    assert "buses" in data["model"] and "loads" in data["model"]
    assert data["model"]["loads-p_set"] == [
        {"snapshot": "2025-01-01T00:00:00", "L": 80.0},
        {"snapshot": "2025-01-01T01:00:00", "L": 90.0},
    ]
    # The output series is NOT pulled in (it pages on demand later).
    assert "generators-p" not in data["model"]
    # Head carries scenario + window for restoring constraints / controls.
    assert data["scenario"]["label"] == "Promote me"
    assert data["snapshotWeight"] == 2

    assert run_store.get_run_model("does-not-exist") is None
