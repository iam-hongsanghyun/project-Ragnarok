from __future__ import annotations

import warnings
from typing import Any

import pandas as pd
import pypsa

from ..utils.emissions import primary_energy_emissions
from ..utils.series import safe_series
from .pathway_periods import snapshot_active_mask
from ..utils.shedding import is_shedding


def _snapshot_parts(snapshot: object) -> tuple[int | None, object]:
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        return int(snapshot[0]), snapshot[1]
    return None, snapshot


def _snapshot_label(snapshot: object) -> tuple[str, str, int | None]:
    period, timestep = _snapshot_parts(snapshot)
    ts = pd.Timestamp(timestep)
    return ts.strftime("%H:%M"), ts.isoformat(), period


def dispatch_by_carrier(
    generator_dispatch_frame: pd.DataFrame,
    generators: pd.DataFrame,
) -> dict[str, pd.Series]:
    result: dict[str, pd.Series] = {}
    for carrier in generators.carrier.unique():
        names = generators.index[generators.carrier == carrier]
        result[carrier] = (
            generator_dispatch_frame.reindex(columns=names, fill_value=0.0)
            .clip(lower=0.0)
            .sum(axis=1)
        )
    return result


# Carrier names treated as the electricity vector when splitting the dispatch
# mix. A blank / missing bus carrier defaults to electricity — PyPSA's own
# default bus carrier is "AC".
ELECTRICITY_CARRIERS = {"", "ac", "dc", "electricity", "elec", "power"}


def _is_electricity(carrier: object) -> bool:
    s = "" if carrier is None else str(carrier).strip().lower()
    return s in ("", "nan", "none") or s in ELECTRICITY_CARRIERS


def _electricity_bus_names(network: pypsa.Network) -> set[str]:
    buses = network.buses
    if "carrier" not in buses.columns:
        return {str(b) for b in buses.index}
    return {str(b) for b, c in buses["carrier"].items() if _is_electricity(c)}


def electricity_bus_scope(network: pypsa.Network) -> set[str] | None:
    """Electricity buses to scope system-level aggregates to, or ``None``.

    Sector-coupled models carry non-electricity buses (gas, heat, H₂ …) whose
    loads, marginal prices and fuel-supply pseudo-generators must not be lumped
    into the electricity-only system aggregates (demand overlay, peak demand,
    average/peak price, generator capacity). This returns the same bus set the
    electricity dispatch mix (``electricity_dispatch_by_carrier``) is built
    from, and ``None`` when no restriction applies — a single-vector model
    (every bus electricity) or a model with no identifiable electricity bus at
    all (restricting to an empty set would zero every aggregate). Callers must
    treat ``None`` as "use every bus", which keeps single-carrier models
    byte-identical to the unscoped behaviour.
    """
    buses = network.buses
    if buses.empty or "carrier" not in buses.columns:
        return None
    if all(_is_electricity(c) for c in buses["carrier"]):
        return None  # single-vector model — nothing to restrict
    elec = _electricity_bus_names(network)
    if not elec:
        return None  # no electricity vector at all — leave aggregates whole-model
    return elec


def _bus_withdrawal_weights(
    network: pypsa.Network,
    columns: list[Any],
    bus_carrier: list[str] | None = None,
) -> pd.DataFrame | None:
    """Per-snapshot, per-bus withdrawal (MW) from ``n.statistics.withdrawal``.

    Called exactly as PyPSA's ``prices(weighting="load")`` calls it (same
    ``groupby``/``bus_carrier`` arguments), so the weights are PyPSA's: power
    drawn from a bus by loads, StorageUnit/Store charging, links and - a PyPSA
    quirk kept on purpose - the sending end of a line or link. ``None`` when the
    statistic cannot be evaluated or no component has solved flows (e.g. an
    imported run that never stored ``loads-p``).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            w = network.statistics.withdrawal(
                groupby="bus", bus_carrier=bus_carrier, groupby_time=False, drop_zero=False,
                round=9, nice_names=False,
            )
    except Exception:  # noqa: BLE001 - no solved flows / unsupported component mix
        return None
    if w is None or len(w) == 0:
        return None
    if "bus" not in (w.index.names or []):
        return None
    per_bus = w.groupby(level="bus").sum().T
    per_bus = per_bus.reindex(index=network.snapshots, columns=columns).fillna(0.0).clip(lower=0.0)
    return per_bus


def system_price_series(
    network: pypsa.Network,
    elec_scope: set[str] | None,
    load_p_set: pd.DataFrame,
) -> pd.Series:
    """System price per snapshot: nodal prices weighted by PyPSA's load weighting.

    Algorithm:
        $$\\bar\\pi(t) = \\frac{\\sum_b W_b(t)\\,\\pi_b(t)}{\\sum_b W_b(t)}$$
        where $\\pi_b(t)$ is the bus marginal price (currency/MWh) and
        $W_b(t)$ the power withdrawn from bus $b$ (MW) as reported by
        ``n.statistics.withdrawal`` (loads + storage charging + link inputs +
        the sending end of lines/links, PyPSA's own weighting).
        Summed over time with the snapshot weights this is exactly
        ``n.statistics.prices(weighting="load")`` (see
        :func:`system_average_price`). ASCII: price(t) = sum_b(W*pi)/sum_b(W).

    Definition change (P28): the weights used to be the load ``p_set`` alone;
    they are now PyPSA's withdrawals, so a storage unit charging at a bus or a
    link drawing from it pulls the price toward that bus, as in PyPSA. Where a
    snapshot has no withdrawal (or the run stored no flows) the weights fall
    back to the load ``p_set``, then to the unweighted bus mean. ``elec_scope``
    restricts the buses exactly as the other system aggregates are scoped.
    """
    mp = network.buses_t.marginal_price
    if mp.empty:
        return pd.Series(0.0, index=network.snapshots)
    cols = [b for b in mp.columns if elec_scope is None or str(b) in elec_scope] or list(mp.columns)
    prices = mp[cols]
    plain_mean = prices.mean(axis=1)

    carriers = None
    if elec_scope is not None and "carrier" in network.buses.columns:
        bc = network.buses["carrier"].astype(str).replace("", "AC").reindex([str(c) for c in cols])
        carriers = sorted(set(bc.dropna())) or None
    weights = _bus_withdrawal_weights(network, cols, carriers)
    total = weights.sum(axis=1) if weights is not None else None
    result = plain_mean.copy()
    if weights is not None and total is not None:
        weighted = (prices.fillna(0.0) * weights).sum(axis=1) / total.where(total > 0.0)
        result = weighted.fillna(plain_mean)

    # Fallback for snapshots without stored flows: the load set-point weighting.
    loads = network.loads
    needs_fallback = result.isna() | (total <= 0.0) if total is not None else pd.Series(True, index=prices.index)
    if needs_fallback.any() and not load_p_set.empty and "bus" in loads.columns:
        bus_load = (
            load_p_set.clip(lower=0.0)
            .T.groupby(loads["bus"].reindex(load_p_set.columns).astype(str))
            .sum()
            .T.reindex(index=prices.index, columns=[str(c) for c in cols])
            .fillna(0.0)
        )
        bus_load.columns = cols
        ltotal = bus_load.sum(axis=1)
        lw = (prices.fillna(0.0) * bus_load).sum(axis=1) / ltotal.where(ltotal > 0.0)
        result = result.where(~needs_fallback, lw.fillna(plain_mean))
    return result.fillna(plain_mean)


def system_average_price(network: pypsa.Network, elec_scope: set[str] | None = None) -> float | None:
    """Run-average system price from ``n.statistics.prices(weighting="load")``.

    Algorithm:
        $$\\bar\\pi = \\frac{\\sum_t w_t \\sum_b W_b(t)\\,\\pi_b(t)}{\\sum_t w_t \\sum_b W_b(t)}$$
        where $w_t$ is the objective snapshot weight (h) and $W_b(t)$ the power
        withdrawn from bus $b$ (MW). ASCII: avg = sum(w*W*pi) / sum(w*W).

    Buses are grouped by bus carrier (PyPSA's ``groupby="bus_carrier"``) and the
    electricity carriers are combined weighted by their withdrawn energy. The
    snapshot weights are PyPSA's hours (not multiplied by investment-period
    weightings, which scale cost, not physical energy or price).

    Returns:
        currency/MWh, or ``None`` when no marginal prices exist.
    """
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None
    bus_carrier = network.buses["carrier"].astype(str).replace("", "AC") if "carrier" in network.buses.columns else None
    if elec_scope is not None and bus_carrier is not None:
        carriers = sorted(set(bus_carrier[[str(b) in elec_scope for b in bus_carrier.index]]))
    else:
        carriers = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            kwargs: dict[str, Any] = {"weighting": "load", "drop_zero": False, "round": 9}
            if carriers:
                kwargs["bus_carrier"] = carriers
            by_carrier = network.statistics.prices(groupby="bus_carrier", **kwargs)
            energy = network.statistics.withdrawal(
                groupby="bus_carrier", drop_zero=False, round=9, nice_names=False,
                **({"bus_carrier": carriers} if carriers else {}),
            )
    except Exception:  # noqa: BLE001
        return None
    if isinstance(by_carrier, pd.DataFrame):
        by_carrier = by_carrier.mean(axis=1)
    by_carrier = by_carrier.dropna()
    if by_carrier.empty:
        return None
    if len(by_carrier) == 1:
        return float(by_carrier.iloc[0])
    if isinstance(energy, pd.DataFrame):
        energy = energy.sum(axis=1)
    e = energy.groupby(level="bus_carrier").sum().reindex(by_carrier.index).fillna(0.0).clip(lower=0.0)
    return float((by_carrier * e).sum() / e.sum()) if e.sum() > 0 else float(by_carrier.mean())


def weighted_mean(series: pd.Series, weights: pd.Series) -> float:
    """Snapshot-weighted mean ($\\sum w x / \\sum w$); plain mean if the weights sum to zero."""
    w = weights.reindex(series.index).fillna(1.0)
    total = float(w.sum())
    return float((series * w).sum() / total) if total > 0.0 else float(series.mean())


def electricity_dispatch_by_carrier(
    network: pypsa.Network,
    generator_dispatch_frame: pd.DataFrame,
) -> dict[str, pd.Series]:
    """The electricity dispatch mix, carrier-aware for sector-coupled models.

    Generators on electricity buses grouped by carrier, plus conversion-Link
    injections into electricity buses grouped by the Link's carrier — so a CCGT
    modelled as a gas→electricity Link shows up as ``CCGT`` power, while its gas
    fuel-supply generator (on the gas bus) is excluded rather than lumped in as a
    huge primary-energy slice. Pure transmission Links (electricity→electricity,
    e.g. HVDC) are not counted as supply.

    For a single-carrier (all-electricity) model this reduces exactly to grouping
    every generator by carrier — the previous behaviour.
    """
    elec_buses = _electricity_bus_names(network)
    gens = network.generators
    if "bus" in gens.columns:
        gens = gens[gens["bus"].astype(str).isin(elec_buses)]
    result = dispatch_by_carrier(generator_dispatch_frame, gens)
    _add_conversion_link_injections(network, elec_buses, result)
    return result


def _link_port_efficiency(
    network: pypsa.Network,
    link: str,
    port: str,
    snapshots: pd.Index,
) -> pd.Series:
    """Per-snapshot efficiency of a Link output port (``"1"``, ``"2"``, …).

    Resolved dense (``get_switchable_as_dense``) so a ``links-efficiency{N}``
    time series — which the solve honours — overrides the static column. Falls
    back to the static value, then to the historical default (1.0 for ``bus1``,
    0.0 for extra ports, matching the previous static-only behaviour).
    """
    attr = "efficiency" if port == "1" else f"efficiency{port}"
    default = 1.0 if port == "1" else 0.0
    try:
        dense = network.get_switchable_as_dense("Link", attr)
        if link in dense.columns:
            return dense[link].reindex(snapshots).astype(float).fillna(default)
    except Exception:
        pass  # attribute not registered on this network — use the static column
    links = network.links
    if attr in links.columns and pd.notna(links.at[link, attr]):
        return pd.Series(float(links.at[link, attr]), index=snapshots)
    return pd.Series(default, index=snapshots)


def _add_conversion_link_injections(
    network: pypsa.Network,
    elec_buses: set[str],
    result: dict[str, pd.Series],
) -> None:
    """Fold each conversion Link's electricity output into ``result`` under the
    Link's carrier.

    Output ports are discovered dynamically — ``bus1`` plus every ``bus{N}``
    column PyPSA registered (CHP heat/power co-products and the like), the same
    discovery ``energy_balance.py`` uses — so a co-product on ``bus4``+ is not
    silently dropped. Only Links whose input (bus0) is NOT electricity count as
    supply (transmission links stay out).

    The injection prefers the actual solved output flow ``p{N}``
    (injection = max(-p{N}, 0)), which honours time-varying ``efficiency{N}``
    series exactly and agrees with ``energy_balance.py``. When the port flow is
    absent (the light stored-run path injects ``p0`` only), it falls back to
    ``p0`` × the dense per-snapshot ``efficiency{N}``.
    """
    # Links and Processes convert the same way (P29): ``p0`` is the withdrawal at
    # bus0 and ``p{N}`` the (negative) injection at bus{N}; a Process just has no
    # ``efficiency{N}`` (its ``rate{N}`` / ``-rate0`` plays that role).
    snapshots = network.snapshots
    sources: list[tuple[str, pd.DataFrame, Any]] = [("Link", network.links, network.links_t)]
    if len(getattr(network, "processes", [])):
        sources.append(("Process", network.processes, network.c.processes.dynamic))
    for comp, links, dyn in sources:
        if len(links) == 0 or dyn["p0"].empty:
            continue
        p0 = dyn["p0"]
        # Output ports: bus1 plus any multi-port columns (bus2, bus3, … — a blank
        # port cell = port unused). Mirrors energy_balance.py's discovery.
        ports = ["1"] + sorted(
            c[3:] for c in links.columns
            if c.startswith("bus") and c[3:].isdigit() and c not in ("bus0", "bus1")
        )
        for link in links.index:
            if link not in p0.columns:
                continue
            bus0 = str(links.at[link, "bus0"]) if "bus0" in links.columns else ""
            if bus0 in elec_buses:
                continue  # same-vector / transmission link, not a conversion into power
            inflow = p0[link].reindex(snapshots).fillna(0.0).clip(lower=0.0)
            carrier = str(links.at[link, "carrier"]) if "carrier" in links.columns else ""
            key = carrier or str(link)
            for port in ports:
                bus_col = f"bus{port}"
                if bus_col not in links.columns:
                    continue
                out_bus = links.at[link, bus_col]
                if not isinstance(out_bus, str) or out_bus not in elec_buses:
                    continue
                pn = dyn[f"p{port}"] if f"p{port}" in dyn else None
                if pn is not None and link in pn.columns:
                    # Solved flow: -p{N} is the injection into bus{N}.
                    inj = (-pn[link].reindex(snapshots).fillna(0.0)).clip(lower=0.0)
                elif comp == "Process":
                    rate0 = float(links.at[link, "rate0"]) if "rate0" in links.columns else -1.0
                    raten = float(links.at[link, f"rate{port}"]) if f"rate{port}" in links.columns else 0.0
                    inj = inflow * (raten / -rate0 if rate0 else 0.0)
                else:
                    inj = inflow * _link_port_efficiency(network, link, port, snapshots)
                if not (inj.abs() > 1e-12).any():
                    continue
                result[key] = result[key].add(inj, fill_value=0.0) if key in result else inj


def build_dispatch_series(
    network: pypsa.Network,
    by_carrier: dict[str, pd.Series],
    load_dispatch: pd.Series,
    generator_dispatch_frame: pd.DataFrame,
) -> tuple[list[dict], list[dict]]:
    # Vectorised: pull whole columns to Python lists once (C-level `tolist()`),
    # then build the sparse per-snapshot dicts from those — instead of a
    # per-(snapshot, carrier/generator) `.loc[...]` label lookup, which is
    # O(snapshots × components) and dominates a multi-bus full-year run.
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    carrier_df = pd.DataFrame(by_carrier, index=snapshots)
    carrier_cols = [str(c) for c in carrier_df.columns]
    carrier_rows = carrier_df.to_numpy().tolist()
    load_vals = load_dispatch.reindex(snapshots).to_numpy().tolist()
    gen_cols = [str(g) for g in generator_dispatch_frame.columns]
    gen_rows = generator_dispatch_frame.reindex(index=snapshots).clip(lower=0.0).to_numpy().tolist()

    dispatch_series: list[dict] = []
    generator_dispatch_series: list[dict] = []
    for i, (label, stamp, period) in enumerate(labels):
        total = float(load_vals[i])
        crow = carrier_rows[i]
        values = {carrier_cols[j]: v for j, v in enumerate(crow) if abs(v) > 1e-6}
        dispatch_series.append(
            {"label": label, "timestamp": stamp, "period": period, "values": values, "total": total}
        )
        grow = gen_rows[i]
        gen_values = {gen_cols[j]: v for j, v in enumerate(grow) if v > 1e-6}
        generator_dispatch_series.append(
            {"label": label, "timestamp": stamp, "period": period, "values": gen_values, "total": total}
        )
    return dispatch_series, generator_dispatch_series


def curtailment_mw_by_generator(
    network: pypsa.Network,
    dispatch: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Curtailed power (MW) per snapshot per generator, from ``n.statistics.curtailment``.

    Algorithm:
        $$c_g(t) = \\max\\left(\\bar p_g(t)\\,P^{opt}_g - p_g(t),\\,0\\right)\\cdot a_g(t)$$
        where $\\bar p_g(t)$ is ``p_max_pu`` (per unit), $P^{opt}_g$ the solved
        ``p_nom_opt`` (MW), $p_g(t)$ the dispatch (MW) and $a_g(t)\\in\\{0,1\\}$
        is 1 while the unit is active (multi-period ``build_year``/``lifetime``).
        ASCII: curt = max(p_max_pu * p_nom_opt - p, 0) * active.

    PyPSA's ``curtailment`` is evaluated with ``groupby_time=False`` (MW per
    snapshot; energy is ``sum_t w_t c(t)`` with the ``generators`` snapshot
    weights). Scope: ``Generator`` only (headroom on a Link or StorageUnit is
    not curtailment), restricted — as PyPSA documents — to assets with a
    time-varying ``p_max_pu`` (a thermal unit at static availability running
    below ``p_nom`` is part-loaded, not curtailed), excluding the injected
    ``load_shedding_*`` backstop. PyPSA does not mask inactive assets in a
    multi-period run (an unbuilt unit would report its whole availability as
    curtailed), so the activity mask is applied here.

    Args:
        network: solved (or output-injected) network.
        dispatch: optional dispatch frame (MW), used only when
            ``network.generators_t.p`` is empty (a network that was never
            solved, whose dispatch was supplied separately); it is then
            attached as ``generators_t.p`` so PyPSA's statistic can read it.

    Returns:
        DataFrame indexed by ``network.snapshots``, one column per variable
        generator; empty (no columns) when there is none.
    """
    snapshots = network.snapshots
    if dispatch is not None and network.generators_t.p.empty and not dispatch.empty:
        network.generators_t.p = dispatch.reindex(index=snapshots).fillna(0.0)
    tv = network.generators_t.p_max_pu
    gens = [
        g for g in tv.columns
        if not is_shedding(g) and g in network.generators.index
    ]
    empty = pd.DataFrame(index=snapshots)
    if not gens or network.generators_t.p.empty:
        return empty
    # p_nom_opt is populated by a solve; a rebuilt/imported network may carry the
    # 0.0 default for non-extendable units, where the input p_nom is the rating.
    ensure_p_nom_opt(network)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = network.statistics.curtailment(
                components=["Generator"], groupby=False, groupby_time=False,
                drop_zero=False, round=9,
            )
    except Exception:  # noqa: BLE001
        return empty
    if raw is None or len(raw) == 0:
        return empty
    frame = raw.droplevel("component").T if "component" in (raw.index.names or []) else raw.T
    frame = frame.reindex(index=snapshots, columns=gens).fillna(0.0).clip(lower=0.0)
    active = snapshot_active_mask(network, "generators")
    if active is not None:
        frame = frame.where(active.reindex(index=snapshots, columns=gens, fill_value=True), 0.0)
    return frame


def ensure_p_nom_opt(network: pypsa.Network) -> None:
    """Fill ``p_nom_opt`` with ``p_nom`` where a unit was never sized (<= 0 and fixed).

    PyPSA's capacity statistics read ``p_nom_opt``; a network rebuilt from stored
    outputs has the 0.0 default for non-extendable units, which would make every
    availability-based statistic zero. Extendable units are left alone (a solved
    0 MW is a real result).
    """
    gens = network.generators
    if gens.empty or "p_nom_opt" not in gens.columns:
        return
    unsized = (gens["p_nom_opt"].fillna(0.0) <= 0.0) & ~gens["p_nom_extendable"].astype(bool)
    if unsized.any():
        gens.loc[unsized, "p_nom_opt"] = gens.loc[unsized, "p_nom"].fillna(0.0)


def build_curtailment_series(
    network: pypsa.Network,
    generator_dispatch_frame: pd.DataFrame | None = None,
) -> list[dict]:
    """Per-carrier curtailed power (MW) per snapshot.

    Definition (P28): PyPSA's ``n.statistics.curtailment`` — see
    :func:`curtailment_mw_by_generator` for the formula and scope. Values are MW
    per snapshot summed per carrier (units: MW; energy = MW x snapshot weight).
    ``generator_dispatch_frame`` is only used when the network carries no
    ``generators_t.p`` of its own (see :func:`curtailment_mw_by_generator`).
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    curt = curtailment_mw_by_generator(network, generator_dispatch_frame)
    if curt.shape[1] == 0:
        return [
            {"label": lbl, "timestamp": st, "period": p, "values": {}}
            for (lbl, st, p) in labels
        ]
    carriers = network.generators.loc[list(curt.columns), "carrier"].astype(str)
    by_carrier = curt.T.groupby(carriers).sum().T  # snapshots x carriers
    cols = [str(c) for c in by_carrier.columns]
    rows = by_carrier.to_numpy().tolist()
    return [
        {
            "label": lbl,
            "timestamp": st,
            "period": p,
            "values": {cols[j]: float(v) for j, v in enumerate(rows[i]) if v > 1e-6},
        }
        for i, (lbl, st, p) in enumerate(labels)
    ]


def curtailment_mwh_by_generator(network: pypsa.Network) -> dict[str, float]:
    """Curtailed energy (MWh) per variable generator over the run.

    $E_g = \\sum_t w_t\\,c_g(t)$ with $w_t$ the ``generators`` snapshot weight
    (hours; investment-period weightings scale cost, not energy). ASCII:
    E = sum(w * curt). Generators without a time-varying ``p_max_pu`` are absent.
    """
    curt = curtailment_mw_by_generator(network)
    if curt.shape[1] == 0:
        return {}
    w = network.snapshot_weightings["generators"].reindex(network.snapshots).fillna(1.0)
    energy = curt.mul(w, axis=0).sum(axis=0)
    return {str(g): float(v) for g, v in energy.items()}


def build_price_emissions_series(
    network: pypsa.Network,
    price_series: pd.Series,
    emissions_factors: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict]]:
    if emissions_factors is None:
        emissions_factors = (
            network.carriers["co2_emissions"].to_dict()
            if "co2_emissions" in network.carriers.columns
            else {}
        )
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    # Per-snapshot generator emissions (tCO₂/h) = Σ_g p_g/η_g × co2 on PyPSA's
    # primary_energy basis (signed dispatch, time-varying η; RB10). Storage
    # depletion is a stock change, not a power flow, so it appears only in the
    # run total (emissionsBreakdown.totalTco2), not in this series.
    rate = primary_energy_emissions(network, emissions_factors).generator_rate_tph
    if rate.shape[1]:
        emission_vals = rate.sum(axis=1).reindex(snapshots).fillna(0.0).to_numpy().tolist()
    else:
        emission_vals = [0.0] * len(labels)
    price_vals = price_series.reindex(snapshots).to_numpy().tolist()

    system_price = [
        {"label": lbl, "timestamp": st, "period": p, "value": float(price_vals[i])}
        for i, (lbl, st, p) in enumerate(labels)
    ]
    system_emissions = [
        {"label": lbl, "timestamp": st, "period": p, "value": float(emission_vals[i])}
        for i, (lbl, st, p) in enumerate(labels)
    ]
    return system_price, system_emissions


def build_storage_soc_series(network: pypsa.Network) -> list[dict]:
    """Per-carrier state of charge (MWh) per snapshot.

    Sums ``state_of_charge`` across the StorageUnits of each carrier and
    ``stores_t.e`` across the Stores of each carrier (PyPSA-Eur-style
    batteries are Store + Link pairs), so the dashboard plots SoC per storage
    technology whichever component models it. SoC is a stock (MWh), not a rate
    — no snapshot weighting applies.
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    frames: list[pd.DataFrame] = []
    for static, soc_frame in (
        (network.storage_units, network.storage_units_t.state_of_charge),
        (network.stores, network.stores_t.e),
    ):
        if len(static.index) == 0 or soc_frame.empty:
            continue
        soc = soc_frame.reindex(index=snapshots).fillna(0.0)
        units = [u for u in soc.columns if u in static.index]
        if not units:
            continue
        # Blank carrier = the default electrical carrier, as everywhere else (dispatch, energy balance).
        carriers = static.loc[units, "carrier"].astype(str).replace("", "AC")
        frames.append(soc[units].T.groupby(carriers).sum().T)  # snapshots x carriers
    if not frames:
        return [
            {"label": lbl, "timestamp": st, "period": p, "values": {}}
            for (lbl, st, p) in labels
        ]
    by_carrier = pd.concat(frames, axis=1)
    by_carrier = by_carrier.T.groupby(level=0).sum().T  # same carrier on units + stores
    cols = [str(c) for c in by_carrier.columns]
    rows = by_carrier.to_numpy().tolist()
    return [
        {
            "label": lbl,
            "timestamp": st,
            "period": p,
            "values": {cols[j]: float(v) for j, v in enumerate(rows[i]) if abs(v) > 1e-6},
        }
        for i, (lbl, st, p) in enumerate(labels)
    ]


def build_storage_series(network: pypsa.Network) -> list[dict]:
    """System storage series, aggregated across StorageUnits and Stores.

    Charge and discharge are split **per unit** before summing, so one unit
    charging while another discharges is reported as both flows rather than
    netted to a smaller number (which understated throughput and storage
    revenue). State of charge sums ``state_of_charge`` (StorageUnits) and
    ``e`` (Stores). A Store's ``p`` is positive when it discharges into its
    bus, the same sign as a StorageUnit's.
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    zeros = pd.Series(0.0, index=snapshots)
    charge = zeros.copy()
    discharge = zeros.copy()
    state = zeros.copy()
    present = False
    for static, p_frame, soc_frame in (
        (network.storage_units, network.storage_units_t.p, network.storage_units_t.state_of_charge),
        (network.stores, network.stores_t.p, network.stores_t.e),
    ):
        if len(static.index) == 0:
            continue
        present = True
        for unit in static.index:
            p_unit = safe_series(p_frame, unit).reindex(snapshots).fillna(0.0)
            charge = charge + p_unit.clip(upper=0.0).abs()
            discharge = discharge + p_unit.clip(lower=0.0)
            state = state + safe_series(soc_frame, unit).reindex(snapshots).fillna(0.0)
    if not present:
        return [
            {"label": lbl, "timestamp": st, "period": p, "charge": 0.0, "discharge": 0.0, "state": 0.0}
            for (lbl, st, p) in labels
        ]
    # `tolist()` each aggregate series once instead of a per-snapshot `.loc`.
    charge_vals = charge.to_numpy().tolist()
    discharge_vals = discharge.to_numpy().tolist()
    soc_vals = state.to_numpy().tolist()
    return [
        {"label": lbl, "timestamp": st, "period": p,
         "charge": float(charge_vals[i]), "discharge": float(discharge_vals[i]),
         "state": float(soc_vals[i])}
        for i, (lbl, st, p) in enumerate(labels)
    ]


def metric_definitions(currency: str = "$") -> dict[str, dict[str, str]]:
    """Unit + definition metadata for result fields whose meaning follows PyPSA (P28/RB10).

    Emitted once per result as ``metricDefinitions`` so a consumer (UI, MCP,
    export) can read what a number means without the source.
    """
    return {
        "curtailmentSeries": {
            "unit": "MW",
            "definition": (
                "n.statistics.curtailment (groupby_time=False): max(p_max_pu * p_nom_opt - p, 0) per "
                "generator with a time-varying p_max_pu, summed per carrier; load-shedding excluded; "
                "units outside their build/lifetime window masked in multi-period runs."
            ),
        },
        "generatorEnergy.curtailmentMwh": {
            "unit": "MWh",
            "definition": "sum_t w_t * curtailment(t), w_t = generators snapshot weighting (hours).",
        },
        "systemPriceSeries": {
            "unit": f"{currency}/MWh",
            "definition": (
                "Per snapshot: bus marginal prices weighted by power withdrawn from each bus "
                "(n.statistics.withdrawal: loads + storage charging + link inputs + the sending end of lines/links, "
                "as PyPSA weights it) - the per-snapshot form of n.statistics.prices(weighting='load')."
            ),
        },
        "runMeta.averageSystemPrice": {
            "unit": f"{currency}/MWh",
            "definition": (
                "n.statistics.prices(weighting='load') over the run: sum(w*W*price)/sum(w*W) "
                "with W the power withdrawn from the bus."
            ),
        },
        "emissionsBreakdown": {
            "unit": "tCO2e",
            "definition": (
                "PyPSA primary_energy accounting (see emissions.py): generators sum(w*p/efficiency)*co2_emissions "
                "(signed; investment-period years weighted in a multi-period solve) plus non-cyclic StorageUnit/Store "
                "co2_emissions*(initial - final stock). Link/Process flows are not counted (emissions stay at the "
                "fuel generator). Equals the primary_energy constraint LHS; per-owner emissions "
                "(companyBreakdown, companyStatement) allocate the same terms and sum to it."
            ),
        },
        "generatorEconomics.revenue": {
            "unit": currency,
            "definition": (
                "n.statistics.revenue per asset: sum_t w_t * p(t) * nodal price (net of charging for storage; "
                "net port value for a Process), x the investment-period objective weight in a pathway run; "
                "assets outside their build/lifetime window contribute 0."
            ),
        },
        "generatorEconomics.grossMargin": {
            "unit": currency,
            "definition": (
                "n.statistics.revenue minus variable cost (sum_t w_t * marginal_cost(t) * p(t), carbon adder and "
                "piecewise overlay folded in)."
            ),
        },
        "generatorEconomics.capturePrice": {
            "unit": f"{currency}/MWh",
            "definition": (
                "n.statistics.revenue / n.statistics.supply (output only): the market value of the asset. Equals "
                "n.statistics.market_value for a unit that never absorbs power."
            ),
        },
        "generatorEconomics.capacityFactor": {
            "unit": "p.u.",
            "definition": (
                "n.statistics.capacity_factor: mean |p| / p_nom_opt, hours-weighted over the investment periods the "
                "asset exists in; a carrier value is capacity-weighted."
            ),
        },
        "expansionResults.capex_horizon": {
            "unit": currency,
            "definition": (
                "n.statistics.capex over the modelled horizon (PyPSA's periodised investment cost, excluding fom_cost; "
                "installed + expanded). capex_expanded / capex_installed are n.statistics.expanded_capex / installed_capex "
                "(new build vs already-built, sunk capacity); overnight_total is n.statistics.overnight_cost and fom_total "
                "is n.statistics.fom, both as PyPSA charged them. capital_cost is the component's periodised cost per unit "
                "for the horizon (capital_cost, or overnight_cost x annuity x nyears)."
            ),
        },
        "expansionResults.capex_annual": {
            "unit": f"{currency}/yr",
            "definition": (
                "capex_horizon / n.nyears: the same n.statistics.capex shown PER YEAR. The only conversion made; "
                "a display basis, not a PyPSA quantity."
            ),
        },
        "lineLoading": {
            "unit": "%",
            "definition": (
                "Peak over snapshots of |p0| / (s_nom_opt or p_nom_opt) x 100 per Line, Link and Transformer. "
                "Kept off n.statistics.transmission, which is the net energy transmitted (MWh), not a peak loading."
            ),
        },
    }
