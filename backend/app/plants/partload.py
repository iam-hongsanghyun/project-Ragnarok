"""Part-load efficiency of a committable thermal unit: the two-point heat-rate curve and how it is written into PyPSA terms.

Off by default (``minLoadEfficiency`` blank): a plant without it keeps the single rated efficiency and every number it had.

Algorithm (two-point heat-rate curve):
    Net electric output :math:`P` (MW_el), rated :math:`\\bar P`, minimum load :math:`m` (per unit of :math:`\\bar P`), efficiency
    :math:`\\eta_f` at full load and :math:`\\eta_m` at minimum load (LHV, net). Fuel at the two points (MW_th)
    $$ F_f = \\bar P/\\eta_f,\\qquad F_m = m\\bar P/\\eta_m $$
    The straight line through them, valid for :math:`m\\bar P \\le P \\le \\bar P`, is
    $$ F(P) = F_0 + b\\,P,\\qquad b = \\frac{F_f - F_m}{(1-m)\\bar P},\\qquad F_0 = F_f - b\\bar P $$
    :math:`b` (MW_th per MW_el) is the incremental heat rate and :math:`F_0` the no-load fuel while the unit is committed
    (:math:`F_0 \\ge 0 \\iff \\eta_m \\le \\eta_f`, :math:`b > 0 \\iff \\eta_m > m\\,\\eta_f`).
    ASCII: F_f = P/eta_f; F_m = m*P/eta_m; b = (F_f - F_m)/((1-m)*P); F0 = F_f - b*P; F(P) = F0 + b*P.

How PyPSA gets it (two routes, chosen by what the component is):

* **Link** (CCGT / OCGT, the fuel-network turbine): PyPSA 1.4's own piecewise ``efficiency`` curve, sheet ``links-efficiency-pw``. The
  curve is the output as a function of the fuel drawn at ``bus0`` (``p0``, per unit of ``p_nom`` = :math:`F_f`) with the breakpoints
  :math:`(0,0)`, :math:`(x_m,\\eta_m)`, :math:`(1,\\eta_f)`, where :math:`x_m = F_m/F_f = m\\,\\eta_f/\\eta_m`, and the Link's
  ``p_min_pu`` is :math:`x_m`. PyPSA ties the curve to the unit's ``status`` (off = no fuel, no output). The no-load fuel is then a
  real flow on the gas bus: the supplier's cost, the gas flow, the CO2 and the blend-share rows of a fuel network all see it. A
  ``stand_by_cost`` + ``marginal_cost`` pair would price the same line in money but leave the no-load fuel out of every flow.
* **Generator** (the simple co-firing plant, which carries the fuel price inside ``marginal_cost``): PyPSA's native
  ``stand_by_cost`` (currency per hour committed) plus an incremental ``marginal_cost``, with :math:`c` the fuel price of the blend
  (EUR/MWh_th) and :math:`v` the variable O&M (EUR/MWh_el)
  $$ \\text{stand\\_by\\_cost} = c\\,F_0,\\qquad \\text{marginal\\_cost} = c\\,b + v $$
  ASCII: stand_by_cost = c*F0 [EUR/h]; marginal_cost = c*b + v [EUR/MWh_el]. PyPSA's Generator piecewise efficiency only enters
  primary-energy constraints, not the cost, so it cannot carry this. The CO2 factor of the carrier is per MWh_th at the full-load
  efficiency, so the no-load fuel of a Generator is priced but not counted in its CO2 (the preview says so).
"""

from __future__ import annotations

from typing import Any

from .registry import PlantError

#: Digits kept on a derived value (more than the 6-8 of the legacy rows so that the curve is reproduced to ~1e-12).
DIGITS = 12


def heat_rate_curve(p_el_mw: float, min_load: float, eta_full: float, eta_min: float) -> dict[str, float]:
    """The derived heat-rate line of a unit (see the module docstring for the equations).

    Args:
        p_el_mw: rated net electric output :math:`\\bar P` (MW_el), fixed size.
        min_load: minimum stable load :math:`m` as a fraction of ``p_el_mw`` (0 < m < 1).
        eta_full: net efficiency at full load (per unit, LHV).
        eta_min: net efficiency at minimum load (per unit, LHV), ``m eta_f < eta_m <= eta_f``.

    Returns:
        ``fuelFullMw`` (:math:`F_f`), ``fuelMinMw`` (:math:`F_m`), ``incrementalHeatRate`` (:math:`b`, MW_th/MW_el), ``noLoadFuelMw``
        (:math:`F_0`), ``minLoadPu`` (:math:`x_m`, fuel at minimum load per unit of the full-load fuel), ``etaFull``, ``etaMin``,
        ``incrementalEfficiency`` (:math:`1/b`).

    Raises:
        PlantError: a value outside its range, or a curve with no valid line (``eta_min`` above ``eta_full`` or at / below ``m eta_f``).
    """
    if p_el_mw <= 0:
        raise PlantError("Part-load efficiency needs a fixed size pNom > 0.")
    if not 0.0 < min_load < 1.0:
        raise PlantError(f"Part-load efficiency needs a minimum load strictly between 0 and 1, got {min_load!r}.")
    if not 0.0 < eta_full <= 1.0:
        raise PlantError(f"The full-load efficiency must be in (0, 1], got {eta_full!r}.")
    if not 0.0 < eta_min <= 1.0:
        raise PlantError(f"minLoadEfficiency must be in (0, 1], got {eta_min!r}.")
    if eta_min > eta_full * (1.0 + 1e-12):
        raise PlantError(f"minLoadEfficiency {eta_min:g} is above the full-load efficiency {eta_full:g}: a unit is not more efficient at "
                         "minimum load (that would make the no-load fuel negative).")
    if eta_min <= min_load * eta_full:
        raise PlantError(f"minLoadEfficiency {eta_min:g} is at or below min_load x efficiency = {min_load * eta_full:g}: fuel at minimum "
                         "load would be at least the full-load fuel, so the heat-rate line has no positive slope.")
    f_full = p_el_mw / eta_full
    f_min = min_load * p_el_mw / eta_min
    b = (f_full - f_min) / ((1.0 - min_load) * p_el_mw)
    f0 = f_full - b * p_el_mw
    return {"pElMw": p_el_mw, "minLoad": min_load, "etaFull": eta_full, "etaMin": eta_min, "fuelFullMw": f_full, "fuelMinMw": f_min,
            "incrementalHeatRate": b, "incrementalEfficiency": 1.0 / b, "noLoadFuelMw": max(f0, 0.0), "minLoadPu": f_min / f_full}


def fuel_at(curve: dict[str, float], p_el_mw: float) -> float:
    """Fuel (MW_th) the heat-rate line gives at output ``p_el_mw``: :math:`F_0 + b P` (valid between minimum and rated output)."""
    return curve["noLoadFuelMw"] + curve["incrementalHeatRate"] * p_el_mw


def link_curve_rows(name: str, curve: dict[str, float]) -> list[dict[str, Any]]:
    """Rows of the sheet ``links-efficiency-pw`` for one Link: breakpoints ``p_pu`` = fuel / ``p_nom`` and the efficiency there.

    The first breakpoint is the origin (PyPSA ignores a non-zero efficiency at ``p_pu = 0`` and warns, so it is written as 0).
    """
    pts = ((0.0, 0.0), (curve["minLoadPu"], curve["etaMin"]), (1.0, curve["etaFull"]))
    return [{"name": name, "breakpoint": i, "p_pu": round(x, DIGITS), "efficiency": round(y, DIGITS)} for i, (x, y) in enumerate(pts)]


def generator_terms(curve: dict[str, float], fuel_price: float, vom: float) -> dict[str, float]:
    """``stand_by_cost`` (currency/h) and incremental ``marginal_cost`` (currency/MWh_el) of a Generator for the fuel price ``fuel_price``."""
    return {"stand_by_cost": round(fuel_price * curve["noLoadFuelMw"], DIGITS),
            "marginal_cost": round(fuel_price * curve["incrementalHeatRate"] + vom, DIGITS)}


def describe(curve: dict[str, float], route: str, written: dict[str, float] | None = None) -> dict[str, Any]:
    """The derived values as shown in the plant preview and stored in the registry (``route``: ``piecewise-link`` / ``stand-by-generator``).

    ``written`` = the component-row values of the Generator route (``stand_by_cost``, ``marginal_cost``), shown beside the curve.
    """
    return {**{k: round(v, 9) for k, v in curve.items()}, "route": route, **({"written": dict(written)} if written else {}),
            "formula": "F(P) = F0 + b*P;  b = (F_full - F_min)/((1-m)*P_rated);  F0 = F_full - b*P_rated"}
