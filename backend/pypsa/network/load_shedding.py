"""Load-shedding generator injection.

Real generators are imported by `pypsa.Network.import_from_excel`. This
module only owns the optional load-shedding backstop, which is not present
in the user's workbook — it is generated from a Settings toggle.
"""
from __future__ import annotations

import pypsa

from ...app.config import load_system_defaults


def add_load_shedding(
    network: pypsa.Network,
    load_totals: dict[str, float],
    notes: list[str],
    enable_load_shedding: bool = False,
    load_shedding_cost: float | None = None,
    currency: str = "$",
) -> None:
    """Add per-bus load-shedding generators when ``enable_load_shedding`` is True.

    Load shedding represents the value of lost load (VOLL): a high-priced
    "generator" that allows the model to leave demand unserved at a known
    penalty rather than infeasibility. Pricing is supplied by the user via
    ``load_shedding_cost`` in the currency configured in Settings.

    When *enable_load_shedding* is False, no shedding generators are added —
    any supply shortfall will surface as a solver infeasibility error.

    Args:
        network: the PyPSA network. Must have buses already added.
        load_totals: peak demand per bus (MW), used to size the shedding
            generator's p_nom so it can absorb the full shortfall.
        notes: run-narrative collector.
        enable_load_shedding: toggle from Settings.
        load_shedding_cost: VOLL in the selected currency per MWh.
        currency: currency symbol for the narrative note.
    """
    if not enable_load_shedding:
        notes.append("Load shedding disabled — infeasibility will surface as a solver error.")
        return

    cfg = load_system_defaults()
    ls_cfg = cfg["load_shedding"]
    cost = float(load_shedding_cost) if load_shedding_cost is not None else float(ls_cfg["marginal_cost"])

    # Shedding capacity is uncapped: the solver must be free to curtail the
    # full bus demand at any snapshot. We size to the system-wide peak demand
    # across all snapshots (covers both static p_set and time-series loads).
    try:
        peak_total = float(network.loads_t.p_set.sum(axis=1).max())
    except Exception:
        peak_total = 0.0
    static_total = float(sum(load_totals.values())) if load_totals else 0.0
    p_nom_uncapped = max(peak_total, static_total, 1.0)
    for bus in network.buses.index:
        shed_name = f"load_shedding_{bus}"
        network.add(
            "Generator",
            shed_name,
            bus=bus,
            carrier=ls_cfg["carrier"],
            p_nom=p_nom_uncapped,
            marginal_cost=cost,
        )
        network.generators_t.p_max_pu.loc[:, shed_name] = 1.0
    notes.append(
        f"Load shedding generators added for {len(network.buses)} bus(es) "
        f"at {cost:.0f} {currency}/MWh (value of lost load)."
    )
