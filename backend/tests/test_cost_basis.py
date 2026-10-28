"""Cost basis: Ragnarok hands cost columns to PyPSA unchanged (workbook schema 2).

* ``capital_cost``   - PyPSA's periodised cost per modelled horizon, passed through;
* ``overnight_cost`` - annuitised by PyPSA: ``overnight x annuity(r, L) x n.nyears``;
* ``fom_cost``       - added per horizon, unscaled.

Step 0 (urgent bugs D20 / D17 / D18 / D19) and step 1 (the cost basis itself, the one-off
workbook migration and the stored-run compatibility). The three audited objectives are pinned
through the REAL migrate -> build -> optimize path, from workbooks written BEFORE the change
(``fixtures/legacy_cost_basis``) and from the regenerated bundled examples.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi import HTTPException
from pypsa.costs import annuity

from backend.app import sqlite_store
from backend.pypsa.network import build_components, build_network, build_stored_network
from backend.pypsa.network import cost_basis as cb

HERE = Path(__file__).resolve().parent
LEGACY = HERE / "fixtures" / "legacy_cost_basis"
EXAMPLES = HERE.parent / "data" / "examples"
OPTIONS = {"enableLoadShedding": False, "currencySymbol": "$"}
SCENARIO = {"carbonPrice": 0.0, "discountRate": 0.05}

# The audited objectives (HiGHS, include_objective_constant=False), identical before and after the change.
OBJECTIVE_CAPACITY_EXPANSION = 1_194_599.2343849267   # audited 1,194,599.23
OBJECTIVE_M17_STORE = 948_727.7335611486           # audited 948,727.73
OBJECTIVE_M16_PATHWAY = 626_611_133.6484756         # audited 626,611,133.65
OLD_ANALYTICS = json.loads((HERE / "fixtures" / "legacy_cost_basis" / "old_analytics.json").read_text())


# ── helpers ───────────────────────────────────────────────────────────────────────

def _raw_model(db: Path) -> dict[str, list[dict[str, Any]]]:
    """Every sheet of a project.db exactly as stored, with NO migration applied (opened read-only: the
    bundled example files must not be touched, not even to switch their journal mode)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = json.loads(conn.execute("SELECT v FROM _kv WHERE k = 'meta'").fetchone()[0])
        tables = json.loads(conn.execute("SELECT v FROM _kv WHERE k = 'tables'").fetchone()[0])
        return {
            str(e["name"]): [json.loads(r[0]) for r in conn.execute(f"SELECT d FROM {tables[e['name']]} ORDER BY __row")]
            for e in meta["sheets"]
        }
    finally:
        conn.close()


def _session_with(db: Path, tmp_path: Path, session: str = "s") -> Path:
    dest = tmp_path / session
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db, dest / "project.db")
    return tmp_path


class _Sessions:
    """Point the session store at ``root`` for the duration of a ``with``."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def __enter__(self) -> None:
        self.old = sqlite_store.ss.SESSION_DIR
        sqlite_store.ss.SESSION_DIR = self.root

    def __exit__(self, *exc: object) -> None:
        sqlite_store.ss.SESSION_DIR = self.old


def _load(db: Path, tmp_path: Path) -> dict[str, list[dict[str, Any]]]:
    """A project.db read through the real loader (which migrates a pre-schema-2 db)."""
    with _Sessions(_session_with(db, tmp_path)):
        model = sqlite_store.load_full_model("s")
    assert model is not None
    return model


def _m16_options() -> dict[str, Any]:
    weights = {2030: 8.1078, 2040: 4.9775, 2050: 3.0558}
    return {**OPTIONS, "pathwayConfig": {
        "enabled": True, "planningMode": "pathway", "snapshotMappingMode": "explicit_period_column",
        "periods": [{"period": p, "objectiveWeight": w, "yearsWeight": 10.0} for p, w in weights.items()],
    }}


def _solve(model: dict, options: dict | None = None, *, pathway: bool = False) -> pypsa.Network:
    n, _ = build_network(model, SCENARIO, options or OPTIONS)
    n.optimize(solver_name="highs", include_objective_constant=False, **({"multi_investment_periods": True} if pathway else {}))
    return n


def _gen_model(extra: dict | None = None, hours: int = 24, **gen: Any) -> dict[str, list[dict[str, Any]]]:
    """One bus, a flat 100 MW load, an extendable wind-like unit and a gas backstop."""
    snaps = pd.date_range("2030-01-01", periods=hours, freq="h")
    wind = {"name": "w", "bus": "b", "carrier": "wind", "p_nom_extendable": True, "marginal_cost": 0.0, **gen}
    model = {
        "buses": [{"name": "b", "carrier": "AC"}],
        "carriers": [{"name": "AC"}, {"name": "wind"}, {"name": "gas"}],
        "snapshots": [{"snapshot": s.isoformat()} for s in snaps],
        "loads": [{"name": "l", "bus": "b", "p_set": 100.0}],
        "generators": [wind, {"name": "gas", "bus": "b", "carrier": "gas", "p_nom": 500.0, "marginal_cost": 200.0}],
        "generators-p_max_pu": [{"snapshot": s.isoformat(), "w": 0.5} for s in snaps],
    }
    model.update(extra or {})
    return model


# ═══ Step 0: urgent bugs ═══════════════════════════════════════════════════════════

def test_d20_a_transform_build_does_not_leak_run_time_conversions_into_the_workbook() -> None:
    """The reduced workbook is the user's model: no e_sum scaling, no carbon adder, no annuity, no window."""
    from backend.pypsa import network_ops

    model = _gen_model(capital_cost=1000.0)
    model["generators"][1]["e_sum_max"] = 1000.0
    model["carriers"][2]["co2_emissions"] = 0.2
    model["generators"][1]["marginal_cost"] = 10.0
    scenario = {"discountRate": 0.05, "carbonPrice": 50.0}
    network = network_ops._build(model, scenario, {})
    reduced = network_ops._to_model(network, model)
    gas = next(g for g in reduced["generators"] if g["name"] == "gas")
    wind = next(g for g in reduced["generators"] if g["name"] == "w")
    assert gas["e_sum_max"] == 1000.0            # was 2.7397 (24 h / 8760 h)
    assert gas["marginal_cost"] == 10.0          # was 20 (carbon adder 50 x 0.2)
    assert wind["capital_cost"] == 1000.0        # was 0.2198 (annuitised and window-scaled)
    assert wind.get("overnight_cost") in (None, "") or pd.isna(wind["overnight_cost"])
    assert len(reduced["snapshots"]) == 24
    assert not any(str(g["name"]).startswith("load_shedding") for g in reduced["generators"])


def test_d20_build_components_snaps_no_placeholder_and_keeps_v_ang_min() -> None:
    model = _gen_model()
    model["generators"][0]["p_nom_max"] = 1e12
    n, _ = build_components(model, {})
    assert float(n.generators.at["w", "p_nom_max"]) == 1e12
    n2, _ = build_network(model, SCENARIO, OPTIONS)
    assert float(n2.generators.at["w", "p_nom_max"]) == 1e12         # D13: the run no longer snaps it; the Forge action does


def test_d20_netcdf_export_is_one_to_one() -> None:
    """The export builds with build_components: the costs and the e_sum caps are the workbook's own."""
    from backend.app.main import _model_payload_to_network
    from backend.app.models import RunPayload

    model = _gen_model(capital_cost=1000.0)
    model["generators"][1]["e_sum_max"] = 1000.0
    payload = RunPayload(model=model, scenario={"discountRate": 0.05, "carbonPrice": 40.0}, options={"snapshotCount": 4})
    n = _model_payload_to_network(payload)
    assert float(n.generators.at["w", "capital_cost"]) == 1000.0     # not the overnight value, not annuitised
    assert float(n.generators.at["gas", "e_sum_max"]) == 1000.0      # no hand-undone scaling needed
    assert len(n.snapshots) == 24


def test_d17_an_imported_extendable_pypsa_network_resolves_to_the_same_objective(tmp_path: Path) -> None:
    """A PyPSA file's capital_cost is already per horizon; the session must not annuitise it a second time."""
    from backend.app.main import _network_to_model_json, _read_network_file

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2030-01-01", periods=48, freq="h"))
    n.add("Bus", "b")
    n.add("Load", "l", bus="b", p_set=np.full(48, 100.0))
    n.add("Generator", "w", bus="b", p_nom_extendable=True, capital_cost=3_000.0, marginal_cost=1.0,
          p_max_pu=np.r_[np.full(24, 0.9), np.full(24, 0.2)])
    n.add("Generator", "gas", bus="b", p_nom=300.0, marginal_cost=120.0)
    n.optimize(solver_name="highs", include_objective_constant=False)
    expected = float(n.objective)
    path = tmp_path / "case.nc"
    n.export_to_netcdf(str(path))

    model = _network_to_model_json(_read_network_file(path.read_bytes(), "case.nc"))
    assert next(g for g in model["generators"] if g["name"] == "w")["capital_cost"] == 3_000.0
    again, _ = build_network(model, {}, OPTIONS)
    again.optimize(solver_name="highs", include_objective_constant=False)
    assert float(again.objective) == pytest.approx(expected, rel=1e-9)


def test_d18_deriving_a_network_from_outputs_invents_no_discount_rate() -> None:
    """A current-basis run is rebuilt as stored: its capital_cost is not annuitised with a made-up 5 %."""
    from backend.pypsa.results.statistics_query import network_from_outputs

    model = cb.stamp(_gen_model(capital_cost=3_000.0))
    n = network_from_outputs(model, {}, {}, {"static": {}, "series": {}})
    assert float(n.generators.at["w", "capital_cost"]) == 3_000.0


def test_d19_pathway_weights_are_read_from_the_model_or_refused() -> None:
    from backend.pypsa.results.derive_outputs import _pathway_options

    outputs = {"series": {"generators-p": [{"snapshot": "2030-01-01T00:00", "period": 2030, "g": 1.0},
                                           {"snapshot": "2040-01-01T00:00", "period": 2040, "g": 1.0}]}}
    with pytest.raises(ValueError, match="no stored investment-period weights"):
        _pathway_options({}, outputs, {})
    model = {"RAGNAROK_PathwayPeriods": [
        {"period": 2030, "objectiveWeight": 8.1078, "yearsWeight": 10},
        {"period": 2040, "objectiveWeight": 4.9775, "yearsWeight": 10},
    ]}
    cfg = _pathway_options({}, outputs, model)
    assert [(p["period"], p["objectiveWeight"], p["yearsWeight"]) for p in cfg["periods"]] == [
        (2030, 8.1078, 10.0), (2040, 4.9775, 10.0)]
    # ... and an explicit pathwayConfig in the options still wins
    given = {"enabled": True, "periods": [{"period": 2030, "objectiveWeight": 2.0, "yearsWeight": 5}]}
    assert _pathway_options({"pathwayConfig": given}, outputs, {}) is given


# ═══ Step 1: cost basis to PyPSA semantics ═══════════════════════════════════════════

def test_capital_cost_passes_through_unchanged_whatever_the_window() -> None:
    """D1/D2: no annuity, no window pro-rating, no meta key."""
    for hours in (24, 168):
        n, notes = build_network(_gen_model(hours=hours, capital_cost=1234.0, lifetime=20.0), SCENARIO, OPTIONS)
        assert float(n.generators.at["w", "capital_cost"]) == 1234.0
        assert "ragnarok_capex_window_scale" not in n.meta
        assert not any("nnuali" in note for note in notes)


def test_objective_charges_capital_cost_per_horizon_as_is() -> None:
    """A flat 100 MW load, wind at 0.5, gas at 200: wind is built to 200 MW; capital is capital_cost x 200."""
    n = _solve(_gen_model(hours=24, capital_cost=500.0, p_nom_max=200.0))
    assert float(n.generators.at["w", "p_nom_opt"]) == pytest.approx(200.0)
    assert float(n.objective) == pytest.approx(500.0 * 200.0, rel=1e-9)          # no gas, no scaling


@pytest.mark.parametrize("hours,life,rate", [(24, 20.0, 0.05), (168, 25.0, 0.07), (8760, 15.0, 0.0)])
def test_overnight_cost_is_annuitised_by_pypsa_and_scaled_by_nyears(hours: int, life: float, rate: float) -> None:
    n = _solve(_gen_model(hours=hours, overnight_cost=1_000_000.0, discount_rate=rate, lifetime=life, p_nom_max=200.0))
    expected = 1_000_000.0 * float(annuity(rate, life)) * (hours / 8760.0) * 200.0
    assert float(n.objective) == pytest.approx(expected, rel=1e-9)
    assert float(n.nyears) == pytest.approx(hours / 8760.0)


def test_fom_cost_is_added_per_horizon_unscaled() -> None:
    n = _solve(_gen_model(hours=24, overnight_cost=1_000_000.0, discount_rate=0.05, lifetime=20.0, fom_cost=300.0, p_nom_max=200.0))
    capex = 1_000_000.0 * float(annuity(0.05, 20.0)) * (24 / 8760.0)
    assert float(n.objective) == pytest.approx((capex + 300.0) * 200.0, rel=1e-9)


def test_d4_an_overnight_row_without_discount_rate_is_refused_not_filled_in() -> None:
    model = _gen_model(overnight_cost=1_000_000.0, lifetime=20.0)
    with pytest.raises(HTTPException) as err:
        build_network(model, SCENARIO, OPTIONS)         # a scenario discountRate must NOT rescue it
    assert err.value.status_code == 400
    assert "discount_rate" in err.value.detail and "Fill discount rate" in err.value.detail
    assert "w" in err.value.detail


def test_d4_forge_fill_discount_rate_writes_the_column_visibly() -> None:
    from backend.app import forge_helpers as fh

    model = {"generators": [{"name": "a", "overnight_cost": 100.0}, {"name": "b", "overnight_cost": 50.0, "discount_rate": 0.1},
                            {"name": "c", "capital_cost": 7.0}]}
    out = fh.fill_discount_rate(model, 0.05)
    assert out["filled"] == 1 and out["skipped"] == 1
    rows = {r["name"]: r for r in out["sheets"]["generators"]}
    assert rows["a"]["discount_rate"] == 0.05 and rows["b"]["discount_rate"] == 0.1 and "discount_rate" not in rows["c"]
    assert fh.fill_discount_rate(model, 0.05, overwrite=True)["overwritten"] == 1
    with pytest.raises(ValueError, match="fraction"):
        fh.fill_discount_rate(model, 5.0)


def test_d5_a_piecewise_capital_curve_is_passed_through_unscaled() -> None:
    model = _gen_model(extra=None)
    model["generators"][0].update({"p_nom_extendable": True, "p_nom_max": 400.0})
    model["generators-capital_cost-pw"] = [{"name": "w", "x": 0.0, "y": 0.0}, {"name": "w", "x": 200.0, "y": 900.0},
                                           {"name": "w", "x": 400.0, "y": 1100.0}]
    n, _ = build_network(model, SCENARIO, OPTIONS)
    frame = n.components.generators.piecewise["capital_cost"]
    assert sorted(frame[("w", "capital_cost")].tolist()) == [0.0, 900.0, 1100.0]


def test_the_expansion_rows_come_from_statistics_and_label_sunk_versus_expanded() -> None:
    from backend.pypsa.results import run_pypsa

    model = _gen_model(hours=168, overnight_cost=1_000_000.0, discount_rate=0.05, lifetime=20.0, p_nom=50.0, p_nom_max=200.0)
    res = run_pypsa(model, SCENARIO, OPTIONS)
    row = next(r for r in res["expansionResults"] if r["name"] == "w")
    nyears = 168 / 8760.0
    per_mw = 1_000_000.0 * float(annuity(0.05, 20.0)) * nyears
    assert row["nyears"] == pytest.approx(nyears, rel=1e-4)
    assert row["capital_cost"] == pytest.approx(per_mw, abs=0.005)                    # PyPSA's periodised cost per MW
    assert row["capex_horizon"] == pytest.approx(per_mw * row["p_nom_opt_mw"], rel=1e-4)
    assert row["capex_annual"] == pytest.approx(row["capex_horizon"] / nyears, rel=1e-4)   # the one conversion: per year
    assert row["capex_installed"] == pytest.approx(per_mw * 50.0, rel=1e-4)            # sunk part of the extendable unit
    assert row["capex_installed"] + row["capex_expanded"] == pytest.approx(row["capex_horizon"], rel=1e-4)
    assert row["overnight_total"] == pytest.approx(1_000_000.0 * row["p_nom_opt_mw"], rel=1e-6)
    capital = next(c for c in res["costBreakdown"] if c["label"].startswith("Capital cost"))
    assert capital["value"] == pytest.approx(row["capex_horizon"], abs=1.0)


def test_a_fixed_asset_with_an_overnight_cost_is_reported_as_sunk_capex() -> None:
    from backend.pypsa.results import run_pypsa

    model = _gen_model(hours=168)
    model["generators"][1].update({"overnight_cost": 800_000.0, "discount_rate": 0.05, "lifetime": 30.0})
    res = run_pypsa(model, SCENARIO, OPTIONS)
    ge = next(g for g in res["generatorEconomics"]["generators"] if g["name"] == "gas")
    assert ge["fixedCostHorizon"] == pytest.approx(800_000.0 * float(annuity(0.05, 30.0)) * (168 / 8760.0) * 500.0, rel=1e-6)
    assert ge["fixedCostAnnual"] == pytest.approx(ge["fixedCostHorizon"] / (168 / 8760.0), rel=1e-6)


# ═══ The migration ═══════════════════════════════════════════════════════════════════

def _legacy_model() -> dict[str, list[dict[str, Any]]]:
    return {
        "generators": [
            {"name": "ext", "p_nom_extendable": True, "capital_cost": 1000.0, "lifetime": float("inf")},
            {"name": "ext2", "p_nom_extendable": "TRUE", "capital_cost": 2000.0, "lifetime": 30},
            {"name": "fixed", "p_nom_extendable": False, "capital_cost": 500.0, "lifetime": 40},
            {"name": "free", "p_nom_extendable": True, "capital_cost": 0},
            {"name": "native", "p_nom_extendable": True, "overnight_cost": 9.0, "discount_rate": 0.03, "capital_cost": 5.0},
        ],
        "transformers": [{"name": "tr", "s_nom_extendable": True, "capital_cost": 77.0}],
        "RAGNAROK_Scenarios": [],
    }


def test_migration_moves_overnight_prices_to_overnight_cost() -> None:
    out, report = cb.migrate_cost_basis(_legacy_model(), discount_rate=0.05)
    rows = {r["name"]: r for r in out["generators"]}
    assert (rows["ext"]["overnight_cost"], rows["ext"]["capital_cost"], rows["ext"]["discount_rate"], rows["ext"]["lifetime"]) == (1000.0, 0, 0.05, 20.0)
    assert (rows["ext2"]["overnight_cost"], rows["ext2"]["lifetime"]) == (2000.0, 30)                 # a finite life is kept
    assert rows["fixed"]["overnight_cost"] == 500.0 and rows["fixed"]["lifetime"] == 40                # fixed rows move too
    assert "overnight_cost" not in rows["free"] and rows["free"]["capital_cost"] == 0                   # nothing to move
    assert rows["native"]["overnight_cost"] == 9.0 and rows["native"]["capital_cost"] == 5.0 and rows["native"]["discount_rate"] == 0.03
    assert out["transformers"][0]["capital_cost"] == 77.0                                              # never converted by the old builder
    assert cb.schema_version(out) == cb.CURRENT_SCHEMA_VERSION and report.migrated
    assert [r["name"] for r in report.changed_rows] == ["ext", "ext2", "fixed"]
    assert report.changed_rows[0]["lifetimeDefaulted"] is True and report.changed_rows[2]["extendable"] is False


def test_migration_leaves_the_fixed_assets_lifetime_alone_and_is_idempotent() -> None:
    model = {"generators": [{"name": "old", "p_nom": 10.0, "capital_cost": 5.0}], "RAGNAROK_Scenarios": []}
    out, _ = cb.migrate_cost_basis(model, discount_rate=0.05)
    assert "lifetime" not in out["generators"][0]                  # inf would be a 20 y retirement in a pathway
    again, report = cb.migrate_cost_basis(out, discount_rate=0.5)
    assert again == out and not report.migrated and not report.changed_rows


def test_migration_input_is_not_mutated_and_pypsa_files_are_only_stamped() -> None:
    model = _legacy_model()
    snapshot = json.dumps(model, sort_keys=True, default=str)
    cb.migrate_cost_basis(model, discount_rate=0.05)
    assert json.dumps(model, sort_keys=True, default=str) == snapshot
    out, report = cb.migrate_cost_basis(model, pypsa_native=True)
    assert out["generators"] == model["generators"] and cb.schema_version(out) == cb.CURRENT_SCHEMA_VERSION and not report.changed_rows


def test_migration_flags_piecewise_capital_curves_instead_of_guessing() -> None:
    model = {"generators": [{"name": "g", "p_nom_extendable": True, "capital_cost": 100.0}],
             "generators-capital_cost-pw": [{"name": "g", "x": 0, "y": 0}, {"name": "g", "x": 10, "y": 90}]}
    out, report = cb.migrate_cost_basis(model, discount_rate=0.05)
    assert out["generators"][0]["capital_cost"] == 100.0 and "overnight_cost" not in out["generators"][0]
    assert report.review and report.review[0]["name"] == "g" and "piecewise" in report.review[0]["reason"]


def test_migration_retargets_saved_scenario_overrides_of_capital_cost() -> None:
    """A preset's modelOverrides on capital_cost were overnight prices; on a migrated row they must set overnight_cost."""
    model = {
        "generators": [{"name": "a", "p_nom_extendable": True, "capital_cost": 100.0}, {"name": "b", "p_nom_extendable": True, "capital_cost": 0}],
        "RAGNAROK_Scenarios": [{"id": "s", "label": "cheap wind", "active": True, "json": json.dumps({"modelOverrides": [
            {"sheet": "generators", "name": "a", "column": "capital_cost", "value": 50.0},
            {"sheet": "generators", "name": "b", "column": "capital_cost", "value": 70.0},
            {"sheet": "generators", "name": "a", "column": "p_nom", "value": 1.0}]})}],
    }
    out, report = cb.migrate_cost_basis(model, discount_rate=0.06)
    overrides = json.loads(out["RAGNAROK_Scenarios"][0]["json"])["modelOverrides"]
    assert [(o["name"], o["column"]) for o in overrides] == [
        ("a", "overnight_cost"), ("b", "overnight_cost"), ("a", "p_nom"), ("b", "discount_rate")]
    assert overrides[-1]["value"] == 0.06                       # the unmigrated row b gets the project rate with its override
    assert any(r["name"] == "b" for r in report.review) and any("scenario override" in n for n in report.notes)
    assert json.loads(model["RAGNAROK_Scenarios"][0]["json"])["modelOverrides"][0]["column"] == "capital_cost"   # input untouched


def test_migration_discount_rate_source_is_stated() -> None:
    _, explicit = cb.migrate_cost_basis(_legacy_model(), discount_rate=0.07)
    assert (explicit.discount_rate, "setting" in explicit.discount_rate_source) == (0.07, True)
    _, fallback = cb.migrate_cost_basis(_legacy_model())
    assert fallback.discount_rate == 0.05 and "default" in fallback.discount_rate_source
    settings = {**_legacy_model(), "RAGNAROK_Settings": [{"key": "discountRate", "value": 0.08}]}
    assert cb.migrate_cost_basis(settings)[1].discount_rate == 0.08


def test_the_session_loader_migrates_an_old_project_db_once_and_reports_it(tmp_path: Path) -> None:
    root = _session_with(LEGACY / "capacity_expansion" / "project.db", tmp_path)
    with _Sessions(root):
        meta = sqlite_store.get_meta("s")
        assert any(s["name"] == cb.SCHEMA_SHEET for s in meta["sheets"])
        model = sqlite_store.load_full_model("s")
        gen = {g["name"]: g for g in model["generators"]}
        assert gen["wind"]["overnight_cost"] == 90_000.0 and gen["wind"]["capital_cost"] == 0
        assert gen["wind"]["lifetime"] == 20.0 and gen["wind"]["discount_rate"] == 0.05
        report = sqlite_store.get_cost_basis_migration("s")
        assert {r["name"] for r in report["changedRows"]} == {"gas", "solar", "wind"}
        assert sqlite_store.acknowledge_cost_basis_migration("s") is True
        assert sqlite_store.get_cost_basis_migration("s") is None            # shown once
        assert sqlite_store.get_cost_basis_migration("s", include_acknowledged=True) is not None
        before = sqlite_store.load_full_model("s")
    with _Sessions(root):
        assert sqlite_store.load_full_model("s") == before                    # a second read changes nothing


def test_save_model_stamps_native_models_and_migrates_only_a_declared_old_workbook(tmp_path: Path) -> None:
    root = tmp_path
    with _Sessions(root):
        native = {"buses": [{"name": "b"}], "generators": [{"name": "g", "bus": "b", "p_nom_extendable": True, "capital_cost": 42.0}]}
        sqlite_store.save_model("a", native)
        saved = sqlite_store.load_full_model("a")
        assert saved["generators"][0]["capital_cost"] == 42.0 and cb.schema_version(saved) == cb.CURRENT_SCHEMA_VERSION
        assert sqlite_store.get_cost_basis_migration("a") is None
        meta = sqlite_store.save_model("b", native, legacy_origin=True, discount_rate=0.06)
        assert meta["costBasisMigration"]["discountRate"] == 0.06
        migrated = sqlite_store.load_full_model("b")["generators"][0]
        assert migrated["overnight_cost"] == 42.0 and migrated["discount_rate"] == 0.06 and migrated["lifetime"] == 20.0


def test_a_project_workbook_round_trip_keeps_the_schema_stamp() -> None:
    from backend.app import project_workbook

    model = cb.stamp({"generators": [{"name": "g", "overnight_cost": 1.0, "discount_rate": 0.05}]})
    data = project_workbook.bundle_to_workbook({"model": model, "scenario": {}, "options": {}, "result": {}})
    bundle = project_workbook.workbook_to_bundle(data, "p.xlsx")
    assert cb.schema_version(bundle["model"]) == cb.CURRENT_SCHEMA_VERSION


# ═══ The audited objectives, through migrate -> build -> optimize ═════════════════════

def test_regression_capacity_expansion_objective_and_fleet(tmp_path: Path) -> None:
    for db in (LEGACY / "capacity_expansion" / "project.db", EXAMPLES / "capacity_expansion" / "project.db"):
        n = _solve(_load(db, tmp_path / db.parent.parent.name))
        assert float(n.objective) == pytest.approx(OBJECTIVE_CAPACITY_EXPANSION, rel=1e-9)
        assert float(n.generators.at["gas", "p_nom_opt"]) == pytest.approx(543.06, abs=0.01)
        assert float(n.generators.at["solar", "p_nom_opt"]) == pytest.approx(796.87, abs=0.01)
        assert float(n.generators.at["wind", "p_nom_opt"]) == pytest.approx(4947.84, abs=0.01)


def test_regression_m17_store_objective(tmp_path: Path) -> None:
    for db in (LEGACY / "training_m17_store" / "project.db", EXAMPLES / "training_m17_store" / "project.db"):
        n = _solve(_load(db, tmp_path / db.parent.parent.name))
        assert float(n.objective) == pytest.approx(OBJECTIVE_M17_STORE, rel=1e-9)


def test_regression_m16_pathway_objective(tmp_path: Path) -> None:
    for db in (LEGACY / "training_m16" / "project.db", EXAMPLES / "training_m16" / "project.db"):
        n = _solve(_load(db, tmp_path / db.parent.parent.name), _m16_options(), pathway=True)
        assert float(n.objective) == pytest.approx(OBJECTIVE_M16_PATHWAY, rel=1e-9)


def test_the_regenerated_examples_are_on_the_new_basis_and_stamped(tmp_path: Path) -> None:
    for ex in ("capacity_expansion", "training_m7", "training_m16", "training_m16_start", "training_m17_store"):
        raw = _raw_model(EXAMPLES / ex / "project.db")
        assert cb.schema_version(raw) == cb.CURRENT_SCHEMA_VERSION, ex
        for sheet in ("generators", "storage_units", "stores", "lines", "links"):
            for row in raw.get(sheet, []):
                if row.get("overnight_cost") not in (None, ""):
                    assert row.get("capital_cost") in (None, "", 0, 0.0), (ex, sheet, row["name"])
                    assert row.get("discount_rate") not in (None, ""), (ex, sheet, row["name"])
    for ex in sorted(p.name for p in EXAMPLES.iterdir()):
        for sheet, rows in _raw_model(EXAMPLES / ex / "project.db").items():
            if sheet in ("generators", "storage_units", "stores", "lines", "links", "processes", "transformers"):
                assert all(r.get("capital_cost") in (None, "", 0, 0.0) for r in rows), (ex, sheet)


# ═══ Stored runs ═══════════════════════════════════════════════════════════════════

def test_stored_run_without_a_stamp_rederives_its_old_numbers(tmp_path: Path) -> None:
    """An old run (overnight capital_cost in its stored model, no buildVersion) is re-derived through the
    in-memory migration, at the run's own discount rate: its analytics are the ones it was solved with."""
    from backend.pypsa.results import run_pypsa
    from backend.pypsa.results.derive_outputs import derive_results_from_outputs

    legacy_model = _raw_model(LEGACY / "capacity_expansion" / "project.db")
    assert cb.schema_version(legacy_model) is None
    fresh = run_pypsa(_load(LEGACY / "capacity_expansion" / "project.db", tmp_path), SCENARIO, OPTIONS)
    derived = derive_results_from_outputs(legacy_model, fresh["outputs"], SCENARIO, OPTIONS)

    old = OLD_ANALYTICS["capacity_expansion"]
    for row in derived["expansionResults"]:
        want = next(r for r in old["expansion"] if r["name"] == row["name"])
        assert row["p_nom_opt_mw"] == pytest.approx(want["p_nom_opt_mw"], abs=0.05)
        assert row["capex_annual"] == pytest.approx(want["capex_annual"], rel=1e-6)          # the old per-year figure
    capital = next(c for c in derived["costBreakdown"] if c["label"].startswith("Capital cost"))
    assert capital["value"] == pytest.approx(old["capitalLine"][0]["value"], abs=1.0)
    for g in derived["generatorEconomics"]["generators"]:
        want = next(x for x in old["geFixed"] if x["name"] == g["name"])
        assert g["fixedCostAnnual"] == pytest.approx(want["fixedCostAnnual"], rel=1e-6)
        assert g["fixedCostHorizon"] == pytest.approx(want["fixedCostHorizon"], abs=1.0)
    assert derived["generatorEconomics"]["system"]["fixedCostHorizon"] == pytest.approx(old["geSystem"]["fixedCostHorizon"], abs=2.0)
    # the fresh solve (which stamps new runs) and the re-derived old run agree on every figure
    assert [r["capex_annual"] for r in fresh["expansionResults"]] == [r["capex_annual"] for r in derived["expansionResults"]]


def test_stored_pathway_run_without_a_stamp_rederives_its_old_numbers(tmp_path: Path) -> None:
    from backend.pypsa.results import run_pypsa
    from backend.pypsa.results.derive_outputs import derive_results_from_outputs

    legacy_model = _raw_model(LEGACY / "training_m16" / "project.db")
    options = _m16_options()
    fresh = run_pypsa(_load(LEGACY / "training_m16" / "project.db", tmp_path), SCENARIO, options)
    derived = derive_results_from_outputs(legacy_model, fresh["outputs"], SCENARIO, options)
    old = OLD_ANALYTICS["training_m16"]
    got = {r["name"]: r for r in derived["expansionResults"]}
    for want in old["expansion"]:
        assert got[want["name"]]["capex_annual"] == pytest.approx(want["capex_annual"], rel=1e-6)
        assert got[want["name"]]["capex_weighted"] == pytest.approx(want["capex_weighted"], rel=1e-6)
    capital = next(c for c in derived["costBreakdown"] if c["label"].startswith("Capital cost"))
    assert capital["value"] == pytest.approx(old["capitalLine"][0]["value"], rel=1e-7)


def test_a_stamped_run_is_not_migrated_and_a_new_run_is_stamped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model = _gen_model(capital_cost=3000.0)
    current, report = cb.model_for_stored_run(model, SCENARIO, {"buildVersion": 2})
    assert current is model and report is None
    legacy, report = cb.model_for_stored_run(model, {"discountRate": 0.07}, {})
    assert legacy["generators"][0]["overnight_cost"] == 3000.0 and report.discount_rate == 0.07
    n, notes = build_stored_network(model, SCENARIO, {"buildVersion": 2})
    assert float(n.generators.at["w", "capital_cost"]) == 3000.0

    from backend.app import run_store

    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    meta = run_store.store_run(_gen_model(), SCENARIO, {}, {"summary": []})
    assert meta is not None
    stored = run_store.get_run(meta["name"]) if hasattr(run_store, "get_run") else None
    if stored is not None:
        assert stored["options"]["buildVersion"] == cb.CURRENT_SCHEMA_VERSION


def test_run_options_reference_no_longer_documents_skip_capex_annuitisation() -> None:
    from backend.app import run_options_reference as ref

    assert "options.skipCapexAnnuitisation" not in ref.documented_paths()
    assert "options.buildVersion" in ref.documented_paths()


# ═══ Module templates write PyPSA's own columns ═════════════════════════════════════════

def test_conversion_template_writes_overnight_fom_lifetime_and_rate_with_capital_cost_blank() -> None:
    from backend.app import forge_helpers as fh

    model = {"buses": [{"name": "elec", "carrier": "AC"}], "carriers": [{"name": "AC"}], "generators": [], "links": [],
             "snapshots": [{"snapshot": f"2030-01-01T{h:02d}:00"} for h in range(24)]}
    link = fh.build_conversion_fragment(
        fh.get_template("heat_pump"), anchor_bus="elec", p_nom=0, extendable=True, name=None, model=model, discount_rate=0.06,
    )["sheets"]["links"][0]
    assert link["overnight_cost"] == 60000 and link["discount_rate"] == 0.06 and link["lifetime"] == 20
    assert "capital_cost" not in link and link["fom_cost"] == 0.0
    with pytest.raises(ValueError, match="discount rate"):
        fh.build_conversion_fragment(fh.get_template("heat_pump"), anchor_bus="elec", p_nom=0, extendable=True, name=None, model=model)


def test_plant_fom_cost_is_written_per_horizon_with_the_conversion_visible() -> None:
    from backend.app.plants import catalog

    snaps = [{"snapshot": f"2030-01-01T{h:02d}:00", "objective": 365.0} for h in range(24)]       # 24 x 365 h = one year
    model = {"buses": [{"name": "b", "carrier": "AC"}], "carriers": [{"name": "AC"}], "snapshots": snaps}
    one_year = catalog.build_plant("bess", {"extendable": True, "pNomMax": 100.0, "discountRate": 0.05}, model)
    row = one_year["fragment"]["sheets"]["storage_units"][0]
    half = [{**s, "objective": 365.0 / 2} for s in snaps]
    half_year = catalog.build_plant("bess", {"extendable": True, "pNomMax": 100.0, "discountRate": 0.05}, {**model, "snapshots": half})
    row_half = half_year["fragment"]["sheets"]["storage_units"][0]
    assert cb.horizon_years({"snapshots": snaps}) == pytest.approx(24 * 365.0 / 8760.0)
    assert row["fom_cost"] > 0 and row_half["fom_cost"] == pytest.approx(row["fom_cost"] / 2, rel=1e-6)
    assert any("per modelled HORIZON" in w for w in one_year["warnings"])
    assert "capital_cost" not in row or row["capital_cost"] in (None, "", 0)


def test_p2x_and_plant_results_read_pypsas_fom_unscaled() -> None:
    """The stored run's fom_cost is charged per horizon by PyPSA: capacity x fom_cost, not x window years."""
    from backend.app.p2x.results import _Run

    net = pypsa.Network()
    net.set_snapshots(pd.date_range("2030-01-01", periods=24, freq="h"))
    net.add("Bus", "b")
    net.add("Generator", "g", bus="b", p_nom_extendable=True, overnight_cost=1e6, discount_rate=0.05, lifetime=20, fom_cost=250.0)
    run = _Run.__new__(_Run)
    run._network = net
    run.window_share = 1.0
    assert run.effective_fom("generators", "g") == 250.0


# ═══ The server entry points ═══════════════════════════════════════════════════════════

@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from backend.app import main, run_store, session_store

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(run_store, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("RAGNAROK_DATA_DIR", str(tmp_path / "data"))
    return TestClient(main.app)


def test_import_project_load_migrates_an_old_project_at_its_own_rate(client) -> None:
    from backend.app import project_workbook

    old_model = _legacy_model()
    old_model["snapshots"] = [{"snapshot": "2030-01-01T00:00:00"}]
    data = project_workbook.bundle_to_workbook(
        {"model": old_model, "scenario": {"discountRate": 0.07}, "options": {}, "result": {}}, include_meta=True
    )
    resp = client.post("/api/import/project/load", files={"file": ("old.xlsx", data, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["costBasisMigration"]["discountRate"] == 0.07
    rows = {r["name"]: r for r in body["model"]["generators"]}
    assert rows["ext"]["overnight_cost"] == 1000 and rows["ext"]["discount_rate"] == 0.07 and rows["ext"]["lifetime"] == 20
    assert cb.schema_version(body["model"]) == cb.CURRENT_SCHEMA_VERSION


def test_promoting_an_old_stored_run_migrates_it_at_the_runs_discount_rate(client) -> None:
    from backend.app import run_store

    model = {"buses": [{"name": "b"}], "generators": [{"name": "g", "bus": "b", "p_nom_extendable": True, "capital_cost": 42.0}]}
    meta = run_store.store_run(model, {"discountRate": 0.06}, {}, {"summary": []}, origin="xlsx_import")
    assert meta is not None
    out = client.post(f"/api/runs/{meta['name']}/promote", json={"sessionId": "promo"}).json()
    assert out["meta"]["costBasisMigration"]["discountRate"] == 0.06
    page = client.get("/api/session/sheet/generators", params={"session_id": "promo"}).json()
    row = page["rows"][0]
    assert row["overnight_cost"] == 42.0 and row["capital_cost"] == 0 and row["discount_rate"] == 0.06
    meta_back = client.get("/api/session/meta", params={"session_id": "promo"}).json()
    assert meta_back["costBasisMigration"]["changedRows"][0]["name"] == "g"
    assert client.post("/api/session/migration/ack", params={"session_id": "promo"}).json() == {"acknowledged": True}
    assert "costBasisMigration" not in client.get("/api/session/meta", params={"session_id": "promo"}).json()


def test_put_model_with_origin_legacy_uses_the_workbooks_own_rate_over_the_apps(client) -> None:
    legacy = {"buses": [{"name": "b"}], "generators": [{"name": "g", "bus": "b", "p_nom_extendable": True, "capital_cost": 5.0}]}
    model = {**legacy, "RAGNAROK_Settings": [{"key": "discountRate", "value": 0.08}]}
    meta = client.post("/api/session/model", json={"model": model, "sessionId": "p", "origin": "legacy", "discountRate": 0.05}).json()
    assert meta["costBasisMigration"]["discountRate"] == 0.08
    plain = client.post("/api/session/model", json={"model": legacy, "sessionId": "q"}).json()
    assert "costBasisMigration" not in plain          # no origin: a native model, stamped and left alone


def test_fill_discount_rate_endpoint_preview_then_apply(client) -> None:
    model = {"buses": [{"name": "b"}], "generators": [{"name": "g", "bus": "b", "overnight_cost": 10.0, "lifetime": 20}]}
    client.post("/api/session/model", json={"model": model, "sessionId": "f"})
    preview = client.post("/api/forge/fill-discount-rate", json={"sessionId": "f", "discountRate": 0.05}).json()
    assert preview["filled"] == 1 and preview["applied"] is False
    assert "discount_rate" not in client.get("/api/session/sheet/generators", params={"session_id": "f"}).json()["rows"][0]
    done = client.post("/api/forge/fill-discount-rate", json={"sessionId": "f", "discountRate": 0.05, "apply": True}).json()
    assert done["applied"] is True and done["sheets"] == {"generators": 1}
    assert client.get("/api/session/sheet/generators", params={"session_id": "f"}).json()["rows"][0]["discount_rate"] == 0.05
    assert client.post("/api/forge/fill-discount-rate", json={"sessionId": "f", "discountRate": 5}).status_code == 400
