"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.ppa` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.ppa`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.ppa`.
"""
import sys

from backend.app.market_studies import ppa as _real

sys.modules[__name__] = _real
