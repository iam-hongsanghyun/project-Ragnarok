"""Compatibility shim: this module moved to :mod:`backend.app.company.company_statement` (core cleanup S7, module extraction).

Aliases the real module in ``sys.modules`` so ``import backend.pypsa.results.company_statement`` and monkeypatching reach the same object.
New code imports :mod:`backend.app.company.company_statement`.
"""
import sys

from backend.app.company import company_statement as _real

sys.modules[__name__] = _real
