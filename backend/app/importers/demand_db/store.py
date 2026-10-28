"""Storage for the self-hosted demand database (D2): slices, manifest, validation.

Layout under :func:`root` (``RAGNAROK_DEMAND_DB_DIR``, default ``<data root>/demand_db``)::

    manifest.json                    one entry per slice (below); written atomically
    refresh_log.jsonl                append-only: what each refresh changed (the vintage record)
    slices/<source>/<area>.parquet   columns: timestamp (UTC, hour-beginning), load_mw, source_url
    raw/<source>/...                 untouched downloads + ``.meta.json`` sidecars (see refresh.py)

Rules this module enforces:

* every write goes to a temp file in the same directory, then ``os.replace`` - an interrupted
  run leaves the previous file, never a half-written one that looks complete;
* a frame is validated *before* it is written (unique, hour-aligned, finite, non-negative,
  plausible, and not mostly rejected - a schema shift fails loudly instead of storing junk);
* merging new rows over an existing slice records how many existing values changed, so a
  revised figure is visible in ``refresh_log.jsonl`` instead of silently replaced;
* each row keeps the ``source_url`` it came from.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ...data_root import data_root
from . import catalogue

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
LOG_NAME = "refresh_log.jsonl"
MAX_PLAUSIBLE_MW = 1_000_000.0  # > the largest national system (~1.1 TW is not hourly load of one area)
MIN_YEAR_ROWS = 24 * 28
MAX_REJECT_FRACTION = 0.2  # more than this rejected => treat as schema drift, not noise
COLUMNS = ["timestamp", "load_mw", "source_url"]


class SchemaDriftError(ValueError):
    """Too many rows failed validation - the upstream format probably changed."""


def root() -> Path:
    named = os.environ.get("RAGNAROK_DEMAND_DB_DIR", "").strip()
    return Path(named).expanduser() if named else data_root() / "demand_db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- atomic writes ------------------------------------------------------------------------------


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the snapshot is meant to be shared
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_bytes(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))


# -- manifest -----------------------------------------------------------------------------------


def _empty_manifest() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "generated_at": None, "slices": {}}


def load_manifest(base: Path | None = None) -> dict[str, Any]:
    path = (base or root()) / MANIFEST_NAME
    if not path.is_file():
        return _empty_manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_manifest()
    if not isinstance(data, dict) or not isinstance(data.get("slices"), dict):
        return _empty_manifest()
    return data


def slice_key(source: str, area: str) -> str:
    return f"{source}/{area}"


def split_key(key: str) -> tuple[str, str]:
    source, _, area = key.partition("/")
    if source not in catalogue.SOURCES or not catalogue.valid_area(area):
        raise KeyError(f"invalid demand-db series key {key!r} (expected '<source>/<area>')")
    return source, area


def slice_path(source: str, area: str, base: Path | None = None) -> Path:
    if source not in catalogue.SOURCES or not catalogue.valid_area(area):
        raise KeyError(f"invalid demand-db series {source}/{area}")
    return (base or root()) / "slices" / source / f"{area}.parquet"


# -- validation ---------------------------------------------------------------------------------


def validate_frame(df: pd.DataFrame, *, label: str = "slice") -> tuple[pd.DataFrame, dict[str, int]]:
    """Validate and clean a candidate slice; returns ``(clean_frame, rejected_by_reason)``.

    Required columns: ``timestamp`` (datetime, UTC), ``load_mw`` (number), ``source_url``.
    Rejects NaT / non-finite / negative / implausible (> ``MAX_PLAUSIBLE_MW``) values,
    timestamps not on the hour, and duplicate timestamps (last one wins). Raises
    :class:`SchemaDriftError` when the columns are wrong or more than ``MAX_REJECT_FRACTION`` of
    a non-trivial frame is rejected.
    """
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise SchemaDriftError(f"{label}: missing columns {missing}")
    out = df[COLUMNS].copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    out["load_mw"] = pd.to_numeric(out["load_mw"], errors="coerce")
    n0 = len(out)
    rejected: dict[str, int] = {}

    def drop(mask: pd.Series, reason: str) -> None:
        nonlocal out
        k = int(mask.sum())
        if k:
            rejected[reason] = rejected.get(reason, 0) + k
            out = out[~mask]

    drop(out["timestamp"].isna(), "bad_timestamp")
    drop(~np.isfinite(out["load_mw"].to_numpy(dtype=float)) | out["load_mw"].isna(), "non_finite")
    drop(out["load_mw"] < 0, "negative")
    drop(out["load_mw"] > MAX_PLAUSIBLE_MW, "implausible")
    drop((out["timestamp"].dt.minute != 0) | (out["timestamp"].dt.second != 0), "not_on_the_hour")
    out = out.sort_values("timestamp", kind="stable")
    drop(out["timestamp"].duplicated(keep="last"), "duplicate_timestamp")
    total_rejected = sum(rejected.values())
    if n0 >= 100 and total_rejected / n0 > MAX_REJECT_FRACTION:
        raise SchemaDriftError(f"{label}: {total_rejected}/{n0} rows rejected {rejected}")
    out["load_mw"] = out["load_mw"].astype("float64")
    out["source_url"] = out["source_url"].astype(str)
    return out.reset_index(drop=True), rejected


# -- slices -------------------------------------------------------------------------------------


def read_slice(
    key: str, year_from: int | None = None, year_to: int | None = None, base: Path | None = None
) -> pd.DataFrame:
    """Rows of one slice (UTC hour-beginning) within ``year_from..year_to`` inclusive (UTC years)."""
    source, area = split_key(key)
    path = slice_path(source, area, base)
    if not path.is_file():
        raise FileNotFoundError(f"no demand-db slice {key!r}; run the refresh CLI")
    df = pd.read_parquet(path)
    ts = pd.to_datetime(df["timestamp"], utc=True)
    df["timestamp"] = ts
    if year_from is not None:
        df = df[ts >= pd.Timestamp(year=int(year_from), month=1, day=1, tz="UTC")]
    if year_to is not None:
        df = df[df["timestamp"] < pd.Timestamp(year=int(year_to) + 1, month=1, day=1, tz="UTC")]
    return df.reset_index(drop=True)


def _frame_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    return len(a) == len(b) and bool(
        (a["timestamp"].to_numpy() == b["timestamp"].to_numpy()).all()
        and np.array_equal(a["load_mw"].to_numpy(), b["load_mw"].to_numpy())
        and (a["source_url"].astype(str).to_numpy() == b["source_url"].astype(str).to_numpy()).all()
    )


def write_slice(
    source: str,
    area: str,
    new_rows: pd.DataFrame,
    *,
    raw_files: list[dict[str, Any]],
    base: Path | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Validate ``new_rows``, merge over the stored slice, write atomically, update the manifest.

    Idempotent: re-running with the same rows leaves the slice file untouched. Returns the
    manifest entry plus ``added`` / ``changed`` / ``unchanged`` counters (``changed`` = existing
    timestamps whose value differs - an upstream revision, also appended to the refresh log).
    """
    base = base or root()
    key = slice_key(source, area)
    clean, rejected = validate_frame(new_rows, label=key)
    if clean.empty:
        raise SchemaDriftError(f"{key}: no valid rows")
    path = slice_path(source, area, base)
    old: pd.DataFrame | None = None
    if path.is_file():
        old = pd.read_parquet(path)
        old["timestamp"] = pd.to_datetime(old["timestamp"], utc=True)
    if old is not None and len(old):
        both = old.merge(clean[["timestamp", "load_mw"]], on="timestamp", suffixes=("_old", "_new"))
        changed = int((~np.isclose(both["load_mw_old"], both["load_mw_new"], rtol=0, atol=1e-9)).sum())
        merged = pd.concat([old[~old["timestamp"].isin(clean["timestamp"])], clean], ignore_index=True)
        merged = merged.sort_values("timestamp", kind="stable").reset_index(drop=True)
        added = int(len(merged) - len(old))
    else:
        changed, merged, added = 0, clean, len(clean)

    manifest = load_manifest(base)
    prev_entry = manifest["slices"].get(key)
    unchanged_file = (
        old is not None and prev_entry is not None and added == 0 and changed == 0
        and _frame_equal(old.sort_values("timestamp").reset_index(drop=True), merged)
    )
    if not unchanged_file:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        os.close(fd)
        try:
            merged.to_parquet(tmp, index=False, compression="zstd")
            os.chmod(tmp, 0o644)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    ts = merged["timestamp"]
    entry = {
        "key": key,
        "source": source,
        "area": area,
        "label": catalogue.area_label(source, area),
        "iso3": catalogue.area_iso3(source, area),
        "primary": catalogue.is_primary(source, area),
        "unit": catalogue.UNIT,
        "timezone": catalogue.TIMEZONE,
        "timestamp_convention": catalogue.TIMESTAMP_CONVENTION,
        "measure": catalogue.SOURCES[source]["measure"],
        "licence": catalogue.SOURCES[source]["licence"],
        "licence_url": catalogue.SOURCES[source]["licence_url"],
        "attribution": catalogue.SOURCES[source]["attribution"],
        "file": str(path.relative_to(base)),
        "coverage_start": ts.min().strftime("%Y-%m-%dT%H:00:00Z"),
        "coverage_end": ts.max().strftime("%Y-%m-%dT%H:00:00Z"),
        # Years with >= 4 weeks of rows: EIA half-year files are cut in local time, so a refresh
        # of one year spills a few hours into the neighbouring UTC year - not a covered year.
        "years": sorted(int(y) for y, n in ts.dt.year.value_counts().items() if n >= MIN_YEAR_ROWS),
        "rows": int(len(merged)),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "retrieved_at": (prev_entry or {}).get("retrieved_at") if unchanged_file else (retrieved_at or now_iso()),
        "raw_files": _merge_raw(((prev_entry or {}).get("raw_files") or []), raw_files),
        "rejected_rows": {k: int(v) for k, v in rejected.items()},
        "schema_version": SCHEMA_VERSION,
    }
    manifest["slices"][key] = entry
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["generated_at"] = now_iso()
    atomic_write_json(base / MANIFEST_NAME, manifest)
    result = {**entry, "added": added, "changed": changed, "written": not unchanged_file}
    if not unchanged_file:
        _append_log(base, {"at": now_iso(), "key": key, "added": added, "changed": changed,
                           "rows": entry["rows"], "sha256": entry["sha256"],
                           "raw": [r.get("sha256") for r in raw_files]})
    return result


def _merge_raw(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url = {r["url"]: r for r in old if isinstance(r, dict) and "url" in r}
    for r in new:
        by_url[r["url"]] = r
    return [by_url[u] for u in sorted(by_url)]


def _append_log(base: Path, record: dict[str, Any]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    with (base / LOG_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


# -- coverage / lookup --------------------------------------------------------------------------


def coverage(base: Path | None = None) -> dict[str, Any]:
    """Public view of the manifest (what a UI / agent needs): sources + slices, no file hashes of raw."""
    base = base or root()
    m = load_manifest(base)
    slices = []
    for key in sorted(m["slices"]):
        e = m["slices"][key]
        slices.append({k: e[k] for k in (
            "key", "source", "area", "label", "iso3", "primary", "unit", "timezone",
            "timestamp_convention", "coverage_start", "coverage_end", "years", "rows", "bytes",
            "sha256", "retrieved_at", "licence", "attribution",
        ) if k in e})
    return {
        "dir": str(base),
        "schema_version": m.get("schema_version"),
        "generated_at": m.get("generated_at"),
        "unit": catalogue.UNIT,
        "timezone": catalogue.TIMEZONE,
        "timestamp_convention": catalogue.TIMESTAMP_CONVENTION,
        "sources": {
            sid: {k: v for k, v in info.items()} | {"slices": sum(1 for s in slices if s["source"] == sid)}
            for sid, info in catalogue.SOURCES.items()
        },
        "slices": slices,
    }


def resolve_key(
    series: str | None, country_iso: str | None, year_from: int, year_to: int, base: Path | None = None
) -> str:
    """An explicit ``source/area`` key, or the best national series for ``country_iso``.

    'Best' = most hours inside ``year_from..year_to``; ties go to ENTSO-E, then OPSD, then EIA
    (fresher/more direct first).
    """
    manifest = load_manifest(base)["slices"]
    if series and series != "auto":
        if series not in manifest:
            known = ", ".join(sorted(manifest)) or "none - run the refresh CLI"
            raise KeyError(f"series {series!r} not in the demand database (have: {known})")
        return series
    iso = (country_iso or "").upper()
    cands = [e for e in manifest.values() if e.get("iso3") == iso and e.get("primary")]
    if not cands:
        raise KeyError(f"no demand series for country {iso or '?'} in the demand database")
    order = {"entsoe": 0, "opsd": 1, "eia930": 2}

    def hours(e: dict[str, Any]) -> int:
        years = [y for y in e.get("years", []) if year_from <= y <= year_to]
        return len(years)

    cands.sort(key=lambda e: (-hours(e), order.get(e["source"], 9), e["area"]))
    return cands[0]["key"]
