"""Compatibility shim: this module moved to :mod:`backend.app.plants.cofiring` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.cofiring`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.plants.cofiring`.
"""
import sys

from backend.app.plants import cofiring as _real

sys.modules[__name__] = _real
