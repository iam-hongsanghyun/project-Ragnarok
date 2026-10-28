"""Compatibility shim: this module moved to :mod:`backend.app.adequacy.adequacy` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.adequacy`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.adequacy.adequacy`.
"""
import sys

from backend.app.adequacy import adequacy as _real

sys.modules[__name__] = _real
