"""Operating-reserves module: spinning-reserve co-optimisation as a declared ``extra_functionality`` term.

PyPSA has no reserve product. With ``options.reserveConfig.enabled`` this module adds a reserve variable
``r[g, t]``, a headroom constraint ``p + r <= p_nom * p_max_pu`` and a requirement constraint
``sum_g r >= R_t`` to the linopy model (a ``constraints`` hook, so it applies to every optimise path), and
reads the requirement dual back as the reserve price (a ``study`` hook, the ``reserve`` result block).
"""
from __future__ import annotations

from .reserves import apply_reserve_constraints, extract_reserve_results

__all__ = ["apply_reserve_constraints", "extract_reserve_results"]
