"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.optimal_bid` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.optimal_bid`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.optimal_bid`.
"""
import sys

from backend.app.market_studies import optimal_bid as _real

sys.modules[__name__] = _real
