"""LMP decomposition — post-process energy/congestion split of nodal prices.

Physical-risk roadmap item #5. This is a **strict post-process reporting
extra**: it never touches the solve and never re-derives a price. The split
itself (an energy reference price plus a per-bus congestion residual) is
Ragnarok's, because PyPSA has no such decomposition; it is built from the
bus-level locational marginal price (LMP, ``n.buses_t.marginal_price``,
currency/MWh) and the solved flows. The money the lines collect is NOT
recomputed: the congestion rent of every Line / Link is
``n.statistics.revenue`` (see :func:`_branch_congestion_rent`), which applies
the snapshot weightings itself. (The solve passes ``assign_all_duals=True``,
so ``n.lines_t.mu_upper`` is populated as well; the old premise that line
duals are empty no longer holds, and no result here reads them.)

**Energy vs. congestion split.** In a lossless linear DC power flow (which is
what PyPSA's LOPF solves), the LMP at bus *b* and snapshot *t* can always be
written as a common system "energy" reference price plus a bus-specific
"congestion" residual:

Algorithm:
    $$ \\mathrm{LMP}_{b,t} = \\pi_t + c_{b,t} $$
    ASCII: LMP[b,t] = energy[t] + congestion[b,t]

    where $\\pi_t$ (the *energy* component, currency/MWh) is a single
    system-wide reference price per snapshot and $c_{b,t}$ = LMP$_{b,t} -
    \\pi_t$ is whatever is left over — by construction the split is exact
    (energy + congestion always reconstructs the observed LMP). $\\pi_t$ is
    not unique in a meshed network (any bus, or any weighted combination,
    is a defensible "reference"); this module supports three conventions,
    selected by ``referenceMode``:

    - ``load-weighted`` (default): the demand-weighted average LMP,
        $$ \\pi_t = \\frac{\\sum_b \\mathrm{load}_{b,t}\\cdot \\mathrm{LMP}_{b,t}}
                          {\\sum_b \\mathrm{load}_{b,t}} $$
        ASCII: energy[t] = sum_b(load[b,t]*LMP[b,t]) / sum_b(load[b,t])
        — falls back to the simple cross-bus mean if total system load in
        that snapshot is zero (division guard).
    - ``min``: the system-wide minimum nodal price, $\\pi_t = \\min_b
      \\mathrm{LMP}_{b,t}$ — the price an unconstrained (uncongested) bus
      would see; every other bus's congestion component is then
      non-negative by construction.
    - ``bus``: pins $\\pi_t$ to a single named reference bus's own LMP,
      $\\pi_t = \\mathrm{LMP}_{\\text{ref},t}$ — congestion is then read
      directly as "price markup relative to the reference hub."

    Time-weighted means (weight $w_t$ = snapshot duration, hours) turn the
    per-snapshot decomposition into a single reporting number per bus:
        $$ \\overline{\\mathrm{LMP}}_b = \\frac{\\sum_t w_t\\,\\mathrm{LMP}_{b,t}}{\\sum_t w_t},
           \\quad \\overline{\\pi} = \\frac{\\sum_t w_t\\,\\pi_t}{\\sum_t w_t},
           \\quad \\overline{c}_b = \\overline{\\mathrm{LMP}}_b - \\overline{\\pi} $$
        ASCII: mean_lmp[b] = sum_t(w[t]*LMP[b,t])/sum_t(w[t]); energy_price =
        sum_t(w[t]*energy[t])/sum_t(w[t]); congestion[b] = mean_lmp[b] - energy_price

    **Congestion rent per line.** For a directed flow $f_{\\ell,t}$ (MW) on
    line/link $\\ell$ from bus $u$ to bus $v$ (PyPSA's ``p0`` sign convention:
    positive = flowing bus0 -> bus1), the merchandising surplus collected on that
    link is the negative of the nodal payments over all its ports, which is
    exactly PyPSA's ``n.statistics.revenue`` of the branch:
        $$ \\mathrm{rent}_{\\ell,t} = -\\sum_{k} \\mathrm{LMP}_{b_k,t}\\; p_{k,t},
           \\qquad \\mathrm{congestionRent}_\\ell = \\sum_t w_t\\,\\mathrm{rent}_{\\ell,t} $$
        ASCII: rent[l,t] = -(sum over ports k of LMP[bus_k,t] * p_k[t]); congestion_rent[l]
        = sum_t(w[t]*rent[l,t]) = n.statistics.revenue(Line/Link)

        For a lossless line (p1 = -p0) this is (LMP_v - LMP_u)·p0; for a lossy link
        (p1 = -efficiency·p0) it credits only delivered power, so pure-loss price
        spreads collect zero rent. Verified on a 2-bus toy: LMP_A=10, LMP_B=80,
        flow_A->B=50 MW => rent = 70 x 50 = 3500 per snapshot, equal to the
        flow-limit shadow price x capacity.

    A line/link is flagged *congested* in a snapshot when its flow magnitude
    is at least 99% of its capacity (``s_nom`` for lines, ``p_nom`` for
    links) — a tolerance band for solver/rounding noise, not a hard binary
    equality test. ``hoursCongested`` sums snapshot weight (hours) over such
    snapshots; ``meanAbsFlow`` / ``utilizationPct`` are simple weighted
    averages of $|f_{\\ell,t}|$ and $100\\cdot\\overline{|f_\\ell|}/\\text{cap}$.

    **Copper-plate special case.** If the spatial spread of LMPs across buses
    is (numerically) zero at every snapshot, there is only one price region:
    congestion collapses to ~0 everywhere and every line's rent is ~0. The
    module still returns a full, well-formed result in this case (never
    ``None`` — that guard is reserved for "no solved prices" / "fewer than 2
    buses") but annotates ``note`` accordingly so the UI can explain the flat
    congestion numbers rather than implying a bug.

Symbols: $b$ = bus; $t$ = snapshot; $\\ell$ = line or link; $w_t$ = snapshot
weight (h); $\\mathrm{LMP}_{b,t}$ = ``buses_t.marginal_price`` (currency/MWh);
$\\mathrm{load}_{b,t}$ = per-bus demand (MW), aggregated from
``loads_t.p``/``loads_t.p_set`` by ``loads.bus``; $\\pi_t$ = energy component
(currency/MWh); $c_{b,t}$ = congestion component (currency/MWh);
$f_{\\ell,t}$ = solved line/link flow (MW, ``*_t.p0`` sign convention);
cap$_\\ell$ = ``s_nom`` (lines) or ``p_nom`` (links), MW.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from .outage_mc import _snapshot_label

_log = logging.getLogger("pypsa.solver")

_EPS = 1e-9
_SPATIAL_SPREAD_EPS = 1e-6
_CONGESTION_UTILIZATION_THRESHOLD = 0.99
_MAX_LINE_ROWS = 25

_DEFAULT_REFERENCE_MODE = "load-weighted"
_VALID_REFERENCE_MODES = ("load-weighted", "min", "bus")


def _safe_float(value: Any) -> float:
    """Coerce to a JSON-safe float (NaN/inf -> 0.0)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(f):
        return 0.0
    return f


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    """Σ w·x / Σ w, guarded against Σw == 0."""
    total_w = float(weights.sum())
    if total_w <= _EPS:
        return _safe_float(np.mean(values)) if values.size else 0.0
    return _safe_float(float(np.dot(values, weights)) / total_w)


def _bus_load_matrix(network: pypsa.Network, snapshots: pd.Index, buses: list[str]) -> pd.DataFrame:
    """Per-bus demand (MW), aggregated from solved dispatch or fallback setpoint.

    Args:
        network: Solved network.
        snapshots: Snapshot index to reindex onto.
        buses: Bus names (columns of the returned frame, in this order).

    Returns:
        (T, B) DataFrame of MW, aligned to ``snapshots`` x ``buses``, 0.0 for
        buses with no load.
    """
    loads = network.loads
    if len(loads) == 0:
        return pd.DataFrame(0.0, index=snapshots, columns=buses)

    p = network.loads_t.p
    if p is None or p.empty:
        p = network.get_switchable_as_dense("Load", "p_set")
    p = p.reindex(index=snapshots, columns=loads.index).fillna(0.0)

    bus_of_load = loads["bus"].astype(str)
    by_bus = p.T.groupby(bus_of_load).sum().T  # (T, unique load-buses)
    return by_bus.reindex(columns=buses, fill_value=0.0)


def _energy_component(
    lmp: pd.DataFrame,
    load: pd.DataFrame,
    reference_mode: str,
    reference_bus: str | None,
) -> tuple[np.ndarray, str | None]:
    """Per-snapshot system "energy" reference price, per ``referenceMode``.

    Args:
        lmp: (T, B) nodal price, currency/MWh.
        load: (T, B) per-bus demand, MW, same shape/index/columns as ``lmp``.
        reference_mode: One of ``load-weighted`` / ``min`` / ``bus``.
        reference_bus: Bus name for mode ``bus`` (ignored otherwise).

    Returns:
        ``(energy_t, resolved_reference_bus)``. ``resolved_reference_bus`` is
        ``None`` unless mode is ``bus`` and the bus was found (falls back to
        ``load-weighted`` — returning ``None`` — if not).
    """
    lmp_arr = lmp.to_numpy()
    if reference_mode == "min":
        return lmp_arr.min(axis=1), None

    if reference_mode == "bus":
        if reference_bus and reference_bus in lmp.columns:
            return lmp[reference_bus].to_numpy(), reference_bus
        # Fall back to load-weighted; caller resets referenceBus to None.
        reference_mode = "load-weighted"

    # load-weighted (default + bus-mode fallback)
    load_arr = load.to_numpy()
    total_load_t = load_arr.sum(axis=1)
    numer = (load_arr * lmp_arr).sum(axis=1)
    energy_t = np.where(total_load_t > _EPS, numer / np.where(total_load_t > _EPS, total_load_t, 1.0), lmp_arr.mean(axis=1))
    return energy_t, None


def _effective_cap(df: pd.DataFrame, name: Any, nom_col: str, opt_col: str, max_pu_col: str) -> float:
    """Effective thermal limit (MW) a branch's flow is measured against.

    Prefers the solved-optimal rating (``s_nom_opt`` / ``p_nom_opt``) over the
    nameplate so an expanded extendable branch is not judged against its
    pre-expansion capacity, and multiplies by the per-unit availability
    (``s_max_pu`` / ``p_max_pu``, default 1.0) so an N-1 / reliability-derated
    branch binds at its true limit. Falls back to the nameplate rating when the
    optimized column is absent or zero (PyPSA sets ``*_nom_opt == *_nom`` for
    non-extendable branches, so the fallback is only exercised pre-solve).
    """
    nom = float(df.at[name, nom_col]) if nom_col in df.columns else 0.0
    if opt_col in df.columns:
        opt = float(df.at[name, opt_col])
        if opt > _EPS:
            nom = opt
    max_pu = float(df.at[name, max_pu_col]) if max_pu_col in df.columns else 1.0
    return nom * max_pu


def _collect_branches(
    network: pypsa.Network,
) -> list[tuple[str, str, str, str, pd.Series, pd.Series, float]]:
    """Enumerate lines + links as ``(name, kind, bus_from, bus_to, p0, p1, cap)``.

    ``p0``/``p1`` are the solved flow series (MW) injected into the branch at
    bus0/bus1 (PyPSA sign convention: ``p1 = -efficiency * p0`` for links,
    ``p1 = -p0`` for lossless lines), so the pair carries link losses. ``cap``
    is the branch's *effective* thermal limit (MW): ``s_nom_opt * s_max_pu`` for
    lines, ``p_nom_opt * p_max_pu`` for links (see ``_effective_cap``).
    """
    branches: list[tuple[str, str, str, str, pd.Series, pd.Series, float]] = []

    lines = network.lines
    if len(lines) > 0 and not network.lines_t.p0.empty:
        p1_frame = network.lines_t.p1
        for name in lines.index:
            if name not in network.lines_t.p0.columns:
                continue
            p0 = network.lines_t.p0[name]
            p1 = p1_frame[name] if (not p1_frame.empty and name in p1_frame.columns) else -p0
            branches.append(
                (
                    str(name),
                    "line",
                    str(lines.at[name, "bus0"]),
                    str(lines.at[name, "bus1"]),
                    p0,
                    p1,
                    _effective_cap(lines, name, "s_nom", "s_nom_opt", "s_max_pu"),
                )
            )

    links = network.links
    if len(links) > 0 and not network.links_t.p0.empty:
        p1_frame = network.links_t.p1
        for name in links.index:
            if name not in network.links_t.p0.columns:
                continue
            p0 = network.links_t.p0[name]
            p1 = p1_frame[name] if (not p1_frame.empty and name in p1_frame.columns) else -p0
            branches.append(
                (
                    str(name),
                    "link",
                    str(links.at[name, "bus0"]),
                    str(links.at[name, "bus1"]),
                    p0,
                    p1,
                    _effective_cap(links, name, "p_nom", "p_nom_opt", "p_max_pu"),
                )
            )

    return branches


def _branch_congestion_rent(network: pypsa.Network) -> tuple[dict[tuple[str, str], float], pd.Series]:
    """Congestion rent of every Line / Link from ``n.statistics.revenue``.

    PyPSA's ``revenue`` of a branch is the negative of the nodal payments over all its ports
    (``-sum_k LMP_k p_k``, ``p_k`` the solved port flows), i.e. the merchandising surplus; for the 2-bus toy
    LMP_A = 10, LMP_B = 80, flow A -> B = 50 MW it is 70 x 50 = 3500 per snapshot. It applies the snapshot
    weightings itself, so nothing is weighted here.

    Returns:
        ``({(component, name): rent over the horizon}, per-snapshot total rent over every branch (currency/h))``.
    """
    from .stat_metrics import asset_statistic, combine_periods

    present = [c for c in ("Line", "Link") if len(network.components[c].static)]
    if not present:
        return {}, pd.Series(0.0, index=network.snapshots)
    total = combine_periods(asset_statistic(network, "revenue", present))
    by_branch = {(str(c), str(n)): float(v) for (c, n), v in total.items()}
    per_snapshot = asset_statistic(network, "revenue", present, groupby_time=False)
    trace = (
        per_snapshot.fillna(0.0).sum(axis=0).reindex(network.snapshots).fillna(0.0)
        if not per_snapshot.empty
        else pd.Series(0.0, index=network.snapshots)
    )
    return by_branch, trace


def build_lmp_decomposition(
    network: pypsa.Network,
    options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Decompose solved nodal prices into an energy component + congestion.

    Reads ``options["lmpDecompositionConfig"]``. Pure post-process: never
    re-solves and never reads a line/link dual; it reads ``buses_t.marginal_price`` and
    ``lines_t.p0`` / ``links_t.p0`` for the split and utilisation, and
    ``n.statistics.revenue`` for the congestion rent of each branch.

    Args:
        network: Solved ``pypsa.Network``.
        options: Run options; reads ``lmpDecompositionConfig`` (keys:
            ``enabled``, ``referenceMode`` in {load-weighted, min, bus},
            ``referenceBus``) plus the top-level ``currencySymbol``.

    Returns:
        The ``"lmpDecomposition"`` payload dict (see module docstring /
        frontend contract), or ``None`` when there are no solved nodal prices
        or fewer than 2 buses.
    """
    cfg = (options or {}).get("lmpDecompositionConfig") or {}
    currency = str((options or {}).get("currencySymbol", "$"))
    unit = f"{currency}/MWh"

    lmp_raw = network.buses_t.marginal_price
    if lmp_raw is None or lmp_raw.empty:
        return None

    buses = [str(b) for b in lmp_raw.columns]
    if len(buses) < 2:
        return None

    snapshots = network.snapshots
    lmp = lmp_raw.reindex(index=snapshots, columns=buses).fillna(0.0)
    T = len(snapshots)
    if T == 0:
        return None

    weights = network.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0).to_numpy()
    labels = [_snapshot_label(s) for s in snapshots]

    reference_mode = str(cfg.get("referenceMode", _DEFAULT_REFERENCE_MODE) or _DEFAULT_REFERENCE_MODE).lower()
    if reference_mode not in _VALID_REFERENCE_MODES:
        reference_mode = _DEFAULT_REFERENCE_MODE
    requested_reference_bus = cfg.get("referenceBus")
    reference_bus_name = str(requested_reference_bus) if requested_reference_bus else None

    load = _bus_load_matrix(network, snapshots, buses)

    energy_t, resolved_reference_bus = _energy_component(lmp, load, reference_mode, reference_bus_name)
    if reference_mode == "bus" and resolved_reference_bus is None:
        # Requested bus missing/empty — energy_t already fell back internally
        # to load-weighted; echo the mode that was ACTUALLY used, per contract.
        reference_mode = "load-weighted"
        reference_bus_name = None
    elif reference_mode == "bus":
        reference_bus_name = resolved_reference_bus
    else:
        reference_bus_name = None

    lmp_arr = lmp.to_numpy()  # (T, B)
    congestion_arr = lmp_arr - energy_t[:, None]  # (T, B)

    # ── Copper-plate detection: spatial spread of LMP across buses, every snapshot.
    spatial_spread = float(np.max(lmp_arr.max(axis=1) - lmp_arr.min(axis=1))) if T else 0.0
    is_copperplate = spatial_spread < _SPATIAL_SPREAD_EPS

    total_w = float(weights.sum())
    energy_price = _weighted_mean(energy_t, weights)

    # ── Per-bus rows ─────────────────────────────────────────────────────────
    load_arr = load.to_numpy()  # (T, B)
    bus_rows: list[dict[str, Any]] = []
    for j, bus in enumerate(buses):
        mean_lmp = _weighted_mean(lmp_arr[:, j], weights)
        congestion_b = mean_lmp - energy_price
        load_mwh = _safe_float(float(np.dot(load_arr[:, j], weights)))
        congestion_cost = _safe_float(float(np.dot(load_arr[:, j] * congestion_arr[:, j], weights)))
        bus_rows.append(
            {
                "bus": bus,
                "meanLmp": round(mean_lmp, 2),
                "energy": round(energy_price, 2),
                "congestion": round(congestion_b, 2),
                "loadMwh": round(load_mwh, 2),
                "congestionCost": round(congestion_cost, 2),
            }
        )
    bus_rows.sort(key=lambda row: row["congestion"], reverse=True)

    # ── Lines + links ────────────────────────────────────────────────────────
    branches = _collect_branches(network)
    bus_index = {b: i for i, b in enumerate(buses)}
    line_rows: list[dict[str, Any]] = []
    total_congestion_rent = 0.0

    rent_by_branch, rent_per_t = _branch_congestion_rent(network)
    for name, kind, bus_from, bus_to, flow_series, p1_series, cap in branches:
        if bus_from not in bus_index or bus_to not in bus_index:
            continue  # an unpriced end: not a branch of this decomposition
        # Merchandising surplus (congestion rent): n.statistics.revenue of the branch (see
        # _branch_congestion_rent), under the snapshot weightings.
        congestion_rent = _safe_float(rent_by_branch.get(("Line" if kind == "line" else "Link", name), 0.0))
        total_congestion_rent += congestion_rent

        flow = flow_series.reindex(snapshots).fillna(0.0).to_numpy()
        abs_flow = np.abs(flow)
        mean_abs_flow = _weighted_mean(abs_flow, weights)
        if cap > _EPS:
            congested_mask = abs_flow >= (_CONGESTION_UTILIZATION_THRESHOLD * cap)
            hours_congested = float(np.dot(congested_mask.astype(float), weights))
            utilization_pct = 100.0 * mean_abs_flow / cap
        else:
            hours_congested = 0.0
            utilization_pct = 0.0

        line_rows.append(
            {
                "name": name,
                "kind": kind,
                "from": bus_from,
                "to": bus_to,
                "congestionRent": round(congestion_rent, 2),
                "hoursCongested": round(hours_congested, 2),
                "meanAbsFlow": round(mean_abs_flow, 2),
                "sNom": round(_safe_float(cap), 2),
                "utilizationPct": round(_safe_float(utilization_pct), 1),
            }
        )

    line_rows.sort(key=lambda row: abs(row["congestionRent"]), reverse=True)
    top_line_rows = line_rows[:_MAX_LINE_ROWS]

    # ── Totals ───────────────────────────────────────────────────────────────
    total_load_wt = float(np.dot(load_arr.sum(axis=1), weights))
    if total_load_wt > _EPS:
        mean_lmp_total = _safe_float(
            float(np.dot((load_arr * lmp_arr).sum(axis=1), weights)) / total_load_wt
        )
    else:
        mean_lmp_total = _weighted_mean(lmp_arr.mean(axis=1), weights)

    congestion_charge = _safe_float(sum(row["congestionCost"] for row in bus_rows))

    totals = {
        "congestionRent": round(_safe_float(total_congestion_rent), 2),
        "energyPrice": round(energy_price, 2),
        "meanLmp": round(mean_lmp_total, 2),
        "congestionCharge": round(congestion_charge, 2),
        "windowHours": round(_safe_float(total_w), 2),
    }

    # ── Series (per-snapshot system-level trace) ────────────────────────────
    series: dict[str, Any] | None = None
    if T > 0:
        mean_lmp_per_t = np.where(
            load_arr.sum(axis=1) > _EPS,
            (load_arr * lmp_arr).sum(axis=1) / np.where(load_arr.sum(axis=1) > _EPS, load_arr.sum(axis=1), 1.0),
            lmp_arr.mean(axis=1),
        )
        # Instantaneous (unweighted) per-snapshot total congestion rent across ALL lines+links, not just
        # the top-N kept in `lines`: n.statistics.revenue with groupby_time=False.
        series = {
            "snapshots": labels,
            "energy": [round(_safe_float(v), 2) for v in energy_t],
            "meanLmp": [round(_safe_float(v), 2) for v in mean_lmp_per_t],
            "congestionRent": [round(_safe_float(v), 2) for v in rent_per_t.to_numpy()],
        }

    # ── Summary KPIs ─────────────────────────────────────────────────────────
    n_congested_lines = sum(1 for row in line_rows if row["hoursCongested"] > 0)
    if bus_rows:
        peak_bus_row = max(bus_rows, key=lambda row: row["congestion"])
    else:
        peak_bus_row = {"bus": "-", "congestion": 0.0}

    summary = [
        {
            "label": "Congestion rent",
            "value": f"{currency}{totals['congestionRent']:,.2f}",
            "detail": f"over {totals['windowHours']:,.1f} modeled hours",
        },
        {
            "label": "Energy price",
            "value": f"{totals['energyPrice']:,.2f} {unit}",
            "detail": f"reference mode: {reference_mode}",
        },
        {
            "label": "Congested lines",
            "value": str(n_congested_lines),
            "detail": f"of {len(line_rows)} line(s)/link(s) at >= {_CONGESTION_UTILIZATION_THRESHOLD:.0%} capacity",
        },
        {
            "label": "Peak congestion",
            "value": f"{peak_bus_row['congestion']:,.2f} {unit}",
            "detail": f"bus {peak_bus_row['bus']}",
        },
    ]

    # ── Note ─────────────────────────────────────────────────────────────────
    mode_note = {
        "load-weighted": "the demand-weighted average nodal price across all buses",
        "min": "the system-wide minimum nodal price (the price an unconstrained bus would see)",
        "bus": f"the nodal price at reference bus '{reference_bus_name}'",
    }[reference_mode]
    note = (
        f"Energy component is {mode_note}. PyPSA's linear optimal power flow "
        "is lossless, so nodal price decomposes into energy + congestion with "
        "no marginal-loss term."
    )
    if is_copperplate:
        note = (
            "Single price region (copper-plate): nodal price has no congestion "
            "component. " + note
        )

    _log.info(
        "lmp_decomposition: mode=%s buses=%d branches=%d congestion_rent=%.2f %s "
        "copperplate=%s",
        reference_mode, len(buses), len(line_rows), totals["congestionRent"], currency, is_copperplate,
    )

    return {
        "enabled": True,
        "referenceMode": reference_mode,
        "referenceBus": reference_bus_name,
        "currency": currency,
        "unit": unit,
        "buses": bus_rows,
        "lines": top_line_rows,
        "totals": totals,
        "series": series,
        "summary": summary,
        "note": note,
    }
