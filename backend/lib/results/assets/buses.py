from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd
import pypsa

from ...constants import carrier_color
from ...utils.coerce import text
from ...utils.series import maybe_series, safe_series, weighted_sum


def build_bus_details(
    network: pypsa.Network,
    dispatch_frame: pd.DataFrame,
    generator_weights: pd.Series,
    emissions_factors: dict[str, float] | None = None,
    currency: str = "$",
) -> dict[str, Any]:
    if emissions_factors is None:
        emissions_factors = (
            network.carriers["co2_emissions"].to_dict()
            if "co2_emissions" in network.carriers.columns
            else {}
        )
    details: dict[str, Any] = {}
    for bus in network.buses.index:
        load_names = list(network.loads.index[network.loads.bus == bus])
        gen_names = list(network.generators.index[network.generators.bus == bus])
        load_series = (
            network.loads_t.p_set.loc[:, load_names].sum(axis=1)
            if load_names
            else pd.Series(0.0, index=network.snapshots)
        )
        gen_series = (
            dispatch_frame.reindex(columns=gen_names, fill_value=0.0).clip(lower=0.0).sum(axis=1)
            if gen_names
            else pd.Series(0.0, index=network.snapshots)
        )
        price_at_bus = safe_series(network.buses_t.marginal_price, bus)
        v_mag = maybe_series(network.buses_t.v_mag_pu, bus)
        v_ang = maybe_series(network.buses_t.v_ang, bus)

        emissions_at_bus = pd.Series(0.0, index=network.snapshots)
        carrier_mix: dict[str, float] = defaultdict(float)
        for gen in gen_names:
            carrier = text(network.generators.at[gen, "carrier"], "Other")
            s = safe_series(dispatch_frame, gen).clip(lower=0.0)
            emissions_at_bus = emissions_at_bus.add(s * emissions_factors.get(carrier, 0.0), fill_value=0.0)
            carrier_mix[carrier] += weighted_sum(s, generator_weights)

        net_series = []
        for snapshot in network.snapshots:
            ts = pd.Timestamp(snapshot)
            net_series.append({
                "label": ts.strftime("%H:%M"), "timestamp": ts.isoformat(),
                "load": float(load_series.loc[snapshot]),
                "generation": float(gen_series.loc[snapshot]),
                "smp": float(price_at_bus.loc[snapshot]) if snapshot in price_at_bus.index else 0.0,
                "emissions": float(emissions_at_bus.loc[snapshot]),
                "v_mag_pu": float(v_mag.loc[snapshot]) if v_mag is not None and snapshot in v_mag.index else 0.0,
                "v_ang": float(v_ang.loc[snapshot]) if v_ang is not None and snapshot in v_ang.index else 0.0,
            })

        details[bus] = {
            "name": bus,
            "summary": [
                {"label": "Average load", "value": f"{round(float(load_series.mean())):,} MW", "detail": f"{len(load_names)} load(s) attached"},
                {"label": "Average generation", "value": f"{round(float(gen_series.mean())):,} MW", "detail": f"{len(gen_names)} generator(s) attached"},
                {"label": "Average SMP", "value": f"{round(float(price_at_bus.mean())):,} {currency}/MWh", "detail": "Bus marginal price"},
            ],
            "netSeries": net_series,
            "hasVoltageMagnitude": v_mag is not None,
            "hasVoltageAngle": v_ang is not None,
            "carrierMix": [
                {"label": c, "value": v, "color": carrier_color(network, c)}
                for c, v in sorted(carrier_mix.items(), key=lambda x: x[1], reverse=True)
                if v > 0.0
            ],
        }
    return details
