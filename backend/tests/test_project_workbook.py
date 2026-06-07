"""Round-trip tests for the lossless project workbook (project_workbook.py).

A run bundle rendered to xlsx and parsed back must preserve the model inputs,
the solved outputs (static + series), and the result metadata — so an exported
project re-imports with nothing lost.
"""
from __future__ import annotations

from typing import Any

from backend.app import project_workbook as pw


def _sample_bundle() -> dict[str, Any]:
    return {
        "model": {
            "buses": [{"name": "n1", "v_nom": 380.0}, {"name": "n2", "v_nom": 380.0}],
            "generators": [
                # carries a stale p_nom_opt (an output) — it must be stripped from
                # the model and re-emerge only under outputs.static.
                {"name": "wind", "bus": "n1", "p_nom": 100.0, "carrier": "wind", "p_nom_opt": 999.0},
                {"name": "gas", "bus": "n2", "p_nom": 50.0, "carrier": "gas", "marginal_cost": 40.0},
            ],
            "loads": [{"name": "load1", "bus": "n1", "p_set": ""}],  # blank numeric cell
            "generators-p_max_pu": [
                {"snapshot": "2025-01-01T00:00:00", "wind": 0.8},
                {"snapshot": "2025-01-01T01:00:00", "wind": 0.6},
            ],
            "RAGNAROK_Scenarios": [{"id": "base", "label": "Base"}],
            "lines": [],  # empty — must be skipped, not crash
        },
        "scenario": {
            "discountRate": 0.07,
            "carbonPrice": 50.0,
            "constraints": [{"id": "c1", "enabled": True, "metric": "co2_cap", "value": 1000.0}],
        },
        "options": {
            "snapshotStart": 0,
            "snapshotEnd": 2,
            "snapshotWeight": 1,
            "currencySymbol": "$",
            "dateFormat": "auto",
            "filename": "demo.xlsx",
        },
        "result": {
            "outputs": {
                "static": {
                    "generators": {"wind": {"p_nom_opt": 120.0}, "gas": {"p_nom_opt": 50.0}},
                },
                "series": {
                    "generators-p": [
                        {"snapshot": "2025-01-01T00:00:00", "wind": 80.0, "gas": 10.0},
                        {"snapshot": "2025-01-01T01:00:00", "wind": 60.0, "gas": 30.0},
                    ],
                },
            },
            "runMeta": {"componentCounts": {"generators": 2, "buses": 2}},
            "pathway": {"enabled": False},
            "rolling": {"enabled": False},
            "narrative": ["Solved in 2 snapshots."],
        },
    }


def test_bundle_to_workbook_round_trip_preserves_everything() -> None:
    bundle = _sample_bundle()
    rt = pw.workbook_to_bundle(pw.bundle_to_workbook(bundle), filename="demo.xlsx")

    # ── Model inputs: non-empty sheets preserved; empty 'lines' dropped ──────
    assert {row["name"] for row in rt["model"]["buses"]} == {"n1", "n2"}
    assert {row["name"] for row in rt["model"]["generators"]} == {"wind", "gas"}
    # Output-static column stripped from the model …
    assert all("p_nom_opt" not in row for row in rt["model"]["generators"])
    # … input columns kept.
    wind = next(r for r in rt["model"]["generators"] if r["name"] == "wind")
    assert wind["p_nom"] == 100.0 and wind["carrier"] == "wind"
    # Input temporal + config sheets copied verbatim.
    assert len(rt["model"]["generators-p_max_pu"]) == 2
    assert rt["model"]["RAGNAROK_Scenarios"][0]["label"] == "Base"
    assert "lines" not in rt["model"]  # empty sheet skipped

    # ── Outputs ──────────────────────────────────────────────────────────────
    static = rt["result"]["outputs"]["static"]["generators"]
    assert static["wind"]["p_nom_opt"] == 120.0
    assert static["gas"]["p_nom_opt"] == 50.0
    series = rt["result"]["outputs"]["series"]["generators-p"]
    assert len(series) == 2
    assert series[0]["wind"] == 80.0 and series[1]["gas"] == 30.0
    assert series[0]["snapshot"] == "2025-01-01T00:00:00"

    # ── Metadata ──────────────────────────────────────────────────────────────
    assert rt["result"]["runMeta"]["componentCounts"] == {"generators": 2, "buses": 2}
    assert rt["result"]["pathway"] == {"enabled": False}
    assert rt["result"]["narrative"] == ["Solved in 2 snapshots."]
    assert rt["scenario"]["constraints"][0]["metric"] == "co2_cap"
    assert rt["scenario"]["carbonPrice"] == 50.0
    assert rt["scenario"]["discountRate"] == 0.07
    assert rt["options"]["snapshotEnd"] == 2
    assert rt["options"]["currencySymbol"] == "$"


def test_workbook_never_uses_out_prefix_or_truncates() -> None:
    import openpyxl

    from io import BytesIO

    data = pw.bundle_to_workbook(_sample_bundle())
    sheets = openpyxl.load_workbook(BytesIO(data), read_only=True).sheetnames
    assert not any(s.startswith("OUT_") for s in sheets), sheets
    assert "generators-p" in sheets  # output series, plainly named
    assert all(len(s) <= 31 for s in sheets), sheets
