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

Scope: single-period outputs. Multi-period (pathway) bundles raise — the
frontend keeps deriving those client-side (it re-derives interactively per
selected period anyway).
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..network import build_network

_log = logging.getLogger("pypsa.solver")

_INDEX_COLS = ("snapshot", "timestamp", "name")  # current + legacy index columns


def _attach_outputs(network: Any, outputs: dict[str, Any]) -> list[str]:
    """Write stored outputs back onto the network (inverse of build_full_outputs).

    Returns notes about anything skipped. Raises ``ValueError`` on multi-period
    (pathway) series — out of scope for server-side derivation.
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
        if "period" in rows[0]:
            raise ValueError(
                "Multi-period (pathway) outputs are not supported by server-side "
                "derivation — the client derives those per selected period."
            )
        df = pd.DataFrame(rows)
        index_col = next((c for c in _INDEX_COLS if c in df.columns), None)
        if index_col is None:
            notes.append(f"{sheet}: no snapshot column — skipped")
            continue
        df[index_col] = pd.to_datetime(df[index_col])
        df = df.set_index(index_col).sort_index()
        df = df.drop(columns=[c for c in _INDEX_COLS if c in df.columns], errors="ignore")

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


def derive_results_from_outputs(
    model: dict[str, list[dict[str, Any]]],
    outputs: dict[str, Any],
    scenario: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full run-results payload derived from ``(model, outputs)`` — no solve.

    Raises:
        ValueError: multi-period outputs, or nothing attachable.
    """
    # Lazy import: this module lives inside the package the symbol comes from.
    from . import _build_solved_payload
    from ..pathway import parse_pathway_config
    from ..rolling import parse_rolling_config
    from ..sampling import parse_sampling_config
    from ..stochastic import parse_stochastic_config

    scenario = dict(scenario or {})
    options = dict(options or {})
    # A derivation never re-solves: strip every mode/config that would trigger
    # extra optimisation passes (MGA, merchant, asset swap, ESS, …) or gate the
    # payload into a study mode.
    for key in (
        "mgaConfig", "merchantConfig", "bidStrategyConfig", "assetSwapConfig",
        "essConfig", "marketSimConfig", "powerFlowConfig", "contingencyConfig",
        "rollingConfig", "stochasticConfig", "pathwayConfig", "samplingConfig",
        "securityConstrainedConfig", "enableLoadShedding",
    ):
        options.pop(key, None)

    network, notes = build_network(model, scenario, options)
    attach_notes = _attach_outputs(network, outputs)
    if network.generators_t.p.empty and network.loads_t.p.empty:
        raise ValueError("Outputs contain no dispatch series to derive analytics from.")
    network._objective = 0.0  # mark solved (pypsa: is_solved == objective assigned)

    snapshot_count = len(network.snapshots)
    snapshot_weight = (
        float(network.snapshot_weightings["objective"].iloc[0]) if snapshot_count else 1.0
    )
    emissions_factors: dict[str, float] = {}
    if "co2_emissions" in network.carriers.columns:
        emissions_factors = network.carriers["co2_emissions"].fillna(0.0).to_dict()

    derive_notes = [
        "Analytics re-derived server-side from the bundle's stored outputs (no re-solve).",
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
        pathway=parse_pathway_config(None),
        rolling=parse_rolling_config(None),
        stochastic=parse_stochastic_config(None),
        sampling=parse_sampling_config(None),
        rolling_windows=[],
        sclopf_enabled=False,
        solver_options={},
    )
    _log.info(
        "derived analytics from outputs: %d snapshots, %d generators (no re-solve)",
        snapshot_count, len(network.generators),
    )
    return payload
