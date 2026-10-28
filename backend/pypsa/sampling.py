"""Sampled snapshot blocks ("test run") configuration and index builder.

Instead of solving one contiguous snapshot window, a sampled run solves a
reduced set of snapshots with weightings scaled so reported totals (energy,
cost, emissions, constraint budgets) represent the ENTIRE window. Three
parametrizations:

- ``mode='count'``: ``block_count`` blocks of ``block_size`` rows, equally
  spaced across the window (first block at the window start, last ending at
  the window end).
- ``mode='gap'``: a block of ``block_size`` rows, then ``gap_snapshots``
  skipped rows, repeating until the window is exhausted (the trailing block
  may be truncated).
- ``mode='average'``: ONE synthetic block of ``block_size`` rows where each
  position holds the mean of that position across every period of the window
  (an "average week"). Energy totals are exact by construction (when the
  window is a multiple of the block); peaks/variance are smoothed away.

This is the "test-run sampling" MODULE: core never samples. ``apply_test_run_sampling`` writes the sampled
snapshots and their weightings (the run applies it, says so in the run notes, and ``sample_model`` /
``POST /api/transform/sample`` writes the same result visibly into the workbook). Resolution is a separate
visible transform (Forge -> Temporal: resample / downsample); sample a workbook that is already at the
resolution you want.

Algorithm (weightings; kept snapshots :math:`K`, window :math:`[a,b)`, imported weights :math:`w_t` in hours):
    $$ w^{obj}_t = w^{gen}_t = w_t\\,\\frac{\\sum_{s=a}^{b-1} w_s}{\\sum_{k\\in K} w_k},
       \\qquad w^{stores}_t = w_t $$
    ASCII: objective = generators = w[t] * sum(w[window]) / sum(w[kept]); stores = w[t].

    ``objective`` / ``generators`` integrate to the full window (totals, costs, budgets); ``stores`` stays the
    physical time step, so the storage recursion is hours-true inside each block. With default weights this is
    ``W / M`` (window rows over modelled rows). PyPSA charges ``start_up_cost`` / ``shut_down_cost`` per EVENT
    with no weighting, so a sampled run would book only the events of the sampled blocks; they are multiplied by
    the same factor :math:`\\sum_{window} w / \\sum_{K} w` (``samplingConfig.scaleStartUpCosts``, default on).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pypsa

from .utils.coerce import number


@dataclass
class SamplingConfig:
    enabled: bool
    mode: str  # 'count' | 'gap'
    block_size: int
    block_count: int
    gap_snapshots: int
    #: scale ``start_up_cost`` / ``shut_down_cost`` of committable units by the representation factor (see
    #: :func:`apply_test_run_sampling`); the scaled values are written into the sampled workbook and the run notes.
    scale_start_up_costs: bool = True


def parse_sampling_config(raw: dict[str, Any] | None) -> SamplingConfig:
    """Parse the ``samplingConfig`` options key (same style as rolling)."""
    raw = raw or {}
    enabled = bool(raw.get("enabled"))
    mode = str(raw.get("mode") or "count")
    if mode not in ("count", "gap", "average"):
        mode = "count"
    block_size = max(1, int(number(raw.get("blockSize"), 168)))
    block_count = max(1, int(number(raw.get("blockCount"), 4)))
    gap_snapshots = max(0, int(number(raw.get("gapSnapshots"), 672)))
    return SamplingConfig(
        enabled=enabled,
        mode=mode,
        block_size=block_size,
        block_count=block_count,
        gap_snapshots=gap_snapshots,
        scale_start_up_costs=bool(raw.get("scaleStartUpCosts", True)),
    )


def sample_block_indices(
    start: int,
    stop: int,
    cfg: SamplingConfig,
    step: int = 1,
) -> tuple[list[int], int]:
    """Positional indices of the sampled snapshots within ``[start, stop)``.

    Returns ``(indices, actual_block_count)``. Indices ascend (chronological)
    and blocks never overlap. ``step`` is the in-block stride.

    Edge cases: a window smaller than one block degenerates to the full
    window (one block); in count mode the block count is clamped so that
    ``N * B <= W`` (blocks stay disjoint); in gap mode the trailing block is
    truncated at the window end.
    """
    W = stop - start
    if W <= 0:
        return [], 0
    B = min(cfg.block_size, W)
    stride = max(1, step)

    blocks: list[tuple[int, int]] = []  # [s, e) half-open
    if cfg.mode == "gap":
        period = B + max(0, cfg.gap_snapshots)
        s = start
        while s < stop:
            blocks.append((s, min(s + B, stop)))
            s += period
    else:  # 'count'
        N = max(1, min(cfg.block_count, W // B))
        if N == 1:
            blocks = [(start, start + B)]
        else:
            spacing = (W - B) / (N - 1)  # >= B because N * B <= W
            prev_end = start
            for i in range(N):
                s = start + int(round(i * spacing))
                s = max(s, prev_end)  # guard against rounding overlap
                e = min(s + B, stop)
                blocks.append((s, e))
                prev_end = e

    indices: list[int] = []
    for s, e in blocks:
        indices.extend(range(s, e, stride))
    return indices, len(blocks)


def average_window_frames(
    network: pypsa.Network,
    start: int,
    stop: int,
    block_size: int,
) -> int:
    """Fold the window's dynamic time-series into one ``block_size`` period.

    Mutates every populated dynamic frame of every component IN PLACE: rows
    ``[start, start+B)`` become the positional mean across all K periods of
    the window, so the caller can then window the snapshots to that first
    block. Returns K (the number of periods folded).

    Algorithm:
        $$ \\bar{x}_j = \\frac{1}{K_j} \\sum_{k} x_{start + kB + j} $$
        ASCII: avg[j] = mean over periods k of row (start + k*B + j),
        j in [0, B). An unequal trailing period contributes only to its
        present positions (K_j < K there) — totals are exact only when the
        window is a whole number of blocks.

    Runs BEFORE ``set_snapshots`` windowing, while frames still hold the full
    snapshot index (time-series sheets are applied ahead of windowing in
    ``build_network``).
    """
    W = stop - start
    B = min(max(1, block_size), W)
    periods = math.ceil(W / B)
    if periods <= 1:
        return max(1, periods)
    pos = np.arange(W) % B
    for list_name in network.components.keys():
        comp = network.components[list_name]
        dynamic = getattr(comp, "dynamic", None)
        if dynamic is None:
            continue
        for _attr, frame in dynamic.items():
            if frame is None or frame.empty or len(frame.columns) == 0 or len(frame) < stop:
                continue
            window = frame.iloc[start:stop]
            averaged = window.groupby(pos).mean()
            frame.iloc[start:start + B] = averaged.to_numpy()
    return periods


WEIGHTING_COLUMNS = ("objective", "stores", "generators")


def sampled_weightings(
    full_weights: Any, full: Any, windowed: Any, start: int, stop: int,
) -> Any:
    """Weightings of the sampled snapshots (see the module Algorithm): ``objective`` / ``generators`` scaled to the window, ``stores`` as is."""
    import pandas as pd

    positions = full.get_indexer(windowed)
    out = pd.DataFrame(index=windowed, columns=list(full_weights.columns), dtype=float)
    for col in full_weights.columns:
        w = full_weights[col].to_numpy(dtype=float)
        kept = w[positions]
        if col == "stores":
            out[col] = kept
            continue
        window_total = float(w[start:stop].sum())
        kept_total = float(kept.sum())
        out[col] = kept * (window_total / kept_total) if kept_total > 0 else kept
    return out


def apply_test_run_sampling(
    network: pypsa.Network, start: int, stop: int, cfg: SamplingConfig, notes: list[str],
) -> dict[str, Any]:
    """Reduce ``network`` (in place) to sampled blocks of the window ``[start, stop)`` and write their weightings.

    Returns ``{blocks, kept, window, factor, averaged}`` (``factor`` = represented / modelled objective hours).
    """
    full = network.snapshots
    averaged = 0
    if cfg.mode == "average":
        B = min(max(1, cfg.block_size), max(1, stop - start))
        averaged = average_window_frames(network, start, stop, B)
        windowed = full[start:start + B]
        blocks = 1
    else:
        idx, blocks = sample_block_indices(start, stop, cfg, 1)
        windowed = full[idx]
    if len(windowed) == 0:
        windowed = full[:1]
    full_weights = network.snapshot_weightings.copy()
    network.set_snapshots(windowed)
    new = sampled_weightings(full_weights, full, windowed, start, stop)
    for col in WEIGHTING_COLUMNS:
        if col in new.columns:
            network.snapshot_weightings[col] = new[col].to_numpy()
    w_obj = full_weights["objective"].to_numpy(dtype=float)
    obj_full = float(w_obj[start:stop].sum())
    obj_kept = float(w_obj[full.get_indexer(windowed)].sum())
    factor = obj_full / obj_kept if obj_kept > 0 else 1.0
    if cfg.mode == "average":
        notes.append(
            f"Test-run sampling: averaged {averaged} period(s) into one {cfg.block_size}-row profile: {len(windowed)} snapshots "
            f"modelled of {stop - start} window rows (objective/generators weight x{factor:.4g}, stores weight unchanged). "
            "Totals represent the full window; peaks and variability are smoothed by the averaging."
        )
    else:
        notes.append(
            f"Test-run sampling: {blocks} block(s) of up to {cfg.block_size} rows: {len(windowed)} snapshots modelled of "
            f"{stop - start} window rows (objective/generators weight x{factor:.4g}, stores weight unchanged). "
            "Totals are scaled to represent the full window."
        )
    scaled = 0
    if cfg.scale_start_up_costs and abs(factor - 1.0) > 1e-12:
        for list_name in ("generators", "links", "processes"):
            if list_name not in network.components.keys():
                continue
            frame = network.components[list_name].static
            if frame.empty or "committable" not in frame.columns:
                continue
            mask = frame["committable"].astype(bool)
            for col in ("start_up_cost", "shut_down_cost"):
                if col in frame.columns and bool(mask.any()):
                    frame.loc[mask, col] = frame.loc[mask, col].astype(float) * factor
            scaled += int(mask.sum())
        if scaled:
            notes.append(
                f"Test-run sampling: start_up_cost / shut_down_cost of {scaled} committable unit(s) multiplied by x{factor:.4g}: "
                "PyPSA charges them per event, so the sampled blocks' events stand for the whole window's."
            )
    return {"blocks": blocks, "kept": int(len(windowed)), "window": int(stop - start), "factor": factor, "averaged": averaged}


def sample_model(model: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """The visible transform: the workbook with the sampled snapshots, weightings and (averaged) series written in.

    ``options``: ``samplingConfig`` (+ optional ``snapshotStart`` / ``snapshotCount`` / ``snapshotEnd`` window).
    Returns ``{model, notes, before, after, factor}``. Raises ``ValueError`` when sampling is off or the model has
    investment periods (pathway runs define their horizon with periods).
    """
    from .network import build_components
    from .network_ops import _to_model

    options = dict(options or {})
    cfg = parse_sampling_config(options.get("samplingConfig"))
    if not cfg.enabled:
        raise ValueError("samplingConfig.enabled must be true to sample a workbook.")
    network, notes = build_components(model, options)
    if isinstance(network.snapshots, __import__("pandas").MultiIndex):
        raise ValueError("Sampling is not available for a multi-period (pathway) workbook.")
    n_all = len(network.snapshots)
    start = max(0, int(number(options.get("snapshotStart"), 0)))
    raw_count = options.get("snapshotCount")
    if raw_count in (None, "") and options.get("snapshotEnd") not in (None, ""):
        raw_count = number(options.get("snapshotEnd"), 0) - start
    stop = min(n_all, start + max(1, int(number(raw_count, n_all or 1))))
    log: list[str] = []
    info = apply_test_run_sampling(network, start, stop, cfg, log)
    return {
        "model": _to_model(network, model), "notes": log, "before": {"snapshots": n_all}, "after": {"snapshots": info["kept"]},
        "factor": info["factor"],
    }
