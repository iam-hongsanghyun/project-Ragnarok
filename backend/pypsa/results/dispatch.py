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
    # Vectorised: pull whole columns to Python lists once (C-level `tolist()`),
    # then build the sparse per-snapshot dicts from those — instead of a
    # per-(snapshot, carrier/generator) `.loc[...]` label lookup, which is
    # O(snapshots × components) and dominates a multi-bus full-year run.
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    carrier_df = pd.DataFrame(by_carrier, index=snapshots)
    carrier_cols = [str(c) for c in carrier_df.columns]
    carrier_rows = carrier_df.to_numpy().tolist()
    load_vals = load_dispatch.reindex(snapshots).to_numpy().tolist()
    gen_cols = [str(g) for g in generator_dispatch_frame.columns]
    gen_rows = generator_dispatch_frame.reindex(index=snapshots).clip(lower=0.0).to_numpy().tolist()

    dispatch_series: list[dict] = []
    generator_dispatch_series: list[dict] = []
    for i, (label, stamp, period) in enumerate(labels):
        total = float(load_vals[i])
        crow = carrier_rows[i]
        values = {carrier_cols[j]: v for j, v in enumerate(crow) if abs(v) > 1e-6}
        dispatch_series.append(
            {"label": label, "timestamp": stamp, "period": period, "values": values, "total": total}
        )
        grow = gen_rows[i]
        gen_values = {gen_cols[j]: v for j, v in enumerate(grow) if v > 1e-6}
        generator_dispatch_series.append(
            {"label": label, "timestamp": stamp, "period": period, "values": gen_values, "total": total}
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
    # Vectorised: emissions = Σ_carrier clip(dispatch, 0) × factor as a single
    # column op, then `tolist()` both series once — no per-snapshot `.loc[]`.
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    emissions_total = None
    for c, s in by_carrier.items():
        ef = emissions_factors.get(c, 0.0)
        if ef:
            contrib = s.clip(lower=0.0) * ef
            emissions_total = contrib if emissions_total is None else emissions_total.add(contrib, fill_value=0.0)
    emission_vals = (
        emissions_total.reindex(snapshots).fillna(0.0).to_numpy().tolist()
        if emissions_total is not None else [0.0] * len(labels)
    )
    price_vals = price_series.reindex(snapshots).to_numpy().tolist()

    system_price = [
        {"label": l, "timestamp": st, "period": p, "value": float(price_vals[i])}
        for i, (l, st, p) in enumerate(labels)
    ]
    system_emissions = [
        {"label": l, "timestamp": st, "period": p, "value": float(emission_vals[i])}
        for i, (l, st, p) in enumerate(labels)
    ]
    return system_price, system_emissions


def build_storage_series(network: pypsa.Network) -> list[dict]:
    """System storage series, aggregated across all storage units.

    Aggregate-then-derive convention (matches the frontend deriveRunResults):
    sum the raw power ``p`` across every unit per snapshot, then split the
    aggregate into charge (abs of the negative part) and discharge (positive
    part). State of charge is summed directly across units.
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    if len(network.storage_units.index) > 0:
        units = list(network.storage_units.index)
        total_p = sum(safe_series(network.storage_units_t.p, unit) for unit in units)
        total_soc = sum(safe_series(network.storage_units_t.state_of_charge, unit) for unit in units)
        # `tolist()` each aggregate series once instead of a per-snapshot `.loc`.
        charge_vals = total_p.clip(upper=0.0).abs().reindex(snapshots).to_numpy().tolist()
        discharge_vals = total_p.clip(lower=0.0).reindex(snapshots).to_numpy().tolist()
        soc_vals = total_soc.reindex(snapshots).to_numpy().tolist()
        return [
            {"label": l, "timestamp": st, "period": p,
             "charge": float(charge_vals[i]), "discharge": float(discharge_vals[i]),
             "state": float(soc_vals[i])}
            for i, (l, st, p) in enumerate(labels)
        ]
    return [
        {"label": l, "timestamp": st, "period": p, "charge": 0.0, "discharge": 0.0, "state": 0.0}
        for (l, st, p) in labels
    ]
