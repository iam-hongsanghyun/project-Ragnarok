"""Author the bundled starter projects ("Start with Examples").

Each example is built as a PyPSA network, SOLVED with HiGHS to prove it's
feasible, converted to the app's model JSON with the backend's own converter,
written to a throwaway session as a SQLite ``project.db`` (sqlite_store format),
and snapshotted into ``backend/data/examples/<id>/project.db`` with its
metadata embedded in the db's ``_kv`` (key "example") — no JSON/xlsx sidecars.

Re-runnable; regenerates every example. Add one by writing a ``build_*``
function and appending it to ``EXAMPLES``.

    .venv-pypsa/bin/python -m backend.scripts.make_examples [example_id ...]
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd
import pypsa

from backend.app import model_store, session_store, sqlite_store
from backend.app.main import _network_to_model_json

AUTHOR_SESSION = "__example_author__"
#: Cost columns follow PyPSA: overnight_cost + discount_rate + lifetime, annuitised by PyPSA itself.
EXAMPLE_DISCOUNT = 0.05
EXAMPLE_LIFETIME = 20
EXAMPLE_KV_KEY = "example"  # matches routers/examples.py
# Non-input catalogs / computed components the converter may emit; an example
# carries only user-authored input sheets.
DROP_SHEETS = ("sub_networks", "line_types", "transformer_types")


@dataclass
class Example:
    id: str
    label: str
    description: str
    order: int
    build: Callable[[], pypsa.Network]
    # Optional hook run on the converted model JSON, for columns PyPSA itself has no attribute
    # for (the `owner` tag the Company views group on).
    tag: Callable[[dict], None] | None = None


# ── Builders ────────────────────────────────────────────────────────────────


def build_three_bus() -> pypsa.Network:
    n = pypsa.Network()
    n.name = "Three-bus example"
    n.set_snapshots(pd.date_range("2030-06-01", periods=24, freq="h"))
    n.add("Carrier", "AC")
    n.add("Carrier", "gas", co2_emissions=0.18)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Carrier", "solar", co2_emissions=0.0)
    n.add("Bus", "north",   v_nom=380, carrier="AC", x=127.05, y=37.80)
    n.add("Bus", "central", v_nom=380, carrier="AC", x=127.30, y=36.60)
    n.add("Bus", "south",   v_nom=380, carrier="AC", x=128.60, y=35.20)
    n.add("Line", "north-central", bus0="north",   bus1="central", x=0.10, r=0.01, s_nom=2000)
    n.add("Line", "central-south", bus0="central", bus1="south",   x=0.10, r=0.01, s_nom=2000)
    n.add("Generator", "gas_central", bus="central", carrier="gas", p_nom=1000, marginal_cost=70)
    n.add("Generator", "wind_north", bus="north", carrier="wind", p_nom=500, marginal_cost=0.0,
          p_max_pu=0.30 + 0.25 * np.sin(np.linspace(0.0, np.pi, 24)))
    n.add("Generator", "solar_south", bus="south", carrier="solar", p_nom=400, marginal_cost=0.0,
          p_max_pu=np.clip(np.sin(np.linspace(-1.2, 4.2, 24)), 0.0, 1.0) * 0.85)
    shape = 0.70 + 0.30 * np.sin(np.linspace(0.0, 2 * np.pi, 24))
    n.add("Load", "load_north",   bus="north",   p_set=200 * shape)
    n.add("Load", "load_central", bus="central", p_set=300 * shape)
    n.add("Load", "load_south",   bus="south",   p_set=150 * shape)
    return n


def build_storage() -> pypsa.Network:
    """Single region, solar + wind + a battery that shifts surplus into the
    evening, with a gas backup. Two days so the storage cycles visibly."""
    n = pypsa.Network()
    n.name = "Renewables + storage"
    hours = 48
    n.set_snapshots(pd.date_range("2030-06-01", periods=hours, freq="h"))
    n.add("Carrier", "AC")
    n.add("Carrier", "gas", co2_emissions=0.18)
    n.add("Carrier", "solar", co2_emissions=0.0)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Carrier", "battery", co2_emissions=0.0)
    n.add("Bus", "grid", v_nom=110, carrier="AC", x=126.98, y=37.57)
    n.add("Generator", "gas", bus="grid", carrier="gas", p_nom=600, marginal_cost=85)
    daylight = np.clip(np.sin((np.arange(hours) % 24 - 6) / 12 * np.pi), 0, 1)
    n.add("Generator", "solar", bus="grid", carrier="solar", p_nom=700, marginal_cost=0.0,
          p_max_pu=0.9 * daylight)
    n.add("Generator", "wind", bus="grid", carrier="wind", p_nom=300, marginal_cost=0.0,
          p_max_pu=0.35 + 0.25 * np.sin(np.linspace(0.0, 4 * np.pi, hours)))
    n.add("StorageUnit", "battery", bus="grid", carrier="battery", p_nom=250, max_hours=4,
          efficiency_store=0.95, efficiency_dispatch=0.95, cyclic_state_of_charge=True,
          marginal_cost=1.0)
    shape = 0.65 + 0.35 * np.clip(np.sin((np.arange(hours) % 24 - 9) / 12 * np.pi), -0.4, 1)
    n.add("Load", "demand", bus="grid", p_set=500 * shape)
    return n


def build_capacity_expansion() -> pypsa.Network:
    """Greenfield single bus: every generator is extendable, so the optimiser
    SIZES the fleet (p_nom_opt) to meet a week of demand at least cost."""
    n = pypsa.Network()
    n.name = "Capacity expansion"
    hours = 168
    n.set_snapshots(pd.date_range("2030-01-01", periods=hours, freq="h"))
    n.add("Carrier", "AC")
    n.add("Carrier", "gas", co2_emissions=0.18)
    n.add("Carrier", "solar", co2_emissions=0.0)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Bus", "zone", v_nom=380, carrier="AC", x=127.0, y=37.5)
    # Overnight capital costs (currency/MW) + marginal costs -> a real trade-off. PyPSA annuitises
    # overnight_cost with the row's own discount_rate and lifetime (x n.nyears for the 168 h horizon).
    n.add("Generator", "gas", bus="zone", carrier="gas", p_nom_extendable=True,
          overnight_cost=60000, discount_rate=EXAMPLE_DISCOUNT, lifetime=EXAMPLE_LIFETIME, marginal_cost=75)
    n.add("Generator", "solar", bus="zone", carrier="solar", p_nom_extendable=True,
          overnight_cost=45000, discount_rate=EXAMPLE_DISCOUNT, lifetime=EXAMPLE_LIFETIME, marginal_cost=0.0,
          p_max_pu=np.clip(np.sin((np.arange(hours) % 24 - 6) / 12 * np.pi), 0, 1) * 0.9)
    n.add("Generator", "wind", bus="zone", carrier="wind", p_nom_extendable=True,
          overnight_cost=90000, discount_rate=EXAMPLE_DISCOUNT, lifetime=EXAMPLE_LIFETIME, marginal_cost=0.0,
          p_max_pu=0.30 + 0.25 * np.sin(np.linspace(0.0, 10 * np.pi, hours)))
    shape = 0.70 + 0.30 * np.sin((np.arange(hours) % 24) / 24 * 2 * np.pi)
    n.add("Load", "demand", bus="zone", p_set=800 * shape)
    return n


# Company views group assets on an `owner` column of generators / storage_units / stores. PyPSA has
# no such attribute, so it is written onto the converted rows rather than into the network.
COMPANY_OWNERS: dict[str, dict[str, str]] = {
    "generators": {
        "wind_north": "Northwind Energy",
        "gas_north": "Northwind Energy",
        "gas_central": "Central Thermal",
        "solar_south": "Southern Solar",
    },
    "storage_units": {"battery_south": "Southern Solar"},
}


def tag_company_owners(model: dict) -> None:
    """Write the owner column. `gas_south` stays untagged: its emissions are the Unassigned row."""
    for sheet, owners in COMPANY_OWNERS.items():
        for row in model.get(sheet, []):
            row["owner"] = owners.get(str(row.get("name")), "")


def build_company_view() -> pypsa.Network:
    """Three-bus grid with a constrained north-central line and four owners' assets.

    Prices split across buses once the line binds, so each company earns a different capture
    price; one untagged gas unit leaves a non-empty Unassigned row.
    """
    n = pypsa.Network()
    n.name = "Three companies"
    hours = 48
    n.set_snapshots(pd.date_range("2030-06-01", periods=hours, freq="h"))
    n.add("Carrier", "AC")
    n.add("Carrier", "gas", co2_emissions=0.18)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Carrier", "solar", co2_emissions=0.0)
    n.add("Carrier", "battery", co2_emissions=0.0)
    n.add("Bus", "north", v_nom=380, carrier="AC", x=127.05, y=37.80)
    n.add("Bus", "central", v_nom=380, carrier="AC", x=127.30, y=36.60)
    n.add("Bus", "south", v_nom=380, carrier="AC", x=128.60, y=35.20)
    n.add("Line", "north-central", bus0="north", bus1="central", x=0.10, r=0.01, s_nom=250)
    n.add("Line", "central-south", bus0="central", bus1="south", x=0.10, r=0.01, s_nom=2000)
    hour = np.arange(hours) % 24
    n.add("Generator", "wind_north", bus="north", carrier="wind", p_nom=500, marginal_cost=0.0,
          p_max_pu=0.35 + 0.30 * np.sin(np.linspace(0.0, 4 * np.pi, hours)) ** 2)
    n.add("Generator", "gas_north", bus="north", carrier="gas", p_nom=200, marginal_cost=95)
    n.add("Generator", "gas_central", bus="central", carrier="gas", p_nom=700, marginal_cost=70)
    # Deliberately left without an owner: its emissions are the Unassigned row.
    n.add("Generator", "gas_south", bus="south", carrier="gas", p_nom=150, marginal_cost=55)
    n.add("Generator", "solar_south", bus="south", carrier="solar", p_nom=450, marginal_cost=0.0,
          p_max_pu=np.clip(np.sin((hour - 6) / 12 * np.pi), 0, 1) * 0.85)
    n.add("StorageUnit", "battery_south", bus="south", carrier="battery", p_nom=120, max_hours=4,
          efficiency_store=0.95, efficiency_dispatch=0.95, cyclic_state_of_charge=True, marginal_cost=1.0)
    shape = 0.70 + 0.30 * np.sin((hour - 9) / 24 * 2 * np.pi)
    n.add("Load", "load_north", bus="north", p_set=150 * shape)
    n.add("Load", "load_central", bus="central", p_set=350 * shape)
    n.add("Load", "load_south", bus="south", p_set=300 * shape)
    return n


# ── Training course examples (modules 16 and 17) ────────────────────────────
#
# Authored here rather than by hand so the numbers the lessons state can be
# regenerated: ``make_examples training_m16 training_m16_start training_m17 ...``.
# Every figure the lessons quote is pinned in tests/test_training_checkpoints.py.

PATHWAY_PERIODS = (2030, 2040, 2050)
#: Years each period stands for, and the discount rate the objective weights are built from.
PATHWAY_YEARS = 10
PATHWAY_DISCOUNT = 0.05
#: Emission caps in tCO2 PER PERIOD (annual tonnes x PATHWAY_YEARS): 1.0 / 0.4 / 0.03 MtCO2 a year.
PATHWAY_CO2_CAPS = {2030: 10_000_000.0, 2040: 4_000_000.0, 2050: 300_000.0}


def pathway_objective_weights(
    periods: tuple[int, ...] = PATHWAY_PERIODS,
    years: int = PATHWAY_YEARS,
    rate: float = PATHWAY_DISCOUNT,
) -> dict[int, float]:
    r"""Objective weight of each investment period: the discounted year count it stands for.

    Algorithm:
        $$ w_p = \sum_{k=0}^{Y-1} (1+r)^{-(p - p_0 + k)} $$
        ASCII: w_p = sum_{k=0..Y-1} (1+r)^-(p - p0 + k)
        p: period label (calendar year); p_0: first period (base year of the present
        value); Y: years the period stands for (years); r: discount rate (1/year).
    """
    base = periods[0]
    return {p: sum((1.0 + rate) ** -(p - base + k) for k in range(years)) for p in periods}


def build_pathway(with_caps: bool = False) -> pypsa.Network:
    """Single-bus system over three investment periods (2030 / 2040 / 2050).

    Each period is one representative day (24 hourly snapshots) standing for a
    year: ``objective`` and ``generators`` weights of 365, ``stores`` weight 1 so
    the battery's state of charge still integrates hours. Coal retires through
    ``build_year`` + ``lifetime``; wind, solar and battery are offered as one
    vintage per period at falling overnight costs; demand grows 20% a decade.
    ``with_caps`` adds one ``primary_energy`` CO2 cap per period.
    """
    n = pypsa.Network()
    n.name = "Multi-year pathway"
    hours = 24
    stamps = [
        (p, pd.Timestamp(year=p, month=6, day=1) + pd.Timedelta(hours=h))
        for p in PATHWAY_PERIODS for h in range(hours)
    ]
    n.set_snapshots(pd.MultiIndex.from_tuples(stamps, names=["period", "timestep"]))
    n.investment_periods = list(PATHWAY_PERIODS)
    n.snapshot_weightings["objective"] = 365.0
    n.snapshot_weightings["generators"] = 365.0
    n.snapshot_weightings["stores"] = 1.0
    for name, co2 in (("AC", 0.0), ("coal", 0.34), ("gas", 0.20), ("wind", 0.0), ("solar", 0.0), ("battery", 0.0)):
        n.add("Carrier", name, co2_emissions=co2)
    n.add("Bus", "grid", carrier="AC", v_nom=380, x=127.0, y=37.5)

    h = np.arange(hours)
    solar = np.round(np.clip(np.sin((h - 6) / 12 * np.pi), 0, 1) * 0.9, 4)
    wind = np.round(0.35 + 0.15 * np.cos((h - 3) / 24 * 2 * np.pi), 4)
    shape = np.round(0.70 + 0.30 * np.exp(-(((h - 19) / 3.0) ** 2)) + 0.15 * np.exp(-(((h - 9) / 3.0) ** 2)), 4)
    peak = {2030: 200.0, 2040: 240.0, 2050: 280.0}
    load = pd.Series(0.0, index=n.snapshots)
    for p in PATHWAY_PERIODS:
        load.loc[p] = peak[p] * shape
    n.add("Load", "demand", bus="grid", p_set=load)

    n.add("Generator", "coal_old", bus="grid", carrier="coal", p_nom=150, marginal_cost=20,
          efficiency=0.4, build_year=1985, lifetime=50)
    n.add("Generator", "coal_new", bus="grid", carrier="coal", p_nom=150, marginal_cost=20,
          efficiency=0.4, build_year=2000, lifetime=45)
    n.add("Generator", "gas_ccgt", bus="grid", carrier="gas", p_nom=150, marginal_cost=55,
          efficiency=0.5, build_year=2010, lifetime=45)
    wind_cost = {2030: 1_600_000, 2040: 1_300_000, 2050: 1_000_000}
    solar_cost = {2030: 900_000, 2040: 650_000, 2050: 450_000}
    batt_cost = {2030: 500_000, 2040: 350_000, 2050: 250_000}
    for p in PATHWAY_PERIODS:
        n.add("Generator", f"wind_{p}", bus="grid", carrier="wind", p_nom_extendable=True, p_nom_max=200,
              overnight_cost=wind_cost[p], discount_rate=PATHWAY_DISCOUNT, lifetime=25, build_year=p, p_max_pu=np.tile(wind, len(PATHWAY_PERIODS)))
        n.add("Generator", f"solar_{p}", bus="grid", carrier="solar", p_nom_extendable=True, p_nom_max=250,
              overnight_cost=solar_cost[p], discount_rate=PATHWAY_DISCOUNT, lifetime=25, build_year=p, p_max_pu=np.tile(solar, len(PATHWAY_PERIODS)))
        n.add("StorageUnit", f"batt_{p}", bus="grid", carrier="battery", p_nom_extendable=True, p_nom_max=100,
              max_hours=4, efficiency_store=0.92, efficiency_dispatch=0.92, cyclic_state_of_charge=True,
              overnight_cost=batt_cost[p], discount_rate=PATHWAY_DISCOUNT, lifetime=15, build_year=p)
    if with_caps:
        for p, tonnes in PATHWAY_CO2_CAPS.items():
            n.add("GlobalConstraint", f"co2_cap_{p}", type="primary_energy", carrier_attribute="co2_emissions",
                  sense="<=", constant=tonnes, investment_period=p)
    return n


def tag_pathway_settings(model: dict) -> None:
    """Carry the Settings -> Multi-year planning table the module has the learner type.

    Written the way the app writes it (``RAGNAROK_Pathway`` / ``RAGNAROK_PathwayPeriods``),
    so loading the finished checkpoint also restores the pathway settings.
    """
    weights = pathway_objective_weights()
    model["RAGNAROK_Pathway"] = [{
        "enabled": True, "planningMode": "pathway",
        "snapshotMappingMode": "explicit_period_column", "selectedPeriod": PATHWAY_PERIODS[0],
    }]
    model["RAGNAROK_PathwayPeriods"] = [
        {"period": p, "objectiveWeight": round(weights[p], 4), "yearsWeight": PATHWAY_YEARS}
        for p in PATHWAY_PERIODS
    ]


# Module 17 — a solar-heavy single bus over three days, the middle one overcast.
BESS_DAYS = 3
BESS_SUN_DAYS = (1.0, 0.45, 0.9)


def build_bess_system(battery: str = "none") -> pypsa.Network:
    """Solar-heavy single bus for the battery module: midday surplus, an evening peak.

    700 MW of solar against a 393 MW evening peak; a 300 MW CCGT (80 per MWh) and a
    200 MW peaker (140 per MWh) cover what solar cannot. ``battery``: ``"none"`` (the
    start of module 17), ``"unit"`` (the finished module: a 100 MW / 4 h StorageUnit at
    0.95 each way) or ``"store"`` (a Store + two Links whose power and energy are
    sized independently — the step 10 comparison).
    """
    hours = 24 * BESS_DAYS
    n = pypsa.Network()
    n.name = "Solar-heavy system" + ("" if battery == "none" else f" + battery ({battery})")
    n.set_snapshots(pd.date_range("2030-06-01", periods=hours, freq="h"))
    for name, co2 in (("AC", 0.0), ("gas", 0.20), ("solar", 0.0), ("battery", 0.0)):
        n.add("Carrier", name, co2_emissions=co2)
    n.add("Bus", "grid", carrier="AC", v_nom=110, x=127.0, y=37.5)
    h = np.arange(hours) % 24
    day = np.arange(hours) // 24
    sun = np.round(np.clip(np.sin((h - 6) / 12 * np.pi), 0, 1) * np.array(BESS_SUN_DAYS)[day] * 0.9, 4)
    shape = np.round(0.55 + 0.45 * np.exp(-(((h - 19.5) / 2.5) ** 2)) + 0.10 * np.exp(-(((h - 8) / 2.0) ** 2)), 4)
    n.add("Generator", "solar", bus="grid", carrier="solar", p_nom=700, marginal_cost=0.0, p_max_pu=sun)
    n.add("Generator", "gas_ccgt", bus="grid", carrier="gas", p_nom=300, marginal_cost=80, efficiency=0.5)
    n.add("Generator", "gas_peaker", bus="grid", carrier="gas", p_nom=200, marginal_cost=140, efficiency=0.35)
    n.add("Load", "demand", bus="grid", p_set=400.0 * shape)
    if battery == "unit":
        n.add("StorageUnit", "batt", bus="grid", carrier="battery", p_nom=100, max_hours=4,
              efficiency_store=0.95, efficiency_dispatch=0.95, standing_loss=0.0,
              cyclic_state_of_charge=True)
    elif battery == "store":
        # Overnight costs per MW / MWh; Ragnarok annuitises them and pro-rates to the 72 h window.
        n.add("Bus", "batt_bus", carrier="battery", v_nom=0.0, x=127.0, y=37.6)
        n.add("Store", "batt_store", bus="batt_bus", carrier="battery", e_nom_extendable=True, e_nom_max=3200,
              e_cyclic=True, overnight_cost=200_000, discount_rate=EXAMPLE_DISCOUNT, lifetime=15)
        n.add("Link", "batt_charge", bus0="grid", bus1="batt_bus", carrier="battery", efficiency=0.95,
              p_nom_extendable=True, p_nom_max=400, overnight_cost=100_000, discount_rate=EXAMPLE_DISCOUNT, lifetime=15)
        n.add("Link", "batt_discharge", bus0="batt_bus", bus1="grid", carrier="battery", efficiency=0.95,
              p_nom_extendable=True, p_nom_max=400, overnight_cost=100_000, discount_rate=EXAMPLE_DISCOUNT, lifetime=15)
    return n



EXAMPLES: list[Example] = [
    Example(
        id="three_bus",
        label="Three-bus example",
        description="A small 3-bus grid (gas, wind, solar) with hourly demand — solves out of the box. A good starting point to learn the workflow.",
        order=1,
        build=build_three_bus,
    ),
    Example(
        id="renewables_storage",
        label="Renewables + storage",
        description="One region with solar, wind and a battery that shifts daytime surplus into the evening, backed by gas. Shows how storage cycles over two days.",
        order=2,
        build=build_storage,
    ),
    Example(
        id="capacity_expansion",
        label="Capacity expansion",
        description="Greenfield single zone where the optimiser SIZES an extendable gas/solar/wind fleet to meet a week of demand at least cost. Explore the built capacities in Analytics.",
        order=3,
        build=build_capacity_expansion,
    ),
    Example(
        id="company_view",
        label="Three companies",
        description="Three-bus grid whose generators and a battery are tagged with an owner column, so Analytics shows the "
                    "company breakdown, income statement and comparison, plus an Unassigned row for the one untagged gas unit.",
        order=4,
        build=build_company_view,
        tag=tag_company_owners,
    ),
    Example(
        id="training_m16_start",
        label="Training: module 16 start (a three-period system)",
        description="Module 16's starting model: one bus, three investment periods (2030 / 2040 / 2050) each a representative day "
                    "standing for a year, two coal units that retire, a gas unit, and wind / solar / battery offered as one vintage per "
                    "period at falling cost. The snapshots carry a period column. Nothing is configured yet: no pathway settings, no CO2 cap.",
        order=102,
        build=build_pathway,
    ),
    Example(
        id="training_m16",
        label="Training: module 16 model (end of module)",
        description="Module 16 finished: the three-period system with the Settings -> Multi-year planning table filled in "
                    "(objective weights 8.1078 / 4.9775 / 3.0558, 10 years each, 5% discount rate) and a CO2 cap per period "
                    "(10 / 4 / 0.3 MtCO2 per period, i.e. 1.0 / 0.4 / 0.03 Mt a year).",
        order=103,
        build=lambda: build_pathway(with_caps=True),
        tag=tag_pathway_settings,
    ),
    Example(
        id="training_m17_start",
        label="Training: module 17 start (a solar-heavy system)",
        description="Module 17's starting model: 700 MW of solar against a 393 MW evening peak over three days (the middle one overcast), "
                    "a 300 MW CCGT at 80 and a 200 MW peaker at 140. No battery yet.",
        order=104,
        build=lambda: build_bess_system("none"),
    ),
    Example(
        id="training_m17",
        label="Training: module 17 model (end of module)",
        description="Module 17 finished: the solar-heavy system with a 100 MW / 4 h battery at 0.95 charging and 0.95 discharging "
                    "efficiency, no standing loss and a cyclic state of charge.",
        order=105,
        build=lambda: build_bess_system("unit"),
    ),
    Example(
        id="training_m17_store",
        label="Training: module 17 Store + Link battery (step 10)",
        description="The solar-heavy system with the battery written as a Store and two Links, so its charging power, discharging "
                    "power and energy capacity are three independent decisions. Capital costs are overnight; the module's step 10 sizes it.",
        order=106,
        build=lambda: build_bess_system("store"),
    ),
]


def author(ex: Example) -> None:
    n = ex.build()
    probe = n.copy()
    # A multi-period example must be probed as one, or PyPSA refuses the (period, timestep) index.
    probe.optimize(solver_name="highs", include_objective_constant=False,
                   multi_investment_periods=bool(getattr(probe, "has_investment_periods", False)))
    assert probe.objective is not None and np.isfinite(probe.objective), f"{ex.id} did not solve"

    model = _network_to_model_json(n)
    for drop in DROP_SHEETS:
        model.pop(drop, None)
    for required in ("buses", "generators", "loads", "carriers", "snapshots"):
        assert required in model and model[required], f"{ex.id}: converter dropped {required}"

    if ex.tag is not None:
        ex.tag(model)

    model_store.save_model(AUTHOR_SESSION, model, filename=ex.label)
    src = session_store.SESSION_DIR / AUTHOR_SESSION / "project.db"
    sqlite_store.write_kv(src, EXAMPLE_KV_KEY, {"label": ex.label, "description": ex.description, "order": ex.order})
    dest = session_store.SESSION_DIR.parent / "examples" / ex.id
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest / "project.db")
    shutil.rmtree(session_store.SESSION_DIR / AUTHOR_SESSION, ignore_errors=True)
    print(f"  ✓ {ex.id}: objective={probe.objective:,.0f}, sheets={sorted(model.keys())}")


def main(only: list[str] | None = None) -> None:
    """Regenerate every example, or just those named on the command line."""
    import sys

    only = only if only is not None else sys.argv[1:]
    for ex in EXAMPLES:
        if only and ex.id not in only:
            continue
        print(f"authoring {ex.id}…")
        author(ex)
    print("done")


if __name__ == "__main__":
    main()
