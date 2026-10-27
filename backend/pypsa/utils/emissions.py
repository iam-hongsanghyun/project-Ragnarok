"""Efficiency-aware CO₂ emission factors (M3 — fuel/thermal basis).

PyPSA stores ``carrier.co2_emissions`` on the **primary-energy (fuel)** basis —
tCO₂ per MWh of fuel *burned*. A thermal generator with ``efficiency`` η turns
one MWh of fuel into η MWh of electricity, so the fuel burned to produce one
MWh of electrical output is ``1 / η`` MWh, and the emissions per MWh *electrical*
are ``co2_emissions / η``.

This matches PyPSA's own native ``GlobalConstraint`` (``primary_energy``)
accounting, which divides dispatch by ``efficiency`` before applying the carrier
factor. The app's custom paths — the carbon-price adder, the constraint DSL
``emissions[...]`` term, the ``co2_cap`` intensity constraint, and the emissions
reports — historically used the *electrical-output* basis (efficiency ignored),
which is only correct while every efficiency is 1.0. Routing them all through
:func:`per_generator_emission_factor` puts them on the same thermal basis.

Algorithm:
    $$ \\text{ef}^{\\text{elec}}_g = \\frac{\\text{co2\\_emissions}(\\text{carrier}_g)}{\\eta_g} $$
    ASCII: ef_elec[g] = co2_emissions[carrier(g)] / efficiency[g]

Symbols:
    ef_elec[g]            tCO₂ per MWh_electrical for generator g
    co2_emissions[carrier] tCO₂ per MWh_thermal (fuel) for the carrier
    efficiency[g] (η_g)   MWh_electrical out / MWh_thermal in (dimensionless)
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd
import pypsa

# Guard so a zero/negative efficiency can't produce inf/negative emissions; a
# real thermal unit is well above this and clean carriers have ef = 0 anyway.
_MIN_EFFICIENCY = 1e-6


def generator_efficiencies(network: pypsa.Network) -> pd.Series:
    """Per-generator efficiency η (MWh_e out / MWh_thermal in).

    Defaults to 1.0 when the column is absent or a value is missing, and floors
    at ``_MIN_EFFICIENCY`` so downstream division is always finite. Indexed by
    generator name.
    """
    gens = network.generators
    if "efficiency" not in gens.columns:
        return pd.Series(1.0, index=gens.index, dtype=float)
    eta = pd.to_numeric(gens["efficiency"], errors="coerce").fillna(1.0)
    return eta.where(eta > _MIN_EFFICIENCY, 1.0).astype(float)


def per_generator_emission_factor(
    network: pypsa.Network,
    ef_by_carrier: Mapping[str, float],
) -> pd.Series:
    """tCO₂ per MWh **electrical** for each generator = carrier factor ÷ efficiency.

    Args:
        network: the (built) PyPSA network.
        ef_by_carrier: carrier name → tCO₂/MWh_thermal (the primary-energy factor,
            e.g. ``network.carriers["co2_emissions"]`` or the app's
            ``emissions_factors`` map).

    Returns:
        Series indexed by generator name; 0.0 for non-emitting carriers.
    """
    gens = network.generators
    carrier_ef = gens["carrier"].map(
        lambda c: float(ef_by_carrier.get(str(c), 0.0))
    ).astype(float)
    eta = generator_efficiencies(network)
    return (carrier_ef / eta).astype(float)


# ── PyPSA primary-energy accounting (RB10) ───────────────────────────────────
@dataclass(frozen=True)
class PrimaryEnergyEmissions:
    """Emissions of one solved network on PyPSA's ``primary_energy`` basis.

    All Series are tCO₂ indexed by component name and equal the term each
    component contributes to the left-hand side of a ``primary_energy``
    ``GlobalConstraint`` (same weights, same efficiency, same sign).

    Attributes:
        generators: Σ_t w_t·y_p·p_g(t)/η_g(t)·ef_c — ``y_p`` the investment-period
            ``years`` weighting in a multi-period run (1 otherwise).
        generators_snapshot: the same without ``y_p`` (emissions over the modelled
            snapshots only), used for intensities.
        storage_units: ef_c·(soc_initial − soc_final) for non-cyclic StorageUnits.
        stores: ef_c·(e_initial − e_final) for non-cyclic Stores.
        generator_rate_tph: tCO₂ per hour per snapshot per generator (unweighted).
    """

    generators: pd.Series
    generators_snapshot: pd.Series
    storage_units: pd.Series
    stores: pd.Series
    generator_rate_tph: pd.DataFrame

    @property
    def total(self) -> float:
        """Σ of every term — equals the ``primary_energy`` constraint LHS."""
        return float(self.generators.sum() + self.storage_units.sum() + self.stores.sum())


def _carrier_emission_map(network: pypsa.Network, ef_by_carrier: Mapping[str, float] | None) -> dict[str, float]:
    """Carrier → tCO₂/MWh_thermal, non-zero entries only (PyPSA ignores ``co2_emissions == 0``)."""
    if ef_by_carrier is None:
        carriers = network.carriers
        ef_by_carrier = (
            pd.to_numeric(carriers["co2_emissions"], errors="coerce").fillna(0.0).to_dict()
            if "co2_emissions" in carriers.columns else {}
        )
    return {str(c): float(v) for c, v in ef_by_carrier.items() if v and float(v) != 0.0}


def primary_energy_emissions(
    network: pypsa.Network,
    ef_by_carrier: Mapping[str, float] | None = None,
) -> PrimaryEnergyEmissions:
    """Emissions by PyPSA's ``primary_energy`` ``GlobalConstraint`` rule.

    Mirrors ``pypsa.optimization.global_constraints.define_primary_energy_limit``
    so the reported total equals the constraint's left-hand side.

    Algorithm:
        $$E = \\sum_{g}\\sum_t w_t\\,y_{p(t)}\\,\\frac{p_g(t)}{\\eta_g(t)}\\,ef_{c(g)}
            + \\sum_{s\\,\\text{non-cyclic}} ef_{c(s)}\\,(e^{0}_s - e^{T}_s)$$
        with $w_t$ the ``generators`` snapshot weighting (h), $y_p$ the
        investment-period ``years`` weighting (1 outside multi-period runs),
        $p_g$ dispatch (MW, **signed** — not clipped), $\\eta_g$ efficiency,
        $ef_c$ the carrier ``co2_emissions`` (tCO₂/MWh_thermal) and
        $e^0, e^T$ the initial and final state of charge of StorageUnits and
        Stores (MWh; cyclic ones are excluded, as in PyPSA). In a multi-period run
        a unit with ``*_initial_per_period`` contributes
        $\\sum_p y_p\\,(e^0 - e^{last(p)})$ instead.
        ASCII: E = sum_g sum_t w*y*p/eta*ef + sum_s ef*(e_initial - e_final).

    What is deliberately **not** counted: ``Link`` and ``Process`` flows. PyPSA's
    constraint does not count them, and a fuel supply generator on the fuel bus
    already carries the carrier's emissions (``p`` × ``co2_emissions``, efficiency
    1) — counting the converting link too would double count the same fuel.
    Emissions therefore stay at the fuel-extraction generator (P29/RB10).

    Args:
        network: solved network.
        ef_by_carrier: optional carrier → tCO₂/MWh_thermal override (the app's
            ``emissions_factors``); defaults to ``network.carriers.co2_emissions``.

    Returns:
        :class:`PrimaryEnergyEmissions`.
    """
    ef = _carrier_emission_map(network, ef_by_carrier)
    snaps = network.snapshots
    # PyPSA applies the period ``years`` weights only when the solve was a
    # multi-investment-period one (``n.optimize(multi_investment_periods=True)``
    # sets ``n._multi_invest``); a network that never solved (rebuilt from stored
    # outputs) has no flag, and Ragnarok's pathway runs always set it.
    multi = (
        isinstance(snaps, pd.MultiIndex)
        and bool(getattr(network, "has_investment_periods", False))
        and bool(getattr(network, "_multi_invest", True))
    )
    w = network.snapshot_weightings["generators"].reindex(snaps).fillna(1.0)
    if multi:
        years = network.investment_period_weightings["years"]
        y = pd.Series(years.reindex(snaps.get_level_values("period")).to_numpy(), index=snaps).fillna(1.0)
    else:
        y = pd.Series(1.0, index=snaps)

    # ── generators ───────────────────────────────────────────────────────────
    gens = network.generators
    emitting = [g for g in gens.index if str(gens.at[g, "carrier"]) in ef]
    p = network.generators_t.p
    cols = [g for g in emitting if g in p.columns]
    if cols:
        eta = network.get_switchable_as_dense("Generator", "efficiency").reindex(index=snaps, columns=cols)
        eta = eta.where(eta > _MIN_EFFICIENCY, 1.0).fillna(1.0)
        rate = (p[cols].reindex(snaps) / eta) * pd.Series(
            [ef[str(gens.at[g, "carrier"])] for g in cols], index=cols
        )
        rate = rate.fillna(0.0)
    else:
        rate = pd.DataFrame(index=snaps, columns=[], dtype=float)
    gen_snapshot = rate.mul(w, axis=0).sum(axis=0).reindex(emitting).fillna(0.0)
    gen_total = rate.mul(w * y, axis=0).sum(axis=0).reindex(emitting).fillna(0.0)

    # ── storage units / stores ───────────────────────────────────────────────
    def _stock_terms(static: pd.DataFrame, series: pd.DataFrame, e0: str, cyclic: str, per_period: str) -> pd.Series:
        if static.empty:
            return pd.Series(dtype=float)
        ok = static["carrier"].astype(str).isin(ef) & ~static[cyclic].astype(bool)
        out: dict[str, float] = {}
        for name in static.index[ok]:
            if name not in series.columns:
                out[name] = 0.0
                continue
            level = series[name].reindex(snaps).ffill()
            initial = float(static.at[name, e0])
            em = ef[str(static.at[name, "carrier"])]
            flagged = bool(static.at[name, per_period]) if per_period in static.columns else False
            if multi and flagged:
                last = level.groupby(snaps.get_level_values("period")).last()
                yrs = network.investment_period_weightings["years"].reindex(last.index).fillna(1.0)
                out[name] = em * float(((initial - last) * yrs).sum())
            else:
                out[name] = em * (initial - float(level.iloc[-1]))
        return pd.Series(out, dtype=float)

    su = _stock_terms(network.storage_units, network.storage_units_t.state_of_charge,
                      "state_of_charge_initial", "cyclic_state_of_charge", "state_of_charge_initial_per_period")
    st = _stock_terms(network.stores, network.stores_t.e, "e_initial", "e_cyclic", "e_initial_per_period")
    return PrimaryEnergyEmissions(
        generators=gen_total, generators_snapshot=gen_snapshot, storage_units=su, stores=st,
        generator_rate_tph=rate,
    )
