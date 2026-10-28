"""Compatibility shim: this module moved to :mod:`backend.app.adequacy.outage_mc` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.outage_mc`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.adequacy.outage_mc`.
"""
import sys

from backend.app.adequacy import outage_mc as _real

sys.modules[__name__] = _real
