"""Constraints module: user-authored custom constraints, the constraint DSL and structured specs.

PyPSA's ``GlobalConstraint`` covers a CO2 cap, a carrier energy limit and nominal-capacity limits. Everything
the user writes beyond that - intensity caps, generation / capacity shares, ratios, the free-text DSL and the
JSON ``constraintSpecs`` from the Constraints tab, each apportioned to the optimised window in a rolling
horizon - is a *declared* ``extra_functionality`` contribution added to the linopy model (a ``constraints``
hook), reported with its dual in ``appliedConstraints``.

Kinds PyPSA's ``GlobalConstraint`` expresses exactly (carrier energy limit, load-shed cap, carrier capacity limit,
a bare DSL ``emissions`` cap) are written as native rows by :mod:`.native_routing` and their dual is
``global_constraints.mu``; every other kind, and every run where the native row would differ (rolling, pathway,
stochastic), keeps its linopy constraint. See docs/backend.md section 8.5.
"""
