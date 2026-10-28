"""Compat only: the snapshot window as build versions before 4 solved it.

Until build version 4 the run builder downsampled with a stride (snapshotWeight = every k-th row, point
sampled, weight = k) and wrote sampled-block weights over the sheet's own (objective / generators = W / M,
stores = the stride). Both are now visible modules (Forge temporal transforms, backend/pypsa/sampling.py);
core never strides. A STORED run from before 4 is re-derived (analytics rebuild the network and align it with the
stored output series) through this module so its snapshot axis and weights match the stored results. A new run never
reaches it: build_network refuses snapshotWeight > 1.

Delete together with the build-version-3 compat in cost_basis.py once no stored run predates version 4.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..sampling import SamplingConfig, average_window_frames, sample_block_indices
from ..pathway import PathwayConfig
from ..utils.coerce import number
from .snapshots import WEIGHTING_COLUMNS, _normalize_dynamic_snapshot_index_names


def rescale_weightings(
    full_weights: pd.DataFrame,
    full: pd.Index,
    windowed: pd.Index,
    start: int,
    stop: int,
    step: int,
    sampled: bool,
) -> pd.DataFrame:
    """Weightings for the modelled snapshots, built from the imported ones.

    Contiguous / strided runs: each kept snapshot carries the SUM of the
    imported weights of the ``step`` rows it stands for (a stride of 1 keeps its
    own weight unchanged). Sampled runs: ``objective``/``generators`` keep their
    own imported weights, scaled so they integrate to the whole window
    ``[start, stop)`` the sample represents; ``stores`` stays the physical
    block-sum so the storage SOC recursion is hours-true.

    Algorithm:
        $$w_i = \\sum_{j=p_i}^{\\min(p_i+s,\\,e_i)-1} w^{imp}_j,\\qquad
          w^{samp}_i = w^{imp}_{p_i}\\,\\frac{\\sum_{j=a}^{b-1} w^{imp}_j}{\\sum_k w^{imp}_{p_k}}$$
        ASCII: w_i = sum(w_imp[p_i : min(p_i+s, e_i)]); sampled: w_i = w_imp[p_i]
        * sum(w_imp[a:b]) / sum(w_imp[kept]).
        p_i position of kept snapshot i in the full index, s the stride (rows),
        e_i the end of its investment period (or ``b``), [a, b) the window;
        weights in hours.
    """
    positions = full.get_indexer(windowed)
    if isinstance(full, pd.MultiIndex) and "period" in (full.names or []):
        period = np.asarray(full.get_level_values("period"))
        group_end = np.empty(len(full), dtype=int)
        end = len(full)
        for i in range(len(full) - 1, -1, -1):
            if i + 1 < len(full) and period[i + 1] != period[i]:
                end = i + 1
            group_end[i] = end
        limits = group_end[positions]
    else:
        limits = np.full(len(positions), stop, dtype=int)
    out = pd.DataFrame(index=windowed, columns=list(full_weights.columns), dtype=float)
    for col in full_weights.columns:
        w = full_weights[col].to_numpy(dtype=float)
        csum = np.concatenate([[0.0], np.cumsum(w)])
        ends = np.minimum(positions + step, np.maximum(limits, positions + 1))
        block = csum[ends] - csum[positions]
        if sampled and col != "stores":
            kept = w[positions]
            window_total = float(csum[stop] - csum[start])
            kept_total = float(kept.sum())
            out[col] = kept * (window_total / kept_total) if kept_total > 0 else block
        else:
            out[col] = block
    return out


def apply_legacy_window(
    network: pypsa.Network,
    options: dict[str, Any],
    pathway: PathwayConfig,
    sampling: SamplingConfig,
    authored_weights: pd.DataFrame | None,
    notes: list[str],
) -> None:
    """Window / stride / sample network exactly as builds before version 4 did (in place)."""
    # ── Snapshot windowing & downsampling ─────────────────────────────────────
    start = max(0, int(number(options.get("snapshotStart"), 0)))
    # snapshotCount wins when present. Absent, fall back to snapshotEnd —
    # clients naturally describe the window as [start, end) and the Ragnarok
    # frontend sends both; a payload carrying only snapshotEnd used to be
    # silently solved over ALL snapshots. Absent both, model everything.
    raw_count = options.get("snapshotCount")
    if raw_count in (None, "") and options.get("snapshotEnd") not in (None, ""):
        raw_count = number(options.get("snapshotEnd"), 0) - start
    count = max(1, int(number(raw_count, len(network.snapshots) or 1)))
    step = max(1, int(number(options.get("snapshotWeight"), 1)))
    full = network.snapshots
    if len(full) > 0:
        if pathway.enabled:
            windowed = full
            if step > 1:
                if isinstance(full, pd.MultiIndex):
                    period_levels = list(full.get_level_values("period").unique())
                    pieces = []
                    for period in period_levels:
                        period_index = full[full.get_level_values("period") == period]
                        pieces.append(period_index[::step])
                    if pieces:
                        windowed = pieces[0]
                        for piece in pieces[1:]:
                            windowed = windowed.append(piece)
                else:
                    windowed = full[::step]
            stop = len(full)
            start = 0
        else:
            stop = min(len(full), start + count)
            if sampling.enabled and sampling.mode == "average":
                B = min(max(1, sampling.block_size), max(1, stop - start))
                averaged_periods = average_window_frames(network, start, stop, B)
                windowed = full[start:start + B]
                if step > 1:
                    windowed = windowed[::step]
            elif sampling.enabled:
                idx, sampled_blocks = sample_block_indices(start, stop, sampling, step)
                windowed = full[idx]
            else:
                windowed = full[start:stop]
                if step > 1:
                    windowed = windowed[::step]
        if len(windowed) == 0:
            windowed = full[:1]
        full_weights = network.snapshot_weightings.copy()
        network.set_snapshots(windowed)
        # Weighting. Contiguous runs: every column = stride hours (unchanged).
        # Sampled runs: objective/generators carry W/M so totals, costs and
        # constraint budgets integrate to the FULL window the sample
        # represents; stores keeps the physical stride so the storage SOC
        # recursion stays an hours-true integration inside each block.
        #   w = W / M   (window rows / modelled snapshots; == step when not sampling)
        sampling_active = sampling.enabled and not pathway.enabled
        if sampling_active:
            represented = float(stop - start)
        else:
            represented = float(len(windowed) * step)
        weight = represented / max(1, len(windowed))
        if authored_weights is not None:
            rescaled = rescale_weightings(
                full_weights, full, windowed, start, stop, step, sampling_active
            )
            for col in WEIGHTING_COLUMNS:
                network.snapshot_weightings[col] = rescaled[col].to_numpy()
        else:
            for col in ("objective", "generators"):
                network.snapshot_weightings[col] = weight
            network.snapshot_weightings["stores"] = float(step)
        if sampling_active and sampling.mode == "average":
            notes.append(
                f"Averaged {averaged_periods} period(s) into one {sampling.block_size}-row profile: "
                f"{len(windowed)} snapshots modelled of {stop - start} window rows "
                f"(weight ×{weight:.2f}). Totals represent the full window; "
                "peaks and variability are smoothed by the averaging."
            )
        elif sampling_active:
            notes.append(
                f"Sampled {sampled_blocks} block(s) of up to {sampling.block_size} rows: "
                f"{len(windowed)} snapshots modelled of {stop - start} window rows "
                f"(weight ×{weight:.2f}, {step}h resolution in-block). "
                "Totals are scaled to represent the full window."
            )
        else:
            notes.append(
                f"Modelled {len(windowed)} snapshots at {step}h resolution "
                f"(rows {start} → {stop} of {len(full)})."
            )
        _normalize_dynamic_snapshot_index_names(network)
