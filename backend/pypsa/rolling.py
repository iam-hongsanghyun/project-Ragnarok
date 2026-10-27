from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .utils.coerce import number


@dataclass
class RollingHorizonConfig:
    enabled: bool
    horizon_snapshots: int
    overlap_snapshots: int
    step_snapshots: int
    #: Soft terminal-SOC target on the LAST window (see :func:`terminal_soc_hook`).
    terminal_soc: bool = True
    #: Currency per MWh of terminal shortfall; ``None`` = auto (:func:`auto_terminal_penalty`).
    terminal_soc_penalty: float | None = None


def parse_rolling_config(raw: dict[str, Any] | None) -> RollingHorizonConfig:
    raw = raw or {}
    enabled = bool(raw.get("enabled"))
    horizon = max(1, int(number(raw.get("horizonSnapshots"), 168)))
    overlap = max(0, int(number(raw.get("overlapSnapshots"), 24)))
    step = max(1, horizon - overlap)
    terminal = raw.get("terminalSoc")
    penalty_raw = raw.get("terminalSocPenalty")
    penalty = None if penalty_raw in (None, "") else max(0.0, float(number(penalty_raw, 0.0)))
    return RollingHorizonConfig(
        enabled=enabled,
        horizon_snapshots=horizon,
        overlap_snapshots=overlap,
        step_snapshots=step,
        terminal_soc=True if terminal is None else bool(terminal),
        terminal_soc_penalty=penalty,
    )


#: Auto penalty = this x the dearest marginal cost, so refilling storage in the last window
#: (cost = marginal cost / charge efficiency) is always cheaper than paying the shortfall.
AUTO_PENALTY_FACTOR = 2.0


def auto_terminal_penalty(network: Any) -> float:
    """Value of one stored MWh at the horizon end: ``2 x`` the dearest generator marginal cost (floor 1.0).

    Energy left in storage at the end of the horizon would otherwise be worth nothing, so
    the last window dumps it, and earlier windows (which cannot see the end) have already
    drawn it down. Valuing the shortfall above the cost of re-creating the energy (the
    dearest marginal cost, with headroom for round-trip losses) makes the last window
    refill the storage whenever capacity allows and give way only when the load needs it.
    """
    mc = 0.0
    gens = getattr(network, "generators", None)
    if gens is not None and len(gens) and "marginal_cost" in gens.columns:
        mc = float(max(0.0, gens["marginal_cost"].max()))
    return AUTO_PENALTY_FACTOR * mc if mc > 0 else 1.0


def terminal_soc_targets(network: Any) -> dict[str, dict[str, float]]:
    """Initial energy per storage unit / store (> 0 only), captured BEFORE any window runs.

    Rolling horizon overwrites ``state_of_charge_initial`` / ``e_initial`` with the previous
    window's end state, so the horizon-start values must be read up front.
    """
    out: dict[str, dict[str, float]] = {"StorageUnit": {}, "Store": {}}
    su = getattr(network, "storage_units", None)
    if su is not None and len(su) and "state_of_charge_initial" in su.columns:
        out["StorageUnit"] = {str(k): float(v) for k, v in su["state_of_charge_initial"].items() if v and v > 0}
    st = getattr(network, "stores", None)
    if st is not None and len(st) and "e_initial" in st.columns:
        out["Store"] = {str(k): float(v) for k, v in st["e_initial"].items() if v and v > 0}
    return out


def terminal_soc_hook(
    targets: dict[str, dict[str, float]],
    penalty: float,
    horizon_end: Any,
    notes: list[str] | None = None,
):
    r"""``extra_functionality`` fragment: soft ``soc[end] + shortfall >= initial`` on the last window.

    Algorithm:
        $$ E_{u,T} + s_u \ge E_{u,0},\quad s_u \ge 0,\quad \min\ \dots + \pi \sum_u s_u $$
        ASCII: E[u,T] + s[u] >= E0[u]; s[u] >= 0; objective += penalty * sum(s)
        E_{u,T}: energy of unit u at the end of the horizon (MWh); E_{u,0}: its initial
        energy (MWh); s_u: shortfall (MWh); pi: penalty (currency/MWh).

    Because the shortfall is unbounded above (up to E0) the constraint can never make a
    window infeasible; it only prices draining the storage. Applied only when the window's
    last snapshot is the horizon's last snapshot.
    """
    state = {"done": False}

    def hook(n: Any, snapshots: Any) -> None:
        if len(snapshots) == 0 or snapshots[-1] != horizon_end or state["done"]:
            return
        m = n.model
        added = 0
        for comp, var_name in (("StorageUnit", "StorageUnit-state_of_charge"), ("Store", "Store-e")):
            tg = targets.get(comp) or {}
            if not tg or var_name not in m.variables:
                continue
            import pandas as pd

            names = [k for k in tg if k in set(m.variables[var_name].coords["name"].values)]
            if not names:
                continue
            idx = pd.Index(names, name="name")
            end = m.variables[var_name].loc[horizon_end].sel(name=names)
            target = pd.Series([tg[k] for k in names], index=idx)
            short = m.add_variables(lower=0, coords=[idx], name=f"terminal_soc_shortfall-{comp}")
            m.add_constraints(end + short >= target, name=f"terminal_soc-{comp}")
            m.objective.expression = m.objective.expression + penalty * short.sum()
            added += len(names)
        if added:
            state["done"] = True
            if notes is not None:
                notes.append(
                    f"Rolling horizon: last window ends with a soft terminal SOC target = initial energy "
                    f"for {added} storage unit(s), penalty {penalty:g}/MWh shortfall."
                )

    return hook
