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


DEFAULT_RENEWABLE_CARRIERS = (
    "solar", "wind", "pv", "onwind", "offwind", "onshore_wind", "offshore_wind",
    "hydro", "ror", "run_of_river", "wave", "tidal", "geothermal",
)


@dataclass(frozen=True)
class ScenarioOverride:
    """Advanced per-scenario override.

    Targets a single (sheet, attribute) cell or a subset of rows by name /
    carrier, then either multiplies or replaces the existing value.
    """
    sheet: str
    attribute: str
    scope_type: str        # 'all' | 'name' | 'carrier'
    scope_value: str       # ignored when scope_type == 'all'
    operation: str         # 'multiply' | 'set'
    value: float


@dataclass(frozen=True)
class StochasticScenario:
    name: str
    weight: float
    load_multiplier: float
    marginal_cost_multiplier: float
    renewable_availability_multiplier: float
    overrides: tuple[ScenarioOverride, ...]


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
        mc_mult = float(number(item.get("marginalCostMultiplier"), 1.0))
        re_mult = float(number(item.get("renewableAvailabilityMultiplier"), 1.0))
        raw_overrides = item.get("overrides") or []
        overrides: list[ScenarioOverride] = []
        for raw_override in raw_overrides:
            sheet = str(raw_override.get("sheet") or "").strip()
            attribute = str(raw_override.get("attribute") or "").strip()
            if not sheet or not attribute:
                continue
            scope_type = str(raw_override.get("scopeType") or "all").strip().lower()
            if scope_type not in ("all", "name", "carrier"):
                scope_type = "all"
            scope_value = str(raw_override.get("scopeValue") or "").strip()
            operation = str(raw_override.get("operation") or "multiply").strip().lower()
            if operation not in ("multiply", "set"):
                operation = "multiply"
            value = float(number(raw_override.get("value"), 1.0))
            overrides.append(ScenarioOverride(
                sheet=sheet,
                attribute=attribute,
                scope_type=scope_type,
                scope_value=scope_value,
                operation=operation,
                value=value,
            ))
        scenarios.append(StochasticScenario(
            name=name,
            weight=weight,
            load_multiplier=load_mult,
            marginal_cost_multiplier=mc_mult,
            renewable_availability_multiplier=re_mult,
            overrides=tuple(overrides),
        ))

    if len(scenarios) < 2:
        return StochasticConfig(enabled=False, scenarios=())

    # Normalise weights to sum=1
    total = sum(s.weight for s in scenarios)
    normalised = tuple(
        StochasticScenario(
            name=s.name,
            weight=s.weight / total,
            load_multiplier=s.load_multiplier,
            marginal_cost_multiplier=s.marginal_cost_multiplier,
            renewable_availability_multiplier=s.renewable_availability_multiplier,
            overrides=s.overrides,
        )
        for s in scenarios
    )
    return StochasticConfig(enabled=True, scenarios=normalised)


def apply_scenarios(network: pypsa.Network, config: StochasticConfig) -> None:
    """Expand ``network`` to a stochastic shape and apply per-scenario overrides.

    Order of application:
      1. Quick knobs (load×, marginal_cost×, renewable_availability×)
      2. Advanced overrides (in row order)

    Later steps overwrite earlier ones so a power user can override a knob
    with a more-specific advanced rule.
    """
    if not config.enabled:
        return
    weights = {s.name: s.weight for s in config.scenarios}
    network.set_scenarios(weights)

    for scenario in config.scenarios:
        _apply_load_multiplier(network, scenario)
        _apply_marginal_cost_multiplier(network, scenario)
        _apply_renewable_availability_multiplier(network, scenario)
        for override in scenario.overrides:
            _apply_advanced_override(network, scenario, override)


def _apply_load_multiplier(network: pypsa.Network, scenario: StochasticScenario) -> None:
    if scenario.load_multiplier == 1.0:
        return
    if "p_set" in network.loads.columns:
        mask = network.loads.index.get_level_values("scenario") == scenario.name
        network.loads.loc[mask, "p_set"] = (
            network.loads.loc[mask, "p_set"] * scenario.load_multiplier
        )
    p_set_t = network.loads_t.p_set
    if not p_set_t.empty and isinstance(p_set_t.columns, pd.MultiIndex):
        scenario_cols = [c for c in p_set_t.columns if c[0] == scenario.name]
        if scenario_cols:
            p_set_t.loc[:, scenario_cols] = p_set_t.loc[:, scenario_cols] * scenario.load_multiplier


def _apply_marginal_cost_multiplier(network: pypsa.Network, scenario: StochasticScenario) -> None:
    """Scale the effective marginal cost (post-carbon adder) for every
    generator in this scenario. Useful for fuel-price uncertainty."""
    if scenario.marginal_cost_multiplier == 1.0:
        return
    if "marginal_cost" in network.generators.columns:
        mask = network.generators.index.get_level_values("scenario") == scenario.name
        network.generators.loc[mask, "marginal_cost"] = (
            network.generators.loc[mask, "marginal_cost"] * scenario.marginal_cost_multiplier
        )
    mc_t = network.generators_t.marginal_cost
    if not mc_t.empty and isinstance(mc_t.columns, pd.MultiIndex):
        scenario_cols = [c for c in mc_t.columns if c[0] == scenario.name]
        if scenario_cols:
            mc_t.loc[:, scenario_cols] = mc_t.loc[:, scenario_cols] * scenario.marginal_cost_multiplier


def _is_renewable_carrier(name: object) -> bool:
    text = str(name or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in DEFAULT_RENEWABLE_CARRIERS)


def _apply_renewable_availability_multiplier(network: pypsa.Network, scenario: StochasticScenario) -> None:
    """Scale ``p_max_pu`` for generators whose carrier looks renewable.

    Matched by carrier-name substring against ``DEFAULT_RENEWABLE_CARRIERS``
    so common renames (``solar_pv``, ``onwind_2020`` …) still resolve.
    """
    if scenario.renewable_availability_multiplier == 1.0:
        return
    carriers = network.generators["carrier"] if "carrier" in network.generators.columns else None
    if carriers is None:
        return
    scenario_mask = network.generators.index.get_level_values("scenario") == scenario.name
    renewable_mask = carriers.apply(_is_renewable_carrier)
    target_mask = scenario_mask & renewable_mask
    if target_mask.any() and "p_max_pu" in network.generators.columns:
        network.generators.loc[target_mask, "p_max_pu"] = (
            network.generators.loc[target_mask, "p_max_pu"] * scenario.renewable_availability_multiplier
        )
    p_max_pu_t = network.generators_t.p_max_pu
    if not p_max_pu_t.empty and isinstance(p_max_pu_t.columns, pd.MultiIndex):
        # Column tuples are (scenario, name); look up each name's carrier and
        # only scale renewable-carrier rows in this scenario.
        target_cols: list[tuple] = []
        for col in p_max_pu_t.columns:
            if col[0] != scenario.name:
                continue
            try:
                gen_carrier = carriers.loc[col]
            except (KeyError, TypeError):
                continue
            if _is_renewable_carrier(gen_carrier):
                target_cols.append(col)
        if target_cols:
            p_max_pu_t.loc[:, target_cols] = p_max_pu_t.loc[:, target_cols] * scenario.renewable_availability_multiplier


def _resolve_override_targets(
    network: pypsa.Network,
    scenario: StochasticScenario,
    override: ScenarioOverride,
) -> pd.Index:
    """Return the static-frame rows the override should touch."""
    try:
        comp = network.components[override.sheet]
    except KeyError:
        return pd.Index([])
    static = comp.static
    if not isinstance(static.index, pd.MultiIndex):
        return pd.Index([])
    scenario_mask = static.index.get_level_values("scenario") == scenario.name
    if override.scope_type == "all":
        return static.index[scenario_mask]
    if override.scope_type == "name":
        name_mask = static.index.get_level_values("name") == override.scope_value
        return static.index[scenario_mask & name_mask]
    if override.scope_type == "carrier":
        if "carrier" not in static.columns:
            return pd.Index([])
        carrier_mask = static["carrier"] == override.scope_value
        return static.index[scenario_mask & carrier_mask]
    return pd.Index([])


def _apply_advanced_override(
    network: pypsa.Network,
    scenario: StochasticScenario,
    override: ScenarioOverride,
) -> None:
    """Apply a single user-authored override to the static frame for this scenario.

    Skipped silently if the column doesn't exist on the target sheet or no
    rows match the scope — the validation pane is the right place to flag
    misconfigured overrides (covered separately).
    """
    targets = _resolve_override_targets(network, scenario, override)
    if len(targets) == 0:
        return
    try:
        comp = network.components[override.sheet]
    except KeyError:
        return
    static = comp.static
    if override.attribute not in static.columns:
        return
    if override.operation == "set":
        comp.static.loc[targets, override.attribute] = override.value
    else:  # multiply
        comp.static.loc[targets, override.attribute] = (
            comp.static.loc[targets, override.attribute] * override.value
        )


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
