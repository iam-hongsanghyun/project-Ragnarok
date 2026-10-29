"""Route the custom-constraint kinds PyPSA's ``GlobalConstraint`` expresses EXACTLY to native rows.

Ragnarok must not duplicate what PyPSA does natively. A user constraint that is, term for term, one of PyPSA's
global-constraint types is written at build time as an ``n.add("GlobalConstraint", ...)`` row (PyPSA builds the
LP row and stores the dual in ``n.global_constraints.mu``); every other kind keeps its declared linopy
constraint (:mod:`.custom_constraints`, :mod:`.constraint_dsl`).

What maps (each check below makes "exactly" concrete; any doubt keeps the linopy path, so no feasible set changes):

================================  =======================================  =====================================
user constraint                   native ``GlobalConstraint``              exact when
================================  =======================================  =====================================
``carrier_max/min_gen`` (MWh),    ``operational_limit``                    the constraint's generators are ALL
DSL ``gen(C) <op> K``             ``carrier_attribute = C``                generators of carrier C (all active)
                                                                           and no non-cyclic storage unit / store
                                                                           carries C (PyPSA adds their net
                                                                           depletion)
``max_load_shed`` (MWh),          ``operational_limit`` on the shedding    the shedding generators are all the
DSL ``load_shed <op> K``          carrier                                  generators of that carrier (same rule)
``carrier_max/min_cap`` (MW),     ``tech_capacity_expansion_limit``        no extendable line / link / store /
DSL ``cap(C) <op> K``             ``constant = K - fixed p_nom of C``      storage unit / transformer has carrier
                                                                           C (PyPSA sums every extendable asset)
                                                                           and at least one generator of C is
                                                                           extendable (else nothing to bind)
DSL ``emissions <op> K``          ``primary_energy`` on                    same emitting generators, static
                                  ``co2_emissions``                        efficiency above the floor, no
                                                                           non-cyclic storage emitting, no
                                                                           piecewise efficiency
================================  =======================================  =====================================

Always required: a single-period, single-scenario, non-rolling run. PyPSA weights ``primary_energy`` /
``operational_limit`` by the investment-period ``years`` (the linopy path does not), refuses
``tech_capacity_expansion_limit`` with scenarios, and applies the constant unchanged to every rolling window
(the linopy path apportions it by the window's hour-share); in those runs the linopy path is the exact one.

Not routable (PyPSA has no such type): the CO2 *intensity* cap, shares, capacity factors and capacity shares
(ratios), multi-term / multi-carrier / column-selector DSL lines, ``gen`` / ``cap`` over all supply.

Dual: ``n.global_constraints.mu`` equals the linopy dual of the same row (same sign, same unit: currency per
MWh, per MW, per tCO2): :func:`backend.pypsa.results.market.build_applied_constraints` reads it from there.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pypsa

from backend.app.emissions.accounting import _MIN_EFFICIENCY, carrier_emission_factors
from backend.pypsa.utils.shedding import shed_carrier, shedding_names

from .constraint_dsl import DslParseError, ParsedConstraint, _spec_to_parsed, parse_line

_log = logging.getLogger(__name__)

#: ``network.meta`` key holding the routed rows (JSON-serialisable list of dicts).
META_KEY = "ragnarok_native_constraints"

_GEN_METRICS = {"carrier_max_gen": "<=", "carrier_min_gen": ">="}
_CAP_METRICS = {"carrier_max_cap": "<=", "carrier_min_cap": ">="}
_FLIP = {"<=": ">=", ">=": "<=", "==": "=="}
_ENERGY_UNIT = {"gen": "MWh", "load_shed": "MWh", "cap": "MW", "emissions": "tCO2"}


@dataclass(frozen=True)
class Candidate:
    """A user constraint reduced to ``atom(carrier) <sense> rhs`` (one atom, literal bound)."""

    source: str          # "cc" (structured) | "spec" | "dsl"
    key: int             # list index (cc), 1-based spec number (spec) or line number (dsl)
    name: str            # the linopy constraint name it would have had; also the GlobalConstraint name
    label: str
    atom: str            # gen | load_shed | cap | emissions
    carrier: str | None  # None for load_shed / emissions
    sense: str
    rhs: float
    shed_excluded: bool  # DSL atoms drop shedding generators; structured carrier kinds do not


# ── Candidate extraction ─────────────────────────────────────────────────────
def _finite(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def structured_candidates(constraints: list[dict[str, Any]]) -> list[Candidate]:
    """Candidates among ``scenario.constraints`` (enabled rows of a routable metric)."""
    out: list[Candidate] = []
    for i, c in enumerate(constraints or []):
        if not c.get("enabled", False):
            continue
        metric = str(c.get("metric", ""))
        value = _finite(c.get("value", 0))
        if value is None:
            continue
        carrier = str(c.get("carrier", ""))
        label = str(c.get("label", metric))
        name = f"cc_{i}_{metric}"
        if metric in _GEN_METRICS and carrier:
            out.append(Candidate("cc", i, name, label, "gen", carrier, _GEN_METRICS[metric], value, False))
        elif metric in _CAP_METRICS and carrier:
            out.append(Candidate("cc", i, name, label, "cap", carrier, _CAP_METRICS[metric], value, False))
        elif metric == "max_load_shed":
            out.append(Candidate("cc", i, name, label, "load_shed", None, "<=", value, False))
    return out


def _single_carrier(term: Any) -> str | None:
    """The one carrier a DSL selector names, or None (several values, other column, bare)."""
    if term.values is not None:
        if (term.column or "carrier") == "carrier" and len(term.values) == 1:
            return str(term.values[0])
        return None
    return None if term.carrier is None else str(term.carrier)


def parsed_candidate(pc: ParsedConstraint, source: str, key: int, name: str) -> Candidate | None:
    """``coef*atom + c  <op>  c'`` with exactly one routable atom becomes ``atom <op'> K``; anything else None."""
    if any(t.kind == "cf" for t in (*pc.lhs, *pc.rhs)):
        return None
    atoms = [(side, t) for side, terms in (("l", pc.lhs), ("r", pc.rhs)) for t in terms if t.kind != "const"]
    if len(atoms) != 1:
        return None
    side, atom = atoms[0]
    if atom.coef == 0.0 or not math.isfinite(atom.coef):
        return None
    c_l = sum(t.coef for t in pc.lhs if t.kind == "const")
    c_r = sum(t.coef for t in pc.rhs if t.kind == "const")
    # coef*atom <op> K  (atom on the left)  or  coef*atom <flipped op> K  (atom on the right)
    sense, bound = (pc.sense, c_r - c_l) if side == "l" else (_FLIP[pc.sense], c_l - c_r)
    rhs = bound / atom.coef
    if atom.coef < 0:
        sense = _FLIP[sense]
    if not math.isfinite(rhs):
        return None
    carrier = _single_carrier(atom)
    if atom.kind in ("gen", "cap"):
        if carrier is None:
            return None
    elif atom.kind == "load_shed":
        carrier = None
    elif atom.kind == "emissions":
        if atom.values is not None or atom.carrier is not None:
            return None
        carrier = None
    else:
        return None
    return Candidate(source, key, name, pc.raw, atom.kind, carrier, sense, rhs, True)


def spec_candidates(specs: list[dict[str, Any]]) -> list[Candidate]:
    out: list[Candidate] = []
    for idx, spec in enumerate(specs or [], start=1):
        try:
            pc = _spec_to_parsed(spec, idx)
        except (DslParseError, ValueError, TypeError, AttributeError):
            continue  # the linopy path reports it
        cand = parsed_candidate(pc, "spec", idx, f"spec_{idx}")
        if cand is not None:
            out.append(cand)
    return out


def dsl_candidates(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    for n0, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            pc = parse_line(line, n0)
        except DslParseError:
            continue
        cand = parsed_candidate(pc, "dsl", n0, f"dsl_{n0}")
        if cand is not None:
            out.append(cand)
    return out


# ── Exactness checks ─────────────────────────────────────────────────────────
def _plain_run(n: pypsa.Network, rolling_enabled: bool, stochastic_enabled: bool) -> bool:
    """Single period, single scenario, no rolling windows (see the module docstring)."""
    return not (
        rolling_enabled
        or stochastic_enabled
        or n.has_scenarios
        or len(n.investment_periods) > 0
    )


def _effective_carrier(static: pd.DataFrame, buses: pd.DataFrame) -> pd.Series:
    """Carrier as PyPSA's ``create_model`` sees it: a blank carrier takes its bus's carrier."""
    if "carrier" not in static.columns or static.empty:
        return pd.Series("", index=static.index, dtype=object)
    car = static["carrier"].astype(str)
    if "bus" in static.columns and "carrier" in buses.columns:
        bus_car = static["bus"].map(buses["carrier"]).fillna("").astype(str)
        car = car.where(car != "", bus_car)
    return car


def _depleting_storage_with(n: pypsa.Network, carriers: set[str]) -> bool:
    """Non-cyclic storage units / stores of these carriers: PyPSA's limits add their net depletion."""
    sus = n.storage_units
    if len(sus) and "cyclic_state_of_charge" in sus.columns:
        eff = _effective_carrier(sus, n.buses)
        if bool((eff.isin(carriers) & ~sus["cyclic_state_of_charge"].astype(bool)).any()):
            return True
    stores = n.stores
    if len(stores) and "e_cyclic" in stores.columns:
        eff = _effective_carrier(stores, n.buses)
        if bool((eff.isin(carriers) & ~stores["e_cyclic"].astype(bool)).any()):
            return True
    return False


def _all_active(gens: pd.DataFrame) -> bool:
    return bool(gens["active"].astype(bool).all()) if "active" in gens.columns and len(gens) else True


def _carrier_gens(n: pypsa.Network, carrier: str) -> list[str]:
    return n.generators.index[n.generators.carrier.astype(str) == carrier].tolist()


def _ours_gens(n: pypsa.Network, cand: Candidate) -> list[str]:
    """Generators the linopy path would sum for this candidate's atom."""
    shed = set(shedding_names(n.generators))
    if cand.atom == "load_shed":
        return sorted(shed)
    gens = _carrier_gens(n, str(cand.carrier))
    return [g for g in gens if g not in shed] if cand.shed_excluded else gens


def _native_spec(n: pypsa.Network, cand: Candidate) -> dict[str, Any] | None:
    """``GlobalConstraint`` kwargs equal to ``cand``, or None when PyPSA's row would not be the same row."""
    if cand.atom in ("gen", "load_shed"):
        carrier = shed_carrier() if cand.atom == "load_shed" else str(cand.carrier)
        ours = _ours_gens(n, cand)
        native = _carrier_gens(n, carrier)
        if not ours or sorted(ours) != sorted(native):
            return None
        if not _all_active(n.generators.loc[native]) or _depleting_storage_with(n, {carrier}):
            return None
        return {"type": "operational_limit", "carrier_attribute": carrier, "sense": cand.sense, "constant": cand.rhs}

    if cand.atom == "cap":
        carrier = str(cand.carrier)
        gens = n.generators
        ours = _ours_gens(n, cand)
        native = _carrier_gens(n, carrier)
        if not ours or sorted(ours) != sorted(native):
            return None
        ext_col = "p_nom_extendable"
        ext = [g for g in native if ext_col in gens.columns and bool(gens.at[g, ext_col])]
        if not ext:
            return None  # fixed capacity: nothing to bind (the linopy path notes the skip)
        if not _all_active(gens.loc[native]):
            return None
        for comp in ("Line", "Link", "Transformer", "Store", "StorageUnit"):
            c = n.components[comp]
            static = c.static
            if static.empty or "carrier" not in static.columns:
                continue
            eff = _effective_carrier(static, n.buses)
            if bool(eff.loc[eff.index.intersection(c.extendables)].astype(str).eq(carrier).any()):
                return None
        fixed = [g for g in native if g not in ext]
        fixed_mw = float(gens.loc[fixed, "p_nom"].fillna(0.0).sum()) if fixed else 0.0
        return {
            "type": "tech_capacity_expansion_limit",
            "carrier_attribute": carrier,
            "sense": cand.sense,
            "constant": cand.rhs - fixed_mw,
        }

    if cand.atom == "emissions":
        if "co2_emissions" not in n.carriers.columns:
            return None
        factors = carrier_emission_factors(n)
        gens = n.generators
        shed = set(shedding_names(gens))
        gen_factor = gens["carrier"].astype(str).map(lambda c: float(factors.get(c, 0.0) or 0.0))
        native_set = set(gens.index[gen_factor != 0.0])
        ours_set = {g for g in gens.index[gen_factor > 0.0] if g not in shed}
        if not ours_set or native_set != ours_set:
            return None
        emitting_carriers = {c for c, f in factors.items() if f and float(f) != 0.0}
        if _depleting_storage_with(n, {str(c) for c in emitting_carriers}):
            return None
        eta = pd.to_numeric(gens.loc[sorted(native_set), "efficiency"], errors="coerce") if "efficiency" in gens.columns else None
        if eta is None or bool((eta.isna() | (eta <= _MIN_EFFICIENCY)).any()):
            return None
        eff_t = getattr(n.generators_t, "efficiency", None)
        if eff_t is not None and len(eff_t.columns.intersection(list(native_set))):
            return None
        try:
            if n.components["Generator"].has_piecewise("efficiency"):
                return None
        except Exception:  # noqa: BLE001 - unknown PyPSA internals: keep the linopy path
            return None
        return {"type": "primary_energy", "carrier_attribute": "co2_emissions", "sense": cand.sense, "constant": cand.rhs}
    return None


def _note_prefix(cand: Candidate) -> str:
    """Same lead-in as the linopy path's own note, so a run's notes read alike either way."""
    if cand.source == "spec":
        return f"Constraint spec {cand.key}: '{cand.label}'"
    if cand.source == "dsl":
        return f"DSL line {cand.key}: '{cand.label}'"
    return f"Constraint '{cand.label}':"


# ── Build step ───────────────────────────────────────────────────────────────
def route_native(
    n: pypsa.Network,
    candidates: list[Candidate],
    notes: list[str],
    *,
    rolling_enabled: bool = False,
    stochastic_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Write every exactly-expressible candidate as a ``GlobalConstraint`` row; return what was routed.

    The returned records (also stored in ``n.meta[META_KEY]``) tell the linopy path which constraints to skip.
    Never raises: a candidate that cannot be proven exact stays on the linopy path.
    """
    routed: list[dict[str, Any]] = []
    if not candidates or not _plain_run(n, rolling_enabled, stochastic_enabled):
        return routed
    for cand in candidates:
        if cand.name in n.global_constraints.index:
            continue
        try:
            spec = _native_spec(n, cand)
        except Exception as exc:  # noqa: BLE001 - the linopy path is always a safe fallback
            _log.debug("native routing of %s skipped: %s", cand.name, exc)
            spec = None
        if spec is None:
            continue
        n.add("GlobalConstraint", cand.name, **spec)
        record = {"name": cand.name, "source": cand.source, "key": cand.key, "label": cand.label,
                  "type": spec["type"], "carrier_attribute": spec["carrier_attribute"],
                  "sense": spec["sense"], "constant": float(spec["constant"])}
        routed.append(record)
        shift = ""
        if spec["type"] == "tech_capacity_expansion_limit" and spec["constant"] != cand.rhs:
            shift = f" (bound {cand.rhs:.6g} MW less {cand.rhs - spec['constant']:.6g} MW of fixed capacity)"
        notes.append(
            f"{_note_prefix(cand)} added as native GlobalConstraint '{cand.name}' "
            f"({spec['type']}, carrier_attribute={spec['carrier_attribute']}, {spec['sense']} "
            f"{spec['constant']:.6g} {_ENERGY_UNIT[cand.atom]}){shift}; its dual is global_constraints.mu."
        )
    if routed:
        n.meta[META_KEY] = routed
    return routed


def routed_keys(n: pypsa.Network, source: str) -> frozenset[int]:
    """Keys (list index / spec number / DSL line) of ``source`` already routed to native rows on ``n``."""
    records = n.meta.get(META_KEY) if isinstance(n.meta, dict) else None
    return frozenset(int(r["key"]) for r in (records or []) if r.get("source") == source)
