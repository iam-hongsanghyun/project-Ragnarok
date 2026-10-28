"""Compatibility shim: this module moved to :mod:`backend.app.constraints.custom_constraints` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.custom_constraints`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.constraints.custom_constraints`.
"""
import sys

from backend.app.constraints import custom_constraints as _real

sys.modules[__name__] = _real
