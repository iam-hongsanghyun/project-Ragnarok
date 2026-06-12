"""Sampled snapshot blocks ("test run") configuration and index builder.

Instead of solving one contiguous snapshot window, a sampled run solves N
disjoint blocks of B snapshots spread across the window, with snapshot
weightings scaled so reported totals (energy, cost, emissions, constraint
budgets) represent the ENTIRE window. Two parametrizations:

- ``mode='count'``: ``block_count`` blocks of ``block_size`` rows, equally
  spaced across the window (first block at the window start, last ending at
  the window end).
- ``mode='gap'``: a block of ``block_size`` rows, then ``gap_snapshots``
  skipped rows, repeating until the window is exhausted (the trailing block
  may be truncated).

The existing stride (``snapshotWeight``) composes with sampling: it is
applied INSIDE each block, so "4 blocks of 168 rows at 3 h resolution" works.

Algorithm (weighting, applied by the caller in ``network.__init__``):
    $$ w = W / M $$
    ASCII: weight = window_rows / modelled_snapshots, so that
    sum_t(weight) == W and totals integrate to the full window.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .utils.coerce import number


@dataclass
class SamplingConfig:
    enabled: bool
    mode: str  # 'count' | 'gap'
    block_size: int
    block_count: int
    gap_snapshots: int


def parse_sampling_config(raw: dict[str, Any] | None) -> SamplingConfig:
    """Parse the ``samplingConfig`` options key (same style as rolling)."""
    raw = raw or {}
    enabled = bool(raw.get("enabled"))
    mode = str(raw.get("mode") or "count")
    if mode not in ("count", "gap"):
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
