#!/usr/bin/env python3
"""Author a training-course checkpoint as a bundled example ``project.db``.

Every module of the "Power market modelling" course after the first opens from a
checkpoint: the model exactly as it stood at the END of the previous module. Those
checkpoints ship as bundled examples under ``backend/data/examples/<id>/`` and
load through ``/api/examples`` like any other.

Module 1's checkpoint was authored by hand, which meant module 2 had to
reverse-engineer the file format from the committed binary. This script is that
knowledge written down, so module 3 does not have to do it a third time.

    python3 scripts/author_training_checkpoint.py training_m2

The format, as the app requires it (see ``backend/app/sqlite_store.py`` and
``routers/examples.py``):

  * one ``sheet_<n>`` table per sheet, each row a JSON object in column ``d``
  * ``_kv['tables']``  — sheet name → table name
  * ``_kv['meta']``    — the session meta the client rehydrates from. Every
    sheet needs ``kind``: ``'static'`` for a component sheet AND for
    ``snapshots``; ``'series'`` only for a genuine temporal sheet
    (``loads-p_set``, ``generators-p_max_pu``). Marking ``snapshots`` as
    ``'series'`` makes the static-only rehydrate drop it and the session opens
    with zero snapshots — the bug that shipped in module 1's first pass.
  * ``_kv['example']`` — label / description / order for the examples list

Every number here is the model the course has the learner type, and each
checkpoint's objective is asserted against a real solve before it is committed
(see the module's own docstring for the values).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "backend" / "data" / "examples"

SNAPSHOTS = ["2030-01-01T00:00:00", "2030-01-01T01:00:00", "2030-01-01T02:00:00"]

# ── Module 2 — the model at the end of "2 · Economic dispatch" ────────────────
# Four generators on one bus, a demand profile and a wind availability profile.
# Solves to 8,980 with prices 0 / 50 / 120 and 14 MWh of wind curtailed.
TRAINING_M2: dict = {
    "filename": "Training module 2 — economic dispatch",
    "example": {
        "label": "Training: module 2 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 2 — one bus, "
            "four generators (coal, gas, oil peaker, wind), a demand profile of 40/80/170 MW and a wind "
            "availability profile. Solves to 8,980 with prices of 0, 50 and 120. Module 3 opens from this."
        ),
        "order": 91,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
        ]),
        # Row order follows the order the course adds them, so a learner comparing
        # their own sheet against the checkpoint sees the same table.
        ("generators", "static", [
            {"name": "gas_1", "bus": "bus_1", "carrier": "gas",
             "p_nom": 100.0, "marginal_cost": 50.0, "efficiency": 0.5},
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_1", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0},
        ]),
        # The static p_set stays at the module-1 value. The profile below overrides
        # it — verified against a solve, not assumed — and the course says so.
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_1", "carrier": "AC", "p_set": 80.0},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": SNAPSHOTS[0], "load_1": 40.0},
            {"snapshot": SNAPSHOTS[1], "load_1": 80.0},
            {"snapshot": SNAPSHOTS[2], "load_1": 170.0},
        ]),
        # Only wind_1 carries a profile. A thermal unit with no column keeps its
        # static default of 1 (fully available), which is what the course teaches.
        ("generators-p_max_pu", "series", [
            {"snapshot": SNAPSHOTS[0], "wind_1": 0.9},
            {"snapshot": SNAPSHOTS[1], "wind_1": 0.4},
            {"snapshot": SNAPSHOTS[2], "wind_1": 0.1},
        ]),
    ],
    "componentCounts": {"buses": 1, "generators": 4, "loads": 1, "carriers": 5},
}

# ── Module 3 — the model at the end of "3 · Networks and congestion" ─────────
# Module 2's fleet split across two buses joined by one 60 MW line: the cheap
# plant and the wind at bus_1, the demand and the expensive plant at bus_2.
# Solves to 9,400 with two different prices in the congested hour (20 and 50)
# and 1,800 of congestion rent. Uprating the line to 100 MW gives module 2's
# 8,980 straight back — a big enough line IS a single bus.
TRAINING_M3: dict = {
    "filename": "Training module 3 — networks and congestion",
    "example": {
        "label": "Training: module 3 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 3 — two buses "
            "joined by a 60 MW line, with cheap coal and wind at one end and the demand plus expensive gas "
            "and oil at the other. Solves to 9,400, with the line congested in the middle hour and two "
            "different prices (20 and 50) either side of it."
        ),
        "order": 92,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
            {"name": "bus_2", "v_nom": 380.0, "x": 129.0, "y": 35.2, "carrier": "AC"},
        ]),
        # Same four units as module 2 — only the `bus` cell moved on two of them.
        ("generators", "static", [
            {"name": "gas_1", "bus": "bus_2", "carrier": "gas",
             "p_nom": 100.0, "marginal_cost": 50.0, "efficiency": 0.5},
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_2", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0},
        ]),
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_2", "carrier": "AC", "p_set": 80.0},
        ]),
        ("lines", "static", [
            {"name": "line_1", "bus0": "bus_1", "bus1": "bus_2",
             "s_nom": 60.0, "x": 0.1, "r": 0.01, "length": 200.0},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": SNAPSHOTS[0], "load_1": 40.0},
            {"snapshot": SNAPSHOTS[1], "load_1": 80.0},
            {"snapshot": SNAPSHOTS[2], "load_1": 170.0},
        ]),
        ("generators-p_max_pu", "series", [
            {"snapshot": SNAPSHOTS[0], "wind_1": 0.9},
            {"snapshot": SNAPSHOTS[1], "wind_1": 0.4},
            {"snapshot": SNAPSHOTS[2], "wind_1": 0.1},
        ]),
    ],
    "componentCounts": {"buses": 2, "generators": 4, "loads": 1, "carriers": 5, "lines": 1},
}

# ── Module 4 — the model at the end of "4 · Storage and time coupling" ───────
# Module 3's congested network plus one 20 MW / 1 h battery at the demand end,
# with a realistic 90% each way. It charges on the cheap hour, discharges on the
# expensive one, and the oil peaker never runs again: 7,730 against module 3's
# 9,400, with the peak price down from 120 to 50 and no wind curtailed at all.
TRAINING_M4: dict = {
    "filename": "Training module 4 — storage and time coupling",
    "example": {
        "label": "Training: module 4 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 4 — module 3's "
            "two-bus congested network with a 20 MW / 1 h battery at the demand end. It shifts energy from "
            "the cheap hour to the expensive one, so the oil peaker never runs and the peak price falls "
            "from 120 to 50. Solves to 7,730."
        ),
        "order": 93,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
            {"name": "bus_2", "v_nom": 380.0, "x": 129.0, "y": 35.2, "carrier": "AC"},
        ]),
        ("generators", "static", [
            {"name": "gas_1", "bus": "bus_2", "carrier": "gas",
             "p_nom": 100.0, "marginal_cost": 50.0, "efficiency": 0.5},
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_2", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0},
        ]),
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_2", "carrier": "AC", "p_set": 80.0},
        ]),
        ("lines", "static", [
            {"name": "line_1", "bus0": "bus_1", "bus1": "bus_2",
             "s_nom": 60.0, "x": 0.1, "r": 0.01, "length": 200.0},
        ]),
        # At bus_2, the demand end — module 4 proves this placement is worth
        # roughly 1,000 more than the same battery behind the constraint.
        ("storage_units", "static", [
            {"name": "batt_1", "bus": "bus_2", "carrier": "AC",
             "p_nom": 20.0, "max_hours": 1.0,
             "efficiency_store": 0.9, "efficiency_dispatch": 0.9,
             "cyclic_state_of_charge": True},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": SNAPSHOTS[0], "load_1": 40.0},
            {"snapshot": SNAPSHOTS[1], "load_1": 80.0},
            {"snapshot": SNAPSHOTS[2], "load_1": 170.0},
        ]),
        ("generators-p_max_pu", "series", [
            {"snapshot": SNAPSHOTS[0], "wind_1": 0.9},
            {"snapshot": SNAPSHOTS[1], "wind_1": 0.4},
            {"snapshot": SNAPSHOTS[2], "wind_1": 0.1},
        ]),
    ],
    "componentCounts": {
        "buses": 2, "generators": 4, "loads": 1, "carriers": 5,
        "lines": 1, "storage_units": 1,
    },
}

# ── Module 5 — the model at the end of "5 · Sector coupling and fuel supply" ─
# The gas plant stops being a Generator on the electrical bus and becomes what it
# physically is: a CCGT converting fuel into electricity, drawing from a gas bus
# that is supplied by an import and buffered by a gas store. Run-of-river hydro
# and a pumped-hydro scheme round the fleet out. Solves to 7,099.59.
TRAINING_M5: dict = {
    "filename": "Training module 5 — sector coupling and fuel supply",
    "example": {
        "label": "Training: module 5 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 5 — module 4's "
            "network with a separate gas bus: an import priced per MWh of fuel, a gas store, and a CCGT "
            "modelled as a Link that converts gas into electricity at 50%. Adds run-of-river hydro and a "
            "pumped-hydro scheme. Solves to 7,099.59."
        ),
        "order": 94,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
            {"name": "hydro", "co2_emissions": 0.0},
        ]),
        # bus_gas carries gas, not electricity — the whole point of the module.
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
            {"name": "bus_2", "v_nom": 380.0, "x": 129.0, "y": 35.2, "carrier": "AC"},
            {"name": "bus_gas", "v_nom": 0.0, "x": 128.0, "y": 36.4, "carrier": "gas"},
        ]),
        # gas_1 is gone: it is now the ccgt_1 Link plus the gas_supply import.
        ("generators", "static", [
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_2", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0},
            {"name": "ror_1", "bus": "bus_1", "carrier": "hydro",
             "p_nom": 15.0, "marginal_cost": 0.0, "efficiency": 1.0},
            # Priced per MWh of FUEL, and capped — the import limit that makes
            # the gas store worth having.
            {"name": "gas_supply", "bus": "bus_gas", "carrier": "gas",
             "p_nom": 150.0, "marginal_cost": 25.0, "efficiency": 1.0},
        ]),
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_2", "carrier": "AC", "p_set": 80.0},
        ]),
        ("lines", "static", [
            {"name": "line_1", "bus0": "bus_1", "bus1": "bus_2",
             "s_nom": 60.0, "x": 0.1, "r": 0.01, "length": 200.0},
        ]),
        # p_nom is measured at bus0, the fuel side: 200 MW of gas in, 100 MW out.
        ("links", "static", [
            {"name": "ccgt_1", "bus0": "bus_gas", "bus1": "bus_2",
             "efficiency": 0.5, "p_nom": 200.0},
        ]),
        ("stores", "static", [
            {"name": "gas_store", "bus": "bus_gas", "e_nom": 200.0, "e_cyclic": True},
        ]),
        ("storage_units", "static", [
            {"name": "batt_1", "bus": "bus_2", "carrier": "AC",
             "p_nom": 20.0, "max_hours": 1.0,
             "efficiency_store": 0.9, "efficiency_dispatch": 0.9,
             "cyclic_state_of_charge": True},
            # Pumped hydro is where the mountains are — which is behind the
            # constraint, and worth a fraction of the battery at the demand end.
            {"name": "phs_1", "bus": "bus_1", "carrier": "hydro",
             "p_nom": 30.0, "max_hours": 6.0,
             "efficiency_store": 0.87, "efficiency_dispatch": 0.87,
             "cyclic_state_of_charge": True},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": SNAPSHOTS[0], "load_1": 40.0},
            {"snapshot": SNAPSHOTS[1], "load_1": 80.0},
            {"snapshot": SNAPSHOTS[2], "load_1": 170.0},
        ]),
        # Run-of-river is variable but NOT volatile — that contrast is the lesson.
        ("generators-p_max_pu", "series", [
            {"snapshot": SNAPSHOTS[0], "wind_1": 0.9, "ror_1": 0.6},
            {"snapshot": SNAPSHOTS[1], "wind_1": 0.4, "ror_1": 0.6},
            {"snapshot": SNAPSHOTS[2], "wind_1": 0.1, "ror_1": 0.55},
        ]),
    ],
    "componentCounts": {
        "buses": 3, "generators": 5, "loads": 1, "carriers": 6,
        "lines": 1, "links": 1, "storage_units": 2, "stores": 1,
    },
}

# ── Module 6 — the model at the end of "6 · Investment and capacity expansion" ─
# Module 5's model with wind and the line made extendable and given capital costs
# scaled to the three hours actually modelled. The optimiser widens the line from
# 60 to 87.55 MW and builds no wind at all — the wire was the binding constraint.
# Solves to 6,187.27.
#
# Ragnarok treats a workbook `capital_cost` as an OVERNIGHT cost and annualises
# it itself, using `lifetime` and Settings -> Discount rate. It does NOT scale
# that annual figure to the modelled window, so on a three-hour model the
# overnight cost must be pre-scaled by 3/8760 by hand — which is the trap module
# 6 is built around, and another reason module 7 exists.
#
#   wind  1,200,000/MW x 3/8760 = 410.9589,  lifetime 25 y
#   line    600,000/MW x 3/8760 = 205.4795,  lifetime 40 y
# Ragnarok then applies CRF(7%, life), giving 35.26 and 15.41 per MW.
TRAINING_M6: dict = {
    "filename": "Training module 6 — investment and capacity expansion",
    "example": {
        "label": "Training: module 6 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 6 — module 5's "
            "system with wind and the transmission line made extendable, and capital costs annualised and "
            "scaled to the modelled window. The optimiser widens the line from 60 to 87.55 MW and builds "
            "30 MW of new wind alongside it, because the wire is what makes the wind reachable. Solves "
            "to 5,995.48 at the default 0.05 discount rate."
        ),
        "order": 95,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
            {"name": "hydro", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
            {"name": "bus_2", "v_nom": 380.0, "x": 129.0, "y": 35.2, "carrier": "AC"},
            {"name": "bus_gas", "v_nom": 0.0, "x": 128.0, "y": 36.4, "carrier": "gas"},
        ]),
        # wind_1 is extendable with p_nom_min at its existing 60 MW — brownfield:
        # the model may build more but may not un-build what is already there.
        ("generators", "static", [
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_2", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0,
             "p_nom_extendable": True, "p_nom_min": 60.0, "p_nom_max": 300.0,
             "capital_cost": 410.9589, "lifetime": 25.0},
            {"name": "ror_1", "bus": "bus_1", "carrier": "hydro",
             "p_nom": 15.0, "marginal_cost": 0.0, "efficiency": 1.0},
            {"name": "gas_supply", "bus": "bus_gas", "carrier": "gas",
             "p_nom": 150.0, "marginal_cost": 25.0, "efficiency": 1.0},
        ]),
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_2", "carrier": "AC", "p_set": 80.0},
        ]),
        ("lines", "static", [
            {"name": "line_1", "bus0": "bus_1", "bus1": "bus_2",
             "s_nom": 60.0, "x": 0.1, "r": 0.01, "length": 200.0,
             "s_nom_extendable": True, "s_nom_min": 60.0, "s_nom_max": 300.0,
             "capital_cost": 205.4795, "lifetime": 40.0},
        ]),
        ("links", "static", [
            {"name": "ccgt_1", "bus0": "bus_gas", "bus1": "bus_2",
             "efficiency": 0.5, "p_nom": 200.0},
        ]),
        ("stores", "static", [
            {"name": "gas_store", "bus": "bus_gas", "e_nom": 200.0, "e_cyclic": True},
        ]),
        ("storage_units", "static", [
            {"name": "batt_1", "bus": "bus_2", "carrier": "AC",
             "p_nom": 20.0, "max_hours": 1.0,
             "efficiency_store": 0.9, "efficiency_dispatch": 0.9,
             "cyclic_state_of_charge": True},
            {"name": "phs_1", "bus": "bus_1", "carrier": "hydro",
             "p_nom": 30.0, "max_hours": 6.0,
             "efficiency_store": 0.87, "efficiency_dispatch": 0.87,
             "cyclic_state_of_charge": True},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": SNAPSHOTS[0], "load_1": 40.0},
            {"snapshot": SNAPSHOTS[1], "load_1": 80.0},
            {"snapshot": SNAPSHOTS[2], "load_1": 170.0},
        ]),
        ("generators-p_max_pu", "series", [
            {"snapshot": SNAPSHOTS[0], "wind_1": 0.9, "ror_1": 0.6},
            {"snapshot": SNAPSHOTS[1], "wind_1": 0.4, "ror_1": 0.6},
            {"snapshot": SNAPSHOTS[2], "wind_1": 0.1, "ror_1": 0.55},
        ]),
    ],
    "componentCounts": {
        "buses": 3, "generators": 5, "loads": 1, "carriers": 6,
        "lines": 1, "links": 1, "storage_units": 2, "stores": 1,
    },
}

CHECKPOINTS = {
    "training_m2": TRAINING_M2,
    "training_m3": TRAINING_M3,
    "training_m4": TRAINING_M4,
    "training_m5": TRAINING_M5,
    "training_m6": TRAINING_M6,
}


def write_checkpoint(example_id: str, spec: dict) -> Path:
    """Write ``<example_id>/project.db``, replacing any existing one."""
    out_dir = EXAMPLES / example_id
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "project.db"
    if db_path.exists():
        db_path.unlink()

    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE _kv (k TEXT PRIMARY KEY, v TEXT)")

    tables: dict[str, str] = {}
    sheet_meta: list[dict] = []
    for i, (name, kind, rows) in enumerate(spec["sheets"]):
        table = f"sheet_{i}"
        tables[name] = table
        con.execute(f"CREATE TABLE {table} (__row INTEGER PRIMARY KEY AUTOINCREMENT, d TEXT)")
        con.executemany(
            f"INSERT INTO {table} (d) VALUES (?)",
            [(json.dumps(r),) for r in rows],
        )
        # Column order is taken from the first row, so authored dicts must be
        # written in the order the learner sees the columns in the grid.
        sheet_meta.append({
            "name": name,
            "kind": kind,
            "rowCount": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
        })

    meta = {
        "sessionId": "__example_author__",
        "filename": spec["filename"],
        "scenarioName": "",
        "savedAt": "2026-08-03T00:00:00+00:00",
        "sheets": sheet_meta,
        "snapshotCount": len(SNAPSHOTS),
        "snapshotStart": SNAPSHOTS[0].replace("T", " "),
        "snapshotEnd": SNAPSHOTS[-1].replace("T", " "),
        "scenarioYear": 2030,
        "componentCounts": spec["componentCounts"],
    }
    for key, value in (("meta", meta), ("tables", tables), ("example", spec["example"])):
        con.execute("INSERT INTO _kv (k, v) VALUES (?, ?)", (key, json.dumps(value)))

    con.commit()
    con.close()
    return db_path


def main() -> int:
    ids = sys.argv[1:] or list(CHECKPOINTS)
    for example_id in ids:
        spec = CHECKPOINTS.get(example_id)
        if spec is None:
            print(f"unknown checkpoint {example_id!r}; known: {', '.join(CHECKPOINTS)}")
            return 1
        path = write_checkpoint(example_id, spec)
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
