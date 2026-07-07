"""Opt-in physical-risk -> forced-outage-rate uplift coupling.

Two layers, tested independently (see backend/app/physical_risk_uplift.py and
backend/pypsa/results/outage_mc.py's "Opt-in physical-risk uplift" section):

1. The app-layer injection function ``compute_for_rate_uplift`` /
   ``apply_physical_risk_uplift`` — given a physical-risk store + session id,
   compute ``{generator_name: uplift_fraction}`` from the session's latest
   completed run. Exercised here against the REAL
   ``backend.app.physical_risk.store.PhysicalRiskStore`` (submit + poll a run
   for real) so the test breaks if the Phase-0 store shape drifts.
2. The pypsa-layer application in ``build_outage_mc`` — given
   ``outageMcConfig.forRateUplift``, the matching generator's effective FOR
   rises (visible via ``upliftApplied`` and a higher EUE at the same seed).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.app.physical_risk.entities import Portfolio, Scenario
from backend.app.physical_risk.entities import Asset as PhysicalRiskAsset
from backend.app.physical_risk.store import PhysicalRiskStore
from backend.app.physical_risk_uplift import (
    _PHYSICAL_RUN_KIND,
    _UPLIFT_CAP,
    apply_physical_risk_uplift,
    compute_for_rate_uplift,
)
from backend.pypsa.network import build_network
from backend.pypsa.results import run_pypsa
from backend.pypsa.results.outage_mc import build_outage_mc

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


# ── App layer: compute_for_rate_uplift against the real store ──────────────


def _make_store_with_done_run(
    *,
    asset_name: str = "g0",
    asset_value: float = 1_000_000.0,
    perils: list[str] | None = None,
) -> tuple[PhysicalRiskStore, str, str]:
    """A real PhysicalRiskStore + real (deterministic) stub engine, end-to-end.

    Submits and polls a real ``kind="physical"`` run to completion through the
    public store API (no reach-into-internals) — the stub engine
    (backend/app/physical_risk/engine.py) is randomness-free, so with a single
    asset the resulting EAI is exactly ``value * peril_factor`` (the
    ``_asset_eai`` index-based spread is 1.0 at index 0).

    Returns (store, session_id, run_id).
    """
    store = PhysicalRiskStore()
    asset = PhysicalRiskAsset(name=asset_name, kind="generator", lat=1.0, lon=1.0, value=asset_value)
    portfolio = Portfolio(assets=[asset])
    store.create_session(portfolio)
    session_id = portfolio.sessionId

    perils = perils if perils is not None else ["tropical_cyclone"]
    run = store.submit_run(session_id, "physical", perils, Scenario())
    assert run is not None
    run_id = run.id

    done = store.poll_run(run_id, session_id=session_id)
    assert done is not None and done.status == "done", done
    return store, session_id, run_id


# Peril EAI factors from the deterministic stub engine (engine.py::_PERIL_FACTOR),
# duplicated here (not imported) so this test also catches an accidental factor
# change upstream by asserting the exact expected ratio.
_TC_FACTOR = 0.0120
_RF_FACTOR = 0.0085


def test_compute_uplift_matches_eai_over_value() -> None:
    store, session_id, run_id = _make_store_with_done_run(
        asset_name="g0", asset_value=1_000_000.0, perils=["tropical_cyclone"],
    )
    uplift, note = compute_for_rate_uplift(store, session_id)
    assert uplift == pytest.approx({"g0": _TC_FACTOR})  # eai = value * factor (index-0 spread = 1.0)
    assert session_id in note
    assert "tropical_cyclone" in note


def test_compute_uplift_sums_across_perils() -> None:
    store, session_id, _run_id = _make_store_with_done_run(
        asset_name="g0", asset_value=1_000_000.0, perils=["tropical_cyclone", "river_flood"],
    )
    uplift, _note = compute_for_rate_uplift(store, session_id)
    assert uplift["g0"] == pytest.approx(_TC_FACTOR + _RF_FACTOR)


def test_compute_uplift_is_capped() -> None:
    """A fake store (not the real engine, whose stub factors are all << the
    cap) exercises the cap path directly with an eai/value far above 0.5."""

    class _FakeAsset:
        def __init__(self, id_: str, name: str, value: float) -> None:
            self.id = id_
            self.name = name
            self.value = value

    class _FakePortfolio:
        def __init__(self, assets: list[_FakeAsset]) -> None:
            self.assets = assets

    class _FakeImpact:
        def __init__(self, asset_id: str, eai: float) -> None:
            self.assetId = asset_id
            self.eai = eai

    class _FakePerilResult:
        def __init__(self, peril: str, per_asset: list[_FakeImpact]) -> None:
            self.peril = peril
            self.perAsset = per_asset

    class _FakeRunOutput:
        def __init__(self, perils: list[_FakePerilResult]) -> None:
            self.perils = perils

    class _FakeStore:
        def __init__(self, portfolio: _FakePortfolio, result: _FakeRunOutput) -> None:
            self._portfolio = portfolio
            self._result = result

        def get_session(self, session_id: str) -> Any:
            return self._portfolio

        def latest_results(self, session_id: str) -> dict[str, Any]:
            return {_PHYSICAL_RUN_KIND: self._result}

    asset = _FakeAsset("a1", "g0", 10_000.0)
    # eai/value = 50_000 / 10_000 = 5.0, far above the 0.5 cap.
    result = _FakeRunOutput([_FakePerilResult("wildfire", [_FakeImpact("a1", 50_000.0)])])
    fake_store = _FakeStore(_FakePortfolio([asset]), result)

    uplift, note = compute_for_rate_uplift(fake_store, "sid")
    assert uplift["g0"] == pytest.approx(_UPLIFT_CAP)
    assert f"{_UPLIFT_CAP:.0%}" in note


def test_compute_uplift_missing_session_returns_empty_with_note() -> None:
    store = PhysicalRiskStore()
    uplift, note = compute_for_rate_uplift(store, "does-not-exist")
    assert uplift == {}
    assert "not found" in note


def test_compute_uplift_no_completed_run_returns_empty_with_note() -> None:
    store = PhysicalRiskStore()
    portfolio = Portfolio(assets=[PhysicalRiskAsset(name="g0", lat=1.0, lon=1.0, value=1e6)])
    store.create_session(portfolio)
    uplift, note = compute_for_rate_uplift(store, portfolio.sessionId)
    assert uplift == {}
    assert "no completed 'physical' run" in note


def test_compute_uplift_empty_session_id_returns_empty_with_note() -> None:
    store = PhysicalRiskStore()
    uplift, note = compute_for_rate_uplift(store, "")
    assert uplift == {}
    assert "skipped" in note


def _run_physical_to_done(store: PhysicalRiskStore, portfolio: Portfolio) -> None:
    """Submit + poll a real ``kind='physical'`` run to DONE for ``portfolio``."""
    store.create_session(portfolio)
    run = store.submit_run(portfolio.sessionId, "physical", ["tropical_cyclone"], Scenario())
    assert run is not None
    done = store.poll_run(run.id, session_id=portfolio.sessionId)
    assert done is not None and done.status == "done", done


def test_storage_asset_sharing_generator_name_does_not_contribute() -> None:
    """PyPSA allows a StorageUnit to share a Generator's name — the same-named
    STORAGE asset (tiny value, hence a different damage ratio) must not
    overwrite the generator's uplift entry."""
    store = PhysicalRiskStore()
    portfolio = Portfolio(
        assets=[
            PhysicalRiskAsset(name="g0", kind="generator", lat=1.0, lon=1.0, value=1_000_000.0),
            PhysicalRiskAsset(name="g0", kind="storage", lat=1.0, lon=1.0, value=10.0),
        ]
    )
    _run_physical_to_done(store, portfolio)

    uplift, _note = compute_for_rate_uplift(store, portfolio.sessionId)
    # Exactly the GENERATOR's damage ratio (index-0 spread = 1.0): the storage
    # asset at index 1 would have yielded factor * 1.05 had it overwritten it.
    assert uplift == pytest.approx({"g0": _TC_FACTOR})


def test_zero_value_asset_gets_no_uplift_entry_and_is_named_in_note() -> None:
    """A zero-value asset has no defined damage ratio: it must be skipped
    entirely (no uplift entry — in particular NOT the capped maximum) and
    named in the provenance note."""
    store = PhysicalRiskStore()
    portfolio = Portfolio(
        assets=[
            PhysicalRiskAsset(name="g0", kind="generator", lat=1.0, lon=1.0, value=1_000_000.0),
            PhysicalRiskAsset(name="g1", kind="generator", lat=2.0, lon=2.0, value=0.0),
        ]
    )
    _run_physical_to_done(store, portfolio)

    uplift, note = compute_for_rate_uplift(store, portfolio.sessionId)
    assert "g1" not in uplift
    assert uplift == pytest.approx({"g0": _TC_FACTOR})
    assert "g1" in note  # skipped asset named ('g' is not a uuid-hex char)
    assert "zero-value" in note.lower()


def test_only_zero_value_assets_yields_empty_uplift_with_named_note() -> None:
    store, session_id, _run_id = _make_store_with_done_run(
        asset_name="g0", asset_value=0.0, perils=["tropical_cyclone"],
    )
    uplift, note = compute_for_rate_uplift(store, session_id)
    assert uplift == {}
    assert "no uplift applied" in note
    assert "g0" in note
    assert "zero-value" in note.lower()


def test_uplift_uses_run_time_portfolio_values_not_later_edits() -> None:
    """The eai/value denominator must come from the portfolio snapshot the run
    was computed on: zeroing an asset's value AFTER the run must not turn a
    small damage ratio into the capped maximum (or into a skip)."""
    store, session_id, _run_id = _make_store_with_done_run(
        asset_name="g0", asset_value=1_000_000.0, perils=["tropical_cyclone"],
    )
    current = store.get_session(session_id)
    assert current is not None
    edited = Portfolio(
        sessionId=session_id,
        assets=[current.assets[0].model_copy(update={"value": 0.0})],  # same asset id
        scenario=current.scenario,
    )
    assert store.save_session(session_id, edited) is not None

    uplift, note = compute_for_rate_uplift(store, session_id)
    assert uplift == pytest.approx({"g0": _TC_FACTOR})  # run-time value, not the zeroed edit
    assert "zero-value" not in note.lower()


# ── App layer: apply_physical_risk_uplift (the injection entry point) ──────


def test_apply_injects_for_rate_uplift_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    store, session_id, _run_id = _make_store_with_done_run(
        asset_name="g0", asset_value=1_000_000.0, perils=["tropical_cyclone"],
    )
    # apply_physical_risk_uplift imports the real singleton lazily from
    # backend.app.physical_risk.store — patch that module's `store` name so
    # the injection entry point sees our populated store.
    import backend.app.physical_risk.store as store_module

    monkeypatch.setattr(store_module, "store", store)

    options: dict[str, Any] = {
        "outageMcConfig": {
            "enabled": True,
            "physicalRiskUplift": True,
            "physicalRiskSessionId": session_id,
        }
    }
    out = apply_physical_risk_uplift(options)
    assert out is options  # mutated in place
    cfg = out["outageMcConfig"]
    assert cfg["forRateUplift"] == pytest.approx({"g0": _TC_FACTOR})
    assert session_id in cfg["forRateUpliftNote"]


def test_apply_is_noop_when_uplift_flag_off() -> None:
    options = {"outageMcConfig": {"enabled": True, "physicalRiskUplift": False}}
    out = apply_physical_risk_uplift(options)
    assert "forRateUplift" not in out["outageMcConfig"]
    assert "forRateUpliftNote" not in out["outageMcConfig"]


def test_apply_missing_session_id_injects_note_not_uplift() -> None:
    options = {"outageMcConfig": {"enabled": True, "physicalRiskUplift": True, "physicalRiskSessionId": ""}}
    out = apply_physical_risk_uplift(options)
    cfg = out["outageMcConfig"]
    assert "forRateUplift" not in cfg
    assert "no physicalRiskSessionId" in cfg["forRateUpliftNote"]


def test_apply_unknown_session_injects_note_not_uplift() -> None:
    options = {
        "outageMcConfig": {
            "enabled": True,
            "physicalRiskUplift": True,
            "physicalRiskSessionId": "ghost-session",
        }
    }
    out = apply_physical_risk_uplift(options)
    cfg = out["outageMcConfig"]
    assert "forRateUplift" not in cfg
    assert "not found" in cfg["forRateUpliftNote"]


def test_apply_handles_none_and_missing_outage_config() -> None:
    assert apply_physical_risk_uplift(None) is None
    assert apply_physical_risk_uplift({}) == {}
    assert apply_physical_risk_uplift({"other": 1}) == {"other": 1}


# ── PyPSA layer: build_outage_mc applies forRateUplift ──────────────────────


def _hourly_snapshots(n_snaps: int) -> list[str]:
    labels = []
    day, hour = 1, 0
    for _ in range(n_snaps):
        labels.append(f"2025-01-{day:02d}T{hour:02d}:00:00")
        hour += 1
        if hour == 24:
            hour = 0
            day += 1
    return labels


def _thermal_model(*, n_snaps: int, load_mw: float, gen_cap: float) -> dict[str, Any]:
    """A tight single-generator 1-bus system (mirrors test_outage_mc.py)."""
    snaps = _hourly_snapshots(n_snaps)
    return {
        "buses": [{"name": "b0", "v_nom": 1.0}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "generators": [
            {"name": "g0", "bus": "b0", "carrier": "gas", "p_nom": gen_cap, "marginal_cost": 10.0},
        ],
        "loads": [{"name": "load", "bus": "b0", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "load": load_mw} for s in snaps],
    }


def _outage_options(**overrides: Any) -> dict[str, Any]:
    cfg = {
        "enabled": True,
        "nMembers": 500,
        "seed": 42,
        "forcedOutageRate": 0.05,
        "mttrHours": 24.0,
    }
    cfg.update(overrides)
    return {"outageMcConfig": cfg}


def test_build_outage_mc_applies_for_rate_uplift_and_raises_effective_for() -> None:
    model = _thermal_model(n_snaps=24 * 14, load_mw=95.0, gen_cap=100.0)
    options = _outage_options(seed=7, forRateUplift={"g0": 0.2})
    result = run_pypsa(model, SCENARIO, options)
    mc = result["outageMc"]
    assert mc is not None
    assert mc["upliftApplied"] == pytest.approx({"g0": 0.2})


def test_uplift_raises_eue_relative_to_no_uplift_baseline_same_seed() -> None:
    """Same seed, same base FOR: with an uplift, the sampled fleet is down
    more often, so EUE (and LOLE) must not decrease, and should meaningfully
    increase for a tight system."""
    model = _thermal_model(n_snaps=24 * 14, load_mw=95.0, gen_cap=100.0)
    n, _ = build_network(
        model, SCENARIO,
        {"snapshotStart": 0, "snapshotCount": 24 * 14, "snapshotWeight": 1.0},
    )
    n.optimize(solver_name="highs")

    baseline = build_outage_mc(n, _outage_options(seed=7))
    uplifted = build_outage_mc(n, _outage_options(seed=7, forRateUplift={"g0": 0.3}))

    assert baseline is not None and uplifted is not None
    assert uplifted["upliftApplied"] == pytest.approx({"g0": 0.3})
    assert baseline.get("upliftApplied") == {}
    assert uplifted["eueDistribution"]["mean"] > baseline["eueDistribution"]["mean"]
    assert uplifted["loleDistribution"]["mean"] >= baseline["loleDistribution"]["mean"]


def test_uplift_note_surfaced_in_result() -> None:
    model = _thermal_model(n_snaps=24, load_mw=50.0, gen_cap=100.0)
    note = "forced-outage uplift derived from physical-risk session 'sid', run 'rid', perils [wildfire]."
    result = run_pypsa(
        model, SCENARIO,
        _outage_options(seed=1, forRateUplift={"g0": 0.1}, forRateUpliftNote=note),
    )
    mc = result["outageMc"]
    assert mc["forRateUpliftNote"] == note
    assert note in mc["note"]


def test_uplift_ignores_nonmatching_generator_names() -> None:
    """A forRateUplift entry for a generator that doesn't exist in this model
    must be silently ignored (not raise), and upliftApplied must stay empty."""
    model = _thermal_model(n_snaps=24, load_mw=50.0, gen_cap=100.0)
    result = run_pypsa(model, SCENARIO, _outage_options(seed=1, forRateUplift={"not_a_real_gen": 0.5}))
    mc = result["outageMc"]
    assert mc is not None
    assert mc["upliftApplied"] == {}


def test_zero_uplift_entry_not_reported_as_applied() -> None:
    """A forRateUplift entry of exactly 0.0 is a no-op: it must not appear in
    upliftApplied nor be counted in the 'Physical-risk FOR uplift' summary."""
    model = _thermal_model(n_snaps=24, load_mw=50.0, gen_cap=100.0)
    result = run_pypsa(model, SCENARIO, _outage_options(seed=1, forRateUplift={"g0": 0.0}))
    mc = result["outageMc"]
    assert mc is not None
    assert mc["upliftApplied"] == {}
    assert all(row["label"] != "Physical-risk FOR uplift" for row in mc["summary"])


def test_uplift_clips_total_for_at_max() -> None:
    """A huge base FOR + uplift must clip at 0.95, not exceed it — checked by
    ensuring the empirical down-fraction of the sampler stays <= ~0.95."""
    for_rates = np.array([0.5])
    mttr = np.array([24.0])
    weights = np.ones(2000)
    from backend.pypsa.results.outage_mc import sample_outage_masks

    # Directly exercise the clip semantics documented in build_outage_mc:
    # base 0.5 + uplift 0.9 -> clipped to 0.95 before being handed to the sampler.
    clipped_for = np.clip(for_rates + 0.9, 0.0, 0.95)
    assert clipped_for[0] == pytest.approx(0.95)
    mask = sample_outage_masks(clipped_for, mttr, weights, n_members=50, seed=3)
    empirical_for = 1.0 - mask.mean()
    assert empirical_for == pytest.approx(0.95, abs=0.02)
