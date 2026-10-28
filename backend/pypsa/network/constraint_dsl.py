"""Compatibility shim: this module moved to :mod:`backend.app.constraints.constraint_dsl` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.constraint_dsl`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.constraints.constraint_dsl`.
"""
import sys

from backend.app.constraints import constraint_dsl as _real

sys.modules[__name__] = _real
