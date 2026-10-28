"""Modelling-to-Generate-Alternatives (MGA) — the near-optimal capacity space.

A single cost-optimal plan hides the fact that many *structurally different*
systems cost almost the same. MGA maps that ambiguity: for each technology it
asks "how little / how much of this carrier can the system build while staying
within ``slack`` of optimal cost?". The min/max pair per carrier traces the
near-optimal corridor — the decision-relevant spread, not a single point.

We delegate the optimisation to PyPSA's ``n.optimize.optimize_mga`` verbatim
(engine-feature parity). Each direction runs on a fresh ``network.copy()`` of
the *solved* optimum so the budget constraint
(``total_cost <= (1 + slack) * optimal_cost``) is always rebuilt from the true
optimum rather than drifting onto a previous alternative.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pypsa

from ...app import carbon_pricing

_log = logging.getLogger("pypsa.solver")

# Each selected carrier costs two LP solves (min + max). Cap the number of
# carriers explored so a single run cannot fan out into an unbounded solve
# count; anything dropped is logged, never silently truncated.
_DEFAULT_MAX_CARRIERS = 6


def _capacity_by_carrier(network: pypsa.Network) -> dict[str, float]:
    """Optimised generator capacity (MW) summed per carrier."""
    gens = network.generators
    if gens.empty:
        return {}
    grouped = gens.groupby("carrier")["p_nom_opt"].sum()
    return {str(c): round(float(v), 3) for c, v in grouped.items()}


def _priced_copy(network: pypsa.Network) -> pypsa.Network:
    """Scratch copy for an MGA solve, with the carbon price in ``marginal_cost``.

    ``optimize_mga`` builds its own model (no ``extra_functionality`` hook) and bounds the cost with
    ``n.statistics`` of the copy, so the carbon-pricing module's scratch-copy form is what keeps the price in
    both the budget and the dispatch. The run's own network is untouched.
    """
    work = network.copy()
    carbon_pricing.write_marginal_cost_adder(work)
    return work


def _solution_cost(network: pypsa.Network) -> float:
    """Total system cost (capex + opex) of the network's current solution."""
    return float(network.statistics.capex().sum() + network.statistics.opex().sum())


# Component -> (PyPSA static frame attribute, default nominal attribute).
_MGA_COMPONENTS: dict[str, tuple[str, str]] = {
    "Generator": ("generators", "p_nom"),
    "Link": ("links", "p_nom"),
    "StorageUnit": ("storage_units", "p_nom"),
    "Store": ("stores", "e_nom"),
    "Line": ("lines", "s_nom"),
    "Transformer": ("transformers", "s_nom"),
}


def _mga_dimensions(
    network: pypsa.Network, spec: dict[str, Any] | None, default_carriers: list[str]
) -> dict[str, dict[str, Any]]:
    """Low-dimensional space for MGA-in-direction, in PyPSA's ``weights`` structure.

    ``spec`` maps a dimension name to ``{component, attribute?, carriers?}``; with no
    spec there is one ``Generator``/``p_nom`` dimension per extendable carrier.
    Each dimension is the sum of that attribute over the component rows whose
    carrier is listed (all rows when ``carriers`` is omitted).

    Raises:
        ValueError: on an unknown component or an empty dimension.
    """
    if not spec:
        spec = {c: {"component": "Generator", "attribute": "p_nom", "carriers": [c]} for c in default_carriers}
    dims: dict[str, dict[str, Any]] = {}
    for name, item in spec.items():
        comp = str(item.get("component", "Generator"))
        if comp not in _MGA_COMPONENTS:
            raise ValueError(f"MGA dimension {name!r}: unknown component {comp!r}")
        frame_name, default_attr = _MGA_COMPONENTS[comp]
        attr = str(item.get("attribute", default_attr))
        frame = getattr(network, frame_name)
        if frame.empty:
            raise ValueError(f"MGA dimension {name!r}: network has no {frame_name}")
        carriers = item.get("carriers")
        mask = frame["carrier"].astype(str).isin([str(c) for c in carriers]) if carriers else pd.Series(True, index=frame.index)
        if f"{attr}_extendable" in frame.columns:
            mask = mask & frame[f"{attr}_extendable"].astype(bool)
        if not bool(mask.any()):
            raise ValueError(f"MGA dimension {name!r}: no extendable {frame_name} match")
        dims[str(name)] = {comp: {attr: mask.astype(float)}}
    return dims


def _direction_table(cfg: dict[str, Any], keys: list[str]) -> pd.DataFrame:
    """Direction vectors as a DataFrame (rows = directions, columns = dimension names)."""
    raw = cfg.get("directions")
    if isinstance(raw, dict) and raw.get("random"):
        from pypsa.optimization.mga import generate_directions_random

        return generate_directions_random(keys, int(raw["random"]), seed=int(raw.get("seed", 0)))
    rows = []
    for item in raw or []:
        weights = item.get("weights", item) if isinstance(item, dict) else {}
        rows.append({k: float(weights.get(k, 0.0)) for k in keys})
    return pd.DataFrame(rows, columns=keys)


def build_mga_directions(
    network: pypsa.Network,
    config: dict[str, Any],
    *,
    slack: float,
    solver_name: str,
    solver_options: dict[str, Any],
    io_api: str | None,
    multi_investment_periods: bool,
    default_carriers: list[str],
) -> dict[str, Any]:
    """MGA in a direction / in several directions (P24).

    Each direction is a vector over user-defined dimensions (default: one per
    extendable-generator carrier); PyPSA maximises the projection of the system
    onto that vector within ``slack`` of optimal cost, and ``project_solved``
    reports where the alternative lands.

    * ``maxParallel`` <= 1 (default): serial ``optimize_mga_in_direction`` on a
      copy of the solved optimum per direction, so cost and capacity mix are
      reported too.
    * ``maxParallel`` > 1: native ``optimize_mga_in_multiple_directions`` (process
      pool; reports coordinates only).

    Returns:
        ``{dimensions, maxParallel, results: [{direction, status, coordinates, cost?,
        costRatio?, capacityByCarrier?}], failed}``.
    """
    spec = config.get("dimensions")
    dimensions = _mga_dimensions(network, spec, default_carriers)
    keys = list(dimensions)
    table = _direction_table(config, keys)
    max_parallel = max(1, int(config.get("maxParallel", 1) or 1))
    optimum_cost = _solution_cost(_priced_copy(network))
    solve_kwargs: dict[str, Any] = {
        "solver_name": solver_name,
        "solver_options": solver_options,
    }
    if io_api:
        solve_kwargs["io_api"] = io_api
    results: list[dict[str, Any]] = []
    failed = 0
    if max_parallel > 1 and len(table) > 1:
        dirs_df, coords_df = _priced_copy(network).optimize.optimize_mga_in_multiple_directions(
            table,
            dimensions,
            multi_investment_periods=multi_investment_periods,
            slack=slack,
            max_parallel=max_parallel,
            **solve_kwargs,
        )
        for (_, drow), (_, crow) in zip(dirs_df.iterrows(), coords_df.iterrows(), strict=False):
            results.append({
                "direction": {k: round(float(v), 6) for k, v in drow.items()},
                "status": "ok",
                "coordinates": {k: round(float(v), 3) for k, v in crow.items()},
            })
        failed = len(table) - len(results)
    else:
        for _, drow in table.iterrows():
            direction = {k: float(v) for k, v in drow.items()}
            try:
                work = _priced_copy(network)
                with pypsa.option_context("params.optimize.include_objective_constant", True):
                    status, condition, coords = work.optimize.optimize_mga_in_direction(
                        direction=direction,
                        dimensions=dimensions,
                        multi_investment_periods=multi_investment_periods,
                        slack=slack,
                        **solve_kwargs,
                    )
            except Exception as exc:  # noqa: BLE001 - one direction must not sink the rest
                _log.warning("MGA direction %s failed: %s", direction, exc)
                failed += 1
                continue
            if str(status) != "ok" or coords is None:
                failed += 1
                continue
            cost = _solution_cost(work)
            results.append({
                "direction": {k: round(v, 6) for k, v in direction.items()},
                "status": str(status),
                "coordinates": {str(k): round(float(v), 3) for k, v in coords.items()},
                "cost": round(cost, 2),
                "costRatio": round(cost / optimum_cost, 4) if optimum_cost else None,
                "capacityByCarrier": _capacity_by_carrier(work),
            })
    return {
        "dimensions": keys,
        "maxParallel": max_parallel,
        "results": results,
        "failed": failed,
    }


def build_mga(
    network: pypsa.Network,
    *,
    slack: float,
    carriers: list[str] | None,
    currency: str,
    solver_options: dict[str, Any] | None = None,
    io_api: str = "direct",
    multi_investment_periods: bool = False,
    max_carriers: int = _DEFAULT_MAX_CARRIERS,
    solver_name: str = "highs",
    config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Map the near-optimal capacity corridor for each selected carrier.

    Runs ``optimize_mga`` twice (min, max) per carrier on copies of the solved
    optimum and returns the optimum mix plus every alternative's full capacity
    mix and cost. Returns ``None`` when there is nothing meaningful to explore
    (unsolved network, no extendable generators) — never raises into the run.

    Args:
        network: A network already solved by ``n.optimize()``.
        slack: Cost relaxation; alternatives stay within ``1 + slack`` of the
            optimal cost (e.g. ``0.05`` = within 5%).
        carriers: Carriers to vary; ``None``/empty = every extendable-generator
            carrier, capped at ``max_carriers``.
        currency: Currency symbol for the cost figures (passthrough for the UI).
        solver_options: HiGHS options mirrored from the main solve.
        io_api: linopy IO api, mirrored from the main solve.
        multi_investment_periods: Pass-through for pathway (multi-period) runs.
        max_carriers: Hard cap on carriers explored (each costs two solves).
        solver_name: linopy solver for the MGA solves (the main solve's solver).
        config: the ``mgaConfig`` block. Beyond ``slack``/``carriers`` it may carry
            ``minMax`` (default true; false skips the per-carrier min/max pairs),
            ``dimensions``, ``directions`` and ``maxParallel`` (see
            :func:`build_mga_directions`).

    Returns:
        ``{slack, currency, optimum: {cost, capacityByCarrier},
        carriers, alternatives: [{carrier, sense, status, cost, costRatio,
        capacityByCarrier}], droppedCarriers}`` or ``None``.
    """
    if not getattr(network, "is_solved", False):
        return None

    gens = network.generators
    if gens.empty:
        return None
    # MGA only moves *extendable* capacity; carriers with no extendable
    # generator have a fixed p_nom and cannot vary in the near-optimal space.
    extendable = gens[gens["p_nom_extendable"]] if "p_nom_extendable" in gens.columns else gens.iloc[0:0]
    if extendable.empty:
        return None
    extendable_carriers = [str(c) for c in pd.unique(extendable["carrier"]) if str(c)]
    if not extendable_carriers:
        return None

    requested = [str(c) for c in (carriers or []) if str(c)]
    selected = [c for c in requested if c in extendable_carriers] or extendable_carriers
    dropped = selected[max_carriers:]
    selected = selected[:max_carriers]
    if dropped:
        _log.warning(
            "MGA: exploring %d carriers (cap=%d); dropped %d: %s",
            len(selected), max_carriers, len(dropped), dropped,
        )

    config = config or {}
    min_max = config.get("minMax", True) is not False
    # ``network.copy()`` refuses while a solver model is attached; detach it first.
    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001 — best effort; copy() will report if it still fails
        pass
    optimum_cost = _solution_cost(_priced_copy(network))
    optimum_mix = _capacity_by_carrier(network)

    # ``network.copy()`` refuses while a solver model is attached; detach it once
    # on the base. The app recomputes every reported number from solved
    # dataframes, never from the live solver model, so this is side-effect-free
    # for the rest of the run.
    try:
        if network.model is not None:
            network.model.solver_model = None
    except Exception:  # noqa: BLE001 — best effort; copy() will report if it still fails
        pass

    solver_options = solver_options or {}
    alternatives: list[dict[str, Any]] = []
    for carrier in selected:
        weights = {
            "Generator": {
                "p_nom": pd.Series(
                    [1.0 if str(c) == carrier else 0.0 for c in gens["carrier"]],
                    index=gens.index,
                )
            }
        }
        for sense in (("min", "max") if min_max else ()):
            try:
                work = _priced_copy(network)
                status, condition = work.optimize.optimize_mga(
                    weights=weights,
                    sense=sense,
                    slack=slack,
                    multi_investment_periods=multi_investment_periods,
                    # include_objective_constant stays True here (passed explicitly:
                    # PyPSA 1.4 warns when unset), however tempting it is to match
                    # the main solve's False. PyPSA's budget
                    # constraint is written to pair with the constant INCLUDED:
                    #
                    #     objective + installed_capex <= (1 + slack) * (capex + opex)
                    #
                    # With the constant in, the objective is (capex + opex) minus
                    # the installed capex, so the two sides balance. Take it out
                    # and the left-hand side gains that installed capex twice —
                    # on this course's expanded year, 25.6M + 7.5M against a
                    # budget of 26.9M — so EVERY direction came back infeasible
                    # and the whole study returned nothing at all.
                    include_objective_constant=True,
                    solver_name=solver_name,
                    solver_options=solver_options,
                    io_api=io_api,
                )
            except Exception as exc:  # noqa: BLE001 — one direction failing must not sink the table
                _log.warning("MGA %s/%s failed: %s", carrier, sense, exc)
                continue
            if str(status) != "ok":
                _log.warning("MGA %s/%s non-optimal: %s/%s", carrier, sense, status, condition)
                continue
            cost = _solution_cost(work)
            alternatives.append(
                {
                    "carrier": carrier,
                    "sense": sense,
                    "status": str(status),
                    "cost": round(cost, 2),
                    "costRatio": round(cost / optimum_cost, 4) if optimum_cost else None,
                    "capacityByCarrier": _capacity_by_carrier(work),
                }
            )

    directions: dict[str, Any] | None = None
    if config.get("directions"):
        directions = build_mga_directions(
            network,
            config,
            slack=slack,
            solver_name=solver_name,
            solver_options=solver_options,
            io_api=io_api,
            multi_investment_periods=multi_investment_periods,
            default_carriers=selected,
        )
    if not alternatives and not (directions and directions["results"]):
        return None
    _log.info("MGA: %d alternatives across %d carriers (slack=%.3f)", len(alternatives), len(selected), slack)
    return {
        "directions": directions,
        "slack": round(float(slack), 4),
        "currency": currency,
        "optimum": {"cost": round(optimum_cost, 2), "capacityByCarrier": optimum_mix},
        "carriers": selected,
        "alternatives": alternatives,
        "droppedCarriers": dropped,
    }
