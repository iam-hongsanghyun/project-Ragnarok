"""Compatibility shim: this module moved to :mod:`backend.app.reserves.reserves` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.network.reserves`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.reserves.reserves`.
"""
import sys

from backend.app.reserves import reserves as _real

sys.modules[__name__] = _real
