"""Compatibility shim: this module moved to :mod:`backend.app.constraints.constraint_checks` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.constraint_checks`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.constraints.constraint_checks`.
"""
import sys

from backend.app.constraints import constraint_checks as _real

sys.modules[__name__] = _real
