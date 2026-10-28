"""Model-check module: read-only checks and diagnostics around a solve.

* :mod:`.checks` - the pre-run model back-brief and trap findings (``/api/model-check``): snapshot alignment,
  weighting vs spacing, placeholder bounds, an overnight-cost asset with an infinite lifetime, structure.
* :mod:`.diagnostics` - why a solve came back infeasible / left load unserved: copper-plate capacity adequacy,
  suspect coefficients, starved ``e_sum`` budgets. Plugged into the core as a ``diagnose`` hook
  (:mod:`.hooks`); the core only words the error around the returned headline and text.
"""
