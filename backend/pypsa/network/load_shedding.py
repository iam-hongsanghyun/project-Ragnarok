"""Load-shedding backstop: PyPSA's ``n.optimize.add_load_shedding``, sized by the system peak.

Shedding is a high-priced generator at every bus (value of lost load, VOLL). PyPSA already provides it
(``Network.optimize.add_load_shedding``, one ``"<bus> load shedding"`` generator per bus), so the builder calls
that and only adds what PyPSA does not: the size and the label. The generators carry the shedding carrier
(``utils/shedding.py``), which is how every result path tells them from supply; runs stored before build version 4 hold
per-bus generators named ``load_shedding_<bus>``, which the same helper still recognises.

Algorithm:
    Each shedding generator may cover the whole demand at any snapshot, so

    $$ P^{shed} = \\max\\left(1,\\ \\max_t \\sum_{l} p^{set}_{l,t}\\right) $$

    where :math:`p^{set}_{l,t}` is the load's time series when it has one and its static ``p_set`` otherwise (a bus
    with both kinds of load counts both). ASCII: p_nom = max(1, max_t sum_l p_set[l, t]); MW.
"""
from __future__ import annotations

import pandas as pd
import pypsa

from ...app.config import load_system_defaults
from ..utils.shedding import SUFFIX, shed_carrier


def system_peak_load(network: pypsa.Network) -> float:
    """``max_t sum_l p_set[l, t]`` in MW: time series where a load has one, its static ``p_set`` elsewhere."""
    loads = network.loads
    if loads.empty:
        return 0.0
    dense = pd.DataFrame(
        {name: float(p) for name, p in pd.to_numeric(loads["p_set"], errors="coerce").fillna(0.0).items()},
        index=network.snapshots,
    )
    dynamic = network.loads_t.p_set
    for name in dynamic.columns:
        if name in dense.columns:
            dense[name] = dynamic[name].reindex(network.snapshots).fillna(0.0).to_numpy()
    return float(dense.sum(axis=1).max()) if len(dense) else 0.0


def add_load_shedding(
    network: pypsa.Network,
    load_totals: dict[str, float] | None,
    notes: list[str],
    enable_load_shedding: bool = False,
    load_shedding_cost: float | None = None,
    currency: str = "$",
) -> None:
    """Add PyPSA's load-shedding generators to every bus when ``enable_load_shedding`` is True.

    Args:
        network: the PyPSA network (buses and loads already added).
        load_totals: unused, kept for the call signature (the size is :func:`system_peak_load`).
        notes: run-narrative collector.
        enable_load_shedding: toggle from Settings.
        load_shedding_cost: VOLL in the selected currency per MWh (default ``system_defaults.json``).
        currency: currency symbol for the narrative note.
    """
    del load_totals
    if not enable_load_shedding:
        notes.append("Load shedding disabled — infeasibility will surface as a solver error.")
        return
    ls_cfg = load_system_defaults()["load_shedding"]
    cost = float(load_shedding_cost) if load_shedding_cost is not None else float(ls_cfg["marginal_cost"])
    p_nom = max(system_peak_load(network), 1.0)
    buses = network.buses.index
    network.optimize.add_load_shedding(suffix=SUFFIX, buses=buses, sign=1, marginal_cost=cost, p_nom=p_nom)
    added = pd.Index([f"{bus}{SUFFIX}" for bus in buses])  # PyPSA names them "<bus><suffix>" (it returns nothing)
    # PyPSA labels the generators carrier "load" and registers a different carrier; use the one name every
    # Ragnarok result path (and the carrier table) knows.
    carrier = shed_carrier()
    network.generators.loc[added, "carrier"] = carrier
    if carrier not in network.carriers.index:
        network.add("Carrier", carrier)
    notes.append(
        f"Load shedding (PyPSA add_load_shedding): {len(added)} generator(s), one per bus, carrier {carrier}, at {cost:.0f} {currency}/MWh "
        f"(value of lost load), p_nom {p_nom:.6g} MW = the system peak of static and time-series loads."
    )
