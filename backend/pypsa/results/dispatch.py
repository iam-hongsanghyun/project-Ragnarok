from __future__ import annotations


import pandas as pd
import pypsa

from ..utils.emissions import per_generator_emission_factor
from ..utils.series import safe_series


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
    links = network.links
    if len(links) == 0 or network.links_t.p0.empty:
        return
    dyn = network.links_t
    p0 = dyn.p0
    snapshots = network.snapshots
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


def build_curtailment_series(
    network: pypsa.Network,
    generator_dispatch_frame: pd.DataFrame,
) -> list[dict]:
    """Per-carrier curtailed power (MW) per snapshot.

    Only generators with a time-varying ``p_max_pu`` (renewables) can be
    curtailed — a thermal unit at static availability running below p_nom is
    part-loaded, not curtailed. The load-shedding backstop (which also gets a
    time-varying p_max_pu) is excluded by name prefix.

    Algorithm:
        curtailment_g(t) = max(p_max_pu_g(t) * p_nom_opt_g - p_g(t), 0)   [MW]
        ASCII: curt = max(avail - dispatch, 0), summed per carrier.
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    tv = network.generators_t.p_max_pu
    gens = [
        g for g in tv.columns
        if not str(g).startswith("load_shedding_") and g in network.generators.index
    ]
    if not gens:
        return [
            {"label": lbl, "timestamp": st, "period": p, "values": {}}
            for (lbl, st, p) in labels
        ]
    # p_nom_opt where solved (>0), else input p_nom — the column exists with a
    # 0.0 default even on unsolved/non-extendable setups.
    p_nom_opt = network.generators.loc[gens, "p_nom_opt"].fillna(0.0) if "p_nom_opt" in network.generators.columns else None
    p_nom_in = network.generators.loc[gens, "p_nom"].fillna(0.0)
    p_nom = p_nom_in if p_nom_opt is None else p_nom_opt.where(p_nom_opt > 0, p_nom_in)
    avail = tv[gens].reindex(snapshots).fillna(0.0).mul(p_nom, axis=1)
    disp = generator_dispatch_frame.reindex(index=snapshots, columns=gens, fill_value=0.0).clip(lower=0.0)
    curt = (avail - disp).clip(lower=0.0)
    carriers = network.generators.loc[gens, "carrier"].astype(str)
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


def build_price_emissions_series(
    network: pypsa.Network,
    by_carrier: dict[str, pd.Series],
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
    # Per-snapshot system emissions (tCO₂/h) = Σ_g clip(dispatch_g, 0) × co2 / η
    # (thermal basis, M3). Summed per generator because η varies by unit, not by
    # carrier — so it can't be applied to the carrier-summed ``by_carrier``.
    eff_ef = per_generator_emission_factor(network, emissions_factors)
    emitting = eff_ef[eff_ef > 0]
    p = network.generators_t.p
    cols = [g for g in emitting.index if g in p.columns] if not p.empty else []
    if cols:
        emissions_total = (p[cols].clip(lower=0.0) * emitting.reindex(cols)).sum(axis=1)
        emission_vals = emissions_total.reindex(snapshots).fillna(0.0).to_numpy().tolist()
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

    Sums ``state_of_charge`` across the storage units of each carrier so the
    dashboard can plot SoC per storage technology. SoC is a stock (MWh), not a
    rate — no snapshot weighting applies.
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    if len(network.storage_units.index) == 0 or network.storage_units_t.state_of_charge.empty:
        return [
            {"label": lbl, "timestamp": st, "period": p, "values": {}}
            for (lbl, st, p) in labels
        ]
    soc = network.storage_units_t.state_of_charge.reindex(index=snapshots).fillna(0.0)
    units = [u for u in soc.columns if u in network.storage_units.index]
    carriers = network.storage_units.loc[units, "carrier"].astype(str)
    by_carrier = soc[units].T.groupby(carriers).sum().T  # snapshots x carriers
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
    """System storage series, aggregated across all storage units.

    Aggregate-then-derive convention (matches the frontend deriveRunResults):
    sum the raw power ``p`` across every unit per snapshot, then split the
    aggregate into charge (abs of the negative part) and discharge (positive
    part). State of charge is summed directly across units.
    """
    snapshots = network.snapshots
    labels = [_snapshot_label(s) for s in snapshots]
    if len(network.storage_units.index) > 0:
        units = list(network.storage_units.index)
        total_p = sum(safe_series(network.storage_units_t.p, unit) for unit in units)
        total_soc = sum(safe_series(network.storage_units_t.state_of_charge, unit) for unit in units)
        # `tolist()` each aggregate series once instead of a per-snapshot `.loc`.
        charge_vals = total_p.clip(upper=0.0).abs().reindex(snapshots).to_numpy().tolist()
        discharge_vals = total_p.clip(lower=0.0).reindex(snapshots).to_numpy().tolist()
        soc_vals = total_soc.reindex(snapshots).to_numpy().tolist()
        return [
            {"label": lbl, "timestamp": st, "period": p,
             "charge": float(charge_vals[i]), "discharge": float(discharge_vals[i]),
             "state": float(soc_vals[i])}
            for i, (lbl, st, p) in enumerate(labels)
        ]
    return [
        {"label": lbl, "timestamp": st, "period": p, "charge": 0.0, "discharge": 0.0, "state": 0.0}
        for (lbl, st, p) in labels
    ]
