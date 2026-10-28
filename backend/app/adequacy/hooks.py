"""Adequacy module hooks (see :mod:`backend.app.module_hooks`)."""
from __future__ import annotations

import logging
from typing import Any

from backend.app import module_hooks as mh

_log = logging.getLogger(__name__)
MODULE = "adequacy"


def _adequacy(ctx: mh.RunContext) -> dict[str, Any]:
    """Stochastic renewable ensemble vs load (A1 + A2 LOLE); None when no time-varying renewable generator.

    Never raises into the solve: any failure (e.g. pathway snapshots are (period, timestep) tuples) degrades
    to a run note, like the Monte Carlo extras below.
    """
    from .adequacy import build_adequacy

    try:
        return {"adequacy": build_adequacy(ctx.network)}
    except Exception as exc:  # noqa: BLE001 - never sink the run over an adequacy extra
        ctx.notes.append(f"Resource adequacy could not be computed: {exc}")
        _log.warning("adequacy failed: %s", exc)
        return {"adequacy": None}


def _optional_mc(config_key: str, payload_key: str, builder_name: str, module_name: str, failure_note: str):
    """A Monte Carlo extra that runs only when ``options[config_key].enabled`` and never raises into the solve."""

    def run(ctx: mh.RunContext) -> dict[str, Any]:
        if not bool((ctx.options.get(config_key) or {}).get("enabled")):
            return {payload_key: None}
        import importlib

        builder = getattr(importlib.import_module(f"{__package__}.{module_name}"), builder_name)
        try:
            return {payload_key: builder(ctx.network, ctx.options)}
        except Exception as exc:  # noqa: BLE001 - never sink the run over an MC extra
            ctx.notes.append(f"{failure_note} could not be computed: {exc}")
            _log.warning("%s failed: %s", module_name, exc)
            return {payload_key: None}

    return run


mh.register("study", "adequacy", _adequacy, module=MODULE, order=180, payload_keys=("adequacy",))
# Thermal forced-outage Monte Carlo: outage-aware LOLE/EUE with a distribution across members.
mh.register("study", "outage-mc", _optional_mc("outageMcConfig", "outageMc", "build_outage_mc", "outage_mc",
                                               "Thermal outage Monte Carlo"),
            module=MODULE, order=181, payload_keys=("outageMc",))
# ELCC / capacity credit: firm-MW-equivalent of each target carrier, bisecting on the outage-inclusive LOLE kernel.
mh.register("study", "elcc", _optional_mc("elccConfig", "elcc", "build_elcc", "elcc", "ELCC / capacity credit"),
            module=MODULE, order=182, payload_keys=("elcc",))
# Correlated multi-driver Monte Carlo (one-factor stress on demand, renewable CF, hydro inflow).
mh.register("study", "correlated-sampling",
            _optional_mc("correlatedSamplingConfig", "correlatedSampling", "build_correlated_sampling",
                         "correlated_sampling", "Correlated multi-driver Monte Carlo"),
            module=MODULE, order=183, payload_keys=("correlatedSampling",))
# Convergence-controlled outage Monte Carlo (+ maintenance placement): batches until the relative SE stabilises.
mh.register("study", "convergence",
            _optional_mc("convergenceConfig", "convergenceSampling", "build_convergence", "convergence",
                         "Convergence-controlled sampling"),
            module=MODULE, order=184, payload_keys=("convergenceSampling",))
