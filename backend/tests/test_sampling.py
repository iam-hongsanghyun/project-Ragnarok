"""Sampled snapshot blocks ("test run") — index builder, weighting, parity.

A sampled run solves N disjoint blocks of B snapshots out of a window of W
rows, with objective/generators weightings scaled to ``w = W / M`` (M =
modelled snapshots) so totals represent the full window:

    energy = sum_t p_t * w   [MWh]  with  sum_t(w) == W

The non-sampling path must stay bit-identical to the old behaviour
(weight == stride), and full-window MWh constraint budgets must apply
unapportioned (window_fraction == 1).
"""
from __future__ import annotations

from typing import Any

import pytest

from backend.pypsa.network import build_network
from backend.pypsa.sampling import SamplingConfig, parse_sampling_config, sample_block_indices

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}


def _cfg(mode: str = "count", block_size: int = 6, block_count: int = 2, gap: int = 0) -> SamplingConfig:
    return SamplingConfig(enabled=True, mode=mode, block_size=block_size, block_count=block_count, gap_snapshots=gap)


def _model(n_snaps: int = 48, load_mw: float = 100.0) -> dict[str, list[dict[str, Any]]]:
    """1 bus, flat load; cheap gas + expensive backup (both 200 MW)."""
    snaps = [f"2030-01-{1 + h // 24:02d}T{h % 24:02d}:00:00" for h in range(n_snaps)]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "backup"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": load_mw}],
        "loads-p_set": [{"snapshot": s, "L": load_mw} for s in snaps],
        "generators": [
            {"name": "G_gas", "bus": "b", "carrier": "gas", "p_nom": 200.0, "marginal_cost": 10.0},
            {"name": "G_backup", "bus": "b", "carrier": "backup", "p_nom": 200.0, "marginal_cost": 100.0},
        ],
    }


# ── Index builder ──────────────────────────────────────────────────────────────


def test_count_mode_exact_partition() -> None:
    """W = N*B: blocks tile the window end to end."""
    idx, blocks = sample_block_indices(0, 12, _cfg(block_size=6, block_count=2))
    assert blocks == 2
    assert idx == list(range(0, 6)) + list(range(6, 12))


def test_count_mode_equally_spaced() -> None:
    """First block at window start, last block ending at window end."""
    idx, blocks = sample_block_indices(0, 100, _cfg(block_size=10, block_count=3))
    assert blocks == 3
    assert idx[:10] == list(range(0, 10))
    assert idx[-10:] == list(range(90, 100))
    assert len(idx) == 30
    assert idx == sorted(set(idx))  # disjoint + chronological


def test_count_mode_clamps_block_count() -> None:
    """N*B > W clamps N so blocks stay disjoint."""
    idx, blocks = sample_block_indices(0, 20, _cfg(block_size=8, block_count=5))
    assert blocks == 2  # 20 // 8
    assert len(idx) == 16
    assert idx == sorted(set(idx))


def test_block_larger_than_window_degenerates_to_full_window() -> None:
    idx, blocks = sample_block_indices(0, 10, _cfg(block_size=50, block_count=3))
    assert blocks == 1
    assert idx == list(range(10))


def test_gap_mode_period_and_truncation() -> None:
    """Block 4, gap 6 → period 10; trailing block truncated at the window end."""
    idx, blocks = sample_block_indices(0, 25, _cfg(mode="gap", block_size=4, gap=6))
    assert blocks == 3
    assert idx == [0, 1, 2, 3, 10, 11, 12, 13, 20, 21, 22, 23]


def test_stride_applies_inside_blocks_only() -> None:
    idx, blocks = sample_block_indices(0, 24, _cfg(block_size=6, block_count=2), step=3)
    assert blocks == 2
    assert idx == [0, 3, 18, 21]


def test_rounding_overlap_guard() -> None:
    """Adversarial small window: blocks never overlap, indices unique."""
    idx, blocks = sample_block_indices(0, 10, _cfg(block_size=3, block_count=3))
    assert blocks == 3
    assert idx == sorted(set(idx))
    assert len(idx) == 9


def test_window_offset_respected() -> None:
    idx, _ = sample_block_indices(5, 17, _cfg(block_size=6, block_count=2))
    assert min(idx) >= 5
    assert max(idx) < 17


def test_parse_defaults_and_clamps() -> None:
    cfg = parse_sampling_config({"enabled": True, "mode": "bogus", "blockSize": -3, "blockCount": 0, "gapSnapshots": -1})
    assert cfg.mode == "count"
    assert cfg.block_size == 1
    assert cfg.block_count == 1
    assert cfg.gap_snapshots == 0
    assert parse_sampling_config(None).enabled is False


# ── Weighting through build_network ────────────────────────────────────────────


def test_sampled_weighting_scales_to_full_window() -> None:
    n, notes = build_network(_model(48), SCENARIO, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2},
    })
    assert len(n.snapshots) == 12
    assert float(n.snapshot_weightings["objective"].iloc[0]) == pytest.approx(4.0)
    assert float(n.snapshot_weightings["generators"].iloc[0]) == pytest.approx(4.0)
    assert float(n.snapshot_weightings["objective"].sum()) == pytest.approx(48.0)
    # SOC integration step stays physical (the stride, not the scale)
    assert float(n.snapshot_weightings["stores"].iloc[0]) == pytest.approx(1.0)
    assert any("Sampled 2 block(s)" in note for note in notes)


def test_non_sampling_path_unchanged() -> None:
    """Sampling disabled: weights identical to the legacy stride behaviour."""
    n, _ = build_network(_model(48), SCENARIO, {"snapshotCount": 48, "snapshotWeight": 4})
    assert len(n.snapshots) == 12
    for col in ("objective", "generators", "stores"):
        assert float(n.snapshot_weightings[col].iloc[0]) == pytest.approx(4.0)


def test_sampling_composes_with_stride() -> None:
    """4 blocks of 8 rows at 2h stride: M = 4*4 = 16 of W = 64 → weight 4."""
    n, _ = build_network(_model(64), SCENARIO, {
        "snapshotCount": 64,
        "snapshotWeight": 2,
        "samplingConfig": {"enabled": True, "mode": "count", "blockSize": 8, "blockCount": 4},
    })
    assert len(n.snapshots) == 16
    assert float(n.snapshot_weightings["objective"].iloc[0]) == pytest.approx(4.0)
    assert float(n.snapshot_weightings["stores"].iloc[0]) == pytest.approx(2.0)


# ── End-to-end parity (analytical: flat load) ──────────────────────────────────


def test_sampled_energy_total_matches_full_window() -> None:
    """Constant 100 MW load: weighted sampled energy == full-window energy."""
    opts_full = {"snapshotCount": 48}
    opts_sampled = {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2},
    }
    n_full, _ = build_network(_model(48), SCENARIO, opts_full)
    n_full.optimize(solver_name="highs")
    full_energy = float((n_full.generators_t.p.sum(axis=1) * n_full.snapshot_weightings["generators"]).sum())

    n_s, _ = build_network(_model(48), SCENARIO, opts_sampled)
    n_s.optimize(solver_name="highs")
    sampled_energy = float((n_s.generators_t.p.sum(axis=1) * n_s.snapshot_weightings["generators"]).sum())

    assert full_energy == pytest.approx(48 * 100.0)
    assert sampled_energy == pytest.approx(full_energy)


def test_run_pypsa_sampled_run_meta_and_guards() -> None:
    from fastapi import HTTPException

    from backend.pypsa.results import run_pypsa

    result = run_pypsa(_model(48), SCENARIO, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2},
    })
    meta = result["runMeta"]
    assert meta["snapshotCount"] == 12
    assert meta["snapshotWeight"] == pytest.approx(4.0)
    assert meta["modeledHours"] == pytest.approx(48.0)
    assert meta["sampling"]["blockCount"] == 2
    assert meta["sampling"]["sampledSnapshots"] == 12
    assert meta["sampling"]["representedSnapshots"] == 48
    assert meta["sampling"]["scale"] == pytest.approx(4.0)

    with pytest.raises(HTTPException):
        run_pypsa(_model(48), SCENARIO, {
            "samplingConfig": {"enabled": True},
            "rollingConfig": {"enabled": True, "horizonSnapshots": 12, "overlapSnapshots": 0},
        })
    with pytest.raises(HTTPException):
        run_pypsa(_model(48), SCENARIO, {
            "samplingConfig": {"enabled": True},
            "pathwayConfig": {"enabled": True, "periods": [{"period": 2030}]},
        })


# ── Constraint budgets under sampling ──────────────────────────────────────────


def test_carrier_max_gen_budget_applies_unapportioned() -> None:
    """A full-window MWh budget binds at the FULL budget in a sampled run
    (window_fraction == 1 because weights sum to the represented hours)."""
    scenario = dict(SCENARIO)
    # Full window would want 48*100 = 4800 MWh of cheap gas; cap it at 2400.
    scenario["constraints"] = [
        {"enabled": True, "metric": "carrier_max_gen", "carrier": "gas", "value": 2400.0, "label": "gas cap"},
    ]
    from backend.pypsa.results import run_pypsa

    result = run_pypsa(_model(48), scenario, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2},
    })
    by_name = {ge["name"]: ge["value"] for ge in result["generatorEnergy"]}
    assert by_name["G_gas"] == pytest.approx(2400.0, rel=1e-4)
    assert by_name["G_backup"] == pytest.approx(2400.0, rel=1e-4)


def test_e_sum_caps_scale_by_represented_hours() -> None:
    """An annual e_sum_max budget is scaled by represented/8760, not by
    modelled/8760, in a sampled run."""
    model = _model(48)
    model["generators"][0]["e_sum_max"] = 8760.0  # annual MWh budget
    n, _ = build_network(model, SCENARIO, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "count", "blockSize": 6, "blockCount": 2},
    })
    # period factor = represented(48)/8760 — same as a contiguous 48 h run
    assert float(n.generators.at["G_gas", "e_sum_max"]) == pytest.approx(8760.0 * 48 / 8760.0)


# ── Averaged-profile mode ──────────────────────────────────────────────────────


def _varying_model(n_snaps: int = 48, period: int = 12) -> dict[str, Any]:
    """Load alternates per period: period k has constant load 100 + 10*k MW."""
    model = _model(n_snaps)
    rows = model["loads-p_set"]
    for i, row in enumerate(rows):
        row["L"] = 100.0 + 10.0 * (i // period)
    return model


def test_average_window_frames_positional_mean() -> None:
    """4 periods of 12 rows with loads 100/110/120/130 → averaged 115 MW."""
    from backend.pypsa.results import run_pypsa

    result = run_pypsa(_varying_model(48, period=12), SCENARIO, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "average", "blockSize": 12},
    })
    meta = result["runMeta"]
    assert meta["snapshotCount"] == 12
    assert meta["snapshotWeight"] == pytest.approx(4.0)
    assert meta["sampling"]["mode"] == "average"
    assert meta["sampling"]["blockCount"] == 4  # periods folded
    assert meta["sampling"]["representedSnapshots"] == 48
    # Generation follows the averaged load: every modelled snapshot serves
    # exactly the positional mean (115 MW), and the weighted total equals the
    # full-window energy exactly (mean preservation).
    by_name = {ge["name"]: ge["value"] for ge in result["generatorEnergy"]}
    total = sum(by_name.values())
    full_total = sum(100.0 + 10.0 * (i // 12) for i in range(48))  # 5520 MWh
    assert total == pytest.approx(full_total)


def test_average_mode_weighting_and_stores() -> None:
    n, notes = build_network(_varying_model(48, period=12), SCENARIO, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "average", "blockSize": 12},
    })
    assert len(n.snapshots) == 12
    assert float(n.snapshot_weightings["objective"].iloc[0]) == pytest.approx(4.0)
    assert float(n.snapshot_weightings["objective"].sum()) == pytest.approx(48.0)
    assert float(n.snapshot_weightings["stores"].iloc[0]) == pytest.approx(1.0)
    # The averaged load really is the positional mean of the four periods.
    assert float(n.loads_t.p_set["L"].iloc[0]) == pytest.approx(115.0)
    assert any("Averaged 4 period(s)" in note for note in notes)


def test_average_mode_composes_with_stride() -> None:
    """B=12 averaged, stride 3 → 4 modelled snapshots, weight 12."""
    n, _ = build_network(_varying_model(48, period=12), SCENARIO, {
        "snapshotCount": 48,
        "snapshotWeight": 3,
        "samplingConfig": {"enabled": True, "mode": "average", "blockSize": 12},
    })
    assert len(n.snapshots) == 4
    assert float(n.snapshot_weightings["objective"].iloc[0]) == pytest.approx(12.0)
    assert float(n.snapshot_weightings["stores"].iloc[0]) == pytest.approx(3.0)


def test_average_mode_guards_and_no_seam_note() -> None:
    from fastapi import HTTPException

    from backend.pypsa.results import run_pypsa

    with pytest.raises(HTTPException):
        run_pypsa(_model(48), SCENARIO, {
            "samplingConfig": {"enabled": True, "mode": "average"},
            "rollingConfig": {"enabled": True, "horizonSnapshots": 12, "overlapSnapshots": 0},
        })
    # Committable + average: the block-seam UC note must NOT appear.
    model = _model(48)
    model["generators"][0]["committable"] = True
    result = run_pypsa(model, SCENARIO, {
        "snapshotCount": 48,
        "samplingConfig": {"enabled": True, "mode": "average", "blockSize": 12},
    })
    assert not any("block boundaries" in note for note in result["narrative"])
