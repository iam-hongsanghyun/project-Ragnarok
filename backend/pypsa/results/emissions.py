"""Compatibility shim: this module moved to :mod:`backend.app.emissions.breakdown` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.emissions`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.emissions.breakdown`.
"""
import sys

from backend.app.emissions import breakdown as _real

sys.modules[__name__] = _real
