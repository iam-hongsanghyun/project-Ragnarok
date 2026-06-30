"""N-1 contingency analysis — branch loading under every single outage.

Distinct from SCLOPF: SCLOPF *constrains the dispatch* so it stays feasible
under any single outage; this reports, for the **given** operating point, which
single passive-branch outages overload a remaining branch.

Built on PyPSA's ``network.lpf_contingency()`` (linear power flow + Line Outage
Distribution Factors): one linear solve plus an algebraic post-contingency flow
for each outage. Evaluated at the peak-demand snapshot (the stress case), since
``lpf_contingency`` runs on a single snapshot.
"""

from __future__ import annotations

from typing import Any

import pypsa

from .full_outputs import build_full_outputs
from .power_flow import EMPTY_OPTIMISE_FIELDS


def _branch_s_nom(network: pypsa.Network, comp: str, name: str) -> float:
    """Rating (MVA) for a passive branch identified by (component, name)."""
    if comp == "Line" and name in network.lines.index:
        return max(float(network.lines.at[name, "s_nom"]), 1.0)
    if comp == "Transformer" and name in network.transformers.index:
        return max(float(network.transformers.at[name, "s_nom"]), 1.0)
    return 1.0


def run_contingency(
    network: pypsa.Network,
    *,
    currency: str,
    snapshot_count: int,
    snapshot_weight: float,
    notes: list[str],
) -> dict[str, Any]:
    """Run N-1 contingency analysis and return the focused result payload."""
    # Evaluate at peak demand — the snapshot most likely to expose an overload.
    if len(network.loads):
        load_dense = network.get_switchable_as_dense("Load", "p_set")
        peak_snap = (
            load_dense.sum(axis=1).idxmax()
            if not load_dense.empty
            else network.snapshots[0]
        )
    else:
        peak_snap = network.snapshots[0]

    error_msg: str | None = None
    contingencies: list[dict[str, Any]] = []
    line_loading: list[dict[str, Any]] = []
    insecure = 0
    n_outages = 0
    base_max = 0.0

    try:
        df = network.lpf_contingency(snapshots=peak_snap)
        base = df["base"]
        outage_cols = [c for c in df.columns if c != "base"]
        n_outages = len(outage_cols)

        for idx, flow in base.items():
            comp, name = idx
            s_nom = _branch_s_nom(network, comp, name)
            line_loading.append(
                {
                    "label": str(name),
                    "value": round(abs(float(flow)) / s_nom * 100.0, 1),
                }
            )
        line_loading.sort(key=lambda r: r["value"], reverse=True)
        base_max = line_loading[0]["value"] if line_loading else 0.0

        for col in outage_cols:
            out_comp, out_name = col
            series = df[col]
            worst_pct = 0.0
            worst_branch: str | None = None
            overloads = 0
            for idx, flow in series.items():
                if idx == col:  # the outaged branch itself carries no flow
                    continue
                comp, name = idx
                pct = abs(float(flow)) / _branch_s_nom(network, comp, name) * 100.0
                if pct > 100.0 + 1e-6:
                    overloads += 1
                if pct > worst_pct:
                    worst_pct = pct
                    worst_branch = str(name)
            if overloads > 0:
                insecure += 1
            contingencies.append(
                {
                    "outage": str(out_name),
                    "worstLoadingPct": round(worst_pct, 1),
                    "worstBranch": worst_branch,
                    "overloadCount": overloads,
                }
            )
        contingencies.sort(key=lambda r: r["worstLoadingPct"], reverse=True)
    except Exception as exc:  # noqa: BLE001 — surface failure as a result, not a 500
        error_msg = str(exc)

    secure = error_msg is None and insecure == 0

    # ── Narrative ─────────────────────────────────────────────────────────────
    if error_msg is not None:
        notes.append(
            f"N-1 contingency analysis did not run: {error_msg}. It needs branch "
            "reactance (x > 0) and a meshed network (a radial branch outage islands load)."
        )
    elif n_outages == 0:
        notes.append(
            "No N-1 contingencies to test — the network has no passive branches whose "
            "outage leaves it connected."
        )
    else:
        notes.append(
            f"N-1 contingency analysis (linear) at peak-demand snapshot {peak_snap}: "
            f"tested {n_outages} single-branch outage(s) — "
            + (
                "N-1 secure (no overloads)."
                if secure
                else f"{insecure} cause an overload."
            )
        )
    notes.append(
        "Contingency analysis reports network physics only — no costs, prices, or emissions."
    )

    # ── Summary KPI cards ─────────────────────────────────────────────────────
    worst = contingencies[0] if contingencies else None
    summary: list[dict[str, Any]] = [
        {
            "label": "N-1 security",
            "value": (
                "n/a"
                if error_msg or n_outages == 0
                else ("Secure" if secure else "Insecure")
            ),
            "detail": (
                error_msg
                or (
                    f"{insecure} of {n_outages} outages overload a branch"
                    if n_outages
                    else "no testable outages"
                )
            ),
        },
    ]
    if worst is not None:
        summary.append(
            {
                "label": "Worst contingency",
                "value": f"{worst['worstLoadingPct']:.0f}%",
                "detail": (
                    f"{worst['worstBranch']} after {worst['outage']} out"
                    if worst["worstBranch"]
                    else f"after {worst['outage']} out"
                ),
            }
        )
    summary.append(
        {
            "label": "Base-case peak loading",
            "value": f"{base_max:.0f}%",
            "detail": "highest branch loading, no outage",
        }
    )
    summary.append(
        {
            "label": "Outages tested",
            "value": f"{n_outages}",
            "detail": "single passive branch (N-1)",
        }
    )

    return {
        **EMPTY_OPTIMISE_FIELDS,
        "summary": summary,
        "lineLoading": line_loading,
        "contingency": {
            "snapshot": str(peak_snap),
            "secure": secure,
            "baseMaxLoadingPct": base_max,
            "outagesTested": n_outages,
            "insecureCount": insecure,
            "contingencies": contingencies,
            "error": error_msg,
            "currency": currency,
        },
        "narrative": notes,
        "runMeta": {
            "snapshotCount": snapshot_count,
            "snapshotWeight": snapshot_weight,
            "modeledHours": snapshot_count * snapshot_weight,
            "studyMode": "contingency",
        },
        "outputs": build_full_outputs(network),
    }
