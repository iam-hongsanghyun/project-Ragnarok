"""ELCC / capacity credit — post-process reliability accreditation.

Resource adequacy (``adequacy.py``) and the thermal forced-outage Monte Carlo
(``outage_mc.py``) both ask "how reliable is the system, given variability and
outages?" This module answers the complementary *accreditation* question every
IRP and capacity market eventually has to answer: **how much is a given
resource class actually worth, expressed in the currency regulators and
markets understand — perfectly-firm MW?**

**Effective Load-Carrying Capability (ELCC).** The ELCC of a resource class
(a carrier — wind, solar, storage, …) is the amount of hypothetical, always-
available ("perfectly firm") capacity that would deliver the *same* system
reliability (loss-of-load expectation, LOLE) as the resource actually
provides. It is the standard "1-in-10" capacity-accreditation metric: a
1,000 MW wind fleet with an ELCC% of 15% is accredited only 150 MW of firm
capacity in a resource-adequacy / capacity-market study, because that is the
firm-MW-equivalent contribution its variable, correlated-with-load output
actually makes to keeping the lights on.

This module is a **strict post-process** (no re-solve): it reuses the exact
outage-inclusive availability ensemble machinery from ``outage_mc.py`` (the
two-state Markov thermal-outage sampler over thermal units, deterministic or
ensemble renewable availability) and the ``compute_adequacy`` LOLE kernel from
``adequacy.py``, then runs a bisection search per carrier.

Algorithm:
    Let ``avail_full`` (M, T) be the full-system available-generation ensemble
    (thermal units subject to Markov forced outage, renewables at their solved
    availability or ensemble draws — identical construction to
    ``build_outage_mc``). Baseline reliability:
        $$ \\mathrm{LOLE}_{\\text{base}} = \\mathrm{LOLE}(\\text{avail\\_full}) $$
        ASCII: LOLE_base = LOLE(avail_full)

    For a target carrier c with nameplate capacity $N_c$ (MW), remove every
    generator/storage unit of that carrier from the ensemble (their MW
    contribution, additive across units, is simply subtracted):
        $$ \\text{avail\\_without}_{m,t} = \\text{avail\\_full}_{m,t} - \\sum_{g \\in c} \\text{contrib}_{g,m,t} $$
        ASCII: avail_without[m,t] = avail_full[m,t] - sum_{g in c} contrib[g,m,t]

    Because removing capacity cannot improve reliability,
    $\\mathrm{LOLE}(\\text{avail\\_without}) \\ge \\mathrm{LOLE}_{\\text{base}}$. Adding a
    constant firm block $F$ (MW, present at every member/snapshot, i.e. never
    on outage) to ``avail_without`` is a monotonically non-increasing function
    of $F$ in LOLE space, so the ELCC is the unique $F^\\*$ solving:
        $$ \\mathrm{LOLE}\\big(\\text{avail\\_without} + F^\\*\\big) = \\mathrm{LOLE}_{\\text{base}}, \\qquad F^\\* \\in [0, N_c] $$
        ASCII: find F* in [0, N_c] such that LOLE(avail_without + F*) == LOLE_base

    found by bisection on $F$ (LOLE is a non-increasing step function of F —
    not strictly monotonic/continuous because the underlying shortfall
    indicator is discrete across members/snapshots — so bisection targets the
    smallest $F$ achieving LOLE $\\le$ LOLE_base within tolerance, which is well
    defined because the function is monotone non-increasing even where flat).
    Capacity credit as a fraction of nameplate:
        $$ \\mathrm{ELCC\\%}_c = 100 \\cdot F^\\*_c / N_c $$
        ASCII: ELCC_pct = 100 * F_star / N_c

    Interpretation of edge cases: if removing carrier c does not change LOLE
    at all (the resource never has output at the system's scarcity
    snapshots — e.g. an evening-peaking system with only solar), $F^\\*=0$
    (bisection converges immediately since ``avail_without`` already meets
    the baseline). If the carrier is perfectly firm (no forced outage, flat
    ``p_max_pu``$\\equiv1$), removing then replacing its full nameplate as an
    always-on firm block reproduces ``avail_full`` exactly, so $F^\\* \\to N_c$
    (ELCC% -> 100%).

Symbols: M = ensemble members; T = snapshots; $N_c$ = nameplate MW of carrier
c (sum of ``p_nom``/``p_nom_opt`` over its generators + storage units);
LOLE = loss-of-load expectation (h/yr, annualised by ``compute_adequacy``);
$F$ = candidate/solved firm-MW block (MW), constant across members and
snapshots by construction (that is precisely what "perfectly firm" means).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pypsa

from ..constants import carrier_color
from .adequacy import compute_adequacy
from .outage_mc import _is_variable_renewable, sample_outage_masks

_log = logging.getLogger("pypsa.solver")

_EPS = 1e-9

_DEFAULT_N_MEMBERS = 200
_DEFAULT_SEED = 42
_DEFAULT_FOR = 0.05
_DEFAULT_MTTR_HOURS = 48.0
_DEFAULT_TOLERANCE_HOURS = 0.05
_MAX_BISECTION_ITERS = 20


def _lole_of(
    available: np.ndarray,
    load: np.ndarray,
    weights: np.ndarray,
    modeled_hours: float,
) -> float:
    """Thin wrapper: LOLE (h/yr) of an availability ensemble via ``compute_adequacy``.

    Args:
        available: (M, T) available generation (MW) per member/snapshot.
        load: (T,) demand (MW).
        weights: (T,) snapshot weight (h).
        modeled_hours: Total modelled window length (h), for annualising.

    Returns:
        Annualised loss-of-load expectation, hours/year.
    """
    return float(compute_adequacy(available, load, weights, modeled_hours=modeled_hours)["lole"])


def _elcc_for_carrier(
    available_without: np.ndarray,
    load: np.ndarray,
    weights: np.ndarray,
    modeled_hours: float,
    nameplate_mw: float,
    baseline_lole: float,
    *,
    tolerance_hours: float = _DEFAULT_TOLERANCE_HOURS,
    max_iters: int = _MAX_BISECTION_ITERS,
) -> float:
    """Bisect the firm MW block that restores baseline LOLE.

    Args:
        available_without: (M, T) system availability with the carrier's
            units removed.
        load: (T,) demand (MW).
        weights: (T,) snapshot weight (h).
        modeled_hours: Total modelled window length (h).
        nameplate_mw: Upper bracket for the firm block (the carrier's own
            nameplate capacity — a perfectly firm resource cannot be worth
            more than its own nameplate).
        baseline_lole: Full-system LOLE (h/yr) to match.
        tolerance_hours: Convergence tolerance on LOLE (h/yr).
        max_iters: Bisection iteration cap.

    Returns:
        ELCC in MW, clamped to ``[0, nameplate_mw]``.

    Algorithm:
        See module docstring. Bisection on F in [lo, hi] = [0, nameplate_mw].
        LOLE(without + F) is non-increasing in F (adding firm capacity never
        hurts reliability), so:
          - lole(0) <= baseline (removing the carrier didn't hurt reliability
            at all): ELCC is 0.
          - lole(nameplate_mw) > baseline (even the full nameplate, added
            firm, does not reach baseline — should not happen when the
            carrier's own presence achieved the baseline, but guarded):
            clamp to nameplate_mw.
          - otherwise: bisect on the BRACKET, not on "first F within
            tolerance". LOLE is a coarse step function of F (only moves when
            a member/snapshot crosses the shortfall threshold), so the first
            probed F whose LOLE happens to land within tolerance is not
            necessarily the *smallest* such F. Track `lo` (known
            under-firmed) and `hi` (known sufficient, within tolerance) each
            iteration by the sign of LOLE(mid) - baseline; `hi` converges to
            the minimal firm MW that restores baseline reliability, which is
            what "ELCC" means (the smallest firm-MW block giving equal
            reliability, not merely a sufficient one).
    """
    if nameplate_mw <= _EPS:
        return 0.0

    def lole_at(f: float) -> float:
        return _lole_of(available_without + f, load, weights, modeled_hours)

    lole_lo = lole_at(0.0)
    if lole_lo <= baseline_lole + tolerance_hours:
        # Removing the carrier didn't (meaningfully) worsen reliability — it
        # was never on the margin at scarcity snapshots. ELCC ~ 0.
        return 0.0

    lole_hi = lole_at(nameplate_mw)
    if lole_hi > baseline_lole + tolerance_hours:
        # Even a full-nameplate firm block doesn't fully recover baseline
        # reliability (can happen with the discrete, member-based LOLE
        # kernel near a tight tolerance) — clamp to nameplate rather than
        # searching outside the resource's own physical size.
        return float(nameplate_mw)

    # Bisect on the BRACKET width (not on "first F within tolerance"): LOLE is
    # a coarse step function of F (it only moves when a member/snapshot
    # crosses the shortfall threshold), so the first mid whose LOLE happens to
    # land within tolerance of baseline is not necessarily the smallest such
    # F — e.g. with a hard load threshold, any F past the gap gives LOLE=0,
    # and stopping at the first such mid overstates ELCC. Instead keep
    # narrowing [lo, hi] by the sign of (LOLE(mid) - baseline) every
    # iteration; `hi` is always a value known to reach baseline (within
    # tolerance) and `lo` is always known not to, so `hi` converges to the
    # minimal firm MW that restores baseline reliability. An early exit is
    # still safe once the bracket itself is tight relative to nameplate.
    lo, hi = 0.0, float(nameplate_mw)
    min_bracket = max(nameplate_mw * 1e-6, 1e-6)
    for _ in range(max_iters):
        mid = 0.5 * (lo + hi)
        lole_mid = lole_at(mid)
        if lole_mid > baseline_lole + tolerance_hours:
            # Still under-firmed relative to baseline reliability — need more F.
            lo = mid
        else:
            # At or below baseline (within tolerance) — F could be smaller;
            # hi tracks the tightest known "sufficient" F.
            hi = mid
        if (hi - lo) < min_bracket:
            break
    return float(np.clip(hi, 0.0, nameplate_mw))


def build_elcc(
    network: pypsa.Network,
    options: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Effective Load-Carrying Capability per carrier, post-process.

    Reads ``options["elccConfig"]``; returns ``None`` when the feature is
    disabled/absent, the network has no successful solve, there are no
    snapshots/loads, or there is no target carrier with nameplate capacity to
    evaluate.

    Args:
        network: solved ``pypsa.Network``.
        options: run options; reads the ``elccConfig`` block.

    Returns:
        The ``"elcc"`` payload dict (see the algorithm docs for the contract),
        or ``None``.
    """
    cfg = (options or {}).get("elccConfig") or {}
    if not bool(cfg.get("enabled")):
        return None
    if not getattr(network, "is_solved", False):
        return None

    snapshots = network.snapshots
    T = len(snapshots)
    if T == 0 or len(network.loads) == 0:
        return None

    n_members = int(cfg.get("nMembers", _DEFAULT_N_MEMBERS) or _DEFAULT_N_MEMBERS)
    seed = int(cfg.get("seed", _DEFAULT_SEED) if cfg.get("seed") is not None else _DEFAULT_SEED)
    for_fallback = float(
        cfg.get("forcedOutageRate", _DEFAULT_FOR) if cfg.get("forcedOutageRate") is not None else _DEFAULT_FOR
    )
    mttr_fallback = float(
        cfg.get("mttrHours", _DEFAULT_MTTR_HOURS) if cfg.get("mttrHours") is not None else _DEFAULT_MTTR_HOURS
    )
    if n_members <= 0:
        return None

    gens = network.generators
    if len(gens) == 0:
        return None

    pmax = network.get_switchable_as_dense("Generator", "p_max_pu")
    cap_col = "p_nom_opt" if "p_nom_opt" in gens.columns else "p_nom"

    # ── Classify generators: thermal (Markov-outage-sampled) vs variable
    # renewable (deterministic solved availability — same split as
    # outage_mc.build_outage_mc, with includeRenewableEnsemble omitted here:
    # ELCC studies the resource's OWN contribution against a fixed, realistic
    # backdrop, so renewables (other than the carrier under study) are held at
    # their solved availability rather than perturbed. ──────────────────────
    thermal_names: list[str] = []
    thermal_cap_list: list[float] = []
    thermal_for_list: list[float] = []
    thermal_mttr_list: list[float] = []
    thermal_carrier_list: list[str] = []

    renewable_names: list[str] = []
    renewable_caps: list[float] = []
    renewable_base_cf: list[np.ndarray] = []
    renewable_carrier_list: list[str] = []

    for g in gens.index:
        name = str(g)
        if name.startswith("load_shedding_"):
            continue
        carrier = str(gens.at[g, "carrier"]) if "carrier" in gens.columns else ""
        cap = float(gens.at[g, cap_col]) if cap_col in gens.columns else 0.0
        if cap <= 0:
            continue
        if _is_variable_renewable(carrier):
            renewable_names.append(name)
            renewable_caps.append(cap)
            renewable_base_cf.append(pmax[g].to_numpy())
            renewable_carrier_list.append(carrier)
            continue
        thermal_names.append(name)
        thermal_cap_list.append(cap)
        thermal_carrier_list.append(carrier)
        for_rate = for_fallback
        if "forced_outage_rate" in gens.columns:
            raw = gens.at[g, "forced_outage_rate"]
            if pd.notna(raw) and float(raw) > 0:
                for_rate = float(raw)
        mttr = mttr_fallback
        if "mean_time_to_repair" in gens.columns:
            raw = gens.at[g, "mean_time_to_repair"]
            if pd.notna(raw) and float(raw) > 0:
                mttr = float(raw)
        thermal_for_list.append(for_rate)
        thermal_mttr_list.append(mttr)

    # Storage units contribute discharge capacity to system adequacy exactly
    # like a generator in this post-process (state-of-charge-limited energy
    # constraints are a re-solve concern, out of scope here); modelled as
    # perfectly firm (no forced outage — mechanical/battery availability is
    # typically far higher than thermal FOR) at their solved p_max_pu.
    storage = network.storage_units
    storage_cap_col = "p_nom_opt" if "p_nom_opt" in storage.columns else "p_nom"
    storage_names: list[str] = []
    storage_caps: list[float] = []
    storage_carrier_list: list[str] = []
    storage_pmax_by_name: dict[str, np.ndarray] = {}
    if len(storage) > 0:
        storage_pmax = network.get_switchable_as_dense("StorageUnit", "p_max_pu")
        for s in storage.index:
            name = str(s)
            carrier = str(storage.at[s, "carrier"]) if "carrier" in storage.columns else ""
            cap = float(storage.at[s, storage_cap_col]) if storage_cap_col in storage.columns else 0.0
            if cap <= 0:
                continue
            storage_names.append(name)
            storage_caps.append(cap)
            storage_carrier_list.append(carrier)
            storage_pmax_by_name[name] = storage_pmax[s].to_numpy() if s in storage_pmax.columns else np.ones(T)

    all_carriers_present = sorted(
        set(thermal_carrier_list) | set(renewable_carrier_list) | set(storage_carrier_list)
    )
    if not all_carriers_present:
        return None

    requested_carriers = cfg.get("carriers")
    if requested_carriers:
        target_carriers = [c for c in requested_carriers if c in all_carriers_present]
    else:
        # Default: variable-renewable carriers present, plus storage carriers
        # if present. Evaluating a thermal carrier is allowed (via an explicit
        # `carriers` override) but is not the default target — its own
        # near-nameplate ELCC is not usually the headline question.
        target_carriers = sorted(
            set(renewable_carrier_list) | set(storage_carrier_list)
        )
    if not target_carriers:
        return None

    weights = network.snapshot_weightings["generators"].reindex(snapshots).fillna(1.0).to_numpy()
    load = network.get_switchable_as_dense("Load", "p_set").sum(axis=1).reindex(snapshots).fillna(0.0).to_numpy()
    modeled_hours = float(weights.sum())

    # ── Build the full-system availability ensemble (M, T), identical
    # construction to outage_mc.build_outage_mc: thermal units under a shared
    # Markov outage mask, renewables at solved (deterministic) availability. ──
    thermal_cap = np.asarray(thermal_cap_list, dtype=float)
    for_rates = np.asarray(thermal_for_list, dtype=float)
    mttr_hours = np.asarray(thermal_mttr_list, dtype=float)
    thermal_pmax = pmax.reindex(columns=thermal_names).to_numpy() if thermal_names else np.zeros((T, 0))

    if thermal_names:
        mask = sample_outage_masks(for_rates, mttr_hours, weights, n_members=n_members, seed=seed)  # (M, G, T)
        thermal_contrib = np.einsum("g,tg,mgt->mt", thermal_cap, thermal_pmax, mask)  # (M, T)
    else:
        thermal_contrib = np.zeros((n_members, T))

    renewable_contrib_by_carrier: dict[str, np.ndarray] = {}
    for name, cap, base, carrier in zip(renewable_names, renewable_caps, renewable_base_cf, renewable_carrier_list):
        contrib = cap * np.broadcast_to(base, (n_members, T))
        renewable_contrib_by_carrier.setdefault(carrier, np.zeros((n_members, T)))
        renewable_contrib_by_carrier[carrier] = renewable_contrib_by_carrier[carrier] + contrib

    storage_contrib_by_carrier: dict[str, np.ndarray] = {}
    for name, cap, carrier in zip(storage_names, storage_caps, storage_carrier_list):
        base = storage_pmax_by_name[name]
        contrib = cap * np.broadcast_to(base, (n_members, T))
        storage_contrib_by_carrier.setdefault(carrier, np.zeros((n_members, T)))
        storage_contrib_by_carrier[carrier] = storage_contrib_by_carrier[carrier] + contrib

    renewable_total = np.zeros((n_members, T))
    for contrib in renewable_contrib_by_carrier.values():
        renewable_total = renewable_total + contrib
    storage_total = np.zeros((n_members, T))
    for contrib in storage_contrib_by_carrier.values():
        storage_total = storage_total + contrib

    available_full = thermal_contrib + renewable_total + storage_total
    baseline_lole = _lole_of(available_full, load, weights, modeled_hours)

    # Per-carrier nameplate: thermal + renewable + storage members of that
    # carrier (a carrier may in principle span component types).
    thermal_cap_by_carrier: dict[str, float] = {}
    for cap, carrier in zip(thermal_cap_list, thermal_carrier_list):
        thermal_cap_by_carrier[carrier] = thermal_cap_by_carrier.get(carrier, 0.0) + cap
    renewable_cap_by_carrier: dict[str, float] = {}
    for cap, carrier in zip(renewable_caps, renewable_carrier_list):
        renewable_cap_by_carrier[carrier] = renewable_cap_by_carrier.get(carrier, 0.0) + cap
    storage_cap_by_carrier: dict[str, float] = {}
    for cap, carrier in zip(storage_caps, storage_carrier_list):
        storage_cap_by_carrier[carrier] = storage_cap_by_carrier.get(carrier, 0.0) + cap

    # Thermal contribution per carrier (needed only if a thermal carrier is an
    # explicit target); computed once, reused per carrier.
    thermal_contrib_by_carrier: dict[str, np.ndarray] = {}
    if thermal_names:
        for gi, carrier in enumerate(thermal_carrier_list):
            g_contrib = thermal_cap[gi] * thermal_pmax[:, gi][None, :] * mask[:, gi, :]  # (M, T)
            thermal_contrib_by_carrier.setdefault(carrier, np.zeros((n_members, T)))
            thermal_contrib_by_carrier[carrier] = thermal_contrib_by_carrier[carrier] + g_contrib

    by_carrier: list[dict[str, Any]] = []
    for carrier in target_carriers:
        nameplate = (
            thermal_cap_by_carrier.get(carrier, 0.0)
            + renewable_cap_by_carrier.get(carrier, 0.0)
            + storage_cap_by_carrier.get(carrier, 0.0)
        )
        if nameplate <= _EPS:
            continue
        contrib = np.zeros((n_members, T))
        if carrier in thermal_contrib_by_carrier:
            contrib = contrib + thermal_contrib_by_carrier[carrier]
        if carrier in renewable_contrib_by_carrier:
            contrib = contrib + renewable_contrib_by_carrier[carrier]
        if carrier in storage_contrib_by_carrier:
            contrib = contrib + storage_contrib_by_carrier[carrier]

        available_without = available_full - contrib
        elcc_mw = _elcc_for_carrier(
            available_without, load, weights, modeled_hours, nameplate, baseline_lole,
        )
        elcc_pct = 100.0 * elcc_mw / nameplate if nameplate > _EPS else 0.0
        by_carrier.append(
            {
                "carrier": carrier,
                "nameplateMw": round(nameplate, 2),
                "elccMw": round(elcc_mw, 2),
                "elccPct": round(elcc_pct, 2),
                "color": carrier_color(network, carrier),
            }
        )

    if not by_carrier:
        return None

    by_carrier.sort(key=lambda row: row["elccMw"], reverse=True)

    summary = [
        {
            "label": "Baseline LOLE",
            "value": f"{baseline_lole:,.2f} h/yr",
            "detail": f"full system, {n_members} outage-MC members, seed {seed}",
        },
    ]
    for row in by_carrier:
        summary.append(
            {
                "label": f"{row['carrier']} ELCC",
                "value": f"{row['elccMw']:,.1f} MW ({row['elccPct']:.1f}%)",
                "detail": f"nameplate {row['nameplateMw']:,.1f} MW",
            }
        )

    note = None
    if not thermal_names:
        note = (
            "No thermal generator was found to sample forced outages over — "
            "the reliability backdrop reflects only the modelled resources' "
            "own (renewable/storage) availability."
        )

    _log.info(
        "elcc: %d members, baseline LOLE=%.2f h/yr, %d carrier(s) evaluated: %s",
        n_members, baseline_lole, len(by_carrier),
        ", ".join(f"{r['carrier']}={r['elccPct']:.1f}%" for r in by_carrier),
    )

    return {
        "enabled": True,
        "nMembers": n_members,
        "seed": seed,
        "byCarrier": by_carrier,
        "baselineLoleHrs": round(baseline_lole, 3),
        "summary": summary,
        "note": note,
    }
