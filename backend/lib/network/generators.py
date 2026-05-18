from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..config import load_system_defaults
from ..utils.annuity import annuity_factor
from ..utils.coerce import bool_value, number, text
from ..utils.workbook import apply_scaled_static_attributes, workbook_rows
from .buses import parse_ts_sheet


def _carrier_emissions(network: pypsa.Network, carrier: str) -> float:
    if carrier in network.carriers.index and "co2_emissions" in network.carriers.columns:
        return float(network.carriers.at[carrier, "co2_emissions"])
    return 0.0


def add_generators(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    snapshots: pd.Index,
    period_factor: float,
    carbon_price: float,
    notes: list[str],
    snapshot_start: int = 0,
    snapshot_window: int | None = None,
    step: int = 1,
    discount_rate: float = 0.05,
    force_lp: bool = False,
    currency: str = "$",
) -> None:
    generators = workbook_rows(model, "generators")
    if not generators:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Workbook has no generators.")

    # Load time-series override sheets — downsample by step to match snapshot index
    ts_p_max_pu = parse_ts_sheet(
        model,
        "generators-p_max_pu",
        snapshots,
        snapshot_start=snapshot_start,
        snapshot_window=snapshot_window,
        step=step,
    )
    ts_p_min_pu = parse_ts_sheet(
        model,
        "generators-p_min_pu",
        snapshots,
        snapshot_start=snapshot_start,
        snapshot_window=snapshot_window,
        step=step,
    )

    for row in generators:
        name = text(row.get("name"))
        bus = text(row.get("bus"))
        carrier = text(row.get("carrier"), "LNG")
        if not name or bus not in network.buses.index:
            continue
        p_nom = number(row.get("p_nom"), 0.0)
        marginal_cost = (
            number(row.get("marginal_cost"), 0.0)
            + carbon_price * _carrier_emissions(network, carrier)
        )
        p_max_pu_static = number(row.get("p_max_pu"), 1.0)
        p_min_pu_static = number(row.get("p_min_pu"), 0.0)
        extendable = bool_value(row.get("extendable"), False)
        # committable=True and p_nom_extendable=True are mutually exclusive in PyPSA
        committable = bool_value(row.get("committable"), False) and not force_lp
        if committable and extendable:
            notes.append(
                f"Generator '{name}': committable=True overrides extendable=True "
                f"(PyPSA MIP restriction — capacity will not be optimised)."
            )
            extendable = False
        raw_capital_cost = number(row.get("capital_cost"), 0.0)
        if extendable:
            lifetime = number(row.get("asset_lifetime"), 20.0)
            af = annuity_factor(discount_rate, lifetime)
            annualised_capital_cost = raw_capital_cost * af
            notes.append(
                f"Generator '{name}' is extendable (lifetime={lifetime:.0f}yr, "
                f"AF={af:.4f}, annualised capex={annualised_capital_cost:.0f} {currency}/MW/yr)."
            )
        else:
            annualised_capital_cost = 0.0
        gen_kwargs: dict[str, Any] = dict(
            bus=bus,
            carrier=carrier,
            control=text(row.get("control"), "PQ"),
            p_nom=p_nom,
            p_nom_min=0.0,
            p_min_pu=p_min_pu_static,
            p_max_pu=p_max_pu_static,
            marginal_cost=marginal_cost,
            capital_cost=annualised_capital_cost,
            p_nom_extendable=extendable,
            committable=committable,
        )
        # Unit-commitment attributes — only relevant when committable=True
        if committable:
            for uc_attr in ("min_up_time", "min_down_time", "start_up_cost", "shut_down_cost"):
                val = number(row.get(uc_attr), 0.0)
                if val > 0:
                    gen_kwargs[uc_attr] = val
        network.add("Generator", name, **gen_kwargs)
        applied = apply_scaled_static_attributes(network.generators, name, row, period_factor)
        if applied:
            notes.append(f"Scaled {', '.join(applied)} for generator {name} by period factor {period_factor:.2f}.")

        # Assign time-series p_max_pu from workbook sheet if present; else no override (static used)
        if ts_p_max_pu and name in ts_p_max_pu:
            network.generators_t.p_max_pu.loc[:, name] = ts_p_max_pu[name]
        # Assign time-series p_min_pu if present
        if ts_p_min_pu and name in ts_p_min_pu:
            network.generators_t.p_min_pu.loc[:, name] = ts_p_min_pu[name]


def add_grid_imports_and_shedding(
    network: pypsa.Network,
    load_totals: dict[str, float],
    carbon_price: float,
    notes: list[str],
    enable_load_shedding: bool = False,
) -> str:
    """Add grid import generator and (optionally) per-bus load shedding; return peak bus name.

    Grid imports are always added as a last-resort feasibility backstop.
    Per-bus load shedding generators are added only when *enable_load_shedding*
    is True; when disabled, infeasibility will surface as a solver error rather
    than being silently absorbed by shedding generators.
    """
    if load_totals:
        peak_bus = max(load_totals, key=load_totals.__getitem__)
    else:
        peak_bus = network.buses.index[0]

    cfg = load_system_defaults()
    gi_cfg = cfg["grid_imports"]
    ls_cfg = cfg["load_shedding"]

    network.add(
        "Generator",
        "grid_imports",
        bus=peak_bus,
        carrier=gi_cfg["carrier"],
        p_nom=max(float(gi_cfg["p_nom_floor"]), sum(load_totals.values())),
        marginal_cost=float(gi_cfg["marginal_cost_base"])
        + carbon_price * _carrier_emissions(network, gi_cfg["carrier"]),
    )
    network.generators_t.p_max_pu.loc[:, "grid_imports"] = 1.0

    if enable_load_shedding:
        for bus in network.buses.index:
            shed_name = f"load_shedding_{bus}"
            network.add(
                "Generator",
                shed_name,
                bus=bus,
                carrier=ls_cfg["carrier"],
                p_nom=max(float(ls_cfg["p_nom_floor"]), load_totals.get(bus, 300.0)),
                marginal_cost=float(ls_cfg["marginal_cost"]),
            )
            network.generators_t.p_max_pu.loc[:, shed_name] = 1.0
        notes.append(f"Load shedding generators added for {len(network.buses)} bus(es).")
    else:
        notes.append("Load shedding disabled — infeasibility will surface as a solver error.")

    return peak_bus
