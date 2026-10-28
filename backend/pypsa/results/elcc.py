"""Compatibility shim: this module moved to :mod:`backend.app.adequacy.elcc` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.elcc`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.adequacy.elcc`.
"""
import sys

from backend.app.adequacy import elcc as _real

sys.modules[__name__] = _real
