"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.simulation` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.simulation`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.simulation`.
"""
import sys

from backend.app.market_studies import simulation as _real

sys.modules[__name__] = _real
