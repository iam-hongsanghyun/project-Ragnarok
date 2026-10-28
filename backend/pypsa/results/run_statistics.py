"""Weighted per-asset totals of a stored run, read from ``n.statistics`` (core cleanup step 6, A14 / A15 / A16).

The per-asset cards used to multiply per-snapshot series by ONE hours-per-snapshot number
(``runMeta.snapshotWeight``): wrong for a sampled run, where each snapshot stands for its own number of hours,
and blind to the carbon term, ``_t`` marginal costs and piecewise curves. PyPSA already weighs every snapshot
itself, so this module only asks it:

* energy and operating cost per generator - ``n.statistics.supply`` / ``opex`` (``groupby=False``), plus the
  carbon-pricing module's declared objective term (carbon is not a PyPSA ``marginal_cost``);
* curtailment - ``n.statistics.curtailment`` (see :func:`..results.dispatch.curtailment_mw_by_generator`);
* load energy and bus carrier mix - ``n.statistics.withdrawal`` / ``supply``;
* mean nodal price - ``n.statistics.prices(weighting="load")`` (``"time"`` where a bus has no withdrawal);
* the weights themselves - ``n.snapshot_weightings`` (the per-snapshot hours the browser must use for any
  window sum it still does).

Emissions per generator are the ``primary_energy`` accounting of :func:`..utils.emissions.primary_energy_emissions`
(PyPSA has no emissions statistic).
"""
from __future__ import annotations

import warnings
from typing import Any

import pandas as pd
import pypsa

from ...app import carbon_pricing
from ...app.emissions import carrier_emission_factors, primary_energy_emissions
from ..utils.shedding import is_shedding
from .dispatch import curtailment_mw_by_generator
from .stat_metrics import asset_statistic, combine_periods, generator_operating_cost


def _by_name(series: pd.Series) -> dict[str, float]:
    """``(component, name)``-indexed statistic -> ``{name: value}`` (a name is unique within one component)."""
    if series.empty:
        return {}
    names = series.index.get_level_values("name") if isinstance(series.index, pd.MultiIndex) else series.index
    return {str(n): float(v) for n, v in zip(names, series.to_numpy(dtype=float))}


def run_statistics(network: pypsa.Network) -> dict[str, Any]:
    """Weighted totals of a solved (or output-injected) network.

    Args:
        network: solved network, one investment period of it included (``period_view_network``).

    Returns:
        ``{weights, modeledHours, generators, buses}``:

        * ``weights`` - PyPSA ``snapshot_weightings["generators"]`` per snapshot, in snapshot order (hours);
        * ``modeledHours`` - their sum;
        * ``generators`` - ``{name: {energyMwh, operatingCost, carbonCost, emissionsTco2, curtailmentMwh}}``
          (``operatingCost`` = ``statistics.opex`` marginal cost + the carbon term, investment-period weighted);
        * ``buses`` - ``{bus: {loadMwh, generationMwh, averagePrice, carrierMwh}}``.
    """
    weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    gens = network.generators
    has_gens = len(gens) > 0

    energy = _by_name(combine_periods(asset_statistic(network, "supply", ["Generator"]))) if has_gens else {}
    opex = generator_operating_cost(network, weighted=True) if has_gens else pd.Series(dtype=float)
    carbon = carbon_pricing.carbon_cost_by_generator(network) if has_gens else pd.Series(dtype=float)
    curtailment = (
        curtailment_mw_by_generator(network).mul(weights, axis=0).sum(axis=0) if has_gens else pd.Series(dtype=float)
    )
    factors = carrier_emission_factors(network)
    emissions = primary_energy_emissions(network, factors).generators if has_gens else pd.Series(dtype=float)

    generators: dict[str, dict[str, float]] = {}
    for name in gens.index:
        key = str(name)
        carbon_cost = float(carbon.get(name, 0.0)) if len(carbon) else 0.0
        generators[key] = {
            "energyMwh": energy.get(key, 0.0),
            "operatingCost": float(opex.get(name, 0.0)) + carbon_cost,
            "carbonCost": carbon_cost,
            "emissionsTco2": float(emissions.get(name, 0.0)) if len(emissions) else 0.0,
            "curtailmentMwh": float(curtailment.get(name, 0.0)) if len(curtailment) else 0.0,
        }

    buses = _bus_statistics(network, gens, energy)
    return {
        "weights": [float(w) for w in weights.to_numpy()],
        "modeledHours": float(weights.sum()),
        "generators": generators,
        "buses": buses,
        "processes": _process_statistics(network),
    }


def _process_statistics(network: pypsa.Network) -> dict[str, dict[str, float]]:
    """Throughput (``withdrawal`` at bus0) and operating cost (``opex``) of each Process."""
    if "processes" not in network.components.keys() or not len(network.components["processes"].static):
        return {}
    throughput = _by_name(combine_periods(asset_statistic(network, "withdrawal", ["Process"], at_port="bus0")))
    cost = _by_name(combine_periods(asset_statistic(network, "opex", ["Process"])))
    return {
        str(name): {"throughputMwh": throughput.get(str(name), 0.0), "operatingCost": cost.get(str(name), 0.0)}
        for name in network.components["processes"].static.index
    }


def _bus_statistics(network: pypsa.Network, gens: pd.DataFrame, energy: dict[str, float]) -> dict[str, dict[str, Any]]:
    load = _by_name(combine_periods(asset_statistic(network, "withdrawal", ["Load"]))) if len(network.loads) else {}
    price = _bus_prices(network)
    out: dict[str, dict[str, Any]] = {}
    for bus in network.buses.index:
        out[str(bus)] = {"loadMwh": 0.0, "generationMwh": 0.0, "averagePrice": price.get(str(bus), 0.0), "carrierMwh": {}}
    if len(network.loads) and "bus" in network.loads.columns:
        for name, mwh in load.items():
            if name in network.loads.index:
                out.setdefault(str(network.loads.at[name, "bus"]), {"loadMwh": 0.0, "generationMwh": 0.0, "averagePrice": 0.0, "carrierMwh": {}})
                out[str(network.loads.at[name, "bus"])]["loadMwh"] += mwh
    for name, mwh in energy.items():
        if name not in gens.index or is_shedding(name, gens.at[name, "carrier"]):
            continue
        row = out.setdefault(str(gens.at[name, "bus"]), {"loadMwh": 0.0, "generationMwh": 0.0, "averagePrice": 0.0, "carrierMwh": {}})
        carrier = str(gens.at[name, "carrier"]) or "Other"
        row["generationMwh"] += mwh
        row["carrierMwh"][carrier] = row["carrierMwh"].get(carrier, 0.0) + mwh
    return out


def _bus_prices(network: pypsa.Network) -> dict[str, float]:
    """Mean marginal price per bus: load-weighted, snapshot-weighted where the bus withdraws nothing."""
    if network.buses_t.marginal_price.empty:
        return {}
    prices: dict[str, float] = {}
    for weighting in ("time", "load"):  # load last: it overrides where defined
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                found = network.statistics.prices(groupby=False, weighting=weighting, drop_zero=False, round=9)
        except Exception:  # noqa: BLE001 - no solved flows
            continue
        if isinstance(found, pd.DataFrame):
            found = found.mean(axis=1)
        for bus, value in found.dropna().items():
            prices[str(bus)] = float(value)
    return prices
