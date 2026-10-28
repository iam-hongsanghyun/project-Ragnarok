"""Compatibility shim: this module moved to :mod:`backend.app.stochastic.scenarios` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.stochastic`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.stochastic.scenarios`.
"""
import sys

from backend.app.stochastic import scenarios as _real

sys.modules[__name__] = _real
