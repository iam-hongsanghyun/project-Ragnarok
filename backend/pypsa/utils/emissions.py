"""Compatibility shim: this module moved to :mod:`backend.app.emissions.accounting` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.utils.emissions`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.emissions.accounting`.
"""
import sys

from backend.app.emissions import accounting as _real

sys.modules[__name__] = _real
