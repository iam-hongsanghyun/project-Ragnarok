"""Compatibility shim: this module moved to :mod:`backend.app.company.ess` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.ess`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.company.ess`.
"""
import sys

from backend.app.company import ess as _real

sys.modules[__name__] = _real
