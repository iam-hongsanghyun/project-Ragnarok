"""Compatibility shim: this module moved to :mod:`backend.app.adequacy.correlated_sampling` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.correlated_sampling`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.adequacy.correlated_sampling`.
"""
import sys

from backend.app.adequacy import correlated_sampling as _real

sys.modules[__name__] = _real
