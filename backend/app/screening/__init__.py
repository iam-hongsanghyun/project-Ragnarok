"""Screening — statistical pre-screen of sites and regions on historical series.

A module of its own (formerly the Screening step of Siting): :mod:`.datasets`
(parse, validate, store per session: site, region and reference datasets),
:mod:`.correlation` (resampling, correlation, region aggregation, within /
between-region structure, complementarity, portfolio optimiser, clustering -
pure functions) and :mod:`.promote` (selected sites -> generators with
``p_max_pu``). HTTP surface ``/api/screening/*`` (``app/routers/screening.py``).
Promotion reuses the alignment maths of :mod:`backend.app.siting.core`.
"""
