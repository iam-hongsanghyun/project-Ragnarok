"""Combine the per-dataset results of one source into a single aligned fetch.

When a user multi-selects datasets of a source (Country → Database → Datasets)
the router fetches each dataset and folds the results together here, into one
``WorkbookFragment`` (+ one ``PreviewSummary``). Because the datasets of a
source share the same bus-derived naming and are fetched in one request, the
combined output is internally consistent — PyPSA-ready — by construction.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .protocol import PreviewSummary, Provenance, WorkbookFragment

_CARRIERS = "carriers"


def _is_temporal(sheet: str, rows: list[dict[str, Any]]) -> bool:
    """PyPSA ``<component>-<attr>`` sheet carrying a ``snapshot`` column."""
    return "-" in sheet and any("snapshot" in r for r in rows)


def combine_fragments(
    fragments: list[WorkbookFragment],
    *,
    source_id: str,
    country_iso: str,
    country_name: str,
    filters: dict[str, Any],
    dataset_ids: list[str],
) -> WorkbookFragment:
    """Fold dataset fragments into one. Static sheets concatenate, ``carriers``
    unions by name, temporal sheets merge per-snapshot (combining columns), and
    snapshots take the sorted union. One provenance row summarises the batch.
    """
    out = WorkbookFragment()
    snapshots: set[str] = set()

    for frag in fragments:
        for sheet, rows in frag.sheets.items():
            if not rows:
                continue
            if sheet == _CARRIERS:
                existing = out.sheets.setdefault(sheet, [])
                names = {str(r.get("name")) for r in existing}
                for r in rows:
                    name = str(r.get("name"))
                    if name not in names:
                        existing.append(dict(r))
                        names.add(name)
            elif _is_temporal(sheet, rows):
                existing = out.sheets.setdefault(sheet, [])
                by_snap: dict[Any, dict[str, Any]] = {
                    r.get("snapshot"): r for r in existing
                }
                for r in rows:
                    snap = r.get("snapshot")
                    if snap in by_snap:
                        by_snap[snap].update(
                            {k: v for k, v in r.items() if k != "snapshot"}
                        )
                    else:
                        nr = dict(r)
                        existing.append(nr)
                        by_snap[snap] = nr
            else:
                out.sheets.setdefault(sheet, []).extend(dict(r) for r in rows)
        for s in frag.snapshots or []:
            snapshots.add(s)

    if snapshots:
        out.snapshots = sorted(snapshots)

    row_counts = {k: len(v) for k, v in out.sheets.items()}
    out.provenance = Provenance(
        database_id=source_id,
        country_iso=country_iso,
        country_name=country_name,
        filters_json=json.dumps(filters, sort_keys=True, default=str),
        convert_options_json=json.dumps(
            {"datasets": dataset_ids}, sort_keys=True, default=str
        ),
        fetch_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        row_counts_json=json.dumps(row_counts, sort_keys=True, default=str),
    )
    return out


def combine_previews(
    fragment: WorkbookFragment, previews: list[PreviewSummary]
) -> PreviewSummary:
    """Build one preview for the batch: headline counts read from the combined
    fragment (authoritative — so snapshots are the union, generators the total),
    carrier/voltage breakdowns + samples + notes merged from the per-dataset
    previews, and the first map overlay (the network's bus points)."""
    counts: dict[str, int] = {}
    for key in ("buses", "loads", "generators", "lines", "transformers", "links"):
        if fragment.sheets.get(key):
            counts[key] = len(fragment.sheets[key])
    if fragment.snapshots:
        counts["snapshots"] = len(fragment.snapshots)

    for p in previews:
        for k, v in p.counts.items():
            if k.startswith("carrier:") or k.startswith("voltage:"):
                if isinstance(v, (int, float)):
                    counts[k] = counts.get(k, 0) + int(v)

    notes: list[str] = []
    samples: dict[str, list[dict[str, Any]]] = {}
    overlay: dict[str, Any] = {}
    for p in previews:
        notes.extend(p.notes)
        for k, v in p.samples.items():
            samples.setdefault(k, []).extend(v)
        if not overlay.get("features") and p.overlay.get("features"):
            overlay = p.overlay

    return PreviewSummary(counts=counts, samples=samples, notes=notes, overlay=overlay)
