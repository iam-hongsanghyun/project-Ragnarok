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
from fastapi import HTTPException
from pypsa.constants import RE_INVARIANT_ATTRS

from ..app import carbon_pricing
from .utils.coerce import number


@dataclass(frozen=True)
class ScenarioOverride:
    """Per-scenario override.

    Targets a sheet's attribute on either all rows, rows matching a name,
    or rows matching a carrier; then either multiplies or replaces the
    existing value.
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
    overrides: tuple[ScenarioOverride, ...]


@dataclass(frozen=True)
class StochasticConfig:
    enabled: bool
    scenarios: tuple[StochasticScenario, ...]


def is_scenario_invariant(attribute: str) -> bool:
    """True when PyPSA requires ``attribute`` to be identical across scenarios.

    These attributes (bus/port wiring, ``carrier``, ``*_nom_set``, ``*_extendable``,
    ``build_year``, ``lifetime``, ``delay`` ...) fix the topology or the
    mathematical structure, so PyPSA >= 1.4 raises ``ConsistencyError`` when a
    scenario changes them. The pattern is PyPSA's own (``RE_INVARIANT_ATTRS``),
    never a copy of it, so it follows the installed version.
    """
    return RE_INVARIANT_ATTRS.fullmatch(attribute) is not None


def parse_stochastic_config(raw: dict[str, Any] | None) -> StochasticConfig:
    """Build a :class:`StochasticConfig` from the JSON payload posted by the GUI.

    Disabled if there are fewer than two valid scenarios, since a single
    scenario is just a deterministic solve.

    Raises:
        HTTPException: 400 when an override targets a scenario-invariant
            attribute (see :func:`is_scenario_invariant`).
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
        raw_overrides = item.get("overrides") or []
        overrides: list[ScenarioOverride] = []
        for raw_override in raw_overrides:
            sheet = str(raw_override.get("sheet") or "").strip()
            attribute = str(raw_override.get("attribute") or "").strip()
            if not sheet or not attribute:
                continue
            if is_scenario_invariant(attribute):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Stochastic scenario '{name}': override of '{sheet}.{attribute}' is not "
                        "allowed. PyPSA requires that attribute to be identical across scenarios "
                        "(it defines the network topology or the optimisation problem). "
                        "Override an operating attribute instead (e.g. marginal_cost, p_set, p_max_pu)."
                    ),
                )
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
            overrides=tuple(overrides),
        ))

    if len(scenarios) < 2:
        return StochasticConfig(enabled=False, scenarios=())

    # Normalise weights to sum=1
    total = sum(s.weight for s in scenarios)
    normalised = tuple(
        StochasticScenario(name=s.name, weight=s.weight / total, overrides=s.overrides)
        for s in scenarios
    )
    return StochasticConfig(enabled=True, scenarios=normalised)


def apply_scenarios(network: pypsa.Network, config: StochasticConfig) -> None:
    """Expand ``network`` to a stochastic shape and apply per-scenario overrides.

    Every variation lives in ``scenario.overrides``: a list of
    ``ScenarioOverride`` rows applied in row order. There are no special
    multiplier shortcuts — the override editor is the single mechanism.
    Common patterns:

      - **Load × 0.8** in this scenario:
        ``{sheet: loads, attribute: p_set, scope: all, op: multiply, value: 0.8}``
      - **Fuel price × 2** on gas generators:
        ``{sheet: generators, attribute: marginal_cost, scope: carrier, scope_value: gas, op: multiply, value: 2}``
      - **Drought year on a specific hydro plant**:
        ``{sheet: generators, attribute: p_max_pu, scope: name, scope_value: hydro_a, op: multiply, value: 0.4}``
    """
    if not config.enabled:
        return
    weights = {s.name: s.weight for s in config.scenarios}
    network.set_scenarios(weights)

    for scenario in config.scenarios:
        for override in scenario.overrides:
            _apply_advanced_override(network, scenario, override)


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
    """Apply a single user-authored override to this scenario.

    Writes to both the static frame and (if present) the corresponding
    ``<list>_t.<attribute>`` time-varying frame so per-snapshot precision
    survives whether the user supplied the attribute as a scalar or as a
    time series.
    """
    targets = _resolve_override_targets(network, scenario, override)
    if len(targets) == 0:
        return
    try:
        comp = network.components[override.sheet]
    except KeyError:
        return

    target_names = [target[1] if isinstance(target, tuple) else target for target in targets]

    # ── Static frame ────────────────────────────────────────────────────────
    static = comp.static
    if override.attribute in static.columns:
        if override.operation == "set":
            comp.static.loc[targets, override.attribute] = override.value
        else:  # multiply
            comp.static.loc[targets, override.attribute] = (
                comp.static.loc[targets, override.attribute] * override.value
            )

    # ── Dynamic frame (if any) ──────────────────────────────────────────────
    dynamic = getattr(comp, "dynamic", None)
    if dynamic is None or override.attribute not in dynamic:
        return
    df = dynamic[override.attribute]
    if df is None or df.empty:
        return
    if not isinstance(df.columns, pd.MultiIndex):
        return
    scenario_cols = [
        col for col in df.columns
        if col[0] == scenario.name and col[1] in target_names
    ]
    if not scenario_cols:
        return
    if override.operation == "set":
        df.loc[:, scenario_cols] = override.value
    else:  # multiply
        df.loc[:, scenario_cols] = df.loc[:, scenario_cols] * override.value


def per_scenario_summaries(
    network: pypsa.Network,
    config: StochasticConfig,
    emissions_factors: dict[str, float],
    currency_symbol: str,
) -> list[dict[str, Any]]:
    """Compute one summary row per scenario from a solved stochastic network.

    ``totalOperatingCost`` prices dispatch at the **dense** marginal cost
    (``get_switchable_as_dense``) plus the carbon-pricing module's adder: a workbook
    ``generators-marginal_cost`` series lives only in the time-varying frame, so the
    static column alone would misprice it. Falls back to the
    static column when the dense read is unavailable.

    Algorithm (per scenario s, generators g, snapshots t, weights w):
        $$C_s = \\sum_{g,t} w_t \\, c_{g,t} \\, \\max(p^s_{g,t}, 0)$$
        ASCII: cost = sum_gt w * mc_dense[g,t] * max(p[g,t], 0).

        Symbols: c = marginal cost [currency/MWh], p = dispatch [MW],
        w = snapshot weight [h].
    """
    if not config.enabled:
        return []
    rows: list[dict[str, Any]] = []
    weights = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    gen_p = network.generators_t.p
    generators_static = network.generators
    try:
        mc_dense_all = carbon_pricing.add_adder(network, network.get_switchable_as_dense("Generator", "marginal_cost"))
    except Exception:
        mc_dense_all = None

    for scenario in config.scenarios:
        # Time-series: `gen_p` columns are a MultiIndex (scenario, generator_name).
        if isinstance(gen_p.columns, pd.MultiIndex):
            try:
                scenario_dispatch = gen_p.xs(scenario.name, level="scenario", axis=1)
            except KeyError:
                scenario_dispatch = pd.DataFrame(index=network.snapshots)
        else:
            scenario_dispatch = gen_p

        # Dense marginal cost sliced to this scenario (columns mirror gen_p's).
        mc_scenario: pd.DataFrame | None = None
        if mc_dense_all is not None:
            if isinstance(mc_dense_all.columns, pd.MultiIndex):
                try:
                    mc_scenario = mc_dense_all.xs(scenario.name, level="scenario", axis=1)
                except KeyError:
                    mc_scenario = None
            else:
                mc_scenario = mc_dense_all

        # Static rows: filter by scenario level
        if isinstance(generators_static.index, pd.MultiIndex):
            try:
                scenario_static = generators_static.xs(scenario.name, level="scenario")
            except KeyError:
                scenario_static = generators_static.iloc[0:0]
        else:
            scenario_static = generators_static

        carriers = scenario_static.get("carrier", pd.Series(dtype=str))
        # tCO₂ per MWh_electrical = carrier co2_emissions / η (thermal basis, M3).
        ef_per_gen = carriers.map(emissions_factors).fillna(0.0)
        eta = pd.to_numeric(
            scenario_static.get("efficiency", pd.Series(dtype=float)), errors="coerce"
        ).reindex(ef_per_gen.index).fillna(1.0)
        eta = eta.where(eta > 1e-6, 1.0)
        ef_per_gen = ef_per_gen / eta
        marginal_cost_static = scenario_static.get("marginal_cost", pd.Series(dtype=float)).fillna(0.0)

        dispatch_pos = scenario_dispatch.clip(lower=0.0)
        energy_per_gen = dispatch_pos.multiply(weights, axis=0).sum()
        # Unserved energy (the load-shedding backstop) is not supply.
        total_energy = float(
            energy_per_gen[
                [c for c in energy_per_gen.index if not str(c).startswith("load_shedding_")]
            ].sum()
        )
        total_emissions = float((energy_per_gen * ef_per_gen.reindex(energy_per_gen.index).fillna(0.0)).sum())
        if mc_scenario is not None:
            mc = mc_scenario.reindex(
                index=dispatch_pos.index, columns=dispatch_pos.columns
            ).fillna(0.0)
            total_operating_cost = float(
                (dispatch_pos * mc).multiply(weights, axis=0).sum().sum()
            )
        else:
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
            "overrideCount": len(scenario.overrides),
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
                if _is_dual_attribute(attr):
                    dynamic[attr] = dynamic[attr] / representative.weight

    # Global-constraint duals live in the static frame (``mu``). PyPSA leaves
    # them at 0.0 on a scenario-indexed frame, so recover the representative
    # scenario's dual from the solved linopy model, then undo the weighting.
    gcs = network.global_constraints
    if "mu" in gcs.columns and len(gcs):
        model = getattr(network, "model", None)
        constraints = getattr(model, "constraints", None)
        for gc_name in gcs.index:
            mu = float(gcs.at[gc_name, "mu"]) if pd.notna(gcs.at[gc_name, "mu"]) else 0.0
            if mu == 0.0 and constraints is not None:
                try:
                    dual = constraints[f"GlobalConstraint-{gc_name}"].dual
                    if "scenario" in dual.dims:
                        dual = dual.sel(scenario=rep_name)
                    mu = float(dual.values.sum())
                    # linopy duals are the sensitivity of the (minimise)
                    # objective to the rhs; PyPSA stores them with the same sign.
                    gcs.at[gc_name, "mu"] = mu
                except Exception:  # noqa: BLE001 — dual not available; keep PyPSA's value
                    continue
            gcs.at[gc_name, "mu"] = float(gcs.at[gc_name, "mu"]) / representative.weight

    return rep_name


def _is_dual_attribute(attr: str) -> bool:
    """Whether a dynamic attribute is a shadow price (scaled by scenario weight).

    Algorithm:
        The stochastic objective is $$\\min \\sum_s w_s C_s$$, so a dual
        returned for scenario ``s`` is $\\lambda_s = w_s \\pi_s$ where
        $\\pi_s$ is the per-scenario price (currency per unit, w_s the
        normalised scenario probability). Reported price: $\\pi_s = \\lambda_s / w_s$.
        ASCII: price = dual / weight.
    """
    return attr == "marginal_price" or attr.startswith("mu_")
