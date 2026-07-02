"""H2′ — result-mapper registry + raw-sheet capture on workbook import."""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import pytest

from backend.app import project_workbook as pw
from backend.app.result_mappers import (
    ResultMapper,
    clear_result_mappers,
    find_result_mapper,
    register_result_mapper,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_result_mappers()
    yield
    clear_result_mappers()


def _xlsx(sheets: dict[str, list[dict[str, Any]]]) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(xl, sheet_name=name, index=False)
    return buf.getvalue()


def test_registered_mapper_takes_over_reconstruction() -> None:
    seen: dict[str, Any] = {}

    def matches(names: list[str]) -> bool:
        return "THIRD_PARTY_RESULTS" in names

    def map_(sheets: dict[str, list[dict]], filename: str) -> dict[str, Any]:
        seen["sheets"] = sorted(sheets)
        return {"model": {"buses": [{"name": "b"}]}, "scenario": {}, "options": {},
                "result": {"summary": [{"label": "Mapped", "value": "1", "detail": ""}]}}

    register_result_mapper(ResultMapper("acme", matches, map_))
    data = _xlsx({"THIRD_PARTY_RESULTS": [{"x": 1}], "buses": [{"name": "b"}]})
    bundle = pw.workbook_to_bundle(data, filename="acme.xlsx")
    assert bundle["options"]["resultMapper"] == "acme"
    assert bundle["result"]["summary"][0]["label"] == "Mapped"
    assert seen["sheets"] == ["THIRD_PARTY_RESULTS", "buses"]  # mapper got every sheet


def test_first_matching_mapper_wins_and_broken_matchers_are_skipped() -> None:
    def boom(_names: list[str]) -> bool:
        raise RuntimeError("broken matcher")

    register_result_mapper(ResultMapper("broken", boom, lambda s, f: {}))
    register_result_mapper(ResultMapper("a", lambda n: "X" in n, lambda s, f: {"model": {}, "result": {"tag": "a"}}))
    register_result_mapper(ResultMapper("b", lambda n: "X" in n, lambda s, f: {"model": {}, "result": {"tag": "b"}}))
    m = find_result_mapper(["X"])
    assert m is not None and m.name == "a"


def test_no_mapper_falls_through_to_canonical() -> None:
    data = _xlsx({"buses": [{"name": "b", "v_nom": 345}]})
    bundle = pw.workbook_to_bundle(data, filename="plain.xlsx")
    assert "resultMapper" not in bundle["options"]
    assert bundle["model"]["buses"][0]["name"] == "b"


def test_unrecognised_sheets_land_as_raw_not_in_model() -> None:
    data = _xlsx({
        "buses": [{"name": "b"}],
        "loads-p_set": [{"snapshot": "2030-01-01T00:00:00", "L": 100}],  # input temporal → model
        "Dashboard": [{"kpi": "profit", "value": 42}],                    # alien → raw
    })
    bundle = pw.workbook_to_bundle(data, filename="mixed.xlsx")
    assert "Dashboard" not in bundle["model"]
    assert bundle["model"]["loads-p_set"][0]["L"] == 100
    assert bundle["result"]["rawSheets"]["Dashboard"] == [{"kpi": "profit", "value": 42}]


def test_plugin_hook_mappers_participate(tmp_path, monkeypatch) -> None:
    import json as _json

    from backend.app import plugins

    d = tmp_path / "plugins" / "acme-mapper"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(_json.dumps({"id": "acme-mapper", "name": "acme"}))
    (d / "plugin.py").write_text(
        "def transform(model, config):\n    return model\n"
        "def result_mapper_matches(names):\n    return 'ACME' in names\n"
        "def result_mapper_map(sheets, filename):\n"
        "    return {'model': {}, 'result': {'tag': 'from-plugin'}}\n"
    )
    monkeypatch.setattr(plugins, "BACKEND_PLUGINS_DIR", tmp_path / "plugins")
    plugins._REGISTRY = None
    try:
        m = find_result_mapper(["ACME"])
        assert m is not None and m.name == "plugin:acme-mapper"
        assert m.map({}, "f")["result"]["tag"] == "from-plugin"
    finally:
        plugins._REGISTRY = None
