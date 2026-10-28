"""Build plant templates: one plant = a bus, a capacity and a few key fields; every component it needs is derived.

A plant is a *group of ordinary PyPSA components* that share a ``plant`` id (a column on each row) and one row in
the ``RAGNAROK_PLANTS`` registry sheet (type, normalised spec, components). There is no separate engine: the
fragments go through the same fragment merge as the Build conversions and the P2X chain (``fragment_merge``).

Modules:

* :mod:`.technologies`  data file loader (CCGT / OCGT / BESS parameters, fuels, LHV per Nm3), every value with its source
* :mod:`.thermal`       CCGT, OCGT and gas + H2 co-firing (simple generator / fuel network) builders
* :mod:`.catalog`       plant types, their fields and defaults; ``build_plant`` dispatch (generator, BESS, thermal, P2X)
* :mod:`.registry`      plant ids, registry rows, list / edit / delete as change sets (shared buses and carriers are kept)
* :mod:`.results`       results read from a stored run and aggregated by plant id (generation, fuel, H2 share, emissions avoided, starts)

The H2 blend-share constraint is a run option beside the RFNBO one: ``backend/pypsa/network/cofiring.py``.
"""
