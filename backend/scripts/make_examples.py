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
    # Annualised capital costs (currency/MW) + marginal costs → a real trade-off.
    n.add("Generator", "gas", bus="zone", carrier="gas", p_nom_extendable=True,
          capital_cost=60000, marginal_cost=75)
    n.add("Generator", "solar", bus="zone", carrier="solar", p_nom_extendable=True,
          capital_cost=45000, marginal_cost=0.0,
          p_max_pu=np.clip(np.sin((np.arange(hours) % 24 - 6) / 12 * np.pi), 0, 1) * 0.9)
    n.add("Generator", "wind", bus="zone", carrier="wind", p_nom_extendable=True,
          capital_cost=90000, marginal_cost=0.0,
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
]


def author(ex: Example) -> None:
    n = ex.build()
    probe = n.copy()
    probe.optimize(solver_name="highs", include_objective_constant=False)
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
