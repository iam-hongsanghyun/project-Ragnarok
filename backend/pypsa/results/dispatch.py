from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..utils.series import safe_series, weighted_sum


def _snapshot_parts(snapshot: object) -> tuple[int | None, object]:
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        return int(snapshot[0]), snapshot[1]
    return None, snapshot


def _snapshot_label(snapshot: object) -> tuple[str, str, int | None]:
    period, timestep = _snapshot_parts(snapshot)
    ts = pd.Timestamp(timestep)
    return ts.strftime("%H:%M"), ts.isoformat(), period


def dispatch_by_carrier(
    generator_dispatch_frame: pd.DataFrame,
    generators: pd.DataFrame,
) -> dict[str, pd.Series]:
    result: dict[str, pd.Series] = {}
    for carrier in generators.carrier.unique():
        names = generators.index[generators.carrier == carrier]
        result[carrier] = (
            generator_dispatch_frame.reindex(columns=names, fill_value=0.0)
            .clip(lower=0.0)
            .sum(axis=1)
        )
    return result


def build_dispatch_series(
    network: pypsa.Network,
    by_carrier: dict[str, pd.Series],
    load_dispatch: pd.Series,
    generator_dispatch_frame: pd.DataFrame,
) -> tuple[list[dict], list[dict]]:
    dispatch_series: list[dict] = []
    generator_dispatch_series: list[dict] = []
    for snapshot in network.snapshots:
        label, stamp, period = _snapshot_label(snapshot)
        values = {
            carrier: float(series.loc[snapshot])
            for carrier, series in by_carrier.items()
            if abs(float(series.loc[snapshot])) > 1e-6
        }
        dispatch_series.append(
            {"label": label, "timestamp": stamp, "period": period, "values": values, "total": float(load_dispatch.loc[snapshot])}
        )
        gen_values = {
            gen: max(float(generator_dispatch_frame.loc[snapshot, gen]), 0.0)
            for gen in generator_dispatch_frame.columns
            if max(float(generator_dispatch_frame.loc[snapshot, gen]), 0.0) > 1e-6
        }
        generator_dispatch_series.append(
            {"label": label, "timestamp": stamp, "period": period, "values": gen_values, "total": float(load_dispatch.loc[snapshot])}
        )
    return dispatch_series, generator_dispatch_series


def build_price_emissions_series(
    network: pypsa.Network,
    by_carrier: dict[str, pd.Series],
    price_series: pd.Series,
    emissions_factors: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict]]:
    if emissions_factors is None:
        emissions_factors = (
            network.carriers["co2_emissions"].to_dict()
            if "co2_emissions" in network.carriers.columns
            else {}
        )
    system_price: list[dict] = []
    system_emissions: list[dict] = []
    for snapshot in network.snapshots:
        label, stamp, period = _snapshot_label(snapshot)
        hourly_emissions = sum(
            max(float(s.loc[snapshot]), 0.0) * emissions_factors.get(c, 0.0)
            for c, s in by_carrier.items()
        )
        system_price.append({"label": label, "timestamp": stamp, "period": period, "value": float(price_series.loc[snapshot])})
        system_emissions.append({"label": label, "timestamp": stamp, "period": period, "value": hourly_emissions})
    return system_price, system_emissions


def build_storage_series(network: pypsa.Network) -> list[dict]:
    """System storage series, aggregated across all storage units.

    Aggregate-then-derive convention (matches the frontend deriveRunResults):
    sum the raw power ``p`` across every unit per snapshot, then split the
    aggregate into charge (abs of the negative part) and discharge (positive
    part). State of charge is summed directly across units.
    """
    state: list[dict] = []
    if len(network.storage_units.index) > 0:
        units = list(network.storage_units.index)
        total_p = sum(safe_series(network.storage_units_t.p, unit) for unit in units)
        total_soc = sum(safe_series(network.storage_units_t.state_of_charge, unit) for unit in units)
        charge = total_p.clip(upper=0.0).abs()
        discharge = total_p.clip(lower=0.0)
        for snapshot in network.snapshots:
            label, stamp, period = _snapshot_label(snapshot)
            state.append({
                "label": label, "timestamp": stamp, "period": period,
                "charge": float(charge.loc[snapshot]),
                "discharge": float(discharge.loc[snapshot]),
                "state": float(total_soc.loc[snapshot]),
            })
    else:
        for snapshot in network.snapshots:
            label, stamp, period = _snapshot_label(snapshot)
            state.append({
                "label": label, "timestamp": stamp, "period": period,
                "charge": 0.0, "discharge": 0.0, "state": 0.0,
            })
    return state
