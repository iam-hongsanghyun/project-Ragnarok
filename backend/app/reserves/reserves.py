"""In-solve operating-reserve (spinning reserve) co-optimization.

Adds a reserve dispatch variable and headroom/requirement constraints to the
linopy model *inside* ``extra_functionality`` — i.e. before the solve, so the
reserve requirement competes with energy dispatch for capacity in the same LP
that clears the market. This is what makes the reserve price a genuine
opportunity cost (the dual of the requirement constraint) rather than a
post-hoc derived number.

Algorithm:
    Decision variable (added to the model, not derived after the solve):
        $$ r_{g,t} \\ge 0 \\quad \\forall g \\in \\text{eligible}, \\; t \\in \\text{snapshots} $$
        ASCII: r[g,t] >= 0, MW of reserve held by generator g at snapshot t.

    Headroom constraint (``reserve_headroom``) — dispatch plus reserve must
    fit under available capacity:
        $$ p_{g,t} + r_{g,t} \\le p_{nom,g} \\cdot pmax_{g,t} \\quad (\\text{fixed } g) $$
        $$ p_{g,t} + r_{g,t} - p_{nom,g}^{var} \\cdot pmax_{g,t} \\le 0 \\quad (\\text{extendable } g) $$
        ASCII: p[g,t] + r[g,t] <= p_nom[g] * p_max_pu[g,t]  (fixed capacity)
               p[g,t] + r[g,t] - p_nom_var[g] * p_max_pu[g,t] <= 0  (extendable)
        Units: p, r in MW; p_nom in MW; p_max_pu dimensionless in [0, 1].

    Requirement constraint (``reserve_requirement``) — the reserve pool must
    cover the configured product at every snapshot:
        $$ \\sum_{g \\in \\text{eligible}} r_{g,t} \\ge R_t \\quad \\forall t $$
        $$ R_t = \\text{fraction} \\cdot \\text{load}_t + \\text{largest\\_unit\\_mw} + R^{fix} $$
        ASCII: sum_g r[g,t] >= R_t, R_t = fraction*load_t + largest_unit_mw + requirementMw
        Units: r, R_t, largest_unit_mw, requirementMw in MW; fraction dimensionless; load_t in MW.
        ``requirementType`` picks the terms: ``fraction``, ``largestUnit``, ``both`` (fraction + largest unit), or
        ``fixed`` (``requirementMw`` alone, e.g. a grid code's reserve in MW). ``requirementMw`` > 0 is added to the
        other types too.

    Spinning rule (``spinning: true``) - only a unit that is generating can hold reserve. Without it an idle unit
    "holds" its whole rating, so in an LP the requirement binds only at peak. With an on/off share
    $u_{g,t} \\in [0, 1]$, a minimum stable load $m_g$ and $P_{g,t} = p_{nom,g} \\cdot pmax_{g,t}$:
        $$ m_g P_{g,t} u_{g,t} \\le p_{g,t}, \\qquad p_{g,t} + r_{g,t} \\le P_{g,t} u_{g,t} $$
        Eliminating $u$ gives the constraint added for a generator that is not committable:
        $$ r_{g,t} \\le \\frac{1 - m_g}{m_g} \\, p_{g,t} $$
        ASCII: r[g,t] <= (1 - m[g]) / m[g] * p[g,t]   (with the headroom above: a unit at full output holds none,
               a unit at minimum load holds up to (1 - m) of its rating, an idle unit holds none)
        Units: m dimensionless in (0, 1): ``minStableLoad``, or the generators sheet column ``reserve_min_load_pu``.
        A committable generator has PyPSA's own status variable, so its headroom becomes
        $$ p_{g,t} + r_{g,t} \\le p_{nom,g} \\cdot pmax_{g,t} \\cdot status_{g,t} $$
        ASCII: p[g,t] + r[g,t] <= p_nom[g] * p_max_pu[g,t] * status[g,t]

    Per-unit ceiling - generators sheet column ``reserve_max_pu`` (what a unit can ramp within the response time):
        $$ r_{g,t} \\le \\rho^{max}_g \\, p_{nom,g} $$
        ASCII: r[g,t] <= reserve_max_pu[g] * p_nom[g]

    Storage units (``includeStorageUnits: true``, fixed size only) hold reserve from standstill:
        $$ p^{dis}_{s,t} + r_{s,t} \\le p_{nom,s} \\cdot pmax_{s,t}, \\qquad
           r_{s,t} \\cdot h / \\eta^{dis}_s \\le soc_{s,t} $$
        ASCII: p_dispatch[s,t] + r[s,t] <= p_nom[s] * p_max_pu[s,t];  r[s,t] * h / efficiency_dispatch[s] <= soc[s,t]
        Units: h = ``reserveDurationHours`` (hours the reserve must be sustained, default 1); soc in MWh.
        The spinning rule does not apply to them (pumped hydro starts within the response time).

    Optional reserve cost term added to the objective (only when
    ``reserveCost > 0`` — the default is 0, in which case the reserve price
    is purely the headroom constraint's shadow cost):
        $$ \\text{extra cost} = \\text{reserveCost} \\cdot \\sum_{g,t} w_t \\cdot r_{g,t} $$
        ASCII: extra_cost = reserveCost * sum_{g,t} weight_t * r[g,t]
        Units: reserveCost in currency/MW; w_t dimensionless (snapshot weight,
        hours); extra_cost in currency.

Eligibility: ``eligible = supply_gens - shed_gens`` (never let the
load-shedding backstop provide reserve), further restricted to
non-variable-renewable carriers when ``providers == "thermal"``, and to the
generators a ``providerSelector`` names (``column=value|value&column2=value``,
read on the generators sheet, else on the generator's bus - the selector form
of ``RAGNAROK_CarrierOutputCap``).

Reading the solution back (rolling-horizon safe): the variable is named
``Generator-r`` (``<Component>-<attr>`` naming), so PyPSA's own
``assign_solution()`` generically persists it into ``n.generators_t.r`` the
same way it persists ``Generator-p`` — including across rolling-horizon
windows, where each window's ``extra_functionality`` call gets a *fresh*
``n.model`` (linopy rebuilds the model from scratch per window) and therefore
cannot see a prior window's solved ``Generator-r``. ``extract_reserve_results``
reads provision from ``n.generators_t.r`` for this reason, not from
``n.model`` directly.

The reserve price ($/MW-reserve at each snapshot) is the dual of
``reserve_requirement`` — read from ``n.model.constraints["reserve_requirement"].dual``.
Unlike the primal, PyPSA has no persistent per-snapshot dual dataframe, so
after a rolling-horizon run ``n.model`` only reflects the *last* window: the
price series only covers that window's snapshots and a note says so. On
MILP / committable runs (or any solve where linopy has no dual), the price
series comes back empty rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from backend.pypsa.constants import carrier_color
from backend.pypsa.utils.shedding import shedding_names

_log = logging.getLogger("pypsa.solver")

# Carrier-name substrings treated as variable (non-dispatchable) renewables —
# excluded from the reserve pool when providers == "thermal". Matched
# case-insensitively against the generator's carrier label.
_VARIABLE_RENEWABLE_MARKERS = ("solar", "pv", "wind")

_EPS = 1e-6


def _snapshot_label(snapshot: Any) -> str:
    """ISO-format a snapshot, handling multi-investment-period tuples."""
    if isinstance(snapshot, tuple) and len(snapshot) == 2:
        _period, timestep = snapshot
        return pd.Timestamp(timestep).isoformat() if not isinstance(timestep, str) else timestep
    try:
        return pd.Timestamp(snapshot).isoformat()
    except Exception:
        return str(snapshot)


def _is_variable_renewable(carrier: str) -> bool:
    key = str(carrier).strip().lower()
    return any(marker in key for marker in _VARIABLE_RENEWABLE_MARKERS)


def _eligible_generators(
    n: pypsa.Network,
    supply_gens: list[str],
    shed_gens: list[str],
    providers: str,
) -> list[str]:
    """Reserve-eligible generators: supply gens minus shed gens, minus
    variable-renewable carriers when ``providers == "thermal"``."""
    shed_set = set(shed_gens)
    eligible = [g for g in supply_gens if g not in shed_set]
    if providers == "thermal":
        carriers = n.generators["carrier"] if "carrier" in n.generators.columns else pd.Series(dtype=str)
        eligible = [g for g in eligible if not _is_variable_renewable(carriers.get(g, ""))]
    return eligible


def _largest_installed_unit(gens: pd.DataFrame, eligible: list[str]) -> float:
    """Largest INSTALLED unit (``p_nom``) among eligible generators — the N-1
    "largest unit" reserve target.

    Keyed to installed capacity (a build-time constant) rather than an
    extendable unit's ``p_nom_max`` (buildable ceiling, which can balloon the
    requirement toward infeasibility) or the post-solve ``p_nom_opt`` (a
    variable, unknown when the constraint is built). Using the same constant in
    the constraint and the reported series guarantees they never diverge; for a
    fixed fleet (``p_nom == p_nom_opt``) it is exact. Expansion beyond ``p_nom``
    is not tracked by the N-1 target in v1.
    """
    if not eligible:
        return 0.0
    p_nom = gens["p_nom"].reindex(eligible).fillna(0.0)
    return float(p_nom.max()) if len(p_nom) else 0.0


REQUIREMENT_TYPES = ("fraction", "largestUnit", "both", "fixed")
MIN_LOAD_COLUMN = "reserve_min_load_pu"
MAX_RESERVE_COLUMN = "reserve_max_pu"


def _number(cfg: dict[str, Any], key: str, default: float) -> float:
    value = cfg.get(key)
    return default if value is None or value == "" else float(value)


def validate_reserve_config(reserve_cfg: dict[str, Any]) -> None:
    """Refuse a reserve plan that cannot be honoured as written (``ValueError``; the hook turns it into a 400).

    A reserve rule that is mis-read must stop the run, not loosen it: an unknown requirement type, a negative or
    non-numeric ``requirementMw``, ``fixed`` with no MW, a spinning rule with no minimum stable load in (0, 1), a
    malformed ``providerSelector``, or a non-positive ``reserveDurationHours``.
    """
    cfg = reserve_cfg or {}
    if not bool(cfg.get("enabled")):
        return
    rtype = str(cfg.get("requirementType", "fraction") or "fraction")
    if rtype not in REQUIREMENT_TYPES:
        raise ValueError(f"reserveConfig.requirementType must be one of {', '.join(REQUIREMENT_TYPES)}, got {rtype!r}.")
    try:
        req_mw = _number(cfg, "requirementMw", 0.0)
        hours = _number(cfg, "reserveDurationHours", 1.0)
        m = cfg.get("minStableLoad")
        m = None if m is None or m == "" else float(m)
    except (TypeError, ValueError):
        raise ValueError("reserveConfig: requirementMw, minStableLoad and reserveDurationHours must be numbers.") from None
    if not np.isfinite(req_mw) or req_mw < 0:
        raise ValueError(f"reserveConfig.requirementMw must be a finite MW >= 0, got {cfg.get('requirementMw')!r}.")
    if rtype == "fixed" and req_mw <= 0:
        raise ValueError("reserveConfig.requirementType 'fixed' needs requirementMw > 0.")
    if bool(cfg.get("spinning")) and (m is None or not 0.0 < m < 1.0):
        raise ValueError("reserveConfig.spinning needs minStableLoad in (0, 1): the minimum stable load of a unit, "
                         f"as a share of its available output (column {MIN_LOAD_COLUMN} overrides it per generator).")
    if not np.isfinite(hours) or hours <= 0:
        raise ValueError(f"reserveConfig.reserveDurationHours must be > 0, got {cfg.get('reserveDurationHours')!r}.")
    selector = str(cfg.get("providerSelector") or "").strip()
    if selector:
        from backend.app.constraints.carrier_output_cap import parse_group

        try:
            parsed = parse_group(selector)
        except Exception as exc:  # noqa: BLE001 - parse_group raises an HTTPException; the message is what matters
            raise ValueError(f"reserveConfig.providerSelector {selector!r}: {getattr(exc, 'detail', exc)}") from None
        if parsed is None:
            raise ValueError(f"reserveConfig.providerSelector {selector!r} must be column=value (e.g. fuel=coal|lng).")


def requirement_series(
    n: pypsa.Network,
    reserve_cfg: dict[str, Any],
    snapshots: Any,
    eligible: list[str],
) -> tuple[pd.Series, list[str]]:
    """The reserve requirement R_t (MW) on ``snapshots`` and the words for each term.

    One function for the constraint and for the reported series, so they never diverge:
    R_t = [fraction * load_t] + [largest eligible unit] + [requirementMw] - see the module docstring.
    """
    cfg = reserve_cfg or {}
    rtype = str(cfg.get("requirementType", "fraction") or "fraction")
    fraction = _number(cfg, "fraction", 0.1)
    req_mw = max(0.0, _number(cfg, "requirementMw", 0.0))
    use_fraction = rtype in ("fraction", "both")
    use_largest_unit = rtype in ("largestUnit", "both")
    if rtype not in REQUIREMENT_TYPES:
        use_fraction = True  # an unrecognised type falls back to the fraction (validate_reserve_config refuses it first)
    requirement = pd.Series(0.0, index=snapshots)
    parts: list[str] = []
    if use_fraction:
        load_t = n.get_switchable_as_dense("Load", "p_set").reindex(snapshots).sum(axis=1).fillna(0.0)
        requirement = requirement + fraction * load_t
        parts.append(f"{fraction:.1%} of load")
    if use_largest_unit and eligible:
        largest_unit_mw = _largest_installed_unit(n.generators, eligible)
        requirement = requirement + largest_unit_mw
        parts.append(f"largest unit ({largest_unit_mw:.4g} MW)")
    if req_mw > 0:
        requirement = requirement + req_mw
        parts.append(f"{req_mw:,.6g} MW fixed")
    return requirement, parts


def _select_providers(n: pypsa.Network, eligible: list[str], selector: str, model: dict[str, Any] | None) -> list[str]:
    """``eligible`` restricted to the generators ``selector`` names (generators sheet columns, else the bus's)."""
    from backend.app.constraints.carrier_output_cap import group_members, model_frames

    gens, buses = model_frames(model, n)
    named = set(group_members(selector, gens, buses))
    return [g for g in eligible if g in named]


def _sheet_column(n: pypsa.Network, model: dict[str, Any] | None, column: str, names: list[str]) -> pd.Series:
    """A generators-sheet column PyPSA does not keep (``reserve_min_load_pu`` ...), as floats by generator (NaN: blank)."""
    from backend.app.constraints.carrier_output_cap import model_frames

    gens, _ = model_frames(model, n)
    if column not in gens:
        return pd.Series(np.nan, index=names, dtype=float)
    return pd.to_numeric(gens[column], errors="coerce").reindex(names).astype(float)


def _dense(frame: pd.DataFrame, snapshots: Any, names: list[str], dim: str) -> Any:
    """A (snapshot x name) frame as a DataArray on the model's own dimension names."""
    import xarray as xr

    values = frame.reindex(index=snapshots, columns=names).to_numpy(dtype=float)
    return xr.DataArray(values, coords=[snapshots, names], dims=["snapshot", dim])


def apply_reserve_constraints(
    n: pypsa.Network,
    reserve_cfg: dict[str, Any],
    snapshots: Any,
    notes: list[str],
    model: dict[str, Any] | None = None,
) -> None:
    """Add the reserve variable + headroom/requirement constraints to ``n.model``.

    Called from ``extra_functionality`` (so ``n.model`` — the linopy Model —
    is available) for every optimize path: single-shot, rolling-horizon
    window, and SCLOPF. ``snapshots`` is the window currently being
    optimised; the reserve requirement is scoped to it exactly like the
    energy balance is.

    Never raises: any failure is caught and reported via ``notes`` so it
    cannot take down the solve.
    """
    if not reserve_cfg or not bool(reserve_cfg.get("enabled")):
        return

    try:
        providers = str(reserve_cfg.get("providers", "all") or "all")
        reserve_cost = float(reserve_cfg.get("reserveCost", 0.0) or 0.0)
        selector = str(reserve_cfg.get("providerSelector") or "").strip()
        spinning = bool(reserve_cfg.get("spinning"))
        include_storage = bool(reserve_cfg.get("includeStorageUnits"))

        gens = n.generators
        shed_gens = shedding_names(gens)
        supply_gens = [g for g in gens.index if g not in set(shed_gens)]
        eligible = _eligible_generators(n, supply_gens, shed_gens, providers)
        if selector:
            eligible = _select_providers(n, eligible, selector, model)

        if not eligible:
            notes.append(
                "Operating reserve: no reserve-eligible generators found — skipped."
            )
            return

        # Committable generators carry PyPSA's own status variable: with the spinning rule their headroom is
        # p + r <= p_nom * p_max_pu * status, so an offline unit holds no reserve.
        committable: list[str] = []
        status_var = None
        if spinning and "committable" in gens.columns and "Generator-status" in n.model.variables:
            status_var = n.model["Generator-status"]
            status_names = set(status_var.indexes[next(d for d in status_var.dims if d != "snapshot")])
            committable = [g for g in eligible if bool(gens["committable"].get(g, False)) and g in status_names]

        gen_p = n.model["Generator-p"]
        dim = [d for d in gen_p.dims if d != "snapshot"][0]

        # p_max_pu per (snapshot, generator) — get_switchable_as_dense resolves
        # static + time-varying inputs uniformly (every generator gets a
        # column, static default already filled in), same source
        # apply_custom_constraints uses.
        p_max_pu = n.get_switchable_as_dense("Generator", "p_max_pu").reindex(
            index=snapshots, columns=eligible
        )

        extendable_col = gens["p_nom_extendable"] if "p_nom_extendable" in gens.columns else pd.Series(False, index=gens.index)
        extendable = [g for g in eligible if bool(extendable_col.get(g, False))]
        fixed = [g for g in eligible if g not in extendable and g not in committable]

        r = n.model.add_variables(
            lower=0,
            coords=[snapshots, eligible],
            dims=["snapshot", dim],
            name="Generator-r",
        )

        # ── Headroom: p + r <= available capacity ───────────────────────────
        if fixed:
            p_nom_fixed = gens.loc[fixed, "p_nom"].fillna(0.0)
            headroom_rhs_fixed = p_max_pu[fixed] * p_nom_fixed
            lhs_fixed = gen_p.sel({dim: fixed}) + r.sel({dim: fixed})
            n.model.add_constraints(
                lhs_fixed <= headroom_rhs_fixed, name="reserve_headroom_fixed"
            )

        if extendable:
            try:
                cap_var = n.model["Generator-p_nom"]
                cap_dim = cap_var.dims[0]
            except Exception:
                cap_var = None
                cap_dim = None
            if cap_var is not None and cap_dim is not None:
                pmax_extendable = p_max_pu[extendable]
                lhs_ext = (
                    gen_p.sel({dim: extendable})
                    + r.sel({dim: extendable})
                    - cap_var.sel({cap_dim: extendable}) * pmax_extendable
                )
                n.model.add_constraints(lhs_ext <= 0, name="reserve_headroom_extendable")
            else:
                # No extendable capacity variable available (shouldn't happen
                # if p_nom_extendable is set) — fall back to the static p_nom
                # so the constraint still bounds reserve provision.
                p_nom_ext_static = gens.loc[extendable, "p_nom"].fillna(0.0)
                headroom_rhs_ext = p_max_pu[extendable] * p_nom_ext_static
                lhs_ext = gen_p.sel({dim: extendable}) + r.sel({dim: extendable})
                n.model.add_constraints(
                    lhs_ext <= headroom_rhs_ext, name="reserve_headroom_extendable"
                )

        if committable and status_var is not None:
            sdim = next(d for d in status_var.dims if d != "snapshot")
            avail = _dense(p_max_pu[committable] * gens.loc[committable, "p_nom"].fillna(0.0), snapshots, committable, sdim)
            lhs_com = (
                gen_p.sel({dim: committable})
                + r.sel({dim: committable})
                - status_var.sel({sdim: committable}) * avail
            )
            n.model.add_constraints(lhs_com <= 0, name="reserve_headroom_committable")

        # ── Spinning rule: r <= (1 - m) / m * p for a generator with no status variable ──
        spinning_note = ""
        if spinning:
            m_default = _number(reserve_cfg, "minStableLoad", float("nan"))
            linear = [g for g in eligible if g not in committable]
            if linear:
                m_own = _sheet_column(n, model, MIN_LOAD_COLUMN, linear)
                m_g = m_own.where((m_own > 0.0) & (m_own < 1.0), m_default)
                if m_g.isna().any() or not ((m_g > 0.0) & (m_g < 1.0)).all():
                    raise ValueError("spinning rule: no minimum stable load in (0, 1) for "
                                     + ", ".join(m_g.index[~((m_g > 0.0) & (m_g < 1.0))][:5].astype(str)))
                import xarray as xr

                rho = xr.DataArray(((1.0 - m_g) / m_g).to_numpy(dtype=float), coords=[linear], dims=[dim])
                n.model.add_constraints(
                    r.sel({dim: linear}) - gen_p.sel({dim: linear}) * rho <= 0, name="reserve_spinning"
                )
                own_n = int(((m_own > 0.0) & (m_own < 1.0)).sum())
                spinning_note = (f" Spinning rule: r <= (1 - m) / m x p, m = {m_default:g}"
                                 + (f" ({own_n} generator(s) with their own {MIN_LOAD_COLUMN})" if own_n else "")
                                 + (f"; {len(committable)} committable generator(s) on their status variable" if committable else "")
                                 + ".")
            elif committable:
                spinning_note = f" Spinning rule: {len(committable)} committable generator(s) on their status variable."

        # ── Per-unit ceiling: r <= reserve_max_pu * p_nom (generators sheet column) ──
        r_max = _sheet_column(n, model, MAX_RESERVE_COLUMN, eligible)
        capped = [g for g in eligible if np.isfinite(r_max.get(g, np.nan)) and r_max[g] >= 0.0]
        if capped:
            import xarray as xr

            ceiling = xr.DataArray((r_max[capped] * gens.loc[capped, "p_nom"].fillna(0.0)).to_numpy(dtype=float),
                                   coords=[capped], dims=[dim])
            n.model.add_constraints(r.sel({dim: capped}) <= ceiling, name="reserve_unit_ceiling")

        # ── Storage units: reserve from standstill, bounded by discharge headroom and stored energy ──
        storage: list[str] = []
        r_storage = None
        if include_storage and len(n.storage_units) and "StorageUnit-p_dispatch" in n.model.variables:
            su = n.storage_units
            su_ext = su["p_nom_extendable"] if "p_nom_extendable" in su.columns else pd.Series(False, index=su.index)
            storage = [s for s in su.index if not bool(su_ext.get(s, False)) and float(su["p_nom"].get(s, 0.0) or 0.0) > 0.0]
        if storage:
            import xarray as xr

            p_dis = n.model["StorageUnit-p_dispatch"]
            soc = n.model["StorageUnit-state_of_charge"]
            sudim = next(d for d in p_dis.dims if d != "snapshot")
            hours = _number(reserve_cfg, "reserveDurationHours", 1.0)
            su_avail = _dense(
                n.get_switchable_as_dense("StorageUnit", "p_max_pu").reindex(index=snapshots, columns=storage)
                * n.storage_units.loc[storage, "p_nom"].fillna(0.0),
                snapshots, storage, sudim,
            )
            eta = n.storage_units.loc[storage, "efficiency_dispatch"].fillna(1.0).clip(lower=1e-6)
            per_mw = xr.DataArray((hours / eta).to_numpy(dtype=float), coords=[storage], dims=[sudim])
            r_storage = n.model.add_variables(
                lower=0, coords=[snapshots, storage], dims=["snapshot", sudim], name="StorageUnit-r"
            )
            n.model.add_constraints(
                p_dis.sel({sudim: storage}) + r_storage <= su_avail, name="reserve_headroom_storage"
            )
            n.model.add_constraints(
                r_storage * per_mw - soc.sel({sudim: storage}) <= 0, name="reserve_energy_storage"
            )

        # ── Requirement: sum_g r[g,t] >= R_t ─────────────────────────────────
        requirement, parts = requirement_series(n, reserve_cfg, snapshots, eligible)

        if float(requirement.abs().sum()) <= _EPS:
            notes.append(
                "Operating reserve: requirement evaluates to zero at every "
                "snapshot (no load and no eligible capacity) — reserve "
                "variable added but the requirement constraint is a no-op."
            )

        total_r = r.sum(dim)
        if r_storage is not None:
            total_r = total_r + r_storage.sum(next(d for d in r_storage.dims if d != "snapshot"))
        n.model.add_constraints(
            total_r >= requirement, name="reserve_requirement"
        )

        if reserve_cost > 0:
            weights = n.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0)
            held = (r * weights).sum()
            if r_storage is not None:
                held = held + (r_storage * weights).sum()
            n.model.objective.expression = n.model.objective.expression + reserve_cost * held

        providers_note = "all supply generators" if providers != "thermal" else "thermal generators only"
        if selector:
            providers_note += f" matching {selector}"
        notes.append(
            f"Operating reserve co-optimized: requirement = {' + '.join(parts) or '0 MW'}, "
            f"providers = {providers_note} ({len(eligible)} eligible"
            + (f", {len(storage)} storage unit(s)" if storage else "")
            + ")."
            + spinning_note
            + (f" {len(capped)} generator(s) capped by {MAX_RESERVE_COLUMN}." if capped else "")
            + (f" Reserve cost {reserve_cost:g}/MW added to the objective." if reserve_cost > 0 else "")
        )
    except Exception as exc:  # never let reserve co-optimization break the solve
        notes.append(f"Operating reserve could not be added: {exc}")


def extract_reserve_results(
    n: pypsa.Network,
    reserve_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Read back the reserve variable, requirement and price after the solve.

    Returns the ``"reserve"`` payload dict (see module docstring / the
    formulation note above for the underlying LP). ``enabled: False`` with a
    ``note`` when reserves were not configured, not added (no eligible
    generators), or the model doesn't expose a ``Generator-r`` variable
    (e.g. the config was toggled off, or the solve failed before reserves
    were built).
    """
    enabled = bool((reserve_cfg or {}).get("enabled"))
    requirement_type = str((reserve_cfg or {}).get("requirementType", "fraction") or "fraction")

    base: dict[str, Any] = {
        "enabled": False,
        "requirementType": requirement_type,
        "requirementMwSeries": [],
        "providedMwSeries": [],
        "priceSeries": [],
        "byCarrier": [],
        "byGenerator": [],
        "summary": [],
        "scarcityHours": 0,
        "note": None,
    }
    if not enabled:
        return base

    try:
        # Provision is read from n.generators_t.r, not n.model directly: the
        # variable is named "Generator-r" ("<Component>-<attr>"), so PyPSA's
        # assign_solution() generically persists it there — the same
        # mechanism that persists Generator-p — and unlike n.model it survives
        # across rolling-horizon windows (each window rebuilds n.model from
        # scratch, so a later window's extra_functionality call never sees an
        # earlier window's solved Generator-r).
        r_t = getattr(n.generators_t, "r", None)
        if r_t is None or r_t.empty:
            base["note"] = "Operating reserve was enabled but not added to the solve (see run notes)."
            return base

        snapshots = n.snapshots
        labels = [_snapshot_label(s) for s in snapshots]
        gen_names = [str(g) for g in r_t.columns if g in n.generators.index]
        provided = r_t.reindex(index=snapshots, columns=gen_names).fillna(0.0)
        # Storage units that held reserve (includeStorageUnits): StorageUnit-r, persisted the same way.
        rs_t = getattr(n.storage_units_t, "r", None)
        storage_names = [str(s) for s in rs_t.columns if s in n.storage_units.index] if rs_t is not None and not rs_t.empty else []
        provided_storage = (rs_t.reindex(index=snapshots, columns=storage_names).fillna(0.0)
                            if storage_names else pd.DataFrame(index=snapshots))
        provided_total = provided.sum(axis=1) + (provided_storage.sum(axis=1) if storage_names else 0.0)

        # ── Requirement series: the same function the constraint used, on the generators that got the
        # variable (the columns of Generator-r), so the displayed requirement never diverges from the LP's.
        gens = n.generators
        eligible = gen_names
        requirement, _parts = requirement_series(n, reserve_cfg or {}, snapshots, eligible)

        requirement_mw_series = [
            {"label": lbl, "value": float(requirement.iloc[i])} for i, lbl in enumerate(labels)
        ]
        provided_mw_series = [
            {"label": lbl, "value": float(provided_total.iloc[i])} for i, lbl in enumerate(labels)
        ]

        # ── Price: dual of the requirement constraint ───────────────────────
        # n.model only reflects the LAST solved window (rolling horizon
        # rebuilds it from scratch every window, and each window's
        # extra_functionality call cannot see a prior window's constraints) —
        # the dual therefore only ever covers, at most, the snapshots of the
        # most recent solve. Align by position via get_indexer so a partial
        # (rolling-horizon) dual still lands on the right snapshots instead of
        # silently misaligning.
        price_by_position: dict[int, float] = {}
        try:
            model = n.model
            if model is not None and "reserve_requirement" in model.constraints:
                dual = model.constraints["reserve_requirement"].dual
                dual_snapshots = dual.coords["snapshot"].values
                dual_values = dual.values
                positions = snapshots.get_indexer(dual_snapshots)
                for pos, val in zip(positions, dual_values):
                    if pos >= 0 and not np.isnan(val):
                        price_by_position[int(pos)] = float(val)
        except Exception:
            price_by_position = {}

        dual_partial = 0 < len(price_by_position) < len(snapshots)
        price_series = [
            {"label": labels[i], "value": price_by_position[i]}
            for i in sorted(price_by_position)
        ]
        price_values: np.ndarray | None = (
            np.array([price_by_position.get(i, np.nan) for i in range(len(snapshots))])
            if price_by_position
            else None
        )

        # ── Per-carrier / per-generator aggregates ──────────────────────────
        carriers = gens["carrier"].reindex(gen_names).fillna("")
        by_carrier_mw: dict[str, float] = {}
        for g in gen_names:
            c = str(carriers.get(g, ""))
            by_carrier_mw[c] = by_carrier_mw.get(c, 0.0) + float(provided[g].mean())
        storage_carriers = (n.storage_units["carrier"].reindex(storage_names).fillna("")
                            if storage_names else pd.Series(dtype=str))
        for s_name in storage_names:
            c = str(storage_carriers.get(s_name, ""))
            by_carrier_mw[c] = by_carrier_mw.get(c, 0.0) + float(provided_storage[s_name].mean())
        by_carrier = [
            {"label": c, "value": v, "color": carrier_color(n, c)}
            for c, v in sorted(by_carrier_mw.items(), key=lambda kv: kv[1], reverse=True)
            if v > 0.0
        ]

        mean_price = float(np.nanmean(price_values)) if price_values is not None and len(price_values) else 0.0
        by_generator = []
        for g in gen_names:
            mean_r = float(provided[g].mean())
            if mean_r <= 0.0:
                continue
            weights = n.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0)
            revenue = 0.0
            if price_values is not None:
                revenue = float((provided[g].to_numpy() * np.nan_to_num(price_values) * weights.to_numpy()).sum())
            by_generator.append(
                {
                    "name": g,
                    "carrier": str(carriers.get(g, "")),
                    "meanReserveMw": mean_r,
                    "meanReservePriceRevenue": revenue,
                }
            )
        for s_name in storage_names:
            mean_r = float(provided_storage[s_name].mean())
            if mean_r <= 0.0:
                continue
            weights = n.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0)
            revenue = 0.0
            if price_values is not None:
                revenue = float((provided_storage[s_name].to_numpy() * np.nan_to_num(price_values) * weights.to_numpy()).sum())
            by_generator.append(
                {
                    "name": s_name,
                    "carrier": str(storage_carriers.get(s_name, "")),
                    "meanReserveMw": mean_r,
                    "meanReservePriceRevenue": revenue,
                }
            )
        by_generator.sort(key=lambda row: row["meanReserveMw"], reverse=True)

        eps = 1e-6
        scarcity_hours = (
            int(np.sum(np.nan_to_num(price_values) > eps)) if price_values is not None else 0
        )

        mean_requirement = float(requirement.mean()) if len(requirement) else 0.0
        mean_provided = float(provided_total.mean()) if len(provided_total) else 0.0
        summary = [
            {
                "label": "Mean reserve requirement",
                "value": f"{mean_requirement:,.1f} MW",
                "detail": f"requirement type: {requirement_type}",
            },
            {
                "label": "Mean reserve provided",
                "value": f"{mean_provided:,.1f} MW",
                "detail": f"{len(eligible)} eligible generator(s)"
                + (f" + {len(storage_names)} storage unit(s)" if storage_names else ""),
            },
            {
                "label": "Mean reserve price",
                "value": f"{mean_price:,.4f} /MW",
                "detail": "dual of the reserve_requirement constraint",
            },
            {
                "label": "Scarcity hours",
                "value": f"{scarcity_hours} of {len(snapshots)}",
                "detail": "snapshots where the reserve requirement is binding",
            },
        ]

        note = None
        if price_values is None:
            note = (
                "Reserve price unavailable: this run has no linopy dual for "
                "reserve_requirement (typical for MILP/committable solves). "
                "Provision (MW) is still reported."
            )
        elif dual_partial:
            note = (
                "Reserve price only covers the last solved window "
                f"({len(price_by_position)} of {len(snapshots)} snapshots) — "
                "rolling horizon rebuilds the linopy model per window, so an "
                "earlier window's dual is not retained. Provision (MW) covers "
                "the full horizon."
            )

        return {
            "enabled": True,
            "requirementType": requirement_type,
            "requirementMwSeries": requirement_mw_series,
            "providedMwSeries": provided_mw_series,
            "priceSeries": price_series,
            "byCarrier": by_carrier,
            "byGenerator": by_generator,
            "summary": summary,
            "scarcityHours": scarcity_hours,
            "note": note,
        }
    except Exception as exc:
        base["note"] = f"Operating reserve results could not be extracted: {exc}"
        _log.warning("reserve extraction failed: %s", exc)
        return base
