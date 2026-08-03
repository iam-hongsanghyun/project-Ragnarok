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


# ── Module 6 — the model at the end of "6 · Time" ────────────────────────────
# Module 5's components on a real 24-hour axis: an overnight lull, an evening
# peak at 170 MW, and wind that fades exactly as demand rises. Solves to
# 52,663.98 at hourly resolution.
#
# The day is what finally lets pumped hydro do its job. Module 5 measured phs_1
# at 45 over three hours and the course called it nearly worthless; over a full
# daily cycle it is worth 1,026. That was the horizon talking, not the asset —
# which is the whole argument for this module.
_M6_DEMAND = [40, 38, 37, 38, 42, 50, 70, 90, 95, 100, 105, 110,
              108, 105, 100, 100, 110, 130, 170, 165, 140, 110, 80, 55]
_M6_WIND = [0.90, 0.85, 0.80, 0.75, 0.70, 0.60, 0.50, 0.45, 0.40, 0.35, 0.30, 0.30,
            0.35, 0.40, 0.40, 0.35, 0.25, 0.15, 0.10, 0.10, 0.15, 0.30, 0.50, 0.70]
_M6_ROR = [0.60] * 18 + [0.55] * 6
_M6_SNAPSHOTS = [f"2030-01-01T{h:02d}:00:00" for h in range(24)]

TRAINING_M6: dict = {
    "filename": "Training module 6 — a real day",
    "example": {
        "label": "Training: module 6 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 6 — module 5's "
            "system on a real 24-hour axis, with an overnight lull, an evening peak of 170 MW and wind "
            "that fades as demand rises. Solves to 52,663.98 hourly. The first horizon long enough for "
            "the pumped-hydro scheme to be worth anything."
        ),
        "order": 95,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in _M6_SNAPSHOTS]),
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
        ("generators", "static", [
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "oil_1", "bus": "bus_2", "carrier": "oil",
             "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0},
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
             "s_nom": 60.0, "x": 0.1, "r": 0.01, "length": 200.0},
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
            {"snapshot": _M6_SNAPSHOTS[i], "load_1": float(_M6_DEMAND[i])} for i in range(24)
        ]),
        ("generators-p_max_pu", "series", [
            {"snapshot": _M6_SNAPSHOTS[i], "wind_1": _M6_WIND[i], "ror_1": _M6_ROR[i]}
            for i in range(24)
        ]),
    ],
    "componentCounts": {
        "buses": 3, "generators": 5, "loads": 1, "carriers": 6,
        "lines": 1, "links": 1, "storage_units": 2, "stores": 1,
    },
}


# ── Module 7 — a synthetic but structured YEAR ───────────────────────────────
# Capacity expansion needs a full year, and not only for realism. Ragnarok
# annuitises a workbook `capital_cost` and the results layer pro-rates that
# annual figure by modelled_hours/8760 for display. On a shorter window the
# optimiser needs the cost pre-scaled and the display then scales it a second
# time, so the reported total disagrees with the objective the solver minimised.
# At 8760 hours the factor is 1, the overnight cost goes in exactly as a cost
# database quotes it, and every number agrees.
#
# The profiles are SYNTHETIC and the course says so. They are shaped rather than
# random: a double-peaked day modulated seasonally, wind with a winter maximum
# and AR(1) persistence, run-of-river with a spring freshet, solar with a summer
# maximum and no output at night. Seeded, so the file regenerates byte-identical.


def _year_profiles() -> dict:
    """Deterministic synthetic profiles for one hourly year."""
    import math
    import random

    hours = 8760
    rnd = random.Random(20300101)
    demand, wind, ror, solar = [], [], [], []

    # AR(1) wind noise, generated once so the series has persistence rather
    # than looking like hour-to-hour static.
    noise, prev = [], 0.0
    for _ in range(hours):
        prev = 0.86 * prev + 0.14 * rnd.gauss(0, 0.16)
        noise.append(prev)

    for i in range(hours):
        hod, doy = i % 24, i // 24
        daily = (
            0.62
            + 0.10 * math.sin((hod - 6) / 24 * 2 * math.pi)
            + 0.26 * math.exp(-((hod - 18.5) ** 2) / 8.0)
            + 0.10 * math.exp(-((hod - 8.5) ** 2) / 6.0)
        )
        seasonal = 1.0 + 0.16 * math.cos(doy / 365 * 2 * math.pi)
        d = min(max(daily * seasonal, 0.28), 1.0) * 170.0 + rnd.gauss(0, 2.0)
        demand.append(round(min(max(d, 30.0), 175.0), 3))

        w = 0.46 + 0.20 * math.cos(doy / 365 * 2 * math.pi) \
            + 0.08 * math.cos((hod - 3) / 24 * 2 * math.pi) + noise[i]
        wind.append(round(min(max(w, 0.0), 1.0), 4))

        ror.append(round(min(max(0.52 + 0.26 * math.exp(-((doy - 120) ** 2) / 3000.0), 0.0), 1.0), 4))

        sd = math.sin((hod - 6) / 12 * math.pi)
        sd = max(sd, 0.0) ** 1.2
        ss = 0.55 + 0.45 * math.cos((doy - 172) / 365 * 2 * math.pi)
        solar.append(round(min(max(sd * ss, 0.0), 1.0), 4))

    return {"demand": demand, "wind": wind, "ror": ror, "solar": solar}


_YEAR = _year_profiles()
def _year_axis() -> list:
    """8760 hourly timestamps from 2030-01-01, as the workbook writes them."""
    from datetime import datetime, timedelta
    t0 = datetime(2030, 1, 1)
    return [(t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(8760)]

# ── Module 7 — investment and capacity expansion, on a full year ─────────────
# `training_m7_year` is what the module STARTS from: module 5's system on 8760
# hourly snapshots, with a solar site added at the demand end and nothing
# extendable yet. `training_m7` is what it ends with — four assets offered to the
# optimiser, which builds three of them.
#
# Costs are OVERNIGHT, exactly as a cost database quotes them; Ragnarok
# annuitises with `lifetime` and Settings -> Discount rate. At 5%:
#   wind  1,200,000/MW, 25 y   cf 0.46   ~21 /MWh
#   solar   500,000/MW, 25 y   cf 0.165  ~25 /MWh
#   line    600,000/MW, 40 y
#   batt    150,000/MW, 15 y, 2 h
# Result at 5%: wind 60 -> 150.21, solar 0 -> 25.20, line 60 -> 140.94, and the
# battery declined at its 20 MW floor. Objective 18,079,255.
_M7_AXIS = _year_axis()


def _m7_sheets(*, extendable: bool) -> list:
    gens = [
        {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
         "p_nom": 50.0, "marginal_cost": 20.0, "efficiency": 0.4},
        {"name": "oil_1", "bus": "bus_2", "carrier": "oil",
         "p_nom": 40.0, "marginal_cost": 120.0, "efficiency": 0.35},
        {"name": "ror_1", "bus": "bus_1", "carrier": "hydro",
         "p_nom": 15.0, "marginal_cost": 0.0, "efficiency": 1.0},
        {"name": "gas_supply", "bus": "bus_gas", "carrier": "gas",
         "p_nom": 150.0, "marginal_cost": 25.0, "efficiency": 1.0},
    ]
    wind = {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
            "p_nom": 60.0, "marginal_cost": 0.0, "efficiency": 1.0}
    solar = {"name": "solar_1", "bus": "bus_2", "carrier": "solar",
             "p_nom": 0.0, "marginal_cost": 0.0, "efficiency": 1.0}
    line = {"name": "line_1", "bus0": "bus_1", "bus1": "bus_2",
            "s_nom": 60.0, "x": 0.1, "r": 0.01, "length": 200.0}
    batt = {"name": "batt_1", "bus": "bus_2", "carrier": "AC",
            "p_nom": 20.0, "max_hours": 2.0,
            "efficiency_store": 0.9, "efficiency_dispatch": 0.9,
            "cyclic_state_of_charge": True}
    if extendable:
        wind |= {"p_nom_extendable": True, "p_nom_min": 60.0, "p_nom_max": 300.0,
                 "capital_cost": 1_200_000.0, "lifetime": 25.0}
        solar |= {"p_nom_extendable": True, "p_nom_min": 0.0, "p_nom_max": 400.0,
                  "capital_cost": 500_000.0, "lifetime": 25.0}
        line |= {"s_nom_extendable": True, "s_nom_min": 60.0, "s_nom_max": 300.0,
                 "capital_cost": 600_000.0, "lifetime": 40.0}
        batt |= {"p_nom_extendable": True, "p_nom_min": 20.0, "p_nom_max": 300.0,
                 "capital_cost": 150_000.0, "lifetime": 15.0}
    return [
        ("snapshots", "static", [{"snapshot": t} for t in _M7_AXIS]),
        ("network", "static", [{"name": "my-first-model"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "oil", "co2_emissions": 0.27},
            {"name": "wind", "co2_emissions": 0.0},
            {"name": "hydro", "co2_emissions": 0.0},
            {"name": "solar", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
            {"name": "bus_2", "v_nom": 380.0, "x": 129.0, "y": 35.2, "carrier": "AC"},
            {"name": "bus_gas", "v_nom": 0.0, "x": 128.0, "y": 36.4, "carrier": "gas"},
        ]),
        ("generators", "static", gens[:2] + [wind, solar] + gens[2:]),
        ("loads", "static", [{"name": "load_1", "bus": "bus_2", "carrier": "AC", "p_set": 80.0}]),
        ("lines", "static", [line]),
        ("links", "static", [{"name": "ccgt_1", "bus0": "bus_gas", "bus1": "bus_2",
                              "efficiency": 0.5, "p_nom": 200.0}]),
        ("stores", "static", [{"name": "gas_store", "bus": "bus_gas",
                               "e_nom": 200.0, "e_cyclic": True}]),
        ("storage_units", "static", [batt,
            {"name": "phs_1", "bus": "bus_1", "carrier": "hydro",
             "p_nom": 30.0, "max_hours": 6.0,
             "efficiency_store": 0.87, "efficiency_dispatch": 0.87,
             "cyclic_state_of_charge": True}]),
        ("loads-p_set", "series", [
            {"snapshot": _M7_AXIS[i], "load_1": _YEAR["demand"][i]} for i in range(8760)]),
        ("generators-p_max_pu", "series", [
            {"snapshot": _M7_AXIS[i], "wind_1": _YEAR["wind"][i],
             "ror_1": _YEAR["ror"][i], "solar_1": _YEAR["solar"][i]} for i in range(8760)]),
    ]


_M7_COUNTS = {"buses": 3, "generators": 6, "loads": 1, "carriers": 7,
              "lines": 1, "links": 1, "storage_units": 2, "stores": 1}

TRAINING_M7_YEAR: dict = {
    "filename": "Training module 7 — a full year",
    "example": {
        "label": "Training: module 7 starting model (a full year)",
        "description": (
            "What module 7 starts from — the course's system on 8,760 hourly snapshots, with synthetic "
            "but structured demand, wind, run-of-river and solar profiles, and a solar site at the demand "
            "end. Nothing is extendable yet."
        ),
        "order": 96,
    },
    "sheets": _m7_sheets(extendable=False),
    "componentCounts": _M7_COUNTS,
}

TRAINING_M7: dict = {
    "filename": "Training module 7 — investment and capacity expansion",
    "example": {
        "label": "Training: module 7 model (end of module)",
        "description": (
            "The model the \"Power market modelling\" course has built by the end of module 7 — a full "
            "year with wind, solar, the transmission line and the battery all offered to the optimiser at "
            "overnight capital costs. At a 5% discount rate it builds wind to 150 MW, solar to 25 MW and "
            "the line to 141 MW, and declines the battery. Objective 18,079,255."
        ),
        "order": 97,
    },
    "sheets": _m7_sheets(extendable=True),
    "componentCounts": _M7_COUNTS,
}

# ── Module 10 — the ring "10 · Meshed networks and power flow" studies ───────
# Deliberately NOT a continuation of module 7's year. Module 10 teaches a
# mechanism — how power divides between parallel paths — and a mechanism is only
# visible in a model small enough to compute by hand. Three 380 kV buses in a
# ring, equal reactance on every line, cheap coal at bus_1, dear gas at bus_2,
# all the demand at bus_3.
#
# Uncongested, it solves to 5,400 and the 90 MW divides 60 / 30: two thirds down
# the direct line_13 and one third the long way round, because the indirect path
# has twice the reactance. Cap line_13 at 50 MW and the answer becomes 8,100 with
# nodal prices of 20 / 50 / 80 — a price at bus_3 above every generator in the
# model. Both figures are pinned in ``backend/tests/test_training_checkpoints.py``.
#
# Impedances are per-km-realistic for a 380 kV overhead circuit (r ≈ 0.03 Ω/km,
# x ≈ 0.3 Ω/km over 100 km) rather than the token 0.1 the earlier modules carry:
# module 10 runs an AC power flow, and only real impedances produce a voltage
# drop and a loss figure worth reading.
_M10_LINE_X = 30.0
_M10_LINE_R = 3.0

TRAINING_M10: dict = {
    "filename": "Training module 10 — meshed network",
    "example": {
        "label": "Training: module 10 ring network (start of module)",
        "description": (
            "Three 380 kV buses in a ring with equal reactance on every line — the network the \"Power "
            "market modelling\" course uses in module 10 to show how power divides between parallel "
            "paths. Cheap coal at bus_1, dear gas at bus_2, 90 MW of demand at bus_3. Solves to 5,400 "
            "with 60 MW on the direct line and 30 MW the long way round."
        ),
        "order": 100,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in SNAPSHOTS]),
        ("network", "static", [{"name": "ring-network"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
            {"name": "bus_2", "v_nom": 380.0, "x": 129.0, "y": 35.2, "carrier": "AC"},
            {"name": "bus_3", "v_nom": 380.0, "x": 126.8, "y": 35.1, "carrier": "AC"},
        ]),
        ("generators", "static", [
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 200.0, "marginal_cost": 20.0, "efficiency": 0.4},
            {"name": "gas_2", "bus": "bus_2", "carrier": "gas",
             "p_nom": 100.0, "marginal_cost": 50.0, "efficiency": 0.5},
        ]),
        ("loads", "static", [
            {"name": "load_3", "bus": "bus_3", "carrier": "AC", "p_set": 90.0},
        ]),
        # Every line the same reactance, so the split is set by how many lines a
        # path has rather than by anything else — which is what makes the two
        # thirds / one third arithmetic doable in your head.
        ("lines", "static", [
            {"name": "line_12", "bus0": "bus_1", "bus1": "bus_2",
             "s_nom": 200.0, "x": _M10_LINE_X, "r": _M10_LINE_R, "length": 100.0},
            {"name": "line_23", "bus0": "bus_2", "bus1": "bus_3",
             "s_nom": 200.0, "x": _M10_LINE_X, "r": _M10_LINE_R, "length": 100.0},
            {"name": "line_13", "bus0": "bus_1", "bus1": "bus_3",
             "s_nom": 200.0, "x": _M10_LINE_X, "r": _M10_LINE_R, "length": 100.0},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": s, "load_3": 90.0} for s in SNAPSHOTS
        ]),
    ],
    "componentCounts": {"buses": 3, "generators": 2, "loads": 1, "carriers": 3, "lines": 3},
}

# ── Module 11 — the fleet "11 · Commitment and operating constraints" runs ───
# Six hours with a windy midday dip: demand 90 / 90 / 50 / 50 / 90 / 90 against
# a wind profile that is zero except in the two dip hours, where it is full.
# That is the whole design. It puts a committable coal unit in front of a real
# decision — hold minimum stable output through the dip and push out free wind,
# or shut down for two hours and pay to restart — and the start-up cost decides
# which, so one number flips the answer.
#
#   as shipped (start_up_cost 3000)   8,800 · coal holds 40 MW · 70 MW of wind spilt an hour
#   start_up_cost 1000                7,200 + 1,000 start-up = 8,200 · coal stops
#   committable cleared               7,200 · what the plant would do if physics let it
#   Force LP                          7,200 · the relaxation, and the only run that prices
#
# Pinned in ``backend/tests/test_training_checkpoints.py``.
_M11_SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
_M11_DEMAND = [90.0, 90.0, 50.0, 50.0, 90.0, 90.0]
_M11_WIND = [0.0, 0.0, 1.0, 1.0, 0.0, 0.0]

TRAINING_M11: dict = {
    "filename": "Training module 11 — commitment",
    "example": {
        "label": "Training: module 11 committable fleet (start of module)",
        "description": (
            "One bus, six hours and a windy midday dip — the model the \"Power market modelling\" "
            "course uses in module 11 to show what a plant that cannot switch on and off freely does "
            "to a dispatch. A committable coal unit with a 40 MW minimum stable output and a 3,000 "
            "start-up cost, a gas unit and wind. Solves to 8,800 with the coal held on through the dip."
        ),
        "order": 101,
    },
    "sheets": [
        ("snapshots", "static", [{"snapshot": s} for s in _M11_SNAPS]),
        ("network", "static", [{"name": "commitment-fleet"}]),
        ("carriers", "static", [
            {"name": "AC", "co2_emissions": 0.0},
            {"name": "gas", "co2_emissions": 0.2},
            {"name": "coal", "co2_emissions": 0.34},
            {"name": "wind", "co2_emissions": 0.0},
        ]),
        ("buses", "static", [
            {"name": "bus_1", "v_nom": 380.0, "x": 127.0, "y": 37.5, "carrier": "AC"},
        ]),
        # coal_1 carries every commitment attribute the module teaches, in the
        # order the learner meets them: the flag, the floor, the price of a
        # start, and how long it must stay off once it stops.
        ("generators", "static", [
            {"name": "coal_1", "bus": "bus_1", "carrier": "coal",
             "p_nom": 100.0, "marginal_cost": 20.0, "efficiency": 0.4,
             "committable": True, "p_min_pu": 0.4,
             "start_up_cost": 3000.0, "min_down_time": 2},
            {"name": "gas_1", "bus": "bus_1", "carrier": "gas",
             "p_nom": 100.0, "marginal_cost": 50.0, "efficiency": 0.5},
            {"name": "wind_1", "bus": "bus_1", "carrier": "wind",
             "p_nom": 80.0, "marginal_cost": 0.0, "efficiency": 1.0},
        ]),
        ("loads", "static", [
            {"name": "load_1", "bus": "bus_1", "carrier": "AC", "p_set": 90.0},
        ]),
        ("loads-p_set", "series", [
            {"snapshot": s, "load_1": d} for s, d in zip(_M11_SNAPS, _M11_DEMAND)
        ]),
        ("generators-p_max_pu", "series", [
            {"snapshot": s, "wind_1": w} for s, w in zip(_M11_SNAPS, _M11_WIND)
        ]),
    ],
    "componentCounts": {"buses": 1, "generators": 3, "loads": 1, "carriers": 4},
}

CHECKPOINTS = {
    "training_m2": TRAINING_M2,
    "training_m3": TRAINING_M3,
    "training_m4": TRAINING_M4,
    "training_m5": TRAINING_M5,
    "training_m6": TRAINING_M6,
    "training_m7_year": TRAINING_M7_YEAR,
    "training_m7": TRAINING_M7,
    "training_m10": TRAINING_M10,
    "training_m11": TRAINING_M11,
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

    snapshots = [r["snapshot"] for r in spec["sheets"][0][2]]
    meta = {
        "sessionId": "__example_author__",
        "filename": spec["filename"],
        "scenarioName": "",
        "savedAt": "2026-08-03T00:00:00+00:00",
        "sheets": sheet_meta,
        "snapshotCount": len(snapshots),
        "snapshotStart": snapshots[0].replace("T", " "),
        "snapshotEnd": snapshots[-1].replace("T", " "),
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
