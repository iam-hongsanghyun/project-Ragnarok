"""Constraints module: user-authored custom constraints, the constraint DSL and structured specs.

PyPSA's ``GlobalConstraint`` covers a CO2 cap, a carrier energy limit and nominal-capacity limits. Everything
the user writes beyond that - intensity caps, generation / capacity shares, ratios, the free-text DSL and the
JSON ``constraintSpecs`` from the Constraints tab, each apportioned to the optimised window in a rolling
horizon - is a *declared* ``extra_functionality`` contribution added to the linopy model (a ``constraints``
hook), reported with its dual in ``appliedConstraints``.

Not routed to native ``GlobalConstraint`` rows: the kinds PyPSA could express (``tech_capacity_expansion_limit``,
per-bus-carrier nominal limits, ``operational_limit``, ``primary_energy``) keep their linopy constraint here,
because the reported dual would move from the constraint name to ``global_constraints.mu`` and the window
apportioning would change. That is a tracked follow-up (docs/TODO.md), not part of the mechanical extraction.
"""
