"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.bid_strategy` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.bid_strategy`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.bid_strategy`.
"""
import sys

from backend.app.market_studies import bid_strategy as _real

sys.modules[__name__] = _real
