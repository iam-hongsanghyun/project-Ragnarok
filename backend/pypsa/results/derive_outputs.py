"""Server-side re-derivation of run analytics from stored outputs (X1).

An imported bundle (project / bare-xlsx result) carries the model and the raw
``outputs`` (``{"static", "series"}`` from :mod:`full_outputs`) but — for a
reconstructed bundle — no derived analytics. Historically the *browser*
re-derived them (766 lines of TS in ``lib/results/runResults.ts``), which both
duplicated the backend's analytics code and made large imports heavy client-side.

This derives them on the server instead, with **zero re-implementation**:

  1. ``build_network(model, scenario, options)`` — the same builder a fresh
     solve uses, so every coefficient (incl. the carbon adder folded into
     ``marginal_cost``) matches the original run;
  2. ``_attach_outputs`` — write the stored output series/statics back onto the
     network's ``*_t`` frames / static columns (the exact inverse of
     ``build_full_outputs``), then mark the network solved;
  3. ``_build_solved_payload`` — the *same* payload assembly ``run_pypsa`` runs
     after a fresh solve.

Because steps 1+3 are literally the fresh-solve code, "derived == fresh solve"
is an assertable identity — pinned field-by-field by ``test_derive_outputs``.

Scope: single-period and multi-period (pathway) outputs. A pathway bundle's
rows carry a ``period`` column and are keyed on ``(period, timestep)``. Pass
``period`` to :func:`derive_results_from_outputs` to get one investment
period's payload (see :func:`period_view_network`).
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..network import build_network
from .stat_metrics import name_dynamic_axes

_log = logging.getLogger("pypsa.solver")

_INDEX_COLS = ("snapshot", "timestamp", "name")  # current + legacy index columns


def _attach_outputs(network: Any, outputs: dict[str, Any]) -> list[str]:
    """Write stored outputs back onto the network (inverse of build_full_outputs).

    Returns notes about anything skipped.
    """
    notes: list[str] = []
    series = (outputs or {}).get("series") or {}
    static = (outputs or {}).get("static") or {}
    snapshots = network.snapshots

    for sheet, rows in series.items():
        if not rows or "-" not in sheet:
            continue
        list_name, attr = sheet.rsplit("-", 1)
        if list_name not in network.components.keys():
            continue
        df = pd.DataFrame(rows)
        index_col = next((c for c in _INDEX_COLS if c in df.columns), None)
        if index_col is None:
            notes.append(f"{sheet}: no snapshot column — skipped")
            continue
        stamps = pd.to_datetime(df[index_col])
        if "period" in df.columns and isinstance(snapshots, pd.MultiIndex):
            # Pathway rows repeat the same timestep in every investment period:
            # key on (period, timestep), the index the network was built with.
            df.index = pd.MultiIndex.from_arrays(
                [pd.to_numeric(df["period"], errors="coerce").to_numpy(), stamps],
                names=list(snapshots.names),
            )
        else:
            df.index = pd.DatetimeIndex(stamps)
            df = df.sort_index()
        df = df.drop(columns=[c for c in (*_INDEX_COLS, "period") if c in df.columns], errors="ignore")

        comp = network.components[list_name]
        known = {str(i) for i in comp.static.index}
        unknown = [c for c in df.columns if str(c) not in known]
        if unknown:
            notes.append(
                f"{sheet}: dropped {len(unknown)} column(s) not present in the model"
            )
            df = df.drop(columns=unknown)
        if df.empty or not len(df.columns):
            continue
        df = df.reindex(snapshots).astype(float).fillna(0.0)
        t_frames = getattr(network, f"{list_name}_t", None)
        if t_frames is None:
            t_frames = comp.dynamic
        t_frames[attr] = df
    name_dynamic_axes(network)  # PyPSA's column-axis name; pandas 3.0.5 revenue needs it

    for list_name, comps in static.items():
        if list_name not in network.components.keys():
            continue
        sdf = network.components[list_name].static
        for comp_name, attrs in (comps or {}).items():
            if comp_name not in sdf.index:
                continue
            for attr, value in (attrs or {}).items():
                try:
                    sdf.loc[comp_name, attr] = value
                except (ValueError, TypeError):
                    notes.append(f"{list_name}.{comp_name}.{attr}: could not attach")
    return notes


def _pathway_options(
    options: dict[str, Any], outputs: dict[str, Any], model: dict[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    """The run's ``pathwayConfig``, reconstructed when a bare import lacks one.

    A stored solve keeps ``options.pathwayConfig``. A bare multi-period result
    (outputs rows with a ``period`` column, no options) does not; its periods are
    read from the rows and given unit weights, the neutral choice - the explicit
    weights live in the options that produced the run.
    """
    cfg = options.get("pathwayConfig")
    if isinstance(cfg, dict) and (cfg.get("enabled") or cfg.get("planningMode") == "pathway"):
        return cfg
    found: set[int] = set()
    for rows in ((outputs or {}).get("series") or {}).values():
        if rows and "period" in rows[0]:
            for row in rows:
                try:
                    found.add(int(float(row["period"])))
                except (KeyError, TypeError, ValueError):
                    continue
            break
    if not found:
        return {}
    return {
        "enabled": True,
        "planningMode": "pathway",
        "snapshotMappingMode": "explicit_period_column",
        "periods": [{"period": p, "objectiveWeight": 1.0, "yearsWeight": 1.0} for p in sorted(found)],
    }


def solved_network_to_bundle(network: Any, filename: str = "") -> dict[str, Any]:
    """A run bundle ``{model, scenario, options, outputs}`` from an imported solved network.

    A PyPSA netCDF / HDF5 file written after ``optimize`` carries the solution
    (``p_nom_opt``, ``generators_t.p``, ``buses_t.marginal_price`` ...) inside the
    network. This lifts it into Ragnarok's stored-run shape: the input side through
    :func:`network_to_model` (the same serialiser the editor import uses), the output
    side through :func:`build_full_outputs`. A multi-period network gets a
    ``pathwayConfig`` read from its ``investment_period_weightings``.

    Raises:
        ValueError: the network has no solution (no generator or load dispatch).
    """
    import pandas as pd

    from ..network.serialize import network_to_model
    from .full_outputs import build_full_outputs

    if network.generators_t.p.empty and network.loads_t.p.empty:
        raise ValueError("The network carries no results (no dispatch series).")
    # A PyPSA-native file stores the ANNUALISED capital cost; build_network must not
    # annuitise it a second time (and then needs no discount rate).
    options: dict[str, Any] = {"skipCapexAnnuitisation": True}
    if filename:
        options["filename"] = filename
    if isinstance(network.snapshots, pd.MultiIndex) and "period" in network.snapshots.names:
        weights = network.investment_period_weightings
        options["pathwayConfig"] = {
            "enabled": True,
            "planningMode": "pathway",
            "snapshotMappingMode": "explicit_period_column",
            "periods": [
                {
                    "period": int(p),
                    "objectiveWeight": float(weights.at[p, "objective"]) if p in weights.index else 1.0,
                    "yearsWeight": float(weights.at[p, "years"]) if p in weights.index else 1.0,
                }
                for p in network.investment_periods
            ],
        }
    return {
        "model": network_to_model(network),
        "scenario": {},
        "options": options,
        "outputs": build_full_outputs(network),
    }


def mark_solved(network: Any) -> None:
    """Flag a rebuilt network as solved, the way ``optimize`` leaves it.

    ``_objective`` assigned is PyPSA's ``is_solved``. A multi-period network also needs
    ``_multi_invest``: it is what makes PyPSA (and
    :func:`backend.pypsa.utils.emissions.primary_energy_emissions`) apply the investment-period
    ``years`` weighting, and a rebuilt network never ran ``optimize(multi_investment_periods=True)``.
    Without it a rebuilt pathway run reported 1/years of its emissions.
    """
    network._objective = 0.0
    if getattr(network, "has_investment_periods", False):
        network._multi_invest = 1


def period_view_network(network: Any, period: int) -> Any:
    """One investment period of a solved multi-period network.

    ``Network.copy(snapshots=, investment_periods=)`` keeps the period's snapshot
    rows, its ``investment_period_weightings`` row, every static column (``p_nom_opt``
    included) and the solved ``*_t`` frames. The copy is a normal multi-period
    network with a single period, so every extraction helper applies the same
    rules it applies to the whole horizon: assets outside their build/lifetime
    window are masked, money carries the period's ``objective`` weight, energy is
    summed with the snapshot weightings, emissions carry the ``years`` weight.

    Raises:
        ValueError: ``period`` is not one of the network's investment periods.
    """
    level = network.snapshots.get_level_values("period")
    if period not in set(int(p) for p in level.unique()):
        raise ValueError(f"Period {period} is not an investment period of this run.")
    view = network.copy(snapshots=network.snapshots[level == period], investment_periods=[period])
    mark_solved(view)
    return view


def derive_results_from_outputs(
    model: dict[str, list[dict[str, Any]]],
    outputs: dict[str, Any],
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    period: int | None = None,
) -> dict[str, Any]:
    """Full run-results payload derived from ``(model, outputs)`` - no solve.

    Args:
        model, outputs, scenario, options: the stored run (see module docstring).
        period: for a multi-period (pathway) run, derive the payload of this one
            investment period instead of the whole horizon. The period rules are
            those of :func:`period_view_network`. ``None`` = the whole horizon.

    Raises:
        ValueError: nothing attachable, or ``period`` is not a period of the run.
    """
    # Lazy import: this module lives inside the package the symbol comes from.
    from . import _build_solved_payload
    from ..pathway import parse_pathway_config
    from ..rolling import parse_rolling_config
    from ..sampling import parse_sampling_config
    from ..stochastic import parse_stochastic_config

    scenario = dict(scenario or {})
    options = dict(options or {})
    pathway_cfg = _pathway_options(options, outputs, model)
    # A derivation never re-solves: strip every mode/config that would trigger
    # extra optimisation passes (MGA, merchant, asset swap, ESS, ...) or gate the
    # payload into a study mode. Build-time model options stay - in particular
    # ``enableLoadShedding`` only injects the ``load_shedding_*`` generators at
    # build time (no extra solve); stripping it made ``_attach_outputs`` drop
    # their stored dispatch columns and report a run's shed energy as zero.
    for key in (
        "mgaConfig", "merchantConfig", "bidStrategyConfig", "assetSwapConfig",
        "essConfig", "marketSimConfig", "powerFlowConfig", "contingencyConfig",
        "rollingConfig", "stochasticConfig", "pathwayConfig",
        "securityConstrainedConfig",
    ):
        options.pop(key, None)
    # ``pathwayConfig`` is a build-time option too: it makes the snapshot axis a
    # (period, timestep) MultiIndex and sets the period weightings, so it is
    # put back (reconstructed for a bare import) - no MGA/solve is triggered.
    if pathway_cfg:
        options["pathwayConfig"] = pathway_cfg
    # ``samplingConfig`` is kept: it is a build-time option (selects the sampled
    # snapshots and sets their W/M weighting), not an extra solve. Dropping it
    # rebuilt the full-window axis with unit weights, so every energy / cost
    # total of a sampled run came out 1/weight too small.

    network, notes = build_network(model, scenario, options)
    attach_notes = _attach_outputs(network, outputs)
    if network.generators_t.p.empty and network.loads_t.p.empty:
        raise ValueError("Outputs contain no dispatch series to derive analytics from.")
    mark_solved(network)
    if period is not None:
        network = period_view_network(network, int(period))

    snapshot_count = len(network.snapshots)
    snapshot_weight = (
        float(network.snapshot_weightings["objective"].iloc[0]) if snapshot_count else 1.0
    )
    emissions_factors: dict[str, float] = {}
    if "co2_emissions" in network.carriers.columns:
        emissions_factors = network.carriers["co2_emissions"].fillna(0.0).to_dict()

    derive_notes = [
        "Analytics re-derived server-side from the bundle's stored outputs (no re-solve).",
        *(
            [f"Investment period {int(period)} only: assets outside their build/lifetime window "
             "are masked, money carries the period's objective weight, emissions its years weight."]
            if period is not None else []
        ),
        *attach_notes,
        *notes,
    ]
    payload = _build_solved_payload(
        network, model, scenario, options, derive_notes,
        currency=str(options.get("currencySymbol", "$")),
        owner_column=str(options.get("ownerColumn") or "owner"),
        emissions_factors=emissions_factors,
        snapshot_count=snapshot_count,
        snapshot_weight=snapshot_weight,
        pathway=parse_pathway_config(pathway_cfg),
        rolling=parse_rolling_config(None),
        stochastic=parse_stochastic_config(None),
        sampling=parse_sampling_config(options.get("samplingConfig")),
        rolling_windows=[],
        sclopf_enabled=False,
        solver_options={},
    )
    _log.info(
        "derived analytics from outputs%s: %d snapshots, %d generators (no re-solve)",
        f" (period {int(period)})" if period is not None else "",
        snapshot_count, len(network.generators),
    )
    return payload
