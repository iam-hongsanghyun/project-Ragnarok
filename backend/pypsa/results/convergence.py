"""Compatibility shim: this module moved to :mod:`backend.app.adequacy.convergence` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.convergence`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.adequacy.convergence`.
"""
import sys

from backend.app.adequacy import convergence as _real

sys.modules[__name__] = _real
