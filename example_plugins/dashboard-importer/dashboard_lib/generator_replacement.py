"""Replace selected new power plants with solar / wind renewables.

Designed to run **after** demand redistribution and **before** region
aggregation and ``apply_standard_p_max_pu`` (so the new units still carry a
``province`` and automatically inherit that province's solar/wind capacity
profile when :func:`~dashboard_lib.p_max_pu.apply_standard_p_max_pu` runs).

User input
----------
A GUI table ``dashboard.generator_replacements`` with one column, ``generator``
(the plant to replace), plus scalar settings:

* Eligibility — two independent filters:
  - **Filter 1 (which plants exist):** the network reaching this step is already
    filtered to the target year by the loader
    (``build_year ≤ target_year < close_year``).
  - **Filter 2 (which of those are replaceable):** ``replace_build_year`` — only
    plants with ``build_year ≥ replace_build_year`` are replaced; everything
    built earlier stays as-is.  ``0``/blank → no extra restriction.
* ``replace_follow`` — when True, split each plant's capacity between solar and
  wind by the **ratio of solar:wind capacity added in that plant's build year**
  (across the network).  The fixed share boxes are ignored in this mode.
* ``replace_solar_pct`` / ``replace_wind_pct`` — fixed solar / wind shares (%),
  used only when not following.  They are direct percentages of the original
  plant capacity, not normalized ratios.

For each selected plant the plant is removed and its **own capacity**
(``p_nom``) is split into a solar unit and/or a wind unit at the **same bus and
province**.  New units are named ``<plant>_solar_<year>`` /
``<plant>_wind_<year>`` and carry the replaced plant's ``build_year`` and
``province`` (the province drives the renewable profile).

New-unit attributes
-------------------
* ``carrier`` = ``"solar"`` / ``"wind"``; ``bus`` / ``province`` copied from the
  plant; ``p_nom`` = its split share of the plant's capacity; ``efficiency`` =
  1.0; ``p_nom_extendable`` = ``False``; ``build_year`` = the plant's.
* ``marginal_cost`` = the mean marginal cost of all existing same-carrier units
  (system-wide), computed before any removals.

Algorithm:
    For a plant with capacity ``C`` (MW) built in year ``y``:

    $$ (C_{solar}, C_{wind}) = \\begin{cases}
        C \\left(\\dfrac{A^{solar}_y}{A^{solar}_y + A^{wind}_y},
                 \\dfrac{A^{wind}_y}{A^{solar}_y + A^{wind}_y}\\right)
            & \\text{follow, additions}>0\\\\
        C \\left(\\dfrac{A^{solar}_k}{A^{solar}_k + A^{wind}_k},
                 \\dfrac{A^{wind}_k}{A^{solar}_k + A^{wind}_k}\\right)
            & \\text{follow, additions}=0,\\; k=\\max\\{t\\le y: A^{solar}_t+A^{wind}_t>0\\}\\\\
        C (0.5, 0.5)
            & \\text{follow, no nonzero prior year}\\\\
        C \\left(\\dfrac{p_{solar}}{100}, \\dfrac{p_{wind}}{100}\\right)
            & \\text{fixed}
       \\end{cases} $$

        follow:   f_solar = solar_additions(y) / (solar+wind additions(y))
        fixed:    C_solar = C * solar_pct/100; C_wind = C * wind_pct/100

    where ``A^c_y`` is the total p_nom of existing carrier-``c`` units with
    ``build_year == y``.  Each new unit's capacity-factor profile is its
    province's ``(province, carrier)`` profile (assigned downstream by
    ``apply_standard_p_max_pu``; copied here from an existing same-province unit
    when profiles are already present).

Symbols (units):
    C        replaced plant capacity (its p_nom)      [MW]
    A^c_y    capacity of carrier c added in year y     [MW]
    p_*      fixed replacement share                    [%]
    mc_*     marginal cost                             [currency/MWh]
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
import pypsa

if TYPE_CHECKING:
    from dashboard_lib.settings import Dashboard

# logging (not print) so the lines reach Ragnarok's Log tab via log_capture —
# plugin print() goes only to the server terminal and is invisible in the UI.
logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = ("generator",)
_RENEWABLES = ("solar", "wind")


def replace_generators(network: pypsa.Network, dashboard: "Dashboard") -> None:
    """Replace selected new plants with solar/wind, modifying *network* in place.

    Args:
        network:   PyPSA Network to modify in place.  Expected after demand
            redistribution and before region aggregation / p_max_pu.
        dashboard: Parsed :class:`~dashboard_lib.settings.Dashboard`.

    Raises:
        ValueError: On any invalid row — unknown plant (not active in the target
            year), a plant selected more than once, a missing ``generator``
            column, or a plant with no capacity to distribute.
    """
    settings = dashboard.settings
    if not getattr(settings, "replace_generators", False):
        return

    base_year = int(settings.base_year)
    follow = bool(getattr(settings, "replace_follow", False))
    # Filter 2 (replacement only): a plant is replaceable iff its build_year is
    # ≥ this replacement base year. The network is already filtered to the target
    # year (Filter 1); this further restricts which of those plants get replaced —
    # everything built earlier stays as-is. 0/blank → no extra restriction.
    threshold = int(getattr(settings, "replace_build_year", 0) or 0)

    # Mean marginal cost per renewable carrier, from the EXISTING units, taken
    # once up front (before any removals change the population).
    carrier_mc = {c: _mean_marginal_cost(network, c) for c in _RENEWABLES}

    def _by(name: str) -> int | None:
        v = pd.to_numeric(network.generators.at[name, "build_year"], errors="coerce")
        return int(v) if pd.notna(v) else None

    def _eligible(by: int | None) -> bool:
        """Filter 2: build_year ≥ replacement base year (no-op when threshold ≤ 0)."""
        if threshold <= 0:
            return True
        return by is not None and by >= threshold

    def _capacity(name: str) -> float:
        v = pd.to_numeric(network.generators.at[name, "p_nom"], errors="coerce")
        return float(v) if pd.notna(v) else 0.0

    # ── Collect targets (ordered): explicit table rows first, then bulk-by-carrier.
    # Table picks are validated strictly (raise on a bad pick); bulk matches are
    # filtered silently. Capacity splits are always computed from the current
    # scalar settings; stale table solar_mw/wind_mw cells are ignored.
    targets: list[str] = []
    seen: set[str] = set()

    rules = dashboard.generator_replacements
    if rules is not None and not rules.empty:
        df = rules.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]
        if "generator" not in df.columns:
            raise ValueError(
                f"Generator replacement table needs a 'generator' column; "
                f"found {list(df.columns)}"
            )
        for _, row in df.iterrows():
            name = str(row["generator"]).strip()
            if not name:
                continue
            if name in seen:
                raise ValueError(f"Generator replacement: plant {name!r} is selected more than once")
            if name not in network.generators.index:
                raise ValueError(
                    f"Generator replacement: plant {name!r} is not in the network "
                    f"(not active in the target year)"
                )
            if _capacity(name) <= 0:
                raise ValueError(f"Generator replacement: plant {name!r} has no capacity (p_nom) to distribute")
            if not _eligible(_by(name)):
                raise ValueError(
                    f"Generator replacement: plant {name!r} (build_year={_by(name)}) is "
                    f"before the replacement base year ({threshold})"
                )
            seen.add(name)
            targets.append(name)

    # Filter 3 (optional): an attribute filter — keep only generators whose
    # <filter_column> equals <filter_value> (any generators column / value).
    filter_col = str(getattr(settings, "replace_filter_column", "") or "").strip()
    filter_val = str(getattr(settings, "replace_filter_value", "") or "").strip()
    use_attr_filter = bool(filter_col and filter_val and filter_col in network.generators.columns)

    def _attr_ok(name: str) -> bool:
        if not use_attr_filter:
            return True
        return str(network.generators.at[name, filter_col]).strip() == filter_val

    # Bulk: every plant of the selected carriers with positive capacity that
    # passes Filter 2 (build_year ≥ replacement base year) and Filter 3 (the
    # attribute filter), not already picked in the table. Network is already
    # target-year-filtered (Filter 1).
    # Carrier matching is case/whitespace-insensitive — a model spelling its
    # carriers "Coal"/"Solar" must still match the lowercase GUI checkboxes.
    carriers_sel = {str(c).strip().lower() for c in getattr(settings, "replace_carriers", ()) if str(c).strip()}
    bulk_added = 0
    if getattr(settings, "replace_all_carriers", False) and carriers_sel and "carrier" in network.generators.columns:
        for name in list(network.generators.index):
            if name in seen:
                continue
            if str(network.generators.at[name, "carrier"]).strip().lower() not in carriers_sel:
                continue
            if _capacity(name) <= 0 or not _eligible(_by(name)) or not _attr_ok(name):
                continue
            seen.add(name)
            bulk_added += 1
            targets.append(name)

    if not targets:
        logger.info(
            "Generator replacement: enabled but nothing selected (no table rows, no bulk carriers) — skipping"
        )
        return

    # ── Apply each replacement ────────────────────────────────────────────────
    added = 0
    annual_additions = _year_additions_by_year(network)
    for name in targets:
        # A pre-existing plant (no build_year) is "always built" → inherit base_year
        # so the renewable unit it becomes is likewise active from the start.
        by = _by(name)
        if by is None:
            by = base_year
        capacity = _capacity(name)
        bus = str(network.generators.at[name, "bus"])
        province = (
            str(network.generators.at[name, "province"])
            if "province" in network.generators.columns and pd.notna(network.generators.at[name, "province"])
            else ""
        )
        solar_cap, wind_cap = _split_capacity(
            settings=settings,
            annual_additions=annual_additions,
            year=by,
            capacity=capacity,
            follow=follow,
        )
        # Per-plant trace in the Log tab — makes the applied ratio verifiable
        # against the reference table (and a 50/50 fallback visible as such).
        logger.info(
            "Generator replacement: %s (build %s): %.1f MW -> solar %.1f + wind %.1f",
            name, by, capacity, solar_cap, wind_cap,
        )

        network.remove("Generator", name)
        for carrier, cap in (("solar", solar_cap), ("wind", wind_cap)):
            if cap <= 0:
                continue
            _add_renewable(
                network,
                base_name=name,
                carrier=carrier,
                bus=bus,
                province=province,
                p_nom=cap,
                marginal_cost=carrier_mc[carrier] or 0.0,
                build_year=by,
            )
            added += 1

    mode = "follow yearly additions" if follow else (
        f"fixed {settings.replace_solar_pct:g}% solar / {settings.replace_wind_pct:g}% wind"
    )
    bulk_note = (
        f", bulk {sorted(carriers_sel)} (+{bulk_added})"
        if (getattr(settings, "replace_all_carriers", False) and carriers_sel)
        else ""
    )
    logger.info(
        "Generator replacement: replaced %d plant(s) with %d renewable unit(s) [%s%s] "
        "(solar mc=%s, wind mc=%s)",
        len(targets), added, mode, bulk_note, carrier_mc["solar"], carrier_mc["wind"],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_capacity(
    settings: object,
    annual_additions: dict[int, tuple[float, float]],
    year: int,
    capacity: float,
    follow: bool,
) -> tuple[float, float]:
    """Return ``(solar_mw, wind_mw)`` for one replaced plant."""
    if follow:
        solar_add, wind_add = _latest_nonzero_additions(annual_additions, year)
        total_add = solar_add + wind_add
        if total_add > 0:
            return capacity * solar_add / total_add, capacity * wind_add / total_add
        # Last-resort fallback: the model has NO solar/wind unit with a build_year
        # in or before this plant's year, so there is no ratio to follow. Say so
        # loudly — a silent 50/50 looks like the setting was ignored.
        logger.warning(
            "Generator replacement: follow mode found no solar/wind additions in "
            "any year <= %s — falling back to 50/50 for this plant. Check the "
            "model's solar/wind build_year values, or use fixed Solar %%/Wind %%.",
            year,
        )
        return capacity * 0.5, capacity * 0.5

    solar_pct = _percentage_setting(settings, "replace_solar_pct", 50.0)
    wind_pct = _percentage_setting(settings, "replace_wind_pct", 50.0)
    return capacity * solar_pct / 100.0, capacity * wind_pct / 100.0


def _latest_nonzero_additions(
    annual_additions: dict[int, tuple[float, float]],
    year: int,
) -> tuple[float, float]:
    """Return additions for *year*, or the latest earlier nonzero additions."""
    solar_add, wind_add = annual_additions.get(year, (0.0, 0.0))
    if solar_add + wind_add > 0:
        return solar_add, wind_add

    for candidate_year in sorted((y for y in annual_additions if y <= year), reverse=True):
        solar_add, wind_add = annual_additions[candidate_year]
        if solar_add + wind_add > 0:
            return solar_add, wind_add
    return 0.0, 0.0


def _percentage_setting(settings: object, field: str, default: float) -> float:
    """Parse a non-negative percentage setting."""
    try:
        value = float(getattr(settings, field, default) or 0.0)
    except (TypeError, ValueError):
        value = default
    return max(value, 0.0)


def _year_additions_by_year(network: pypsa.Network) -> dict[int, tuple[float, float]]:
    """Return ``{build_year: (solar_mw, wind_mw)}`` from the pre-replacement fleet."""
    gens = network.generators
    if gens.empty or "build_year" not in gens.columns or "carrier" not in gens.columns:
        return {}
    by = pd.to_numeric(gens["build_year"], errors="coerce")
    carrier = gens["carrier"].astype(str).str.strip().str.lower()
    p_nom = (
        pd.to_numeric(gens["p_nom"], errors="coerce").fillna(0.0)
        if "p_nom" in gens.columns
        else pd.Series(0.0, index=gens.index)
    )

    rows = pd.DataFrame({"year": by, "carrier": carrier, "p_nom": p_nom})
    rows = rows[rows["year"].notna() & rows["carrier"].isin(_RENEWABLES)]
    if rows.empty:
        return {}
    grouped = rows.groupby(["year", "carrier"], dropna=True)["p_nom"].sum()
    additions: dict[int, tuple[float, float]] = {}
    for year_value in rows["year"].dropna().unique():
        year = int(year_value)
        additions[year] = (
            float(grouped.get((year_value, "solar"), 0.0)),
            float(grouped.get((year_value, "wind"), 0.0)),
        )
    return additions


def _mean_marginal_cost(network: pypsa.Network, carrier: str) -> float | None:
    """Mean ``marginal_cost`` of existing generators of *carrier* (or ``None``)."""
    gens = network.generators
    if gens.empty or "carrier" not in gens.columns:
        return None
    mask = gens["carrier"].astype(str).str.strip().str.lower() == carrier
    if "marginal_cost" not in gens.columns or not mask.any():
        return None
    values = pd.to_numeric(gens.loc[mask, "marginal_cost"], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _add_renewable(
    network: pypsa.Network,
    base_name: str,
    carrier: str,
    bus: str,
    province: str,
    p_nom: float,
    marginal_cost: float,
    build_year: int,
) -> str:
    """Add one renewable generator (``<base>_<carrier>_<year>``); return its name."""
    new_name = _unique_name(network, f"{base_name}_{carrier}_{build_year}")
    network.add(
        "Generator",
        new_name,
        bus=bus,
        carrier=carrier,
        p_nom=float(p_nom),
        marginal_cost=float(marginal_cost),
        efficiency=1.0,
        p_nom_extendable=False,
        build_year=int(build_year),
    )
    if "province" in network.generators.columns and province:
        network.generators.at[new_name, "province"] = province
    _copy_profile_if_available(network, new_name, province, carrier)
    return new_name


def _unique_name(network: pypsa.Network, candidate: str) -> str:
    """Return *candidate* or a suffixed variant not already a generator name."""
    if candidate not in network.generators.index:
        return candidate
    i = 2
    while f"{candidate}_{i}" in network.generators.index:
        i += 1
    return f"{candidate}_{i}"


def _copy_profile_if_available(
    network: pypsa.Network,
    new_name: str,
    province: str,
    carrier: str,
) -> None:
    """Copy a same-(province, carrier) p_max_pu profile to *new_name* if present.

    A no-op when ``generators_t.p_max_pu`` is still empty — that is the normal
    case at this pipeline stage, and ``apply_standard_p_max_pu`` will assign the
    province profile downstream.  When profiles are already populated (a model
    that shipped its own p_max_pu), copy the closest existing match so the new
    unit is not left at the constant default of 1.0.
    """
    ts = getattr(network.generators_t, "p_max_pu", None)
    if ts is None or ts.empty:
        return

    gens = network.generators
    same_carrier = gens.index[gens["carrier"].astype(str).str.strip() == carrier]
    in_ts = [g for g in same_carrier if g in ts.columns and g != new_name]
    if not in_ts:
        return

    donor = None
    if province and "province" in gens.columns:
        for g in in_ts:
            if str(gens.at[g, "province"]).strip() == province:
                donor = g
                break
    if donor is None:
        donor = in_ts[0]
    network.generators_t.p_max_pu[new_name] = ts[donor].to_numpy()
