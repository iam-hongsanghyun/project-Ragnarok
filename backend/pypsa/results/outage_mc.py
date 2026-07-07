"""Thermal forced-outage Monte Carlo — outage-aware LOLE/EUE with a distribution.

A resource-adequacy study (see ``adequacy.py``) asks how the system copes with
renewable *variability*. This module asks a complementary question: how does it
cope with thermal *unavailability* — generators forced offline by unplanned
failures? It is a strict post-process (no re-solve): it samples an on/off
availability chain per thermal unit per Monte-Carlo member over the solved
network's snapshots, feeds the resulting available-generation ensemble through
the same ``compute_adequacy`` kernel used by the renewable-ensemble study, and
— because outages are a per-member draw, not just a per-snapshot probability —
also reports the *distribution* of annualised LOLE/EUE across members (P50,
P90, P95, mean, max), not just the ensemble mean.

**Two-state Markov forced-outage sampler.** Each thermal generator is modelled
as a two-state continuous-time-like chain (up / down) discretised at the
snapshot resolution, parameterised by its forced-outage rate (FOR — the
long-run probability of being on forced outage) and mean-time-to-repair (MTTR,
hours). Standard reliability-engineering identities:

Algorithm:
    Per-step repair probability (down -> up), from MTTR and the step length
    Δt (the snapshot's weight, hours) — the chain "repairs" with intensity
    1/MTTR per hour:
        $$ p_{\\text{repair}} = \\operatorname{clip}\\!\\left(\\frac{\\Delta t}{\\text{MTTR}},\\, 0,\\, 1\\right) $$
        ASCII: p_repair = clip(dt / MTTR, 0, 1)

    Per-step failure probability (up -> down), chosen so the chain's
    *stationary* down-probability equals FOR exactly (detailed balance of a
    2-state Markov chain: stationary_down = p_fail / (p_fail + p_repair) = FOR
    solved for p_fail):
        $$ p_{\\text{fail}} = p_{\\text{repair}} \\cdot \\frac{\\text{FOR}}{1-\\text{FOR}} $$
        ASCII: p_fail = p_repair * FOR / (1 - FOR)

    Initial state drawn from the stationary distribution (so the ensemble is
    already "warmed up" at t=0 rather than biased to all-up):
        $$ P(\\text{up at } t=0) = 1 - \\text{FOR} $$
        ASCII: P(up@0) = 1 - FOR

    Symbols: Δt = snapshot weight (h); MTTR = mean time to repair (h); FOR =
    forced-outage rate, dimensionless in [0, 1); p_repair, p_fail =
    per-step transition probabilities, dimensionless in [0, 1].

**Reliability metrics with a distribution.** Given the (M, G, T) availability
mask and each generator's rated MW, available generation per member/snapshot
is:
        $$ \\text{avail}_{m,t} = \\sum_g p_{nom,g} \\cdot pmax_{g,t} \\cdot \\text{mask}_{m,g,t} $$
        ASCII: avail[m,t] = sum_g p_nom[g] * p_max_pu[g,t] * mask[m,g,t]

    The ensemble-aggregate LOLE/EENS come from ``compute_adequacy`` (shared
    kernel with the renewable-ensemble study). In addition, **per member** m,
    this module computes that member's own annualised loss-of-load hours and
    unserved energy:
        $$ \\text{LOLE}_m = \\Big(\\sum_t w_t \\cdot \\mathbb{1}[\\text{avail}_{m,t} < \\text{load}_t]\\Big) \\cdot s $$
        $$ \\text{EUE}_m = \\Big(\\sum_t w_t \\cdot \\max(\\text{load}_t - \\text{avail}_{m,t},\\, 0)\\Big) \\cdot s $$
        ASCII: LOLE_m = sum_t w_t * 1[avail<load] * s ; EUE_m = sum_t w_t * max(load-avail,0) * s
        (s = annualising scale, 8760 / modelled_hours)

    Quantiles of {LOLE_m} and {EUE_m} across m give the P50/P90/P95/mean/max
    "outputs are a distribution" headline.

Symbols: p_nom (MW) rated capacity (p_nom_opt when expansion solved it);
pmax (dimensionless, 0-1) the switchable ``p_max_pu`` availability signal;
w_t (h) snapshot weight; load_t (MW) system demand.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..constants import carrier_color
from .adequacy import compute_adequacy, generate_renewable_ensemble

_log = logging.getLogger("pypsa.solver")

# Carrier-name substrings treated as variable (non-dispatchable) renewables —
# not subject to forced outage (their unavailability is intermittency, not
# FOR) unless includeRenewableEnsemble explicitly perturbs them separately.
# Mirrors network/reserves.py's _VARIABLE_RENEWABLE_MARKERS.
_VARIABLE_RENEWABLE_MARKERS = ("solar", "pv", "wind")

_EPS = 1e-9

_DEFAULT_N_MEMBERS = 200
_DEFAULT_SEED = 42
_DEFAULT_FOR = 0.05
_DEFAULT_MTTR_HOURS = 48.0
_N_HISTOGRAM_BINS = 12


def _is_variable_renewable(carrier: str) -> bool:
    key = str(carrier).strip().lower()
    return any(marker in key for marker in _VARIABLE_RENEWABLE_MARKERS)


def _snapshot_label(snapshot: Any) -> str:
    """ISO-format a snapshot, handling multi-investment-period tuples."""
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        _period, timestep = snapshot
        return pd.Timestamp(timestep).isoformat() if not isinstance(timestep, str) else timestep
    try:
        return pd.Timestamp(snapshot).isoformat()
    except Exception:
        return str(snapshot)


def sample_outage_masks(
    for_rates: np.ndarray,
    mttr_hours: np.ndarray,
    weights: np.ndarray,
    *,
    n_members: int,
    seed: int,
) -> np.ndarray:
    """Two-state Markov up/down chains for a fleet of generators.

    Args:
        for_rates: (G,) forced-outage rate per generator, in [0, 1).
        mttr_hours: (G,) mean time to repair per generator, hours (> 0).
        weights: (T,) snapshot weight (hours) — the per-step Δt of the chain.
        n_members: Number of Monte-Carlo members M.
        seed: RNG seed (reproducible; one ``default_rng`` for the whole draw).

    Returns:
        Boolean array (M, G, T), True where the unit is UP (available).

    Algorithm:
        See module docstring. One shared RNG draws, per member per generator,
        the t=0 state from the stationary distribution and then a uniform
        draw per subsequent step compared against p_repair (if down) or
        p_fail (if up) to decide whether the state flips.
    """
    for_rates = np.asarray(for_rates, dtype=float)
    mttr_hours = np.asarray(mttr_hours, dtype=float)
    weights = np.asarray(weights, dtype=float)
    G = for_rates.shape[0]
    T = weights.shape[0]
    if G == 0 or T == 0 or n_members <= 0:
        return np.ones((max(0, n_members), G, T), dtype=bool)

    rng = np.random.default_rng(seed)

    for_rates = np.clip(for_rates, 0.0, 0.999999)
    mttr_hours = np.where(mttr_hours > 0, mttr_hours, _DEFAULT_MTTR_HOURS)

    # Per-step transition probabilities, shape (G, T): p_repair from Δt/MTTR,
    # p_fail scaled so the chain's stationary down-probability equals FOR.
    p_repair = np.clip(weights[None, :] / mttr_hours[:, None], 0.0, 1.0)  # (G, T)
    # p_fail keeps the ratio p_fail/p_repair = FOR/(1-FOR), which fixes the chain's
    # stationary down-probability at exactly FOR. When the requested p_fail would
    # exceed 1 (high FOR + large Δt/MTTR), clipping p_fail ALONE breaks that ratio
    # and pulls the equilibrium toward 0.5 — UNDERSTATING outage risk (the wrong
    # direction for a risk tool). Instead scale BOTH rates down so the larger
    # equals 1, preserving the ratio and hence the stationary FOR (repairs just
    # become correspondingly stickier).
    p_fail = p_repair * (for_rates / (1.0 - for_rates))[:, None]  # (G, T), may exceed 1
    overflow = np.maximum(1.0, p_fail)  # > 1 only where p_fail > 1
    p_fail = p_fail / overflow
    p_repair = p_repair / overflow

    mask = np.empty((n_members, G, T), dtype=bool)
    # t = 0: draw from the stationary distribution (up with prob 1 - FOR).
    u0 = rng.random((n_members, G))
    up = u0 >= for_rates[None, :]  # (M, G) — True == up
    mask[:, :, 0] = up

    for t in range(1, T):
        draw = rng.random((n_members, G))
        # If currently up: flips down when draw < p_fail[:, t]. If currently
        # down: flips up (repairs) when draw < p_repair[:, t].
        flip_down = up & (draw < p_fail[None, :, t])
        flip_up = (~up) & (draw < p_repair[None, :, t])
        up = np.where(flip_down, False, np.where(flip_up, True, up))
        mask[:, :, t] = up

    return mask


def _per_member_metrics(
    available: np.ndarray,
    load: np.ndarray,
    weights: np.ndarray,
    *,
    annual_scale: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-member annualised LOLE (h/yr) and EUE (MWh/yr).

    Args:
        available: (M, T) available generation (MW) per member/snapshot.
        load: (T,) demand (MW).
        weights: (T,) snapshot weight (h).
        annual_scale: 8760 / modelled_hours.

    Returns:
        (lole_per_member, eue_per_member), each shape (M,).
    """
    shortfall = np.clip(load[None, :] - available, 0.0, None)  # (M, T)
    short_flag = shortfall > _EPS
    lole_per_member = (short_flag * weights[None, :]).sum(axis=1) * annual_scale
    eue_per_member = (shortfall * weights[None, :]).sum(axis=1) * annual_scale
    return lole_per_member, eue_per_member


def _distribution(values: np.ndarray) -> dict[str, float]:
    """P50/P90/P95/mean/max of a per-member metric array."""
    if values.size == 0:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "p50": round(float(np.percentile(values, 50)), 3),
        "p90": round(float(np.percentile(values, 90)), 3),
        "p95": round(float(np.percentile(values, 95)), 3),
        "mean": round(float(values.mean()), 3),
        "max": round(float(values.max()), 3),
    }


def _eue_histogram(eue_per_member: np.ndarray, n_bins: int = _N_HISTOGRAM_BINS) -> list[dict[str, Any]]:
    """Small histogram of per-member EUE (MWh) for the UI."""
    if eue_per_member.size == 0:
        return []
    lo, hi = float(eue_per_member.min()), float(eue_per_member.max())
    if hi - lo < _EPS:
        # Degenerate (all members identical, e.g. an overbuilt system at 0) —
        # a single bin still conveys the (trivial) distribution.
        return [{"bin": round(lo, 3), "count": int(eue_per_member.size)}]
    counts, edges = np.histogram(eue_per_member, bins=n_bins, range=(lo, hi))
    return [
        {"bin": round(float(edges[i]), 3), "count": int(counts[i])}
        for i in range(len(counts))
    ]


def _by_carrier_lost_load(
    network: pypsa.Network,
    thermal_names: list[str],
    thermal_carriers: list[str],
    thermal_cap: np.ndarray,
    mask: np.ndarray,
    shortfall: np.ndarray,
    short_flag: np.ndarray,
    weights: np.ndarray,
    *,
    annual_scale: float,
) -> list[dict[str, Any]]:
    """Attribute unserved energy to the carriers that were out, heuristically.

    In each (member, snapshot) with a shortfall, the outaged thermal MW is
    split across carriers by their share of total outaged thermal MW at that
    (member, snapshot); that share of the snapshot's shortfall energy is
    credited to each carrier. Snapshots where nothing thermal is out (the
    shortfall is driven purely by load exceeding total nameplate, e.g. an
    undersized system with no outages at all) are not attributable to any
    carrier and are silently excluded from this breakdown — the aggregate EUE
    in ``eueDistribution`` still counts them.
    """
    if not thermal_names or not short_flag.any():
        return []
    M, G, T = mask.shape
    down = ~mask  # (M, G, T) True where out
    outaged_mw = thermal_cap[None, :, None] * down  # (M, G, T) MW out, per unit
    total_outaged = outaged_mw.sum(axis=1)  # (M, T)

    totals: dict[str, float] = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        for gi, carrier in enumerate(thermal_carriers):
            share = np.where(total_outaged > _EPS, outaged_mw[:, gi, :] / total_outaged, 0.0)  # (M, T)
            credited = share * shortfall * weights[None, :] * annual_scale  # (M, T) MWh/yr-scaled contribution
            total_mwh = float(credited.sum()) / M if M else 0.0
            if total_mwh > _EPS:
                totals[carrier] = totals.get(carrier, 0.0) + total_mwh

    return [
        {"label": c, "value": round(v, 1), "color": carrier_color(network, c)}
        for c, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
        if v > 0.0
    ]


def build_outage_mc(
    network: pypsa.Network,
    options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Thermal forced-outage Monte Carlo, post-process, over a solved network.

    Reads ``options["outageMcConfig"]``; returns ``None`` when the feature is
    disabled/absent, the network has no successful solve, there are no
    snapshots/loads, or there are no thermal (non-variable-renewable)
    generators to sample outages over.

    Args:
        network: solved ``pypsa.Network``.
        options: run options; reads the ``outageMcConfig`` block.

    Returns:
        The ``"outageMc"`` payload dict (see module docstring for the
        contract), or ``None``.
    """
    cfg = (options or {}).get("outageMcConfig") or {}
    if not bool(cfg.get("enabled")):
        return None
    if not getattr(network, "is_solved", False):
        return None

    snapshots = network.snapshots
    T = len(snapshots)
    if T == 0 or len(network.loads) == 0:
        return None

    n_members = int(cfg.get("nMembers", _DEFAULT_N_MEMBERS) or _DEFAULT_N_MEMBERS)
    seed = int(cfg.get("seed", _DEFAULT_SEED) if cfg.get("seed") is not None else _DEFAULT_SEED)
    for_fallback = float(cfg.get("forcedOutageRate", _DEFAULT_FOR) if cfg.get("forcedOutageRate") is not None else _DEFAULT_FOR)
    mttr_fallback = float(cfg.get("mttrHours", _DEFAULT_MTTR_HOURS) if cfg.get("mttrHours") is not None else _DEFAULT_MTTR_HOURS)
    include_renewable_ensemble = bool(cfg.get("includeRenewableEnsemble", False))

    if n_members <= 0:
        return None

    gens = network.generators
    if len(gens) == 0:
        return None

    pmax = network.get_switchable_as_dense("Generator", "p_max_pu")
    cap_col = "p_nom_opt" if "p_nom_opt" in gens.columns else "p_nom"

    thermal_names: list[str] = []
    thermal_cap_list: list[float] = []
    thermal_for_list: list[float] = []
    thermal_mttr_list: list[float] = []
    thermal_carrier_list: list[str] = []

    renewable_deterministic = np.zeros(T)  # renewables at solved (deterministic) availability
    renewable_names: list[str] = []
    renewable_caps: list[float] = []
    renewable_base_cf: list[np.ndarray] = []

    for g in gens.index:
        name = str(g)
        if name.startswith("load_shedding_"):
            continue
        carrier = str(gens.at[g, "carrier"]) if "carrier" in gens.columns else ""
        cap = float(gens.at[g, cap_col]) if cap_col in gens.columns else 0.0
        if cap <= 0:
            continue
        if _is_variable_renewable(carrier):
            if include_renewable_ensemble:
                renewable_names.append(name)
                renewable_caps.append(cap)
                renewable_base_cf.append(pmax[g].to_numpy())
            else:
                renewable_deterministic += cap * pmax[g].to_numpy()
            continue
        thermal_names.append(name)
        thermal_cap_list.append(cap)
        thermal_carrier_list.append(carrier)
        for_rate = for_fallback
        if "forced_outage_rate" in gens.columns:
            raw = gens.at[g, "forced_outage_rate"]
            if pd.notna(raw) and float(raw) > 0:
                for_rate = float(raw)
        mttr = mttr_fallback
        if "mean_time_to_repair" in gens.columns:
            raw = gens.at[g, "mean_time_to_repair"]
            if pd.notna(raw) and float(raw) > 0:
                mttr = float(raw)
        thermal_for_list.append(for_rate)
        thermal_mttr_list.append(mttr)

    if not thermal_names:
        return None

    thermal_cap = np.asarray(thermal_cap_list, dtype=float)
    for_rates = np.asarray(thermal_for_list, dtype=float)
    mttr_hours = np.asarray(thermal_mttr_list, dtype=float)

    weights = network.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0).to_numpy()
    load = network.get_switchable_as_dense("Load", "p_set").sum(axis=1).reindex(snapshots).fillna(0.0).to_numpy()

    thermal_pmax = pmax.reindex(columns=thermal_names).to_numpy()  # (T, G)

    mask = sample_outage_masks(for_rates, mttr_hours, weights, n_members=n_members, seed=seed)  # (M, G, T)

    # Available thermal generation per member/snapshot: p_nom * p_max_pu * mask,
    # summed over generators. thermal_pmax is (T, G); broadcast against mask (M, G, T).
    available = np.einsum("g,tg,mgt->mt", thermal_cap, thermal_pmax, mask)

    if include_renewable_ensemble and renewable_names:
        for i, (name, cap, base) in enumerate(zip(renewable_names, renewable_caps, renewable_base_cf)):
            ens = generate_renewable_ensemble(base, n_members=n_members, seed=seed + 1000 + i)
            available += cap * ens
    else:
        available += renewable_deterministic[None, :]

    modeled_hours = float(weights.sum())
    metrics = compute_adequacy(available, load, weights, modeled_hours=modeled_hours)
    annual_scale = metrics["annualScale"]

    lole_per_member, eue_per_member = _per_member_metrics(
        available, load, weights, annual_scale=annual_scale
    )
    lole_dist = _distribution(lole_per_member)
    eue_dist = _distribution(eue_per_member)

    labels = [_snapshot_label(s) for s in snapshots]
    lolp_series = [
        {"label": labels[t], "value": round(float(metrics["loloProbability"][t]), 5)}
        for t in range(T)
    ]

    shortfall = np.clip(load[None, :] - available, 0.0, None)
    short_flag = shortfall > _EPS
    by_carrier_lost_load = _by_carrier_lost_load(
        network, thermal_names, thermal_carrier_list, thermal_cap, mask,
        shortfall, short_flag, weights, annual_scale=annual_scale,
    )

    eue_histogram = _eue_histogram(eue_per_member)

    summary = [
        {
            "label": "LOLE (P50)",
            "value": f"{lole_dist['p50']:,.2f} h/yr",
            "detail": f"aggregate (mean-member) LOLE {metrics['lole']:,.2f} h/yr across {n_members} samples",
        },
        {
            "label": "LOLE (P95)",
            "value": f"{lole_dist['p95']:,.2f} h/yr",
            "detail": f"max {lole_dist['max']:,.2f} h/yr",
        },
        {
            "label": "EUE (P50)",
            "value": f"{eue_dist['p50']:,.1f} MWh/yr",
            "detail": f"aggregate EENS {metrics['eens']:,.1f} MWh/yr across {n_members} samples",
        },
        {
            "label": "EUE (P95)",
            "value": f"{eue_dist['p95']:,.1f} MWh/yr",
            "detail": f"max {eue_dist['max']:,.1f} MWh/yr",
        },
        {
            "label": "Thermal units sampled",
            "value": str(len(thermal_names)),
            "detail": f"seed {seed}, {n_members} Monte-Carlo members",
        },
    ]

    note = None
    if include_renewable_ensemble and not renewable_names:
        note = (
            "includeRenewableEnsemble was set but no variable-renewable generator "
            "was found — renewables (if any) were included at their solved "
            "(deterministic) availability."
        )

    _log.info(
        "outage_mc: %d members, %d thermal units, LOLE P50=%.2f P95=%.2f h/yr, "
        "EUE P50=%.1f P95=%.1f MWh/yr",
        n_members, len(thermal_names), lole_dist["p50"], lole_dist["p95"],
        eue_dist["p50"], eue_dist["p95"],
    )

    return {
        "enabled": True,
        "nMembers": n_members,
        "seed": seed,
        "loleDistribution": lole_dist,
        "eueDistribution": eue_dist,
        "lolpSeries": lolp_series,
        "byCarrierLostLoad": by_carrier_lost_load,
        "eueHistogram": eue_histogram,
        "summary": summary,
        "note": note,
    }
