"""Correlated multi-driver Monte Carlo — one-factor "stress" model for reliability.

Independent per-driver draws (as in ``adequacy.py``'s renewable ensemble or
``outage_mc.py``'s forced-outage sampler) miss the *co-movement* that dominates
real physical risk: a cold-calm event is high load AND low wind AND low hydro
inflow, all at once, driven by the same synoptic weather pattern. This module
is a strict post-process (no re-solve) that adds that co-movement with the
smallest model that can express it: a **one-factor stress model**, not a full
covariance matrix the user would have to author.

**One-factor model.** Each Monte-Carlo member m draws a single common "stress"
factor z_m — the severity of a cold-snap/heatwave-type event for that member —
plus independent idiosyncratic noise per driver. Drivers respond to the same
z with signed sensitivities (demand rises, renewables and hydro inflow fall)
so members with a large z look like a coincident cold-calm/dry event:

Algorithm:
    Common factor and idiosyncratic noise, one draw per member m (M members),
    all i.i.d. standard normal from a single shared RNG:
        $$ z_m \\sim \\mathcal{N}(0, 1), \\qquad \\varepsilon_{m,d} \\sim \\mathcal{N}(0, 1) $$
        ASCII: z_m ~ N(0,1); eps_m_d ~ N(0,1) for each driver d

    Per-driver multiplier, linear response to the common factor plus
    idiosyncratic noise (sensitivities and idiosyncratic std are the model's
    only free parameters):
        $$ \\text{load\\_mult}_m = 1 + s_L \\cdot z_m + \\sigma_L \\cdot \\varepsilon_{m,L} $$
        $$ \\text{cf\\_mult}_m = \\operatorname{clip}\\!\\left(1 - s_R \\cdot z_m + \\sigma_R \\cdot \\varepsilon_{m,R},\\, 0,\\, \\infty\\right) $$
        $$ \\text{inflow\\_mult}_m = \\operatorname{clip}\\!\\left(1 - s_I \\cdot z_m + \\sigma_I \\cdot \\varepsilon_{m,I},\\, 0,\\, \\infty\\right) $$
        ASCII: load_mult = 1 + s_L*z + sigma_L*eps_L
               cf_mult    = clip(1 - s_R*z + sigma_R*eps_R, 0, inf)
               inflow_mult = clip(1 - s_I*z + sigma_I*eps_I, 0, inf)

    Renewables and hydro inflow carry a MINUS sign on z (a positive stress
    event — e.g. a winter anticyclone — depresses wind/solar output and
    catchment inflow while raising heating demand); load carries a PLUS sign.
    This single shared z is what correlates the three drivers across members:
    a high-z member simultaneously has high load and low renewable/inflow
    multipliers, without ever constructing an explicit correlation matrix.

    Available generation per member/snapshot, reusing the solved network's
    dispatch shape: renewables scaled by the member's cf multiplier, thermal
    ("firm") at its solved (deterministic) availability, hydro storage output
    scaled by the member's inflow multiplier (see the v1 simplification note
    below), inflow-less storage (e.g. batteries) at its solved discharge
    unscaled (not weather-driven, so no stress multiplier applies), load
    scaled by the member's load multiplier:
        $$ \\text{avail}_{m,t} = \\text{firm}_t + \\text{cf\\_mult}_m \\sum_r p_{nom,r}\\, pmax_{r,t}
           + \\text{inflow\\_mult}_m \\sum_h \\text{hydro\\_out}_{h,t}
           + \\sum_b \\text{storage\\_out}_{b,t} $$
        $$ \\text{load}_{m,t} = \\text{load\\_mult}_m \\cdot \\text{load}_t $$
        ASCII: avail[m,t] = firm[t] + cf_mult[m]*sum_r(p_nom[r]*pmax[r,t])
                            + inflow_mult[m]*sum_h(hydro_out[h,t])
                            + sum_b(storage_out[b,t])
               load[m,t]  = load_mult[m] * load[t]

    hydro_out and storage_out are the solved storage-unit dispatch clipped at
    zero from below (max(p, 0), MW): only discharge counts as available
    generation. A net-charging snapshot contributes ZERO to availability — a
    charging unit is not supplying — rather than subtracting the charging
    draw (charging is discretionary and would be curtailed under scarcity).

    Reliability metrics reuse ``adequacy.compute_adequacy`` for the ensemble
    aggregate and ``outage_mc``'s per-member LOLE/EUE + quantile machinery for
    the DISTRIBUTION (P50/P90/P95/mean/max across members) — the same
    "outputs are a distribution, not a point estimate" pattern as the forced-
    outage study, composing independently of it (this module perturbs
    weather/load/inflow; ``outage_mc`` perturbs unit availability; running
    both together would require sampling both dimensions per member, which is
    out of scope for v1 — see the module-level simplification notes below).

Symbols: z_m (dimensionless, per member) common stress factor; s_L, s_R, s_I
(dimensionless) sensitivities — response per unit of stress; sigma_L, sigma_R,
sigma_I (dimensionless) idiosyncratic noise std; eps_{m,d} (dimensionless)
per-member per-driver idiosyncratic noise; p_nom (MW) rated renewable
capacity; pmax (dimensionless, 0-1) solved availability signal; hydro_out
(MW) solved hydro storage-unit dispatch.

**v1 simplifications (deliberate, stated up front):**

1. **Hydro inflow.** A rigorous inflow-to-output mapping would re-solve the
   dispatch (a storage unit's state of charge and hence output in later hours
   depends on today's inflow — a path-dependent recursion). v1 stays a pure
   post-process: it scales the storage unit's *solved* dispatch (``p``, MW,
   whatever sign convention PyPSA used for net discharge) by the inflow
   multiplier directly, as a proxy for "less inflow => proportionally less
   hydro output available that snapshot". This is a **first-order
   approximation** that ignores reservoir buffering (a well-stocked reservoir
   would smooth a short dry spell, so this OVERSTATES the hydro sensitivity
   for systems with large storage relative to inflow variability) and
   ignores the inflow's own re-optimisation of the dispatch schedule. A
   storage unit whose solved dispatch is net-charging (negative) at a
   snapshot contributes ZERO to available generation at that snapshot (the
   dispatch is clipped at 0 before scaling): charging is not "available
   generation", and treating the charging draw as an obligation would
   overstate scarcity — under stress the unit would simply stop charging.
   Storage units with no inflow signal (e.g. batteries) are not
   weather-driven, so their solved discharge (same clip at 0) enters
   availability UNSCALED — no stress multiplier applies, but their firm
   contribution must not be dropped.
2. **Fuel-price correlation -> cost distribution.** A cold-snap event
   typically also spikes fuel/gas prices, which would shift the *cost*
   distribution — but that requires a per-sample re-solve (each member's
   price shock changes the merit order), which v1 explicitly does NOT do.
   This is deferred to a v2 re-solve harness; v1 covers only the
   availability drivers (load, renewable CF, hydro inflow) that drive the
   *reliability* (LOLE/EUE) distribution, not cost.
3. **Composition with forced outages.** This module does not draw unit
   forced-outage states; it is independent of and composes with
   ``outage_mc`` only in the sense that a caller could run both studies side
   by side (each returns its own distribution). It does not attempt a joint
   draw across both dimensions in v1.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from .adequacy import compute_adequacy
from .outage_mc import _distribution, _eue_histogram

_log = logging.getLogger("pypsa.solver")

# Carrier-name substrings treated as variable (non-dispatchable) renewables —
# mirrors outage_mc.py's / reserves.py's _VARIABLE_RENEWABLE_MARKERS.
_VARIABLE_RENEWABLE_MARKERS = ("solar", "pv", "wind")

_EPS = 1e-9

_DEFAULT_N_MEMBERS = 200
_DEFAULT_SEED = 42
_DEFAULT_LOAD_SENSITIVITY = 0.15
_DEFAULT_RENEWABLE_SENSITIVITY = 0.3
_DEFAULT_INFLOW_SENSITIVITY = 0.2
_DEFAULT_LOAD_STD = 0.05
_DEFAULT_RENEWABLE_STD = 0.1
_DEFAULT_INFLOW_STD = 0.1


def _is_variable_renewable(carrier: str) -> bool:
    key = str(carrier).strip().lower()
    return any(marker in key for marker in _VARIABLE_RENEWABLE_MARKERS)


def sample_driver_multipliers(
    cfg: dict[str, Any],
    seed: int,
    n_members: int,
) -> dict[str, np.ndarray]:
    """Draw the common stress factor and per-driver correlated multipliers.

    Args:
        cfg: ``correlatedSamplingConfig`` dict; reads sensitivity/std knobs
            (missing keys fall back to the module defaults).
        seed: RNG seed (one shared ``default_rng`` draws z and all three
            idiosyncratic noise vectors, in that order, for reproducibility).
        n_members: Number of Monte-Carlo members M.

    Returns:
        Dict with keys ``"z"``, ``"load_mult"``, ``"cf_mult"``,
        ``"inflow_mult"``, each a ``(M,)`` array. Renewable and inflow
        multipliers are clipped to ``[0, None)`` (they scale a physical
        quantity that cannot go negative); load multiplier is left unclipped
        (a demand multiplier below zero would require pathological inputs —
        sensitivity/std both > 1 — and is not clipped so a caller can see it
        rather than have it silently masked).

    Algorithm:
        See module docstring. z and each epsilon are independent standard
        normals from one shared RNG (z first, then load/renewable/inflow
        idiosyncratic noise, in that fixed order) so the draw is reproducible
        and stable under changes elsewhere in the call graph.
    """
    if n_members <= 0:
        return {
            "z": np.zeros(0),
            "load_mult": np.zeros(0),
            "cf_mult": np.zeros(0),
            "inflow_mult": np.zeros(0),
        }
    rng = np.random.default_rng(seed)

    load_sensitivity = float(cfg.get("loadSensitivity", _DEFAULT_LOAD_SENSITIVITY) if cfg.get("loadSensitivity") is not None else _DEFAULT_LOAD_SENSITIVITY)
    renewable_sensitivity = float(cfg.get("renewableSensitivity", _DEFAULT_RENEWABLE_SENSITIVITY) if cfg.get("renewableSensitivity") is not None else _DEFAULT_RENEWABLE_SENSITIVITY)
    inflow_sensitivity = float(cfg.get("inflowSensitivity", _DEFAULT_INFLOW_SENSITIVITY) if cfg.get("inflowSensitivity") is not None else _DEFAULT_INFLOW_SENSITIVITY)
    load_std = float(cfg.get("loadStd", _DEFAULT_LOAD_STD) if cfg.get("loadStd") is not None else _DEFAULT_LOAD_STD)
    renewable_std = float(cfg.get("renewableStd", _DEFAULT_RENEWABLE_STD) if cfg.get("renewableStd") is not None else _DEFAULT_RENEWABLE_STD)
    inflow_std = float(cfg.get("inflowStd", _DEFAULT_INFLOW_STD) if cfg.get("inflowStd") is not None else _DEFAULT_INFLOW_STD)

    z = rng.standard_normal(n_members)
    eps_load = rng.standard_normal(n_members)
    eps_renewable = rng.standard_normal(n_members)
    eps_inflow = rng.standard_normal(n_members)

    load_mult = 1.0 + load_sensitivity * z + load_std * eps_load
    cf_mult = np.clip(1.0 - renewable_sensitivity * z + renewable_std * eps_renewable, 0.0, None)
    inflow_mult = np.clip(1.0 - inflow_sensitivity * z + inflow_std * eps_inflow, 0.0, None)

    return {
        "z": z,
        "load_mult": load_mult,
        "cf_mult": cf_mult,
        "inflow_mult": inflow_mult,
    }


def _driver_summary(multipliers: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    """Mean/P95 multiplier per driver — the compact "how far did each driver
    move" readout for the UI."""
    rows = []
    for label, key in (
        ("Demand", "load_mult"),
        ("Renewable CF", "cf_mult"),
        ("Hydro inflow", "inflow_mult"),
    ):
        values = multipliers[key]
        if values.size == 0:
            rows.append({"driver": label, "meanMultiplier": 1.0, "p95Multiplier": 1.0})
            continue
        rows.append({
            "driver": label,
            "meanMultiplier": round(float(values.mean()), 4),
            "p95Multiplier": round(float(np.percentile(values, 95)), 4),
        })
    return rows


def build_correlated_sampling(
    network: pypsa.Network,
    options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Correlated multi-driver Monte Carlo, post-process, over a solved network.

    Reads ``options["correlatedSamplingConfig"]``; returns ``None`` when the
    feature is disabled/absent, the network has no successful solve, or there
    are no snapshots/loads to build an availability-vs-load picture from.

    Args:
        network: solved ``pypsa.Network``.
        options: run options; reads the ``correlatedSamplingConfig`` block.

    Returns:
        The ``"correlatedSampling"`` payload dict (see module docstring for
        the contract), or ``None``.
    """
    cfg = (options or {}).get("correlatedSamplingConfig") or {}
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
    if n_members <= 0:
        return None

    weights = network.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0).to_numpy()
    load = network.get_switchable_as_dense("Load", "p_set").sum(axis=1).reindex(snapshots).fillna(0.0).to_numpy()

    gens = network.generators
    pmax = network.get_switchable_as_dense("Generator", "p_max_pu")
    cap_col = "p_nom_opt" if "p_nom_opt" in gens.columns else "p_nom"

    firm = np.zeros(T)
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
            renewable_names.append(name)
            renewable_caps.append(cap)
            renewable_base_cf.append(pmax[g].to_numpy())
        else:
            firm += cap * pmax[g].to_numpy()

    # Renewable base capacity factors kept PER generator (not pre-summed) so the
    # stressed availability can be clamped at each unit's nameplate below — a
    # member with cf_mult > 1 (a favourable draw) must not push any unit above
    # its p_nom, and clamping the pre-summed total would let one unit's surplus
    # mask another's shortfall.

    # Hydro inflow (v1 simplification — see module docstring, point 1): scale
    # each inflow-driven storage unit's SOLVED discharge (dispatch clipped at
    # 0 — net-charging snapshots contribute zero availability) by the
    # member's inflow multiplier, as a proxy for less/more inflow =>
    # less/more hydro output available. Storage units with no inflow signal
    # (e.g. a battery) are not weather-driven, so their solved discharge
    # (same clip at 0) enters availability UNSCALED — a battery covering a
    # scarcity snapshot must still count as supply under the stress draw.
    hydro_base = np.zeros(T)
    storage_base = np.zeros(T)  # inflow-less storage discharge, deterministic
    hydro_names: list[str] = []
    storage_names: list[str] = []
    if len(network.storage_units):
        inflow_frame = (
            network.storage_units_t.inflow
            if hasattr(network.storage_units_t, "inflow")
            else pd.DataFrame()
        )
        dispatch_frame = network.storage_units_t.p if hasattr(network.storage_units_t, "p") else pd.DataFrame()
        for s in network.storage_units.index:
            name = str(s)
            if name in dispatch_frame.columns:
                dispatch = dispatch_frame[name].reindex(snapshots).fillna(0.0).to_numpy()
            else:
                dispatch = np.zeros(T)
            is_hydro = False
            if name in inflow_frame.columns:
                inflow_series = inflow_frame[name].reindex(snapshots).fillna(0.0).to_numpy()
                is_hydro = bool(np.any(inflow_series > _EPS))
            if is_hydro:
                hydro_names.append(name)
                hydro_base += np.clip(dispatch, 0.0, None)
            else:
                storage_names.append(name)
                storage_base += np.clip(dispatch, 0.0, None)

    multipliers = sample_driver_multipliers(cfg, seed, n_members)
    load_mult = multipliers["load_mult"]
    cf_mult = multipliers["cf_mult"]
    inflow_mult = multipliers["inflow_mult"]

    # Stressed renewable availability, clamped at nameplate PER generator:
    # output_r = cap_r * min(1, cf_mult * base_cf[r,t]) — the min caps the
    # capacity factor at 1 so a >1 cf_mult can't yield output above p_nom.
    renewable_avail = np.zeros((n_members, T))
    for cap, base in zip(renewable_caps, renewable_base_cf):
        renewable_avail += cap * np.minimum(1.0, cf_mult[:, None] * base[None, :])

    # Available generation per member/snapshot: firm (deterministic) + stressed
    # renewables (nameplate-capped) + stressed hydro + inflow-less storage
    # discharge (deterministic, unscaled). Load: stressed demand.
    available = (
        firm[None, :]
        + renewable_avail
        + inflow_mult[:, None] * hydro_base[None, :]
        + storage_base[None, :]
    )
    member_load = load_mult[:, None] * load[None, :]

    modeled_hours = float(weights.sum())
    # compute_adequacy expects a single (T,) load; feed it the mean-member load
    # so the ensemble-aggregate LOLE/EENS reflect a representative demand level
    # while the per-member metrics below use each member's own stressed load
    # (the actual point of this study).
    metrics = compute_adequacy(available, load, weights, modeled_hours=modeled_hours)
    annual_scale = metrics["annualScale"]

    # Per-member LOLE/EUE, computed inline rather than via outage_mc's
    # _per_member_metrics: that helper takes a single shared (T,) load, but
    # here load itself is stressed per member (member_load is (M, T)) — the
    # correlation this whole module exists to capture — so the shortfall
    # must be computed against each member's own stressed load.
    shortfall = np.clip(member_load - available, 0.0, None)  # (M, T)
    short_flag = shortfall > _EPS
    lole_per_member = (short_flag * weights[None, :]).sum(axis=1) * annual_scale
    eue_per_member = (shortfall * weights[None, :]).sum(axis=1) * annual_scale

    lole_dist = _distribution(lole_per_member)
    eue_dist = _distribution(eue_per_member)
    eue_histogram = _eue_histogram(eue_per_member)
    driver_summary = _driver_summary(multipliers)

    summary = [
        {
            "label": "LOLE (P50)",
            "value": f"{lole_dist['p50']:,.2f} h/yr",
            "detail": f"{n_members} correlated-stress samples (seed {seed})",
        },
        {
            "label": "LOLE (P95)",
            "value": f"{lole_dist['p95']:,.2f} h/yr",
            "detail": f"max {lole_dist['max']:,.2f} h/yr",
        },
        {
            "label": "EUE (P50)",
            "value": f"{eue_dist['p50']:,.1f} MWh/yr",
            "detail": f"aggregate EENS {metrics['eens']:,.1f} MWh/yr at solved (unstressed) load",
        },
        {
            "label": "EUE (P95)",
            "value": f"{eue_dist['p95']:,.1f} MWh/yr",
            "detail": f"max {eue_dist['max']:,.1f} MWh/yr",
        },
        {
            "label": "Stress drivers",
            "value": f"{len(renewable_names)} renewable, {len(hydro_names)} hydro",
            "detail": f"seed {seed}, {n_members} Monte-Carlo members",
        },
    ]

    note = None
    if not renewable_names and not hydro_names:
        note = (
            "No time-varying renewable generator or inflow-bearing storage unit "
            "was found — only demand was stressed; renewable CF and hydro inflow "
            "multipliers had nothing to scale."
        )

    _log.info(
        "correlated_sampling: %d members, %d renewables, %d hydro units, "
        "%d inflow-less storage units, "
        "LOLE P50=%.2f P95=%.2f h/yr, EUE P50=%.1f P95=%.1f MWh/yr",
        n_members, len(renewable_names), len(hydro_names), len(storage_names),
        lole_dist["p50"], lole_dist["p95"], eue_dist["p50"], eue_dist["p95"],
    )

    return {
        "enabled": True,
        "nMembers": n_members,
        "seed": seed,
        "loleDistribution": lole_dist,
        "eueDistribution": eue_dist,
        "driverSummary": driver_summary,
        "eueHistogram": eue_histogram,
        "summary": summary,
        "note": note,
    }
