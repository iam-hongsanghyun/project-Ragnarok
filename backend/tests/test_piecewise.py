"""Piecewise-linear cost / efficiency curves (PyPSA >= 1.3) end to end (P10, P40, P30).

Every parity test builds the SAME problem twice - once natively through
``pypsa.Network.add(..., marginal_cost={x: y})`` and once through Ragnarok's
workbook sheet ``<list>-<attr>-pw`` + ``build_network`` - and compares the
optimum. Tolerances are explicit: objective ``rtol=1e-9``, dispatch ``atol=1e-6``.
"""
from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pypsa
import pytest
from fastapi import HTTPException

from backend.app.pypsa_schema_builder import build_pypsa_schema
from backend.app.project_workbook import bundle_to_workbook, workbook_to_bundle
from backend.pypsa.network import build_network
from backend.pypsa.network.piecewise import (
    curve_shape,
    network_piecewise_rows,
    parse_piecewise_options,
    parse_piecewise_sheet_name,
    piecewise_catalog,
    piecewise_sheet_name,
)
from backend.pypsa.network.serialize import network_to_model
from backend.pypsa.optimise_options import parse_optimise_options
from backend.pypsa.results import run_pypsa

warnings.filterwarnings("ignore")
logging.disable(logging.WARNING)

LOAD = [50.0, 60.0, 80.0, 90.0]
SNAPS = [f"2030-01-01T{h:02d}:00:00" for h in range(len(LOAD))]
OBJ_RTOL = 1e-9
P_ATOL = 1e-6


def _solve(n: pypsa.Network, **kw: Any) -> float:
    status, cond = n.optimize(solver_name="highs", include_objective_constant=False, **kw)
    assert (status, cond) == ("ok", "optimal")
    return float(n.objective)


def _native(curve: dict[float, float] | None, *, h_cost: float = 35.0) -> pypsa.Network:
    n = pypsa.Network()
    n.set_snapshots(pd.to_datetime(SNAPS))
    n.add("Bus", "n1")
    n.add("Carrier", "gas")
    n.add("Load", "L", bus="n1", p_set=LOAD)
    n.add("Generator", "g", bus="n1", carrier="gas", p_nom=100, **({"marginal_cost": curve} if curve else {}))
    n.add("Generator", "h", bus="n1", carrier="gas", p_nom=100, marginal_cost=h_cost)
    return n


def _model(curve: dict[float, float], *, h_cost: float = 35.0) -> dict[str, Any]:
    return {
        "snapshots": [{"snapshot": s} for s in SNAPS],
        "buses": [{"name": "n1"}],
        "carriers": [{"name": "gas", "co2_emissions": 0.0}],
        "generators": [
            {"name": "g", "bus": "n1", "carrier": "gas", "p_nom": 100},
            {"name": "h", "bus": "n1", "carrier": "gas", "p_nom": 100, "marginal_cost": h_cost},
        ],
        "loads": [{"name": "L", "bus": "n1"}],
        "loads-p_set": [{"snapshot": s, "L": v} for s, v in zip(SNAPS, LOAD)],
        "generators-marginal_cost-pw": [
            {"name": "g", "p_pu": x, "marginal_cost": y} for x, y in curve.items()
        ],
    }


CONVEX = {0.0: 0.0, 0.5: 10.0, 1.0: 40.0}  # cost 10 up to 50 MW, then 40
NONCONVEX = {0.0: 0.0, 0.5: 40.0, 1.0: 10.0}  # economies of scale: 40 then 10


# ── Parity vs native n.optimize() ─────────────────────────────────────────────


@pytest.mark.parametrize("curve", [CONVEX, NONCONVEX], ids=["convex-LP", "nonconvex-MIP"])
def test_parity_with_native_optimize(curve: dict[float, float]) -> None:
    nat = _native(curve)
    obj_nat = _solve(nat)
    rag, _ = build_network(_model(curve), {}, {})
    obj_rag = _solve(rag)
    assert obj_rag == pytest.approx(obj_nat, rel=OBJ_RTOL)
    np.testing.assert_allclose(
        rag.generators_t.p.to_numpy(), nat.generators_t.p.to_numpy(), atol=P_ATOL
    )
    # The silent-drop regression: with the curve lost the LP sees g as free.
    assert obj_rag > 0.0
    assert rag.c.generators.has_piecewise("marginal_cost")


def test_known_optima_are_the_hand_computed_values() -> None:
    """Independent of PyPSA: closed-form optimum of both cases."""
    # Convex: g takes min(load, 50) at 10 and the rest (up to 100) at 40 vs h at 35 -> h.
    convex = 4 * 50 * 10 + sum(max(0, d - 50) for d in LOAD) * 35
    rag, _ = build_network(_model(CONVEX), {}, {})
    assert _solve(rag) == pytest.approx(convex, rel=OBJ_RTOL)  # 2000 + 2800 = 4800
    assert convex == 4800.0
    # Non-convex: g either off, or on at >=? 40 for 50 then 10 -> 8550 is the MIP optimum.
    rag2, _ = build_network(_model(NONCONVEX), {}, {})
    assert _solve(rag2) == pytest.approx(8550.0, rel=OBJ_RTOL)


def test_nonconvex_needs_a_mip_and_convex_does_not() -> None:
    assert curve_shape("cost", [0, 0.5, 1], [0, 10, 40]) == "convex"
    assert curve_shape("cost", [0, 0.5, 1], [0, 40, 10]) == "nonconvex"
    assert curve_shape("cost", [0, 0.5, 1], [0, 20, 20]) == "linear"
    assert curve_shape("efficiency", [0, 0.5, 1], [0, 0.4, 0.4]) == "linear"
    assert curve_shape("efficiency", [0, 0.5, 1], [0, 0.3, 0.45]) == "nonconvex"
    _, notes = build_network(_model(NONCONVEX), {}, {})
    assert any("non-convex" in n and "MIP" in n for n in notes)


def test_piecewise_options_sos2_runs_on_highs() -> None:
    """``method: sos2`` needs linopy's SOS reformulation on HiGHS (no native SOS2)."""
    oo = parse_optimise_options(
        {"piecewiseOptions": [{"component": "Generator", "attribute": "marginal_cost", "method": "sos2"}]}
    )
    kw = oo.optimize_kwargs()
    assert kw["piecewise_options"][0]["method"] == "sos2"
    assert kw["piecewise_options"][0]["sign"] == ">="
    assert kw["reformulate_sos"] == "auto"
    rag, _ = build_network(_model(NONCONVEX), {}, {})
    assert _solve(rag, **kw) == pytest.approx(8550.0, rel=OBJ_RTOL)
    # and without any override the kwargs stay absent (bare solves unchanged)
    assert "piecewise_options" not in parse_optimise_options({}).optimize_kwargs()


def test_piecewise_options_validation() -> None:
    assert parse_piecewise_options(None) == ()
    with pytest.raises(HTTPException) as bad:
        parse_piecewise_options([{"component": "Generator", "attribute": "p_nom"}])
    assert bad.value.status_code == 400 and "no piecewise curve" in bad.value.detail
    with pytest.raises(HTTPException):
        parse_piecewise_options([{"component": "Generator", "attribute": "marginal_cost", "method": "magic"}])
    out = parse_piecewise_options({"component": "Link", "attribute": "efficiency2", "name": "l1"})
    assert out[0]["sign"] == "=" and out[0]["name"] == ("l1",)


# ── Capital cost curve (annuitised exactly like the scalar capital_cost) ───────


def test_capital_cost_curve_is_annuitised_like_the_scalar() -> None:
    rate, life, hours = 0.05, 20.0, float(len(LOAD))
    af = rate / (1 - (1 + rate) ** -life)
    scale = af * hours / 8760.0
    overnight = {0.0: 0.0, 50.0: 1.0e6, 200.0: 1.0e7}  # per-MW price on each segment

    nat = pypsa.Network()
    nat.set_snapshots(pd.to_datetime(SNAPS))
    nat.add("Bus", "n1")
    nat.add("Carrier", "gas")
    nat.add("Load", "L", bus="n1", p_set=[80.0] * len(LOAD))
    nat.add("Generator", "peak", bus="n1", carrier="gas", p_nom=200, marginal_cost=100)
    nat.add(
        "Generator", "g", bus="n1", carrier="gas", p_nom_extendable=True, p_nom_max=200,
        capital_cost={x: y * scale for x, y in overnight.items()},
    )
    obj_nat = _solve(nat)

    model = _model(CONVEX)
    model["generators"] = [
        {"name": "peak", "bus": "n1", "carrier": "gas", "p_nom": 200, "marginal_cost": 100},
        {"name": "g", "bus": "n1", "carrier": "gas", "p_nom_extendable": True, "p_nom_max": 200,
         "lifetime": life},
    ]
    model["loads-p_set"] = [{"snapshot": s, "L": 80.0} for s in SNAPS]
    del model["generators-marginal_cost-pw"]
    model["generators-capital_cost-pw"] = [
        {"name": "g", "p_nom": x, "capital_cost": y} for x, y in overnight.items()
    ]
    rag, _ = build_network(model, {"discountRate": rate}, {})
    obj_rag = _solve(rag)
    assert obj_rag == pytest.approx(obj_nat, rel=OBJ_RTOL)
    assert rag.generators.at["g", "p_nom_opt"] == pytest.approx(nat.generators.at["g", "p_nom_opt"], abs=P_ATOL)
    assert obj_rag > 0.0
    # sanity: pw y was scaled by AF x window, not left overnight
    y1 = rag.c.generators.piecewise["capital_cost"][("g", "capital_cost")].iloc[1]
    assert y1 == pytest.approx(1.0e6 * scale, rel=1e-12)


# ── Link efficiency curve + extendable / validation errors ─────────────────────


def test_link_efficiency_curve_parity() -> None:
    eff = {0.0: 0.0, 0.5: 0.9, 1.0: 0.6}  # non-linear conversion -> MIP

    def base(n: pypsa.Network) -> None:
        n.set_snapshots(pd.to_datetime(SNAPS))
        n.add("Bus", ["a", "b"])
        n.add("Carrier", "gas")
        n.add("Load", "L", bus="b", p_set=[30.0, 40.0, 50.0, 60.0])
        n.add("Generator", "src", bus="a", carrier="gas", p_nom=500, marginal_cost=10)
        n.add("Generator", "alt", bus="b", carrier="gas", p_nom=500, marginal_cost=60)

    nat = pypsa.Network()
    base(nat)
    nat.add("Link", "l", bus0="a", bus1="b", p_nom=100, efficiency=eff)
    obj_nat = _solve(nat)

    model = network_to_model(_native_without_link(base))
    model["links"] = [{"name": "l", "bus0": "a", "bus1": "b", "p_nom": 100}]
    model["links-efficiency-pw"] = [{"name": "l", "p_pu": x, "efficiency": y} for x, y in eff.items()]
    rag, _ = build_network(model, {}, {})
    assert _solve(rag) == pytest.approx(obj_nat, rel=OBJ_RTOL)
    np.testing.assert_allclose(rag.links_t.p1.to_numpy(), nat.links_t.p1.to_numpy(), atol=P_ATOL)


def _native_without_link(base: Any) -> pypsa.Network:
    n = pypsa.Network()
    base(n)
    return n


def test_extendable_component_with_a_per_unit_curve_is_a_clear_400() -> None:
    model = _model(CONVEX)
    model["generators"][0]["p_nom_extendable"] = True
    with pytest.raises(HTTPException) as exc:
        build_network(model, {"discountRate": 0.05}, {})
    assert exc.value.status_code == 400
    assert "generators-marginal_cost-pw" in exc.value.detail and "extendable" in exc.value.detail


@pytest.mark.parametrize(
    "rows, needle",
    [
        ([{"name": "g", "p_pu": 0, "marginal_cost": 0}], "at least 2 breakpoints"),
        (
            [{"name": "g", "p_pu": 0, "marginal_cost": 0}, {"name": "g", "p_pu": 0, "marginal_cost": 5},
             {"name": "g", "p_pu": 1, "marginal_cost": 9}],
            "duplicate",
        ),
        ([{"name": "g", "p_pu": 0.2, "marginal_cost": 0}, {"name": "g", "p_pu": 1, "marginal_cost": 9}], "start at p_pu=0"),
        ([{"name": "g", "p_pu": 0, "marginal_cost": 0}, {"name": "g", "p_pu": 0.8, "marginal_cost": 9}], "end at p_pu=1"),
        ([{"name": "g", "p_pu": 0, "marginal_cost": 0}, {"name": "g", "p_pu": "abc", "marginal_cost": 9}], "non-numeric"),
    ],
)
def test_bad_curves_are_rejected_with_the_sheet_name(rows: list[dict[str, Any]], needle: str) -> None:
    model = _model(CONVEX)
    model["generators-marginal_cost-pw"] = rows
    with pytest.raises(HTTPException) as exc:
        build_network(model, {}, {})
    assert exc.value.status_code == 400
    assert "generators-marginal_cost-pw" in exc.value.detail and needle in exc.value.detail


def test_unknown_component_rows_are_dropped_with_a_note() -> None:
    model = _model(CONVEX)
    model["generators-marginal_cost-pw"] += [
        {"name": "ghost", "p_pu": 0, "marginal_cost": 0},
        {"name": "ghost", "p_pu": 1, "marginal_cost": 5},
    ]
    net, notes = build_network(model, {}, {})
    assert any("ghost" in n for n in notes)
    assert list(net.c.generators.piecewise["marginal_cost"].columns.unique("name")) == ["g"]


def test_carbon_price_is_added_to_every_segment_of_an_emitting_curve() -> None:
    model = _model(CONVEX)
    model["carriers"] = [{"name": "gas", "co2_emissions": 0.2}]
    price = 50.0  # adder = 50 * 0.2 / eta(=1) = 10 per MWh on every segment
    rag, _ = build_network(model, {"carbonPrice": price}, {})
    ys = rag.c.generators.piecewise["marginal_cost"][("g", "marginal_cost")].tolist()
    assert ys == [0.0, 20.0, 50.0]  # y_0 (ignored by PyPSA) untouched
    # parity with a native network carrying the already-adjusted curve + h at 35+10
    nat = _native({0.0: 0.0, 0.5: 20.0, 1.0: 50.0}, h_cost=45.0)
    assert _solve(rag) == pytest.approx(_solve(nat), rel=OBJ_RTOL)


def test_carbon_schedule_that_varies_cannot_be_applied_to_a_curve() -> None:
    model = _model(CONVEX)
    model["carriers"] = [{"name": "gas", "co2_emissions": 0.2}]
    opts = {"carbonPriceSchedule": [{"year": 2020, "price": 10}, {"year": 2030, "price": 80}]}
    # constant within the 2030 snapshots -> allowed; a within-run change is refused
    build_network(model, {"carbonPrice": 0}, opts)
    model["snapshots"] = [{"snapshot": "2020-06-01T00:00:00"}, {"snapshot": "2031-06-01T00:00:00"}]
    model["loads-p_set"] = [{"snapshot": "2020-06-01T00:00:00", "L": 10}, {"snapshot": "2031-06-01T00:00:00", "L": 10}]
    with pytest.raises(HTTPException) as exc:
        build_network(model, {"carbonPrice": 0}, opts)
    assert "piecewise" in exc.value.detail


# ── Results: *_piecewise_opt shown, breakdown matches the objective ───────────


@pytest.mark.parametrize("curve", [CONVEX, NONCONVEX], ids=["convex", "nonconvex"])
def test_cost_breakdown_sums_to_the_objective(curve: dict[float, float]) -> None:
    res = run_pypsa(_model(curve), {"carbonPrice": 0}, {})
    nat = _native(curve)
    obj = _solve(nat)
    total = sum(r["value"] for r in res["costBreakdown"])
    assert total == pytest.approx(obj, abs=1.0)  # breakdown rows are rounded to whole currency
    labels = {r["label"]: r["value"] for r in res["costBreakdown"]}
    assert labels["Fuel cost"] == pytest.approx(obj, abs=1.0)  # curve cost reported as fuel, not "stand-by"
    assert "Quadratic / stand-by cost" not in labels


def test_results_expose_the_curve_and_its_piecewise_opt() -> None:
    res = run_pypsa(_model(CONVEX), {"carbonPrice": 0}, {})
    pw = res["piecewise"]
    assert pw is not None
    (curve,) = pw["curves"]
    assert (curve["component"], curve["name"], curve["attribute"], curve["shape"]) == (
        "Generator", "g", "marginal_cost", "convex",
    )
    assert curve["breakpoints"] == [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 10.0}, {"x": 1.0, "y": 40.0}]
    solved = curve["solved"]
    # g runs flat at 50 MW (all on the 10/MWh segment): average == 10, cost 4 x 500
    assert solved["averagePerMWh"] == pytest.approx(10.0, abs=1e-6)
    assert solved["operatingCost"] == pytest.approx(2000.0, abs=1e-6)
    assert pw["totalOperatingCost"] == pytest.approx(2000.0, abs=1e-6)
    # the raw output reaches full_outputs under PyPSA's own name
    assert "generators-marginal_cost_piecewise_opt" in res["outputs"]["series"]


def test_no_curves_means_no_piecewise_block() -> None:
    model = _model(CONVEX)
    del model["generators-marginal_cost-pw"]
    assert run_pypsa(model, {"carbonPrice": 0}, {})["piecewise"] is None


# ── I/O round trips (P40) ─────────────────────────────────────────────────────


def _rows(model: dict[str, Any], sheet: str) -> list[tuple[str, float, float]]:
    attr = parse_piecewise_sheet_name(sheet)[1]
    x = "p_pu"
    return sorted((r["name"], float(r[x]), float(r[attr])) for r in model[sheet])


@pytest.mark.parametrize("fmt", ["netcdf", "hdf5", "csv"])
def test_native_file_round_trip_keeps_the_curve(tmp_path: Path, fmt: str) -> None:
    if fmt == "hdf5":
        pytest.importorskip("tables")
    sheet = piecewise_sheet_name("generators", "marginal_cost")
    net, _ = build_network(_model(NONCONVEX), {}, {})
    path = tmp_path / ("net.nc" if fmt == "netcdf" else "net.h5" if fmt == "hdf5" else "csvdir")
    {"netcdf": net.export_to_netcdf, "hdf5": net.export_to_hdf5, "csv": net.export_to_csv_folder}[fmt](str(path))
    back = pypsa.Network(str(path)) if fmt != "csv" else pypsa.Network(str(path))
    model = network_to_model(back)
    assert sheet in model, f"{fmt} import dropped the piecewise sheet"
    assert _rows(model, sheet) == _rows(_model(NONCONVEX), sheet)
    rebuilt, _ = build_network(model, {}, {})
    assert _solve(rebuilt) == pytest.approx(8550.0, rel=OBJ_RTOL)


def test_network_to_model_emits_long_rows_with_breakpoint_index() -> None:
    net, _ = build_network(_model(CONVEX), {}, {})
    rows = network_piecewise_rows(net)["generators-marginal_cost-pw"]
    assert rows == [
        {"name": "g", "breakpoint": 0, "p_pu": 0.0, "marginal_cost": 0.0},
        {"name": "g", "breakpoint": 1, "p_pu": 0.5, "marginal_cost": 10.0},
        {"name": "g", "breakpoint": 2, "p_pu": 1.0, "marginal_cost": 40.0},
    ]


def test_project_workbook_round_trip_keeps_the_curve() -> None:
    sheet = "generators-marginal_cost-pw"
    model = _model(NONCONVEX)
    xlsx = bundle_to_workbook({"model": model, "result": {}})
    bundle = workbook_to_bundle(xlsx, "p.xlsx")
    assert sheet in bundle["model"]
    assert _rows(bundle["model"], sheet) == _rows(model, sheet)
    rebuilt, _ = build_network(bundle["model"], {}, {})
    assert _solve(rebuilt) == pytest.approx(8550.0, rel=OBJ_RTOL)


def test_long_sheet_names_survive_excels_31_char_limit() -> None:
    for row in piecewise_catalog():
        assert len(row["sheet"]) <= 31, row["sheet"]  # no SheetNames indirection needed


# ── Schema ─────────────────────────────────────────────────────────────────────


def test_schema_publishes_the_curves_each_component_accepts() -> None:
    comps = build_pypsa_schema()["components"]
    gen = {p["attribute"]: p for p in comps["generators"]["piecewise_attributes"]}
    assert gen["marginal_cost"]["x"] == "p_pu" and gen["marginal_cost"]["allow_extendable"] is False
    assert gen["capital_cost"]["x"] == "p_nom" and gen["capital_cost"]["allow_extendable"] is True
    assert gen["marginal_cost"]["sheet"] == "generators-marginal_cost-pw"
    assert {p["attribute"] for p in comps["storage_units"]["piecewise_attributes"]} == {"marginal_cost", "capital_cost"}
    assert comps["buses"]["piecewise_attributes"] == []
    assert any(a["attribute"] == "marginal_cost" and a["piecewise"] for a in comps["generators"]["attributes"])


# ── Session store: a `-pw` sheet is static, not a snapshot-indexed series ──────


def test_session_store_keeps_pw_sheets_static(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app import model_store, session_store

    monkeypatch.setattr(session_store, "SESSION_DIR", tmp_path / "session")
    sheet = "generators-marginal_cost-pw"
    assert model_store.is_series_sheet("generators-p_max_pu") is True
    assert model_store.is_series_sheet(sheet) is False
    model_store.save_model("default", _model(NONCONVEX), filename="case.xlsx")
    # visible to the thin editor (static-only load) with every cell intact
    static = model_store.load_full_model("default", static_only=True)
    assert _rows(static, sheet) == _rows(_model(NONCONVEX), sheet)
    page = model_store.get_sheet_page("default", sheet, offset=0, limit=100)
    assert page is not None and len(page["rows"]) == 3
    # a row edit goes through the generic sheet patch (what the MCP tools use)
    model_store.patch_sheet("default", sheet, [{"op": "addRow", "values": {"name": "g2", "p_pu": 0.0, "marginal_cost": 0.0}}])
    assert len(model_store.get_sheet_page("default", sheet, offset=0, limit=100)["rows"]) == 4


@pytest.mark.parametrize("method", ["auto", "incremental", "sos2"])
def test_run_pypsa_honours_the_piecewise_run_option(method: str) -> None:
    opts = {"piecewiseOptions": [{"component": "Generator", "attribute": "marginal_cost", "method": method}]}
    res = run_pypsa(_model(NONCONVEX), {"carbonPrice": 0}, opts)
    assert sum(r["value"] for r in res["costBreakdown"]) == pytest.approx(8550.0, abs=1.0)
    assert res["optimiseOptions"]["piecewise_options"][0]["method"] == method


@pytest.mark.parametrize(
    "cls, kw, sheet",
    [
        ("Link", dict(name="l", bus0="a", bus1="b", p_nom=100, marginal_cost={0: 0, 0.5: 5, 1.0: 30}),
         "links-marginal_cost-pw"),
        ("Process", dict(name="p", bus0="a", bus1="b", p_nom=100, rate0=-1, rate1={0: 0, 0.5: 0.9, 1.0: 0.6}),
         "processes-rate1-pw"),
    ],
    ids=["link-marginal_cost", "process-rate1"],
)
def test_other_components_round_trip_through_the_sheet_and_match_native(cls: str, kw: dict, sheet: str) -> None:
    """Native -> workbook model (``network_to_model``) -> ``build_network`` reproduces the optimum."""
    nat = pypsa.Network()
    nat.set_snapshots(pd.to_datetime(SNAPS))
    nat.add("Bus", ["a", "b"])
    nat.add("Carrier", "gas")
    nat.add("Load", "L", bus="b", p_set=[30.0, 40.0, 50.0, 60.0])
    nat.add("Generator", "src", bus="a", carrier="gas", p_nom=500, marginal_cost=10)
    nat.add("Generator", "alt", bus="b", carrier="gas", p_nom=500, marginal_cost=60)
    nat.add(cls, **kw)
    obj_nat = _solve(nat)
    model = network_to_model(nat)
    assert sheet in model
    rag, _ = build_network(model, {}, {})
    assert _solve(rag) == pytest.approx(obj_nat, rel=OBJ_RTOL)
