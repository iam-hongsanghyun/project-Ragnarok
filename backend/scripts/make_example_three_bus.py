"""Author the bundled "Three-bus example" starter project.

Builds a tiny, solvable 3-bus PyPSA network, solves it to prove feasibility,
converts it to the app's model JSON with the backend's own converter, writes it
to a throwaway session as a SQLite ``project.db`` (sqlite_store format), then
snapshots that db into ``backend/data/examples/three_bus/``. Re-runnable.

    .venv-pypsa/bin/python -m backend.scripts.make_example_three_bus
"""
from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd
import pypsa

from backend.app import model_store, session_store
from backend.app.main import _network_to_model_json

AUTHOR_SESSION = "__example_author__"
EXAMPLE_ID = "three_bus"
HOURS = 24


def build_network() -> pypsa.Network:
    n = pypsa.Network()
    n.name = "Three-bus example"
    n.set_snapshots(pd.date_range("2030-06-01", periods=HOURS, freq="h"))

    n.add("Carrier", "AC")
    n.add("Carrier", "gas", co2_emissions=0.18)
    n.add("Carrier", "wind", co2_emissions=0.0)
    n.add("Carrier", "solar", co2_emissions=0.0)

    # Three buses, loosely placed over the Korean peninsula so the map looks real.
    n.add("Bus", "north",   v_nom=380, carrier="AC", x=127.05, y=37.80)
    n.add("Bus", "central", v_nom=380, carrier="AC", x=127.30, y=36.60)
    n.add("Bus", "south",   v_nom=380, carrier="AC", x=128.60, y=35.20)

    n.add("Line", "north-central", bus0="north",   bus1="central", x=0.10, r=0.01, s_nom=2000)
    n.add("Line", "central-south", bus0="central", bus1="south",   x=0.10, r=0.01, s_nom=2000)

    # Dispatchable gas big enough to cover peak demand alone → always feasible.
    n.add("Generator", "gas_central", bus="central", carrier="gas", p_nom=1000, marginal_cost=70)
    # Variable renewables with simple daily profiles.
    wind_pu = 0.30 + 0.25 * np.sin(np.linspace(0.0, np.pi, HOURS))
    n.add("Generator", "wind_north", bus="north", carrier="wind", p_nom=500, marginal_cost=0.0,
          p_max_pu=wind_pu)
    solar_pu = np.clip(np.sin(np.linspace(-1.2, 4.2, HOURS)), 0.0, 1.0) * 0.85
    n.add("Generator", "solar_south", bus="south", carrier="solar", p_nom=400, marginal_cost=0.0,
          p_max_pu=solar_pu)

    # Demand with a daily shape (time-varying p_set).
    shape = 0.70 + 0.30 * np.sin(np.linspace(0.0, 2 * np.pi, HOURS))
    n.add("Load", "load_north",   bus="north",   p_set=200 * shape)
    n.add("Load", "load_central", bus="central", p_set=300 * shape)
    n.add("Load", "load_south",   bus="south",   p_set=150 * shape)
    return n


def main() -> None:
    n = build_network()

    # Prove it solves before we ship it — on a copy, so solving doesn't pollute
    # the network we convert (optimize() builds non-input `sub_networks` etc.).
    probe = n.copy()
    probe.optimize(solver_name="highs")
    assert probe.objective is not None and np.isfinite(probe.objective), "example network did not solve"
    print(f"solved: objective={probe.objective:,.1f}")

    model = _network_to_model_json(n)
    # Drop auto-populated non-input catalogs / computed components — an example
    # should carry only the user-authored input sheets.
    for drop in ("sub_networks", "line_types", "transformer_types"):
        model.pop(drop, None)
    for required in ("buses", "generators", "loads", "lines", "carriers", "snapshots"):
        assert required in model and model[required], f"converter dropped sheet: {required}"
    print("model sheets:", sorted(model.keys()))

    model_store.save_model(AUTHOR_SESSION, model, filename="Three-bus example")
    src = session_store.SESSION_DIR / AUTHOR_SESSION / "project.db"
    assert src.exists(), f"author session db missing: {src}"

    dest = session_store.SESSION_DIR.parent / "examples" / EXAMPLE_ID
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest / "project.db")
    (dest / "meta.json").write_text(
        json.dumps(
            {
                "label": "Three-bus example",
                "description": "A small 3-bus grid (gas, wind, solar) with hourly demand — solves out of the box. A good starting point to learn the workflow.",
                "order": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    shutil.rmtree(session_store.SESSION_DIR / AUTHOR_SESSION, ignore_errors=True)
    print(f"wrote {dest / 'project.db'}")


if __name__ == "__main__":
    main()
