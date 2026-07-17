"""Convergence-controlled Monte Carlo sampling + PASA-style maintenance placement.

The forced-outage Monte Carlo in ``outage_mc.py`` draws a *fixed* member count
(``nMembers``) and reports a distribution. That leaves a defensibility gap: is
200 members enough? Is 2000 overkill? This module answers that question
directly by drawing the same Markov outage sampler in **incremental batches**
until the running estimate of the target reliability metric (EUE or LOLE) has
stabilised, tracked via its standard error (SE). It composes a second,
independent capability — **maintenance placement** — a simple PASA
("Probabilistic Assessment of System Adequacy")-style heuristic that schedules
each eligible thermal unit's planned-maintenance requirement into the
lowest-net-load window of the horizon, staggering units so the fleet is not
all down at once, and folds the resulting planned-outage mask into the same
availability ensemble the convergence sampler draws.

**A) Convergence-controlled sampling.** Rather than fix M up front, draw
``batchSize`` new members at a time (advancing the seed deterministically per
batch so the whole run is reproducible from one top-level ``seed``),
accumulate the per-member metric (EUE or LOLE, from the same
``_per_member_metrics`` kernel ``outage_mc.py`` uses), and recompute the
running sample mean and its standard error after every batch:

Algorithm:
    After n accumulated members with per-member metric values
    $\\{x_1, \\dots, x_n\\}$ (EUE in MWh/yr or LOLE in h/yr, each already
    annualised by ``outage_mc``'s per-member kernel):
        $$ \\hat{\\mu}_n = \\frac{1}{n}\\sum_{i=1}^n x_i, \\qquad
           s_n = \\sqrt{\\frac{1}{n-1}\\sum_{i=1}^n (x_i - \\hat{\\mu}_n)^2}, \\qquad
           \\mathrm{SE}_n = \\frac{s_n}{\\sqrt{n}} $$
        ASCII: mean_n = (1/n) sum(x_i); s_n = sample_std(x_i); se_n = s_n / sqrt(n)

    Stop (declare convergence) once the *relative* standard error drops below
    the tolerance, or the estimate itself is ~0 (a relative criterion is
    undefined/meaningless at zero — a system with no shortfall in any sampled
    member has already "converged" trivially):
        $$ \\text{stop when } \\quad \\frac{\\mathrm{SE}_n}{|\\hat{\\mu}_n|} < \\text{tolerance}
           \\quad \\text{or} \\quad |\\hat{\\mu}_n| < \\varepsilon
           \\quad \\text{or} \\quad n \\ge \\text{maxMembers} $$
        ASCII: stop if se_n/|mean_n| < tolerance OR |mean_n| < eps OR n >= maxMembers

    Neither the relative-SE nor the zero-estimate branch may fire before a
    minimum accumulated member count (``min(maxMembers, max(2*batchSize, 100))``)
    is reached: a single lucky batch can read exactly zero shortfall — tripping
    the zero floor on a genuinely inadequate system — and ``SE`` is undefined
    (0) for n < 2, which would make the relative test trivially true for
    ``batchSize`` 1. The floor never exceeds ``maxMembers`` so a small budget
    still converges once it is exhausted.

    A 95% confidence interval on the converged (or exhausted) estimate uses
    the normal approximation (valid for n in the hundreds-to-thousands the
    batching produces):
        $$ \\mathrm{CI}_{95\\%} = \\hat{\\mu}_n \\pm 1.96\\,\\mathrm{SE}_n $$
        ASCII: ci = [mean_n - 1.96*se_n, mean_n + 1.96*se_n]

    Symbols: n = accumulated member count; x_i = per-member EUE (MWh/yr) or
    LOLE (h/yr); $\\hat{\\mu}_n$ = running estimate; $s_n$ = running sample
    standard deviation (Bessel-corrected); $\\mathrm{SE}_n$ = standard error of
    the mean; tolerance = target relative SE (dimensionless); $\\varepsilon$ =
    a small absolute floor (1e-6) below which the metric is treated as zero.

**B) Maintenance placement (PASA-style heuristic).** Net load is the load the
dispatchable/thermal fleet must cover after subtracting the deterministic,
solved must-run/renewable output:
        $$ \\text{netLoad}_t = \\text{load}_t - \\sum_{g \\in \\text{renewables}} p_{nom,g}\\cdot pmax_{g,t} $$
        ASCII: net_load[t] = load[t] - sum_{g in renewables} p_nom[g] * p_max_pu[g,t]

    Each eligible unit requires ``maintenanceWeeks`` of planned outage per
    year, converted to a *contiguous run of snapshots* whose cumulative
    snapshot weight (hours) first reaches the requirement:
        $$ \\text{durationHours} = \\text{maintenanceWeeks} \\times 168,\\qquad
           n_{\\text{snap}} = \\min\\{k : \\textstyle\\sum_{i=0}^{k-1} w_{t_0+i} \\ge \\text{durationHours}\\} $$
        ASCII: duration_hours = maintenance_weeks * 168; find smallest window (in snapshots)
        whose cumulative weight covers duration_hours.

    For each unit (processed in a stable order — largest capacity first, a
    conventional PASA tie-break since taking the biggest unit off the
    margin first is the most consequential placement decision), the
    algorithm scans every feasible contiguous start position and picks the
    window minimising the *peak effective stress* — net load, plus the MW of
    every *already scheduled* unit's planned outage in that window, plus this
    unit's own capacity if it too were removed there. A window already
    crowded with other units' outages therefore looks worse (higher stress)
    than an empty window even when the raw net load there is mildly lower —
    exactly what pushes later units away from windows earlier units already
    claimed and produces the stagger:
        $$ t^\\*_u = \\operatorname*{arg\\,min}_{t_0} \\; \\max_{t \\in [t_0, t_0+n_{\\text{snap}})}
           \\Big(\\text{netLoad}_t + \\sum_{u' \\text{ scheduled}} p_{nom,u'}\\cdot\\mathbb{1}[t \\in \\text{window}_{u'}] + p_{nom,u}\\Big) $$
        ASCII: pick start minimizing the peak of (net_load + sum of already-committed
        outaged MW + this unit's own MW) over the candidate window; ties broken by
        earliest start.

    The resulting boolean planned-outage mask (unit x snapshot, True = unit
    forced to zero availability for maintenance) is combined
    *multiplicatively* with the Markov forced-outage mask before the
    convergence sampler runs — i.e. a unit can be down for either reason, and
    the two never partially cancel (stacking is logical AND on "up").

Symbols: $p_{nom,g}$ (MW) rated capacity; $pmax_{g,t}$ (dimensionless, 0-1)
solved availability signal; $w_t$ (h) snapshot weight; 168 = hours/week.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from .outage_mc import _is_variable_renewable, _per_member_metrics, _snapshot_label, sample_outage_masks

_log = logging.getLogger("pypsa.solver")

_EPS = 1e-9
_ZERO_ESTIMATE_FLOOR = 1e-6
# Minimum accumulated members before ANY convergence stop branch may fire.
# Guards against two premature-convergence traps: (a) a single lucky batch that
# happens to draw zero shortfall trips the zero-estimate floor and reports a
# genuinely inadequate system as perfectly reliable; (b) batch_size 1 yields
# se=0 from the n<2 guard, making the relative-SE test trivially true after one
# draw. Effective floor is min(max_members, max(2*batch_size, this)) so a small
# member budget still converges on its full budget rather than being blocked.
_MIN_STOP_MEMBERS = 100

_DEFAULT_TARGET_METRIC = "eue"
_DEFAULT_TOLERANCE = 0.05
_DEFAULT_BATCH_SIZE = 50
_DEFAULT_MAX_MEMBERS = 2000
_DEFAULT_SEED = 42
_DEFAULT_FOR = 0.05
_DEFAULT_MTTR_HOURS = 48.0

_DEFAULT_MAINTENANCE_ENABLED = False
_DEFAULT_MAINTENANCE_WEEKS = 3.0
_HOURS_PER_WEEK = 168.0

# Default carriers eligible for planned maintenance when maintenanceCarriers
# is not supplied: anything NOT a variable renewable (mirrors outage_mc's /
# reserves.py's "thermal" convention) is a candidate for scheduled outage.


def _running_se(values: np.ndarray) -> tuple[float, float]:
    """Sample mean and standard error of the mean.

    Args:
        values: 1-D array of per-member metric draws accumulated so far.

    Returns:
        ``(mean, se)``. ``se`` is 0.0 for n < 2 (no dispersion estimate yet).
    """
    n = values.size
    if n == 0:
        return 0.0, 0.0
    mean = float(values.mean())
    if n < 2:
        return mean, 0.0
    std = float(values.std(ddof=1))
    return mean, std / np.sqrt(n)


def run_convergence_sampling(
    for_rates: np.ndarray,
    mttr_hours: np.ndarray,
    weights: np.ndarray,
    load: np.ndarray,
    thermal_cap: np.ndarray,
    thermal_pmax: np.ndarray,
    renewable_floor: np.ndarray,
    *,
    target_metric: str,
    tolerance: float,
    batch_size: int,
    max_members: int,
    seed: int,
    modeled_hours: float,
    planned_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Draw the Markov forced-outage sampler in batches until SE stabilises.

    Args:
        for_rates: (G,) forced-outage rate per thermal generator, in [0, 1).
        mttr_hours: (G,) mean time to repair per thermal generator, hours.
        weights: (T,) snapshot weight (h).
        load: (T,) system demand (MW).
        thermal_cap: (G,) rated capacity (MW) per thermal generator.
        thermal_pmax: (T, G) solved availability signal (dimensionless, 0-1)
            per thermal generator.
        renewable_floor: (T,) deterministic renewable + must-run contribution
            (MW), added on top of the sampled thermal availability.
        target_metric: ``"eue"`` (MWh/yr) or ``"lole"`` (h/yr).
        tolerance: Target relative standard error (dimensionless, e.g. 0.05).
        batch_size: Members drawn per batch.
        max_members: Hard cap on accumulated members.
        seed: Top-level RNG seed; batch ``k`` (0-indexed) draws with
            ``seed + k`` so the whole run is reproducible from one seed while
            each batch is an independent draw.
        modeled_hours: Total modelled window length (h), for annualising.
        planned_mask: Optional (G, T) boolean planned-maintenance mask (True
            = unit forced to zero availability that snapshot). Combined via
            logical AND with each batch's sampled forced-outage mask before
            computing available generation — i.e. a unit is available only
            if it is neither on forced outage nor on planned maintenance.

    Returns:
        Dict with ``achievedMembers``, ``converged``, ``estimate``, ``ciLow``,
        ``ciHigh``, ``unit``, and ``trace`` (list of
        ``{"members", "estimate", "se"}`` after each batch).

    Algorithm:
        See module docstring, section A. Per-member EUE/LOLE from
        ``outage_mc._per_member_metrics`` are pure per-draw scalars, so
        batches can be concatenated into one running array without
        re-deriving anything from ``compute_adequacy`` (which only reports
        ensemble aggregates, not the per-member array) beyond the annualising
        scale, computed once up front from ``modeled_hours``.
    """
    if target_metric not in ("eue", "lole"):
        target_metric = _DEFAULT_TARGET_METRIC
    unit = "MWh/yr" if target_metric == "eue" else "h/yr"

    annual_scale = 8760.0 / modeled_hours if modeled_hours > 0 else 1.0

    G = thermal_cap.shape[0]
    T = weights.shape[0]

    trace: list[dict[str, Any]] = []
    accumulated = np.empty(0, dtype=float)
    achieved_members = 0
    converged = False
    batch_index = 0

    if G == 0 or T == 0 or batch_size <= 0 or max_members <= 0:
        return {
            "achievedMembers": 0,
            "converged": True,
            "estimate": 0.0,
            "ciLow": 0.0,
            "ciHigh": 0.0,
            "unit": unit,
            "trace": [],
        }

    # No stop branch may fire before this many members have accumulated (but
    # never more than the member budget, so a small run still converges on its
    # full budget). See _MIN_STOP_MEMBERS.
    min_stop = min(max_members, max(2 * batch_size, _MIN_STOP_MEMBERS))

    while achieved_members < max_members:
        remaining = max_members - achieved_members
        this_batch = min(batch_size, remaining)
        batch_seed = seed + batch_index
        mask = sample_outage_masks(
            for_rates, mttr_hours, weights, n_members=this_batch, seed=batch_seed
        )  # (m, G, T)
        if planned_mask is not None and planned_mask.size:
            mask = mask & planned_mask[None, :, :]

        available = np.einsum("g,tg,mgt->mt", thermal_cap, thermal_pmax, mask)
        available = available + renewable_floor[None, :]

        lole_batch, eue_batch = _per_member_metrics(
            available, load, weights, annual_scale=annual_scale
        )
        batch_values = eue_batch if target_metric == "eue" else lole_batch

        accumulated = np.concatenate([accumulated, batch_values])
        achieved_members = accumulated.size
        batch_index += 1

        mean, se = _running_se(accumulated)
        trace.append(
            {
                "members": int(achieved_members),
                "estimate": round(float(mean), 4),
                "se": round(float(se), 4),
            }
        )

        if achieved_members < min_stop:
            # Too few members to trust either stop test yet: a lucky zero batch
            # would trip the zero floor, and se is unreliable (0.0 for n<2).
            continue

        if abs(mean) < _ZERO_ESTIMATE_FLOOR:
            converged = True
            break
        if se / abs(mean) < tolerance:
            converged = True
            break

    mean, se = _running_se(accumulated)
    ci_low = mean - 1.96 * se
    ci_high = mean + 1.96 * se

    return {
        "achievedMembers": int(achieved_members),
        "converged": bool(converged),
        "estimate": round(float(mean), 4),
        "ciLow": round(float(ci_low), 4),
        "ciHigh": round(float(ci_high), 4),
        "unit": unit,
        "trace": trace,
    }


def _maintenance_window_length(
    weights: np.ndarray,
    maintenance_weeks: float,
) -> int:
    """Smallest snapshot-count window whose cumulative weight covers the requirement.

    Args:
        weights: (T,) snapshot weight (h).
        maintenance_weeks: Planned-outage duration, weeks.

    Returns:
        Window length in snapshots, clamped to ``[1, T]``.
    """
    T = weights.shape[0]
    if T == 0:
        return 0
    duration_hours = max(0.0, maintenance_weeks) * _HOURS_PER_WEEK
    if duration_hours <= 0:
        return 1
    cumulative = np.cumsum(weights)
    idx = int(np.searchsorted(cumulative, duration_hours, side="left"))
    return int(np.clip(idx + 1, 1, T))


def place_maintenance(
    unit_names: list[str],
    unit_caps: np.ndarray,
    net_load: np.ndarray,
    weights: np.ndarray,
    *,
    maintenance_weeks: float,
) -> tuple[np.ndarray, list[tuple[str, int, int]]]:
    """Schedule each unit's planned outage into the lowest-impact window.

    Args:
        unit_names: (G,) eligible unit names, any stable order (re-sorted
            internally by descending capacity).
        unit_caps: (G,) rated capacity (MW), aligned with ``unit_names``.
        net_load: (T,) load minus deterministic renewable/must-run output
            (MW); may go negative (renewables exceeding load) — the
            algorithm only uses relative comparisons, so sign is fine.
        weights: (T,) snapshot weight (h).
        maintenance_weeks: Planned-outage duration per unit, weeks/yr.

    Returns:
        ``(mask, schedule)``: ``mask`` is a boolean (G, T) array (True =
        available; False = on planned outage), aligned with the ORIGINAL
        ``unit_names`` order; ``schedule`` is a list of
        ``(unit_name, start_index, window_length)`` in placement order
        (largest unit first).

    Algorithm:
        See module docstring, section B. Greedy, largest-unit-first
        placement against a running "committed outaged MW" accumulator so
        later units see (and avoid) windows already crowded by earlier
        placements.
    """
    G = len(unit_names)
    T = net_load.shape[0]
    mask = np.ones((G, T), dtype=bool)
    schedule: list[tuple[str, int, int]] = []
    if G == 0 or T == 0:
        return mask, schedule

    window_len = _maintenance_window_length(weights, maintenance_weeks)
    window_len = min(window_len, T)
    n_starts = T - window_len + 1
    if n_starts <= 0:
        return mask, schedule

    committed_outage_mw = np.zeros(T)  # running sum of already-placed units' MW, per snapshot
    order = sorted(range(G), key=lambda i: -unit_caps[i])

    for i in order:
        name = unit_names[i]
        cap = unit_caps[i]
        # Effective stress if this unit is ALSO taken out at a given snapshot:
        # the net load the rest of the fleet must cover, plus whatever other
        # units are ALREADY committed to be out there (their MW is no longer
        # available either). Higher committed_outage_mw at a snapshot makes it
        # a WORSE (not better) place to add this unit's outage too — this is
        # what pushes later units away from windows already used.
        stress = net_load + committed_outage_mw  # (T,)

        best_start = 0
        best_peak = np.inf
        for start in range(n_starts):
            end = start + window_len
            # Peak stress in the window if this unit is ALSO removed here.
            peak = float((stress[start:end] + cap).max())
            if peak < best_peak - _EPS:
                best_peak = peak
                best_start = start
        end = best_start + window_len
        mask[i, best_start:end] = False
        committed_outage_mw[best_start:end] += cap
        schedule.append((name, best_start, window_len))

    return mask, schedule


def build_convergence(
    network: pypsa.Network,
    options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Convergence-controlled outage MC + optional maintenance placement.

    Reads ``options["convergenceConfig"]``; returns ``None`` when the feature
    is disabled/absent, the network has no successful solve, there are no
    snapshots/loads, or there are no thermal (non-variable-renewable)
    generators to sample outages over.

    Args:
        network: solved ``pypsa.Network``.
        options: run options; reads the ``convergenceConfig`` block.

    Returns:
        The ``"convergenceSampling"`` payload dict (see module docstring for
        the contract), or ``None``.
    """
    cfg = (options or {}).get("convergenceConfig") or {}
    if not bool(cfg.get("enabled")):
        return None
    if not getattr(network, "is_solved", False):
        return None

    snapshots = network.snapshots
    T = len(snapshots)
    if T == 0 or len(network.loads) == 0:
        return None

    target_metric = str(cfg.get("targetMetric", _DEFAULT_TARGET_METRIC) or _DEFAULT_TARGET_METRIC).lower()
    if target_metric not in ("eue", "lole"):
        target_metric = _DEFAULT_TARGET_METRIC
    tolerance = float(cfg.get("tolerance", _DEFAULT_TOLERANCE) if cfg.get("tolerance") is not None else _DEFAULT_TOLERANCE)
    tolerance = tolerance if tolerance > 0 else _DEFAULT_TOLERANCE
    batch_size = int(cfg.get("batchSize", _DEFAULT_BATCH_SIZE) or _DEFAULT_BATCH_SIZE)
    max_members = int(cfg.get("maxMembers", _DEFAULT_MAX_MEMBERS) or _DEFAULT_MAX_MEMBERS)
    seed = int(cfg.get("seed", _DEFAULT_SEED) if cfg.get("seed") is not None else _DEFAULT_SEED)
    for_fallback = float(
        cfg.get("forcedOutageRate", _DEFAULT_FOR) if cfg.get("forcedOutageRate") is not None else _DEFAULT_FOR
    )
    mttr_fallback = float(
        cfg.get("mttrHours", _DEFAULT_MTTR_HOURS) if cfg.get("mttrHours") is not None else _DEFAULT_MTTR_HOURS
    )

    maintenance_enabled = bool(cfg.get("maintenanceEnabled", _DEFAULT_MAINTENANCE_ENABLED))
    maintenance_weeks = float(
        cfg.get("maintenanceWeeks", _DEFAULT_MAINTENANCE_WEEKS)
        if cfg.get("maintenanceWeeks") is not None
        else _DEFAULT_MAINTENANCE_WEEKS
    )
    requested_maintenance_carriers = cfg.get("maintenanceCarriers")

    if batch_size <= 0 or max_members <= 0:
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

    renewable_floor = np.zeros(T)

    for g in gens.index:
        name = str(g)
        if name.startswith("load_shedding_"):
            continue
        carrier = str(gens.at[g, "carrier"]) if "carrier" in gens.columns else ""
        cap = float(gens.at[g, cap_col]) if cap_col in gens.columns else 0.0
        if cap <= 0:
            continue
        if _is_variable_renewable(carrier):
            renewable_floor += cap * pmax[g].to_numpy()
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
    modeled_hours = float(weights.sum())

    thermal_pmax = pmax.reindex(columns=thermal_names).to_numpy()  # (T, G)

    # ── Optional maintenance placement ──────────────────────────────────────
    maintenance_payload: dict[str, Any] | None = None
    planned_mask: np.ndarray | None = None
    if maintenance_enabled:
        if requested_maintenance_carriers:
            eligible_idx = [
                i for i, c in enumerate(thermal_carrier_list) if c in requested_maintenance_carriers
            ]
        else:
            eligible_idx = list(range(len(thermal_names)))

        if eligible_idx:
            net_load = load - renewable_floor
            eligible_names = [thermal_names[i] for i in eligible_idx]
            eligible_caps = thermal_cap[eligible_idx]
            eligible_mask, schedule = place_maintenance(
                eligible_names, eligible_caps, net_load, weights,
                maintenance_weeks=maintenance_weeks,
            )
            planned_mask = np.ones((len(thermal_names), T), dtype=bool)
            for row, i in enumerate(eligible_idx):
                planned_mask[i, :] = eligible_mask[row, :]

            labels = [_snapshot_label(s) for s in snapshots]
            # ``schedule`` comes back in PLACEMENT order (largest capacity
            # first), NOT eligible-list order, so the carrier must be looked
            # up by unit name — indexing thermal_carrier_list by the row's
            # position would attribute another unit's carrier whenever the
            # fleet isn't already sorted by descending capacity.
            carrier_by_unit = {thermal_names[i]: thermal_carrier_list[i] for i in eligible_idx}
            schedule_rows = [
                {
                    "unit": name,
                    "carrier": carrier_by_unit[name],
                    "startLabel": labels[start],
                    "weeks": round(maintenance_weeks, 3),
                }
                for name, start, _length in schedule
            ]

            # Before/after planning-reserve-margin summary: peak(net_load) vs
            # peak(net_load - committed planned-outage MW) — the worst-case
            # margin impact of the schedule, evaluated at solved (no forced
            # outage) availability so it isolates the maintenance effect.
            planned_outage_mw = np.zeros(T)
            for row, i in enumerate(eligible_idx):
                planned_outage_mw += eligible_caps[row] * (~eligible_mask[row, :])
            peak_net_load_before = float(net_load.max()) if T else 0.0
            peak_net_load_after = float((net_load + planned_outage_mw).max()) if T else 0.0
            total_thermal_cap = float(thermal_cap.sum())
            margin_before = total_thermal_cap - peak_net_load_before
            margin_after = total_thermal_cap - peak_net_load_after

            maintenance_payload = {
                "enabled": True,
                "schedule": schedule_rows,
                "summary": [
                    {
                        "label": "Units scheduled",
                        "value": str(len(schedule_rows)),
                        "detail": f"{maintenance_weeks:g} weeks/yr each, staggered",
                    },
                    {
                        "label": "Peak net load (before)",
                        "value": f"{peak_net_load_before:,.1f} MW",
                        "detail": "load minus deterministic renewable/must-run output",
                    },
                    {
                        "label": "Peak net load (after)",
                        "value": f"{peak_net_load_after:,.1f} MW",
                        "detail": "with scheduled planned outages removed from availability",
                    },
                    {
                        "label": "Planning reserve margin (before -> after)",
                        "value": f"{margin_before:,.1f} -> {margin_after:,.1f} MW",
                        "detail": f"thermal nameplate {total_thermal_cap:,.1f} MW minus peak net load",
                    },
                ],
            }
        else:
            maintenance_payload = {
                "enabled": True,
                "schedule": [],
                "summary": [
                    {
                        "label": "Units scheduled",
                        "value": "0",
                        "detail": "no eligible thermal unit matched maintenanceCarriers",
                    }
                ],
            }
    else:
        maintenance_payload = None

    result = run_convergence_sampling(
        for_rates, mttr_hours, weights, load, thermal_cap, thermal_pmax, renewable_floor,
        target_metric=target_metric, tolerance=tolerance, batch_size=batch_size,
        max_members=max_members, seed=seed, modeled_hours=modeled_hours,
        planned_mask=planned_mask,
    )

    summary = [
        {
            "label": f"{target_metric.upper()} estimate",
            "value": f"{result['estimate']:,.2f} {result['unit']}",
            "detail": f"95% CI [{result['ciLow']:,.2f}, {result['ciHigh']:,.2f}] {result['unit']}",
        },
        {
            "label": "Members drawn",
            "value": str(result["achievedMembers"]),
            "detail": (
                f"converged at tolerance {tolerance:.2%}" if result["converged"]
                else f"stopped at maxMembers={max_members} before converging"
            ),
        },
        {
            "label": "Thermal units sampled",
            "value": str(len(thermal_names)),
            "detail": f"seed {seed}, batch size {batch_size}",
        },
    ]

    note = None
    if not result["converged"]:
        note = (
            f"Did not reach the target relative standard error ({tolerance:.2%}) "
            f"within maxMembers={max_members}; the estimate's CI may still be wide."
        )

    _log.info(
        "convergence: metric=%s members=%d converged=%s estimate=%.3f %s (CI [%.3f, %.3f])",
        target_metric, result["achievedMembers"], result["converged"],
        result["estimate"], result["unit"], result["ciLow"], result["ciHigh"],
    )

    return {
        "enabled": True,
        "targetMetric": target_metric,
        "tolerance": tolerance,
        "achievedMembers": result["achievedMembers"],
        "converged": result["converged"],
        "estimate": result["estimate"],
        "ciLow": result["ciLow"],
        "ciHigh": result["ciHigh"],
        "unit": result["unit"],
        "trace": result["trace"],
        "maintenance": maintenance_payload,
        "summary": summary,
        "note": note,
    }
