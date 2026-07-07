"""Opt-in coupling: Physical Risk portfolio damage -> forced-outage-rate uplift.

Bridges two features that otherwise don't know about each other:

* the native physical-risk capability (:mod:`backend.app.physical_risk`) —
  portfolio sessions + completed damage runs. A run of kind ``"physical"``
  carries a :class:`~backend.app.physical_risk.entities.PhysicalRunOutput`
  with ``perils[].perAsset[].eai`` (expected annual impact, keyed by asset
  id, per peril);
* the thermal forced-outage Monte Carlo (:mod:`backend.pypsa.results.outage_mc`)
  — samples generator up/down states from a forced-outage rate (FOR).

This module is the ONLY place that reaches across both. It lives in the app
layer (not ``backend/pypsa/``) because ``backend/pypsa`` must stay pure — no
imports from ``backend/app`` — so the PyPSA-side outage sampler only ever sees
a plain ``forRateUplift: {generator_name: float}`` dict inside
``options["outageMcConfig"]``, built here and injected before the solve.

Algorithm — damage-ratio-as-availability-loss:
    For each GENERATOR-kind physical-risk asset (``kind == "generator"``;
    storage assets are excluded — PyPSA allows a StorageUnit to share a
    Generator's name, and a same-named storage asset must never overwrite the
    generator's uplift) whose name matches a PyPSA generator, take the sum of
    expected annual impact (EAI) across the latest physical run's perils and
    normalise by the asset's value at risk. Both EAI and value come from the
    SAME portfolio snapshot the run was computed on (the store freezes it at
    submission), so editing an asset after the run cannot skew the ratio.
    Assets whose snapshot value is <= 0 are skipped entirely (no uplift
    entry) and named in the note — a damage ratio is undefined without a
    value at risk. The ratio is reinterpreted as an ADDITIONAL
    forced-unavailability fraction on top of the generator's base FOR (the
    actual application/clip happens in ``outage_mc.py``; this module only
    computes and caps the per-asset uplift fraction):
        $$ f_a = \\min\\!\\left(f_{\\text{cap}},\\ \\frac{\\sum_p \\text{eai}_{a,p}}{\\text{value}_a}\\right) \\quad (\\text{value}_a > 0) $$
        ASCII: f[a] = min(f_cap, sum_p(eai[a, p]) / value[a]), only for value[a] > 0

    Symbols: eai_{a,p} = expected annual impact of peril p on asset a, in the
    run's currency (same currency as ``value``); value_a = asset value at
    risk (currency, from the run-time portfolio snapshot); f_cap = 0.5
    (dimensionless, [0,1]) — a conservative ceiling so one hazard-heavy asset
    cannot alone force FOR to 1; f_a = per-asset uplift fraction,
    dimensionless in [0, f_cap].

    This is a deliberately simple, transparent proxy (not a CLIMADA
    engineering-fragility curve): "a year of expected damage equal to X% of
    the asset's value" is read as "X percentage points of extra forced
    outage". It is a reasonable order-of-magnitude bridge for Phase 0 and is
    always presented with its provenance (session id, run id, perils) so the
    user can judge it, never silently baked in.

Design notes:
    * Pure function ``compute_for_rate_uplift`` takes the store + ids and
      returns a plain dict — no FastAPI/pydantic objects leak into it beyond
      what the store already returns, so it is unit-testable with a fake
      store.
    * Uses the store's PUBLIC accessors only: ``latest_results(session_id)``
      (``{run_kind: result}``, latest DONE run per kind) and — when the store
      provides it — ``latest_run_portfolio(session_id, kind)`` for the frozen
      run-time portfolio snapshot (stores/fakes without that accessor fall
      back to the current session portfolio). It does not reach into any
      private store attribute. This module only knows about the ``"physical"``
      run kind's ``PhysicalRunOutput`` shape (``perils[].perAsset[].eai``);
      other run kinds are ignored.
    * Never raises and never blocks a solve: any lookup failure (unknown
      session, no completed physical run) degrades to "no uplift injected"
      plus an explanatory note, and a zero-value asset degrades to "no uplift
      for that asset" with the asset named in the note.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("pypsa_gui.physical_risk_uplift")

# The physical-risk run kind this coupling reads (see backend/app/physical_risk
# /entities.py::RUN_KINDS) — damage/impact results, not uncertainty/cost-benefit/etc.
_PHYSICAL_RUN_KIND = "physical"

# Ceiling on the per-asset damage-ratio-derived uplift fraction (dimensionless,
# [0, 1]) — keeps one hazard-heavy asset from single-handedly pushing FOR to 1.
# The final clip to a total (base + uplift) FOR of 0.95 happens in outage_mc.py.
_UPLIFT_CAP = 0.5


def compute_for_rate_uplift(
    store: Any,
    session_id: str,
    *,
    asset_names: dict[str, str] | None = None,
) -> tuple[dict[str, float], str]:
    """Compute per-generator FOR uplift fractions from a physical-risk run.

    Args:
        store: a :class:`backend.app.physical_risk.store.PhysicalRiskStore`
            (or a fake with the same ``get_session`` + ``latest_results``
            shape, for tests; the frozen-portfolio accessor
            ``latest_run_portfolio`` is used when present, see below).
        session_id: physical-risk session id to look up.
        asset_names: optional ``{asset_id: asset_name}`` override (tests use
            this to avoid depending on ``store``'s asset shape); when omitted
            it's read from the run-time portfolio's generator-kind assets.

    Returns:
        ``(uplift_by_name, note)`` — ``uplift_by_name`` maps a PyPSA generator
        name (the physical-risk asset's ``name``, which is seeded 1:1 from the
        model) to its uplift fraction in ``[0, _UPLIFT_CAP]``. Only
        generator-kind assets contribute (a storage asset sharing a
        generator's name is ignored), asset values are taken from the SAME
        portfolio snapshot the run was computed on when the store exposes it
        (``latest_run_portfolio``; otherwise the current session portfolio),
        and assets whose value is <= 0 are skipped entirely and named in the
        note. Empty when nothing could be computed. ``note`` is always a
        short, human-readable provenance string — either citing the
        session/run/perils used (plus any skipped assets), or explaining why
        no uplift was applied.
    """
    if not session_id:
        return {}, "physical-risk uplift requested with no session id — skipped."

    portfolio = store.get_session(session_id)
    if portfolio is None:
        return {}, f"physical-risk session {session_id!r} not found — no uplift applied."

    latest = store.latest_results(session_id) or {}
    result = latest.get(_PHYSICAL_RUN_KIND)
    if result is None:
        return {}, (
            f"physical-risk session {session_id!r} has no completed 'physical' run — "
            "no uplift applied."
        )

    # Asset metadata comes from the SAME portfolio snapshot the run was computed
    # on when the store can provide it (submit_run freezes the portfolio into
    # the run state) — the EAI numerator is run-time, so a value edited AFTER
    # the run must not skew eai/value. Stores/fakes without that accessor fall
    # back to the current session portfolio.
    run_portfolio = None
    frozen_getter = getattr(store, "latest_run_portfolio", None)
    if callable(frozen_getter):
        run_portfolio = frozen_getter(session_id, _PHYSICAL_RUN_KIND)
    source_portfolio = run_portfolio if run_portfolio is not None else portfolio

    # Only generator-kind assets may drive a generator's FOR — PyPSA allows a
    # StorageUnit to share a Generator's name, and a same-named storage asset
    # must not overwrite the generator's uplift. Assets without a ``kind``
    # attribute default to 'generator' (the Asset entity's default).
    generator_assets = [
        asset
        for asset in getattr(source_portfolio, "assets", [])
        if str(getattr(asset, "kind", "generator")) == "generator"
    ]
    generator_ids = {asset.id for asset in generator_assets}
    if asset_names is None:
        asset_names = {asset.id: asset.name for asset in generator_assets}
    asset_values = {asset.id: float(asset.value) for asset in generator_assets}

    perils = list(getattr(result, "perils", []) or [])
    if not perils:
        return {}, f"physical-risk session {session_id!r}'s run has no peril results — no uplift applied."

    # sum EAI across perils, per generator-kind asset id.
    eai_by_asset: dict[str, float] = {}
    peril_labels: list[str] = []
    for peril_result in perils:
        peril_labels.append(str(getattr(peril_result, "peril", "")))
        for impact in getattr(peril_result, "perAsset", []) or []:
            if impact.assetId not in generator_ids:
                continue
            eai_by_asset[impact.assetId] = eai_by_asset.get(impact.assetId, 0.0) + float(impact.eai)

    uplift_by_name: dict[str, float] = {}
    skipped_zero_value: list[str] = []
    for asset_id, eai in eai_by_asset.items():
        name = asset_names.get(asset_id)
        if not name:
            continue
        value = asset_values.get(asset_id, 0.0)
        if value <= 0.0:
            # A zero-value asset has no defined damage ratio — deriving an
            # uplift from it would be arbitrary. Skip it, but say so.
            skipped_zero_value.append(name)
            continue
        fraction = eai / value
        uplift_by_name[name] = min(_UPLIFT_CAP, max(0.0, fraction))

    skipped_note = (
        f" Skipped zero-value asset(s) [{', '.join(sorted(skipped_zero_value))}] — "
        "no damage ratio derivable without a value at risk."
        if skipped_zero_value
        else ""
    )

    if not uplift_by_name:
        return {}, (
            f"physical-risk session {session_id!r}'s run produced no per-asset impact "
            f"matching a named generator — no uplift applied.{skipped_note}"
        )

    note = (
        f"forced-outage uplift derived from physical-risk session {session_id!r}, "
        f"perils [{', '.join(peril_labels)}] "
        f"(damage-ratio capped at {_UPLIFT_CAP:.0%}).{skipped_note}"
    )
    return uplift_by_name, note


def apply_physical_risk_uplift(options: dict[str, Any] | None) -> dict[str, Any] | None:
    """Injection entry point — called once, before a solve is dispatched.

    Mutates and returns ``options`` in place (safe no-op when the feature is
    off or ``options`` is falsy): if
    ``options["outageMcConfig"]["physicalRiskUplift"]`` is truthy and
    ``physicalRiskSessionId`` is a non-empty string, looks up that session's
    latest completed physical-risk run in the process-local store and injects
    ``options["outageMcConfig"]["forRateUplift"]`` (``{generator_name:
    fraction}``) plus a provenance ``forRateUpliftNote`` string. Never raises
    and never blocks the solve — any failure just leaves ``forRateUplift``
    absent and explains why via the note.

    Args:
        options: the run's ``options`` dict (as assembled by the solve submit
            path), or ``None``.

    Returns:
        ``options`` (same object, mutated), or ``None`` if it was ``None``.
    """
    if not options:
        return options
    cfg = options.get("outageMcConfig")
    if not isinstance(cfg, dict):
        return options
    if not bool(cfg.get("physicalRiskUplift")):
        return options
    session_id = cfg.get("physicalRiskSessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        cfg["forRateUpliftNote"] = (
            "physicalRiskUplift enabled but no physicalRiskSessionId was set — skipped."
        )
        return options

    # Imported lazily so a circular/heavy import at module load time never
    # affects normal (non-uplift) solves, and so this module can be imported
    # for unit tests without pulling in the physical-risk package at all.
    from .physical_risk.store import store as physical_risk_store

    uplift_by_name, note = compute_for_rate_uplift(physical_risk_store, session_id.strip())
    if uplift_by_name:
        cfg["forRateUplift"] = uplift_by_name
    cfg["forRateUpliftNote"] = note
    _log.info(
        "physical_risk_uplift: session=%s matched=%d note=%s",
        session_id, len(uplift_by_name), note,
    )
    return options
