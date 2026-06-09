"""Scale generator marginal cost by a per-carrier multiplier.

A GUI table ``dashboard.marginal_cost_rules`` maps a carrier to a percentage
**of the original** marginal cost.  ``100`` leaves it unchanged, ``30`` sets it
to 30 % (``×0.30``), ``130`` raises it 30 % (``×1.30``).  Carriers with no row
(or a blank percentage) are left untouched.

Designed to run on the per-generator fleet (after generator replacement, before
or after region/carrier aggregation — a uniform per-carrier factor commutes with
the capacity-weighted merge, so the result is the same either way).

Algorithm:
    For every generator ``g`` of carrier ``c`` with a multiplier ``p_c`` (%):

        $$ c'_g = \\frac{p_c}{100}\\, c_g $$

        marginal_cost_g  ←  (multiplier_pct[c] / 100) × marginal_cost_g

Symbols (units):
    c_g            generator marginal cost            [currency/MWh]
    p_c            multiplier for carrier c           [%]
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pypsa

if TYPE_CHECKING:
    from dashboard_lib.settings import Dashboard

_REQUIRED_COLUMNS = ("carrier", "multiplier_pct")


def apply_marginal_cost_multipliers(network: pypsa.Network, dashboard: "Dashboard") -> None:
    """Scale generator ``marginal_cost`` per carrier, modifying *network* in place.

    Reads ``dashboard.settings.marginal_cost_multiplier`` (gate) and
    ``dashboard.marginal_cost_rules`` (carrier → percent of original).

    Args:
        network:   PyPSA Network to modify in place.
        dashboard: Parsed :class:`~dashboard_lib.settings.Dashboard`.

    Raises:
        ValueError: When the table is missing its required columns, or a
            percentage is negative / not a number.
    """
    settings = dashboard.settings
    if not getattr(settings, "marginal_cost_multiplier", False):
        return

    rules = dashboard.marginal_cost_rules
    if rules is None or rules.empty:
        print("  Marginal cost: enabled but no carrier multipliers provided — skipping")
        return

    df = rules.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Marginal-cost table missing columns {missing}; found {list(df.columns)}"
        )

    # carrier → factor (percent of original / 100). Last non-blank row wins.
    factors: dict[str, float] = {}
    for _, row in df.iterrows():
        carrier = str(row["carrier"]).strip()
        if not carrier or carrier.lower() == "nan":
            continue
        raw = row["multiplier_pct"]
        if raw is None or (isinstance(raw, float) and raw != raw) or str(raw).strip() == "":
            continue
        pct = pd.to_numeric(raw, errors="coerce")
        if pd.isna(pct):
            raise ValueError(f"Marginal cost: multiplier_pct {raw!r} for {carrier!r} is not a number")
        if float(pct) < 0:
            raise ValueError(f"Marginal cost: multiplier_pct for {carrier!r} must be ≥ 0, got {pct}")
        factors[carrier] = float(pct) / 100.0

    if not factors:
        print("  Marginal cost: no usable carrier multipliers — skipping")
        return

    gens = network.generators
    if gens.empty or "carrier" not in gens.columns or "marginal_cost" not in gens.columns:
        print("  Marginal cost: no generators with a marginal_cost — skipping")
        return

    carrier_col = gens["carrier"].astype(str).str.strip()
    for carrier, factor in factors.items():
        mask = carrier_col == carrier
        count = int(mask.sum())
        if not count:
            print(f"  Marginal cost: no generators of carrier {carrier!r} — skipped")
            continue
        current = pd.to_numeric(gens.loc[mask, "marginal_cost"], errors="coerce").fillna(0.0)
        network.generators.loc[mask, "marginal_cost"] = current * factor
        print(f"  Marginal cost: {carrier} ×{factor:.2f} ({factor * 100:g}% of original) — {count} generator(s)")
