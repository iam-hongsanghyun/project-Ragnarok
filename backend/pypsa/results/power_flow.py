"""Power-flow study mode — run PyPSA's ``pf()`` / ``lpf()`` instead of an LP.

This is *not* an optimisation: nothing is minimised. Given fixed injections
(generator ``p_set`` / dispatch and load ``p_set``) it solves the network
physics for branch flows and bus voltages.

  • ``n.pf()``  — full AC power flow (Newton-Raphson per sub-network, per
    snapshot). Populates ``buses_t.v_mag_pu`` / ``v_ang`` and active+reactive
    branch flows; reports per-snapshot convergence.
  • ``n.lpf()`` — linearised (DC) power flow. Direct solve, always "converges",
    lossless, and leaves voltage magnitudes at 1.0 pu.

The optimise pipeline in :mod:`pypsa.results` assumes a solved LP (objective,
locational marginal prices, costs); none of those exist after a power flow, so
this path produces its own focused payload — convergence, branch loading, the
voltage profile, losses, and the per-bus injection balance — rather than
falling through code that would emit meaningless zeros.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pypsa

from ..utils.series import weighted_sum
from .full_outputs import build_full_outputs

# Empty optimise-only result fields, kept so the stored payload is the same
# shape the frontend expects for any run (the charts simply render empty).
EMPTY_OPTIMISE_FIELDS: dict[str, Any] = {
    "dispatchSeries": [],
    "curtailmentSeries": [],
    "generatorDispatchSeries": [],
    "systemPriceSeries": [],
    "systemEmissionsSeries": [],
    "storageSeries": [],
    "storageSocSeries": [],
    "nodalPriceSeries": [],
    "carrierMix": [],
    "generatorEnergy": [],
    "costBreakdown": [],
    "expansionResults": [],
    "meritOrder": [],
    "co2Shadow": None,
    "appliedConstraints": [],
    "generatorEconomics": None,
    "emissionsBreakdown": None,
    "pathway": None,
    "rolling": None,
    "stochastic": None,
    "securityConstrained": None,
}


def _branch_loading(network: pypsa.Network) -> list[dict[str, Any]]:
    """Peak |flow| / rating (%) for every passive branch and link, post-flow."""
    out: list[dict[str, Any]] = []
    if not network.lines_t.p0.empty:
        for line in network.lines.index:
            s_nom = max(float(network.lines.at[line, "s_nom"]), 1.0)
            peak = float((network.lines_t.p0[line].abs() / s_nom * 100.0).max())
            out.append({"label": str(line), "value": round(peak, 1)})
    if not network.transformers.empty and not network.transformers_t.p0.empty:
        for tr in network.transformers.index:
            s_nom = max(float(network.transformers.at[tr, "s_nom"]), 1.0)
            peak = float((network.transformers_t.p0[tr].abs() / s_nom * 100.0).max())
            out.append({"label": str(tr), "value": round(peak, 1)})
    if not network.links.empty and not network.links_t.p0.empty:
        for link in network.links.index:
            p_nom = max(float(network.links.at[link, "p_nom"]), 1.0)
            peak = float((network.links_t.p0[link].abs() / p_nom * 100.0).max())
            out.append({"label": str(link), "value": round(peak, 1)})
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


def _voltage_profile(network: pypsa.Network) -> list[dict[str, Any]]:
    """Per-bus voltage magnitude (pu) across snapshots: min / mean / max.

    Meaningful for AC ``pf()``; for ``lpf()`` the magnitudes stay at 1.0 pu (or
    the frame is empty), so the caller flags that in the narrative.
    """
    vmag = getattr(network.buses_t, "v_mag_pu", pd.DataFrame())
    if vmag is None or vmag.empty:
        return []
    out: list[dict[str, Any]] = []
    for bus in network.buses.index:
        if bus not in vmag.columns:
            continue
        col = vmag[bus].astype(float)
        out.append(
            {
                "bus": str(bus),
                "min": round(float(col.min()), 4),
                "mean": round(float(col.mean()), 4),
                "max": round(float(col.max()), 4),
            }
        )
    return out


def _nodal_balance(network: pypsa.Network) -> list[dict[str, Any]]:
    """Mean generation vs load (MW) per bus — both populated by the flow solve."""
    load_dense = (
        network.get_switchable_as_dense("Load", "p_set")
        if len(network.loads)
        else pd.DataFrame(index=network.snapshots)
    )
    gen_p = network.generators_t.p
    out: list[dict[str, Any]] = []
    for bus in network.buses.index:
        bus_loads = list(network.loads.index[network.loads.bus == bus])
        load_val = (
            float(
                load_dense.reindex(columns=bus_loads, fill_value=0.0).sum(axis=1).mean()
            )
            if bus_loads
            else 0.0
        )
        gen_names = list(network.generators.index[network.generators.bus == bus])
        gen_val = (
            float(gen_p.reindex(columns=gen_names, fill_value=0.0).sum(axis=1).mean())
            if (gen_names and not gen_p.empty)
            else 0.0
        )
        out.append({"label": str(bus), "load": load_val, "generation": gen_val})
    out.sort(key=lambda x: x["load"], reverse=True)
    return out


def run_power_flow(
    network: pypsa.Network,
    *,
    linear: bool,
    currency: str,
    snapshot_count: int,
    snapshot_weight: float,
    notes: list[str],
) -> dict[str, Any]:
    """Run a power-flow study and return the focused result payload.

    Args:
        network: the built (un-optimised) PyPSA network.
        linear: ``True`` → ``lpf()`` (DC); ``False`` → ``pf()`` (AC).
        currency: symbol for formatted summary strings.
        snapshot_count / snapshot_weight: modelled-window meta for ``runMeta``.
        notes: the build-phase narrative to append flow notes to.
    """
    weights = (
        network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    )

    converged = True
    n_iter_max = 0
    max_error = 0.0
    error_msg: str | None = None
    try:
        if linear:
            network.lpf()
        else:
            res = network.pf()
            conv = getattr(res, "converged", None)
            if conv is not None and getattr(conv, "size", 0):
                converged = bool(conv.to_numpy().all())
            n_iter = getattr(res, "n_iter", None)
            if n_iter is not None and getattr(n_iter, "size", 0):
                n_iter_max = int(n_iter.to_numpy().max())
            err = getattr(res, "error", None)
            if err is not None and getattr(err, "size", 0):
                max_error = float(err.to_numpy().max())
    except Exception as exc:  # noqa: BLE001 — surface failure as a result, not a 500
        converged = False
        error_msg = str(exc)

    method = "Linear (DC) power flow" if linear else "AC power flow (Newton-Raphson)"

    # ── Derived readouts ──────────────────────────────────────────────────────
    line_loading = _branch_loading(network) if error_msg is None else []
    voltage_profile = (
        _voltage_profile(network) if (not linear and error_msg is None) else []
    )
    nodal_balance = _nodal_balance(network) if error_msg is None else []

    losses_mwh = 0.0
    peak_loss_mw = 0.0
    if not linear and error_msg is None and not network.lines_t.p0.empty:
        # For a lossy AC branch, p0 (into bus0) + p1 (into bus1) = I²R losses ≥ 0.
        loss = (network.lines_t.p0 + network.lines_t.p1).sum(axis=1)
        if not network.transformers.empty and not network.transformers_t.p0.empty:
            loss = loss + (network.transformers_t.p0 + network.transformers_t.p1).sum(
                axis=1
            )
        losses_mwh = weighted_sum(loss, weights)
        peak_loss_mw = float(loss.max()) if len(loss) else 0.0

    peak_line = line_loading[0] if line_loading else None
    vmins = [v["min"] for v in voltage_profile]
    vmaxs = [v["max"] for v in voltage_profile]

    # ── Narrative ─────────────────────────────────────────────────────────────
    if error_msg is not None:
        notes.append(
            f"{method} did not run: {error_msg}. Power flow needs branch reactance "
            "(x > 0) and a generator in every connected sub-network (slack)."
        )
    else:
        notes.append(
            f"{method} solved over {snapshot_count} snapshot(s)"
            + (
                f" — converged in ≤{n_iter_max} iterations (max mismatch {max_error:.2e})."
                if not linear
                else " — direct linear solve, lossless, |V| = 1.0 pu."
            )
        )
        if not linear and not converged:
            notes.append(
                "One or more snapshots did NOT converge — results are unreliable."
            )
    notes.append(
        "Power-flow mode reports network physics only — no costs, prices, or emissions "
        "(those come from an optimisation run)."
    )

    # ── Summary KPI cards ─────────────────────────────────────────────────────
    n_branches = len(network.lines) + len(network.transformers) + len(network.links)
    summary: list[dict[str, Any]] = [
        {
            "label": "Method",
            "value": "Linear (DC)" if linear else "AC (NR)",
            "detail": method,
        },
        {
            "label": "Convergence",
            "value": (
                "n/a" if linear else ("Converged" if converged else "Did not converge")
            ),
            "detail": (
                error_msg
                or (
                    "direct solve"
                    if linear
                    else f"≤{n_iter_max} iterations, max mismatch {max_error:.1e}"
                )
            ),
        },
        {
            "label": "Buses",
            "value": f"{len(network.buses):,}",
            "detail": f"{n_branches:,} branches",
        },
    ]
    if peak_line is not None:
        summary.append(
            {
                "label": "Peak line loading",
                "value": f"{peak_line['value']:.0f}%",
                "detail": f"on {peak_line['label']}",
            }
        )
    if voltage_profile:
        summary.append(
            {
                "label": "Voltage range",
                "value": f"{min(vmins):.3f}–{max(vmaxs):.3f} pu",
                "detail": "per-unit bus magnitude",
            }
        )
    if not linear and error_msg is None:
        summary.append(
            {
                "label": "Losses",
                "value": f"{round(losses_mwh):,} MWh",
                "detail": f"peak {round(peak_loss_mw):,} MW",
            }
        )

    return {
        **EMPTY_OPTIMISE_FIELDS,
        "summary": summary,
        "lineLoading": line_loading,
        "nodalBalance": nodal_balance,
        "powerFlow": {
            "linear": linear,
            "method": method,
            "converged": converged,
            "iterations": n_iter_max,
            "maxError": round(max_error, 8),
            "error": error_msg,
            "voltageProfile": voltage_profile,
            "lossesMwh": round(losses_mwh, 1),
            "peakLossMw": round(peak_loss_mw, 1),
            "currency": currency,
        },
        "narrative": notes,
        "runMeta": {
            "snapshotCount": snapshot_count,
            "snapshotWeight": snapshot_weight,
            "modeledHours": snapshot_count * snapshot_weight,
            "studyMode": "lpf" if linear else "pf",
        },
        "outputs": build_full_outputs(network),
    }
