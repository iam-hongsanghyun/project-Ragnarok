"""Stochastic module: probability-weighted scenarios on top of PyPSA's native ``set_scenarios``.

PyPSA owns the scenario dimension (``n.set_scenarios``) and the CVaR risk preference
(``n.set_risk_preference``); both stay native. This module owns what PyPSA lacks around them:

* the per-scenario **overrides** the user authors (``multiply`` / ``set`` on a sheet attribute, by name or
  carrier) applied to the scenario-broadcast frames - a ``build_step`` hook;
* the **collapse** of the scenario-indexed solution to one representative scenario so the single-scenario
  result pipeline keeps working, with the duals divided back by the scenario probability and the global
  constraint ``mu`` recovered from linopy - a ``post_solve`` hook, reported in the ``stochastic`` payload block.

Hooks are declared in :mod:`.hooks`; the maths is in :mod:`.scenarios`.
"""
from __future__ import annotations

from .scenarios import (
    ScenarioOverride,
    StochasticConfig,
    StochasticScenario,
    apply_scenarios,
    collapse_to_representative_scenario,
    is_scenario_invariant,
    parse_stochastic_config,
    per_scenario_summaries,
)

__all__ = [
    "ScenarioOverride", "StochasticConfig", "StochasticScenario", "apply_scenarios",
    "collapse_to_representative_scenario", "is_scenario_invariant", "parse_stochastic_config",
    "per_scenario_summaries",
]
