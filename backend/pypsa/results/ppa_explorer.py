"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.ppa_explorer` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.ppa_explorer`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.ppa_explorer`.
"""
import sys

from backend.app.market_studies import ppa_explorer as _real

sys.modules[__name__] = _real
