"""Compatibility shim: this module moved to :mod:`backend.app.company.finance` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.finance`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.company.finance`.
"""
import sys

from backend.app.company import finance as _real

sys.modules[__name__] = _real
