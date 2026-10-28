"""Compatibility shim: this module moved to :mod:`backend.app.model_check.diagnostics` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.diagnostics`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.model_check.diagnostics`.
"""
import sys

from backend.app.model_check import diagnostics as _real

sys.modules[__name__] = _real
