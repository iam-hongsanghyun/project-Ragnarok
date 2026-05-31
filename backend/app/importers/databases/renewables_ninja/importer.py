"""Renewables.ninja hourly capacity-factor importer.

Self-contained. No imports from a shared convert/ package. Slug / dedupe /
provenance inlined. Output:

- one row in `generators` per selected tech (`{ISO}_{tech}_profile`) with
  `carrier` set to `Wind` / `Solar` but `p_nom` INTENTIONALLY UNSET — this
  module ships a *profile*, not a sized generator. The user attaches the
  profile to their own generator (via T3) or sets `p_nom` manually.
- N rows in `generators-p_max_pu` covering the requested window with
  `snapshot` + one column per tech generator.
- `WorkbookFragment.snapshots` populated so the merger can union.

Every column the Renewables.ninja CSV ships (electricity, irradiance_*,
temperature, …) is preserved on the per-tech static generator row as
metadata.

No PyPSA defaults are fabricated.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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

_DEFAULT_BASE = "https://www.renewables.ninja/api/data"


def _api_base() -> str:
    return os.environ.get("RAGNAROK_RENEWABLES_NINJA_URL", _DEFAULT_BASE)


_TECH_URL = {
    "wind": "wind",
    "solar": "pv",
}


# ── Slug helper ──────────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def _slug(raw: str | None, fallback: str = "asset") -> str:
    if not raw:
        return fallback
    s = _NAME_RE.sub("_", str(raw).strip()).strip("_")
    return s or fallback


def _dedupe(name: str, taken: set[str]) -> str:
    if name not in taken:
        taken.add(name)
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    final = f"{name}_{i}"
    taken.add(final)
    return final


# ── HTTP ────────────────────────────────────────────────────────────────────


def _http_get_csv(url: str, *, retries: int = 3, sleep: float = 2.0) -> bytes:
    headers = {
        "Accept": "text/csv",
        "User-Agent": os.environ.get(
            "RAGNAROK_RN_UA", "Ragnarok/0.1 (+https://github.com/PyPSA/PyPSA)"
        ),
    }
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (429, 502, 503, 504) and attempt < retries:
                # Honour Retry-After when present.
                ra = exc.headers.get("Retry-After") if exc.headers else None
                pause = float(ra) if (ra and ra.isdigit()) else sleep * attempt
                _log.warning(
                    "Renewables.ninja %s on attempt %d/%d — sleeping %.1fs",
                    exc.code, attempt, retries, pause,
                )
                time.sleep(pause)
                continue
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(sleep * attempt)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Renewables.ninja request failed for an unknown reason")


def _parse_csv(blob: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """RN's CSV starts with a header block ('## ' lines), then a blank line,
    then the column header. We skip the comment block and parse the rest."""
    text = blob.decode("utf-8", errors="replace")
    body_start = 0
    for i, line in enumerate(text.splitlines(keepends=False)):
        if not line.startswith("##") and "," in line and "time" in line.lower():
            body_start = sum(len(l) + 1 for l in text.splitlines(keepends=False)[:i])
            break
    body = text[body_start:]
    reader = csv.DictReader(io.StringIO(body))
    headers = list(reader.fieldnames or [])
    rows = [dict(r) for r in reader]
    return headers, rows


# ── Tech fetch ──────────────────────────────────────────────────────────────


@dataclass
class _TechSeries:
    tech: str
    headers: list[str]
    rows: list[dict[str, str]]


def _fetch_tech(
    tech: str, *, lat: float, lon: float, date_from: str, date_to: str
) -> _TechSeries:
    base = _api_base()
    path = _TECH_URL[tech]
    if tech == "wind":
        qs = urllib.parse.urlencode({
            "lat": lat, "lon": lon,
            "date_from": date_from, "date_to": date_to,
            "capacity": "1", "height": "100",
            "turbine": "Vestas V80 2000",
            "format": "csv",
        })
    else:
        qs = urllib.parse.urlencode({
            "lat": lat, "lon": lon,
            "date_from": date_from, "date_to": date_to,
            "dataset": "merra2",
            "capacity": "1",
            "system_loss": "0.1",
            "tracking": "0",
            "tilt": "35",
            "azim": "180",
            "format": "csv",
        })
    url = f"{base}/{path}?{qs}"
    blob = _http_get_csv(url)
    headers, rows = _parse_csv(blob)
    return _TechSeries(tech=tech, headers=headers, rows=rows)


# ── Database implementation ──────────────────────────────────────────────────


@dataclass
class RenewablesNinjaImporter:
    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult:
        date_from = str(filters.get("date_from") or "2019-01-01")
        date_to = str(filters.get("date_to") or "2019-12-31")
        techs = [str(t).lower() for t in (filters.get("tech") or ["wind", "solar"])]
        techs = [t for t in techs if t in _TECH_URL]
        # Country centroid (`I4` polygon-region path is deferred).
        centroid_x, centroid_y = float(region.polygon.centroid.x), float(region.polygon.centroid.y)
        series: list[_TechSeries] = []
        notes: list[str] = []
        for tech in techs:
            try:
                series.append(_fetch_tech(
                    tech, lat=centroid_y, lon=centroid_x,
                    date_from=date_from, date_to=date_to,
                ))
            except Exception as exc:  # noqa: BLE001
                notes.append(f"Renewables.ninja {tech} fetch failed: {exc}")
        return FetchResult(
            database_id=self.meta.id,
            region=region,
            filters={"date_from": date_from, "date_to": date_to, "tech": techs, **dict(filters)},
            payload={"series": series, "centroid": (centroid_x, centroid_y)},
            notes=notes,
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        series_list: list[_TechSeries] = result.payload.get("series") or []
        if not series_list:
            return PreviewSummary(
                counts={"techs": 0},
                samples={},
                notes=result.notes or ["No Renewables.ninja data."],
                overlay={},
            )
        counts: dict[str, int] = {"techs": len(series_list)}
        samples: dict[str, list[dict[str, Any]]] = {}
        for s in series_list:
            counts[f"hours:{s.tech}"] = len(s.rows)
            samples[s.tech] = [dict(r) for r in s.rows[:24]]
        cx, cy = result.payload.get("centroid", (0.0, 0.0))
        return PreviewSummary(
            counts=counts,
            samples=samples,
            notes=[
                f"{len(series_list)} tech series at centroid ({cy:.2f}, {cx:.2f})",
            ],
            overlay={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [cx, cy]},
                        "properties": {"kind": "centroid", "name": "Renewables.ninja point"},
                    }
                ],
            },
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        fragment = WorkbookFragment()
        series_list: list[_TechSeries] = result.payload.get("series") or []
        ts_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not series_list:
            fragment.provenance = self._provenance(result, options, ts_now, {"generators": 0})
            return fragment

        country_iso = result.region.country_iso
        cx, cy = result.payload.get("centroid", (0.0, 0.0))
        carrier_for = {"wind": "Wind", "solar": "Solar"}

        gen_rows: list[dict[str, Any]] = []
        carrier_rows: list[dict[str, Any]] = []
        used_carriers: set[str] = set()
        taken_gen_names: set[str] = set()
        per_tech_p_max_pu: list[tuple[str, list[dict[str, Any]]]] = []
        all_snapshots: set[str] = set()

        for s in series_list:
            tech_name = _dedupe(
                _slug(f"{country_iso}_{s.tech}_profile", fallback="profile"),
                taken_gen_names,
            )
            carrier = carrier_for[s.tech]
            # Static generator row: carrier + coordinates + EVERY RN
            # column on the FIRST row preserved as metadata (most are
            # constant or per-row, but we don't lose anything).
            gen_row: dict[str, Any] = {
                "name": tech_name,
                "carrier": carrier,
                "x": cx, "y": cy,
                "country": country_iso,
                "source": "Renewables.ninja",
                "rn_tech": s.tech,
            }
            if s.rows:
                first = s.rows[0]
                for col, val in first.items():
                    if val in (None, ""):
                        continue
                    if col in gen_row:
                        continue
                    gen_row[f"rn_{col}"] = val
            gen_rows.append(gen_row)

            if carrier not in used_carriers:
                used_carriers.add(carrier)
                carrier_rows.append({"name": carrier})

            # Temporal rows. RN's `electricity` column is the unit-capacity
            # CF — directly the value PyPSA wants for `p_max_pu`.
            time_col = _pick_time_col(s.headers)
            ts_rows: list[dict[str, Any]] = []
            for raw in s.rows:
                ts = (raw.get(time_col) or "").strip() if time_col else ""
                cf = raw.get("electricity")
                if not ts or cf in (None, ""):
                    continue
                try:
                    cf_f = float(cf)
                except (TypeError, ValueError):
                    continue
                iso_snap = _to_iso_t(ts)
                ts_rows.append({"snapshot": iso_snap, tech_name: cf_f})
                all_snapshots.add(iso_snap)
            per_tech_p_max_pu.append((tech_name, ts_rows))

        if gen_rows:
            fragment.sheets["generators"] = gen_rows
        if carrier_rows:
            fragment.sheets["carriers"] = carrier_rows
        # Merge per-tech temporal slices into a single `generators-p_max_pu`
        # sheet keyed by snapshot.
        if per_tech_p_max_pu and all_snapshots:
            merged: dict[str, dict[str, Any]] = {s: {"snapshot": s} for s in sorted(all_snapshots)}
            for name, rows in per_tech_p_max_pu:
                for r in rows:
                    snap = r["snapshot"]
                    if snap in merged:
                        merged[snap][name] = r[name]
            fragment.sheets["generators-p_max_pu"] = list(merged.values())
            fragment.snapshots = sorted(all_snapshots)

        row_counts = {sheet: len(rows) for sheet, rows in fragment.sheets.items()}
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


def _pick_time_col(headers: list[str]) -> str | None:
    for c in ("time", "local_time", "utc_time"):
        if c in headers:
            return c
    return None


def _to_iso_t(ts: str) -> str:
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1]
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    return s
