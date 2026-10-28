"""Adequacy module: resource-adequacy and reliability Monte Carlo studies on the solved system.

Post-solve studies (``study`` hooks in :mod:`.hooks`) that never re-solve and never raise into the solve (a failure
becomes a run note): the renewable-ensemble adequacy / LOLE read (always attempted), the thermal forced-outage
Monte Carlo, ELCC / capacity credit, the correlated multi-driver stress sampling and the convergence-controlled
outage sampling.
"""
