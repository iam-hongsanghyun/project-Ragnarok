from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from fastapi import HTTPException

from .utils.coerce import number


@dataclass
class RollingHorizonConfig:
    enabled: bool
    horizon_snapshots: int
    overlap_snapshots: int
    step_snapshots: int
    #: Soft terminal-SOC target on the LAST window (see :func:`terminal_soc_hook`). A rolling-module OPTION, default OFF:
    #: it adds a penalised variable to the last window, so it is declared in the run notes when on.
    terminal_soc: bool = False
    #: Currency per MWh of terminal shortfall; ``None`` = auto (:func:`auto_terminal_penalty`).
    terminal_soc_penalty: float | None = None
    #: Window and overlap in HOURS (the UI / MCP unit). PyPSA counts snapshots, so :func:`resolve_rolling` converts them
    #: with the weights the run uses; ``None`` = the snapshot counts above are authoritative (old presets).
    horizon_hours: float | None = None
    overlap_hours: float | None = None


def parse_rolling_config(raw: dict[str, Any] | None) -> RollingHorizonConfig:
    """Parse ``rollingConfig``: ``horizonHours`` / ``overlapHours`` (preferred) or the snapshot counts (old presets)."""
    raw = raw or {}
    enabled = bool(raw.get("enabled"))
    h_hours = None if raw.get("horizonHours") in (None, "") else float(number(raw.get("horizonHours"), 0.0))
    o_hours = None if raw.get("overlapHours") in (None, "") else float(number(raw.get("overlapHours"), 0.0))
    if h_hours is not None and h_hours <= 0:
        raise HTTPException(status_code=400, detail="rollingConfig.horizonHours must be > 0.")
    if o_hours is not None and (o_hours < 0 or (h_hours is not None and o_hours >= h_hours)):
        raise HTTPException(status_code=400, detail="rollingConfig.overlapHours must satisfy 0 <= overlap < horizon.")
    horizon = max(1, int(number(raw.get("horizonSnapshots"), 168)))
    overlap = max(0, int(number(raw.get("overlapSnapshots"), 24)))
    if h_hours is not None:  # provisional counts at a 1 h step; resolve_rolling redoes them with the run's weights
        horizon = max(1, math.ceil(h_hours - 1e-9))
        overlap = max(0, math.ceil((o_hours or 0.0) - 1e-9))
    step = max(1, horizon - overlap)
    terminal = raw.get("terminalSoc")
    penalty_raw = raw.get("terminalSocPenalty")
    penalty = None if penalty_raw in (None, "") else max(0.0, float(number(penalty_raw, 0.0)))
    return RollingHorizonConfig(
        enabled=enabled,
        horizon_snapshots=horizon,
        overlap_snapshots=overlap,
        step_snapshots=step,
        terminal_soc=False if terminal is None else bool(terminal),
        terminal_soc_penalty=penalty,
        horizon_hours=h_hours,
        overlap_hours=o_hours,
    )


def resolve_rolling(cfg: RollingHorizonConfig, step_hours: float, notes: list[str] | None = None) -> RollingHorizonConfig:
    """Snapshot counts of a window given in hours, at the run's time step (hours between snapshots).

    $$ H_{snap} = \\lceil H_{h} / w \\rceil, \\qquad O_{snap} = \\lceil O_{h} / w \\rceil $$

    ASCII: horizon_snapshots = ceil(horizon_hours / w); overlap_snapshots = ceil(overlap_hours / w), kept below the
    horizon. ``w`` is the run's smallest ``stores`` weighting. A config given as snapshot counts is returned as is.
    """
    if cfg.horizon_hours is None:
        return cfg
    w = step_hours if step_hours > 0 else 1.0
    horizon = max(1, math.ceil(cfg.horizon_hours / w - 1e-9))
    overlap = max(0, math.ceil((cfg.overlap_hours or 0.0) / w - 1e-9))
    if overlap >= horizon:
        overlap = horizon - 1
    out = replace(cfg, horizon_snapshots=horizon, overlap_snapshots=overlap, step_snapshots=max(1, horizon - overlap))
    if notes is not None:
        notes.append(
            f"Rolling horizon: {cfg.horizon_hours:g} h window / {(cfg.overlap_hours or 0.0):g} h overlap = {horizon} / {overlap} snapshots "
            f"at a {w:g} h step (ceil(hours / step))."
        )
    return out


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


#: (sheet, flag) pairs that make a storage cyclic: the end state is tied to the start of the window.
CYCLIC_FLAGS: tuple[tuple[str, str], ...] = (
    ("storage_units", "cyclic_state_of_charge"),
    ("storage_units", "cyclic_state_of_charge_per_period"),
    ("stores", "e_cyclic"),
    ("stores", "e_cyclic_per_period"),
)


def rolling_cyclic_problem(network: Any) -> str | None:
    """Why a network with cyclic storage cannot roll, or ``None``.

    PyPSA solves each window on its own and carries the previous window's end state in as the initial state. A cyclic
    condition (end state = start state) is tied to each window's own start, so it forces every window - the shorter
    trailing one especially - to net-zero storage and is often infeasible. Ragnarok used to switch the flags off silently;
    it now refuses, and the visible workbook step :func:`make_noncyclic` (Forge -> Operations; ``POST /api/model/make-noncyclic``)
    writes the flags.
    """
    hits: list[str] = []
    for sheet, flag in CYCLIC_FLAGS:
        frame = getattr(network, sheet, None)
        if frame is None or not len(frame) or flag not in frame.columns:
            continue
        n_true = int(frame[flag].astype(bool).sum())
        if n_true:
            hits.append(f"{n_true} {sheet} with {flag}=true")
    if not hits:
        return None
    return (
        "Rolling horizon needs non-cyclic storage: " + "; ".join(hits) + ". Each window starts from the previous window's end "
        "state, so a cyclic end = start condition inside a window contradicts the carried state. Run the visible step "
        "'Make non-cyclic for rolling' (Forge -> Operations; POST /api/model/make-noncyclic) to write the flags into the "
        "workbook, or set them yourself, or run without rolling horizon."
    )


def make_noncyclic(model: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The workbook step for rolling horizon: every cyclic flag set to False (input not mutated).

    Returns ``(model, changed)`` with ``changed`` = ``[{sheet, name, attribute}]``.
    """
    out = dict(model)
    changed: list[dict[str, Any]] = []
    truthy = {"true", "1", "yes", "y", "t", "on"}
    for sheet, flag in CYCLIC_FLAGS:
        rows = out.get(sheet)
        if not isinstance(rows, list):
            continue
        new_rows = []
        for row in rows:
            if isinstance(row, dict) and str(row.get(flag, "")).strip().lower() in truthy | {"1.0"}:
                row = {**row, flag: False}
                changed.append({"sheet": sheet, "name": str(row.get("name", "")), "attribute": flag})
            new_rows.append(row)
        out[sheet] = new_rows
    return out, changed
