"""The carbon price as a declared objective term, and the numbers read back from it.

PyPSA has no carbon price (its CO2 instrument is the ``primary_energy`` GlobalConstraint). This
module sends PyPSA the price as ONE extra term of the objective, added by ``extra_functionality``
after PyPSA has built its model. ``marginal_cost`` is left exactly as the workbook states it, so
``n.statistics.opex`` is the fuel (and every other operating) cost and the carbon cost is this
term, evaluated from the solution.

Algorithm:
    For every generator :math:`g` whose carrier has ``co2_emissions`` :math:`e_c > 0`:

    $$ \\min \\quad \\ldots + \\sum_{t} w_t\\,\\omega_{p(t)}\\,\\pi_t \\sum_{g}
         \\frac{e_{c(g)}}{\\eta_{g,t}}\\,p_{g,t} $$

    ASCII: objective += sum_t w[t] * omega[period(t)] * price[t] * sum_g co2[carrier g] / eta[g,t] * p[g,t]

    :math:`w_t` objective snapshot weighting (h), :math:`\\omega_p` investment-period objective
    weighting (1 outside a pathway run), :math:`\\pi_t` carbon price (currency/tCO2, see
    :func:`.config.price_series`), :math:`e_c` carrier ``co2_emissions`` (tCO2/MWh of fuel),
    :math:`\\eta_{g,t}` the generator's efficiency (static, or its time series; a blank / non-positive
    value falls back to the static one, then to 1), :math:`p_{g,t}` dispatch (MW). In a stochastic
    run the term is weighted by the scenario probabilities, as PyPSA weights its own costs.

    This is the same quantity as the ``primary_energy`` accounting (``sum w p / eta * e``) priced at
    :math:`\\pi_t`: emissions stay at the generator that burns the fuel. A Link that converts a fuel
    bus (gas -> electricity) carries none: the fuel-supply generator upstream already does, at
    efficiency 1, so nothing is counted twice.

The same coefficient is what the module writes into ``marginal_cost`` of a SCRATCH COPY for the
studies that overwrite marginal costs themselves or build the model through a PyPSA entry point with
no ``extra_functionality`` hook (modelling-to-generate-alternatives, strategic bidding): see
:func:`write_marginal_cost_adder`. The network a run is built and solved on never has it.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa
import xarray as xr

from .config import PLAN_KEY, CarbonPriceConfig, early_snapshots, from_meta, price_series

_MIN_EFFICIENCY = 1e-6


# ── the plan a built network carries ──────────────────────────────────────────────

def set_plan(network: pypsa.Network, config: CarbonPriceConfig | None) -> None:
    """Record the price a network was built for (``network.meta``); ``None`` clears it."""
    if config is None or not config.enabled:
        network.meta.pop(PLAN_KEY, None)
        return
    network.meta[PLAN_KEY] = config.to_meta()


def plan_of(network: pypsa.Network) -> CarbonPriceConfig | None:
    """The price recorded on ``network``, ``None`` when it carries none."""
    return from_meta(getattr(network, "meta", {}).get(PLAN_KEY))


def _first_scenario(frame: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """A stochastic network indexes statics by (scenario, name); carrier and efficiency are shared."""
    if isinstance(frame.index, pd.MultiIndex) and "scenario" in (frame.index.names or []):
        first = frame.index.get_level_values("scenario")[0]
        return frame.xs(first, level="scenario")
    return frame


def _carrier_factor(network: pypsa.Network) -> pd.Series:
    """tCO2/MWh of fuel per carrier name (empty when no carrier states one)."""
    carriers = network.carriers
    if "co2_emissions" not in carriers.columns or carriers.empty:
        return pd.Series(dtype=float)
    ef = pd.to_numeric(_first_scenario(carriers)["co2_emissions"], errors="coerce").fillna(0.0)
    return ef.astype(float)


def emission_factors(network: pypsa.Network) -> pd.Series:
    """``co2_emissions`` of each generator's carrier (tCO2/MWh of fuel), indexed by generator name."""
    gens = _first_scenario(network.generators)
    if gens.empty:
        return pd.Series(dtype=float)
    ef = _carrier_factor(network)
    return gens["carrier"].map(lambda c: float(ef.get(str(c), 0.0))).astype(float)


def _column_names(columns: pd.Index) -> list[str]:
    return [str(c[-1]) if isinstance(c, tuple) else str(c) for c in columns]


# ── the coefficient: currency per MWh of electricity ──────────────────────────────

def adder_frame(network: pypsa.Network, config: CarbonPriceConfig | None = None) -> pd.DataFrame:
    """Carbon cost per MWh of generator output, ``price_t * co2_emissions / eta_t`` (currency/MWh).

    Rows are ``network.snapshots``; columns the emitting generators (``(scenario, name)`` pairs of a
    stochastic network). An empty frame when nothing is priced.
    """
    cfg = config if config is not None else plan_of(network)
    empty = pd.DataFrame(index=network.snapshots, dtype=float)
    if cfg is None or not cfg.is_active or network.generators.empty:
        return empty
    series = price_series(cfg, network.snapshots)
    if (series <= 0).all():
        return empty
    ef_by_name = emission_factors(network)
    eta = network.get_switchable_as_dense("Generator", "efficiency")
    names = _column_names(eta.columns)
    ef_col = np.array([float(ef_by_name.get(n, 0.0)) for n in names])
    keep = ef_col > 0
    if not keep.any():
        return empty
    eta = eta.loc[:, keep].astype(float)
    ef_col = ef_col[keep]
    fallback = _static_efficiency(network)
    static_col = np.array([float(fallback.get(n, 1.0)) for n in np.array(names)[keep]])
    eta_v = eta.to_numpy()
    eta_v = np.where(eta_v > _MIN_EFFICIENCY, eta_v, static_col[None, :])
    eta_v = np.where(eta_v > _MIN_EFFICIENCY, eta_v, 1.0)
    adder = series.to_numpy()[:, None] * ef_col[None, :] / eta_v
    return pd.DataFrame(adder, index=eta.index, columns=eta.columns)


def _static_efficiency(network: pypsa.Network) -> pd.Series:
    """Static efficiency by generator name (1.0 when blank or non-positive)."""
    gens = _first_scenario(network.generators)
    if "efficiency" not in gens.columns:
        return pd.Series(1.0, index=gens.index, dtype=float)
    eta = pd.to_numeric(gens["efficiency"], errors="coerce").fillna(1.0)
    return eta.where(eta > _MIN_EFFICIENCY, 1.0).astype(float)


def objective_weights(network: pypsa.Network, snapshots: pd.Index, *, multi_invest: bool) -> pd.Series:
    """``w_t * omega_p(t)``: the weight PyPSA gives an operating cost at each snapshot."""
    w = network.snapshot_weightings["objective"].reindex(snapshots).fillna(1.0).astype(float)
    if multi_invest and isinstance(snapshots, pd.MultiIndex) and "period" in (snapshots.names or []):
        omega = network.investment_period_weightings["objective"]
        w = w * omega.reindex(snapshots.get_level_values("period")).fillna(1.0).to_numpy()
    return w


# ── the objective term ────────────────────────────────────────────────────────────

def _expression(p: Any, coef: pd.DataFrame) -> Any:
    names = [c for c in coef.columns if c in set(p.indexes["name"])]
    coef = coef[names]
    da = xr.DataArray(
        coef.to_numpy(),
        coords={"snapshot": coef.index, "name": pd.Index(names, name="name")},
        dims=("snapshot", "name"),
    )
    return (p.sel(name=names) * da).sum(["name", "snapshot"])


def extra_functionality(n: pypsa.Network, snapshots: Any = None) -> None:
    """Add the carbon-price term to ``n.model``'s objective (a PyPSA ``extra_functionality`` hook).

    A no-op when the network carries no price. Call it once per model (PyPSA does, from
    ``extra_functionality``): a second call would add the term twice.
    """
    cfg = plan_of(n)
    if cfg is None or not cfg.is_active:
        return
    m = n.model
    if "Generator-p" not in m.variables:
        return
    p = m["Generator-p"]
    idx = p.indexes["snapshot"]
    adder = adder_frame(n, cfg)
    if adder.empty:
        return
    weight = objective_weights(n, idx, multi_invest=bool(getattr(n, "_multi_invest", False)))
    if n.has_scenarios:
        parts = []
        for scenario, probability in n.scenario_weightings["weight"].items():
            coef = adder.xs(scenario, level="scenario", axis=1).reindex(idx).mul(weight, axis=0)
            parts.append(_expression(p.sel(scenario=scenario, drop=True), coef) * float(probability))
        term = sum(parts[1:], parts[0])
    else:
        term = _expression(p, adder.reindex(idx).mul(weight, axis=0))
    m.objective.expression = m.objective.expression + term


# ── the numbers read back from the solution ───────────────────────────────────────

def carbon_cost_by_generator(
    network: pypsa.Network,
    config: CarbonPriceConfig | None = None,
    *,
    period_weighted: bool = True,
    per_scenario: bool = False,
) -> pd.Series:
    """Carbon cost of each generator, ``sum_t w_t omega_p pi_t p_t e / eta_t`` (currency), from the solved dispatch.

    This is the objective term evaluated at the solution: the same weights, price and efficiency.
    Expected value over scenarios in a stochastic run. ``period_weighted=False`` leaves out the
    investment-period objective weighting (a per-modelled-window figure, as the company statement
    reports). Indexed by generator name; ``per_scenario=True`` keeps a stochastic run's
    ``(scenario, name)`` index with each scenario's own cost (no probability weighting), the
    shape ``n.statistics.opex(groupby=False)`` has.
    """
    cfg = config if config is not None else plan_of(network)
    adder = adder_frame(network, cfg)
    if adder.empty:
        return pd.Series(dtype=float)
    snaps = network.snapshots
    pathway = isinstance(snaps, pd.MultiIndex) and "period" in (snaps.names or [])
    weight = objective_weights(network, snaps, multi_invest=pathway and period_weighted)
    p = network.generators_t.p.reindex(snaps)
    cols = [c for c in adder.columns if c in p.columns]
    if not cols:
        return pd.Series(dtype=float)
    cost = (p[cols].fillna(0.0) * adder[cols]).mul(weight, axis=0).sum(axis=0)
    if per_scenario:
        return cost.astype(float)
    if isinstance(cost.index, pd.MultiIndex) and "scenario" in (cost.index.names or []):
        probability = network.scenario_weightings["weight"]
        cost = cost.mul(probability.reindex(cost.index.get_level_values("scenario")).to_numpy(), axis=0)
        cost = cost.groupby(level="name").sum()
    return cost.astype(float)


def carbon_cost(network: pypsa.Network, config: CarbonPriceConfig | None = None, *, period_weighted: bool = True) -> float:
    """Total carbon cost of the solved network (currency), the module's declared term at the solution."""
    return float(carbon_cost_by_generator(network, config, period_weighted=period_weighted).sum())


def add_adder(network: pypsa.Network, marginal_cost: pd.DataFrame) -> pd.DataFrame:
    """``marginal_cost`` (a dense snapshot x generator frame) plus the carbon adder."""
    adder = adder_frame(network)
    if adder.empty:
        return marginal_cost
    return marginal_cost.add(adder.reindex(index=marginal_cost.index, columns=marginal_cost.columns), fill_value=0.0)


def effective_marginal_cost(network: pypsa.Network) -> pd.DataFrame:
    """Per-snapshot cost of one MWh of each generator: PyPSA's ``marginal_cost`` (with the solved
    piecewise-curve cost) plus the carbon adder. What dispatch is priced at; for merit order,
    finance and the bidding studies."""
    from ...pypsa.network.piecewise import overlay_piecewise_marginal_cost

    mc = overlay_piecewise_marginal_cost(network, network.get_switchable_as_dense("Generator", "marginal_cost"))
    return add_adder(network, mc)


def carbon_adder_series(network: pypsa.Network, name: str) -> pd.Series:
    """The carbon adder of one generator over the snapshots (zeros when it is not priced)."""
    adder = adder_frame(network)
    if name in adder.columns:
        return adder[name]
    return pd.Series(0.0, index=network.snapshots)


# ── the scratch-copy form ─────────────────────────────────────────────────────────

def write_marginal_cost_adder(network: pypsa.Network, config: CarbonPriceConfig | None = None) -> int:
    """Write the carbon adder into ``marginal_cost`` of ``network`` and drop its plan.

    ONLY for a scratch copy (``network.copy()``) that a study re-solves where the objective hook is
    unavailable or the study rewrites marginal costs itself (MGA, strategic bidding). The result is
    the old "price inside marginal_cost" network, so those studies reproduce their numbers. The
    run's own network is never touched.

    Returns:
        Number of generators that received an adder.

    Raises:
        ValueError: an emitting generator has a piecewise ``marginal_cost`` curve (a curve ignores
            the scalar / series cost, so the adder would be lost).
    """
    cfg = config if config is not None else plan_of(network)
    adder = adder_frame(network, cfg)
    set_plan(network, None)
    if adder.empty:
        return 0
    comp = network.components["generators"]
    if comp.has_piecewise("marginal_cost"):
        curved = set(comp.piecewise["marginal_cost"].columns.unique("name"))
        hit = sorted(curved & set(_column_names(adder.columns)))
        if hit:
            raise ValueError(
                f"carbon price on generator(s) {', '.join(hit)} with a piecewise marginal_cost curve cannot be "
                "written into a scratch copy: remove the curve or the price for this study."
            )
    dense = network.get_switchable_as_dense("Generator", "marginal_cost")
    mc_t = network.generators_t.marginal_cost
    for col in adder.columns:
        base = dense[col] if col in dense.columns else 0.0
        mc_t[col] = base + adder[col]
    return int(adder.shape[1])


# ── what the user is told ─────────────────────────────────────────────────────────

def build_notes(network: pypsa.Network, config: CarbonPriceConfig, currency: str) -> list[str]:
    """Notes of a build: what price the module will send, and to how many generators."""
    if not config.is_active:
        return []
    notes: list[str] = []
    ef = emission_factors(network)
    n_emitting = int((ef > 0).sum())
    if n_emitting == 0:
        return [f"Carbon price set but no generator's carrier has co2_emissions > 0: nothing is priced."]
    n_early = early_snapshots(config, network.snapshots)
    if n_early:
        notes.append(
            f"{n_early} snapshot(s) precede the first carbon-price schedule year "
            f"({config.schedule[0].year}) and are priced at that entry ({config.schedule[0].price:g})."
        )
    if config.is_scheduled and len({e.price for e in config.schedule}) > 1:
        summary = ", ".join(f"{e.year}→{e.price:.0f}" for e in config.schedule)
        notes.append(
            f"Carbon price schedule [{summary}] {currency}/t is added to the objective for {n_emitting} "
            "emitting generator(s): price × co2_emissions ÷ efficiency × output (marginal_cost is unchanged)."
        )
    else:
        flat = config.schedule[0].price if config.is_scheduled else config.scalar
        notes.append(
            f"Carbon price {flat:.2f} {currency}/t is added to the objective for {n_emitting} "
            "emitting generator(s): price × co2_emissions ÷ efficiency × output (marginal_cost is unchanged)."
        )
    return notes
