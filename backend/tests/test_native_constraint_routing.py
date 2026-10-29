"""Custom constraints PyPSA's ``GlobalConstraint`` expresses exactly are written as native rows.

Every routed kind is solved twice on the same small network: the old way (a declared linopy constraint, native
routing switched off) and the new way (a ``GlobalConstraint`` row written by the constraints hook). The objective
and the dual must agree: ``global_constraints.mu`` is the linopy dual of the same row (same sign, same unit).
Kinds PyPSA cannot express, and runs where the native row would differ (rolling, pathway, depleting storage),
must stay on the linopy path.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from backend.app import module_hooks as mh
from backend.app.constraints import hooks as chooks
from backend.app.constraints import native_routing
from backend.app.emissions.accounting import carrier_emission_factors
from backend.pypsa.network import build_network
from backend.pypsa.results.market import build_applied_constraints
from backend.tests.test_carrier_capacity_constraints import _exp_model
from backend.tests.test_custom_constraints import _flat_model

SCENARIO = {"discountRate": 0.0, "carbonPrice": 0.0}
OPTIONS = {"snapshotStart": 0, "snapshotCount": 6, "snapshotWeight": 1.0}
RTOL, ATOL = 1e-9, 1e-6


def _solve(model, *, constraints=None, specs=None, dsl="", native: bool, monkeypatch, options=None):
    """Build, let the constraints hook route (or not), solve; return (network, notes)."""
    if not native:
        monkeypatch.setattr(native_routing, "_native_spec", lambda n, cand: None)
    scenario = dict(SCENARIO, constraints=constraints or [], constraintSpecs=specs or [], customDsl=dsl)
    n, notes = build_network(model, scenario, options or OPTIONS)
    ctx = mh.RunContext(scenario=scenario, notes=notes, network=n, emissions_factors=carrier_emission_factors(n))
    extra = chooks._prepare(ctx)
    n.optimize(solver_name="highs", extra_functionality=extra)
    return n, notes


def _dual(n, name: str, *, native: bool) -> float:
    if native:
        return float(n.global_constraints.at[name, "mu"])
    return float(n.model.constraints[name].dual.values.squeeze())


def _both(model, name: str, monkeypatch, **kw):
    """Solve both ways; assert routing happened only in the native solve and that objective and dual agree."""
    old, _ = _solve(model, native=False, monkeypatch=monkeypatch, **kw)
    monkeypatch.undo()
    new, notes = _solve(model, native=True, monkeypatch=monkeypatch, **kw)
    assert name not in old.global_constraints.index
    assert name in new.global_constraints.index, notes
    assert name not in new.model.constraints  # the linopy row is not added a second time
    assert any("native GlobalConstraint" in t and name in t for t in notes)
    np.testing.assert_allclose(float(new.objective), float(old.objective), rtol=RTOL, atol=ATOL)
    d_old, d_new = _dual(old, name, native=False), _dual(new, name, native=True)
    np.testing.assert_allclose(abs(d_new), abs(d_old), rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(d_new, d_old, rtol=RTOL, atol=ATOL)  # same sign convention too
    return old, new, d_new


def _cc(metric: str, carrier: str, value: float) -> dict[str, Any]:
    return {"enabled": True, "metric": metric, "carrier": carrier, "value": value, "label": f"{metric}-{carrier}"}


def _spec(lhs, sense, rhs) -> dict[str, Any]:
    return {"lhs": lhs, "sense": sense, "rhs": rhs}


# ── operational_limit: carrier energy ────────────────────────────────────────
def test_carrier_max_gen(monkeypatch) -> None:
    # Gas (10/MWh) would serve 600 MWh; capped at 300 the backup (100/MWh) covers 300: dual = 10 - 100 = -90.
    _, new, dual = _both(_flat_model(), "cc_0_carrier_max_gen", monkeypatch,
                         constraints=[_cc("carrier_max_gen", "gas", 300.0)])
    assert dual == pytest.approx(-90.0, abs=1e-6)
    assert float(new.global_constraints.at["cc_0_carrier_max_gen", "constant"]) == 300.0
    assert new.global_constraints.at["cc_0_carrier_max_gen", "type"] == "operational_limit"


def test_carrier_min_gen(monkeypatch) -> None:
    # Forcing 200 MWh of the dear backup: each MWh costs 100 - 10 = 90 more, dual +90 (>= row, minimisation).
    _, _, dual = _both(_flat_model(), "cc_0_carrier_min_gen", monkeypatch,
                       constraints=[_cc("carrier_min_gen", "backup", 200.0)])
    assert dual == pytest.approx(90.0, abs=1e-6)


def test_max_load_shed(monkeypatch) -> None:
    # Shedding (50/MWh) is cheaper than the backup (100/MWh), so a 60 MWh shed cap binds: dual = 50 - 100 = -50.
    model = _flat_model()
    model["generators"][0]["p_nom"] = 50.0  # gas 50 MW of the 100 MW load
    _, new, dual = _both(model, "cc_0_max_load_shed", monkeypatch,
                         constraints=[{"enabled": True, "metric": "max_load_shed", "value": 60.0, "label": "shed"}],
                         options=dict(OPTIONS, enableLoadShedding=True, loadSheddingCost=50.0))
    assert dual == pytest.approx(-50.0, abs=1e-6)
    assert new.global_constraints.at["cc_0_max_load_shed", "carrier_attribute"] == "LoadShedding"


# ── tech_capacity_expansion_limit ────────────────────────────────────────────
def test_carrier_max_cap(monkeypatch) -> None:
    _, _, dual = _both(_exp_model(), "cc_0_carrier_max_cap", monkeypatch,
                       constraints=[_cc("carrier_max_cap", "wind", 50.0)])
    assert dual == pytest.approx(-590.0, abs=1e-6)


def test_carrier_min_cap(monkeypatch) -> None:
    _both(_exp_model(), "cc_0_carrier_min_cap", monkeypatch, constraints=[_cc("carrier_min_cap", "wind", 150.0)])


def test_carrier_cap_with_fixed_part_shifts_the_constant(monkeypatch) -> None:
    """PyPSA sums only EXTENDABLE capacity; the linopy row also counts fixed p_nom, so the bound drops by it."""
    model = _exp_model()
    model["generators"].append({"name": "G_wind_old", "bus": "b", "carrier": "wind", "p_nom": 20.0,
                                "marginal_cost": 0.0})
    _, new, _ = _both(model, "cc_0_carrier_max_cap", monkeypatch, constraints=[_cc("carrier_max_cap", "wind", 50.0)])
    assert float(new.global_constraints.at["cc_0_carrier_max_cap", "constant"]) == pytest.approx(30.0)
    assert float(new.generators.at["G_wind", "p_nom_opt"]) == pytest.approx(30.0, abs=1e-6)


# ── DSL / spec lines that reduce to one atom against a literal ────────────────
def _emitters():
    from backend.tests.test_constraint_specs import _two_carrier_model

    return _two_carrier_model()


def test_spec_gen_cap_native(monkeypatch) -> None:
    spec = _spec([{"coef": 1.0, "kind": "gen", "carrier": "coal"}], "<=", [{"coef": 50.0, "kind": "const"}])
    _both(_emitters(), "spec_1", monkeypatch, specs=[spec], options={})


def test_spec_normalised_forms_equal(monkeypatch) -> None:
    """``2*gen <= 100`` and ``50 >= gen`` are the same bound as ``gen <= 50`` once the atom is isolated."""
    two = _spec([{"coef": 2.0, "kind": "gen", "carrier": "coal"}], "<=", [{"coef": 100.0, "kind": "const"}])
    flipped = _spec([{"coef": 50.0, "kind": "const"}], ">=", [{"coef": 1.0, "kind": "gen", "carrier": "coal"}])
    neg = _spec([{"coef": -1.0, "kind": "gen", "carrier": "coal"}], ">=", [{"coef": -50.0, "kind": "const"}])
    for spec in (two, flipped, neg):
        cands = native_routing.spec_candidates([spec])
        assert [(c.atom, c.carrier, c.sense, c.rhs) for c in cands] == [("gen", "coal", "<=", 50.0)]


def test_dsl_emissions_cap_native(monkeypatch) -> None:
    # Coal 0.9 / gas 0.4 tCO2/MWh, 160 MWh of load: all coal is 144 t; capped at 100 t gas takes the rest.
    _, new, dual = _both(_emitters(), "dsl_1", monkeypatch, dsl="emissions <= 100", options={})
    assert new.global_constraints.at["dsl_1", "type"] == "primary_energy"
    assert dual == pytest.approx(-(30.0 - 10.0) / (0.9 - 0.4), abs=1e-6)  # 40 per tCO2


def test_dsl_emissions_cap_on_thermal_basis(monkeypatch) -> None:
    """Efficiency below 1: both paths count co2_emissions / efficiency per MWh of electricity."""
    model = _emitters()
    model["generators"][0]["efficiency"] = 0.45
    model["generators"][1]["efficiency"] = 0.55
    _, new, dual = _both(model, "dsl_1", monkeypatch, dsl="emissions <= 120", options={})
    assert abs(dual) > 1.0  # binds
    assert new.global_constraints.at["dsl_1", "carrier_attribute"] == "co2_emissions"


def test_time_varying_efficiency_keeps_emissions_on_linopy() -> None:
    n, _ = build_network(_emitters(), {"discountRate": 0.0}, {})
    n.generators_t.efficiency["c"] = 0.4
    cands = native_routing.dsl_candidates("emissions <= 100")
    assert native_routing.route_native(n, cands, []) == []


def test_dsl_load_shed_and_cap_lines(monkeypatch) -> None:
    model = _flat_model()
    model["generators"][0]["p_nom"] = 50.0
    _both(model, "dsl_1", monkeypatch, dsl="load_shed <= 60",
          options=dict(OPTIONS, enableLoadShedding=True, loadSheddingCost=50.0))
    _both(_exp_model(), "dsl_1", monkeypatch, dsl="cap(wind) <= 50")


# ── what must stay on the linopy path ────────────────────────────────────────
@pytest.mark.parametrize(
    "constraints, dsl",
    [
        ([_cc("co2_cap", "", 0.5)], ""),                       # intensity: a ratio, no GlobalConstraint type
        ([_cc("carrier_max_share", "gas", 40.0)], ""),         # share
        ([_cc("carrier_max_cf", "gas", 30.0)], ""),            # capacity factor
        ([], "gen(coal) + gen(gas) <= 100"),                   # several atoms
        ([], "gen(coal & gas) <= 100"),                        # several carriers
        ([], "gen <= 100"),                                    # all supply
        ([], "emissions(coal) <= 10"),                         # emissions of one carrier
        ([], "cf(coal) <= 0.5"),
    ],
)
def test_inexpressible_kinds_stay_linopy(monkeypatch, constraints, dsl) -> None:
    n, _ = _solve(_emitters(), constraints=constraints, dsl=dsl, native=True, monkeypatch=monkeypatch, options={})
    assert len(n.global_constraints) == 0
    assert native_routing.META_KEY not in n.meta


def test_rolling_run_keeps_linopy_path() -> None:
    """The linopy row apportions a whole-run budget per window; PyPSA applies the constant to each window."""
    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    cands = native_routing.structured_candidates([_cc("carrier_max_gen", "gas", 300.0)])
    assert native_routing.route_native(n, cands, [], rolling_enabled=True) == []
    assert native_routing.route_native(n, cands, [], stochastic_enabled=True) == []
    assert len(n.global_constraints) == 0
    assert len(native_routing.route_native(n, cands, [])) == 1


def test_depleting_storage_of_the_carrier_keeps_linopy_path() -> None:
    """PyPSA's operational_limit also counts a non-cyclic store's net depletion; the linopy row does not."""
    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    cands = native_routing.structured_candidates([_cc("carrier_max_gen", "gas", 300.0)])
    n.add("Store", "gas_store", bus="b", carrier="gas", e_nom=100.0, e_cyclic=False)
    assert native_routing.route_native(n, cands, []) == []
    n.stores.loc["gas_store", "e_cyclic"] = True
    assert len(native_routing.route_native(n, cands, [])) == 1


def test_extendable_link_of_the_carrier_keeps_cap_on_linopy() -> None:
    """tech_capacity_expansion_limit sums every extendable asset of the carrier, generators and others."""
    n, _ = build_network(_exp_model(), SCENARIO, OPTIONS)
    n.add("Bus", "b2")
    n.add("Link", "wind_link", bus0="b", bus1="b2", carrier="wind", p_nom_extendable=True)
    cands = native_routing.structured_candidates([_cc("carrier_max_cap", "wind", 50.0)])
    assert native_routing.route_native(n, cands, []) == []


def test_fixed_carrier_capacity_is_not_routed() -> None:
    n, _ = build_network(_flat_model(), SCENARIO, OPTIONS)
    cands = native_routing.structured_candidates([_cc("carrier_max_cap", "gas", 50.0)])
    assert native_routing.route_native(n, cands, []) == []  # nothing extendable: the linopy path notes the skip


# ── payload ──────────────────────────────────────────────────────────────────
def test_applied_constraints_reads_mu_with_the_same_sign(monkeypatch) -> None:
    cons = [_cc("carrier_max_gen", "gas", 300.0)]
    old, _ = _solve(_flat_model(), constraints=cons, native=False, monkeypatch=monkeypatch)
    monkeypatch.undo()
    new, _ = _solve(_flat_model(), constraints=cons, native=True, monkeypatch=monkeypatch)
    a_old = {c["name"]: c for c in build_applied_constraints(old)}
    a_new = {c["name"]: c for c in build_applied_constraints(new)}
    assert a_old["cc_0_carrier_max_gen"]["source"] == a_new["cc_0_carrier_max_gen"]["source"] == "custom"
    assert "native" not in a_old["cc_0_carrier_max_gen"] and a_new["cc_0_carrier_max_gen"]["native"] is True
    np.testing.assert_allclose(
        a_new["cc_0_carrier_max_gen"]["shadowPrice"], a_old["cc_0_carrier_max_gen"]["shadowPrice"], rtol=RTOL, atol=ATOL
    )
    assert a_new["cc_0_carrier_max_gen"]["shadowPrice"] == pytest.approx(-90.0, abs=1e-6)
    assert len(a_new) == len(a_old) == 1  # listed once, not as a native row and again as a linopy row
