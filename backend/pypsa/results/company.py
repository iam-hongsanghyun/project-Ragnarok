"""Compatibility shim: this module moved to :mod:`backend.app.company.company` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.company`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.company.company`.
"""
import sys

from backend.app.company import company as _real

sys.modules[__name__] = _real
