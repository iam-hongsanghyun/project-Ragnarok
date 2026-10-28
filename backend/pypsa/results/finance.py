"""Company-level financial model (F2) — project finance per owner.

Turns dispatch + capacity results into the metrics an investor actually asks
for: NPV, IRR, simple and discounted payback, and (when debt is specified)
DSCR. Builds a per-company annual cashflow from each asset's overnight capex at
year 0 and its level operating margin over its lifetime, then discounts.

The optimiser reports an *annualised* capital cost (the app convention, shared
with F0). We reconstruct the overnight capex from it via the inverse capital
recovery factor — ``C = a · (1 − (1+r)^−L) / r`` — so the year-0 outflow is
explicit and standard IRR / payback fall out of the cashflow.

Basis: dispatch and prices cover only the modelled window of
``H = Σ_t w_t`` represented hours (the build path scales snapshot weightings
to the window, not to 8760 h). Every recurring cashflow here is **annual**, so
the window operating margin is annualised by ``× 8760 / H`` before it enters
the cashflow, NPV, IRR, payback and DSCR. The overnight capex is already on a
true annual→present basis and is not rescaled.

Algorithm:
    $$M = \\left(\\text{revenue}_H - \\text{opex}_H\\right) \\cdot
      \\frac{8760}{H}, \\quad
      \\mathrm{NPV} = \\sum_{t=0}^{T} \\frac{CF_t}{(1+r)^t}, \\quad
      CF_0 = -C,\\; CF_{1..L} = M$$
    ASCII: M = (revenue_H - opex_H) * 8760/H ; NPV = sum_t CF_t / (1+r)^t ;
    CF_0 = -C ; CF_t = M.

    Symbols: r = discount rate [-], L = asset lifetime [yr], C = overnight
    capex [currency], H = modelled window [h], revenue_H / opex_H = window
    totals [currency], M = annual operating margin [currency/yr], a =
    annualised capital cost [currency/yr], IRR = rate solving NPV(IRR)=0 [-].
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pypsa
from ...app import carbon_pricing

from .adequacy import electricity_buses, store_link_pairs
from pypsa.costs import annuity as _pypsa_annuity

from .market import HOURS_PER_YEAR, process_assets
from .stat_metrics import fixed_cost_of, fixed_cost_table, overnight_capex_table

_log = logging.getLogger("pypsa.solver")

# Sane fallbacks when the model leaves a value unset.
_DEFAULT_LIFETIME = 25.0
_MAX_HORIZON = 60  # cap the cashflow horizon (years) to bound the arithmetic


def _crf(rate: float, life: float) -> float:
    """Capital recovery factor — PyPSA's own ``annuity(rate, life)`` (debt service, fallback overnight)."""
    if life <= 0:
        return 1.0
    return float(_pypsa_annuity(float(rate), float(life)))


def _npv(rate: float, cashflows: list[float]) -> float:
    """Net present value of a year-indexed cashflow list (index 0 = today)."""
    if rate <= -1.0:
        return float("inf")
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cashflows))


def _irr(cashflows: list[float]) -> float | None:
    """Internal rate of return via bisection; ``None`` if no sign change."""
    # A financeable project needs at least one outflow and one inflow.
    if not any(cf < 0 for cf in cashflows) or not any(cf > 0 for cf in cashflows):
        return None
    lo, hi = -0.9, 10.0
    f_lo, f_hi = _npv(lo, cashflows), _npv(hi, cashflows)
    # Very profitable projects (tiny capex vs an annualised margin) can carry
    # an IRR beyond the initial bracket — expand it geometrically first.
    while f_lo * f_hi > 0 and hi < 1e9:
        hi *= 10.0
        f_hi = _npv(hi, cashflows)
    if f_lo * f_hi > 0:
        return None  # no root bracketed in the search range
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        f_mid = _npv(mid, cashflows)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def _payback(cashflows: list[float], *, discount_rate: float | None = None) -> float | None:
    """First crossing year where cumulative (optionally discounted) CF ≥ 0."""
    cum = 0.0
    prev_cum = 0.0
    for t, cf in enumerate(cashflows):
        flow = cf if discount_rate is None else cf / (1.0 + discount_rate) ** t
        cum += flow
        if cum >= 0 and t > 0:
            # Linear interpolation within the crossing year for a smoother figure.
            span = cum - prev_cum
            frac = (-prev_cum / span) if span > 1e-12 else 0.0
            return round(t - 1 + max(0.0, min(1.0, frac)), 2)
        prev_cum = cum
    return None  # never pays back within the horizon


def _lifetime(df, name: str) -> float:
    if "lifetime" in df.columns:
        try:
            v = float(df.at[name, "lifetime"])
            if v > 0 and v != float("inf") and v == v:  # finite, positive, non-NaN
                return min(v, float(_MAX_HORIZON))
        except (TypeError, ValueError):
            pass
    return _DEFAULT_LIFETIME


@dataclass(frozen=True)
class StorageAsset:
    """One storage resource's window economics, on the single shared rule.

    ``revenue`` and ``op_cost`` are window totals (currency, weighted by the
    snapshot weights); ``capex_annual`` is the fixed charge PER YEAR that ``n.statistics`` reports
    (``(capex + fom) / n.nyears``, currency/yr; installed and expanded capacity alike) and
    ``overnight`` the ``n.statistics.overnight_cost`` of the asset (currency; NaN when PyPSA cannot
    resolve it). ``capex_sunk`` / ``capex_expanded`` split the horizon capex into what was already
    built and what the solve added.
    """

    name: str
    sheet: str  # model sheet the owner tag lives on: "storage_units" | "stores"
    bus: str
    carrier: str
    capacity_mw: float
    energy_mwh: float
    capex_annual: float
    lifetime: float
    revenue: float
    op_cost: float
    discharged_mwh: float
    charged_mwh: float
    overnight: float = float("nan")
    capex_sunk: float = 0.0
    capex_expanded: float = 0.0


_STATIC_FRAME = {"StorageUnit": "storage_units", "Store": "stores", "Link": "links"}


def _component_series(network: pypsa.Network, component: str, attr: str, name: str) -> np.ndarray:
    """Per-snapshot value of ``attr`` (series over static), 0 when the attribute is absent."""
    T = len(network.snapshots)
    try:
        dense = network.get_switchable_as_dense(component, attr)
        if name in dense.columns:
            return dense[name].to_numpy(dtype=float)
    except Exception:  # noqa: BLE001 — attribute not registered on this component
        pass
    frame = getattr(network, _STATIC_FRAME[component])
    value = float(frame.at[name, attr]) if attr in frame.columns else 0.0
    return np.full(T, value)


def _flow(frame: Any, name: str, T: int) -> np.ndarray:
    return frame[name].to_numpy(dtype=float) if name in frame.columns else np.zeros(T)


def storage_assets(
    network: pypsa.Network,
    price_of: Callable[[str], np.ndarray | None],
    weights: np.ndarray,
    *,
    storage_units: Iterable[str] = (),
    stores: Iterable[str] = (),
) -> list[StorageAsset]:
    """Window revenue / cost / capex of the named storage, one rule for every consumer.

    Finance, the company statement, the company breakdown and the merchant study
    all read storage through here, so they cannot drift apart.

    * ``StorageUnit``: revenue = Σ w (p_dispatch − p_store) π; cost =
      Σ w (marginal_cost·p_dispatch + marginal_cost_storage·soc + spill_cost·spill).
    * ``Store`` + ``Link``: revenue at the electricity side of the chargers and
      dischargers (a Store sitting on an electricity bus is injected directly);
      cost = Σ w (marginal_cost·p + marginal_cost_storage·e) plus the links'
      ``marginal_cost · p0``. Links serving several stores are split pro rata.
    * Capex and overnight cost are read from ``n.statistics`` (store: its own plus its links' pro-rata
      share), never recomputed from ``capital_cost``.

    Assets whose market bus has no price (``price_of`` returns ``None``) are skipped.
    """
    T = len(network.snapshots)
    out: list[StorageAsset] = []
    fixed = fixed_cost_table(network, ["StorageUnit", "Store", "Link"])
    overnight_all = overnight_capex_table(network, ["StorageUnit", "Store", "Link"])

    su = network.storage_units
    for s in storage_units:
        if s not in su.index:
            continue
        bus = str(su.at[s, "bus"])
        pi = price_of(bus)
        t = network.storage_units_t
        if pi is None or s not in t.p_dispatch.columns or s not in t.p_store.columns:
            continue
        pd_ = t.p_dispatch[s].to_numpy(dtype=float)
        pc = t.p_store[s].to_numpy(dtype=float)
        mc = _component_series(network, "StorageUnit", "marginal_cost", str(s))
        mcs = _component_series(network, "StorageUnit", "marginal_cost_storage", str(s))
        spill_cost = _component_series(network, "StorageUnit", "spill_cost", str(s))
        soc = _flow(t.state_of_charge, s, T)
        spill = _flow(t.spill, s, T)
        fc = fixed_cost_of(fixed, "StorageUnit", str(s))
        power = float(su.at[s, "p_nom_opt"]) if "p_nom_opt" in su.columns else float(su.at[s, "p_nom"])
        hours = float(su.at[s, "max_hours"]) if "max_hours" in su.columns else 1.0
        out.append(StorageAsset(
            name=str(s), sheet="storage_units", bus=bus,
            carrier=str(su.at[s, "carrier"]) if "carrier" in su.columns else "",
            capacity_mw=power, energy_mwh=power * hours,
            capex_annual=fc["annual"],
            overnight=float(overnight_all.get(("StorageUnit", str(s)), float("nan"))),
            capex_sunk=fc["capex_sunk"], capex_expanded=fc["capex_expanded"],
            lifetime=_lifetime(su, s),
            revenue=float(((pd_ - pc) * pi * weights).sum()),
            op_cost=float(((mc * pd_ + mcs * soc + spill_cost * spill) * weights).sum()),
            discharged_mwh=float((pd_ * weights).sum()),
            charged_mwh=float((pc * weights).sum()),
        ))

    st = network.stores
    wanted = [s for s in stores if s in st.index]
    if wanted:
        pairs = store_link_pairs(network)
        elec = electricity_buses(network)
        links = network.links
        for s in wanted:
            bus = str(st.at[s, "bus"])
            e_nom = float(st.at[s, "e_nom_opt"]) if "e_nom_opt" in st.columns else float(st.at[s, "e_nom"])
            e_max = float(st.at[s, "e_max_pu"]) if "e_max_pu" in st.columns else 1.0
            mc = _component_series(network, "Store", "marginal_cost", str(s))
            mcs = _component_series(network, "Store", "marginal_cost_storage", str(s))
            e_flow = _flow(network.stores_t.e, s, T)
            p_store = _flow(network.stores_t.p, s, T)
            op = float(((mc * p_store + mcs * e_flow) * weights).sum())
            fc = fixed_cost_of(fixed, "Store", str(s))
            capex = fc["annual"]
            sunk, expanded = fc["capex_sunk"], fc["capex_expanded"]
            over = float(overnight_all.get(("Store", str(s)), float("nan")))
            revenue = discharged = charged = capacity = 0.0
            market_bus = bus
            pair = pairs.get(str(s))
            if pair is not None:
                market_bus = str(links.at[pair.discharge[0], "bus1"])
                for ln in pair.discharge + pair.charge:
                    p0 = _flow(network.links_t.p0, ln, T)
                    p1 = _flow(network.links_t.p1, ln, T)
                    link_mc = _component_series(network, "Link", "marginal_cost", ln)
                    op += float((link_mc * p0 * weights).sum()) * pair.share
                    lfc = fixed_cost_of(fixed, "Link", str(ln))
                    l_size = float(links.at[ln, "p_nom_opt"]) if "p_nom_opt" in links.columns else float(links.at[ln, "p_nom"])
                    capex += lfc["annual"] * pair.share
                    sunk += lfc["capex_sunk"] * pair.share
                    expanded += lfc["capex_expanded"] * pair.share
                    l_over = float(overnight_all.get(("Link", str(ln)), float("nan")))
                    over = (0.0 if over != over else over) + (0.0 if l_over != l_over else l_over) * pair.share
                    if ln in pair.discharge:
                        pi_l = price_of(str(links.at[ln, "bus1"]))
                        if pi_l is None:
                            continue
                        injected = -p1 * pair.share
                        revenue += float((injected * pi_l * weights).sum())
                        discharged += float((np.clip(injected, 0.0, None) * weights).sum())
                        eff = float(links.at[ln, "efficiency"]) if "efficiency" in links.columns else 1.0
                        capacity += l_size * eff * pair.share
                    else:
                        pi_l = price_of(str(links.at[ln, "bus0"]))
                        if pi_l is None:
                            continue
                        drawn = p0 * pair.share
                        revenue -= float((drawn * pi_l * weights).sum())
                        charged += float((np.clip(drawn, 0.0, None) * weights).sum())
            elif bus in elec and price_of(bus) is not None:
                pi_b = price_of(bus)
                revenue = float((p_store * pi_b * weights).sum())
                discharged = float((np.clip(p_store, 0.0, None) * weights).sum())
                charged = float((np.clip(-p_store, 0.0, None) * weights).sum())
            else:
                continue
            out.append(StorageAsset(
                name=str(s), sheet="stores", bus=market_bus,
                carrier=str(st.at[s, "carrier"]) if "carrier" in st.columns else "",
                capacity_mw=capacity, energy_mwh=e_nom * e_max,
                capex_annual=capex, lifetime=_lifetime(st, s),
                revenue=revenue, op_cost=op, discharged_mwh=discharged, charged_mwh=charged,
                overnight=over, capex_sunk=sunk, capex_expanded=expanded,
            ))
    return out


def build_company_finance(
    network: pypsa.Network,
    model: dict[str, list[dict[str, Any]]],
    *,
    owner_column: str,
    discount_rate: float,
    currency: str,
    debt: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Per-company project-finance metrics from the solved network.

    Args:
        network: A solved network with marginal prices (an LP run).
        model: Raw model dict — source of the owner tags.
        owner_column: Which model column holds the owner tag.
        discount_rate: Discount rate r (fraction) for NPV / overnight capex.
        currency: Currency symbol (passthrough).
        debt: Optional ``{gearing, interestRate, tenorYears}`` for DSCR. Gearing
            0 (default) ⇒ all-equity, DSCR omitted.

    Returns:
        ``{ownerColumn, currency, discountRate, companies: [...]}`` or ``None``
        when no owner-tagged asset has both capex and revenue to finance.
        Each company's ``annualMargin`` (and hence the cashflow, NPV, IRR,
        payback and DSCR) is the modelled-window margin annualised by
        ``× 8760 / H`` (H = Σ snapshot weights, the represented hours).
    """
    if not getattr(network, "is_solved", False):
        return None
    column = (owner_column or "owner").strip() or "owner"
    mp = network.buses_t.marginal_price
    if mp is None or mp.empty:
        return None  # no price signal ⇒ no revenue ⇒ no finance
    weights = network.snapshot_weightings["objective"].to_numpy()
    # Modelled window (represented hours). Window money × 8760/H = annual.
    H = float(weights.sum())
    if H <= 0:
        return None
    annualize = HOURS_PER_YEAR / H
    r = float(discount_rate or 0.0)

    gearing = float((debt or {}).get("gearing", 0.0) or 0.0)
    interest = float((debt or {}).get("interestRate", 0.0) or 0.0)
    tenor = float((debt or {}).get("tenorYears", 0.0) or 0.0)
    use_debt = gearing > 0 and tenor > 0

    def _owner(sheet: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in model.get(sheet, []) or []:
            n = str(row.get("name", "")).strip()
            o = str(row.get(column, "")).strip()
            if n and o:
                out[n] = o
        return out

    gen_owner = _owner("generators")
    sto_owner = _owner("storage_units")
    store_owner = _owner("stores")
    process_owner = _owner("processes")
    if not gen_owner and not sto_owner and not store_owner and not process_owner:
        return None

    # company -> list of (overnight_capex, annual_margin, lifetime)
    assets: dict[str, list[tuple[float, float, float]]] = {}
    gen_fixed = fixed_cost_table(network, ["Generator", "Process"])
    overnight_gp = overnight_capex_table(network, ["Generator", "Process"])

    def _add(company: str, annual_capex: float, margin: float, life: float, overnight: float = float("nan")) -> None:
        """Overnight capex is PyPSA's ``n.statistics.overnight_cost``. Where PyPSA cannot resolve it
        (a capital_cost row with no discount_rate / lifetime) it is the per-year charge over the
        finance annuity ``annuity(r, life)`` - the only place a conversion is made, and the one that
        needs the PROJECT discount rate."""
        if overnight == overnight:
            c = overnight
        else:
            c = annual_capex / _crf(r, life) if annual_capex > 0 else 0.0
        assets.setdefault(company, []).append((c, margin, life))

    # Dense marginal cost: a time-varying series (workbook `generators-
    # marginal_cost`, or a varying carbon-price schedule writing its adder to
    # generators_t only) is invisible in the static column.
    mc_dense = carbon_pricing.effective_marginal_cost(network)

    for g in network.generators.index:
        company = gen_owner.get(str(g))
        if not company:
            continue
        bus = str(network.generators.at[g, "bus"])
        if bus not in mp.columns:
            continue
        p = network.generators_t.p[g].to_numpy() if g in network.generators_t.p.columns else None
        if p is None:
            continue
        pi = mp[bus].to_numpy()
        revenue = float((p * pi * weights).sum())
        mc = mc_dense[g].to_numpy(dtype=float)
        opex = float((mc * p * weights).sum())
        a = fixed_cost_of(gen_fixed, "Generator", str(g))["annual"]
        _add(company, a, (revenue - opex) * annualize, _lifetime(network.generators, g),
             float(overnight_gp.get(("Generator", str(g)), float("nan"))))

    # Storage (StorageUnit and Store + Link) through the one shared rule.
    def _price(bus: str) -> np.ndarray | None:
        return mp[bus].to_numpy() if bus in mp.columns else None

    for a in storage_assets(
        network, _price, weights, storage_units=list(sto_owner), stores=list(store_owner),
    ):
        company = (sto_owner if a.sheet == "storage_units" else store_owner).get(a.name)
        if company:
            _add(company, a.capex_annual, (a.revenue - a.op_cost) * annualize, a.lifetime, a.overnight)

    # Processes (P29): net port value at the nodal prices less marginal cost; capex from
    # n.statistics — the same rule as generator economics.
    if process_owner:
        for pa in process_assets(network, _price, weights, names=list(process_owner)):
            _add(
                process_owner[pa.name], pa.capex_annual,
                (pa.revenue - pa.variable_cost) * annualize,
                _lifetime(network.processes, pa.name),
                float(overnight_gp.get(("Process", pa.name), float("nan"))),
            )

    companies: list[dict[str, Any]] = []
    for company, rows in assets.items():
        capex_total = sum(c for c, _, _ in rows)
        margin_total = sum(m for _, m, _ in rows)
        horizon = int(min(_MAX_HORIZON, max((int(round(life)) for _, _, life in rows), default=0)))
        if horizon <= 0:
            continue
        cashflows = [0.0] * (horizon + 1)
        for c, m, life in rows:
            cashflows[0] -= c
            for t in range(1, int(round(life)) + 1):
                if t <= horizon:
                    cashflows[t] += m

        npv = _npv(r, cashflows)
        irr = _irr(cashflows)
        entry: dict[str, Any] = {
            "company": company,
            "overnightCapex": round(capex_total, 2),
            "annualMargin": round(margin_total, 2),
            "horizonYears": horizon,
            "npv": round(npv, 2),
            "irr": round(irr, 5) if irr is not None else None,
            "paybackYears": _payback(cashflows),
            "discountedPaybackYears": _payback(cashflows, discount_rate=r),
            "dscr": None,
        }
        if use_debt and capex_total > 0:
            debt_amount = gearing * capex_total
            service = debt_amount * _crf(interest, tenor)
            entry["dscr"] = round(margin_total / service, 3) if service > 1e-9 else None
        companies.append(entry)

    if not companies:
        return None
    companies.sort(key=lambda c: (c["npv"] if c["npv"] is not None else 0.0), reverse=True)
    _log.info("company finance: %d companies (r=%.3f, debt=%s)", len(companies), r, use_debt)
    return {
        "ownerColumn": column,
        "currency": currency,
        "discountRate": r,
        "companies": companies,
    }
