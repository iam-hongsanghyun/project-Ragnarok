"""RFNBO matching rules (Commission Delegated Regulation (EU) 2023/1184) for P2X electrolysers.

Renewable fuels of non-biological origin (RFNBO) count the electricity an
electrolyser takes from the grid as fully renewable only under the Regulation's
rules. This module turns them into (a) an in-solve linopy constraint, (b) a
candidate filter and (c) pre-/post-solve checks. Article numbers below are those
of the Regulation (OJ L 157, 20.6.2023, p. 11).

Run option ``options.rfnboConfig`` (see :func:`normalise_config`)::

    {enabled, temporal: hourly|monthly|auto, electrolysers: [...], designatedGenerators: [...],
     enforceAdditionality, additionalityMonths, unknownBuildYearAs,
     enforceGeographic, zoneColumn, hourlyFrom, priceRule, gridAlternatives}

Algorithm (temporal correlation, Art. 6):
    Let ``E`` be the electrolyser set, ``G`` the designated renewable generators (PPA matching),
    ``p`` the power (MW) and ``w_t`` the snapshot weighting (h). For a matching period ``T``
    (one snapshot when hourly, one calendar month when monthly):
    $$\\sum_{t\\in T} w_t \\sum_{e\\in E} p^{el}_{e,t} \\;\\le\\; \\sum_{t\\in T} w_t \\sum_{g\\in G} p^{gen}_{g,t}
      \\qquad \\forall T$$
    ASCII: sum_{t in T} w_t * sum_e p_el[e,t]  <=  sum_{t in T} w_t * sum_g p_gen[g,t]  for every period T.
    Art. 6(1): until 31 December 2029 the period is the calendar month; Art. 6(2): from
    1 January 2030 it is the one-hour period (``temporal: auto`` switches at ``hourlyFrom``).
    Units: p in MW, w_t in h, both sides MWh. ``p_el`` is the electrolyser Link's ``p0`` (electricity
    taken from ``bus0``).

Additionality (Art. 5(a), Art. 3(b)): a designated installation must have come into operation not
earlier than 36 months before the electrolyser: ``build_year_gen >= build_year_el - 3``. Years are
the model's resolution, so the test is on calendar years. Applied as a *check* and as a *candidate
filter* (``enforceAdditionality``), never as an LP constraint. Art. 5(b) (no operating or
investment aid) cannot be read from a model and is always reported as ``attest``.

Geographic correlation (Art. 7(1)(a)): the designated installation is in the same bidding zone
as the electrolyser. Zone of a bus = its ``zoneColumn`` value (``bidding_zone``, ``zone`` or ``country``,
first present), else the bus itself. Art. 7(1)(b) (interconnected zone with an equal or higher
day-ahead price) and 7(1)(c) (offshore zone) need market data and are reported as ``attest``.

Grid-electricity alternatives (Art. 4(1), 4(2)): REPORTED ONLY, from the solved run: a renewable share
above 90 % in the bidding zone (4(1)) or an electricity emission intensity below 18 gCO2e/MJ (4(2)).
Art. 6(3): in a one-hour period with a clearing price at or below 20 EUR/MWh (or below
0.36 x the EUA price) the temporal condition is always met; reported as an ex-post count.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

REGISTRY_SHEET = "RAGNAROK_P2X"
#: Art. 6(2): hourly correlation applies from this date unless the Member State applies it earlier (1 July 2027).
HOURLY_FROM_DEFAULT = "2030-01-01"
#: Art. 5(a) / Art. 3(b): months before the electrolyser a renewable installation may have come into operation.
ADDITIONALITY_MONTHS_DEFAULT = 36
#: Art. 4(1): renewable share threshold; Art. 4(2): emission intensity threshold, gCO2e/MJ of electricity.
GRID_RES_SHARE = 0.9
GRID_INTENSITY_G_PER_MJ = 18.0
#: Art. 6(3): price threshold EUR/MWh and the factor on the EUA price (EUR/tCO2).
PRICE_RULE_EUR_PER_MWH = 20.0
PRICE_RULE_EUA_FACTOR = 0.36
#: tCO2/MWh -> gCO2/MJ: 1e6 g/t / 3600 MJ/MWh.
G_PER_MJ_PER_T_PER_MWH = 1.0e6 / 3600.0
#: Carriers treated as renewable for the Art. 4 share (editable via gridAlternatives.renewableCarriers).
RES_CARRIERS_DEFAULT = ("wind", "solar", "onwind", "offwind", "offwind-ac", "offwind-dc", "hydro", "ror", "solar-hsat", "pv", "geothermal")
_ZONE_COLUMNS = ("bidding_zone", "zone", "country")
RTOL = 1.0e-9
ATOL = 1.0e-6


def normalise_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """``options.rfnboConfig`` with every default made explicit (a copy)."""
    r = dict(raw or {})
    pr = dict(r.get("priceRule") or {})
    ga = dict(r.get("gridAlternatives") or {})
    temporal = str(r.get("temporal") or "hourly").lower()
    if temporal not in ("hourly", "monthly", "auto"):
        raise ValueError(f"rfnboConfig.temporal must be hourly|monthly|auto, got {temporal!r}.")
    return {
        "enabled": bool(r.get("enabled", False)),
        "temporal": temporal,
        "hourlyFrom": str(r.get("hourlyFrom") or HOURLY_FROM_DEFAULT),
        "chainId": r.get("chainId") or None,
        "electrolysers": [str(x) for x in r.get("electrolysers") or []],
        "designatedGenerators": [str(x) for x in r.get("designatedGenerators") or []],
        "enforceAdditionality": bool(r.get("enforceAdditionality", False)),
        "additionalityMonths": float(r.get("additionalityMonths", ADDITIONALITY_MONTHS_DEFAULT)),
        "unknownBuildYearAs": str(r.get("unknownBuildYearAs") or "fail").lower(),
        "enforceGeographic": bool(r.get("enforceGeographic", False)),
        "zoneColumn": r.get("zoneColumn") or None,
        "priceRule": {"enabled": bool(pr.get("enabled", False)),
                      "thresholdEurPerMwh": float(pr.get("thresholdEurPerMwh", PRICE_RULE_EUR_PER_MWH)),
                      "euaEurPerT": None if pr.get("euaEurPerT") in (None, "") else float(pr["euaEurPerT"])},
        "gridAlternatives": {
            "renewableShareThreshold": float(ga.get("renewableShareThreshold", GRID_RES_SHARE)),
            "intensityThresholdGPerMj": float(ga.get("intensityThresholdGPerMj", GRID_INTENSITY_G_PER_MJ)),
            "renewableCarriers": [str(c) for c in ga.get("renewableCarriers") or RES_CARRIERS_DEFAULT],
        },
    }


# ── registry / model helpers (rows in, rows out) ─────────────────────────────────


def registry_chains(model: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Parsed ``RAGNAROK_P2X`` registry rows (one dict per chain; bad rows skipped)."""
    out: list[dict[str, Any]] = []
    for row in model.get(REGISTRY_SHEET) or []:
        try:
            reg = json.loads(str(row.get("json") or ""))
        except (TypeError, ValueError):
            continue
        if isinstance(reg, dict) and reg.get("chainId"):
            out.append(reg)
    return out


def _rows(model: dict[str, list[dict[str, Any]]], sheet: str) -> dict[str, dict[str, Any]]:
    return {str(r.get("name")): r for r in model.get(sheet) or [] if r.get("name") not in (None, "")}


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def _year(v: Any) -> int | None:
    try:
        y = int(float(v))
    except (TypeError, ValueError):
        return None
    return y if y > 0 else None


def first_snapshot_year(model: dict[str, list[dict[str, Any]]]) -> int | None:
    """Calendar year of the first snapshot (the reference commissioning year of an electrolyser without a build_year)."""
    for row in model.get("snapshots") or []:
        try:
            return int(pd.Timestamp(str(row.get("snapshot"))).year)
        except (TypeError, ValueError):
            continue
    return None


def resolve_sets(model: dict[str, list[dict[str, Any]]], cfg: dict[str, Any]) -> dict[str, Any]:
    """Electrolysers and designated generators for ``cfg`` (explicit lists win, else the P2X registry).

    Returns ``{electrolysers: [...], designated: [...], chains: [chainId...], source: str}``.
    """
    links = _rows(model, "links")
    chains = registry_chains(model)
    if cfg.get("chainId"):
        chains = [c for c in chains if c["chainId"] == cfg["chainId"]]
    ely = list(cfg["electrolysers"])
    des = list(cfg["designatedGenerators"])
    source = "config"
    if not ely:
        ely = [c["components"]["electrolyser"]["name"] for c in chains if "electrolyser" in c.get("components", {})]
        source = "registry"
    if not ely:
        ely = [n for n, r in links.items() if str(r.get("carrier") or "").lower() == "electrolysis"]
        source = "carrier 'electrolysis'"
    if not des:
        for c in chains:
            des += [g for g in c.get("designatedGenerators", []) if g not in des]
    return {"electrolysers": [e for e in dict.fromkeys(ely)], "designated": list(dict.fromkeys(des)),
            "chains": [c["chainId"] for c in chains], "source": source}


def _zone(bus_row: dict[str, Any] | None, bus_name: str, column: str | None) -> tuple[str, str]:
    """``(zone, how)`` of a bus: the zone column value if present, else the bus name."""
    cols = (column,) if column else _ZONE_COLUMNS
    if bus_row:
        for c in cols:
            v = bus_row.get(c)
            if v not in (None, ""):
                return str(v), c
    return bus_name, "bus"


# ── checks (pre-solve, from model rows) ──────────────────────────────────────────


def check_additionality(model: dict[str, list[dict[str, Any]]], cfg: dict[str, Any], sets: dict[str, Any]) -> list[dict[str, Any]]:
    """Art. 5(a) / 3(b): one result per designated generator against the (earliest) electrolyser.

    Status ``pass`` / ``fail`` / ``unknown``; a generator that is itself extendable and has no
    ``build_year`` is built in this run with the electrolyser, so it passes.
    """
    links, gens = _rows(model, "links"), _rows(model, "generators")
    registries = {c["components"]["electrolyser"]["name"]: c for c in registry_chains(model) if "electrolyser" in c.get("components", {})}
    ref_default = first_snapshot_year(model)
    ely_years: dict[str, tuple[int | None, str]] = {}
    for e in sets["electrolysers"]:
        y = _year((links.get(e) or {}).get("build_year"))
        how = "link build_year"
        if y is None:
            y = _year(((registries.get(e) or {}).get("electrolyser") or {}).get("buildYear"))
            how = "registry buildYear"
        if y is None and ref_default is not None:
            y, how = ref_default, "first snapshot year (no build_year set)"
        ely_years[e] = (y, how)
    known = [y for y, _ in ely_years.values() if y is not None]
    ely_year = min(known) if known else None
    window_years = cfg["additionalityMonths"] / 12.0
    out = []
    for g in sets["designated"]:
        row = gens.get(g)
        if row is None:
            out.append({"generator": g, "status": "unknown", "reason": "not in the model"})
            continue
        by = _year(row.get("build_year"))
        if by is None and _truthy(row.get("p_nom_extendable")):
            out.append({"generator": g, "status": "pass", "buildYear": None, "electrolyserYear": ely_year,
                        "reason": "extendable: built in this run together with the electrolyser (Art. 5(a))"})
            continue
        if by is None or ely_year is None:
            status = "pass" if cfg["unknownBuildYearAs"] == "pass" else "unknown"
            out.append({"generator": g, "status": status, "buildYear": by, "electrolyserYear": ely_year,
                        "reason": "no build_year on the generator" if by is None else "no electrolyser commissioning year"})
            continue
        ok = by >= ely_year - window_years
        out.append({"generator": g, "status": "pass" if ok else "fail", "buildYear": by, "electrolyserYear": ely_year,
                    "reason": f"came into operation in {by}; electrolyser {ely_year}; window {cfg['additionalityMonths']:g} months "
                              f"(Art. 5(a)): {'within' if ok else 'earlier than the window'}"})
    return out


def check_geography(model: dict[str, list[dict[str, Any]]], cfg: dict[str, Any], sets: dict[str, Any]) -> list[dict[str, Any]]:
    """Art. 7(1)(a): the designated generator is in the electrolyser's bidding zone (``pass`` / ``fail`` / ``unknown``)."""
    links, gens, buses = _rows(model, "links"), _rows(model, "generators"), _rows(model, "buses")
    ely_zones = {}
    for e in sets["electrolysers"]:
        bus = str((links.get(e) or {}).get("bus0") or "")
        ely_zones[e] = (bus, *_zone(buses.get(bus), bus, cfg["zoneColumn"]))
    out = []
    for g in sets["designated"]:
        row = gens.get(g)
        if row is None:
            out.append({"generator": g, "status": "unknown", "reason": "not in the model"})
            continue
        gbus = str(row.get("bus") or "")
        gzone, ghow = _zone(buses.get(gbus), gbus, cfg["zoneColumn"])
        worst = "pass"
        reasons = []
        for e, (ebus, ezone, ehow) in ely_zones.items():
            if gbus == ebus or (gzone == ezone and ghow == ehow and ghow != "bus"):
                reasons.append(f"{e}: same {'bus' if gbus == ebus else 'zone ' + ezone}")
            elif ghow == "bus" or ehow == "bus":
                worst = "unknown" if worst == "pass" else worst
                reasons.append(f"{e}: different buses ({gbus} vs {ebus}) and no zone column on the buses - the zone cannot be read")
            else:
                worst = "fail"
                reasons.append(f"{e}: zone {gzone} differs from {ezone} (Art. 7(1)(a); 7(1)(b)/(c) need market data)")
        out.append({"generator": g, "status": worst, "bus": gbus, "reason": "; ".join(reasons) or "no electrolyser"})
    return out


def eligible_generators(model: dict[str, list[dict[str, Any]]], cfg: dict[str, Any], sets: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Candidate filter: drop designated generators failing an *enforced* check.

    Returns ``(eligible, report)``. ``unknown`` passes the geography filter and fails the
    additionality filter unless ``unknownBuildYearAs`` is ``pass``.
    """
    add = {r["generator"]: r for r in check_additionality(model, cfg, sets)}
    geo = {r["generator"]: r for r in check_geography(model, cfg, sets)}
    keep, dropped = [], []
    for g in sets["designated"]:
        a, ge = add.get(g, {}).get("status"), geo.get(g, {}).get("status")
        if cfg["enforceAdditionality"] and a != "pass":
            dropped.append({"generator": g, "rule": "additionality (Art. 5(a))", "status": a, "reason": add[g]["reason"]})
        elif cfg["enforceGeographic"] and ge == "fail":
            dropped.append({"generator": g, "rule": "geographic correlation (Art. 7(1)(a))", "status": ge, "reason": geo[g]["reason"]})
        else:
            keep.append(g)
    return keep, {"additionality": list(add.values()), "geographic": list(geo.values()), "dropped": dropped}


def resolve_plan(model: dict[str, list[dict[str, Any]]], raw_cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    """The solve plan for ``options.rfnboConfig`` or ``None`` when matching is off.

    Raises:
        ValueError: matching is on but there is no electrolyser, or no eligible designated generator.
    """
    cfg = normalise_config(raw_cfg)
    if not cfg["enabled"]:
        return None
    sets = resolve_sets(model, cfg)
    if not sets["electrolysers"]:
        raise ValueError("RFNBO matching is on but the model has no electrolyser (a P2X chain, a Link with carrier 'electrolysis', "
                         "or rfnboConfig.electrolysers).")
    links = _rows(model, "links")
    missing = [e for e in sets["electrolysers"] if e not in links]
    if missing:
        raise ValueError(f"RFNBO electrolyser(s) not found among the links: {missing}.")
    keep, report = eligible_generators(model, cfg, sets)
    if not keep:
        why = "; ".join(f"{d['generator']}: {d['rule']}" for d in report["dropped"]) or "none designated"
        raise ValueError("RFNBO matching is on but no designated renewable generator is eligible "
                         f"({why}). Designate generators in the P2X chain or rfnboConfig.designatedGenerators.")
    gens = _rows(model, "generators")
    absent = [g for g in keep if g not in gens]
    if absent:
        raise ValueError(f"RFNBO designated generator(s) not found: {absent}.")
    return {"config": cfg, "electrolysers": sets["electrolysers"], "designated": keep, "chains": sets["chains"],
            "source": sets["source"], "report": report}


# ── the LP constraint ────────────────────────────────────────────────────────────


def period_keys(snapshots: Any, temporal: str, hourly_from: str) -> list[Any]:
    """Matching-period key of every snapshot: the snapshot itself (hourly) or ``(year, month)`` (monthly).

    ``auto`` is monthly before ``hourly_from`` (Art. 6(1)) and hourly from it (Art. 6(2)).
    """
    idx = pd.Index(snapshots)
    ts = idx.get_level_values(-1) if isinstance(idx, pd.MultiIndex) else idx
    if temporal == "hourly":
        return list(range(len(ts)))
    try:
        stamps = pd.DatetimeIndex(pd.to_datetime(ts))
    except (TypeError, ValueError) as exc:
        raise ValueError("RFNBO monthly matching needs date-time snapshots.") from exc
    cut = pd.Timestamp(hourly_from)
    keys: list[Any] = []
    for i, t in enumerate(stamps):
        keys.append(i if (temporal == "auto" and t >= cut) else ("m", int(t.year), int(t.month)))
    return keys


def apply_rfnbo_constraints(n: Any, plan: dict[str, Any] | None, snapshots: Any, notes: list[str]) -> None:
    """Add the Art. 6 matching constraint to ``n.model`` (call inside ``extra_functionality``).

    One row per matching period ``T``: ``sum_{t in T} w_t (sum_e p_el[e,t] - sum_g p_gen[g,t]) <= 0``
    (see the module docstring). Hourly periods are vectorised into a single constraint block
    ``rfnbo_hourly``; each monthly period is its own row in ``rfnbo_monthly``. With rolling horizon the
    periods are cut at the window edge (a month spanning two windows is matched per window).
    """
    if not plan:
        return
    cfg = plan["config"]
    window = pd.Index(list(snapshots) if not isinstance(snapshots, pd.Index) else snapshots)
    if len(window) == 0:
        return
    link_p = n.model["Link-p"]
    gen_p = n.model["Generator-p"]
    ldim = next(d for d in link_p.dims if d != "snapshot")
    gdim = next(d for d in gen_p.dims if d != "snapshot")
    w = n.snapshot_weightings["generators"].reindex(window).fillna(1.0).to_numpy(dtype=float)
    keys = period_keys(window, cfg["temporal"], cfg["hourlyFrom"])
    pos = {k: [] for k in dict.fromkeys(keys)}
    for i, k in enumerate(keys):
        pos[k].append(i)
    hourly_pos = [p[0] for k, p in pos.items() if not (isinstance(k, tuple))]
    monthly = {k: p for k, p in pos.items() if isinstance(k, tuple)}
    ely = list(plan["electrolysers"])
    des = list(plan["designated"])
    snap_dim_names = [d for d in link_p.dims if d == "snapshot"]
    if not snap_dim_names:
        raise ValueError("RFNBO matching: the Link-p variable has no snapshot dimension.")

    def _energy(var: Any, dim: str, names: list[str], positions: list[int]) -> Any:
        sel = var.sel({dim: names}).isel(snapshot=positions)
        weights = xr_weights(w[positions], sel)
        return (sel * weights)

    def xr_weights(vals: np.ndarray, like: Any) -> Any:
        import xarray as xr

        return xr.DataArray(vals, coords={"snapshot": like.coords["snapshot"]}, dims=["snapshot"])

    if hourly_pos:
        lhs = (link_p.sel({ldim: ely}).isel(snapshot=hourly_pos).sum(ldim)
               - gen_p.sel({gdim: des}).isel(snapshot=hourly_pos).sum(gdim))
        n.model.add_constraints(lhs <= 0, name="rfnbo_hourly")
    for j, (k, positions) in enumerate(monthly.items()):
        lhs = _energy(link_p, ldim, ely, positions).sum() - _energy(gen_p, gdim, des, positions).sum()
        n.model.add_constraints(lhs <= 0, name=f"rfnbo_monthly_{k[1]}_{k[2]:02d}")
    notes.append(
        f"RFNBO matching ({cfg['temporal']}): {len(ely)} electrolyser(s) <= {len(des)} designated generator(s) "
        f"over {len(hourly_pos)} hourly and {len(monthly)} monthly period(s) (Delegated Reg. (EU) 2023/1184 Art. 6)."
    )


# ── ex-post compliance from stored series (pure pandas) ──────────────────────────


def compliance(
    snapshots: list[Any],
    electrolyser_mw: np.ndarray,
    designated_mw: np.ndarray,
    weights_h: np.ndarray,
    price: np.ndarray | None = None,
    price_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hourly and monthly compliance of an electrolyser profile against the designated generation.

    Args:
        snapshots: ISO timestamps (one per row).
        electrolyser_mw: summed ``p0`` of the electrolysers (MW).
        designated_mw: summed output of the designated generators (MW).
        weights_h: hours per row.
        price: nodal price at the electrolyser bus (EUR/MWh), optional (Art. 6(3) count).
        price_rule: ``{enabled, thresholdEurPerMwh, euaEurPerT}``.

    Returns:
        ``{hourly: {...}, monthly: {...}, months: [...], art63: {...}}`` with, per regime, the share of
        operating periods that comply, the unmatched electricity (MWh) and the matched share.
    """
    e = np.asarray(electrolyser_mw, dtype=float) * weights_h           # MWh per row
    g = np.asarray(designated_mw, dtype=float) * weights_h
    ts = pd.DatetimeIndex(pd.to_datetime(snapshots))
    tol = ATOL + RTOL * max(1.0, float(np.abs(e).max() if e.size else 0.0))
    short_h = np.maximum(e - g, 0.0)
    operating = e > tol
    df = pd.DataFrame({"e": e, "g": g, "short": short_h, "op": operating, "ym": ts.strftime("%Y-%m")})
    monthly = df.groupby("ym").agg(e=("e", "sum"), g=("g", "sum"), hours=("e", "size"), op_h=("op", "sum"), short_h=("short", "sum"))
    monthly["short_m"] = np.maximum(monthly["e"] - monthly["g"], 0.0)
    tol_m = ATOL + RTOL * max(1.0, float(monthly["e"].max() if len(monthly) else 0.0))
    m_op = monthly["e"] > tol_m
    total_e = float(e.sum())

    def _regime(short_total: float, comply: int, op: int, periods: int) -> dict[str, Any]:
        return {"periods": periods, "operatingPeriods": op, "compliantOperatingPeriods": comply,
                "compliantShareOfOperating": (comply / op) if op else 1.0,
                "unmatchedMwh": short_total, "unmatchedShareOfElectrolyserEnergy": (short_total / total_e) if total_e > 0 else 0.0,
                "matchedMwh": total_e - short_total}

    h_comply = int(((short_h <= tol) & operating).sum())
    hourly = _regime(float(short_h.sum()), h_comply, int(operating.sum()), len(e))
    monthly_reg = _regime(float(monthly["short_m"].sum()), int(((monthly["short_m"] <= tol_m) & m_op).sum()), int(m_op.sum()), len(monthly))
    months = [{"month": k, "electrolyserMwh": float(r.e), "designatedMwh": float(r.g), "unmatchedHourlyMwh": float(r.short_h),
               "unmatchedMonthlyMwh": float(r.short_m), "operatingHours": int(r.op_h)} for k, r in monthly.iterrows()]
    art63: dict[str, Any] = {"enabled": False}
    if price is not None and price_rule and price_rule.get("enabled"):
        thr = float(price_rule.get("thresholdEurPerMwh", PRICE_RULE_EUR_PER_MWH))
        if price_rule.get("euaEurPerT") is not None:
            thr = max(thr, PRICE_RULE_EUA_FACTOR * float(price_rule["euaEurPerT"]))
        cheap = np.asarray(price, dtype=float) <= thr
        art63 = {"enabled": True, "thresholdEurPerMwh": thr, "operatingPeriodsAtOrBelow": int((cheap & operating).sum()),
                 "mwhAtOrBelow": float(e[cheap].sum()),
                 "unmatchedMwhHourlyAfterRule": float(short_h[~cheap].sum())}
    return {"hourly": hourly, "monthly": monthly_reg, "months": months, "art63": art63}


def grid_alternatives(
    res_energy_mwh: float,
    total_energy_mwh: float,
    emissions_t: float,
    load_mwh: float,
    cfg: dict[str, Any],
    electrolyser_hours: float,
    hours: float,
) -> dict[str, Any]:
    """Art. 4(1) / 4(2) grid-electricity alternatives as reported-only checks.

    Args:
        res_energy_mwh: renewable generation (MWh).
        total_energy_mwh: all generation (MWh).
        emissions_t: system CO2 over the horizon (t).
        load_mwh: electricity demand (MWh), the intensity denominator.
        cfg: normalised config.
        electrolyser_hours: full-load-equivalent hours used by the electrolysers (for the 4(1) hour cap).
        hours: hours in the horizon.

    Returns:
        ``{art41: {...}, art42: {...}}`` with the measured value, threshold and ``pass``.
    """
    ga = cfg["gridAlternatives"]
    share = res_energy_mwh / total_energy_mwh if total_energy_mwh > 0 else 0.0
    intensity = (emissions_t / load_mwh) * G_PER_MJ_PER_T_PER_MWH if load_mwh > 0 else float("nan")
    cap_hours = hours * share
    return {
        "art41": {"article": "Art. 4(1)", "renewableShare": share, "threshold": ga["renewableShareThreshold"],
                  "pass": bool(share > ga["renewableShareThreshold"]),
                  "maxFullLoadHours": cap_hours, "electrolyserFullLoadHours": electrolyser_hours,
                  "note": "Needs a zone share above 90 % in the previous calendar year; the production-hours cap is share x hours. Reported only."},
        "art42": {"article": "Art. 4(2)", "emissionIntensityGPerMj": intensity, "threshold": ga["intensityThresholdGPerMj"],
                  "pass": bool(intensity < ga["intensityThresholdGPerMj"]) if not math.isnan(intensity) else None,
                  "note": "Also needs a PPA and Art. 6-7 correlation. Intensity = system CO2 / electricity demand in gCO2/MJ (indicative). Reported only."},
    }
