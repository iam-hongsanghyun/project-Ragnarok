"""Two-stage stochastic planning support.

Ragnarok wraps PyPSA's ``network.set_scenarios()`` API in a small config
object so the GUI can author probability-weighted scenarios alongside
the existing deterministic options. Each scenario carries a name, a
probability weight, and a load-multiplier that scales every ``loads.p_set``
value in that scenario.

The shape of a stochastic solve:

  1. ``build_network`` constructs the deterministic network normally.
  2. If stochastic mode is enabled, this module calls
     ``network.set_scenarios({name: weight})`` *after* deterministic setup
     so all per-component frames expand to ``(scenario, name)`` MultiIndex.
  3. For each scenario, ``loads.p_set`` rows are multiplied by the
     scenario's load multiplier.
  4. ``network.optimize()`` runs as usual; first-stage decisions
     (capacities) are shared across scenarios, second-stage (dispatch) is
     per scenario.

After the solve, ``run_pypsa`` collapses the scenario-indexed frames to
a single representative scenario (the highest-weighted) so the existing
deterministic result-extraction pipeline keeps working unchanged. A
separate ``stochasticResult`` payload exposes per-scenario totals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pypsa

from .utils.coerce import number


@dataclass(frozen=True)
class StochasticScenario:
    name: str
    weight: float
    load_multiplier: float


@dataclass(frozen=True)
class StochasticConfig:
    enabled: bool
    scenarios: tuple[StochasticScenario, ...]


def parse_stochastic_config(raw: dict[str, Any] | None) -> StochasticConfig:
    """Build a :class:`StochasticConfig` from the JSON payload posted by the GUI.

    Disabled if there are fewer than two valid scenarios, since a single
    scenario is just a deterministic solve.
    """
    raw = raw or {}
    if not bool(raw.get("enabled")):
        return StochasticConfig(enabled=False, scenarios=())

    scenarios: list[StochasticScenario] = []
    for item in raw.get("scenarios") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        weight = float(number(item.get("weight"), 0.0))
        if weight <= 0:
            continue
        load_mult = float(number(item.get("loadMultiplier"), 1.0))
        scenarios.append(StochasticScenario(name=name, weight=weight, load_multiplier=load_mult))

    if len(scenarios) < 2:
        return StochasticConfig(enabled=False, scenarios=())

    # Normalise weights to sum=1
    total = sum(s.weight for s in scenarios)
    normalised = tuple(
        StochasticScenario(name=s.name, weight=s.weight / total, load_multiplier=s.load_multiplier)
        for s in scenarios
    )
    return StochasticConfig(enabled=True, scenarios=normalised)


def apply_scenarios(network: pypsa.Network, config: StochasticConfig) -> None:
    """Expand ``network`` to a stochastic shape and apply per-scenario overrides."""
    if not config.enabled:
        return
    weights = {s.name: s.weight for s in config.scenarios}
    network.set_scenarios(weights)

    # Apply load_multiplier to static `p_set` (PyPSA broadcasts to all snapshots
    # if the time-varying frame is empty for that load).
    if "p_set" in network.loads.columns:
        for scenario in config.scenarios:
            if scenario.load_multiplier == 1.0:
                continue
            mask = network.loads.index.get_level_values("scenario") == scenario.name
            network.loads.loc[mask, "p_set"] = (
                network.loads.loc[mask, "p_set"] * scenario.load_multiplier
            )

    # And to the time-varying p_set frame, if any loads use one.
    p_set_t = network.loads_t.p_set
    if not p_set_t.empty and isinstance(p_set_t.columns, pd.MultiIndex):
        for scenario in config.scenarios:
            if scenario.load_multiplier == 1.0:
                continue
            scenario_cols = [c for c in p_set_t.columns if c[0] == scenario.name]
            if scenario_cols:
                p_set_t.loc[:, scenario_cols] = p_set_t.loc[:, scenario_cols] * scenario.load_multiplier


def per_scenario_summaries(
    network: pypsa.Network,
    config: StochasticConfig,
    emissions_factors: dict[str, float],
    currency_symbol: str,
) -> list[dict[str, Any]]:
    """Compute one summary row per scenario from a solved stochastic network."""
    if not config.enabled:
        return []
    rows: list[dict[str, Any]] = []
    weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    gen_p = network.generators_t.p
    generators_static = network.generators

    for scenario in config.scenarios:
        # Time-series: `gen_p` columns are a MultiIndex (scenario, generator_name).
        if isinstance(gen_p.columns, pd.MultiIndex):
            try:
                scenario_dispatch = gen_p.xs(scenario.name, level="scenario", axis=1)
            except KeyError:
                scenario_dispatch = pd.DataFrame(index=network.snapshots)
        else:
            scenario_dispatch = gen_p

        # Static rows: filter by scenario level
        if isinstance(generators_static.index, pd.MultiIndex):
            try:
                scenario_static = generators_static.xs(scenario.name, level="scenario")
            except KeyError:
                scenario_static = generators_static.iloc[0:0]
        else:
            scenario_static = generators_static

        carriers = scenario_static.get("carrier", pd.Series(dtype=str))
        ef_per_gen = carriers.map(emissions_factors).fillna(0.0)
        marginal_cost_static = scenario_static.get("marginal_cost", pd.Series(dtype=float)).fillna(0.0)

        energy_per_gen = scenario_dispatch.clip(lower=0.0).multiply(weights, axis=0).sum()
        total_energy = float(energy_per_gen.sum())
        total_emissions = float((energy_per_gen * ef_per_gen.reindex(energy_per_gen.index).fillna(0.0)).sum())
        total_operating_cost = float((energy_per_gen * marginal_cost_static.reindex(energy_per_gen.index).fillna(0.0)).sum())

        shed = [c for c in scenario_dispatch.columns if str(c).startswith("load_shedding_")]
        load_shed_energy = (
            float(scenario_dispatch[shed].clip(lower=0.0).multiply(weights, axis=0).sum().sum())
            if shed
            else 0.0
        )

        rows.append({
            "name": scenario.name,
            "weight": scenario.weight,
            "loadMultiplier": scenario.load_multiplier,
            "totalEnergyMwh": total_energy,
            "totalEmissionsTco2": total_emissions,
            "totalOperatingCost": total_operating_cost,
            "totalOperatingCostFormatted": f"{round(total_operating_cost):,} {currency_symbol}",
            "loadShedEnergyMwh": load_shed_energy,
        })
    return rows


def collapse_to_representative_scenario(
    network: pypsa.Network,
    config: StochasticConfig,
) -> str:
    """Reduce a solved stochastic network to its highest-weight scenario in
    place so the deterministic result-extraction pipeline can consume it.

    Returns the name of the chosen representative scenario for surfacing to
    the user.
    """
    if not config.enabled or not config.scenarios:
        return ""
    representative = max(config.scenarios, key=lambda s: s.weight)
    rep_name = representative.name

    # Static frames: (scenario, name) MultiIndex → slice to representative, drop level
    for list_name in network.components.keys():
        comp = network.components[list_name]
        static = comp.static
        if isinstance(static.index, pd.MultiIndex) and "scenario" in static.index.names:
            if len(static) == 0:
                # `xs` errors on empty MultiIndex frames in newer pandas; rebuild
                # a single-level empty frame with matching columns.
                comp.static = pd.DataFrame(columns=static.columns, index=pd.Index([], name="name"))
            else:
                comp.static = static.xs(rep_name, level="scenario")
        dynamic = comp.dynamic
        if dynamic is None:
            continue
        for attr in list(dynamic.keys()):
            df = dynamic[attr]
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex) and "scenario" in df.columns.names:
                dynamic[attr] = df.xs(rep_name, level="scenario", axis=1)

    return rep_name
