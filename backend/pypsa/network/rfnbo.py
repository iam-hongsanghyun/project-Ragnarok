"""Compatibility shim: this module moved to :mod:`backend.app.p2x.rfnbo` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.rfnbo`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.p2x.rfnbo`.
"""
import sys

from backend.app.p2x import rfnbo as _real

sys.modules[__name__] = _real
