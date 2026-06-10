"""Region & Carrier Analyzer — backend (server-side) plugin.

Backend port of the former frontend plugin (v6, browser JS). The browser
version read ``result.assetDetails`` from the page — which is EMPTY when a
backend-STORED run is viewed (the light "View result" payload strips every
per-component series), so its charts and flow map came up blank. This version
runs ``analyze`` inside the Ragnarok backend and reads the run straight from
the server-side run store (``backend.app.run_store``): granular SQL reads of
just the three series it needs, no 100+ MB bundle reassembly, nothing shipped
to the browser.

Hooks (see ``backend/app/plugins.py`` for the contract):

* ``analyze(result, config)`` — aggregates the chosen stored run (blank =
  most recent) to regional output and returns chart specs + tables. The
  ``result`` argument from the request is ignored; the run store is the
  source of truth.
* ``options(name, config, ctx)`` — ``/runs`` lists the stored runs for the
  "Stored run" dropdown.

Output (rendered by the host's chart components, ``kind`` line/area/bar/donut/map):

1. system carrier-mix donut
2. generation-by-region stacked bar
3. per-region carrier-mix donut + hourly stacked area (region configurable)
4. inter-region net-flow bar
5. inter-region flow MAP (region nodes sized by generation, carrier-mix pies,
   net flows as weighted lines)
6. the underlying tables
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger("pypsa_gui.plugins.region_analyzer")

# ── Embedded geography for the standard KR model ──────────────────────────────
# Bus -> province (official name) so a numbered nodal bus can be mapped to a
# region. A bus whose NAME is already a province/region (a region-aggregated
# model) bypasses this and matches the mapping table directly. Buses absent
# here stay per-bus and are counted as unmapped in the Settings row.
BUS_PROVINCE: dict[str, str] = {"1": "강원특별자치도", "2": "경기도", "3": "경기도", "4": "경기도", "5": "경기도", "6": "인천광역시", "7": "경기도", "8": "경기도", "9": "서울특별시", "10": "경기도", "11": "경기도", "12": "서울특별시", "13": "서울특별시", "14": "서울특별시", "15": "경기도", "16": "경기도", "17": "서울특별시", "18": "서울특별시", "19": "서울특별시", "20": "경기도", "21": "인천광역시", "22": "서울특별시", "23": "서울특별시", "24": "서울특별시", "25": "인천광역시", "26": "경기도", "27": "인천광역시", "28": "경기도", "29": "서울특별시", "30": "서울특별시", "31": "서울특별시", "32": "경기도", "33": "서울특별시", "34": "인천광역시", "35": "경기도", "36": "경기도", "37": "인천광역시", "38": "경기도", "39": "경기도", "40": "경기도", "41": "경기도", "42": "경기도", "43": "경기도", "44": "경기도", "45": "경기도", "46": "경기도", "47": "경기도", "48": "경기도", "49": "경기도", "50": "경기도", "51": "경기도", "52": "충청북도", "53": "충청남도", "54": "충청북도", "55": "충청남도", "56": "충청북도", "57": "충청남도", "58": "충청남도", "59": "충청남도", "60": "충청남도", "61": "충청북도", "62": "충청북도", "63": "충청남도", "64": "세종특별자치시", "65": "강원특별자치도", "66": "강원특별자치도", "67": "강원특별자치도", "68": "강원특별자치도", "69": "강원특별자치도", "70": "강원특별자치도", "71": "강원특별자치도", "72": "강원특별자치도", "73": "강원특별자치도", "74": "강원특별자치도", "75": "강원특별자치도", "76": "강원특별자치도", "77": "강원특별자치도", "78": "강원특별자치도", "79": "강원특별자치도", "80": "강원특별자치도", "81": "충청북도", "82": "경상북도", "83": "충청북도", "84": "충청북도", "85": "경상북도", "86": "경상북도", "87": "경상북도", "88": "경상북도", "89": "경상북도", "90": "경상북도", "91": "충청북도", "92": "충청북도", "93": "경상북도", "94": "경상북도", "95": "경상북도", "96": "충청남도", "97": "충청남도", "98": "대전광역시", "99": "대전광역시", "100": "충청남도", "101": "대전광역시", "102": "충청북도", "103": "충청남도", "104": "충청남도", "105": "충청남도", "106": "충청남도", "107": "전북특별자치도", "108": "전북특별자치도", "109": "전북특별자치도", "110": "전북특별자치도", "111": "전북특별자치도", "112": "전북특별자치도", "113": "전북특별자치도", "114": "전북특별자치도", "115": "전북특별자치도", "116": "전북특별자치도", "117": "전북특별자치도", "118": "전북특별자치도", "119": "전북특별자치도", "120": "전북특별자치도", "121": "전라남도", "122": "전라남도", "123": "전라남도", "124": "전라남도", "125": "전라남도", "126": "광주광역시", "127": "광주광역시", "128": "광주광역시", "129": "전라남도", "130": "전라남도", "131": "전라남도", "132": "전라남도", "133": "전라남도", "134": "전라남도", "135": "전라남도", "136": "전라남도", "137": "전라남도", "138": "전라남도", "139": "전라남도", "140": "전라남도", "141": "전라남도", "142": "전라남도", "143": "전라남도", "144": "전라남도", "145": "전라남도", "146": "대구광역시", "147": "충청북도", "148": "경상북도", "149": "경상북도", "150": "경상북도", "151": "경상북도", "152": "경상북도", "153": "경상북도", "154": "경상북도", "155": "대구광역시", "156": "대구광역시", "157": "대구광역시", "158": "경상북도", "159": "경상북도", "160": "대구광역시", "161": "경상북도", "162": "경상남도", "163": "경상북도", "164": "경상남도", "165": "울산광역시", "166": "울산광역시", "167": "울산광역시", "168": "경상남도", "169": "경상남도", "170": "경상남도", "171": "경상남도", "172": "경상남도", "173": "경상남도", "174": "경상남도", "175": "부산광역시", "176": "경상남도", "177": "경상남도", "178": "경상남도", "179": "부산광역시", "180": "경상남도", "181": "부산광역시", "182": "부산광역시", "183": "경상남도", "184": "부산광역시", "185": "부산광역시", "186": "부산광역시", "187": "부산광역시", "188": "경상남도", "189": "경상남도", "190": "경상남도", "191": "경상남도", "192": "경상남도", "193": "경상남도", "194": "제주특별자치도", "195": "경상북도", "196": "경상북도", "197": "전라남도", "198": "전북특별자치도", "199": "경기도", "200": "경기도", "201": "경기도", "202": "충청남도", "203": "인천광역시", "204": "인천광역시"}

# Approximate centroid (lat, lon) per province official name. A region
# (province group) centroid is the mean of its member provinces' centroids.
PROVINCE_CENTROID: dict[str, tuple[float, float]] = {
    "강원특별자치도": (37.8, 128.2), "경기도": (37.4, 127.2), "경상남도": (35.4, 128.2),
    "경상북도": (36.4, 128.9), "광주광역시": (35.16, 126.85), "대구광역시": (35.87, 128.60),
    "대전광역시": (36.35, 127.38), "부산광역시": (35.18, 129.07), "서울특별시": (37.57, 126.98),
    "세종특별자치시": (36.48, 127.29), "울산광역시": (35.54, 129.31), "인천광역시": (37.46, 126.71),
    "전라남도": (34.9, 126.9), "전북특별자치도": (35.7, 127.1), "제주특별자치도": (33.38, 126.55),
    "충청남도": (36.5, 126.8), "충청북도": (36.8, 127.7),
}

# Output series read from the run store: (series sheet, model sheet) per
# branch component. p0 = MW into the branch at bus0 (PyPSA sign convention).
_BRANCH_SHEETS = (
    ("lines-p0", "lines"),
    ("links-p0", "links"),
    ("transformers-p0", "transformers"),
)

# Unbounded page/window sizes for the granular run-store readers — the reads
# below must return WHOLE sheets/series, not a downsampled preview.
_ALL_ROWS = 10**9


def _key(value: Any) -> str:
    """Normalise a bus/name cell to a string key ("9", not "9.0")."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value if value is not None else "").strip()


def _num(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n else 0.0  # NaN -> 0


def _iso_label(iso: str) -> str:
    """Snapshot label "HH:MM" from an ISO timestamp (no TZ shifts)."""
    t = iso.find("T")
    return iso[t + 1 : t + 6] if 0 <= t and len(iso) >= t + 6 else iso


def _run_store() -> Any:
    from backend.app import run_store

    return run_store


def _series_frame(rs: Any, run_name: str, sheet: str) -> pd.DataFrame | None:
    """One FULL output series as a numeric frame indexed by snapshot string."""
    win = rs.run_series_window(run_name, sheet, max_points=_ALL_ROWS)
    if not win or not win.get("rows"):
        return None
    df = pd.DataFrame(win["rows"])
    idx = win.get("indexCol") or "snapshot"
    if idx in df.columns:
        df = df.set_index(df[idx].astype(str)).drop(columns=[idx])
    return df.apply(pd.to_numeric, errors="coerce").fillna(0.0)


def _model_rows(rs: Any, run_name: str, sheet: str) -> list[dict[str, Any]]:
    page = rs.run_model_sheet_page(run_name, sheet, offset=0, limit=_ALL_ROWS)
    return list(page["rows"]) if page and page.get("rows") else []


def _make_region_resolver(
    cfg: dict[str, Any], unmapped: set[str]
) -> tuple[Callable[[Any], str], str]:
    """(bus -> region) resolver + the mapping-table column in effect.

    Resolution order (mirrors the v6 frontend plugin):
    1. per-bus mode: the bus IS the region;
    2. bus name found in the mapping table (short/official) -> mapped region;
    3. numbered bus -> embedded province -> mapped region (or the province
       itself when the column is blank);
    4. otherwise unmapped: stays per-bus and is counted.
    """
    by_region = cfg.get("aggregate_by_region") is not False  # default on
    rc = str(cfg.get("region_column") or "").strip()
    col = "short" if rc == "province" else rc
    lookup: dict[str, str] = {}
    if by_region and col:
        for row in cfg.get("province_mapping") or []:
            if not isinstance(row, dict):
                continue
            value = str(row.get(col) or "").strip()
            if not value:
                continue
            for k in ("short", "official"):
                name = str(row.get(k) or "").strip()
                if name:
                    lookup[name] = value

    def resolve(bus: Any) -> str:
        b = _key(bus)
        if not by_region:
            return b
        if col and b in lookup:
            return lookup[b]
        province = BUS_PROVINCE.get(b)
        if province is not None:
            if col and province in lookup:
                return lookup[province]
            return province
        unmapped.add(b)
        return b

    return resolve, col


def _region_centroid_fn(
    cfg: dict[str, Any], col: str
) -> Callable[[str], tuple[float, float] | None]:
    """Region -> (lat, lon): a province directly, else the mean of the mapping
    table's member provinces for that region value."""
    officials: dict[str, list[str]] = {}
    for row in cfg.get("province_mapping") or []:
        if not isinstance(row, dict):
            continue
        official = str(row.get("official") or "").strip()
        if not official:
            continue
        region = str(row.get(col) or "").strip() if col else ""
        region = region or str(row.get("short") or "").strip()
        if region:
            officials.setdefault(region, []).append(official)

    def centroid(region: str) -> tuple[float, float] | None:
        if region in PROVINCE_CENTROID:
            return PROVINCE_CENTROID[region]
        points = [PROVINCE_CENTROID[o] for o in officials.get(region, []) if o in PROVINCE_CENTROID]
        if not points:
            return None
        return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))

    return centroid


def analyze(result: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any]:
    """Output-tab analytics: regional generation/flow charts + tables + flow map.

    ``result`` (the request body's result) is ignored — the run store is the
    source of truth, so this works on any stored run regardless of what the
    browser is currently viewing. Never raises: every failure degrades to an
    actionable ``{"note": …}``.
    """
    del result
    cfg = {k: v for k, v in (config or {}).items() if k != "__plugin_data_dir__"}
    try:
        rs = _run_store()
    except Exception as exc:  # noqa: BLE001 — degrade, never break the Output tab
        return {"note": f"Run store unavailable: {exc}"}

    run_name = str(cfg.get("run_name") or "").strip()
    if not run_name:
        runs = rs.list_runs()
        if not runs:
            return {"note": "No stored runs yet — run the model with 'Store run in backend' enabled, then come back."}
        run_name = str(runs[0].get("name") or "")
    try:
        return _analyze_run(rs, run_name, cfg)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Region analysis failed for run %s", run_name)
        return {"note": f"Analysis of {run_name!r} failed: {exc}"}


def _analyze_run(rs: Any, run_name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    gen_p = _series_frame(rs, run_name, "generators-p")
    if gen_p is None:
        return {"note": f"Run {run_name!r} has no generator dispatch series."}

    light = rs.get_run_analytics(run_name) or {}
    weight = _num(cfg.get("snapshot_weight")) or _num(light.get("snapshotWeight")) or 1.0

    unit = str(cfg.get("energy_unit") or "GWh").upper()
    scale = 1.0 if unit == "MWH" else 1e-6 if unit == "TWH" else 1e-3
    unit_label = "MWh" if unit == "MWH" else "TWh" if unit == "TWH" else "GWh"
    energy = lambda mwh: round(mwh * scale, 4)  # noqa: E731 — mirrors the JS helper

    by_carrier = cfg.get("aggregate_by_carrier") is not False  # default on
    unmapped: set[str] = set()
    region_of, mapping_col = _make_region_resolver(cfg, unmapped)

    # Generator name -> (region, carrier, capacity MW). p_nom_opt (solved)
    # wins over the input p_nom when the run optimised capacity.
    p_nom_opt = ((light.get("result") or {}).get("outputs") or {}).get("static") or {}
    p_nom_opt = p_nom_opt.get("generators") or {}
    gen_region: dict[str, str] = {}
    gen_carrier: dict[str, str] = {}
    gen_capacity: dict[str, float] = {}
    for row in _model_rows(rs, run_name, "generators"):
        name = _key(row.get("name"))
        if not name:
            continue
        gen_region[name] = region_of(row.get("bus"))
        carrier = str(row.get("carrier") or "").strip() or "(none)"
        gen_carrier[name] = carrier if by_carrier else "all"
        opt = (p_nom_opt.get(name) or {}).get("p_nom_opt") if isinstance(p_nom_opt.get(name), dict) else None
        gen_capacity[name] = _num(opt) or _num(row.get("p_nom"))

    gen_cols = [c for c in gen_p.columns if c in gen_region]
    if not gen_cols:
        return {"note": f"Run {run_name!r}: no dispatch column matches a generators-sheet name."}
    pos = gen_p[gen_cols].clip(lower=0.0)
    snapshots = [str(s) for s in gen_p.index]
    n_snap = len(snapshots)
    max_hours = int(_num(cfg.get("max_hours")) or 168)
    hours_shown = min(n_snap, max_hours) if max_hours > 0 else n_snap
    labels = [_iso_label(s) for s in snapshots]

    # ── Generation totals: region × carrier (MWh) + capacity (MW) ─────────────
    energy_per_gen = pos.sum(axis=0) * weight  # MWh per generator
    gen_total: dict[str, dict[str, float]] = {}
    cap_total: dict[str, dict[str, float]] = {}
    for name in gen_cols:
        r, c = gen_region[name], gen_carrier[name]
        gen_total.setdefault(r, {})[c] = gen_total.get(r, {}).get(c, 0.0) + float(energy_per_gen[name])
        cap_total.setdefault(r, {})[c] = cap_total.get(r, {}).get(c, 0.0) + gen_capacity[name]
    regions = sorted(gen_total)
    carriers = sorted({c for per in gen_total.values() for c in per})
    region_total = {r: sum(gen_total[r].values()) for r in regions}
    carrier_total: dict[str, float] = {}
    for per in gen_total.values():
        for c, mwh in per.items():
            carrier_total[c] = carrier_total.get(c, 0.0) + mwh
    total_generation = sum(carrier_total.values())

    # ── Inter-region flows (lines + links + transformers) ─────────────────────
    pair_net: dict[tuple[str, str], float] = {}
    pair_gross: dict[tuple[str, str], float] = {}
    for series_sheet, model_sheet in _BRANCH_SHEETS:
        flows = _series_frame(rs, run_name, series_sheet)
        if flows is None:
            continue
        endpoints = {
            _key(row.get("name")): (region_of(row.get("bus0")), region_of(row.get("bus1")))
            for row in _model_rows(rs, run_name, model_sheet)
        }
        for branch in flows.columns:
            ends = endpoints.get(_key(branch))
            if ends is None or ends[0] == ends[1]:
                continue
            a, b = ends
            sign = 1.0
            if a > b:
                a, b, sign = b, a, -1.0
            p0 = flows[branch]
            pair_net[(a, b)] = pair_net.get((a, b), 0.0) + float(p0.sum()) * sign * weight
            pair_gross[(a, b)] = pair_gross.get((a, b), 0.0) + float(p0.abs().sum()) * weight

    flow_rows = sorted(
        (
            {
                "from": a if net >= 0 else b,
                "to": b if net >= 0 else a,
                f"net_{unit_label}": energy(abs(net)),
                f"gross_{unit_label}": energy(pair_gross[(a, b)]),
            }
            for (a, b), net in pair_net.items()
        ),
        key=lambda r: -r[f"net_{unit_label}"],
    )

    # ── Selected region for the per-region deep-dive charts ───────────────────
    rc = str(cfg.get("region_column") or "province").strip()
    sel_field = {
        "province": "chart_region_province", "group1": "chart_region_group1",
        "group2": "chart_region_group2", "group3": "chart_region_group3",
        "singlenode": "chart_region_singlenode",
    }.get(rc, "chart_region_province")
    wanted = str(cfg.get(sel_field) or cfg.get("chart_region") or "").strip()
    selected = wanted if wanted in gen_total else max(regions, key=lambda r: region_total[r], default="")

    sel_hourly: dict[str, pd.Series] = {}
    if selected:
        sel_cols = [g for g in gen_cols if gen_region[g] == selected]
        for c in sorted({gen_carrier[g] for g in sel_cols}):
            cols = [g for g in sel_cols if gen_carrier[g] == c]
            sel_hourly[c] = pos[cols].sum(axis=1)

    # ── Chart specs (host renders: kind donut/bar/area/map) ───────────────────
    donut_system = {
        "kind": "donut",
        "description": f"System generation by carrier ({unit_label})",
        "slices": [
            {"label": c, "value": energy(carrier_total[c])}
            for c in carriers
            if carrier_total.get(c, 0.0) > 0
        ],
    }
    bar_by_region = {
        "kind": "bar", "stacked": True,
        "description": f"Generation by region ({unit_label})",
        "xAxisTitle": "region", "yAxisTitle": unit_label,
        "series": [{"key": c} for c in carriers],
        "rows": [
            {"label": r, **{c: energy(gen_total[r].get(c, 0.0)) for c in carriers}}
            for r in regions
        ],
    }
    donut_region = {
        "kind": "donut",
        "description": f"Carrier mix — {selected} ({unit_label})",
        "slices": [
            {"label": c, "value": energy(gen_total.get(selected, {}).get(c, 0.0))}
            for c in carriers
            if gen_total.get(selected, {}).get(c, 0.0) > 0
        ],
    }
    sel_carriers = sorted(sel_hourly)
    area_region = {
        "kind": "area", "stacked": True,
        "description": f"Hourly generation — {selected} (MW, first {hours_shown} of {n_snap} snapshots)",
        "xAxisTitle": "snapshot", "yAxisTitle": "MW",
        "series": [{"key": c} for c in sel_carriers],
        "rows": [
            {"label": labels[i], **{c: round(float(sel_hourly[c].iloc[i]), 3) for c in sel_carriers}}
            for i in range(hours_shown)
        ],
    }
    flow_bar = {
        "kind": "bar",
        "description": f"Inter-region net flow ({unit_label})",
        "yAxisTitle": unit_label,
        "series": [{"key": "net", "label": f"net {unit_label}"}],
        "rows": [{"label": f"{f['from']}→{f['to']}", "net": f[f"net_{unit_label}"]} for f in flow_rows],
    }

    centroid_of = _region_centroid_fn(cfg, mapping_col)
    map_nodes = []
    located: set[str] = set()
    for r in regions:
        point = centroid_of(r)
        if point is None:
            continue
        located.add(r)
        mix = [
            {"label": c, "value": energy(gen_total[r].get(c, 0.0))}
            for c in carriers
            if gen_total[r].get(c, 0.0) > 0
        ]
        map_nodes.append({
            "id": r, "label": r, "lat": point[0], "lon": point[1],
            "value": energy(region_total[r]), "mix": mix,
        })
    map_edges = [
        {
            "from": f["from"], "to": f["to"], "value": f[f"net_{unit_label}"],
            "label": f"{f['from']} → {f['to']}: {f[f'net_{unit_label}']} {unit_label}",
        }
        for f in flow_rows
        if f["from"] in located and f["to"] in located
    ]
    flow_map = {
        "kind": "map",
        "description": (
            f"Generation mix by node ({unit_label}) — pie = carrier mix, "
            "size = total generation, line width = net inter-region flow"
        ),
        "nodes": map_nodes, "edges": map_edges,
    }

    # ── Tables ─────────────────────────────────────────────────────────────────
    generation_table = [
        {
            "region": r,
            **{c: energy(gen_total[r].get(c, 0.0)) for c in carriers},
            f"Total_{unit_label}": energy(region_total[r]),
        }
        for r in regions
    ]
    capacity_table = (
        [
            {
                "region": r,
                **{c: round(cap_total.get(r, {}).get(c, 0.0), 2) for c in carriers},
                "Total_MW": round(sum(cap_total.get(r, {}).values()), 2),
            }
            for r in regions
        ]
        if by_carrier
        else None
    )
    carrier_table = sorted(
        (
            {
                "carrier": c,
                f"energy_{unit_label}": energy(carrier_total[c]),
                "share_pct": round(carrier_total[c] / total_generation * 100, 2) if total_generation > 0 else 0,
            }
            for c in carriers
        ),
        key=lambda r: -r[f"energy_{unit_label}"],
    )

    grouping = (
        "per-bus"
        if cfg.get("aggregate_by_region") is False
        else (str(cfg.get("region_column") or "") or "identity (bus = region)")
    )
    out: dict[str, Any] = {}
    out["Settings"] = (
        f"run={run_name}, group by={grouping}, regions={len(regions)}, "
        f"unit={unit_label}, weight={round(weight, 4)}h"
        + (f", UNMAPPED buses={len(unmapped)} (kept per-bus — check model/bus numbering)" if unmapped else "")
    )
    out[f"Total generation ({unit_label})"] = energy(total_generation)
    out["Carrier mix (system)"] = donut_system
    out["Generation by region"] = bar_by_region
    out[f"Carrier mix — {selected}"] = donut_region
    out[f"Hourly generation — {selected}"] = area_region
    out["Inter-region net flow"] = flow_bar
    out["Inter-region flow map"] = flow_map
    out[f"Generation by region — table ({unit_label})"] = generation_table
    if capacity_table is not None:
        out["Capacity by region — table (MW)"] = capacity_table
    out[f"Carrier totals — table ({unit_label})"] = carrier_table
    out[f"Regional flow — table ({unit_label})"] = flow_rows
    return out


def options(name: str, config: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
    """On-demand dropdown rows. ``/runs`` lists the stored runs, newest first."""
    del config, ctx
    if name != "/runs":
        return []
    try:
        rs = _run_store()
        rows = []
        for meta in rs.list_runs():
            run = str(meta.get("name") or "")
            if not run:
                continue
            label = str(meta.get("label") or run)
            saved = str(meta.get("savedAt") or "")[:10]
            rows.append({"name": run, "display": f"{label} ({saved})" if saved else label})
        return rows
    except Exception:  # noqa: BLE001 — an empty dropdown beats a broken form
        logger.exception("Failed to list stored runs")
        return []
