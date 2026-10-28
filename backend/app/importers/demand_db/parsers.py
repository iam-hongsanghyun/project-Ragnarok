"""Pure parsers: upstream file -> ``{area: DataFrame[timestamp, load_mw, source_url]}`` (D2).

No network, no writes. Timestamps come out tz-aware UTC and **hour-beginning**; the unit is MW.
Tested against small captured fixtures (``backend/tests/fixtures/demand_db``).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

OPSD_LOAD_SUFFIX = "_load_actual_entsoe_transparency"
OPSD_TS_COL = "utc_timestamp"

EIA_BA_COL = "Balancing Authority"
EIA_UTC_END_COL = "UTC Time at End of Hour"
EIA_DEMAND_COLS = ("Demand (MW) (Adjusted)", "Demand (MW) (Imputed)", "Demand (MW)")
EIA_TS_FORMAT = "%m/%d/%Y %I:%M:%S %p"
# The bulk file is labelled hour-ENDING (UTC); PyPSA snapshots are interval starts (RI4, same
# rule as the eia_demand importer), so the stored timestamp is the end minus one hour.
HOUR_ENDING_SHIFT = pd.Timedelta(hours=1)


class ParseError(ValueError):
    """The file does not look like the format we expect (columns missing / unparseable)."""


def opsd_areas(csv_path: Path) -> list[str]:
    """Areas that have an actual-load column in an OPSD ``time_series_60min`` CSV."""
    cols = list(pd.read_csv(csv_path, nrows=0).columns)
    if OPSD_TS_COL not in cols:
        raise ParseError(f"OPSD file has no {OPSD_TS_COL!r} column (columns: {cols[:5]}...)")
    return [c[: -len(OPSD_LOAD_SUFFIX)] for c in cols if c.endswith(OPSD_LOAD_SUFFIX)]


def parse_opsd(csv_path: Path, areas: Iterable[str], source_url: str) -> dict[str, pd.DataFrame]:
    """Actual total load per area from the OPSD single-index 60-minute CSV.

    ``utc_timestamp`` is "start of time period in UTC", already hour-beginning; values are MW.
    Missing values stay out of the result (the validator drops NaN too).
    """
    areas = list(areas)
    have = set(opsd_areas(csv_path))
    unknown = [a for a in areas if a not in have]
    if unknown:
        raise ParseError(f"OPSD file has no load_actual column for {unknown}")
    cols = {a: a + OPSD_LOAD_SUFFIX for a in areas}
    df = pd.read_csv(csv_path, usecols=[OPSD_TS_COL, *cols.values()])
    ts = pd.to_datetime(df[OPSD_TS_COL], utc=True, errors="coerce")
    if ts.isna().all():
        raise ParseError("OPSD utc_timestamp column could not be parsed")
    out: dict[str, pd.DataFrame] = {}
    for area, col in cols.items():
        frame = pd.DataFrame({"timestamp": ts, "load_mw": pd.to_numeric(df[col], errors="coerce")})
        frame = frame.dropna()
        frame["source_url"] = source_url
        out[area] = frame.reset_index(drop=True)
    return out


def parse_eia930(csv_path: Path, areas: Iterable[str] | None, source_url: str) -> dict[str, pd.DataFrame]:
    """Demand per balancing authority from an ``EIA930_BALANCE_<year>_<half>.csv``.

    Takes 'Demand (MW) (Adjusted)', filling gaps from '(Imputed)' then the raw column, and
    shifts hour-ending UTC to hour-beginning. ``areas=None`` returns every BA in the file.
    """
    header = list(pd.read_csv(csv_path, nrows=0).columns)
    for needed in (EIA_BA_COL, EIA_UTC_END_COL):
        if needed not in header:
            raise ParseError(f"EIA-930 file lacks column {needed!r} (has: {header[:6]}...)")
    demand_cols = [c for c in EIA_DEMAND_COLS if c in header]
    if not demand_cols:
        raise ParseError("EIA-930 file has no Demand (MW) column")
    # dtype=str on the code column keeps codes like '0' prefixes intact; thousands="," is for
    # quoted values such as "10,123".
    df = pd.read_csv(
        csv_path, usecols=[EIA_BA_COL, EIA_UTC_END_COL, *demand_cols], thousands=",",
        dtype={EIA_BA_COL: str},
    )
    if areas is not None:
        df = df[df[EIA_BA_COL].isin(list(areas))]
    end = pd.to_datetime(df[EIA_UTC_END_COL], format=EIA_TS_FORMAT, utc=True, errors="coerce")
    value = pd.to_numeric(df[demand_cols[0]], errors="coerce")
    for c in demand_cols[1:]:
        value = value.fillna(pd.to_numeric(df[c], errors="coerce"))
    frame = pd.DataFrame({"area": df[EIA_BA_COL].to_numpy(), "timestamp": (end - HOUR_ENDING_SHIFT).to_numpy(),
                          "load_mw": value.to_numpy()})
    frame = frame.dropna(subset=["timestamp", "load_mw"])
    out: dict[str, pd.DataFrame] = {}
    for area, g in frame.groupby("area", sort=True):
        g = g[["timestamp", "load_mw"]].copy()
        g["timestamp"] = pd.to_datetime(g["timestamp"], utc=True)
        g["source_url"] = source_url
        out[str(area)] = g.reset_index(drop=True)
    return out


def parse_entsoe_load(xml_text: str, source_url: str) -> pd.DataFrame:
    """ENTSO-E A65 GL_MarketDocument -> hourly frame (sub-hourly points averaged; interval start).

    Reuses the entsoe_load importer's parser, so both stay in step. An Acknowledgement document
    (HTTP 200 carrying an error / 'no data' reason) raises ``RuntimeError`` - it is never read as
    an empty series.
    """
    from ..databases.entsoe_load import _aggregate_hourly, _parse_load_xml

    hourly: list[tuple[str, float]] = _aggregate_hourly(_parse_load_xml(xml_text))
    frame = pd.DataFrame(hourly, columns=["timestamp", "load_mw"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["source_url"] = source_url
    return frame


_NO_DATA_RE = re.compile(r"no matching data|no data", re.I)


def is_no_data_error(exc: Exception) -> bool:
    return bool(_NO_DATA_RE.search(str(exc)))


def eia_file_names(year: int) -> list[str]:
    return [f"EIA930_BALANCE_{year}_Jan_Jun.csv", f"EIA930_BALANCE_{year}_Jul_Dec.csv"]


def summary_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Annual-style sanity figures for a frame: TWh (sum of hourly MW / 1e6), peak and mean MW."""
    if df.empty:
        return {"hours": 0}
    return {
        "hours": int(len(df)),
        "energy_twh": round(float(df["load_mw"].sum()) / 1e6, 3),
        "peak_mw": round(float(df["load_mw"].max()), 1),
        "mean_mw": round(float(df["load_mw"].mean()), 1),
        "min_mw": round(float(df["load_mw"].min()), 1),
    }
