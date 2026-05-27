from __future__ import annotations

import pandas as pd


def safe_series(frame: pd.DataFrame, name: str) -> pd.Series:
    """Return the named column or a zero-filled series with the same index."""
    if name in frame.columns:
        return frame[name]
    return pd.Series(0.0, index=frame.index)


def weighted_sum(series: pd.Series, weights: pd.Series) -> float:
    aligned = weights.reindex(series.index).fillna(1.0)
    return float((series * aligned).sum())
