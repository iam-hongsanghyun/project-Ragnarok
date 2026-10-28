"""Compatibility shim: this module moved to :mod:`backend.app.model_check.checks` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.model_check`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.model_check.checks`.
"""
import sys

from backend.app.model_check import checks as _real

sys.modules[__name__] = _real
