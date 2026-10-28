"""Refresh the self-hosted demand database (D2).

    python -m backend.app.importers.demand_db.refresh [--countries DE FR GB_GBN ERCO ...]
        [--years 2019 2020 | 2015-2020] [--sources opsd eia930 entsoe] [--dir PATH]
        [--force] [--dry-run] [--opsd-version 2020-10-06]

Sources (all keyless and redistributable except the optional ENTSO-E step):

* ``opsd``   - Open Power System Data ``time_series_60min_singleindex.csv`` (one ~130 MB file,
  version-pinned, verified against the sha256 in OPSD's ``datapackage.json``).
* ``eia930`` - EIA Form-930 bulk balance files, ``EIA930_BALANCE_<year>_<Jan_Jun|Jul_Dec>.csv``
  (~40 MB each, public domain). robots.txt on www.eia.gov allows ``/electricity/``.
* ``entsoe`` - ENTSO-E Actual Total Load via the Transparency API; runs only when a token is
  configured (``RAGNAROK_SECRET_ENTSOE_KEY`` or the stored ``entsoe_key``). One request per
  country-year, never fan-out.

Re-runnable by construction: every download goes to ``<name>.part`` and is renamed on success;
raw files keep a ``.meta.json`` sidecar (url, sha256, bytes, etag) and are reused when the
upstream ETag / size still match; slices are merged by timestamp and rewritten only when
content changes. A killed run therefore resumes where it stopped. Downloads are sequential
with a pause, retries use exponential backoff with jitter and honour ``Retry-After``.
Per-source failures are reported and do not abort the other sources (exit status 1).

Not idempotent by design: ``retrieved_at`` / ``refresh_log.jsonl`` advance when content changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx
import pandas as pd

from . import catalogue, parsers, store

logger = logging.getLogger("ragnarok.demand_db")

USER_AGENT = "Ragnarok-demand-db/1.0 (+https://github.com/PyPSA/PyPSA; self-hosted snapshot refresh)"
OPSD_BASE = "https://data.open-power-system-data.org/time_series"
OPSD_DEFAULT_VERSION = "2020-10-06"  # latest OPSD release (data ends 2020-09-30)
OPSD_CSV = "time_series_60min_singleindex.csv"
EIA_BASE = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles"
ENTSOE_API = "https://web-api.tp.entsoe.eu/api"
OPEN_FILE_MAX_AGE = timedelta(days=1)  # a still-growing half-year / year is re-checked after this
SEALED_AFTER = timedelta(days=120)  # EIA half-years older than this are re-checked by HEAD only


class DownloadError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# -- HTTP ----------------------------------------------------------------------------------------


class Downloader:
    """Sequential, retrying, streaming downloader. ``transport`` lets tests inject a mock."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 5,
        pause_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        secrets: Iterable[str] = (),
    ) -> None:
        logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs may carry a token
        self._client = httpx.Client(
            transport=transport, follow_redirects=True, headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(connect=20.0, read=120.0, write=30.0, pool=30.0),
        )
        self.max_attempts = max_attempts
        self.pause_seconds = pause_seconds
        self._sleep = sleep
        self._secrets = [s for s in secrets if s]

    def close(self) -> None:
        self._client.close()

    def _mask(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        return text

    def _wait(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(300.0, max(0.0, float(retry_after)))
            except ValueError:
                pass
        return min(60.0, 2.0 ** attempt) * random.uniform(0.5, 1.5)

    def _send(self, method: str, url: str, params: dict[str, Any] | None, dest: Path | None) -> httpx.Response:
        """One logical request with retries. With ``dest`` the body is streamed to it (``.part``)."""
        last = "no attempt"
        for attempt in range(1, self.max_attempts + 1):
            try:
                with self._client.stream(method, url, params=params) as resp:
                    if resp.status_code in (429, 500, 502, 503, 504):
                        last = f"HTTP {resp.status_code}"
                        if attempt < self.max_attempts:
                            self._sleep(self._wait(attempt, resp.headers.get("Retry-After")))
                            continue
                        raise DownloadError(f"{last} for {self._mask(url)} after {attempt} attempts", resp.status_code)
                    if resp.status_code >= 400:
                        raise DownloadError(f"HTTP {resp.status_code} for {self._mask(url)}", resp.status_code)
                    if dest is not None:
                        with dest.open("wb") as fh:
                            for chunk in resp.iter_bytes(1 << 20):
                                fh.write(chunk)
                            fh.flush()
                            os.fsync(fh.fileno())
                    else:
                        resp.read()
                    return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = f"{type(exc).__name__}"
                if attempt < self.max_attempts:
                    self._sleep(self._wait(attempt, None))
                    continue
                raise DownloadError(f"{last} for {self._mask(url)} after {attempt} attempts") from None
        raise DownloadError(f"{last} for {self._mask(url)}")

    def head(self, url: str) -> dict[str, str] | None:
        try:
            r = self._send("HEAD", url, None, None)
        except DownloadError:
            return None
        return {k.lower(): v for k, v in r.headers.items()}

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        r = self._send("GET", url, params, None)
        text = r.text
        # A 200 can still carry an HTML login / error page where data should be.
        return text

    def download(self, url: str, dest: Path) -> dict[str, Any]:
        """Stream ``url`` to ``dest`` via ``dest.part``; returns the sidecar dict."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        try:
            resp = self._send("GET", url, None, part)
            size = part.stat().st_size
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) != size and not resp.headers.get("Content-Encoding"):
                raise DownloadError(f"truncated download of {url}: got {size} of {declared} bytes")
            digest = store.sha256_file(part)
            os.replace(part, dest)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
        if self.pause_seconds:
            self._sleep(self.pause_seconds)
        return {
            "url": url, "fetched_at": store.now_iso(), "bytes": size, "sha256": digest,
            "etag": resp.headers.get("ETag"), "last_modified": resp.headers.get("Last-Modified"),
        }


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def fetch_raw(
    dl: Downloader, url: str, dest: Path, *, immutable: bool = False, force: bool = False,
    max_age: timedelta | None = None, expected_sha256: str | None = None, expect_prefix: bytes | None = None,
) -> tuple[dict[str, Any], bool]:
    """Ensure ``dest`` holds the current upstream file. Returns ``(sidecar, reused)``.

    Reuse when the file and its sidecar agree on size and (for non-immutable files) a HEAD
    shows the same ETag / Content-Length - or the HEAD fails (offline resume). A redownload
    appends the previous sha to the sidecar's ``previous`` list (vintage record).
    """
    side_path = _sidecar(dest)
    side: dict[str, Any] | None = None
    if dest.is_file() and side_path.is_file() and not force:
        try:
            side = json.loads(side_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            side = None
        if side and dest.stat().st_size != side.get("bytes"):
            side = None  # file does not match its record: treat as incomplete
    if side is not None:
        if immutable:
            return side, True
        if max_age is not None:
            fetched = datetime.fromisoformat(side["fetched_at"])
            if datetime.now(timezone.utc) - fetched < max_age:
                return side, True  # fetched recently: do not even HEAD
        head = dl.head(url)
        if head is None:
            return side, True  # offline / HEAD refused: resume with what we have
        same_etag = side.get("etag") and head.get("etag") == side.get("etag")
        same_len = head.get("content-length") and str(side.get("bytes")) == head.get("content-length")
        if same_etag or (same_len and not side.get("etag")):
            return side, True
    new = dl.download(url, dest)
    if expect_prefix is not None:
        with dest.open("rb") as fh:
            head_bytes = fh.read(len(expect_prefix))
        if head_bytes != expect_prefix:
            # HTTP 200 carrying an HTML "not found" / error page instead of the CSV.
            dest.unlink(missing_ok=True)
            raise DownloadError(f"{url} returned a non-CSV body (starts {head_bytes[:20]!r}); treating as not published", 404)
    if expected_sha256 and new["sha256"] != expected_sha256:
        dest.unlink(missing_ok=True)
        raise DownloadError(f"sha256 mismatch for {url}: expected {expected_sha256}, got {new['sha256']}")
    if side and side.get("sha256") != new["sha256"]:
        new["previous"] = [*(side.get("previous") or []), {"sha256": side.get("sha256"), "fetched_at": side.get("fetched_at")}]
    store.atomic_write_json(side_path, new)
    return new, False


def _raw_record(url: str, side: dict[str, Any]) -> dict[str, Any]:
    return {"url": url, "sha256": side.get("sha256"), "bytes": side.get("bytes"), "fetched_at": side.get("fetched_at")}


# -- selection helpers ---------------------------------------------------------------------------


def parse_years(tokens: list[str] | None) -> list[int] | None:
    """``['2019', '2021-2023', '2020,2022']`` -> sorted unique years; ``None`` = no restriction."""
    if not tokens:
        return None
    years: set[int] = set()
    for tok in tokens:
        for part in str(tok).split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                lo, hi = int(a), int(b)
                if hi < lo:
                    raise ValueError(f"bad year range {part!r}")
                years.update(range(lo, hi + 1))
            else:
                years.add(int(part))
    bad = [y for y in years if not 1990 <= y <= 2100]
    if bad:
        raise ValueError(f"implausible years {bad}")
    return sorted(years)


def match_areas(source: str, available: Iterable[str], tokens: list[str] | None) -> list[str]:
    """Which of ``available`` areas the user's ``--countries`` tokens select.

    Tokens are area codes (``DE``, ``GB_GBN``, ``ERCO``) or country codes (``DEU``, ``GB``,
    ``US``/``USA``). For OPSD an exact code wins; otherwise ``GB`` expands to ``GB_*`` zones.
    ``tokens=None`` selects all.
    """
    avail = sorted(set(available))
    if not tokens:
        return avail
    iso3_to_iso2 = {v: k for k, v in catalogue.ISO2_TO_ISO3.items()}
    chosen: set[str] = set()
    for raw in tokens:
        t = raw.strip()
        if not t:
            continue
        if source == "eia930":
            if t.upper() in ("US", "USA"):
                chosen.update(avail)
            elif t.upper() in avail:
                chosen.add(t.upper())
        elif source == "entsoe":
            iso3 = catalogue.ISO2_TO_ISO3.get(t.upper(), t.upper())
            if iso3 in avail:
                chosen.add(iso3)
        else:  # opsd: case-sensitive area codes like 'IE_sem'; accept ISO3 too
            code = iso3_to_iso2.get(t.upper(), t if t in avail else t.upper())
            if code in avail:
                chosen.add(code)
            elif t in avail:
                chosen.add(t)
            else:
                chosen.update(a for a in avail if a.startswith(code + "_"))
    return sorted(chosen)


# -- per-source refresh --------------------------------------------------------------------------


def refresh_opsd(
    dl: Downloader, base: Path, countries: list[str] | None, years: list[int] | None, *,
    version: str = OPSD_DEFAULT_VERSION, force: bool = False, dry_run: bool = False,
) -> list[dict[str, Any]]:
    """One CSV for all areas: download (sha-verified), parse selected areas, write slices."""
    folder = base / "raw" / "opsd" / version
    csv_url = f"{OPSD_BASE}/{version}/{OPSD_CSV}"
    if dry_run:
        return [{"plan": f"download {csv_url}", "areas": countries or "all"}]
    pkg = json.loads(dl.get_text(f"{OPSD_BASE}/{version}/datapackage.json"))
    resource = next((r for r in pkg.get("resources", []) if r.get("path") == OPSD_CSV), None)
    expected = (resource or {}).get("hash")
    if not expected:
        raise parsers.ParseError("OPSD datapackage.json has no hash for the 60-minute CSV (format changed?)")
    csv_path = folder / OPSD_CSV
    side, reused = fetch_raw(dl, csv_url, csv_path, immutable=True, force=force, expected_sha256=expected)
    if reused and side.get("sha256") != expected:
        raise DownloadError(f"cached OPSD file hash {side.get('sha256')} != datapackage {expected}; rerun with --force")
    areas = match_areas("opsd", parsers.opsd_areas(csv_path), countries)
    if not areas:
        return []
    frames = parsers.parse_opsd(csv_path, areas, csv_url)
    out = []
    for area in areas:
        df = frames[area]
        if years is not None:
            df = df[df["timestamp"].dt.year.isin(years)]
        if df.empty:
            logger.warning("opsd/%s: no rows in the requested years", area)
            continue
        out.append(store.write_slice("opsd", area, df, raw_files=[_raw_record(csv_url, side)], base=base))
    return out


def _eia_period(year: int, name: str) -> tuple[date, date]:
    return (date(year, 1, 1), date(year, 6, 30)) if "Jan_Jun" in name else (date(year, 7, 1), date(year, 12, 31))


def refresh_eia930(
    dl: Downloader, base: Path, countries: list[str] | None, years: list[int], *,
    force: bool = False, dry_run: bool = False, today: date | None = None,
) -> list[dict[str, Any]]:
    today = today or datetime.now(timezone.utc).date()
    per_area: dict[str, list[pd.DataFrame]] = {}
    raws: list[dict[str, Any]] = []
    plan: list[dict[str, Any]] = []
    for year in years:
        for name in parsers.eia_file_names(year):
            start, end = _eia_period(year, name)
            if start > today:
                continue  # that half-year has not begun
            url = f"{EIA_BASE}/{name}"
            if dry_run:
                plan.append({"plan": f"download {url}"})
                continue
            open_period = end >= today - SEALED_AFTER
            dest = base / "raw" / "eia930" / name
            try:
                side, _ = fetch_raw(dl, url, dest, force=force, max_age=OPEN_FILE_MAX_AGE if open_period else None,
                                    expect_prefix=b'"Balancing Authority"')
            except DownloadError as exc:
                if exc.status == 404:
                    logger.warning("eia930: %s not published yet (404) - skipped", name)
                    continue
                raise
            raws.append(_raw_record(url, side))
            frames = parsers.parse_eia930(dest, None, url)
            wanted = match_areas("eia930", frames.keys(), countries)
            for area in wanted:
                per_area.setdefault(area, []).append(frames[area])
    if dry_run:
        return plan
    out = []
    for area in sorted(per_area):
        df = pd.concat(per_area[area], ignore_index=True)
        out.append(store.write_slice("eia930", area, df, raw_files=raws, base=base))
    return out


def refresh_entsoe(
    dl: Downloader, base: Path, countries: list[str] | None, years: list[int], token: str, *,
    force: bool = False, dry_run: bool = False, today: date | None = None,
) -> list[dict[str, Any]]:
    from ..databases.entsoe_load import _EIC_BY_ISO

    today = today or datetime.now(timezone.utc).date()
    isos = match_areas("entsoe", _EIC_BY_ISO.keys(), countries)
    out: list[dict[str, Any]] = []
    for iso in isos:
        eic = _EIC_BY_ISO[iso][0]
        frames: list[pd.DataFrame] = []
        raws: list[dict[str, Any]] = []
        for year in years:
            if date(year, 1, 1) > today:
                continue
            # No token in the recorded URL (it is a credential); the request carries it as a param.
            url = (f"{ENTSOE_API}?documentType=A65&processType=A16&outBiddingZone_Domain={eic}"
                   f"&periodStart={year}01010000&periodEnd={year + 1}01010000")
            if dry_run:
                out.append({"plan": f"GET {url}"})
                continue
            dest = base / "raw" / "entsoe" / iso / f"{year}.xml"
            sealed = year < today.year
            xml = _fetch_entsoe_xml(dl, url, dest, token, sealed=sealed, force=force, eic=eic, year=year)
            if xml is None:
                continue
            side = json.loads(_sidecar(dest).read_text(encoding="utf-8"))
            try:
                frames.append(parsers.parse_entsoe_load(xml, url))
            except RuntimeError as exc:
                if parsers.is_no_data_error(exc):
                    logger.info("entsoe/%s %s: no data published", iso, year)
                    continue
                raise
            raws.append(_raw_record(url, side))
        if frames:
            out.append(store.write_slice("entsoe", iso, pd.concat(frames, ignore_index=True), raw_files=raws, base=base))
    return out


def _fetch_entsoe_xml(
    dl: Downloader, url: str, dest: Path, token: str, *, sealed: bool, force: bool, eic: str, year: int,
) -> str | None:
    side_path = _sidecar(dest)
    if dest.is_file() and side_path.is_file() and not force:
        side = json.loads(side_path.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(side["fetched_at"])
        if dest.stat().st_size == side.get("bytes") and (sealed or age < OPEN_FILE_MAX_AGE):
            return dest.read_text(encoding="utf-8")
    try:
        text = dl.get_text(ENTSOE_API, params={
            "securityToken": token, "documentType": "A65", "processType": "A16",
            "outBiddingZone_Domain": eic, "periodStart": f"{year}01010000", "periodEnd": f"{year + 1}01010000",
        })
    except DownloadError as exc:
        if exc.status in (401, 403):
            raise PermissionError("ENTSO-E rejected the API token (401/403)") from None
        raise
    data = text.encode("utf-8")
    store.atomic_write_bytes(dest, data)
    store.atomic_write_json(side_path, {
        "url": url, "fetched_at": store.now_iso(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    })
    return text


# -- orchestration / CLI -------------------------------------------------------------------------

ALL_SOURCES = ("opsd", "eia930", "entsoe")


def default_years(today: date | None = None) -> list[int]:
    y = (today or datetime.now(timezone.utc).date()).year
    return [y - 2, y - 1, y]


def run_refresh(
    *, base: Path, sources: list[str] | None, countries: list[str] | None, years: list[int] | None,
    downloader: Downloader, entsoe_token: str | None, force: bool = False, dry_run: bool = False,
    opsd_version: str = OPSD_DEFAULT_VERSION,
) -> dict[str, Any]:
    """Run the selected sources; returns ``{source: {status, slices|error|note}}``."""
    explicit = bool(sources)
    chosen = list(sources or ALL_SOURCES)
    report: dict[str, Any] = {}
    for src in chosen:
        try:
            if src == "opsd":
                res = refresh_opsd(downloader, base, countries, years, version=opsd_version, force=force, dry_run=dry_run)
            elif src == "eia930":
                res = refresh_eia930(downloader, base, countries, years or default_years(), force=force, dry_run=dry_run)
            elif src == "entsoe":
                if not entsoe_token:
                    report[src] = {"status": "skipped", "note": "no ENTSO-E token configured (RAGNAROK_SECRET_ENTSOE_KEY)"}
                    if explicit:
                        report[src]["status"] = "error"
                    continue
                res = refresh_entsoe(downloader, base, countries, years or default_years(), entsoe_token, force=force, dry_run=dry_run)
            else:
                report[src] = {"status": "error", "error": f"unknown source {src!r}"}
                continue
            report[src] = {"status": "ok", "slices": res}
        except Exception as exc:  # noqa: BLE001 - one source failing must not hide the others
            logger.error("%s failed: %s", src, exc)
            report[src] = {"status": "error", "error": str(exc)}
    return report


def _slice_line(s: dict[str, Any]) -> str:
    if "plan" in s:
        return f"  plan: {s['plan']}"
    flag = "wrote" if s.get("written") else "same "
    return (f"  {flag} {s['key']:<16} rows={s['rows']:>7} {s['coverage_start'][:10]}..{s['coverage_end'][:10]} "
            f"+{s['added']} ~{s['changed']} rejected={sum(s['rejected_rows'].values())}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m backend.app.importers.demand_db.refresh", description=__doc__.split("\n\n")[0])
    ap.add_argument("--countries", nargs="+", help="area / country codes (DE FR GB ERCO PJM ...); default all")
    ap.add_argument("--years", nargs="+", help="years or ranges, e.g. 2019 2021-2023; default: all for OPSD, last 3 for EIA/ENTSO-E")
    ap.add_argument("--sources", nargs="+", choices=ALL_SOURCES, help="default: opsd eia930 (+entsoe when a token is configured)")
    ap.add_argument("--dir", type=Path, help="database folder (default RAGNAROK_DEMAND_DB_DIR or <data root>/demand_db)")
    ap.add_argument("--force", action="store_true", help="re-download even if the cached raw file looks current")
    ap.add_argument("--dry-run", action="store_true", help="print what would be fetched; touch nothing")
    ap.add_argument("--opsd-version", default=OPSD_DEFAULT_VERSION)
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # httpx logs every request URL at INFO, query string included - that would print the ENTSO-E token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        years = parse_years(args.years)
    except ValueError as exc:
        ap.error(str(exc))
    base = args.dir or store.root()
    token = None
    try:
        from ...secrets_store import server_secrets

        token = server_secrets().get("entsoe_key") or None
    except Exception:  # noqa: BLE001 - the secrets store is optional for this CLI
        token = None
    dl = Downloader(secrets=[token] if token else [])
    try:
        report = run_refresh(
            base=base, sources=args.sources, countries=args.countries, years=years, downloader=dl,
            entsoe_token=token, force=args.force, dry_run=args.dry_run, opsd_version=args.opsd_version,
        )
    finally:
        dl.close()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"demand database: {base}")
        for src, res in report.items():
            print(f"{src}: {res['status']}" + (f" - {res.get('error') or res.get('note')}" if res["status"] != "ok" else ""))
            for s in res.get("slices", []):
                print(_slice_line(s))
    return 1 if any(r["status"] == "error" for r in report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
