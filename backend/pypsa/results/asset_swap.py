"""Compatibility shim: this module moved to :mod:`backend.app.company.asset_swap` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.asset_swap`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.company.asset_swap`.
"""
import sys

from backend.app.company import asset_swap as _real

sys.modules[__name__] = _real
