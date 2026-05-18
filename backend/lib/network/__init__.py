from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..config import load_system_defaults
from ..models import RunPayload
from ..profiles import modeled_period_factor, snapshot_settings, workbook_snapshot_index
from ..utils.coerce import number, text
from ..utils.workbook import workbook_rows
from .buses import add_buses, add_loads
from .constraints import add_global_constraints
from .generators import add_generators, add_grid_imports_and_shedding
from .lines import add_links, add_lines, add_shunt_impedances, add_transformers
from .processes import add_processes
from .storage import add_storage_units, add_stores
from .validators import validate_model


def build_network(payload: RunPayload) -> tuple[pypsa.Network, list[str]]:
    model = payload.model
    scenario = payload.scenario
    notes: list[str] = []

    # Determine snapshot index: use workbook timestamps if available, else synthetic
    snapshot_rows = workbook_rows(model, "snapshots")

    options = payload.options or {}
    date_format: str = str(options.get("dateFormat", "auto"))

    wb_index = workbook_snapshot_index(snapshot_rows, date_format=date_format)
    window, _step, snapshot_start = snapshot_settings(payload)

    # step = temporal resolution: every `step`-th hourly snapshot is modelled;
    # each kept snapshot carries snapshot_weightings = step (hours it represents).
    # This matches the PyPSA convention: n.snapshots[::step] + weightings = step.
    step = max(1, int(round(number(options.get("snapshotWeight"), 1.0))))

    if wb_index is not None:
        snapshot_start = max(0, min(len(wb_index) - 1, snapshot_start))
        snapshot_stop = min(len(wb_index), snapshot_start + window)
        snapshots = wb_index[snapshot_start:snapshot_stop:step]
        snapshot_weight = float(step)
        snapshot_count = len(snapshots)
        notes.append(
            f"Using {snapshot_count} workbook snapshots at {step}h resolution "
            f"(rows {snapshot_start} → {snapshot_stop} of {len(wb_index)}; "
            f"{snapshots[0]} → {snapshots[-1]})."
        )
    else:
        start_date = load_system_defaults().get("simulation", {}).get("start_date", "2024-01-01")
        start_ts = pd.Timestamp(start_date) + pd.Timedelta(hours=snapshot_start)
        # Generate the full hourly window, then keep every `step`-th snapshot.
        hourly = pd.date_range(start_ts, periods=window, freq="h")
        snapshots = hourly[::step]
        snapshot_weight = float(step)
        snapshot_count = len(snapshots)
        notes.append(
            f"Synthetic {snapshot_count} snapshots at {step}h resolution "
            f"(window {window}h from {start_ts}; each snapshot = {step}h)."
        )

    period_factor = modeled_period_factor(snapshot_count, snapshot_weight)

    network = pypsa.Network()
    network.set_snapshots(snapshots)
    network.snapshot_weightings.loc[:, "objective"] = snapshot_weight
    network.snapshot_weightings.loc[:, "stores"] = snapshot_weight
    network.snapshot_weightings.loc[:, "generators"] = snapshot_weight
    network.name = text(
        workbook_rows(model, "network")[0].get("name")
        if workbook_rows(model, "network")
        else "Ragnarok Case"
    )

    # Carriers
    system_carriers = {"Imports", "LoadShedding"}
    for row in workbook_rows(model, "carriers"):
        carrier_name = text(row.get("name"))
        if carrier_name and carrier_name not in network.carriers.index:
            color = text(row.get("color"))
            kwargs: dict[str, Any] = {
                "co2_emissions": number(row.get("co2_emissions"), 0.0),
            }
            if color:
                kwargs["color"] = color
            network.add("Carrier", carrier_name, **kwargs)
        system_carriers.discard(carrier_name)
    for carrier_name in system_carriers:
        network.add("Carrier", carrier_name, co2_emissions=0.0)

    # Run parameters
    carbon_price = number(scenario.get("carbonPrice"), 0.0)
    discount_rate = number(scenario.get("discountRate"), 0.05)

    # Topology
    add_buses(network, model)
    load_totals = add_loads(
        network,
        model,
        snapshots,
        snapshot_start=snapshot_start,
        snapshot_window=window,
        step=step,
    )
    add_stores(network, model, period_factor, notes)
    add_storage_units(network, model, period_factor, notes, discount_rate=discount_rate)
    add_shunt_impedances(network, model)

    # Generation
    force_lp = bool(options.get("forceLp", False))
    add_generators(
        network, model, snapshots, period_factor,
        carbon_price, notes,
        snapshot_start=snapshot_start,
        snapshot_window=window,
        step=step, discount_rate=discount_rate,
        force_lp=force_lp,
    )
    add_grid_imports_and_shedding(network, load_totals, carbon_price, notes)

    # Transmission
    add_lines(network, model)
    add_links(network, model)
    add_transformers(network, model)

    # Processes (multi-input/output energy conversion — PyPSA Process component)
    add_processes(network, model)

    # Constraints
    add_global_constraints(network, model, period_factor)

    notes.append(
        f"Prepared PyPSA case with {len(network.buses)} buses, "
        f"{len(network.generators)} generators, {len(network.loads)} loads."
    )
    return network, notes
