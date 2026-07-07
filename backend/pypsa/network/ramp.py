"""In-solve, timestep-weighted ramp-rate limits.

PyPSA ships native ``ramp_limit_up`` / ``ramp_limit_down`` columns, but its
constraint (``pypsa.optimization.constraints.define_ramp_limit_constraints``)
bounds the change in dispatch **per snapshot**, regardless of that snapshot's
duration:

    p[g,t] - p[g,t-1] <= ramp_limit_up[g] * p_nom[g]

That is correct for hourly snapshots but wrong for any other resolution — a
15-minute snapshot and a 4-hour snapshot would be held to the *same* absolute
MW swing, even though four times as much wall-clock time has elapsed in the
latter. This module instead scales the allowed swing by the snapshot's
duration (``n.snapshot_weightings.generators``, hours), so a rate expressed
as "fraction of p_nom per hour" behaves the same at any time resolution.

Algorithm:
    Eligible generators: supply generators (``load_shedding_*`` excluded),
    further restricted to non-variable-renewable carriers when
    ``appliesTo == "thermal"`` (reusing the reserve module's variable-
    renewable carrier detection so "thermal" means the same thing across
    both features).

    Per-generator hourly rate: the generator's own ``ramp_limit_up`` /
    ``ramp_limit_down`` column when set (> 0), else the config default.
    Note this column is read purely as a per-hour RATE parameter here — it is
    never written back onto ``n.generators``, so PyPSA's own native ramp
    constraint builder (which reads the same columns) never sees them and
    never fires; see "No double enforcement" below.

    Constraint, for eligible generator g and snapshot t that is not the first
    snapshot of the current optimisation window (window meaning: the full
    horizon in a single-shot solve, or one rolling-horizon window — ramp is
    NOT coupled across windows in v1, see "Rolling horizon" below):
        $$ p_{g,t} - p_{g,t-1} \\le \\text{rampUp}_g \\cdot p_{nom,g} \\cdot \\Delta t_t
           \\quad (\\texttt{"ramp\\_up"}) $$
        $$ p_{g,t-1} - p_{g,t} \\le \\text{rampDown}_g \\cdot p_{nom,g} \\cdot \\Delta t_t
           \\quad (\\texttt{"ramp\\_down"}) $$
        ASCII: p[g,t] - p[g,t-1] <= rampUp[g] * p_nom[g] * dt[t]        (ramp_up)
               p[g,t-1] - p[g,t] <= rampDown[g] * p_nom[g] * dt[t]      (ramp_down)
        Units: p in MW; rampUp/rampDown dimensionless per hour (fraction of
        p_nom per hour); p_nom in MW; dt in hours (the snapshot's weight).

    For an EXTENDABLE generator, ``p_nom`` is itself a linopy decision
    variable (``Generator-p_nom``); the RHS's ``rampUp_g * dt_t`` coefficient
    multiplying that variable is moved to the LHS so the constraint stays
    linear in the model's variables:
        $$ p_{g,t} - p_{g,t-1} - \\text{rampUp}_g \\cdot \\Delta t_t \\cdot
           p_{nom,g}^{var} \\le 0 $$
        ASCII: p[g,t] - p[g,t-1] - rampUp[g]*dt[t]*p_nom_var[g] <= 0

No double enforcement: PyPSA's native ramp constraint builder
(``define_ramp_limit_constraints``) is a no-op whenever the ``ramp_limit_up``
/ ``ramp_limit_down`` static columns are either absent from
``n.generators`` or entirely NaN (it checks
``{"ramp_limit_up","ramp_limit_down"}.isdisjoint(columns)`` and an
``all_null`` short-circuit before adding anything). This module never writes
into those columns on the network — it only *reads* per-generator overrides
from them as a rate parameter — so the native path always takes its early
return and this module's own ``ramp_up`` / ``ramp_down`` constraints are the
only ramp constraints in the LP. This is verified in the test suite by
asserting ``"Generator-p-ramp_limit_up"`` / ``"Generator-p-ramp_limit_down"``
are absent from ``n.model.constraints`` after a solve with ramp enabled.

Rolling horizon: each window's ``extra_functionality`` call gets a *fresh*
``n.model`` (linopy rebuilds it from scratch per window), so there is no
variable representing the previous window's last dispatch to couple against.
v1 therefore does not enforce a ramp limit across the window boundary (the
first snapshot of every window, including the very first, is left
unconstrained by this module) — a known limitation, reported in ``notes``
whenever rolling horizon is active.

Never raises into the solve: any failure is caught and reported via
``notes``, matching ``reserves.py``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa
import xarray as xr

from ..constants import carrier_color

_log = logging.getLogger("pypsa.solver")

# Carrier-name substrings treated as variable (non-dispatchable) renewables —
# excluded from ramp enforcement when appliesTo == "thermal". Kept identical
# to reserves.py so "thermal" means the same set of carriers everywhere.
_VARIABLE_RENEWABLE_MARKERS = ("solar", "pv", "wind")

_EPS = 1e-6


def _is_variable_renewable(carrier: str) -> bool:
    key = str(carrier).strip().lower()
    return any(marker in key for marker in _VARIABLE_RENEWABLE_MARKERS)


def _eligible_generators(
    n: pypsa.Network,
    applies_to: str,
) -> list[str]:
    """Ramp-eligible generators: all supply generators (``load_shedding_*``
    excluded), minus variable-renewable carriers when ``applies_to == "thermal"``.
    """
    supply_gens = [g for g in n.generators.index if not str(g).startswith("load_shedding_")]
    if applies_to == "thermal":
        carriers = n.generators["carrier"] if "carrier" in n.generators.columns else pd.Series(dtype=str)
        supply_gens = [g for g in supply_gens if not _is_variable_renewable(carriers.get(g, ""))]
    return supply_gens


def _per_generator_rates(
    gens: pd.DataFrame,
    eligible: list[str],
    default_up: float,
    default_down: float,
) -> tuple[pd.Series, pd.Series]:
    """Per-hour ramp rate (fraction of p_nom) for each eligible generator.

    A generator's own ``ramp_limit_up`` / ``ramp_limit_down`` column overrides
    the config default when set and > 0; otherwise the config default
    applies. These columns are read-only here (never written back), which is
    what keeps PyPSA's native ramp constraint from also firing — see the
    module docstring's "No double enforcement" section.
    """
    if "ramp_limit_up" in gens.columns:
        up_override = pd.to_numeric(gens["ramp_limit_up"].reindex(eligible), errors="coerce")
    else:
        up_override = pd.Series(np.nan, index=eligible)
    if "ramp_limit_down" in gens.columns:
        down_override = pd.to_numeric(gens["ramp_limit_down"].reindex(eligible), errors="coerce")
    else:
        down_override = pd.Series(np.nan, index=eligible)

    rate_up = up_override.where(up_override.notna() & (up_override > 0), default_up)
    rate_down = down_override.where(down_override.notna() & (down_override > 0), default_down)
    return rate_up, rate_down


def _rate_frame(dt_now: pd.Series, rate: pd.Series, t_now: list[Any], gens: list[str], dim: str) -> Any:
    """Build a (t_now x gens) xarray DataArray of ``dt[t] * rate[g]``, with
    dims explicitly named ``snapshot`` / ``dim`` (whatever ``Generator-p``'s
    own non-snapshot dim is called).

    linopy's ``force_dim_names`` check rejects multiplying a bare
    ``Variable``/``LinearExpression`` by a plain ``pandas.DataFrame`` whose
    index/columns are unnamed — pandas-to-xarray conversion then invents
    ``dim_0``/``dim_1`` instead of reusing ``snapshot``/``name``, which
    linopy refuses outright (``add_constraints`` is more permissive and
    silently outer-joins on mismatched names, but that reintroduces the same
    class of "looks fine, silently misaligned" bug this app avoids
    elsewhere — so this always builds an explicitly-dimensioned
    ``xr.DataArray`` before it ever touches a linopy variable).
    """
    outer = np.outer(dt_now.to_numpy(), rate.reindex(gens).to_numpy())
    return xr.DataArray(outer, dims=["snapshot", dim], coords={"snapshot": t_now, dim: gens})


def apply_ramp_constraints(
    n: pypsa.Network,
    ramp_cfg: dict[str, Any],
    snapshots: Any,
    notes: list[str],
) -> None:
    """Add timestep-weighted ramp-rate constraints to ``n.model``.

    Called from ``extra_functionality`` for every optimise path (single-shot,
    rolling-horizon window, SCLOPF). ``snapshots`` is the window currently
    being optimised; the first snapshot of that window is skipped (no
    ``t-1`` inside the window — see the module docstring's "Rolling horizon"
    note for why this is not coupled across windows in v1).

    Never raises: any failure is caught and reported via ``notes`` so a
    misconfigured ramp cannot take down the solve.
    """
    if not ramp_cfg or not bool(ramp_cfg.get("enabled")):
        return

    try:
        default_up = float(ramp_cfg.get("rampLimitUp", 0.0) if ramp_cfg.get("rampLimitUp") is not None else 0.0)
        default_down = float(
            ramp_cfg.get("rampLimitDown", 0.0) if ramp_cfg.get("rampLimitDown") is not None else 0.0
        )
        applies_to = str(ramp_cfg.get("appliesTo", "all") or "all")

        window = list(snapshots)
        if len(window) < 2:
            notes.append("Ramp-rate limits: window has fewer than 2 snapshots — skipped.")
            return

        eligible = _eligible_generators(n, applies_to)
        if not eligible:
            notes.append("Ramp-rate limits: no eligible generators found — skipped.")
            return

        rate_up, rate_down = _per_generator_rates(n.generators, eligible, default_up, default_down)
        # Nothing to enforce if every eligible generator's rate is zero on
        # both directions (0 would forbid any dispatch change at all, which
        # is a legitimate — if extreme — user configuration, so only skip
        # when BOTH defaults and BOTH overrides are entirely absent/zero and
        # would otherwise silently rigid-lock dispatch to its first-snapshot
        # value; we still add the constraint in that case, it is just very
        # tight, matching the "never silently drop a configured limit" rule).

        gen_p = n.model["Generator-p"]
        dim = [d for d in gen_p.dims if d != "snapshot"][0]

        t_now = window[1:]
        t_prev = window[:-1]

        weights_full = n.snapshot_weightings["generators"]
        dt = weights_full.reindex(window).fillna(1.0)
        dt_now = pd.Series(dt.loc[t_now].to_numpy(), index=t_now)  # Δt_t, hours

        gens = n.generators
        extendable_col = (
            gens["p_nom_extendable"] if "p_nom_extendable" in gens.columns else pd.Series(False, index=gens.index)
        )
        extendable = [g for g in eligible if bool(extendable_col.get(g, False))]
        fixed = [g for g in eligible if g not in extendable]

        p_now = gen_p.sel({"snapshot": t_now})
        p_prev_raw = gen_p.sel({"snapshot": t_prev})
        # p_prev_raw carries the t_prev snapshot labels as its coordinate; the
        # model needs both sides of the inequality indexed by the SAME
        # snapshot (t_now) to form one row per (t, g) — relabel before
        # subtracting.
        p_prev = p_prev_raw.assign_coords(snapshot=t_now)

        delta_p = p_now - p_prev  # p[g,t] - p[g,t-1], one row per (t in t_now, g)

        if fixed:
            p_nom_fixed = gens.loc[fixed, "p_nom"].fillna(0.0)
            # RHS: rampUp[g] * p_nom[g] * dt[t] — outer product of dt_t (rows)
            # and rampUp*p_nom (columns), a (t_now, fixed) frame.
            up_rate_fixed = rate_up.reindex(fixed) * p_nom_fixed
            down_rate_fixed = rate_down.reindex(fixed) * p_nom_fixed
            up_rhs_fixed = _rate_frame(dt_now, up_rate_fixed, t_now, fixed, dim)
            down_rhs_fixed = _rate_frame(dt_now, down_rate_fixed, t_now, fixed, dim)
            n.model.add_constraints(
                delta_p.sel({dim: fixed}) <= up_rhs_fixed, name="ramp_up_fixed"
            )
            n.model.add_constraints(
                -delta_p.sel({dim: fixed}) <= down_rhs_fixed, name="ramp_down_fixed"
            )

        if extendable:
            try:
                cap_var = n.model["Generator-p_nom"]
                cap_dim = cap_var.dims[0]
            except Exception:
                cap_var = None
                cap_dim = None
            if cap_var is not None and cap_dim is not None:
                up_rate_ext = _rate_frame(dt_now, rate_up, t_now, extendable, dim)
                down_rate_ext = _rate_frame(dt_now, rate_down, t_now, extendable, dim)
                cap_var_ext = cap_var.sel({cap_dim: extendable})
                if cap_dim != dim:
                    cap_var_ext = cap_var_ext.rename({cap_dim: dim})
                # p[g,t] - p[g,t-1] - rampUp[g]*dt[t]*p_nom_var[g] <= 0
                lhs_up = delta_p.sel({dim: extendable}) - up_rate_ext * cap_var_ext
                n.model.add_constraints(lhs_up <= 0, name="ramp_up_extendable")
                # p[g,t-1] - p[g,t] - rampDown[g]*dt[t]*p_nom_var[g] <= 0
                lhs_down = -delta_p.sel({dim: extendable}) - down_rate_ext * cap_var_ext
                n.model.add_constraints(lhs_down <= 0, name="ramp_down_extendable")
            else:
                # No extendable capacity variable available (shouldn't happen
                # if p_nom_extendable is set) — fall back to static p_nom so
                # the constraint still bounds the ramp.
                p_nom_ext_static = gens.loc[extendable, "p_nom"].fillna(0.0)
                up_rate_ext_static = rate_up.reindex(extendable) * p_nom_ext_static
                down_rate_ext_static = rate_down.reindex(extendable) * p_nom_ext_static
                up_rhs_ext = _rate_frame(dt_now, up_rate_ext_static, t_now, extendable, dim)
                down_rhs_ext = _rate_frame(dt_now, down_rate_ext_static, t_now, extendable, dim)
                n.model.add_constraints(
                    delta_p.sel({dim: extendable}) <= up_rhs_ext, name="ramp_up_extendable"
                )
                n.model.add_constraints(
                    -delta_p.sel({dim: extendable}) <= down_rhs_ext, name="ramp_down_extendable"
                )

        applies_note = "all supply generators" if applies_to != "thermal" else "thermal generators only"
        window_note = ""
        if len(window) < len(n.snapshots):
            window_note = (
                " Ramp is not coupled across rolling-horizon windows in v1 — "
                "the first snapshot of each window is unconstrained."
            )
        notes.append(
            f"Ramp-rate limits applied ({applies_note}, {len(eligible)} eligible): "
            f"default up {default_up:.2%}/h, down {default_down:.2%}/h, "
            f"Δt-weighted per snapshot weight.{window_note}"
        )
    except Exception as exc:  # never let ramp enforcement break the solve
        notes.append(f"Ramp-rate limits could not be added: {exc}")


def extract_ramp_results(
    n: pypsa.Network,
    ramp_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Read back dispatch deltas and ramp-constraint duals after the solve.

    Returns the ``"ramp"`` payload dict (see module docstring for the
    underlying constraint). ``enabled: False`` with a ``note`` when ramp was
    not configured or the network has no solved dispatch to diff.
    """
    enabled = bool((ramp_cfg or {}).get("enabled"))
    base: dict[str, Any] = {
        "enabled": False,
        "bindingHours": 0,
        "byCarrier": [],
        "summary": [],
        "note": None,
    }
    if not enabled:
        return base

    try:
        p_t = getattr(n.generators_t, "p", None)
        if p_t is None or p_t.empty:
            base["note"] = "Ramp-rate limits were enabled but no generator dispatch is available (see run notes)."
            return base

        applies_to = str(ramp_cfg.get("appliesTo", "all") or "all")
        default_up = float(ramp_cfg.get("rampLimitUp", 0.0) if ramp_cfg.get("rampLimitUp") is not None else 0.0)
        default_down = float(
            ramp_cfg.get("rampLimitDown", 0.0) if ramp_cfg.get("rampLimitDown") is not None else 0.0
        )

        eligible = [g for g in _eligible_generators(n, applies_to) if g in p_t.columns]
        if not eligible:
            base["note"] = "Ramp-rate limits: no eligible generators found in solved dispatch."
            return base

        snapshots = n.snapshots
        dispatch = p_t.reindex(index=snapshots, columns=eligible).fillna(0.0)

        weights = n.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0)
        rate_up, rate_down = _per_generator_rates(n.generators, eligible, default_up, default_down)
        p_nom = n.generators["p_nom_opt"].reindex(eligible) if "p_nom_opt" in n.generators.columns else n.generators[
            "p_nom"
        ].reindex(eligible)
        p_nom = p_nom.fillna(0.0)
        # Fall back to static p_nom for any generator whose p_nom_opt is 0/NaN
        # and not actually extendable (keeps a fixed unit's limit off 0 if
        # p_nom_opt was never populated by this solve path).
        static_p_nom = n.generators["p_nom"].reindex(eligible).fillna(0.0)
        p_nom = p_nom.where(p_nom > 0, static_p_nom)

        delta = dispatch.diff().iloc[1:]  # p[t] - p[t-1], drop the first (undefined) row
        dt = weights.iloc[1:]

        up_limit = pd.DataFrame(
            np.outer(dt.to_numpy(), (rate_up * p_nom).to_numpy()), index=delta.index, columns=eligible
        )
        down_limit = pd.DataFrame(
            np.outer(dt.to_numpy(), (rate_down * p_nom).to_numpy()), index=delta.index, columns=eligible
        )

        binding_up = delta >= (up_limit - _EPS)
        binding_down = (-delta) >= (down_limit - _EPS)
        # Only count as "binding" where a limit is actually active (rate > 0);
        # a zero-rate column would otherwise register every flat snapshot as
        # binding.
        active_up = pd.DataFrame(
            np.tile((rate_up.to_numpy() > 0), (len(delta.index), 1)), index=delta.index, columns=eligible
        )
        active_down = pd.DataFrame(
            np.tile((rate_down.to_numpy() > 0), (len(delta.index), 1)), index=delta.index, columns=eligible
        )
        binding_mask = (binding_up & active_up) | (binding_down & active_down)
        binding_hours_by_snapshot = binding_mask.any(axis=1)
        binding_hours = int(binding_hours_by_snapshot.sum())

        # Also check the linopy duals when available (last-window-only under
        # rolling horizon, same caveat as reserves.py's price series).
        dual_binding_snapshots: set[Any] = set()
        try:
            model = n.model
            if model is not None:
                for cname in ("ramp_up_fixed", "ramp_up_extendable", "ramp_down_fixed", "ramp_down_extendable"):
                    if cname in model.constraints:
                        dual = model.constraints[cname].dual
                        nz = np.abs(np.nan_to_num(dual.values)) > _EPS
                        if nz.any():
                            snap_coords = dual.coords["snapshot"].values
                            snap_idx = np.where(nz.any(axis=tuple(range(1, nz.ndim))))[0] if nz.ndim > 1 else np.where(nz)[0]
                            for i in snap_idx:
                                dual_binding_snapshots.add(snap_coords[i])
        except Exception:
            dual_binding_snapshots = set()

        if dual_binding_snapshots:
            binding_hours = max(
                binding_hours,
                len({s for s in dual_binding_snapshots if s in set(delta.index)}),
            )

        abs_delta = delta.abs()
        mean_abs_delta_by_gen = abs_delta.mean(axis=0)
        carriers = n.generators["carrier"].reindex(eligible).fillna("")
        by_carrier_mw: dict[str, float] = {}
        for g in eligible:
            c = str(carriers.get(g, ""))
            by_carrier_mw[c] = by_carrier_mw.get(c, 0.0) + float(mean_abs_delta_by_gen.get(g, 0.0))
        by_carrier = [
            {"label": c, "value": v, "color": carrier_color(n, c)}
            for c, v in sorted(by_carrier_mw.items(), key=lambda kv: kv[1], reverse=True)
            if v > 0.0
        ]

        mean_abs_delta = float(abs_delta.to_numpy().mean()) if abs_delta.size else 0.0
        max_abs_delta = float(abs_delta.to_numpy().max()) if abs_delta.size else 0.0
        summary = [
            {
                "label": "Mean |Δp| across ramp-constrained generators",
                "value": f"{mean_abs_delta:,.2f} MW",
                "detail": f"{len(eligible)} eligible generator(s)",
            },
            {
                "label": "Max |Δp|",
                "value": f"{max_abs_delta:,.2f} MW",
                "detail": "largest single-snapshot dispatch swing",
            },
            {
                "label": "Binding hours",
                "value": f"{binding_hours} of {len(delta.index)}",
                "detail": "snapshots where an up or down ramp limit binds",
            },
            {
                "label": "Default rate",
                "value": f"up {default_up:.2%}/h, down {default_down:.2%}/h",
                "detail": f"applies to: {applies_to}",
            },
        ]

        note = None
        if len(delta.index) < len(snapshots) - 1:
            note = "Ramp results cover fewer transitions than snapshots — check rolling-horizon window notes."

        return {
            "enabled": True,
            "bindingHours": binding_hours,
            "byCarrier": by_carrier,
            "summary": summary,
            "note": note,
        }
    except Exception as exc:
        base["note"] = f"Ramp-rate limit results could not be extracted: {exc}"
        _log.warning("ramp extraction failed: %s", exc)
        return base
