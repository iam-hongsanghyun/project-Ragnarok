"""Gas + H2 co-firing: blend-share conversions, the blend-share constraint (fuel-network plants) and its plan.

Run option ``options.cofiringConfig`` (see :func:`normalise_config`)::

    {enabled, plants: [plantId...], minShare, maxShare, unit: energy|vol, scope: hourly|period,
     perPlant: {plantId: {minShare, maxShare, unit, scope}}}

A run that sets no ``cofiringConfig`` takes the limits stored with each fuel-network plant (the plant's ``blend``
block in the ``RAGNAROK_PLANTS`` registry); an explicit value, even ``{enabled: false}``, always wins.

Algorithm (volume share to energy share):
    A volume fraction of H2 ``x`` (Nm3 H2 per Nm3 gas mixture) with lower heating values per normal cubic metre
    ``L_H`` (H2) and ``L_G`` (CH4 / natural gas) is, in energy terms,
    $$ s = \\frac{x\\,L_H}{x\\,L_H + (1-x)\\,L_G},\\qquad x = \\frac{s/L_H}{s/L_H + (1-s)/L_G} $$
    ASCII: s = x*L_H / (x*L_H + (1-x)*L_G);   x = (s/L_H) / (s/L_H + (1-s)/L_G).
    ``x``, ``s`` in [0, 1] (per unit); ``L_H`` = 10.78 and ``L_G`` = 35.8 MJ/Nm3 (data file). 30 vol% H2 is 11.4 % of the energy.

Algorithm (blend-share constraint, fuel-network plant ``k``):
    ``h_t`` = H2 feeder flow (MW, LHV) and ``g_t`` = gas feeder flow (MW, LHV) into the plant's fuel bus; the share of
    H2 in the fuel burned is ``h_t / (h_t + g_t)``. With bounds ``s_min <= s <= s_max`` (energy basis):
    $$ h_t \\le s_{max}\\,(h_t+g_t),\\qquad h_t \\ge s_{min}\\,(h_t+g_t)\\qquad \\forall t \\ \\text{(hourly)} $$
    $$ \\sum_t w_t\\,h_t \\le s_{max}\\sum_t w_t\\,(h_t+g_t),\\qquad
       \\sum_t w_t\\,h_t \\ge s_{min}\\sum_t w_t\\,(h_t+g_t) \\ \\ \\text{(period)} $$
    ASCII: (1-s_max)*h_t - s_max*g_t <= 0 and s_min*g_t - (1-s_min)*h_t <= 0 for every t; the period form sums the same
    rows weighted by the snapshot weighting w_t (h). Units: h, g in MW, w in h. Hourly implies period (hourly is the
    tighter), so a period cap is never tighter than the hourly cap with the same limit.
    With rolling horizon the period is each optimisation window.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

REGISTRY_SHEET = "RAGNAROK_PLANTS"
SCOPES = ("hourly", "period")
UNITS = ("energy", "vol")
RTOL = 1.0e-9
ATOL = 1.0e-6


def vol_to_energy_share(vol_share: float, lhv_h2: float, lhv_gas: float) -> float:
    """Energy share of H2 from its volume share (both per unit); ``lhv_*`` in MJ/Nm3."""
    x = float(vol_share)
    if not 0.0 <= x <= 1.0:
        raise ValueError(f"A volume share must be in [0, 1], got {x!r}.")
    num = x * lhv_h2
    den = num + (1.0 - x) * lhv_gas
    return num / den if den > 0 else 0.0


def energy_to_vol_share(energy_share: float, lhv_h2: float, lhv_gas: float) -> float:
    """Volume share of H2 from its energy share (both per unit); ``lhv_*`` in MJ/Nm3."""
    s = float(energy_share)
    if not 0.0 <= s <= 1.0:
        raise ValueError(f"An energy share must be in [0, 1], got {s!r}.")
    num = s / lhv_h2
    den = num + (1.0 - s) / lhv_gas
    return num / den if den > 0 else 0.0


def share_to_energy(value: float, unit: str, lhv_h2: float, lhv_gas: float) -> float:
    """A blend limit entered as ``energy`` or ``vol`` share, as an energy share."""
    if unit == "energy":
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"An energy share must be in [0, 1], got {value!r}.")
        return float(value)
    if unit == "vol":
        return vol_to_energy_share(value, lhv_h2, lhv_gas)
    raise ValueError(f"unit must be one of {UNITS}, got {unit!r}.")


def _limit(raw: Any, name: str) -> float | None:
    if raw is None or raw == "":
        return None
    v = float(raw)
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"cofiringConfig {name} is a fraction in [0, 1] (0.3 = 30 %), got {raw!r}.")
    return v


def _block(raw: dict[str, Any] | None, base: dict[str, Any] | None = None) -> dict[str, Any]:
    b = {**(base or {}), **{k: v for k, v in (raw or {}).items() if v is not None and v != ""}}
    unit = str(b.get("unit") or "energy").lower()
    scope = str(b.get("scope") or "hourly").lower()
    if unit not in UNITS:
        raise ValueError(f"cofiringConfig unit must be one of {UNITS}, got {unit!r}.")
    if scope not in SCOPES:
        raise ValueError(f"cofiringConfig scope must be one of {SCOPES}, got {scope!r}.")
    lo, hi = _limit(b.get("minShare"), "minShare"), _limit(b.get("maxShare"), "maxShare")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError(f"cofiringConfig minShare {lo:g} is above maxShare {hi:g}.")
    return {"minShare": lo, "maxShare": hi, "unit": unit, "scope": scope}


def normalise_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """``options.cofiringConfig`` with every default explicit (a copy)."""
    r = dict(raw or {})
    return {
        "enabled": bool(r.get("enabled", True)), "plants": [str(p) for p in r.get("plants") or []],
        **_block(r), "perPlant": {str(k): _block(v) for k, v in (r.get("perPlant") or {}).items()},
    }


def registry_plants(model: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Parsed ``RAGNAROK_PLANTS`` rows (bad rows skipped)."""
    out = []
    for row in model.get(REGISTRY_SHEET) or []:
        try:
            reg = json.loads(str(row.get("json") or ""))
        except (TypeError, ValueError):
            continue
        if isinstance(reg, dict) and reg.get("plantId"):
            out.append(reg)
    return out


def network_plants(model: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Registry rows of the fuel-network co-firing plants."""
    return [p for p in registry_plants(model) if p.get("type") == "cofiring_network"]


def resolve_plan(model: dict[str, list[dict[str, Any]]], raw_cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    """The solve plan for ``options.cofiringConfig`` (or the plants' stored limits) or ``None`` when no limit applies.

    Raises:
        ValueError: a limit is set but names no fuel-network plant, or a plant's feeder Links are missing.
    """
    plants = network_plants(model)
    links = {str(r.get("name")) for r in model.get("links") or []}
    items: list[dict[str, Any]] = []
    if raw_cfg is not None:
        cfg = normalise_config(raw_cfg)
        if not cfg["enabled"]:
            return None
        chosen = [p for p in plants if not cfg["plants"] or p["plantId"] in cfg["plants"]]
        unknown = [p for p in cfg["plants"] if p not in {q["plantId"] for q in plants}]
        if unknown:
            raise ValueError(f"cofiringConfig.plants names no fuel-network co-firing plant: {unknown}.")
        glob = _block(raw_cfg)
        for p in chosen:
            blk = _block((raw_cfg.get("perPlant") or {}).get(p["plantId"]), glob)
            items.append({"plant": p, **blk})
    else:
        for p in plants:
            blk = _block(p.get("blend"))
            items.append({"plant": p, **blk})
    out = []
    for it in items:
        if it["minShare"] is None and it["maxShare"] is None:
            continue
        p = it["plant"]
        feeders = p["feeders"]
        miss = [n for n in (feeders["gas"], feeders["h2"]) if n not in links]
        if miss:
            raise ValueError(f"Co-firing plant {p['plantId']!r}: feeder Link(s) {miss} not found in the model.")
        lh, lg = float(p["lhvMjPerNm3"]["H2"]), float(p["lhvMjPerNm3"]["CH4"])
        lo = None if it["minShare"] is None else share_to_energy(it["minShare"], it["unit"], lh, lg)
        hi = None if it["maxShare"] is None else share_to_energy(it["maxShare"], it["unit"], lh, lg)
        out.append({"plantId": p["plantId"], "gasLink": feeders["gas"], "h2Link": feeders["h2"], "minEnergyShare": lo,
                    "maxEnergyShare": hi, "unit": it["unit"], "scope": it["scope"], "minInput": it["minShare"], "maxInput": it["maxShare"]})
    if raw_cfg is not None and not out and normalise_config(raw_cfg)["enabled"]:
        if not plants:
            raise ValueError("cofiringConfig is on but the model has no fuel-network co-firing plant.")
        raise ValueError("cofiringConfig sets no minShare or maxShare.")
    return {"items": out} if out else None


def apply_cofiring_constraints(n: Any, plan: dict[str, Any] | None, snapshots: Any, notes: list[str]) -> None:
    """Add the blend-share rows to ``n.model`` (call inside ``extra_functionality``, beside the RFNBO hook).

    Hourly: one constraint block per bound over the snapshot dimension (``cofiring_<plant>_<min|max>_hourly``);
    period: one row per bound, snapshot-weighted (``..._period``). See the module docstring for the equations.
    """
    if not plan or not plan.get("items"):
        return
    import pandas as pd
    import xarray as xr

    window = pd.Index(list(snapshots) if not isinstance(snapshots, pd.Index) else snapshots)
    if len(window) == 0:
        return
    link_p = n.model["Link-p"]
    ldim = next(d for d in link_p.dims if d != "snapshot")
    w = n.snapshot_weightings["generators"].reindex(window).fillna(1.0).to_numpy(dtype=float)
    wx = xr.DataArray(w, coords={"snapshot": window}, dims=["snapshot"])
    count = 0
    for it in plan["items"]:
        h = link_p.sel({ldim: it["h2Link"]}, drop=True).sel(snapshot=window)       # drop=True: no clashing scalar `name` coordinate
        g = link_p.sel({ldim: it["gasLink"]}, drop=True).sel(snapshot=window)
        rows = {"max": (1.0 - it["maxEnergyShare"]) * h - it["maxEnergyShare"] * g if it["maxEnergyShare"] is not None else None,
                "min": it["minEnergyShare"] * g - (1.0 - it["minEnergyShare"]) * h if it["minEnergyShare"] is not None else None}
        for bound, lhs in rows.items():
            if lhs is None:
                continue
            name = f"cofiring_{it['plantId']}_{bound}_{it['scope']}"
            if it["scope"] == "hourly":
                n.model.add_constraints(lhs <= 0, name=name)
            else:
                n.model.add_constraints((lhs * wx).sum("snapshot") <= 0, name=name)
            count += 1
        lo, hi = it["minEnergyShare"], it["maxEnergyShare"]
        txt = " and ".join(t for t in (f">= {lo * 100:.2f} %" if lo is not None else "", f"<= {hi * 100:.2f} %" if hi is not None else "") if t)
        notes.append(f"Co-firing blend share ({it['scope']}): H2 energy share of plant {it['plantId']} {txt} "
                     f"(entered as {it['unit']} share).")
    return


def hourly_shares(h2_mw: np.ndarray, gas_mw: np.ndarray, lhv_h2: float, lhv_gas: float) -> dict[str, np.ndarray]:
    """Per-snapshot H2 energy share and its volume equivalent (0 where the plant burns nothing)."""
    h2, gas = np.asarray(h2_mw, dtype=float), np.asarray(gas_mw, dtype=float)
    tot = h2 + gas
    s = np.divide(h2, tot, out=np.zeros_like(tot), where=tot > ATOL)
    num = s / lhv_h2
    den = num + (1.0 - s) / lhv_gas
    x = np.divide(num, den, out=np.zeros_like(den), where=tot > ATOL)
    return {"energy": s, "vol": x}
