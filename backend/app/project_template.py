"""The project template: a small model that runs as it is, with every input sheet a person fills in.

Fill the sheets with your own data and settings (Excel, or a script / agent writing the same sheets), open the file
in Ragnarok (Import Project) and press Run: the settings in ``RAGNAROK_RunSettings`` and the limits in
``RAGNAROK_PeriodBudgets`` are what the run uses. The format is ``docs/project-file.md``.

The example: two regions joined by one line, 6-hourly snapshots over January-February 2030 (weight 6 h each), gas,
solar and a hydro plant whose monthly energy is limited, solved in monthly rolling windows.
"""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

from . import run_settings

README_SHEET = "README"

_README = [
    ("What this is", "A Ragnarok project template. It runs as it is; replace the example with your own data and settings."),
    ("How to use", "Fill the sheets, then in Ragnarok: Model -> Import Project -> pick this file -> Run."),
    ("snapshots", "One row per time step: snapshot (date-time) and the hours it stands for in objective / generators / stores (6 for 6-hourly)."),
    ("Component sheets", "buses, carriers, generators, loads, lines, links, storage_units, stores: one row per component, columns = PyPSA attributes in PyPSA units (MW, MWh, currency/MWh, t/MWh)."),
    ("Time series", "<component>-<attribute> (generators-p_max_pu, loads-p_set): one row per snapshot, one column per component name."),
    ("RAGNAROK_RunSettings", "How the run is solved: window, carbon price, discount rate, load shedding, rolling horizon, solver, currency, modules. Blank value = the app default."),
    ("RAGNAROK_PeriodBudgets", "Energy or emission limits over a period (YYYY-MM, YYYY or start/end): kept exactly in a single solve, carried over window by window in a rolling run."),
    ("RAGNAROK_Schema", "Leave as is: it says the costs follow PyPSA's semantics."),
    ("Reference", "docs/project-file.md in the Ragnarok repository; MCP: describe_project_file."),
]


def example_model() -> dict[str, list[dict[str, Any]]]:
    """The runnable example (``{sheet: rows}``)."""
    stamps = pd.date_range("2030-01-01", "2030-02-28 18:00", freq="6h")
    labels = [s.strftime("%Y-%m-%d %H:%M") for s in stamps]
    solar = [round(max(0.0, 1.0 - abs(s.hour + 3 - 12) / 7.0), 3) for s in stamps]  # 6-hour block mean shape
    demand_n = [(300 + 60 * (1 if 6 <= s.hour < 18 else 0)) for s in stamps]
    demand_s = [(200 + 40 * (1 if 6 <= s.hour < 18 else 0)) for s in stamps]
    return {
        "snapshots": [{"snapshot": t, "objective": 6, "generators": 6, "stores": 6} for t in labels],
        "buses": [{"name": "north", "v_nom": 380, "carrier": "AC"}, {"name": "south", "v_nom": 380, "carrier": "AC"}],
        "carriers": [
            {"name": "AC"}, {"name": "gas", "co2_emissions": 0.2}, {"name": "solar", "co2_emissions": 0.0},
            {"name": "hydro", "co2_emissions": 0.0},
        ],
        "generators": [
            {"name": "gas_north", "bus": "north", "carrier": "gas", "p_nom": 600, "marginal_cost": 60, "efficiency": 0.5},
            {"name": "solar_south", "bus": "south", "carrier": "solar", "p_nom": 300, "marginal_cost": 0},
            {"name": "hydro_north", "bus": "north", "carrier": "hydro", "p_nom": 150, "marginal_cost": 1},
        ],
        "generators-p_max_pu": [{"snapshot": t, "solar_south": v} for t, v in zip(labels, solar, strict=True)],
        "loads": [{"name": "load_north", "bus": "north"}, {"name": "load_south", "bus": "south"}],
        "loads-p_set": [
            {"snapshot": t, "load_north": a, "load_south": b} for t, a, b in zip(labels, demand_n, demand_s, strict=True)
        ],
        "lines": [{"name": "north_south", "bus0": "north", "bus1": "south", "s_nom": 400, "x": 0.1, "r": 0.01}],
        "RAGNAROK_PeriodBudgets": [
            {"name": "hydro_jan", "measure": "energy", "carrier": "hydro", "generator": "", "period": "2030-01",
             "start": "", "end": "", "sense": "<=", "value": 40000},
            {"name": "hydro_feb", "measure": "energy", "carrier": "hydro", "generator": "", "period": "2030-02",
             "start": "", "end": "", "sense": "<=", "value": 30000},
            {"name": "co2_total", "measure": "emissions", "carrier": "", "generator": "", "period": "",
             "start": "", "end": "", "sense": "<=", "value": 250000},
        ],
        "RAGNAROK_Schema": [{"ragnarok_schema_version": 4}],
    }


def example_settings(model: dict[str, Any]) -> dict[str, Any]:
    labels = run_settings.snapshot_labels(model)
    return {
        "windowStart": labels[0], "windowEnd": labels[-1], "carbonPrice": 0, "discountRate": 0.05,
        "loadShedding": True, "loadSheddingCost": 10000, "rolling": True, "rollingWindowHours": 744,
        "rollingOverlapHours": 24, "rollingTerminalSoc": False, "solverType": "auto", "currencyCode": "USD",
        "currencySymbol": "$",
    }


def template_model() -> dict[str, Any]:
    """The example plus its ``RAGNAROK_RunSettings`` sheet (every setting listed, with unit and meaning)."""
    model = example_model()
    state = run_settings.apply({}, example_settings(model), labels=run_settings.snapshot_labels(model),
                               step_hours=run_settings.step_hours_of(model))
    model[run_settings.SHEET] = run_settings.sheet_rows(state, run_settings.snapshot_labels(model))
    return model


def template_xlsx() -> bytes:
    """The template as an Excel workbook: README first, then the model, settings and budgets sheets."""
    model = template_model()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(_README, columns=["topic", "what to do"]).to_excel(writer, sheet_name=README_SHEET, index=False)
        for name, rows in model.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=name[:31], index=False)
        for ws in writer.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 80)
    return buf.getvalue()
