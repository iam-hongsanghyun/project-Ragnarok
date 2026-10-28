"""Compatibility shim: this module moved to :mod:`backend.app.market_studies.lmp_decomposition` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.lmp_decomposition`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.market_studies.lmp_decomposition`.
"""
import sys

from backend.app.market_studies import lmp_decomposition as _real

sys.modules[__name__] = _real
