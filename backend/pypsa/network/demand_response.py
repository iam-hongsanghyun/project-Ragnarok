"""Compatibility shim: this module moved to :mod:`backend.app.demand_response.shift` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.demand_response`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.demand_response.shift`.
"""
import sys

from backend.app.demand_response import shift as _real

sys.modules[__name__] = _real
