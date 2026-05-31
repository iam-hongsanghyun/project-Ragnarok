"""OPSD hourly load importer — country-level hourly p_set from a public CSV.

Self-contained. No imports from a shared convert/ package. Slug / dedupe /
provenance inlined. Output:

- one row in `loads` with name `{ISO}_national_load` carrying every OPSD
  metadata column the CSV header exposes;
- N rows in `loads-p_set` (one per hour in the requested date window), with
  `snapshot` + the single load name as columns;
- `WorkbookFragment.snapshots` populated so the frontend merger can union
  with the workbook's existing range.

No PyPSA defaults are fabricated. Anything the upstream is silent about
stays empty.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...protocol import (
    ConvertOptions,
    DatabaseMeta,
    FetchResult,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)

_log = logging.getLogger(__name__)

# Canonical URL — the date segment is pinned in config to a known release.
_DEFAULT_URL = (
    "https://data.open-power-system-data.org/time_series/2020-10-06/"
    "time_series_60min_singleindex.csv"
)
_TIMESTAMP_COL = "utc_timestamp"

# Module-local fetch cache; keyed by URL.
_CACHED_CSV: bytes | None = None
_CACHED_URL: str | None = None


def _csv_url() -> str:
    return os.environ.get("RAGNAROK_OPSD_LOAD_URL", _DEFAULT_URL)


def _csv_local_override() -> Path | None:
    override = os.environ.get("RAGNAROK_OPSD_LOAD_PATH")
    return Path(override).expanduser() if override else None


def _load_csv_bytes() -> bytes:
    global _CACHED_CSV, _CACHED_URL
    url = _csv_url()
    if _CACHED_CSV is not None and _CACHED_URL == url:
        return _CACHED_CSV
    override = _csv_local_override()
    if override is not None and override.exists():
        _log.info("loading OPSD load from local override: %s", override)
        _CACHED_CSV = override.read_bytes()
        _CACHED_URL = url
        return _CACHED_CSV
    _log.info("fetching OPSD load time-series from %s", url)
    with urllib.request.urlopen(url, timeout=600) as resp:
        _CACHED_CSV = resp.read()
    _CACHED_URL = url
    return _CACHED_CSV


def reset_cache() -> None:
    global _CACHED_CSV, _CACHED_URL
    _CACHED_CSV = None
    _CACHED_URL = None


# ── Slug helper ──────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _slug(raw: str | None, fallback: str = "load") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


# ── CSV parsing ──────────────────────────────────────────────────────────────


def _load_column_for(country_iso2: str, headers: list[str]) -> str | None:
    """Pick the best OPSD load column for a country. OPSD names them
    `{ISO2}_load_actual_entsoe_transparency` (preferred) or
    `{ISO2}_load_actual_entsoe_power_statistics` (older / patchier)."""
    candidates = [
        f"{country_iso2}_load_actual_entsoe_transparency",
        f"{country_iso2}_load_actual_entsoe_power_statistics",
        f"{country_iso2}_load_old",
    ]
    for c in candidates:
        if c in headers:
            return c
    return None


def _iso3_to_iso2(iso3: str) -> str:
    """Tiny ISO-3 → ISO-2 lookup. Covers the OPSD-supported set; everything
    else returns the input which makes the column lookup fail clean."""
    return _ISO3_TO_ISO2.get(iso3.upper(), iso3.upper())


_ISO3_TO_ISO2 = {
    "AUT": "AT", "BEL": "BE", "BGR": "BG", "CHE": "CH", "CYP": "CY",
    "CZE": "CZ", "DEU": "DE", "DNK": "DK", "ESP": "ES", "EST": "EE",
    "FIN": "FI", "FRA": "FR", "GBR": "GB", "GRC": "GR", "HRV": "HR",
    "HUN": "HU", "IRL": "IE", "ITA": "IT", "LTU": "LT", "LUX": "LU",
    "LVA": "LV", "MKD": "MK", "MLT": "MT", "NLD": "NL", "NOR": "NO",
    "POL": "PL", "PRT": "PT", "ROU": "RO", "SRB": "RS", "SVK": "SK",
    "SVN": "SI", "SWE": "SE",
}


@dataclass
class _Slice:
    column: str
    headers: list[str]
    # List of (utc_timestamp_iso, value_mw, raw_row_dict)
    rows: list[tuple[str, float, dict[str, str]]]


def _parse_window(csv_bytes: bytes, *, country_iso2: str, date_from: str, date_to: str) -> _Slice | None:
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return None
    column = _load_column_for(country_iso2, list(reader.fieldnames))
    if column is None:
        return None
    rows: list[tuple[str, float, dict[str, str]]] = []
    # date_from / date_to are inclusive at day level; window snapshots are
    # selected by the leading 10 chars of the ISO `utc_timestamp` column.
    for row in reader:
        ts = (row.get(_TIMESTAMP_COL) or "").strip()
        if not ts or ts[:10] < date_from or ts[:10] > date_to:
            continue
        val = row.get(column)
        if val is None or val == "":
            continue
        try:
            mw = float(val)
        except (TypeError, ValueError):
            continue
        rows.append((ts, mw, dict(row)))
    return _Slice(column=column, headers=list(reader.fieldnames), rows=rows)


# ── Database implementation ──────────────────────────────────────────────────


@dataclass
class OPSDLoadImporter:
    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult:
        date_from = str(filters.get("date_from") or "2019-01-01")
        date_to = str(filters.get("date_to") or "2019-12-31")
        iso2 = _iso3_to_iso2(region.country_iso)
        notes: list[str] = []
        try:
            csv_bytes = _load_csv_bytes()
        except Exception as exc:  # noqa: BLE001
            return FetchResult(
                database_id=self.meta.id,
                region=region,
                filters=dict(filters),
                payload={"slice": None},
                notes=[f"OPSD load CSV fetch failed: {exc}"],
            )
        sliced = _parse_window(
            csv_bytes,
            country_iso2=iso2,
            date_from=date_from,
            date_to=date_to,
        )
        if sliced is None:
            notes.append(
                f"OPSD does not publish hourly load for {region.country_iso} "
                f"(no `{iso2}_load_actual_*` column)."
            )
        elif not sliced.rows:
            notes.append(
                f"No OPSD rows in {date_from}..{date_to} for {region.country_iso}."
            )
        return FetchResult(
            database_id=self.meta.id,
            region=region,
            filters={"date_from": date_from, "date_to": date_to, **dict(filters)},
            payload={"slice": sliced, "country_iso2": iso2},
            notes=notes,
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        sliced: _Slice | None = result.payload.get("slice")
        if sliced is None or not sliced.rows:
            return PreviewSummary(
                counts={"hours": 0},
                samples={},
                notes=result.notes or ["No hourly load available."],
                overlay={},
            )
        total = sum(mw for _, mw, _ in sliced.rows)
        avg = total / len(sliced.rows) if sliced.rows else 0.0
        peak = max(mw for _, mw, _ in sliced.rows)
        # Sample shows the first 24 rows of the imported window, with all
        # OPSD columns visible so the user can sanity-check.
        samples = {
            "hourly": [
                {**row, "_load_mw": mw}
                for _, mw, row in sliced.rows[:24]
            ]
        }
        return PreviewSummary(
            counts={
                "hours": len(sliced.rows),
                "avg_load_mw": int(round(avg)),
                "peak_load_mw": int(round(peak)),
            },
            samples=samples,
            notes=[
                f"{len(sliced.rows)} hourly rows from OPSD column `{sliced.column}`",
                f"Avg {round(avg, 1)} MW, peak {round(peak, 1)} MW.",
            ],
            overlay={},
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        fragment = WorkbookFragment()
        sliced: _Slice | None = result.payload.get("slice")
        ts_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if sliced is None or not sliced.rows:
            fragment.provenance = self._provenance(result, options, ts_now, {"hours": 0})
            return fragment

        load_name = _slug(
            f"{result.region.country_iso}_national_load", fallback="load"
        )

        # Static load row: every OPSD column EXCEPT timestamps/per-country
        # values is dumped as metadata on the Load row so the upstream is
        # never truncated. We keep the first row's metadata since most
        # columns are stable across the window.
        first_raw = sliced.rows[0][2]
        load_row: dict[str, Any] = {
            "name": load_name,
            "country": result.region.country_iso,
            "source": "OPSD",
            "opsd_column": sliced.column,
        }
        for col, val in first_raw.items():
            # Skip the timestamp and the per-country load columns themselves —
            # those flow into the temporal sheet, not the static row.
            if col == _TIMESTAMP_COL or col.endswith("_load_actual_entsoe_transparency"):
                continue
            if val in ("", None):
                continue
            load_row[f"opsd_{col}"] = val
        fragment.sheets["loads"] = [load_row]

        # Temporal sheet: one row per hour, `snapshot` + `<load_name>` columns.
        ts_rows: list[dict[str, Any]] = []
        snapshots: list[str] = []
        for ts, mw, _ in sliced.rows:
            iso_snap = _to_iso_t(ts)
            snapshots.append(iso_snap)
            ts_rows.append({"snapshot": iso_snap, load_name: mw})
        fragment.sheets["loads-p_set"] = ts_rows
        fragment.snapshots = snapshots

        row_counts = {
            "loads": 1,
            "loads-p_set": len(ts_rows),
            "snapshots": len(snapshots),
        }
        fragment.provenance = self._provenance(result, options, ts_now, row_counts)
        return fragment

    def _provenance(
        self,
        result: FetchResult,
        options: ConvertOptions,
        timestamp: str,
        row_counts: dict[str, int],
    ) -> Provenance:
        return Provenance(
            database_id=self.meta.id,
            country_iso=result.region.country_iso,
            country_name=result.region.country_name,
            filters_json=json.dumps(result.filters, sort_keys=True, default=str),
            convert_options_json=json.dumps(options.__dict__, sort_keys=True, default=str),
            fetch_timestamp=timestamp,
            row_counts_json=json.dumps(row_counts, sort_keys=True),
        )


def _to_iso_t(ts: str) -> str:
    """Normalise OPSD's `2019-01-01T00:00:00Z` / `2019-01-01 00:00:00` to the
    ISO-`T` format the frontend's snapshot parsing expects."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1]
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    return s
