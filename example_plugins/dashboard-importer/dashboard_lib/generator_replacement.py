"""Replace selected new power plants with solar / wind renewables.

Designed to run **after** demand redistribution and **before** region
aggregation and ``apply_standard_p_max_pu`` (so the new units still carry a
``province`` and automatically inherit that province's solar/wind capacity
profile when :func:`~dashboard_lib.p_max_pu.apply_standard_p_max_pu` runs).

User input
----------
A GUI table ``dashboard.generator_replacements`` with a ``generator`` column (the
plant to replace) and optional ``solar_mw`` / ``wind_mw`` columns: when both are
present on a row the split is **frozen** — that plant is replaced with exactly
those MW (and the row skips the base-year filter), so batches added under
different settings keep their own rule. Rows without a frozen split use the
scalar settings below. Plus scalar settings:

* Eligibility — table picks vs. bulk-by-carrier:
  - **Table picks** name a plant from the target-year dropdown, so they are
    validated against the (target-year-filtered) network and must be active in it.
  - **Bulk by carrier** (``replace_all_carriers`` + ``replace_carriers``) is
    **retire-and-replace across years**: it is sourced from the RAW generators
    sheet on the dashboard, so it reaches every selected-carrier plant built by
    the target year — **including plants that already retire before it**
    (``close_year ≤ target_year``), which the target-year loader dropped. Their
    coal capacity still becomes renewables, dated at the plant's close/forced year
    (see below), so a coal unit closing in 2030 shows up as 2030-vintage solar/wind.
  - **Filter 2 (which are replaceable):** ``replace_build_year`` — only plants
    with ``build_year ≥ replace_build_year`` are replaced. ``0``/blank → no extra
    restriction.
  - **``replace_include_existing``** — when True, Filter 2 is ignored entirely:
    the whole selected fleet is replaceable (existing plants built before the base
    year included), so e.g. an entire coal fleet can be swapped for renewables.
  - **Filter 3 (optional attribute filter):** ``replace_filter_column`` /
    ``replace_filter_value`` — keep only rows whose column equals the value
    (string- or numeric-equal, so a flag column stored as ``1.0`` matches ``"1"``).
* ``replace_follow`` — when True, split each plant's capacity between solar and
  wind by the **ratio of solar:wind capacity added in a reference year** (across
  the model).  The reference year is each plant's **build year** by default, but
  its **close year** when ``replace_include_existing`` is on — when a plant
  retires, that is when its replacement renewables come online, so the split
  follows the mix added that year (applied uniformly to every replaced plant, so
  plants of different vintages share one mix).  Because a still-active plant's
  close year is after the target year, the close-year lookup uses the full-model
  additions (incl. post-target years) supplied on the dashboard.  The close-year
  reference is **capped at** ``replace_max_close_year`` (default: the target
  year): a plant closing on/after that year — or one that never closes — follows
  that year's mix instead of its own far-future close year.  The fixed share
  boxes are ignored in this mode.
* ``replace_solar_pct`` / ``replace_wind_pct`` — fixed solar / wind shares (%),
  used only when not following.  They are direct percentages of the original
  plant capacity, not normalized ratios.

For each selected plant, the plant (if present in the network) is removed and its
**own capacity** (``p_nom``) is split into a solar unit and/or a wind unit at the
**same bus and province**.  The renewables come online at the plant's
**replacement year** ``ry = min(close_year, cap)`` — forced no later than
``cap = replace_max_close_year`` (default: the target year) and never before the
plant is built, clamped to the target year. A plant with no close year retires at
``cap``. So ``cap`` is a forced-retirement deadline: a unit closing in 2040 with
``cap = 2035`` is replaced in 2035. New units are named ``<plant>_solar_<year>`` /
``<plant>_wind_<year>`` (year = ``ry``) and carry that ``build_year`` and the
plant's ``province`` (the province drives the renewable profile).

New-unit attributes
-------------------
* ``carrier`` = ``"solar"`` / ``"wind"``; ``bus`` / ``province`` copied from the
  plant; ``p_nom`` = its split share of the plant's capacity; ``efficiency`` =
  1.0; ``p_nom_extendable`` = ``False``; ``build_year`` = the replacement year ``ry``.
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


def replace_generators(
    network: pypsa.Network, dashboard: "Dashboard"
) -> dict[str, float]:
    """Replace selected new plants with solar/wind, modifying *network* in place.

    Args:
        network:   PyPSA Network to modify in place.  Expected after demand
            redistribution and before region aggregation / p_max_pu.
        dashboard: Parsed :class:`~dashboard_lib.settings.Dashboard`.

    Returns:
        ``{bus: total replaced p_nom (MW)}`` — the original capacity removed at
        each bus where a replacement happened. Used to size the optional ESS
        added at those buses (see :mod:`dashboard_lib.ess`). Empty when
        replacement is disabled or nothing matched.

    Raises:
        ValueError: On any invalid row — unknown plant (not active in the target
            year), a plant selected more than once, a missing ``generator``
            column, or a plant with no capacity to distribute.
    """
    settings = dashboard.settings
    if not getattr(settings, "replace_generators", False):
        return {}

    base_year = int(settings.base_year)
    follow = bool(getattr(settings, "replace_follow", False))
    # Filter 2 (replacement only): a plant is replaceable iff its build_year is
    # ≥ this replacement base year. The network is already filtered to the target
    # year (Filter 1); this further restricts which of those plants get replaced —
    # everything built earlier stays as-is. 0/blank → no extra restriction.
    replace_base_year = int(getattr(settings, "replace_build_year", 0) or 0)
    # "Include existing plants" overrides Filter 2: when on, the whole fleet
    # (every plant active in the target year, regardless of build_year) is
    # replaceable — so e.g. an entire coal fleet, existing units included, is
    # replaced. When off, only build_year ≥ threshold plants are touched.
    include_existing = bool(getattr(settings, "replace_include_existing", False))
    threshold = 0 if include_existing else replace_base_year
    # Follow-mode reference year: by default every replaced plant follows its own
    # BUILD year. When "Include existing plants" is on, every replaced plant
    # follows its CLOSE year instead (when it retires and the renewables come
    # online) — uniformly, so plants of different vintages get the same mix.
    follow_close_year = follow and include_existing
    # Cap for that close-year reference: a plant closing on/after this year (or
    # that never closes) follows this year's mix instead of its own (far-future)
    # close year. 0/blank → the target year.
    target_year = int(settings.target_year)
    max_close_year = (
        int(getattr(settings, "replace_max_close_year", 0) or 0) or target_year
    )

    # Mean marginal cost per renewable carrier, from the EXISTING units, taken
    # once up front (before any removals change the population).
    carrier_mc = {c: _mean_marginal_cost(network, c) for c in _RENEWABLES}

    def _by(name: str) -> int | None:
        v = pd.to_numeric(network.generators.at[name, "build_year"], errors="coerce")
        return int(v) if pd.notna(v) else None

    def _close_year(name: str) -> int | None:
        if "close_year" not in network.generators.columns:
            return None
        v = pd.to_numeric(network.generators.at[name, "close_year"], errors="coerce")
        return int(v) if pd.notna(v) else None

    def _eligible(by: int | None) -> bool:
        """Filter 2: build_year ≥ replacement base year (no-op when threshold ≤ 0)."""
        if threshold <= 0:
            return True
        return by is not None and by >= threshold

    def _capacity(name: str) -> float:
        v = pd.to_numeric(network.generators.at[name, "p_nom"], errors="coerce")
        return float(v) if pd.notna(v) else 0.0

    # Forced-retirement cap: every replaced plant's renewables come online at
    # ``min(close_year, cap)``; a plant with no close_year retires at ``cap``. So
    # a unit closing after the cap is forced to close at the cap (close 2040 +
    # cap 2035 → 2035), and one that never closes retires at the cap too. cap =
    # ``replace_max_close_year`` when set, else the target year.
    cap = max_close_year

    def _repl_year(by: int | None, close: int | None) -> int:
        """Year the renewable replacement comes online.

        The plant's close year, forced no later than the cap; a plant with no
        close year retires at the cap; never before it was built; and clamped to
        the target year so the new unit is active in the (single-year) model.
        """
        ry = close if close is not None else cap
        ry = min(ry, cap)
        if by is not None:
            ry = max(ry, by)
        return min(ry, target_year)

    def _canon_bus(v: object) -> str:
        """Bus id as a string, collapsing float ids (53.0 → "53") so a raw-sheet
        integer bus matches the network's string bus index."""
        try:
            f = float(v)  # type: ignore[arg-type]
            if f.is_integer():
                return str(int(f))
        except (TypeError, ValueError):
            pass
        return str(v).strip()

    def _attr_match(cell: object, val: str) -> bool:
        """Filter-3 value match: string-equal, or numeric-equal so a flag column
        stored as ``1.0`` still matches a typed ``"1"`` (the common case where a
        boolean/flag column reads back as a float)."""
        if str(cell).strip() == val:
            return True
        try:
            return float(cell) == float(val)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    # ── Collect target RECORDS (ordered): explicit table rows first, then
    # bulk-by-carrier. Each record carries everything the apply step needs —
    # {name, capacity, bus, province, by, ry, in_net, frozen} — because a bulk
    # target may be a plant that already RETIRED before the target year (so it is
    # NOT in the target-year network). Table picks are validated strictly (raise
    # on a bad pick); bulk matches are filtered silently. A row carrying a FROZEN
    # solar_mw/wind_mw split (captured by "Fill table from carriers" at add-time)
    # is replaced with exactly those MW and bypasses the base-year check.
    records: list[dict] = []
    seen: set[str] = set()

    # Raw-fleet index by name, so a table pick that already RETIRED before the
    # target year (not in the network) is still resolvable — "Fill table from
    # carriers" can freeze such plants, and the build must replace them too.
    raw = getattr(dashboard, "raw_generators", None)
    raw_index: dict[str, int] = {}
    if raw is not None and not raw.empty and "name" in raw.columns:
        for i, nm in raw["name"].astype(str).str.strip().items():
            raw_index.setdefault(nm, i)

    def _raw_row(name: str) -> dict | None:
        i = raw_index.get(name)
        if i is None:
            return None

        def g(c: str) -> object:
            return raw.at[i, c] if c in raw.columns else None

        p = pd.to_numeric(g("p_nom"), errors="coerce")
        b = pd.to_numeric(g("build_year"), errors="coerce")
        c = pd.to_numeric(g("close_year"), errors="coerce")
        bus_v, prov_v = g("bus"), g("province")
        return {
            "p_nom": float(p) if pd.notna(p) else 0.0,
            "by": int(b) if pd.notna(b) else None,
            "close": int(c) if pd.notna(c) else None,
            "bus": _canon_bus(bus_v) if pd.notna(bus_v) else "",
            "province": str(prov_v).strip() if pd.notna(prov_v) else "",
        }

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
                raise ValueError(
                    f"Generator replacement: plant {name!r} is selected more than once"
                )
            in_net = name in network.generators.index
            if in_net:
                cap_mw = _capacity(name)
                by = _by(name)
                close = _close_year(name)
                bus = _canon_bus(network.generators.at[name, "bus"])
                province = (
                    str(network.generators.at[name, "province"])
                    if "province" in network.generators.columns
                    and pd.notna(network.generators.at[name, "province"])
                    else ""
                )
            else:
                # Retired before the target year — resolve from the raw fleet
                # (retire-and-replace), so a frozen table row for it still builds.
                rr = _raw_row(name)
                if rr is None:
                    raise ValueError(
                        f"Generator replacement: plant {name!r} is not in the network "
                        f"or the raw model (unknown plant)"
                    )
                cap_mw, by, close = rr["p_nom"], rr["by"], rr["close"]
                bus, province = rr["bus"], rr["province"]
            if cap_mw <= 0:
                raise ValueError(
                    f"Generator replacement: plant {name!r} has no capacity (p_nom) to distribute"
                )
            fs = _frozen_split_from_row(row)
            # A frozen row carries its own decision, so it skips the base-year
            # filter; only live rows are held to the replacement base year.
            if fs is None and not _eligible(by):
                raise ValueError(
                    f"Generator replacement: plant {name!r} (build_year={by}) is "
                    f"before the replacement base year ({threshold})"
                )
            records.append(
                {
                    "name": name,
                    "capacity": cap_mw,
                    "bus": bus,
                    "province": province,
                    "by": by,
                    "ry": _repl_year(by, close),
                    "in_net": in_net,
                    "frozen": fs,
                }
            )
            seen.add(name)

    # Filter 3 (optional): an attribute filter — keep only rows whose
    # <filter_column> equals <filter_value> (any generators column / value).
    filter_col = str(getattr(settings, "replace_filter_column", "") or "").strip()
    filter_val = str(getattr(settings, "replace_filter_value", "") or "").strip()

    # Bulk: every plant of the selected carriers, built by the target year, with
    # positive capacity, passing Filter 2 (build_year ≥ replacement base year)
    # and Filter 3, not already picked in the table. Sourced from the RAW fleet
    # (retire-and-replace) so plants that RETIRED before the target year are
    # included — the target-year network dropped them, but their coal capacity
    # must still become renewables (dated at the plant's close/forced year).
    # Carrier matching is case/whitespace-insensitive.
    carriers_sel = {
        str(c).strip().lower()
        for c in getattr(settings, "replace_carriers", ())
        if str(c).strip()
    }
    bulk_on = bool(getattr(settings, "replace_all_carriers", False)) and bool(
        carriers_sel
    )
    bulk_added = 0
    retired_added = 0

    if (
        bulk_on
        and raw is not None
        and not raw.empty
        and {"name", "carrier"} <= set(raw.columns)
    ):
        rdf = raw

        def _rcol(c: str) -> pd.Series:
            return (
                rdf[c]
                if c in rdf.columns
                else pd.Series([None] * len(rdf), index=rdf.index)
            )

        r_name = _rcol("name").astype(str).str.strip()
        r_carr = _rcol("carrier").astype(str).str.strip().str.lower()
        r_pnom = pd.to_numeric(_rcol("p_nom"), errors="coerce")
        r_by = pd.to_numeric(_rcol("build_year"), errors="coerce")
        r_cl = pd.to_numeric(_rcol("close_year"), errors="coerce")
        r_bus = _rcol("bus")
        r_prov = _rcol("province")
        r_filt = (
            _rcol(filter_col) if (filter_col and filter_col in rdf.columns) else None
        )
        for i in rdf.index:
            nm = r_name[i]
            if not nm or nm.lower() == "nan" or nm in seen:
                continue
            if r_carr[i] not in carriers_sel:
                continue
            p = float(r_pnom[i]) if pd.notna(r_pnom[i]) else 0.0
            if p <= 0:
                continue
            by = int(r_by[i]) if pd.notna(r_by[i]) else None
            if by is not None and by > target_year:
                continue  # not yet built within this horizon
            if not _eligible(by):
                continue
            if (
                r_filt is not None
                and filter_val
                and not _attr_match(r_filt[i], filter_val)
            ):
                continue
            close = int(r_cl[i]) if pd.notna(r_cl[i]) else None
            in_net = nm in network.generators.index
            records.append(
                {
                    "name": nm,
                    "capacity": p,
                    "bus": _canon_bus(r_bus[i]) if pd.notna(r_bus[i]) else "",
                    "province": str(r_prov[i]).strip() if pd.notna(r_prov[i]) else "",
                    "by": by,
                    "ry": _repl_year(by, close),
                    "in_net": in_net,
                    "frozen": None,
                }
            )
            seen.add(nm)
            bulk_added += 1
            if not in_net:
                retired_added += 1
    elif bulk_on and "carrier" in network.generators.columns:
        # Legacy fallback (no raw fleet stashed): target-year network only.
        use_attr = bool(
            filter_col and filter_val and filter_col in network.generators.columns
        )
        for name in list(network.generators.index):
            if name in seen:
                continue
            if (
                str(network.generators.at[name, "carrier"]).strip().lower()
                not in carriers_sel
            ):
                continue
            by = _by(name)
            if _capacity(name) <= 0 or not _eligible(by):
                continue
            if use_attr and not _attr_match(
                network.generators.at[name, filter_col], filter_val
            ):
                continue
            province = (
                str(network.generators.at[name, "province"])
                if "province" in network.generators.columns
                and pd.notna(network.generators.at[name, "province"])
                else ""
            )
            records.append(
                {
                    "name": name,
                    "capacity": _capacity(name),
                    "bus": _canon_bus(network.generators.at[name, "bus"]),
                    "province": province,
                    "by": by,
                    "ry": _repl_year(by, _close_year(name)),
                    "in_net": True,
                    "frozen": None,
                }
            )
            seen.add(name)
            bulk_added += 1

    if not records:
        logger.info(
            "Generator replacement: enabled but nothing matched (no table rows, no bulk carriers) — skipping"
        )
        return {}

    # ── Apply each replacement ────────────────────────────────────────────────
    added = 0
    skipped_no_bus = 0
    replaced_by_bus: dict[str, float] = {}
    # Additions for the solar:wind split. Following each plant's BUILD year uses
    # the target-year network's table; following the CLOSE/forced (replacement)
    # year needs additions across ALL build years, which the pipeline supplies as
    # ``renewable_additions_by_year`` (fall back to the network table when absent).
    annual_additions = _year_additions_by_year(network)
    full_additions = (
        getattr(dashboard, "renewable_additions_by_year", None) or annual_additions
    )
    # Map canonical bus id → the actual network bus name, so a raw-sheet plant's
    # renewables attach to the right bus (and retired plants whose bus is gone are
    # skipped rather than silently dropped).
    bus_actual = {_canon_bus(b): b for b in network.buses.index}
    for rec in records:
        name = rec["name"]
        capacity = rec["capacity"]
        ry = rec["ry"]
        bus = bus_actual.get(rec["bus"])
        if bus is None:
            skipped_no_bus += 1
            logger.warning(
                "Generator replacement: %s — bus %r not in network; cannot attach replacement, skipped",
                name,
                rec["bus"],
            )
            continue
        # A pre-existing plant (no build_year) is "always built" → inherit base_year.
        by = rec["by"] if rec["by"] is not None else base_year
        province = rec["province"]
        if rec["frozen"] is not None:
            # Frozen at add-time — use the stored split verbatim, no recompute.
            solar_cap, wind_cap = rec["frozen"]
        elif follow:
            # Reference year for the solar:wind mix: the replacement (close/forced)
            # year when including existing plants, else the plant's build year.
            ref_year = ry if follow_close_year else by
            split_additions = full_additions if follow_close_year else annual_additions
            solar_cap, wind_cap = _split_capacity(
                settings=settings,
                annual_additions=split_additions,
                year=ref_year,
                capacity=capacity,
                follow=True,
            )
        else:
            solar_cap, wind_cap = _split_capacity(
                settings=settings,
                annual_additions=annual_additions,
                year=ry,
                capacity=capacity,
                follow=False,
            )
        # Per-plant trace in the Log tab — the ratio is verifiable against the
        # reference table, and "online <ry>" shows the retire-and-replace year.
        logger.info(
            "Generator replacement: %s (build %s → renewables online %s): %.1f MW -> solar %.1f + wind %.1f",
            name,
            rec["by"],
            ry,
            capacity,
            solar_cap,
            wind_cap,
        )

        # Record the original capacity removed at this bus so an ESS can be
        # sized as a proportion of it (summed when several plants share a bus).
        replaced_by_bus[bus] = replaced_by_bus.get(bus, 0.0) + capacity

        if rec["in_net"]:
            network.remove("Generator", name)
        for carrier, cap_mw in (("solar", solar_cap), ("wind", wind_cap)):
            if cap_mw <= 0:
                continue
            _add_renewable(
                network,
                base_name=name,
                carrier=carrier,
                bus=bus,
                province=province,
                p_nom=cap_mw,
                marginal_cost=carrier_mc[carrier] or 0.0,
                build_year=ry,
            )
            added += 1

    mode = (
        "follow yearly additions"
        if follow
        else (
            f"fixed {settings.replace_solar_pct:g}% solar / {settings.replace_wind_pct:g}% wind"
        )
    )
    bulk_note = (
        f", bulk {sorted(carriers_sel)} (+{bulk_added}, {retired_added} retired-early)"
        if bulk_on
        else ""
    )
    skip_note = f", {skipped_no_bus} skipped (bus missing)" if skipped_no_bus else ""
    logger.info(
        "Generator replacement: replaced %d plant(s) with %d renewable unit(s) [%s%s]%s "
        "(solar mc=%s, wind mc=%s)",
        len(records) - skipped_no_bus,
        added,
        mode,
        bulk_note,
        skip_note,
        carrier_mc["solar"],
        carrier_mc["wind"],
    )
    return replaced_by_bus


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

    for candidate_year in sorted(
        (y for y in annual_additions if y <= year), reverse=True
    ):
        solar_add, wind_add = annual_additions[candidate_year]
        if solar_add + wind_add > 0:
            return solar_add, wind_add
    return 0.0, 0.0


def _frozen_split_from_row(row: "pd.Series") -> tuple[float, float] | None:
    """Return ``(solar_mw, wind_mw)`` frozen on a table row, or ``None`` if absent.

    "Fill table from carriers" stores the split it computed at add-time in each
    row's ``solar_mw`` / ``wind_mw`` cells. When both are present and numeric the
    row is replaced with exactly that split (no recompute); otherwise the split
    is computed live. Either cell missing / blank / non-numeric → not frozen.
    """
    if "solar_mw" not in row.index or "wind_mw" not in row.index:
        return None
    solar = pd.to_numeric(row["solar_mw"], errors="coerce")
    wind = pd.to_numeric(row["wind_mw"], errors="coerce")
    if pd.isna(solar) or pd.isna(wind):
        return None
    return float(solar), float(wind)


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
