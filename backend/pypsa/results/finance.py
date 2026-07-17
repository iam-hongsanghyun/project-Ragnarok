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
from typing import Any

import pypsa

from .market import HOURS_PER_YEAR

_log = logging.getLogger("pypsa.solver")

# Sane fallbacks when the model leaves a value unset.
_DEFAULT_LIFETIME = 25.0
_MAX_HORIZON = 60  # cap the cashflow horizon (years) to bound the arithmetic


def _crf(rate: float, life: float) -> float:
    """Capital recovery factor — annuity payment per unit of present capital."""
    if life <= 0:
        return 1.0
    if abs(rate) < 1e-9:
        return 1.0 / life
    return rate / (1.0 - (1.0 + rate) ** (-life))


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
    if not gen_owner and not sto_owner:
        return None

    # company -> list of (overnight_capex, annual_margin, lifetime)
    assets: dict[str, list[tuple[float, float, float]]] = {}

    def _add(company: str, annualised_capex: float, margin: float, life: float) -> None:
        c = annualised_capex / _crf(r, life) if annualised_capex > 0 else 0.0
        assets.setdefault(company, []).append((c, margin, life))

    # Dense marginal cost: a time-varying series (workbook `generators-
    # marginal_cost`, or a varying carbon-price schedule writing its adder to
    # generators_t only) is invisible in the static column.
    mc_dense = network.get_switchable_as_dense("Generator", "marginal_cost")

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
        ext = bool(network.generators.at[g, "p_nom_extendable"]) if "p_nom_extendable" in network.generators.columns else False
        a = float(network.generators.at[g, "capital_cost"]) * float(network.generators.at[g, "p_nom_opt"]) if ext else 0.0
        _add(company, a, (revenue - opex) * annualize, _lifetime(network.generators, g))

    for s in network.storage_units.index:
        company = sto_owner.get(str(s))
        if not company:
            continue
        bus = str(network.storage_units.at[s, "bus"])
        if bus not in mp.columns:
            continue
        pd_ = network.storage_units_t.p_dispatch[s].to_numpy() if s in network.storage_units_t.p_dispatch.columns else None
        pc = network.storage_units_t.p_store[s].to_numpy() if s in network.storage_units_t.p_store.columns else None
        if pd_ is None or pc is None:
            continue
        pi = mp[bus].to_numpy()
        revenue = float(((pd_ - pc) * pi * weights).sum())
        mc = float(network.storage_units.at[s, "marginal_cost"]) if "marginal_cost" in network.storage_units.columns else 0.0
        opex = float((mc * pd_ * weights).sum())
        ext = bool(network.storage_units.at[s, "p_nom_extendable"]) if "p_nom_extendable" in network.storage_units.columns else False
        a = float(network.storage_units.at[s, "capital_cost"]) * float(network.storage_units.at[s, "p_nom_opt"]) if ext else 0.0
        _add(company, a, (revenue - opex) * annualize, _lifetime(network.storage_units, s))

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
