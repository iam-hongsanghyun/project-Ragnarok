"""Resource adequacy — stochastic renewable ensemble (A1) + LOLE metrics (A2).

A model is solved against one weather year; adequacy asks how the system copes
across the *distribution* of renewable outcomes. Two pure pieces:

**A1 — ensemble generator.** From a base capacity-factor series, produce N
synthetic members that keep the diurnal/seasonal *shape* (multiplicative noise
on the base, so night-time solar stays zero) but perturb the magnitude with a
controllable variability knob. Noise is AR(1) so members are temporally
autocorrelated (a calm/windy spell persists rather than flickering hour to hour).

**A2 — adequacy metrics.** Given available generation per member per snapshot
and the load, compute the reliability metrics regulators use:

    LOLP_t = P(available_t < load_t)                    (loss-of-load probability)
    LOLE   = Σ_t LOLP_t · w_t                            (loss-of-load expectation, h/period)
    EENS   = mean_m Σ_t max(load_t − avail_{m,t}, 0)·w_t (expected energy not served, MWh)

    ASCII: LOLE = sum_t P(shortfall) * weight ; EENS = E[ sum_t shortfall * weight ].

Symbols: available (MW) = firm capacity + Σ renewable capacity · CF + storage
discharge; w_t = snapshot weight (h). Storage discharge comes from the shared
SOC-limited kernel ``storage_dispatch`` (power, energy, efficiency, recharge only
from surplus), used identically by adequacy, the outage Monte Carlo, ELCC and
the convergence sampler. The "1 day in 10 years" yardstick is LOLE ≈ 2.4 h/yr.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from backend.pypsa.results.dispatch import _snapshot_label
from backend.pypsa.utils.shedding import is_shedding

_log = logging.getLogger("pypsa.solver")


def maintenance_available_pmax(network: pypsa.Network) -> pd.DataFrame:
    """Generator ``p_max_pu`` with scheduled-maintenance outages applied.

    A ``maintainable`` generator that the solve scheduled into maintenance
    (``generators_t.maintenance`` = 1) has only ``1 - maintenance_pu`` of its
    capacity available that snapshot:
    $$ a_{g,t} = p^{max}_{g,t}\\,(1 - m_{g,t}\\,\\mu_g) $$
    ASCII: avail_pu[g,t] = p_max_pu[g,t] * (1 - maintenance[g,t] * maintenance_pu[g]).
    Symbols: m = maintenance status (0/1), mu = maintenance_pu (per unit).
    Without a maintenance schedule the plain ``p_max_pu`` is returned, so
    adequacy, the outage Monte Carlo, ELCC and the convergence sampler all see
    planned outages exactly as the solve placed them.
    """
    pmax = network.get_switchable_as_dense("Generator", "p_max_pu")
    maint = getattr(network.generators_t, "maintenance", None)
    gens = network.generators
    if maint is None or getattr(maint, "empty", True) or "maintenance_pu" not in gens.columns:
        return pmax
    cols = [c for c in maint.columns if c in pmax.columns]
    if not cols:
        return pmax
    out = pmax.copy()
    mu = gens["maintenance_pu"].reindex(cols).fillna(1.0)
    out[cols] = pmax[cols] * (1.0 - maint[cols].reindex(pmax.index).fillna(0.0) * mu)
    return out


def generate_renewable_ensemble(
    base: np.ndarray,
    *,
    n_members: int = 200,
    variability: float = 0.15,
    autocorr: float = 0.8,
    seed: int = 11,
    cap: float = 1.0,
) -> np.ndarray:
    """Synthetic capacity-factor ensemble around a base series.

    Args:
        base: Base CF series (T,), values in [0, cap].
        n_members: Number of ensemble members M.
        variability: Perturbation scale (0 = identical to base; 0.3 ≈ ±30%).
        autocorr: AR(1) lag-1 correlation of the multiplicative noise (0–1).
        seed: RNG seed (reproducible).
        cap: Upper clip for CF (1.0 by default).

    Returns:
        Array (M, T), each row a member; clipped to [0, cap]. Multiplicative, so
        base-zero snapshots (e.g. solar at night) stay exactly zero.
    """
    base = np.asarray(base, dtype=float)
    T = base.shape[0]
    if T == 0 or n_members <= 0:
        return np.zeros((max(0, n_members), T))
    rng = np.random.default_rng(seed)
    rho = float(min(0.999, max(0.0, autocorr)))
    innov_std = np.sqrt(max(1e-12, 1.0 - rho * rho))  # unit stationary variance
    out = np.empty((n_members, T))
    for m in range(n_members):
        e = np.empty(T)
        e[0] = rng.standard_normal()
        for t in range(1, T):
            e[t] = rho * e[t - 1] + innov_std * rng.standard_normal()
        out[m] = np.clip(base * (1.0 + variability * e), 0.0, cap)
    return out


def ensemble_stats(base: np.ndarray, ensemble: np.ndarray) -> dict[str, Any]:
    """Similarity + spread of an ensemble versus its base series."""
    base = np.asarray(base, dtype=float)
    M = ensemble.shape[0]
    if M == 0:
        return {"members": 0, "meanR2": 0.0, "meanRmse": 0.0, "band": []}
    # Mean R² and RMSE of members vs the base.
    r2s, rmses = [], []
    denom = float(((base - base.mean()) ** 2).sum())
    for m in range(M):
        resid = ensemble[m] - base
        rmses.append(float(np.sqrt((resid ** 2).mean())))
        if denom > 1e-12:
            r2s.append(1.0 - float((resid ** 2).sum()) / denom)
    p10 = np.percentile(ensemble, 10, axis=0)
    p50 = np.percentile(ensemble, 50, axis=0)
    p90 = np.percentile(ensemble, 90, axis=0)
    return {
        "members": M,
        "meanR2": round(float(np.mean(r2s)), 4) if r2s else 1.0,
        "meanRmse": round(float(np.mean(rmses)), 5),
        "band": [
            {"p10": round(float(p10[t]), 4), "p50": round(float(p50[t]), 4),
             "p90": round(float(p90[t]), 4)}
            for t in range(base.shape[0])
        ],
    }


@dataclass(frozen=True)
class StorageFleet:
    """Storage units as the SOC-limited dispatch kernel sees them.

    One row per physical store: a ``StorageUnit``, or a ``Store`` together with
    the ``Link`` chargers / dischargers wired to its bus.

    Attributes:
        names: unit names (a ``Store`` keeps its own name).
        carriers: unit carriers.
        discharge_mw: (S, T) maximum grid-side discharge power (MW) per snapshot.
        charge_mw: (S,) maximum grid-side charge power (MW).
        energy_mwh: (S,) usable stored-energy capacity (MWh).
        eta_charge: (S,) charge efficiency (grid energy -> stored energy), 0-1.
        eta_discharge: (S,) discharge efficiency (stored -> grid energy), 0-1.
        standing_loss: (S,) fraction of stored energy lost per hour.
        initial_soc_mwh: (S,) stored energy at the start of the window (MWh).
    """

    names: tuple[str, ...]
    carriers: tuple[str, ...]
    discharge_mw: np.ndarray
    charge_mw: np.ndarray
    energy_mwh: np.ndarray
    eta_charge: np.ndarray
    eta_discharge: np.ndarray
    standing_loss: np.ndarray
    initial_soc_mwh: np.ndarray

    def __len__(self) -> int:
        return len(self.names)

    def without_carriers(self, carriers: set[str]) -> StorageFleet:
        """The fleet minus every unit whose carrier is in ``carriers``."""
        keep = np.array([c not in carriers for c in self.carriers], dtype=bool)
        return StorageFleet(
            tuple(n for n, k in zip(self.names, keep) if k),
            tuple(c for c, k in zip(self.carriers, keep) if k),
            self.discharge_mw[keep], self.charge_mw[keep], self.energy_mwh[keep],
            self.eta_charge[keep], self.eta_discharge[keep], self.standing_loss[keep],
            self.initial_soc_mwh[keep],
        )

    def nameplate_by_carrier(self) -> dict[str, float]:
        """Peak grid-side discharge power (MW) summed per carrier."""
        out: dict[str, float] = {}
        for i, carrier in enumerate(self.carriers):
            out[carrier] = out.get(carrier, 0.0) + float(self.discharge_mw[i].max(initial=0.0))
        return out


def electricity_buses(network: pypsa.Network) -> set[str]:
    """Buses of the electricity system, derived from the data.

    The carrier that carries the most load defines "electricity" (a lumped
    model with no bus carriers set takes every bus), less Store-only plumbing
    buses (a battery bus reached through Links). Nothing here names a carrier.
    """
    buses = network.buses
    if len(buses) == 0:
        return set()
    carrier = buses["carrier"].astype(str) if "carrier" in buses.columns else pd.Series("", index=buses.index)
    # A bus that only hosts a Store (a battery / tank bus reached through Links)
    # is storage plumbing, not part of the electricity system, even when bus
    # carriers are all left blank.
    direct = {
        str(b)
        for frame in (network.loads, network.generators, network.storage_units)
        for b in frame["bus"]
    }
    plumbing = {str(b) for b in network.stores["bus"]} - direct
    if len(network.loads) == 0:
        return {str(b) for b in buses.index} - plumbing
    load_peak = network.get_switchable_as_dense("Load", "p_set").abs().max(axis=0)
    by_bus = load_peak.groupby(network.loads["bus"].reindex(load_peak.index)).sum()
    by_carrier = by_bus.groupby(carrier.reindex(by_bus.index)).sum()
    if by_carrier.empty:
        return {str(b) for b in buses.index} - plumbing
    main = str(by_carrier.idxmax())
    return {str(b) for b in buses.index[carrier == main]} - plumbing


@dataclass(frozen=True)
class StoreLinks:
    """Links wiring one ``Store`` to the electricity system.

    ``discharge`` / ``charge`` are link names; ``share`` is this store's energy
    share of all stores on the same bus (links serving several stores are split
    pro rata, so nothing is counted twice).
    """

    discharge: tuple[str, ...]
    charge: tuple[str, ...]
    share: float


def store_link_pairs(network: pypsa.Network) -> dict[str, StoreLinks]:
    """Chargers / dischargers of every ``Store``, found by topology.

    A discharger is a link leaving the store's bus into an electricity bus; a
    charger one arriving from an electricity bus. Stores without a discharger
    are absent (they cannot serve load).
    """
    stores = network.stores
    links = network.links
    if len(stores) == 0 or len(links) == 0:
        return {}
    elec = electricity_buses(network)
    e_col = "e_nom_opt" if "e_nom_opt" in stores.columns else "e_nom"
    energy = stores[e_col].astype(float)
    on_bus = energy.groupby(stores["bus"].astype(str)).sum()
    bus0 = links["bus0"].astype(str)
    bus1 = links["bus1"].astype(str)
    out: dict[str, StoreLinks] = {}
    for s in stores.index:
        bus = str(stores.at[s, "bus"])
        dis = tuple(str(x) for x in links.index[(bus0 == bus) & bus1.isin(elec)])
        if not dis:
            continue
        chg = tuple(str(x) for x in links.index[(bus1 == bus) & bus0.isin(elec)])
        total = float(on_bus.get(bus, 0.0))
        share = float(energy[s]) / total if total > 0 else 1.0
        out[str(s)] = StoreLinks(dis, chg, share)
    return out


def _link_power(
    network: pypsa.Network, links: pd.DataFrame, share: float, *, discharge: bool, T: int,
) -> tuple[np.ndarray, float]:
    """Grid-side (T,) power limit of parallel links and their power-weighted efficiency."""
    if len(links) == 0:
        return np.zeros(T), 1.0
    col = "p_nom_opt" if "p_nom_opt" in links.columns else "p_nom"
    pmax = network.get_switchable_as_dense("Link", "p_max_pu")
    total = np.zeros(T)
    eta_num = 0.0
    eta_den = 0.0
    for name in links.index:
        eff = float(links.at[name, "efficiency"]) if "efficiency" in links.columns else 1.0
        cap = float(links.at[name, col]) * share
        profile = pmax[name].to_numpy() if name in pmax.columns else np.ones(T)
        # Link p_nom is on bus0. A discharger delivers eff*p at bus1 (grid);
        # a charger draws p at bus0 (grid).
        power = cap * profile * (eff if discharge else 1.0)
        total = total + power
        eta_num += float(power.max(initial=0.0)) * eff
        eta_den += float(power.max(initial=0.0))
    return total, (eta_num / eta_den if eta_den > 0 else 1.0)


def extract_storage_fleet(network: pypsa.Network) -> StorageFleet:
    """Collect every storage resource of a solved network into a ``StorageFleet``.

    * ``StorageUnit``: power ``p_nom_opt`` (fallback ``p_nom``), energy
      ``max_hours`` (PyPSA default 1 h) times power, own efficiencies.
    * ``Store`` + ``Link``: energy ``e_nom_opt`` (fallback ``e_nom``) times
      ``e_max_pu``; the discharger is a link leaving the store's bus into an
      electricity bus, the charger a link arriving from one. Links shared by
      several stores on one bus are split pro rata to store energy. A store
      with no discharger cannot serve load and is left out.

    The initial state of charge is the solved end-of-window value for a cyclic
    unit (the cycle makes it the start value), else the unit's own initial value.
    """
    T = len(network.snapshots)
    names: list[str] = []
    carriers: list[str] = []
    discharge: list[np.ndarray] = []
    charge: list[float] = []
    energy: list[float] = []
    eta_c: list[float] = []
    eta_d: list[float] = []
    loss: list[float] = []
    soc0: list[float] = []

    su = network.storage_units
    if len(su):
        cap_col = "p_nom_opt" if "p_nom_opt" in su.columns else "p_nom"
        pmax = network.get_switchable_as_dense("StorageUnit", "p_max_pu")
        soc_t = getattr(network.storage_units_t, "state_of_charge", pd.DataFrame())
        for s in su.index:
            cap = float(su.at[s, cap_col])
            if cap <= 0:
                continue
            hours = float(su.at[s, "max_hours"]) if "max_hours" in su.columns else 1.0
            pmin = float(su.at[s, "p_min_pu"]) if "p_min_pu" in su.columns else -1.0
            cyclic = bool(su.at[s, "cyclic_state_of_charge"]) if "cyclic_state_of_charge" in su.columns else False
            start = float(su.at[s, "state_of_charge_initial"]) if "state_of_charge_initial" in su.columns else 0.0
            if cyclic and s in soc_t.columns and len(soc_t):
                start = float(soc_t[s].iloc[-1])
            names.append(str(s))
            carriers.append(str(su.at[s, "carrier"]) if "carrier" in su.columns else "")
            discharge.append(cap * (pmax[s].to_numpy() if s in pmax.columns else np.ones(T)))
            charge.append(cap * max(0.0, -pmin))
            energy.append(cap * hours)
            eta_c.append(float(su.at[s, "efficiency_store"]) if "efficiency_store" in su.columns else 1.0)
            eta_d.append(float(su.at[s, "efficiency_dispatch"]) if "efficiency_dispatch" in su.columns else 1.0)
            loss.append(float(su.at[s, "standing_loss"]) if "standing_loss" in su.columns else 0.0)
            soc0.append(max(0.0, start))

    stores = network.stores
    if len(stores) and len(network.links):
        e_col = "e_nom_opt" if "e_nom_opt" in stores.columns else "e_nom"
        links = network.links
        e_t = getattr(network.stores_t, "e", pd.DataFrame())
        for s, pair in store_link_pairs(network).items():
            e_nom = float(stores.at[s, e_col])
            if e_nom <= 0:
                continue
            dis = links.loc[list(pair.discharge)]
            chg = links.loc[list(pair.charge)]
            share = pair.share
            dis_mw, eta_dis = _link_power(network, dis, share, discharge=True, T=T)
            if not dis_mw.any():
                continue
            chg_mw, eta_chg = _link_power(network, chg, share, discharge=False, T=T)
            e_max = float(stores.at[s, "e_max_pu"]) if "e_max_pu" in stores.columns else 1.0
            cyclic = bool(stores.at[s, "e_cyclic"]) if "e_cyclic" in stores.columns else False
            start = float(stores.at[s, "e_initial"]) if "e_initial" in stores.columns else 0.0
            if cyclic and s in e_t.columns and len(e_t):
                start = float(e_t[s].iloc[-1])
            names.append(str(s))
            carriers.append(str(stores.at[s, "carrier"]) if "carrier" in stores.columns else "")
            discharge.append(dis_mw)
            charge.append(float(chg_mw.max(initial=0.0)))
            energy.append(e_nom * e_max)
            eta_c.append(eta_chg)
            eta_d.append(eta_dis)
            loss.append(float(stores.at[s, "standing_loss"]) if "standing_loss" in stores.columns else 0.0)
            soc0.append(max(0.0, start))

    return StorageFleet(
        tuple(names), tuple(carriers),
        np.array(discharge, dtype=float).reshape(len(names), T),
        np.array(charge, dtype=float), np.array(energy, dtype=float),
        np.array(eta_c, dtype=float), np.array(eta_d, dtype=float),
        np.array(loss, dtype=float), np.array(soc0, dtype=float),
    )


def storage_dispatch(
    generation: np.ndarray,
    load: np.ndarray,
    weights: np.ndarray,
    fleet: StorageFleet,
) -> np.ndarray:
    """SOC-limited greedy shortfall shaving — the one storage model of every reliability study.

    Adequacy, the outage Monte Carlo, ELCC and the convergence sampler all call
    this, so a storage unit is worth the same MW in each.

    Args:
        generation: (M, T) or (T,) non-storage available generation (MW).
        load: (T,) demand (MW).
        weights: (T,) hours each snapshot represents.
        fleet: storage resources (see ``extract_storage_fleet``).

    Returns:
        (M, T) grid-side storage discharge (MW); add it to ``generation``.

    Algorithm:
        Per member, snapshots in order, units in order. With deficit
        $D_t=\\max(L_t-G_t,0)$ and surplus $S_t=\\max(G_t-L_t,0)$ (MW), stored
        energy $e$ (MWh), power limits $\\bar p^{d}_t,\\bar p^{c}$ (MW), capacity
        $E$ (MWh), efficiencies $\\eta_c,\\eta_d$, standing loss $\\lambda$ (1/h),
        snapshot weight $w_t$ (h):
            $$ e \\leftarrow e\\,(1-\\lambda)^{w_t} $$
            $$ d=\\min\\big(D_t,\\ \\bar p^{d}_t,\\ e\\,\\eta_d/w_t\\big),\\quad e \\leftarrow e-d\\,w_t/\\eta_d $$
            $$ c=\\min\\big(S_t,\\ \\bar p^{c},\\ (E-e)/(\\eta_c w_t)\\big),\\quad e \\leftarrow e+c\\,\\eta_c w_t $$
        Storage recharges only from surplus generation, never from a deficit
        snapshot, and discharges only to cover a deficit. The rule is myopic
        (no look-ahead to a later, deeper peak), so it is a conservative
        reliability value for a duration-limited unit.
        ASCII: e *= (1-loss)^w; d = min(deficit, pmax_d, e*eta_d/w); e -= d*w/eta_d;
        c = min(surplus, pmax_c, (E-e)/(eta_c*w)); e += c*eta_c*w.
    """
    gen = np.atleast_2d(np.asarray(generation, dtype=float))
    M, T = gen.shape
    out = np.zeros((M, T))
    S = len(fleet)
    if S == 0 or T == 0:
        return out
    net = np.asarray(load, dtype=float)[None, :] - gen
    deficit = np.clip(net, 0.0, None)
    surplus = np.clip(-net, 0.0, None)
    has_deficit = deficit.any(axis=0)
    has_surplus = surplus.any(axis=0)
    soc = np.tile(fleet.initial_soc_mwh[:, None], (1, M))  # (S, M)
    eta_c = np.clip(fleet.eta_charge, 1e-9, None)
    eta_d = np.clip(fleet.eta_discharge, 1e-9, None)
    lossy = bool(np.any(fleet.standing_loss > 0))
    for t in range(T):
        w = float(weights[t])
        if w <= 0:
            continue
        if lossy:
            soc *= ((1.0 - fleet.standing_loss) ** w)[:, None]
        if not has_deficit[t] and not has_surplus[t]:
            continue
        need = deficit[:, t].copy()
        spare = surplus[:, t].copy()
        for s in range(S):
            if has_deficit[t]:
                d = np.minimum(need, np.minimum(fleet.discharge_mw[s, t], soc[s] * eta_d[s] / w))
                soc[s] -= d * w / eta_d[s]
                need -= d
                out[:, t] += d
            if has_surplus[t] and fleet.charge_mw[s] > 0:
                room = np.clip(fleet.energy_mwh[s] - soc[s], 0.0, None)
                c = np.minimum(spare, np.minimum(fleet.charge_mw[s], room / (eta_c[s] * w)))
                soc[s] += c * eta_c[s] * w
                spare -= c
    return out


def compute_adequacy(
    available: np.ndarray,   # (M, T) available generation (MW) per member/snapshot
    load: np.ndarray,        # (T,) demand (MW)
    weights: np.ndarray,     # (T,) snapshot weights (h)
    *,
    modeled_hours: float | None = None,
) -> dict[str, Any]:
    """Loss-of-load metrics from an availability ensemble.

    LOLP per snapshot is the share of members short; LOLE weights it by hours
    and annualises (scales the modeled window up to 8760 h). EENS is the
    expected unserved energy across members.
    """
    available = np.asarray(available, dtype=float)
    load = np.asarray(load, dtype=float)
    weights = np.asarray(weights, dtype=float)
    M, T = available.shape if available.ndim == 2 else (0, load.shape[0])
    if M == 0 or T == 0:
        return {"lole": 0.0, "eens": 0.0, "eue": 0.0, "loloProbability": [],
                "worstPeriods": [], "annualScale": 1.0}

    shortfall = np.clip(load[None, :] - available, 0.0, None)  # (M, T)
    short_flag = shortfall > 1e-9
    lolp = short_flag.mean(axis=0)  # (T,) probability of loss of load per snapshot

    window_hours = float((weights).sum()) if weights.size else float(T)
    total = float(modeled_hours) if modeled_hours else window_hours
    annual_scale = 8760.0 / total if total > 0 else 1.0

    lole_window = float((lolp * weights).sum())          # hours in the modeled window
    lole = lole_window * annual_scale                    # scaled to a year
    eens_window = float((shortfall * weights[None, :]).sum(axis=1).mean())  # MWh, mean over members
    eens = eens_window * annual_scale

    order = np.argsort(-lolp)
    worst = [
        {"snapshot": int(i), "lolp": round(float(lolp[i]), 4),
         "meanShortfallMW": round(float(shortfall[:, i].mean()), 2)}
        for i in order[:10] if lolp[i] > 0
    ]
    return {
        "lole": round(lole, 3),
        "eens": round(eens, 1),
        "eue": round(eens, 1),  # EUE ≡ EENS here (expected unserved energy)
        "loloProbability": [round(float(v), 5) for v in lolp],
        "worstPeriods": worst,
        "annualScale": round(annual_scale, 4),
    }


def build_adequacy(
    network: pypsa.Network,
    *,
    members: int = 200,
    variability: float = 0.15,
    seed: int = 11,
) -> dict[str, Any] | None:
    """Resource-adequacy study over a stochastic renewable ensemble.

    Reads the solved network's renewable generators (those with a time-varying
    ``p_max_pu`` — the availability signal) as base capacity factors, builds an
    ensemble per renewable (A1), forms available generation = firm capacity +
    Σ renewable capacity · CF + storage discharge, and returns LOLE / LOLP / EENS versus load (A2).

    Returns ``None`` when there is no load or no renewable (time-varying)
    generator — there's no stochastic availability to study.
    """
    if not getattr(network, "is_solved", False):
        return None
    snapshots = network.snapshots
    T = len(snapshots)
    if T == 0 or len(network.loads) == 0:
        return None

    load = network.get_switchable_as_dense("Load", "p_set").sum(axis=1).to_numpy()
    weights = network.snapshot_weightings["objective"].to_numpy()

    gens = network.generators
    pmax = maintenance_available_pmax(network)
    tv_cols = set(getattr(network.generators_t, "p_max_pu", pd.DataFrame()).columns)

    firm = np.zeros(T)
    renewables: list[tuple[str, float, np.ndarray]] = []  # (name, capacity, base CF)
    for g in gens.index:
        name = str(g)
        if is_shedding(name):
            # Injected VOLL backstop, not a physical resource: counting it as a
            # stochastic renewable (it carries a time-varying p_max_pu column)
            # adds ~peak-load fake capacity per bus and zeroes LOLE/EENS.
            continue
        cap = float(gens.at[g, "p_nom_opt"]) if "p_nom_opt" in gens.columns else float(gens.at[g, "p_nom"])
        if cap <= 0:
            continue
        if name in tv_cols:  # time-varying availability → stochastic renewable
            renewables.append((name, cap, pmax[g].to_numpy()))
        else:  # firm/dispatchable: available at its (static) rated availability
            firm += cap * pmax[g].to_numpy()

    if not renewables:
        return None

    # Available generation per member = firm + Σ renewable capacity · ensemble CF.
    available = np.tile(firm, (members, 1))
    total_renewable_cap = 0.0
    for i, (name, cap, base) in enumerate(renewables):
        ens = generate_renewable_ensemble(
            base, n_members=members, variability=variability, seed=seed + i,
        )
        available += cap * ens
        total_renewable_cap += cap

    # Storage serves shortfall on the shared SOC-limited kernel (power, energy,
    # efficiency and recharge-from-surplus limits), not as unlimited firm MW.
    fleet = extract_storage_fleet(network)
    if len(fleet):
        available = available + storage_dispatch(available, load, weights, fleet)

    metrics = compute_adequacy(available, load, weights, modeled_hours=float(weights.sum()))

    # A representative available-vs-load band for the card (p10/p50/p90 of total
    # available each snapshot), plus timestamps.
    p10 = np.percentile(available, 10, axis=0)
    p50 = np.percentile(available, 50, axis=0)
    p90 = np.percentile(available, 90, axis=0)
    # Pathway runs index snapshots by (period, timestep): same label convention
    # as the dispatch series.
    labels = [_snapshot_label(s)[1] for s in snapshots]
    band = [
        {"timestamp": labels[t], "load": round(float(load[t]), 2),
         "p10": round(float(p10[t]), 2), "p50": round(float(p50[t]), 2),
         "p90": round(float(p90[t]), 2)}
        for t in range(T)
    ]

    _log.info("adequacy: LOLE=%.2f h/yr, EENS=%.0f MWh, %d renewables, %d members",
              metrics["lole"], metrics["eens"], len(renewables), members)
    return {
        "members": members,
        "variability": variability,
        "firmCapacityMW": round(float(firm.max()), 2),
        "renewableCapacityMW": round(total_renewable_cap, 2),
        "storageCapacityMW": round(float(sum(fleet.nameplate_by_carrier().values())), 2),
        "storageEnergyMWh": round(float(fleet.energy_mwh.sum()), 2),
        "peakLoadMW": round(float(load.max()), 2),
        "lole": metrics["lole"],
        "eens": metrics["eens"],
        "worstPeriods": metrics["worstPeriods"],
        "band": band,
    }
