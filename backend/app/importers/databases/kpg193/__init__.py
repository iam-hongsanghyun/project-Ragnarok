"""KPG193 — Korean Power Grid 193-bus reference network.

Python backend port of the browser importer (frontend
``src/lib/importers/kpg193/{meta,fetch,parse,convert}.ts``). Faithful
translation — the algorithm is preserved exactly; only the runtime
plumbing changes (``ctx.http`` instead of ``fetch``, stdlib ``csv``
instead of PapaParse).

The fetch step DISCOVERS the available versions and renewable years from
the GitHub Contents API at request time — no hardcoded paths — so as
upstream adds new versions (``kpg193_v2_0``, …) or new renewable
snapshots (2023, 2024, …) they show up automatically. The user can pin a
specific version / year via the filters; the default ``latest`` lets the
discovery pick the newest available.

Two GitHub URL forms are in use:

  • Contents API (JSON listing):
      https://api.github.com/repos/agm-center/kpg-testgrid/contents/<path>
  • Raw file:
      https://raw.githubusercontent.com/agm-center/kpg-testgrid/main/<path>
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

from ...context import ImportContext
from ...protocol import (
    ConvertOptions,
    Database,
    DatabaseMeta,
    FetchResult,
    Filter,
    PreviewSummary,
    Provenance,
    Region,
    WorkbookFragment,
)

# ── Upstream repo ─────────────────────────────────────────────────────────────

REPO_OWNER = "agm-center"
REPO_NAME = "kpg-testgrid"
REPO_BRANCH = "main"


def _contents_url(path: str = "") -> str:
    base = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents"
    return f"{base}/{path}" if path else base


def _raw_url(path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/"
        f"{REPO_BRANCH}/{path}"
    )


# ── MATPOWER column schemas (mirror parse.ts / build_kpg193_pypsa.py) ────────

BUS_COLUMNS = [
    "bus_i", "type", "Pd", "Qd", "Gs", "Bs", "area",
    "Vm", "Va", "baseKV", "zone", "Vmax", "Vmin",
]

GEN_COLUMNS = [
    "bus", "Pg", "Qg", "Qmax", "Qmin", "Vg", "mBase", "status",
    "Pmax", "Pmin", "Pc1", "Pc2", "Qc1min", "Qc1max", "Qc2min", "Qc2max",
    "ramp_agc", "ramp_10", "ramp_30", "ramp_q", "apf",
]

BRANCH_COLUMNS = [
    "fbus", "tbus", "r", "x", "b",
    "rateA", "rateB", "rateC",
    "ratio", "angle", "status", "angmin", "angmax",
]

DCLINE_COLUMNS = [
    "f_bus", "t_bus", "br_status", "Pf", "Pt", "Qf", "Qt", "Vf", "Vt",
    "Pmin", "Pmax", "QminF", "QmaxF", "QminT", "QmaxT", "loss0", "loss1",
]

GENCOST_COLUMNS = [
    "model", "startup", "shutdown", "n", "c2", "c1", "c0",
]

GENTHERMAL_COLUMNS = [
    "type_thermal", "UT", "DT", "inistate", "initialpower",
    "ramp_up", "ramp_down", "startup_limit", "shutdown_limit",
    "startup1", "startup2", "startup3",
    "startupdelay1", "startupdelay2", "startupdelay3",
]


# ── MATPOWER `.m` block parser (port of parse.ts) ────────────────────────────


def extract_scalar(text: str, key: str) -> str:
    """Find the first ``mpc.<key> = <value>;`` and return the right-hand
    side as a string (with surrounding quotes stripped). Raises if missing.
    """
    marker = f"mpc.{key} ="
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith(marker):
            continue
        rhs = line[len(marker):].strip()
        if rhs.endswith(";"):
            rhs = rhs[:-1]
        rhs = rhs.strip()
        if rhs.startswith("'"):
            rhs = rhs[1:]
        if rhs.endswith("'"):
            rhs = rhs[:-1]
        return rhs
    raise ValueError(f"MATPOWER scalar not found: mpc.{key}")


def extract_block_lines(text: str, key: str) -> list[str]:
    """Find ``mpc.<key> = [ ... ];`` and return the inner lines (everything
    between the opening bracket and the closing ``];``). Returns ``[]`` when
    the block is absent — older case files may not carry ``mpc.dcline`` etc.
    """
    marker = f"mpc.{key} = ["
    start = text.find(marker)
    if start == -1:
        return []
    end = text.find("];", start)
    if end == -1:
        return []
    block = text[start:end]
    block_lines = block.split("\n")
    # Drop the first line — it's the `mpc.<key> = [` line itself.
    return block_lines[1:]


def parse_matrix_lines(lines: list[str]) -> list[dict[str, Any]]:
    """Parse the inner lines of a block into ``{values, comment}`` rows.

    Values are numeric (NaN for unparseable tokens, although real MATPOWER
    files are clean). Comments are everything after the first ``%`` on the
    row's data line.
    """
    rows: list[dict[str, Any]] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("%"):
            continue  # section-level comment, skip

        pct_idx = line.find("%")
        data_part = (line if pct_idx == -1 else line[:pct_idx])
        data_part = data_part.replace(";", " ").strip()
        if not data_part:
            continue
        comment = "" if pct_idx == -1 else line[pct_idx + 1:].strip()

        tokens = data_part.split()
        values: list[float] = []
        for t in tokens:
            try:
                v = float(t)
            except ValueError:
                v = math.nan
            values.append(v if math.isfinite(v) else math.nan)
        rows.append({"values": values, "comment": comment})
    return rows


def parse_matrix(
    lines: list[str], columns: list[str], comment_column: str
) -> list[dict[str, Any]]:
    """Wrap ``parse_matrix_lines`` with a named-column projection so
    downstream code can read ``row["Pmax"]`` instead of ``row["values"][8]``.
    """
    parsed = parse_matrix_lines(lines)
    out: list[dict[str, Any]] = []
    for row in parsed:
        rec: dict[str, Any] = {}
        vals: list[float] = row["values"]
        for i, col in enumerate(columns):
            rec[col] = vals[i] if i < len(vals) else math.nan
        rec[comment_column] = row["comment"]
        out.append(rec)
    return out


# ── Numeric helpers (mirror JS Number(...) || 0 semantics) ───────────────────


def _num(v: Any) -> float:
    """JS ``Number(v) || 0`` — NaN/None/unparseable → 0.0."""
    if v is None or v == "":
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f) or f == 0:
        return 0.0
    return f


def _int_str(v: Any) -> str:
    """JS ``String(Number(v))`` for an integer-valued field."""
    return str(int(round(_num(v))))


# ── Version / renewable-year discovery (port of fetch.ts) ────────────────────


def _compare_version_tag(a: str, b: str) -> int:
    """Compare semver-ish version strings like "v1_5" / "v2_0" / "1.5"."""

    def norm(s: str) -> list[int]:
        s = re.sub(r"^v", "", s, flags=re.IGNORECASE)
        s = s.replace("_", ".")
        parts: list[int] = []
        for p in s.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return parts

    av = norm(a)
    bv = norm(b)
    n = max(len(av), len(bv))
    for i in range(n):
        ai = av[i] if i < len(av) else 0
        bi = bv[i] if i < len(bv) else 0
        diff = ai - bi
        if diff != 0:
            return diff
    return 0


class _VersionKey:
    """Sort key wrapping ``_compare_version_tag`` so ``list.sort`` matches
    the TypeScript ``versions.sort(compareVersionTag(...))`` ordering."""

    __slots__ = ("value",)

    def __init__(self, version_dir: str) -> None:
        self.value = re.sub(r"^kpg193_", "", version_dir)

    def __lt__(self, other: "_VersionKey") -> bool:
        return _compare_version_tag(self.value, other.value) < 0


async def _list_contents(ctx: ImportContext, path: str = "") -> list[dict[str, Any]]:
    body = await ctx.http.get_json(_contents_url(path))
    if not isinstance(body, list):
        msg = ""
        if isinstance(body, dict):
            msg = str(body.get("message") or "unknown")
        raise RuntimeError(
            f"KPG193 listing returned non-array for {path or '<root>'}: "
            f"{msg or 'unknown'}"
        )
    return body


async def _discover_versions(ctx: ImportContext) -> list[str]:
    """Return the ``kpg193_v*`` directory names sorted ascending by version."""
    root = await _list_contents(ctx)
    versions = [
        e["name"]
        for e in root
        if e.get("type") == "dir"
        and re.match(r"^kpg193_v", str(e.get("name", "")), flags=re.IGNORECASE)
    ]
    versions.sort(key=_VersionKey)
    return versions


async def _discover_renewable_years(ctx: ImportContext, version_dir: str) -> list[int]:
    """Return the available renewable-year integers inside a version dir."""
    entries = await _list_contents(ctx, f"{version_dir}/renewables_capacity")
    years: set[int] = set()
    for e in entries:
        m = re.search(r"_generators_(\d{4})\.csv$", str(e.get("name", "")))
        if m:
            years.add(int(m.group(1)))
    return sorted(years)


async def _resolve_paths(
    ctx: ImportContext, filters: dict[str, Any]
) -> dict[str, Any]:
    """Resolve user filter values to actual repo paths, using discovery for
    any value the user left at ``latest``. Raises if the repo is empty / the
    pinned version doesn't exist / the pinned year doesn't exist.
    """
    versions = await _discover_versions(ctx)
    if not versions:
        raise RuntimeError(
            "KPG193: no kpg193_v* directories found in the upstream repo"
        )

    requested_version = str(filters.get("version") or "latest").strip()
    if requested_version in ("latest", ""):
        version_dir = versions[-1]
    else:
        # Accept either "v1_5" or "kpg193_v1_5".
        wanted = (
            requested_version
            if requested_version.startswith("kpg193_")
            else f"kpg193_{requested_version}"
        )
        match = next(
            (v for v in versions if v.lower() == wanted.lower()), None
        )
        if match is None:
            raise RuntimeError(
                f'KPG193: version "{requested_version}" not found. '
                f"Available: {', '.join(versions)}"
            )
        version_dir = match

    years = await _discover_renewable_years(ctx, version_dir)
    requested_year = str(filters.get("renewable_year") or "latest").strip()
    if requested_year in ("latest", ""):
        renewable_year = years[-1] if years else 0
    else:
        try:
            wanted_year = int(requested_year)
        except ValueError:
            wanted_year = 0
        if wanted_year not in years:
            raise RuntimeError(
                f'KPG193: renewable year "{requested_year}" not found in '
                f"{version_dir}. Available: {', '.join(str(y) for y in years)}"
            )
        renewable_year = wanted_year

    version_tag = re.sub(r"^kpg193_", "", version_dir)
    # The MATPOWER .m file is named KPG193_ver<tag>.m using the tag form
    # without the leading "v" (e.g. "KPG193_ver1_5.m").
    mat_file_tag = re.sub(r"^v", "", version_tag, flags=re.IGNORECASE)
    return {
        "version_dir": version_dir,
        "version_tag": version_tag,
        "renewable_year": renewable_year,
        "matpower_path": f"{version_dir}/network/m/KPG193_ver{mat_file_tag}.m",
        "bus_location_path": f"{version_dir}/network/location/bus_location.csv",
        "solar_path": (
            f"{version_dir}/renewables_capacity/solar_generators_{renewable_year}.csv"
        ),
        "wind_path": (
            f"{version_dir}/renewables_capacity/wind_generators_{renewable_year}.csv"
        ),
        "hydro_path": (
            f"{version_dir}/renewables_capacity/hydro_generators_{renewable_year}.csv"
        ),
    }


# ── Bus location CSV (port of convert.ts parseBusLocation) ───────────────────


def _strip_bom(key: str) -> str:
    return key.replace("﻿", "").strip()


def _parse_bus_location(csv_text: str) -> dict[int, dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    out: dict[int, dict[str, Any]] = {}
    for raw in reader:
        norm: dict[str, str] = {}
        for k, v in raw.items():
            if k is None:
                continue
            norm[_strip_bom(k)] = ("" if v is None else str(v)).strip()
        bus_raw = norm.get("bus_id") or norm.get("bus_ID") or ""
        try:
            bus_id = int(float(bus_raw))
        except (TypeError, ValueError):
            continue
        out[bus_id] = {
            "bus_id": bus_id,
            "latitude": _parse_float(norm.get("Latitude") or norm.get("latitude")),
            "longitude": _parse_float(norm.get("Longitude") or norm.get("longitude")),
            "name_korean": norm.get("name_Korean") or norm.get("name_korean") or "",
            "name_english": norm.get("name_English") or norm.get("name_english") or "",
        }
    return out


def _parse_float(v: Any) -> float:
    """JS ``parseFloat`` returning NaN for unparseable values."""
    if v is None or v == "":
        return math.nan
    try:
        return float(v)
    except (TypeError, ValueError):
        return math.nan


# ── Renewable capacity CSV (port of convert.ts parseRenewableCsv) ────────────


def _parse_renewable_csv(csv_text: str, carrier: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    out: list[dict[str, Any]] = []
    for raw in reader:
        row: dict[str, str] = {}
        for k, v in raw.items():
            if k is None:
                continue
            row[_strip_bom(k)] = ("" if v is None else str(v)).strip()
        bus_id = row.get("bus_ID") or row.get("bus_id") or row.get("bus")
        if not bus_id:
            continue
        # Header is one of: "Pmax [MW]", "Pmax", or "pmax". Find by prefix.
        pmax_key = next(
            (k for k in row if k.lower().startswith("pmax")), None
        )
        pmin_key = next(
            (k for k in row if k.lower().startswith("pmin")), None
        )
        if not pmax_key:
            continue
        pmax = _parse_float(row.get(pmax_key) or "0")
        if not math.isfinite(pmax) or pmax <= 0:
            continue
        p_nom_min = 0.0
        if pmin_key:
            pm = _parse_float(row.get(pmin_key) or "0")
            p_nom_min = pm if math.isfinite(pm) else 0.0
        try:
            bus_str = str(int(float(bus_id)))
        except (TypeError, ValueError):
            continue
        out.append({
            "bus": bus_str,
            "carrier": carrier,
            "p_nom": pmax,
            "p_nom_min": p_nom_min,
        })
    return out


# ── PyPSA materialisers (port of convert.ts) ─────────────────────────────────


def _control_from_matpower_type(t: float) -> str:
    # MATPOWER bus.type: 1=PQ, 2=PV, 3=Slack/Reference, 4=Isolated.
    rounded = int(round(t))
    return {1: "PQ", 2: "PV", 3: "Slack", 4: "Isolated"}.get(rounded, "PQ")


def _build_buses(
    bus_rows: list[dict[str, Any]], locations: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in bus_rows:
        bus_id = int(round(_num(row.get("bus_i"))))
        loc = locations.get(bus_id)
        lon = loc["longitude"] if loc else math.nan
        lat = loc["latitude"] if loc else math.nan
        out.append({
            "name": str(bus_id),
            "x": (lon if (loc and math.isfinite(lon)) else ""),
            "y": (lat if (loc and math.isfinite(lat)) else ""),
            "v_nom": _num(row.get("baseKV")),
            "carrier": "AC",
            "unit": "kV",
            "control": _control_from_matpower_type(_num(row.get("type"))),
            "v_mag_pu_set": _num(row.get("Vm")),
            "v_mag_pu_min": _num(row.get("Vmin")),
            "v_mag_pu_max": _num(row.get("Vmax")),
            "sub_network": 0,
            "kpg193_bus_id": bus_id,
            "kpg193_name_kr": (loc["name_korean"] if loc else ""),
            "kpg193_name_en": (loc["name_english"] if loc else ""),
            "source": "KPG193",
        })
    return out


def _build_loads(bus_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # One load row per bus, named load_<bus_i>, even where Pd = 0 — keeps
    # the indexing straightforward and PyPSA ignores zero-load entries.
    out: list[dict[str, Any]] = []
    for row in bus_rows:
        bus_id = int(round(_num(row.get("bus_i"))))
        out.append({
            "name": f"load_{bus_id}",
            "bus": str(bus_id),
            "carrier": "load",
            "p_set": _num(row.get("Pd")),
            "q_set": _num(row.get("Qd")),
            "sign": 1,
            "source": "KPG193",
        })
    return out


def _build_thermal_generators(
    gen_rows: list[dict[str, Any]],
    gencost_rows: list[dict[str, Any]],
    genthermal_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Positional join: each block has the same row count and ordering.
    n = len(gen_rows)
    out: list[dict[str, Any]] = []
    for i in range(n):
        g = gen_rows[i]
        c = gencost_rows[i] if i < len(gencost_rows) else {}
        t = genthermal_rows[i] if i < len(genthermal_rows) else {}
        carrier = (
            _str_or_empty(g.get("gen_fuel"))
            or _str_or_empty(c.get("gencost_fuel"))
            or _str_or_empty(t.get("genthermal_fuel"))
            or ""
        )
        pmax = _num(g.get("Pmax"))
        pmin = _num(g.get("Pmin"))
        out.append({
            "name": f"gen_{i + 1}",
            "bus": _int_str(g.get("bus")),
            "control": "PV",
            "carrier": carrier,
            "p_nom": pmax,
            "p_nom_min": pmin,
            "p_min_pu": (pmin / pmax if pmax > 0 else 0),
            "p_max_pu": (_num(g.get("status")) or 1),
            "p_set": _num(g.get("Pg")),
            "q_set": _num(g.get("Qg")),
            "marginal_cost": _num(c.get("c1")),
            "capital_cost": _num(c.get("startup")),
            "committable": True,
            "source": "KPG193",
        })
    return out


def _str_or_empty(v: Any) -> str:
    """Mirror JS ``(x as string) || ''`` — only strings pass through."""
    return v if isinstance(v, str) and v else ""


def _build_renewable_generators(
    rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "name": f"gen_{r['carrier']}_{r['bus']}",
            "bus": r["bus"],
            "control": "PV",
            "carrier": r["carrier"],
            "p_nom": r["p_nom"],
            "p_nom_min": r["p_nom_min"],
            "p_min_pu": 0,
            "p_max_pu": 1,
            "p_set": 0,
            "q_set": 0,
            "marginal_cost": 0,
            "capital_cost": 0,
            "committable": False,
            "source": "KPG193 (renewables CSV)",
        })
    return out


def _enrich_branches(
    branch_rows: list[dict[str, Any]],
    buses: list[dict[str, Any]],
    base_mva: float,
) -> list[dict[str, Any]]:
    v_nom_by_bus: dict[str, float] = {}
    for b in buses:
        v_nom_by_bus[str(b["name"])] = _num(b.get("v_nom"))
    out: list[dict[str, Any]] = []
    for i, row in enumerate(branch_rows):
        bus0 = _int_str(row.get("fbus"))
        bus1 = _int_str(row.get("tbus"))
        v0 = v_nom_by_bus.get(bus0, 0.0)
        v1 = v_nom_by_bus.get(bus1, 0.0)
        ratio = _num(row.get("ratio"))
        angle = _num(row.get("angle"))
        is_transformer = ratio != 0 or angle != 0
        z_base = (v0 * v0) / base_mva if base_mva > 0 else 0.0
        out.append({
            "name": str(i + 1),
            "bus0": bus0,
            "bus1": bus1,
            "v_nom_0": v0,
            "v_nom_1": v1,
            "is_transformer": is_transformer,
            "s_nom": _num(row.get("rateA")),
            "r_ohm": _num(row.get("r")) * z_base,
            "x_ohm": _num(row.get("x")) * z_base,
            "b_siemens": (_num(row.get("b")) / z_base if z_base > 0 else 0),
            "tap_ratio": (ratio or 1.0),
            "phase_shift": angle,
            "status": _num(row.get("status")),
        })
    return out


def _build_lines(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in branches:
        if b["is_transformer"]:
            continue
        out.append({
            "name": b["name"],
            "bus0": b["bus0"],
            "bus1": b["bus1"],
            "type": "",
            "x": b["x_ohm"],
            "r": b["r_ohm"],
            "b": b["b_siemens"],
            "s_nom": b["s_nom"],
            "length": 1,
            "num_parallel": 1,
            "s_max_pu": 1,
            "v_nom": b["v_nom_0"],
            "source": "KPG193",
        })
    return out


def _build_transformers(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in branches:
        if not b["is_transformer"]:
            continue
        out.append({
            "name": b["name"],
            "bus0": b["bus0"],
            "bus1": b["bus1"],
            "type": "",
            "model": "t",
            "x": b["x_ohm"],
            "r": b["r_ohm"],
            "g": 0,
            "b": b["b_siemens"],
            "s_nom": b["s_nom"],
            "tap_ratio": b["tap_ratio"],
            "tap_side": 0,
            "phase_shift": b["phase_shift"],
            "s_max_pu": 1,
            "source": "KPG193",
        })
    return out


def _build_links(dcline_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, row in enumerate(dcline_rows):
        pmax = _num(row.get("Pmax"))
        pmin = _num(row.get("Pmin"))
        loss1 = _num(row.get("loss1"))
        p_min_pu = max(-1.0, min(0.0, pmin / pmax)) if pmax != 0 else 0.0
        out.append({
            "name": f"dcline_{i + 1}",
            "bus0": _int_str(row.get("f_bus")),
            "bus1": _int_str(row.get("t_bus")),
            "p_nom": pmax,
            "p_min_pu": p_min_pu,
            "efficiency": max(0.0, min(1.0, 1.0 - loss1)),
            "carrier": "DC",
            "source": "KPG193",
        })
    return out


# ── Metadata ─────────────────────────────────────────────────────────────────

META = DatabaseMeta(
    id="kpg193",
    name="KPG193 — Korean reference grid (193-bus)",
    short_name="KPG193",
    category="transmission",
    subcategory="Reference network",
    license="See agm-center/kpg-testgrid (academic / research use)",
    homepage="https://github.com/agm-center/kpg-testgrid",
    version_hint="latest (discovered)",
    description=(
        "Complete reference network for the Republic of Korea power system: "
        "193 buses, ~360 transmission lines, ~300 thermal generators with "
        "cost + commitment parameters, per-bus renewable nameplate capacity "
        "(PV / wind / hydro), and DC links. Static single-trip import — drop "
        "into the workbook and run a least-cost dispatch right away. Versions "
        "and renewable-year snapshots are discovered from the repo at fetch "
        "time, so newer datasets appear without a code change."
    ),
    targets=[
        "buses", "generators", "lines", "transformers", "links",
        "loads", "carriers",
    ],
    available=True,
    country_coverage=["KOR"],
    requires_secrets=[],
    filters=[
        Filter(
            id="version",
            label="Dataset version",
            kind="select",
            default="latest",
            options=[
                {"value": "latest", "label": "latest (discover at fetch time)"}
            ],
            description=(
                'Which kpg193_v* directory in the repo to use. "latest" picks '
                "the highest-numbered version found in the repo via the GitHub "
                'Contents API; you can pin a specific value (e.g. "v1_5", '
                '"v2_0") to freeze. The preview note shows which version was '
                "actually used."
            ),
        ),
        Filter(
            id="renewable_year",
            label="Renewable capacity year",
            kind="select",
            default="latest",
            options=[
                {"value": "latest", "label": "latest (discover at fetch time)"}
            ],
            description=(
                "Which year of the renewables_capacity/"
                "{solar,wind,hydro}_generators_<year>.csv files to attach. "
                '"latest" picks the most recent year present in the chosen '
                'version directory; you can pin a year (e.g. "2022") to freeze.'
            ),
        ),
        Filter(
            id="include_renewables",
            label="Include renewable capacities (PV / wind / hydro)",
            kind="toggle",
            default=True,
            description=(
                "Pull per-bus solar / wind / hydro nameplate capacity from the "
                "auxiliary CSVs and emit them as PyPSA Generator rows alongside "
                "the thermal fleet (which lives in the MATPOWER mpc.gen block)."
            ),
        ),
        Filter(
            id="include_dc_links",
            label="Include HVDC links",
            kind="toggle",
            default=True,
            description=(
                "Convert mpc.dcline rows into PyPSA Link rows. p_min_pu = "
                "Pmin/Pmax (negative -> bidirectional). Efficiency = 1 - loss1 "
                "(the piecewise-linear loss-per-MW term)."
            ),
        ),
    ],
)


# ── Module ───────────────────────────────────────────────────────────────────


class Kpg193:
    meta = META

    async def fetch(
        self, region: Region, filters: dict[str, Any], ctx: ImportContext
    ) -> FetchResult:
        paths = await _resolve_paths(ctx, filters)
        include_renewables = filters.get("include_renewables") is not False
        include_dc_links = filters.get("include_dc_links") is not False

        mat_text = await ctx.http.get_text(_raw_url(paths["matpower_path"]))
        loc_text = await ctx.http.get_text(_raw_url(paths["bus_location_path"]))

        async def _fetch_renewable(path: str) -> str | None:
            # Renewable CSV may not exist for every (version, carrier) tuple.
            try:
                return await ctx.http.get_text(_raw_url(path))
            except Exception:
                return None

        solar_text = (
            await _fetch_renewable(paths["solar_path"])
            if include_renewables
            else None
        )
        wind_text = (
            await _fetch_renewable(paths["wind_path"])
            if include_renewables
            else None
        )
        hydro_text = (
            await _fetch_renewable(paths["hydro_path"])
            if include_renewables
            else None
        )

        base_mva = float(extract_scalar(mat_text, "baseMVA"))
        bus_rows = parse_matrix(
            extract_block_lines(mat_text, "bus"), BUS_COLUMNS, "bus_comment"
        )
        gen_rows = parse_matrix(
            extract_block_lines(mat_text, "gen"), GEN_COLUMNS, "gen_fuel"
        )
        branch_rows = parse_matrix(
            extract_block_lines(mat_text, "branch"), BRANCH_COLUMNS,
            "branch_comment",
        )
        gencost_rows = parse_matrix(
            extract_block_lines(mat_text, "gencost"), GENCOST_COLUMNS,
            "gencost_fuel",
        )
        genthermal_rows = parse_matrix(
            extract_block_lines(mat_text, "genthermal"), GENTHERMAL_COLUMNS,
            "genthermal_fuel",
        )
        dcline_rows = (
            parse_matrix(
                extract_block_lines(mat_text, "dcline"), DCLINE_COLUMNS,
                "dcline_comment",
            )
            if include_dc_links
            else []
        )

        locations = _parse_bus_location(loc_text)
        renewables: list[dict[str, Any]] = []
        if solar_text:
            renewables.extend(_parse_renewable_csv(solar_text, "solar"))
        if wind_text:
            renewables.extend(_parse_renewable_csv(wind_text, "wind"))
        if hydro_text:
            renewables.extend(_parse_renewable_csv(hydro_text, "hydro"))

        buses = _build_buses(bus_rows, locations)
        loads = _build_loads(bus_rows)
        thermal_gens = _build_thermal_generators(
            gen_rows, gencost_rows, genthermal_rows
        )
        renewable_gens = _build_renewable_generators(renewables)
        generators = [*thermal_gens, *renewable_gens]

        branches = _enrich_branches(branch_rows, buses, base_mva)
        lines = _build_lines(branches)
        transformers = _build_transformers(branches)
        links = _build_links(dcline_rows)

        # Union of carriers actually present.
        carriers_set: set[str] = {"AC", "load"}
        for g in generators:
            c = g.get("carrier")
            if isinstance(c, str) and c:
                carriers_set.add(c)
        if links:
            carriers_set.add("DC")
        carriers = [{"name": name} for name in sorted(carriers_set)]

        sheets: dict[str, list[dict[str, Any]]] = {
            "carriers": carriers,
            "buses": buses,
            "loads": loads,
            "generators": generators,
            "lines": lines,
        }
        if transformers:
            sheets["transformers"] = transformers
        if links:
            sheets["links"] = links

        payload = {
            "paths": paths,
            "sheets": sheets,
            "counts": {
                "buses": len(buses),
                "loads": len(loads),
                "thermal_generators": len(thermal_gens),
                "renewable_generators": len(renewable_gens),
                "lines": len(lines),
                "transformers": len(transformers),
                "links": len(links),
                "base_mva": base_mva,
            },
        }
        return FetchResult(META.id, region, dict(filters), payload)

    def preview(self, result: FetchResult) -> PreviewSummary:
        paths = result.payload["paths"]
        counts = result.payload["counts"]
        sheets = result.payload["sheets"]
        links_note = (
            f", {counts['links']} HVDC links" if counts["links"] else ""
        )
        summary = (
            f"KPG193 {paths['version_tag']}, renewables "
            f"{paths['renewable_year']}: {counts['buses']} buses, "
            f"{counts['lines']} lines, {counts['transformers']} transformers, "
            f"{counts['thermal_generators']} thermal + "
            f"{counts['renewable_generators']} renewable generators"
            f"{links_note}."
        )
        # Per-bus point overlay so the user sees the network footprint
        # immediately. KPG193's bus_location.csv covers every bus.
        features: list[dict[str, Any]] = []
        for b in sheets.get("buses", []):
            x = b.get("x")
            y = b.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(x), float(y)],
                },
                "properties": {
                    "kind": "substation",
                    "name": str(
                        b.get("kpg193_name_en")
                        or b.get("kpg193_name_kr")
                        or b.get("name")
                    ),
                    "voltages_kv": [_num(b.get("v_nom"))],
                },
            })
        overlay = {"type": "FeatureCollection", "features": features}

        return PreviewSummary(
            counts={
                "buses": counts["buses"],
                "loads": counts["loads"],
                "generators": (
                    counts["thermal_generators"]
                    + counts["renewable_generators"]
                ),
                "lines": counts["lines"],
                "transformers": counts["transformers"],
                "links": counts["links"],
            },
            samples={
                "buses": [
                    {
                        "name": b.get("name"),
                        "v_nom": b.get("v_nom"),
                        "name_en": b.get("kpg193_name_en"),
                    }
                    for b in sheets.get("buses", [])[:10]
                ],
                "generators": [
                    {
                        "name": g.get("name"),
                        "bus": g.get("bus"),
                        "carrier": g.get("carrier"),
                        "p_nom": g.get("p_nom"),
                    }
                    for g in sheets.get("generators", [])[:10]
                ],
            },
            notes=[summary, f"baseMVA = {counts['base_mva']}"],
            overlay=overlay,
        )

    def to_sheets(
        self, result: FetchResult, options: ConvertOptions
    ) -> WorkbookFragment:
        paths = result.payload["paths"]
        sheets = result.payload["sheets"]
        counts = result.payload["counts"]
        frag = WorkbookFragment()
        frag.sheets = sheets

        row_counts: dict[str, Any] = {k: len(v) for k, v in sheets.items()}
        row_counts["base_mva"] = counts["base_mva"]

        frag.provenance = Provenance(
            database_id=META.id,
            country_iso=result.region.country_iso,
            country_name=result.region.country_name,
            filters_json=json.dumps(
                result.filters, sort_keys=True, default=str
            ),
            convert_options_json=json.dumps(
                {
                    "version": paths["version_tag"],
                    "renewable_year": paths["renewable_year"],
                },
                sort_keys=True,
                default=str,
            ),
            fetch_timestamp=datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            row_counts_json=json.dumps(
                row_counts, sort_keys=True, default=str
            ),
        )
        return frag


def build() -> Database:
    return Kpg193()
