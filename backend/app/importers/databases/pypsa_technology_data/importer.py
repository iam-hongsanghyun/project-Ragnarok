"""PyPSA technology-data costs importer.

Self-contained. Fetches `costs_{year}.csv` from PyPSA/technology-data and
writes one row per technology into the `carriers` sheet. The technology-data
CSV is the ONE place where cost / efficiency / lifetime / CO2 intensity
columns are populated — every other importer leaves them empty.

The CSV has a wide-or-long shape depending on the version; both have
columns `technology`, `parameter`, `value`, `unit`, `source`. We pivot
the long form into one carrier row per `technology` whose columns are
the parameters (capital_cost, marginal_cost, efficiency, FOM, VOM,
lifetime, CO2 intensity, …), preserving the `unit` / `source` next to
each parameter as auxiliary columns.

No defaults are fabricated. If technology-data doesn't ship a parameter,
the column is absent.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
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

_DEFAULT_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/PyPSA/technology-data/master/outputs/"
    "costs_{year}.csv"
)


def _url_for(year: str) -> str:
    tmpl = os.environ.get("RAGNAROK_TECHDATA_URL_TEMPLATE", _DEFAULT_URL_TEMPLATE)
    return tmpl.format(year=year)


def _local_override() -> Path | None:
    override = os.environ.get("RAGNAROK_TECHDATA_PATH")
    return Path(override).expanduser() if override else None


def _http_get_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "text/csv",
            "User-Agent": os.environ.get(
                "RAGNAROK_TECHDATA_UA",
                "Ragnarok/0.1 (+https://github.com/PyPSA/PyPSA)",
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


# ── Carrier mapping ─────────────────────────────────────────────────────────

_CARRIER_MAP_PATH = Path(__file__).resolve().parent / "carrier_map.json"


def _carrier_mapping() -> dict[str, str]:
    raw = json.loads(_CARRIER_MAP_PATH.read_text())
    return dict(raw.get("tech_to_carrier", {}))


def _map_tech(tech: str, mapping: dict[str, str]) -> str:
    """Return the Ragnarok carrier name for a technology-data tech-id.
    Falls back to the tech-id itself (preserves the long tail of techs)."""
    key = tech.strip()
    return mapping.get(key, key)


# ── CSV parsing (long-form: technology, parameter, value, unit, source) ─────


@dataclass
class _Param:
    parameter: str
    value: str
    unit: str
    source: str


def _parse_costs(blob: bytes) -> dict[str, list[_Param]]:
    text = blob.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out: dict[str, list[_Param]] = {}
    for row in reader:
        tech = (row.get("technology") or "").strip()
        param = (row.get("parameter") or "").strip()
        value = (row.get("value") or "").strip()
        if not tech or not param:
            continue
        out.setdefault(tech, []).append(
            _Param(
                parameter=param,
                value=value,
                unit=(row.get("unit") or "").strip(),
                source=(row.get("source") or "").strip(),
            )
        )
    return out


# ── Database implementation ──────────────────────────────────────────────────


@dataclass
class PyPSATechnologyDataImporter:
    meta: DatabaseMeta

    def fetch(self, region: Region, filters: dict[str, Any]) -> FetchResult:
        year = str(filters.get("year") or "2030")
        try:
            override = _local_override()
            if override is not None and override.exists():
                blob = override.read_bytes()
            else:
                blob = _http_get_bytes(_url_for(year))
        except Exception as exc:  # noqa: BLE001
            return FetchResult(
                database_id=self.meta.id,
                region=region,
                filters={"year": year, **dict(filters)},
                payload={"techs": None, "year": year},
                notes=[f"technology-data fetch failed: {exc}"],
            )
        techs = _parse_costs(blob)
        return FetchResult(
            database_id=self.meta.id,
            region=region,
            filters={"year": year, **dict(filters)},
            payload={"techs": techs, "year": year},
        )

    def preview(self, result: FetchResult) -> PreviewSummary:
        techs = result.payload.get("techs") or {}
        if not techs:
            return PreviewSummary(
                counts={"technologies": 0},
                samples={},
                notes=result.notes or ["No technology-data rows."],
                overlay={},
            )
        # Sample one tech's full parameter set for the preview.
        sample_tech = next(iter(techs))
        sample_rows = [
            {"parameter": p.parameter, "value": p.value, "unit": p.unit, "source": p.source}
            for p in techs[sample_tech]
        ]
        return PreviewSummary(
            counts={
                "technologies": len(techs),
                "total_parameters": sum(len(v) for v in techs.values()),
            },
            samples={f"{sample_tech} parameters": sample_rows},
            notes=[
                f"{len(techs)} technologies for year {result.payload.get('year')}",
            ],
            overlay={},
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        fragment = WorkbookFragment()
        techs = result.payload.get("techs") or {}
        ts_now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not techs:
            fragment.provenance = self._provenance(
                result, options, ts_now, {"carriers": 0}
            )
            return fragment

        mapping = _carrier_mapping()
        carrier_rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for tech_id, params in techs.items():
            carrier_name = _map_tech(tech_id, mapping)
            if carrier_name in seen:
                # Same carrier may be hit by multiple tech-ids (e.g. CCGT
                # and OCGT both → Gas). Keep the first; the user can split
                # in Build if they want per-tech rows.
                continue
            seen.add(carrier_name)
            row: dict[str, Any] = {
                "name": carrier_name,
                "tech_data_year": result.payload.get("year"),
                "tech_data_source": tech_id,
                "source": "PyPSA technology-data",
            }
            for p in params:
                if p.value == "":
                    continue
                row[p.parameter] = _maybe_number(p.value)
                if p.unit:
                    row[f"{p.parameter}_unit"] = p.unit
                if p.source:
                    row[f"{p.parameter}_source"] = p.source
            carrier_rows.append(row)
        if carrier_rows:
            fragment.sheets["carriers"] = carrier_rows
        row_counts = {"carriers": len(carrier_rows)}
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


def _maybe_number(s: str) -> Any:
    """Best-effort numeric coercion — keeps the cell number-typed when the
    upstream value parses, otherwise leaves it as a string."""
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return int(s)
    except ValueError:
        return s
