"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.price_formation` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.price_formation`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.price_formation`.
"""
import sys

from backend.app.market_studies import price_formation as _real

sys.modules[__name__] = _real
