"""Resource adequacy — stochastic renewable ensemble (A1) + LOLE metrics (A2).

A model is solved against one weather year; adequacy asks how the system copes
across the *distribution* of renewable outcomes. Two pure pieces:

**A1 — ensemble generator.** From a base capacity-factor series, produce N
synthetic members that keep the diurnal/seasonal *shape* (multiplicative noise
on the base, so night-time solar stays zero) but perturb the magnitude with a
controllable variability knob. Noise is AR(1) so members are temporally
autocorrelated (a calm/windy spell persists rather than flickering hour to hour).

**A2 — adequacy metrics.** Given available generation per member per snapshot
and the load, compute the reliability metrics regulators use:

    LOLP_t = P(available_t < load_t)                    (loss-of-load probability)
    LOLE   = Σ_t LOLP_t · w_t                            (loss-of-load expectation, h/period)
    EENS   = mean_m Σ_t max(load_t − avail_{m,t}, 0)·w_t (expected energy not served, MWh)

    ASCII: LOLE = sum_t P(shortfall) * weight ; EENS = E[ sum_t shortfall * weight ].

Symbols: available (MW) = firm capacity + Σ renewable capacity · CF; w_t = snapshot
weight (h). The "1 day in 10 years" yardstick is LOLE ≈ 2.4 h/yr.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

_log = logging.getLogger("pypsa.solver")


def generate_renewable_ensemble(
    base: np.ndarray,
    *,
    n_members: int = 200,
    variability: float = 0.15,
    autocorr: float = 0.8,
    seed: int = 11,
    cap: float = 1.0,
) -> np.ndarray:
    """Synthetic capacity-factor ensemble around a base series.

    Args:
        base: Base CF series (T,), values in [0, cap].
        n_members: Number of ensemble members M.
        variability: Perturbation scale (0 = identical to base; 0.3 ≈ ±30%).
        autocorr: AR(1) lag-1 correlation of the multiplicative noise (0–1).
        seed: RNG seed (reproducible).
        cap: Upper clip for CF (1.0 by default).

    Returns:
        Array (M, T), each row a member; clipped to [0, cap]. Multiplicative, so
        base-zero snapshots (e.g. solar at night) stay exactly zero.
    """
    base = np.asarray(base, dtype=float)
    T = base.shape[0]
    if T == 0 or n_members <= 0:
        return np.zeros((max(0, n_members), T))
    rng = np.random.default_rng(seed)
    rho = float(min(0.999, max(0.0, autocorr)))
    innov_std = np.sqrt(max(1e-12, 1.0 - rho * rho))  # unit stationary variance
    out = np.empty((n_members, T))
    for m in range(n_members):
        e = np.empty(T)
        e[0] = rng.standard_normal()
        for t in range(1, T):
            e[t] = rho * e[t - 1] + innov_std * rng.standard_normal()
        out[m] = np.clip(base * (1.0 + variability * e), 0.0, cap)
    return out


def ensemble_stats(base: np.ndarray, ensemble: np.ndarray) -> dict[str, Any]:
    """Similarity + spread of an ensemble versus its base series."""
    base = np.asarray(base, dtype=float)
    M = ensemble.shape[0]
    if M == 0:
        return {"members": 0, "meanR2": 0.0, "meanRmse": 0.0, "band": []}
    # Mean R² and RMSE of members vs the base.
    r2s, rmses = [], []
    denom = float(((base - base.mean()) ** 2).sum())
    for m in range(M):
        resid = ensemble[m] - base
        rmses.append(float(np.sqrt((resid ** 2).mean())))
        if denom > 1e-12:
            r2s.append(1.0 - float((resid ** 2).sum()) / denom)
    p10 = np.percentile(ensemble, 10, axis=0)
    p50 = np.percentile(ensemble, 50, axis=0)
    p90 = np.percentile(ensemble, 90, axis=0)
    return {
        "members": M,
        "meanR2": round(float(np.mean(r2s)), 4) if r2s else 1.0,
        "meanRmse": round(float(np.mean(rmses)), 5),
        "band": [
            {"p10": round(float(p10[t]), 4), "p50": round(float(p50[t]), 4),
             "p90": round(float(p90[t]), 4)}
            for t in range(base.shape[0])
        ],
    }


def compute_adequacy(
    available: np.ndarray,   # (M, T) available generation (MW) per member/snapshot
    load: np.ndarray,        # (T,) demand (MW)
    weights: np.ndarray,     # (T,) snapshot weights (h)
    *,
    modeled_hours: float | None = None,
) -> dict[str, Any]:
    """Loss-of-load metrics from an availability ensemble.

    LOLP per snapshot is the share of members short; LOLE weights it by hours
    and annualises (scales the modeled window up to 8760 h). EENS is the
    expected unserved energy across members.
    """
    available = np.asarray(available, dtype=float)
    load = np.asarray(load, dtype=float)
    weights = np.asarray(weights, dtype=float)
    M, T = available.shape if available.ndim == 2 else (0, load.shape[0])
    if M == 0 or T == 0:
        return {"lole": 0.0, "eens": 0.0, "eue": 0.0, "loloProbability": [],
                "worstPeriods": [], "annualScale": 1.0}

    shortfall = np.clip(load[None, :] - available, 0.0, None)  # (M, T)
    short_flag = shortfall > 1e-9
    lolp = short_flag.mean(axis=0)  # (T,) probability of loss of load per snapshot

    window_hours = float((weights).sum()) if weights.size else float(T)
    total = float(modeled_hours) if modeled_hours else window_hours
    annual_scale = 8760.0 / total if total > 0 else 1.0

    lole_window = float((lolp * weights).sum())          # hours in the modeled window
    lole = lole_window * annual_scale                    # scaled to a year
    eens_window = float((shortfall * weights[None, :]).sum(axis=1).mean())  # MWh, mean over members
    eens = eens_window * annual_scale

    order = np.argsort(-lolp)
    worst = [
        {"snapshot": int(i), "lolp": round(float(lolp[i]), 4),
         "meanShortfallMW": round(float(shortfall[:, i].mean()), 2)}
        for i in order[:10] if lolp[i] > 0
    ]
    return {
        "lole": round(lole, 3),
        "eens": round(eens, 1),
        "eue": round(eens, 1),  # EUE ≡ EENS here (expected unserved energy)
        "loloProbability": [round(float(v), 5) for v in lolp],
        "worstPeriods": worst,
        "annualScale": round(annual_scale, 4),
    }


def build_adequacy(
    network: pypsa.Network,
    *,
    members: int = 200,
    variability: float = 0.15,
    seed: int = 11,
) -> dict[str, Any] | None:
    """Resource-adequacy study over a stochastic renewable ensemble.

    Reads the solved network's renewable generators (those with a time-varying
    ``p_max_pu`` — the availability signal) as base capacity factors, builds an
    ensemble per renewable (A1), forms available generation = firm capacity +
    Σ renewable capacity · CF, and returns LOLE / LOLP / EENS versus load (A2).

    Returns ``None`` when there is no load or no renewable (time-varying)
    generator — there's no stochastic availability to study.
    """
    if not getattr(network, "is_solved", False):
        return None
    snapshots = network.snapshots
    T = len(snapshots)
    if T == 0 or len(network.loads) == 0:
        return None

    load = network.get_switchable_as_dense("Load", "p_set").sum(axis=1).to_numpy()
    weights = network.snapshot_weightings["objective"].to_numpy()

    gens = network.generators
    pmax = network.get_switchable_as_dense("Generator", "p_max_pu")
    tv_cols = set(getattr(network.generators_t, "p_max_pu", pd.DataFrame()).columns)

    firm = np.zeros(T)
    renewables: list[tuple[str, float, np.ndarray]] = []  # (name, capacity, base CF)
    for g in gens.index:
        cap = float(gens.at[g, "p_nom_opt"]) if "p_nom_opt" in gens.columns else float(gens.at[g, "p_nom"])
        if cap <= 0:
            continue
        if str(g) in tv_cols:  # time-varying availability → stochastic renewable
            renewables.append((str(g), cap, pmax[g].to_numpy()))
        else:  # firm/dispatchable: available at its (static) rated availability
            firm += cap * pmax[g].to_numpy()

    if not renewables:
        return None

    # Available generation per member = firm + Σ renewable capacity · ensemble CF.
    available = np.tile(firm, (members, 1))
    total_renewable_cap = 0.0
    for i, (name, cap, base) in enumerate(renewables):
        ens = generate_renewable_ensemble(
            base, n_members=members, variability=variability, seed=seed + i,
        )
        available += cap * ens
        total_renewable_cap += cap

    metrics = compute_adequacy(available, load, weights, modeled_hours=float(weights.sum()))

    # A representative available-vs-load band for the card (p10/p50/p90 of total
    # available each snapshot), plus timestamps.
    p10 = np.percentile(available, 10, axis=0)
    p50 = np.percentile(available, 50, axis=0)
    p90 = np.percentile(available, 90, axis=0)
    labels = [pd.Timestamp(s).isoformat() for s in snapshots]
    band = [
        {"timestamp": labels[t], "load": round(float(load[t]), 2),
         "p10": round(float(p10[t]), 2), "p50": round(float(p50[t]), 2),
         "p90": round(float(p90[t]), 2)}
        for t in range(T)
    ]

    _log.info("adequacy: LOLE=%.2f h/yr, EENS=%.0f MWh, %d renewables, %d members",
              metrics["lole"], metrics["eens"], len(renewables), members)
    return {
        "members": members,
        "variability": variability,
        "firmCapacityMW": round(float(firm.max()), 2),
        "renewableCapacityMW": round(total_renewable_cap, 2),
        "peakLoadMW": round(float(load.max()), 2),
        "lole": metrics["lole"],
        "eens": metrics["eens"],
        "worstPeriods": metrics["worstPeriods"],
        "band": band,
    }
