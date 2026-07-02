"""X1 parity gate — derived-from-outputs analytics must equal the fresh solve.

``derive_results_from_outputs(model, outputs)`` reconstructs a solved network
from a run's stored outputs and reassembles the payload through the SAME code
path as ``run_pypsa``. So for any solved run:

    run_pypsa(model)  ->  payload P (with P["outputs"])
    derive(model, P["outputs"])  ->  payload D

must give D == P on every derived field (narrative/solve-notes excepted).
A mismatch means output attachment lost or distorted information — exactly the
silent corruption this suite exists to catch.
"""
from __future__ import annotations

import math
from typing import Any

import pytest

from backend.pypsa.results import run_pypsa
from backend.pypsa.results.derive_outputs import derive_results_from_outputs

SCENARIO = {"carbonPrice": 25.0, "discountRate": 0.05}
OPTIONS = {"currencySymbol": "$", "ownerColumn": "owner"}

# Every payload field that must survive the round trip exactly. Excluded:
# narrative (solve vs derive notes legitimately differ), outputs (identity in →
# rebuilt out; compared separately), statistics (pypsa n.statistics table is
# solver-metadata sensitive), nearOptimal/merchant/… (config-gated, None here).
PARITY_FIELDS = [
    "summary", "dispatchSeries", "curtailmentSeries", "generatorDispatchSeries",
    "systemPriceSeries", "systemEmissionsSeries", "storageSeries",
    "storageSocSeries", "nodalPriceSeries", "carrierMix", "generatorEnergy",
    "costBreakdown", "nodalBalance", "lineLoading", "expansionResults",
    "meritOrder", "co2Shadow", "appliedConstraints", "generatorEconomics",
    "emissionsBreakdown", "energyBalance", "companies", "companyFinance",
    "companyStatement", "adequacy", "priceFormation", "commitment", "runMeta",
]


def _approx_equal(a: Any, b: Any, path: str = "") -> None:
    """Deep equality with float tolerance; pinpoints the diverging path."""
    if isinstance(a, float) or isinstance(b, float):
        af, bf = float(a), float(b)
        assert math.isclose(af, bf, rel_tol=1e-6, abs_tol=1e-6), f"{path}: {af} != {bf}"
        return
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys(), f"{path}: keys {sorted(a)} != {sorted(b)}"
        for k in a:
            _approx_equal(a[k], b[k], f"{path}.{k}")
        return
    if isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f"{path}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _approx_equal(x, y, f"{path}[{i}]")
        return
    assert a == b, f"{path}: {a!r} != {b!r}"


def _dispatch_model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
    load = [80, 140, 200, 120, 90, 160]
    wind = [0.5, 0.3, 0.6, 0.4, 0.7, 0.2]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.4}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom": 300,
             "marginal_cost": 60, "owner": "GasCo"},
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom": 120,
             "marginal_cost": 0, "owner": "WindCo"},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind1": w} for s, w in zip(snaps, wind)],
    }


def _storage_model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
    load = [40, 40, 120, 120, 60, 60]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 60}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "cheap", "bus": "b", "carrier": "gas", "p_nom": 80, "marginal_cost": 20},
            {"name": "peak", "bus": "b", "carrier": "gas", "p_nom": 100, "marginal_cost": 200},
        ],
        "storage_units": [
            {"name": "batt", "bus": "b", "carrier": "gas", "p_nom": 30, "max_hours": 4,
             "efficiency_store": 0.95, "efficiency_dispatch": 0.95,
             "cyclic_state_of_charge": True},
        ],
    }


def _expansion_model() -> dict[str, list[dict[str, Any]]]:
    snaps = [f"2030-01-01T{h:02d}:00:00" for h in range(6)]
    load = [100, 120, 150, 200, 180, 140]
    wind = [0.6, 0.5, 0.4, 0.3, 0.5, 0.7]
    return {
        "buses": [{"name": "b"}],
        "carriers": [{"name": "gas"}, {"name": "wind"}],
        "snapshots": [{"snapshot": s} for s in snaps],
        "loads": [{"name": "L", "bus": "b", "p_set": 100}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(snaps, load)],
        "generators": [
            {"name": "wind1", "bus": "b", "carrier": "wind", "p_nom_extendable": True,
             "capital_cost": 90, "marginal_cost": 0, "lifetime": 1},
            {"name": "gas1", "bus": "b", "carrier": "gas", "p_nom_extendable": True,
             "capital_cost": 40, "marginal_cost": 70, "lifetime": 1},
        ],
        "generators-p_max_pu": [{"snapshot": s, "wind1": w} for s, w in zip(snaps, wind)],
    }


CASES = [
    ("dispatch", _dispatch_model),
    ("storage", _storage_model),
    ("expansion", _expansion_model),
]


@pytest.mark.parametrize("name,factory", CASES, ids=[c[0] for c in CASES])
def test_derive_equals_fresh_solve(name: str, factory) -> None:
    model = factory()
    fresh = run_pypsa(model, SCENARIO, dict(OPTIONS))
    derived = derive_results_from_outputs(model, fresh["outputs"], SCENARIO, dict(OPTIONS))
    for field in PARITY_FIELDS:
        _approx_equal(derived.get(field), fresh.get(field), f"{name}.{field}")
    # The rebuilt outputs must round-trip the attached series too.
    _approx_equal(
        derived["outputs"]["series"].get("generators-p"),
        fresh["outputs"]["series"].get("generators-p"),
        f"{name}.outputs.generators-p",
    )


def test_derive_notes_flag_no_resolve() -> None:
    model = _dispatch_model()
    fresh = run_pypsa(model, SCENARIO, dict(OPTIONS))
    derived = derive_results_from_outputs(model, fresh["outputs"], SCENARIO, dict(OPTIONS))
    assert any("re-derived server-side" in n for n in derived["narrative"])


def test_derive_rejects_pathway_outputs() -> None:
    outputs = {"series": {"generators-p": [{"period": 2030, "snapshot": "2030-01-01T00:00:00", "g": 1.0}]},
               "static": {}}
    with pytest.raises(ValueError, match="Multi-period"):
        derive_results_from_outputs(_dispatch_model(), outputs, SCENARIO, dict(OPTIONS))


def test_derive_rejects_empty_outputs() -> None:
    with pytest.raises(ValueError, match="no dispatch series"):
        derive_results_from_outputs(_dispatch_model(), {"series": {}, "static": {}}, SCENARIO, {})


# ── Import wiring: a bare (reconstructed) workbook arrives with analytics ────

def test_bare_workbook_import_gets_server_derived_analytics() -> None:
    from backend.app import project_workbook as pw

    model = _dispatch_model()
    fresh = run_pypsa(model, SCENARIO, dict(OPTIONS))
    bundle = {"model": model, "scenario": dict(SCENARIO), "options": dict(OPTIONS), "result": fresh}
    # A bare workbook (no embedded bundle) forces the sheet-reconstruction path,
    # which historically returned NO derived analytics (client re-derived).
    data = pw.bundle_to_workbook(bundle, include_bundle=False)
    imported = pw.import_bundle_from_upload(data, "demo.xlsx")
    result = imported["result"]
    assert result.get("summary"), "server-side derivation should fill summary"
    assert result.get("carrierMix"), "carrierMix filled"
    # KPI labels match the fresh solve (values can shift via sheet round-trip
    # precision, so pin the structure + the exact carrier mix labels).
    assert [s["label"] for s in result["summary"]] == [s["label"] for s in fresh["summary"]]
    assert [c["label"] for c in result["carrierMix"]] == [c["label"] for c in fresh["carrierMix"]]


def test_fill_derived_analytics_leaves_pathway_bundles_untouched() -> None:
    from backend.app.project_workbook import _fill_derived_analytics

    bundle = {
        "model": _dispatch_model(),
        "scenario": {}, "options": {},
        "result": {"outputs": {"series": {"generators-p": [
            {"period": 2030, "snapshot": "2030-01-01T00:00:00", "gas1": 1.0},
        ]}, "static": {}}},
    }
    out = _fill_derived_analytics(bundle)
    assert "summary" not in out["result"]  # derivation skipped, client will derive


def test_fill_derived_analytics_respects_existing_summary() -> None:
    from backend.app.project_workbook import _fill_derived_analytics

    sentinel = [{"label": "Existing", "value": "1", "detail": ""}]
    bundle = {"model": {}, "scenario": {}, "options": {},
              "result": {"summary": sentinel, "outputs": {"series": {"x-y": [{"snapshot": "s"}]}, "static": {}}}}
    assert _fill_derived_analytics(bundle)["result"]["summary"] is sentinel
