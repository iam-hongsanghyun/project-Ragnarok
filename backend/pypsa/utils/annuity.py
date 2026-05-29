"""Annuity / capital recovery factor utilities for capacity expansion."""
from __future__ import annotations


def annuity_factor(discount_rate: float, lifetime_years: float) -> float:
    """Return the capital recovery factor (annuity factor).

    Converts a total overnight capital cost into an annualised cost.
    Formula: AF = r(1+r)^n / ((1+r)^n − 1)

    If *discount_rate* ≤ 0 the function falls back to straight-line
    amortisation over *lifetime_years*.
    """
    r = float(discount_rate)
    n = float(lifetime_years)

    if n <= 0:
        return 1.0

    if r <= 0:
        # straight-line (no time-value-of-money)
        return 1.0 / n

    rn = (1.0 + r) ** n
    return r * rn / (rn - 1.0)
