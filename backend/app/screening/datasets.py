"""Screening datasets — parse, validate and store uploaded site / region time series.

A *dataset* is a set of historical series (one per site) plus a site table
(name, lat, lon, technology, region, unit). It is NOT model sheets: it lives
under ``<data root>/screening_datasets/<session id>/<dataset id>/`` as

    meta.json        sites (or regions), validation report, provenance
    series.parquet   UTC timestamp index x site columns, capacity factor 0-1

so it survives a reload and a backend restart, and never touches the working
model until the user promotes sites (see :mod:`.promote`). Three kinds:

* ``sites`` - one series per site plus the site table;
* ``regions`` - one series per *region* (a national or zonal CF / generation
  series) plus a region table: ``name``, optional centroid ``lat`` / ``lon``,
  optional GeoJSON polygon, optional ``technology``, ``unit``, ``capacity_mw``.
  The same validation as a site upload applies (timestamps, duplicates, gaps,
  time zone, units);
* ``reference`` - one load or price series (MW or currency/MWh, not normalised)
  used as the reference of a correlation.

Datasets stored by the earlier Siting > Screening step sit under
``<data root>/siting_datasets/``; :func:`datasets_dir` moves them to the new
folder the first time a session is touched, so they keep loading.

Two upload layouts are read (CSV or xlsx):

* long: ``site, timestamp, value``
* wide: one timestamp column, one column per site

Validation covers timestamps (unparseable rows), duplicates (averaged), gaps
(reported per site, then interpolated up to a limit or dropped), the time zone
(timestamps with an offset are converted; naive ones are read in the chosen
zone, default UTC) and unit sanity (capacity factor must lie in 0-1; MW series
are divided by the site capacity first).
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from ..data_root import data_root

#: Largest accepted upload (bytes).
MAX_UPLOAD_BYTES = int(os.environ.get("RAGNAROK_SITING_MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))
#: Most sites a dataset may hold.
MAX_SITES = int(os.environ.get("RAGNAROK_SITING_MAX_SITES", "400"))
#: Gaps up to this many steps are interpolated under the ``interpolate`` policy.
DEFAULT_MAX_INTERP_STEPS = int(os.environ.get("RAGNAROK_SITING_MAX_INTERP_STEPS", "48"))
#: Slack allowed around 0 and 1 before a capacity factor counts as out of range.
CF_TOLERANCE = 1e-3
#: Share of unparseable timestamps above which the upload is rejected rather than trimmed.
MAX_BAD_TIMESTAMP_SHARE = 0.05

TECHNOLOGIES = ("solar", "wind", "other")
UNITS = ("cf", "mw")
KINDS = ("sites", "reference", "regions")
GAP_POLICIES = ("interpolate", "drop")

_ID_GUARD = re.compile(r"^[A-Za-z0-9._\-]+$")
_TS_ALIASES = ("timestamp", "time", "datetime", "date", "snapshot", "datetime_utc", "time_utc", "utc")
_SITE_ALIASES = ("site", "name", "site_name", "id", "site_id", "location")
_VALUE_ALIASES = ("value", "cf", "capacity_factor", "cf_value", "mw", "power", "load", "price", "load_mw", "output")
_SITE_COLS = {
    "name": ("name", "site", "site_name", "id", "site_id"),
    "lat": ("lat", "latitude", "y"),
    "lon": ("lon", "lng", "long", "longitude", "x"),
    "technology": ("technology", "tech", "type", "carrier", "fuel"),
    "region": ("region", "zone", "area", "country"),
    "unit": ("unit", "units"),
    "capacity_mw": ("capacity_mw", "capacity", "p_nom", "p_nom_mw", "installed_mw", "mw"),
}
_REGION_COLS = {
    "name": ("name", "region", "zone", "area", "country", "id"),
    "lat": _SITE_COLS["lat"],
    "lon": _SITE_COLS["lon"],
    "technology": _SITE_COLS["technology"],
    "unit": _SITE_COLS["unit"],
    "capacity_mw": _SITE_COLS["capacity_mw"],
    "geometry": ("geometry", "geojson", "polygon", "boundary"),
}
_TZ_SUFFIX = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})\s*$")


class DatasetError(ValueError):
    """An upload that cannot be stored; ``report`` carries the full validation findings."""

    def __init__(self, message: str, report: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.report = report or {}


# ── paths ─────────────────────────────────────────────────────────────────────


def _is_safe(name: str) -> bool:
    return bool(name) and ".." not in name and bool(_ID_GUARD.match(name))


def _migrate_legacy(session_id: str) -> None:
    """Move datasets of the old ``siting_datasets/<session>`` folder into ``screening_datasets/<session>``.

    Idempotent: a dataset already present in the new folder is left alone (and its old copy kept), an
    emptied old session folder is removed. Runs on every call but is a single ``exists`` check once done.
    """
    old = data_root() / "siting_datasets" / session_id
    if not old.is_dir():
        return
    new = data_root() / "screening_datasets" / session_id
    new.mkdir(parents=True, exist_ok=True)
    for folder in list(old.iterdir()):
        target = new / folder.name
        if folder.is_dir() and not target.exists():
            shutil.move(str(folder), str(target))
    try:
        old.rmdir()
        (data_root() / "siting_datasets").rmdir()
    except OSError:
        pass  # something is left behind (a clashing id) or other sessions still use the old root


def datasets_dir(session_id: str) -> Path:
    """Folder holding a session's datasets (resolved at call time so tests can retarget the data root)."""
    if not _is_safe(session_id):
        raise DatasetError(f"Invalid session id {session_id!r}.")
    _migrate_legacy(session_id)
    return data_root() / "screening_datasets" / session_id


def _dataset_dir(session_id: str, dataset_id: str) -> Path:
    if not _is_safe(dataset_id):
        raise DatasetError(f"Invalid dataset id {dataset_id!r}.")
    return datasets_dir(session_id) / dataset_id


# ── reading uploads ───────────────────────────────────────────────────────────


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """Read a CSV or xlsx upload into a frame (first sheet of a workbook).

    Raises:
        DatasetError: unsupported extension, empty file or unreadable content.
    """
    if not data:
        raise DatasetError(f"{filename or 'file'} is empty.")
    ext = Path(filename or "").suffix.lower()
    try:
        if ext in (".xlsx", ".xlsm", ".xls"):
            df = pd.read_excel(io.BytesIO(data), sheet_name=0)
        elif ext in (".csv", ".txt", ".tsv", ""):
            df = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
        else:
            raise DatasetError(f"Unsupported file type {ext!r}; upload .csv or .xlsx.")
    except DatasetError:
        raise
    except Exception as exc:
        raise DatasetError(f"Could not read {filename}: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    if df.empty:
        raise DatasetError(f"{filename} has no rows.")
    return df


def _find_col(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    lower = {c.lower().replace(" ", "_"): c for c in columns}
    for alias in aliases:
        if alias in lower:
            return lower[alias]
    return None


def parse_site_table(df: pd.DataFrame, default_unit: str = "cf") -> list[dict[str, Any]]:
    """Normalise a site table to ``name, lat, lon, technology, region, unit, capacityMw`` rows.

    Raises:
        DatasetError: missing name / lat / lon column, bad coordinates, technology or unit,
            duplicate names, or an MW site without a positive capacity.
    """
    cols = list(df.columns)
    found = {key: _find_col(cols, aliases) for key, aliases in _SITE_COLS.items()}
    missing = [k for k in ("name", "lat", "lon", "technology") if not found[k]]
    if missing:
        raise DatasetError(
            f"Site table needs columns name, lat, lon, technology (optional: region, unit, capacity_mw); missing {missing}; found {cols}."
        )
    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, rec in enumerate(df.to_dict("records"), start=2):
        name = str(rec[found["name"]]).strip()
        if not name or name.lower() == "nan":
            continue
        if name in seen:
            problems.append(f"row {i}: duplicate site name {name!r}")
            continue
        seen.add(name)
        try:
            lat, lon = float(rec[found["lat"]]), float(rec[found["lon"]])
        except (TypeError, ValueError):
            problems.append(f"row {i} ({name}): lat/lon are not numbers")
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            problems.append(f"row {i} ({name}): lat/lon out of WGS84 range")
            continue
        tech = str(rec[found["technology"]]).strip().lower()
        if tech not in TECHNOLOGIES:
            problems.append(f"row {i} ({name}): technology {tech!r} is not one of {list(TECHNOLOGIES)}")
            continue
        unit = str(rec[found["unit"]]).strip().lower() if found["unit"] and not _blank(rec[found["unit"]]) else default_unit
        if unit not in UNITS:
            problems.append(f"row {i} ({name}): unit {unit!r} is not one of {list(UNITS)}")
            continue
        cap: float | None = None
        if found["capacity_mw"] and not _blank(rec[found["capacity_mw"]]):
            try:
                cap = float(rec[found["capacity_mw"]])
            except (TypeError, ValueError):
                problems.append(f"row {i} ({name}): capacity is not a number")
                continue
        if unit == "mw" and not (cap and cap > 0):
            problems.append(f"row {i} ({name}): unit is MW, so a positive capacity_mw is needed to normalise to CF")
            continue
        region = "" if not found["region"] or _blank(rec[found["region"]]) else str(rec[found["region"]]).strip()
        rows.append({"name": name, "lat": lat, "lon": lon, "technology": tech, "region": region, "unit": unit, "capacityMw": cap})
    if problems:
        raise DatasetError("Site table is invalid: " + "; ".join(problems[:10]) + (" ..." if len(problems) > 10 else ""),
                           {"errors": problems})
    if not rows:
        raise DatasetError("Site table has no usable rows.")
    if len(rows) > MAX_SITES:
        raise DatasetError(f"Site table has {len(rows)} sites; the limit is {MAX_SITES}.")
    return rows


def _ring_area_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Signed area (deg^2) and centroid (x = lon, y = lat) of one closed ring by the shoelace formula."""
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    a = cx = cy = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i][0], pts[i][1]
        x1, y1 = pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    a *= 0.5
    if abs(a) < 1e-12:  # degenerate ring: vertex mean
        return 0.0, float(np.mean([p[1] for p in pts])), float(np.mean([p[0] for p in pts]))
    return a, cy / (6.0 * a), cx / (6.0 * a)


def validate_geometry(geometry: Any, label: str) -> dict[str, Any]:
    """A GeoJSON ``Polygon`` / ``MultiPolygon`` in WGS84, or :class:`DatasetError`."""
    if isinstance(geometry, str):
        try:
            geometry = json.loads(geometry)
        except ValueError as exc:
            raise DatasetError(f"{label}: geometry is not valid JSON.") from exc
    if isinstance(geometry, dict) and geometry.get("type") == "Feature":
        geometry = geometry.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise DatasetError(f"{label}: geometry must be a GeoJSON Polygon or MultiPolygon.")
    polys = [geometry.get("coordinates")] if geometry["type"] == "Polygon" else list(geometry.get("coordinates") or [])
    try:
        for poly in polys:
            for ring in poly:
                if len(ring) < 4:
                    raise ValueError("ring with fewer than 4 positions")
                for lon, lat, *_ in ring:
                    if not (-180 <= float(lon) <= 180 and -90 <= float(lat) <= 90):
                        raise ValueError("position outside WGS84 range (GeoJSON order is lon, lat)")
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"{label}: invalid polygon ({exc}).") from exc
    if not polys:
        raise DatasetError(f"{label}: empty polygon.")
    return {"type": geometry["type"], "coordinates": geometry["coordinates"]}


def geometry_centroid(geometry: dict[str, Any]) -> tuple[float, float]:
    """Centroid ``(lat, lon)`` of the largest outer ring of a polygon, by the shoelace formula (planar, degrees)."""
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else list(geometry["coordinates"])
    best = max((_ring_area_centroid(poly[0]) for poly in polys), key=lambda t: abs(t[0]))
    return best[1], best[2]


def parse_region_table(df: pd.DataFrame, default_unit: str = "cf") -> list[dict[str, Any]]:
    """Normalise a region table to ``name, lat, lon, technology, region, unit, capacityMw, geometry`` rows.

    ``lat`` / ``lon`` (a centroid) are optional; a ``geometry`` column (a GeoJSON polygon as text) is
    optional and, when there is no centroid, supplies one. A region without either is analysed but not drawn.

    Raises:
        DatasetError: missing name column, bad coordinates / geometry / unit / capacity, duplicate names.
    """
    cols = list(df.columns)
    found = {key: _find_col(cols, aliases) for key, aliases in _REGION_COLS.items()}
    if not found["name"]:
        raise DatasetError(f"Region table needs a name column (optional: lat, lon, technology, unit, capacity_mw, geometry); found {cols}.")
    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, rec in enumerate(df.to_dict("records"), start=2):
        name = str(rec[found["name"]]).strip()
        if not name or name.lower() == "nan":
            continue
        if name in seen:
            problems.append(f"row {i}: duplicate region name {name!r}")
            continue
        seen.add(name)
        lat = lon = None
        if found["lat"] and found["lon"] and not _blank(rec[found["lat"]]) and not _blank(rec[found["lon"]]):
            try:
                lat, lon = float(rec[found["lat"]]), float(rec[found["lon"]])
            except (TypeError, ValueError):
                problems.append(f"row {i} ({name}): lat/lon are not numbers")
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                problems.append(f"row {i} ({name}): lat/lon out of WGS84 range")
                continue
        geometry = None
        if found["geometry"] and not _blank(rec[found["geometry"]]):
            try:
                geometry = validate_geometry(rec[found["geometry"]], f"row {i} ({name})")
            except DatasetError as exc:
                problems.append(str(exc))
                continue
        tech = "" if not found["technology"] or _blank(rec[found["technology"]]) else str(rec[found["technology"]]).strip().lower()
        if tech and tech not in TECHNOLOGIES:
            problems.append(f"row {i} ({name}): technology {tech!r} is not one of {list(TECHNOLOGIES)}")
            continue
        unit = str(rec[found["unit"]]).strip().lower() if found["unit"] and not _blank(rec[found["unit"]]) else default_unit
        if unit not in UNITS:
            problems.append(f"row {i} ({name}): unit {unit!r} is not one of {list(UNITS)}")
            continue
        cap: float | None = None
        if found["capacity_mw"] and not _blank(rec[found["capacity_mw"]]):
            try:
                cap = float(rec[found["capacity_mw"]])
            except (TypeError, ValueError):
                problems.append(f"row {i} ({name}): capacity is not a number")
                continue
        if unit == "mw" and not (cap and cap > 0):
            problems.append(f"row {i} ({name}): unit is MW, so a positive capacity_mw is needed to normalise to CF")
            continue
        if lat is None and geometry is not None:
            lat, lon = geometry_centroid(geometry)
        rows.append({"name": name, "lat": lat, "lon": lon, "technology": tech, "region": name, "unit": unit,
                     "capacityMw": cap, "geometry": geometry})
    if problems:
        raise DatasetError("Region table is invalid: " + "; ".join(problems[:10]) + (" ..." if len(problems) > 10 else ""),
                           {"errors": problems})
    if not rows:
        raise DatasetError("Region table has no usable rows.")
    if len(rows) > MAX_SITES:
        raise DatasetError(f"Region table has {len(rows)} regions; the limit is {MAX_SITES}.")
    return rows


def attach_geojson(rows: list[dict[str, Any]], geojson: Any) -> list[str]:
    """Attach polygons of a GeoJSON FeatureCollection to the region rows by ``properties.name`` (or ``region`` / ``id``).

    Returns the warnings (features that match no region). Regions without a centroid get the polygon's.

    Raises:
        DatasetError: not a FeatureCollection / Feature, or an invalid polygon of a matched region.
    """
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except ValueError as exc:
            raise DatasetError("GeoJSON is not valid JSON.") from exc
    if isinstance(geojson, dict) and geojson.get("type") == "Feature":
        geojson = {"type": "FeatureCollection", "features": [geojson]}
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        raise DatasetError("GeoJSON must be a FeatureCollection (or one Feature) whose properties carry the region name.")
    by_name = {r["name"]: r for r in rows}
    warnings: list[str] = []
    for feat in geojson.get("features") or []:
        props = feat.get("properties") or {}
        key = next((str(props[k]).strip() for k in ("name", "region", "id", "NAME") if k in props and not _blank(props[k])), None)
        if key is None or key not in by_name:
            warnings.append(f"GeoJSON feature {key!r} matches no region and was ignored.")
            continue
        row = by_name[key]
        row["geometry"] = validate_geometry(feat, key)
        if row["lat"] is None:
            row["lat"], row["lon"] = geometry_centroid(row["geometry"])
    return warnings


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip() == "" or str(v).lower() == "nan"


def _parse_timestamps(col: pd.Series, tz_name: str) -> tuple[pd.DatetimeIndex, str, int]:
    """Timestamps to naive UTC. Returns ``(index with NaT for unparseable, how, n_unparseable)``."""
    try:
        zone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise DatasetError(f"Unknown time zone {tz_name!r} (use an IANA name such as 'UTC' or 'Asia/Seoul').") from exc
    how = f"read in {tz_name}, converted to UTC" if tz_name.upper() != "UTC" else "read as UTC"
    if pd.api.types.is_datetime64_any_dtype(col):
        ts = pd.DatetimeIndex(col)
    else:
        text = col.astype(str).str.strip()
        has_offset = text.str.contains(_TZ_SUFFIX).mean() > 0.5
        utc = True if has_offset else None
        ts = pd.DatetimeIndex(pd.to_datetime(text, errors="coerce", utc=utc, format="ISO8601"))
        if pd.isna(ts).mean() > 0.5:  # not ISO: fall back to per-element parsing (slower)
            ts = pd.DatetimeIndex(pd.to_datetime(text, errors="coerce", utc=utc, format="mixed"))
        if has_offset:
            how = "timestamps carry a UTC offset; converted to UTC (selected zone ignored)"
    if ts.tz is None:
        if tz_name.upper() != "UTC":
            ts = ts.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")
            ts = ts.tz_convert("UTC").tz_localize(None)
    else:
        ts = ts.tz_convert("UTC").tz_localize(None)
    bad = int(pd.isna(ts).sum() - col.isna().sum())
    return ts, how, max(0, bad)


def _to_wide(
    df: pd.DataFrame, layout: str, tz_name: str, kind: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reshape an upload into a UTC-indexed wide frame + the timestamp / duplicate findings."""
    cols = list(df.columns)
    report: dict[str, Any] = {"layout": layout}
    if layout == "long":
        ts_col = _find_col(cols, _TS_ALIASES)
        val_col = _find_col([c for c in cols if c != ts_col], _VALUE_ALIASES)
        site_col = _find_col([c for c in cols if c not in (ts_col, val_col)], _SITE_ALIASES)
        if kind == "reference" and site_col is None:
            df = df.assign(__site__="reference")
            site_col = "__site__"
        if not (ts_col and val_col and site_col):
            raise DatasetError(f"Long layout needs columns site, timestamp, value; found {cols}.")
        ts, how, n_bad = _parse_timestamps(df[ts_col], tz_name)
        value = pd.to_numeric(df[val_col], errors="coerce")
        n_non_numeric = int(value.isna().sum() - df[val_col].isna().sum())
        long = pd.DataFrame({"site": df[site_col].astype(str).str.strip(), "ts": ts, "value": value})
        n_in = len(long)
        long = long[long["ts"].notna()]
        dup = int(long.duplicated(["site", "ts"]).sum())
        wide = long.pivot_table(index="ts", columns="site", values="value", aggfunc="mean", dropna=False)
        wide = wide.reindex(columns=list(dict.fromkeys(long["site"])))
    elif layout == "wide":
        ts_col = _find_col(cols, _TS_ALIASES) or cols[0]
        site_cols = [c for c in cols if c != ts_col]
        if not site_cols:
            raise DatasetError("Wide layout needs a timestamp column and one column per site.")
        ts, how, n_bad = _parse_timestamps(df[ts_col], tz_name)
        values = df[site_cols].apply(pd.to_numeric, errors="coerce")
        n_non_numeric = int(values.isna().sum().sum() - df[site_cols].isna().sum().sum())
        n_in = len(df)
        wide = values.copy()
        wide.index = ts
        wide = wide[wide.index.notna()]
        dup = int(wide.index.duplicated().sum())
        wide = wide.groupby(level=0).mean()
    else:
        raise DatasetError("layout must be 'long' or 'wide'.")
    if n_in and n_bad / n_in > MAX_BAD_TIMESTAMP_SHARE:
        raise DatasetError(
            f"{n_bad} of {n_in} timestamps ({100 * n_bad / n_in:.0f} %) could not be parsed; check the timestamp column and the layout.",
            {"timestamps": {"unparseable": n_bad, "rows": n_in}},
        )
    report["timestamps"] = {"interpretation": how, "unparseable": n_bad, "rowsRead": n_in}
    report["duplicates"] = {"count": dup, "resolution": "averaged" if dup else "none"}
    report["nonNumericValues"] = n_non_numeric
    wide = wide.sort_index()
    wide.index.name = "timestamp"
    wide.columns = [str(c) for c in wide.columns]
    return wide, report


def _gap_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """(start position, length) of every run of True in a boolean array."""
    if not mask.any():
        return []
    padded = np.concatenate(([False], mask, [False]))
    diff = np.diff(padded.astype(int))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return [(int(s), int(e - s)) for s, e in zip(starts, ends)]


def _regularise(wide: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timedelta, int]:
    """Snap onto a regular grid at the median step. Returns ``(frame, step, off_grid_count)``."""
    if len(wide) < 2:
        raise DatasetError("Need at least two timestamps.")
    steps = pd.Series(wide.index[1:] - wide.index[:-1])
    step = pd.Timedelta(steps.median())
    if step < pd.Timedelta(minutes=1):
        raise DatasetError(f"Median time step {step} is below one minute; check the timestamp column.")
    off_grid = int(((wide.index - wide.index[0]) % step != pd.Timedelta(0)).sum())
    freq = f"{int(step.total_seconds())}s"
    grid = wide.resample(freq, origin="start").mean()
    return grid, step, off_grid


def build_dataset(
    series_df: pd.DataFrame,
    *,
    layout: str,
    sites_df: pd.DataFrame | None,
    timezone_name: str = "UTC",
    gap_policy: str = "interpolate",
    max_interp_steps: int | None = None,
    kind: str = "sites",
    default_unit: str = "cf",
    reference_unit: str = "MW",
    geojson: Any = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Validate an upload and produce the series and site list to store.

    Args:
        series_df: raw uploaded series table (long or wide).
        layout: ``"long"`` or ``"wide"``.
        sites_df: the site table (``kind="sites"``) or region table (``kind="regions"``); required for both.
        timezone_name: IANA zone of naive timestamps.
        gap_policy: ``interpolate`` (linear in time, gaps up to ``max_interp_steps``; longer
            gaps and leading / trailing holes are dropped) or ``drop`` (every timestamp with
            a missing value in any site is removed, giving all sites a common time base).
        max_interp_steps: longest gap interpolated; default :data:`DEFAULT_MAX_INTERP_STEPS`.
        kind: ``sites``, ``regions`` or ``reference``.
        default_unit: unit of sites whose table row has none.
        reference_unit: label of a reference series (``MW`` / ``currency/MWh``).
        geojson: optional GeoJSON FeatureCollection of region polygons (``kind="regions"``), matched by name.

    Returns:
        ``(series, sites, report)`` — ``series`` is NaN-free, UTC-indexed, CF in 0-1 for sites.

    Raises:
        DatasetError: with ``.report`` when any error-level finding blocks the upload.
    """
    if kind not in KINDS:
        raise DatasetError(f"kind must be one of {list(KINDS)}.")
    if gap_policy not in GAP_POLICIES:
        raise DatasetError(f"gapPolicy must be one of {list(GAP_POLICIES)}.")
    limit = DEFAULT_MAX_INTERP_STEPS if max_interp_steps is None else max(0, int(max_interp_steps))
    wide, report = _to_wide(series_df, layout, timezone_name, kind)
    errors: list[str] = []
    warnings: list[str] = []
    report["timezone"] = timezone_name
    if report["timestamps"]["unparseable"]:
        warnings.append(f"{report['timestamps']['unparseable']} row(s) with unparseable timestamps were dropped.")
    if report["duplicates"]["count"]:
        warnings.append(f"{report['duplicates']['count']} duplicate timestamp(s) were averaged.")
    if report["nonNumericValues"]:
        warnings.append(f"{report['nonNumericValues']} non-numeric value(s) were read as missing.")

    # sites (or regions) <-> series
    if kind in ("sites", "regions"):
        label = "site" if kind == "sites" else "region"
        if sites_df is None:
            raise DatasetError(
                "A site table (name, lat, lon, technology, region, unit) is required." if kind == "sites"
                else "A region table (name, optional lat, lon, technology, unit, capacity_mw, geometry) is required."
            )
        sites = parse_site_table(sites_df, default_unit) if kind == "sites" else parse_region_table(sites_df, default_unit)
        if kind == "regions" and geojson is not None:
            warnings.extend(attach_geojson(sites, geojson))
        table_names = {s["name"] for s in sites}
        unmatched = [c for c in wide.columns if c not in table_names]
        no_series = [n for n in table_names if n not in set(wide.columns)]
        if unmatched:
            errors.append(f"Series for {label}(s) not in the {label} table: {unmatched[:8]}.")
        if no_series:
            warnings.append(f"{label.capitalize()}(s) in the table without a series were ignored: {sorted(no_series)[:8]}.")
        sites = [s for s in sites if s["name"] in set(wide.columns)]
        wide = wide[[s["name"] for s in sites]] if sites else wide
        if not sites:
            errors.append(f"No {label} in the table has a series.")
    else:
        if wide.shape[1] != 1:
            raise DatasetError(f"A reference dataset holds exactly one series; found {wide.shape[1]}.")
        wide.columns = ["reference"]
        sites = []
    report["sites"] = {"count": len(sites) if kind != "reference" else 1}
    if errors:
        report["errors"], report["warnings"] = errors, warnings
        raise DatasetError(" ".join(errors), report)

    # regular grid + gaps
    grid, step, off_grid = _regularise(wide)
    if off_grid:
        warnings.append(f"{off_grid} timestamp(s) were off the {step} grid and were averaged into their step.")
    gap_sites: dict[str, Any] = {}
    for col in grid.columns:
        runs = _gap_runs(grid[col].isna().to_numpy())
        if runs:
            gap_sites[col] = {
                "missingSteps": int(sum(n for _, n in runs)),
                "runs": len(runs),
                "longestRunSteps": int(max(n for _, n in runs)),
                "first": [
                    {"from": grid.index[s].isoformat(), "steps": n} for s, n in runs[:3]
                ],
            }
    total_steps = len(grid)
    report["resolution"] = {"stepMinutes": step.total_seconds() / 60.0, "steps": total_steps,
                            "start": grid.index[0].isoformat(), "end": grid.index[-1].isoformat()}
    report["gaps"] = {
        "sitesWithGaps": len(gap_sites),
        "missingStepsTotal": int(sum(g["missingSteps"] for g in gap_sites.values())),
        "bySite": gap_sites,
        "policy": gap_policy,
        "maxInterpolatedSteps": limit,
    }
    before = len(grid)
    interpolated = 0
    if gap_sites:
        if gap_policy == "interpolate":
            filled = grid.interpolate(method="time", limit=limit, limit_area="inside") if limit > 0 else grid
            interpolated = int(grid.isna().sum().sum() - filled.isna().sum().sum())
            grid = filled
        grid = grid.dropna(how="any")
    report["gaps"].update({"interpolatedValues": interpolated, "rowsDropped": before - len(grid)})
    if gap_sites:
        warnings.append(
            f"{len(gap_sites)} site(s) have gaps ({report['gaps']['missingStepsTotal']} missing steps): "
            f"{interpolated} value(s) interpolated, {before - len(grid)} timestamp(s) dropped."
        )
    if len(grid) < 3:
        report["errors"], report["warnings"] = ["Fewer than 3 complete timestamps remain after gap handling."], warnings
        raise DatasetError("Fewer than 3 complete timestamps remain after gap handling.", report)

    # units
    unit_findings: list[dict[str, Any]] = []
    if kind in ("sites", "regions"):
        for s in sites:
            x = grid[s["name"]].to_numpy(dtype=float)
            if s["unit"] == "mw":
                x = x / float(s["capacityMw"])
            lo, hi = float(np.min(x)), float(np.max(x))
            bad = int(np.sum((x < -CF_TOLERANCE) | (x > 1 + CF_TOLERANCE)))
            if bad:
                hint = " Values look like percent - divide by 100." if 1 < hi <= 100 and s["unit"] == "cf" else (
                    " Check the capacity_mw." if s["unit"] == "mw" else "")
                unit_findings.append({"site": s["name"], "unit": s["unit"], "min": lo, "max": hi, "outOfRange": bad})
                errors.append(f"{s['name']}: {bad} value(s) outside the capacity-factor range 0-1 (min {lo:.3g}, max {hi:.3g}).{hint}")
            grid[s["name"]] = np.clip(x, 0.0, 1.0)
            s["meanCf"] = float(np.mean(grid[s["name"]]))
    report["units"] = {"outOfRange": unit_findings, "basis": "capacity factor 0-1" if kind != "reference" else reference_unit}
    report["errors"], report["warnings"] = errors, warnings
    if errors:
        raise DatasetError(" ".join(errors[:5]), report)
    report["rowsStored"] = len(grid)
    return grid, sites, report


# ── store ─────────────────────────────────────────────────────────────────────


def store_dataset(
    session_id: str,
    name: str,
    series: pd.DataFrame,
    sites: list[dict[str, Any]],
    report: dict[str, Any],
    *,
    kind: str = "sites",
    timezone_name: str = "UTC",
    layout: str = "wide",
    filename: str = "",
    reference_kind: str | None = None,
    unit: str = "cf",
) -> dict[str, Any]:
    """Persist a validated dataset and return its summary."""
    dataset_id = f"ds_{uuid.uuid4().hex[:10]}"
    folder = _dataset_dir(session_id, dataset_id)
    folder.mkdir(parents=True, exist_ok=True)
    out = series.copy()
    out.index.name = "timestamp"
    out.to_parquet(folder / "series.parquet")
    meta = {
        "id": dataset_id,
        "name": name or Path(filename).stem or dataset_id,
        "kind": kind,
        "referenceKind": reference_kind,
        "unit": unit,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "sessionId": session_id,
        "timezone": timezone_name,
        "layout": layout,
        "filename": filename,
        "stepMinutes": report.get("resolution", {}).get("stepMinutes"),
        "start": series.index[0].isoformat(),
        "end": series.index[-1].isoformat(),
        "rows": len(series),
        "sites" if kind != "regions" else "regions": sites,
        "report": report,
    }
    (folder / "meta.json").write_text(json.dumps(meta, default=str), encoding="utf-8")
    return meta


def summary(meta: dict[str, Any]) -> dict[str, Any]:
    """The list-view of a dataset: meta without the (bulky) report and site rows."""
    keys = ("id", "name", "kind", "referenceKind", "unit", "createdAt", "timezone", "stepMinutes", "start", "end", "rows", "filename")
    out = {k: meta.get(k) for k in keys}
    kind = meta.get("kind")
    out["siteCount"] = len(meta.get("sites") or []) if kind == "sites" else (1 if kind == "reference" else 0)
    out["regionCount"] = len(meta.get("regions") or []) if kind == "regions" else 0
    out["warnings"] = len((meta.get("report") or {}).get("warnings") or [])
    return out


def get_meta(session_id: str, dataset_id: str) -> dict[str, Any] | None:
    """A dataset's meta, or ``None`` when absent."""
    path = _dataset_dir(session_id, dataset_id) / "meta.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_series(session_id: str, dataset_id: str) -> pd.DataFrame | None:
    """The stored series frame (UTC index, site columns), or ``None``."""
    path = _dataset_dir(session_id, dataset_id) / "series.parquet"
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df.index = pd.DatetimeIndex(df.index)
    return df


def list_datasets(session_id: str, kind: str | None = None) -> list[dict[str, Any]]:
    """Summaries of a session's datasets, newest first."""
    root = datasets_dir(session_id)
    out: list[dict[str, Any]] = []
    if root.exists():
        for folder in root.iterdir():
            meta_path = folder / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if kind is None or meta.get("kind") == kind:
                    out.append(summary(meta))
    return sorted(out, key=lambda m: str(m.get("createdAt")), reverse=True)


def delete_dataset(session_id: str, dataset_id: str) -> bool:
    """Remove a dataset; ``False`` when it did not exist."""
    folder = _dataset_dir(session_id, dataset_id)
    if not folder.exists():
        return False
    shutil.rmtree(folder)
    return True
