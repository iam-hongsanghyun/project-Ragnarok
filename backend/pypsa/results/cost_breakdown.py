"""Operating-cost terms of the objective that the per-generator maths cannot see.

The fuel / carbon / load-shedding split is derived generator by generator from
``marginal_cost x dispatch``. The LP objective carries more: StorageUnit, Store
and Link marginal costs, ``marginal_cost_quadratic`` and ``stand_by_cost`` (and
the start-up / shut-down costs reported separately). PyPSA's own
``n.statistics.opex`` already sums every one of them per component with the
correct snapshot (and investment-period) weightings, so the breakdown takes its
totals from there and reports only what the linear maths did not explain.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd
import pypsa

_log = logging.getLogger("pypsa.solver")

# Below this a residual is solver noise / rounding, not a cost term.
_MIN_TERM = 0.5


def _friendly(component: str) -> str:
    """``StorageUnit`` -> ``Storage unit`` (CamelCase component name to a label)."""
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", component).split()
    return " ".join([words[0], *[w.lower() for w in words[1:]]]) if words else component


def statistics_opex_by_component(network: pypsa.Network) -> dict[str, float]:
    """``n.statistics.opex`` summed over names and periods, per component.

    Returns ``{}`` when the statistics module cannot be evaluated (unsolved
    network, unsupported component) so the breakdown degrades to the explicit
    generator terms instead of failing the run.
    """
    try:
        opex = network.statistics.opex(groupby=False)
    except Exception as exc:  # noqa: BLE001 — a reporting extra must not sink the run
        _log.debug("statistics.opex unavailable: %s", exc)
        return {}
    if opex is None or len(opex) == 0:
        return {}
    if isinstance(opex, pd.DataFrame):  # multi-period: one column per period
        opex = opex.sum(axis=1)
    opex = opex.fillna(0.0)
    return {str(c): float(v) for c, v in opex.groupby(level="component").sum().items()}


def other_operating_costs(
    network: pypsa.Network,
    *,
    generator_explained: float,
) -> list[dict[str, Any]]:
    """Cost-breakdown rows for objective terms beyond fuel / carbon / shedding.

    Args:
        network: Solved network.
        generator_explained: Generator operating cost already itemised
            (fuel + load shedding + start-up/shut-down; carbon is not in n.statistics.opex), in the same
            currency and weighting as ``n.statistics.opex``.

    Returns:
        ``[{"label", "value"}]`` rows: the generator remainder (quadratic and
        stand-by cost) and one row per other component with operating cost.
    """
    by_component = statistics_opex_by_component(network)
    rows: list[dict[str, Any]] = []
    remainder = by_component.pop("Generator", 0.0) - generator_explained
    if abs(remainder) >= _MIN_TERM:
        rows.append({"label": "Quadratic / stand-by cost", "value": round(remainder)})
    for component, value in sorted(by_component.items()):
        if abs(value) >= _MIN_TERM:
            rows.append({"label": f"{_friendly(component)} operating cost", "value": round(value)})
    return rows
